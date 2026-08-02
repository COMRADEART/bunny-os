#!/usr/bin/python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Establish and verify the per-user directories bunny-first-boot sandboxes.

bunny-first-boot.service runs under `ProtectHome=read-only` and names two
`ReadWritePaths=` inside the user's home. systemd builds that mount namespace
*before* ExecStart, so a named path that does not exist kills the unit with
226/NAMESPACE and the unit's own ExecStart never runs. That is how the unit
failed on 60 of 60 fresh homes: its job was to create state in the directory
whose absence killed it.

`/usr/share/user-tmpfiles.d/bunny-os.conf` creates both paths from the user
manager before basic.target. This program is the assertion that it worked,
and it exists because the tmpfiles outcome was measured and is not
self-announcing:

  * tmpfiles exits 0 when it *refuses* an unsafe path. Given a symlink, a
    dangling symlink or a regular file at the target it logs
    "already exists and is not a directory" and returns success, so
    systemd-tmpfiles-setup.service reports success with the directory absent.
  * tmpfiles exits 0 and leaves ownership alone when the directory exists but
    belongs to another user. In --user mode it cannot chown, so a
    wrong-owner directory is silently accepted.

Both cases would otherwise reach bunny-first-boot.service as an opaque
namespace error or a write failure. Here they become a named refusal.

What this program will not do, because the alternative is worse than the
failure it would paper over:

  * follow a symlink at the target, or replace one;
  * replace a non-directory;
  * take ownership of a directory belonging to another user;
  * touch anything recursively, or anything outside the two named paths.

Exit 0 when both paths are usable, 1 when one is not, naming which and why.
"""

from __future__ import annotations

import os
from pathlib import Path
import stat
import sys

MODE = 0o700

# Exactly the paths bunny-first-boot.service declares as ReadWritePaths=.
# Kept as a literal list so a change to the unit that is not mirrored here is
# caught by tests/first_login/test_first_boot_unit.py rather than by a boot.
RELATIVE_PATHS = (".config/bunny-os", ".config/systemd/user")


class Refusal(Exception):
    """An unsafe or foreign path. Refused, never repaired."""


def home() -> Path:
    # The unit pins XDG_CONFIG_HOME=%h/.config so the sandbox, the tmpfiles
    # rule and bunny-first-boot all resolve to one place; this program is
    # about the sandboxed paths, which are anchored on %h regardless.
    value = os.environ.get("HOME")
    if not value:
        raise Refusal("HOME is unset; the user manager always sets it")
    return Path(value)


def verify_directory(path: Path, uid: int, gid: int) -> str:
    """Return a one-word action taken, or raise Refusal."""
    try:
        link_info = path.lstat()
    except FileNotFoundError:
        create(path, uid)
        return "created"
    except PermissionError as exc:
        raise Refusal(f"{path}: parent directory is not accessible ({exc})")

    if stat.S_ISLNK(link_info.st_mode):
        try:
            target = os.readlink(path)
        except OSError:
            target = "?"
        raise Refusal(
            f"{path}: is a symbolic link to {target!r}. Refused: following it "
            "would place Bunny configuration, and a bind mount writable by "
            "this service, wherever the link points. Remove the link and let "
            "the directory be created.")

    if not stat.S_ISDIR(link_info.st_mode):
        raise Refusal(
            f"{path}: exists and is not a directory "
            f"({stat.filemode(link_info.st_mode)}). Refused rather than "
            "replaced: this program does not delete user data.")

    # Ownership is judged from the lstat, before any open. A directory owned
    # by another user is commonly mode 0700 and cannot be opened by this user
    # at all, so opening first would report a bare "permission denied" and
    # lose the one fact that explains it.
    if link_info.st_uid != uid:
        raise Refusal(
            f"{path}: is owned by uid {link_info.st_uid}, not by uid {uid} "
            "who is logging in. Refused: this service does not take ownership "
            "of another account's directory, and systemd-tmpfiles in --user "
            "mode does not correct it either — it accepts such a directory "
            "silently and reports success, which is why this check exists.")

    # O_NOFOLLOW on an already-verified directory closes the window between
    # the lstat above and the fstat below.
    try:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as exc:
        raise Refusal(f"{path}: cannot be opened as a directory ({exc})")
    try:
        info = os.fstat(fd)
        if info.st_uid != uid:
            raise Refusal(
                f"{path}: changed ownership to uid {info.st_uid} between the "
                f"check and the open. Refused.")
        current = stat.S_IMODE(info.st_mode)
        if current != MODE:
            # Mode is the one property that is safe to correct in place: it
            # is a property of this directory alone, needs no recursion, and
            # a world-readable Bunny configuration directory is a privacy
            # defect on an image whose privacy defaults are all off.
            os.fchmod(fd, MODE)
            return f"mode {current:04o} -> {MODE:04o}"
        return "verified"
    finally:
        os.close(fd)


def create(path: Path, uid: int) -> None:
    parent = path.parent
    if parent != path:
        try:
            parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        except FileExistsError:
            pass
        except PermissionError as exc:
            raise Refusal(f"{parent}: cannot be created ({exc})")
    try:
        os.mkdir(path, MODE)
    except FileExistsError:
        # Raced with the user manager's own tmpfiles run; re-verify rather
        # than assume the winner produced something acceptable.
        return
    except PermissionError as exc:
        raise Refusal(f"{path}: cannot be created ({exc})")
    # mkdir's mode is masked by the umask; set it explicitly.
    os.chmod(path, MODE)


def main() -> int:
    uid, gid = os.getuid(), os.getgid()
    try:
        base = home()
    except Refusal as refusal:
        print(f"bunny-config-dir: {refusal}", file=sys.stderr)
        return 1

    failed = False
    for relative in RELATIVE_PATHS:
        path = base / relative
        try:
            action = verify_directory(path, uid, gid)
        except Refusal as refusal:
            print(f"bunny-config-dir: {refusal}", file=sys.stderr)
            failed = True
            continue
        print(f"bunny-config-dir: {path}: {action}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
