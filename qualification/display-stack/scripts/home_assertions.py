#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""dsq-2 — what the Bunny configuration directory actually is, read offline.

The journal can say that bunny-first-boot.service succeeded. It cannot say
that the directory it wrote into is a directory, owned by the user who logged
in, mode 0700, not a symlink, and carrying the expected SELinux context. Those
are properties of the filesystem, so they are read from the filesystem — from
the run's own overlay, mounted read-only after the guest has powered down.

Reading them offline rather than from inside the guest matters: an in-guest
check would run as the account under test, through the same user session whose
correctness is the question, and would be reported by the same journal that is
already the subject of the assertion.

Every assertion returns a value or an explicit reason it could not be taken.
An unreadable path is never rendered as a passing check.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess

#: The directories bunny-first-boot.service declares as ReadWritePaths=,
#: relative to the account's home. Kept in step with the unit by
#: tests/first_login/test_corrections.py.
REQUIRED_DIRECTORIES = (".config/bunny-os", ".config/systemd/user")

#: The marker bunny-first-boot writes when it completes.
COMPLETION_MARKER = ".config/bunny-os/first-boot-complete.json"

#: What SELinux gives a file created under a user's home on this image. The
#: dsq-1 pass established that the installed policy labels home content
#: config_home_t or user_home_t depending on path; both are accepted and the
#: measured value is always recorded, so a policy change shows up as a changed
#: fact rather than as a silent pass.
EXPECTED_HOME_CONTEXTS = ("config_home_t", "user_home_t", "gconf_home_t")


class HomeReadError(Exception):
    pass


def _guestfish(overlay: Path, root: str, *commands: list[str]) -> str:
    argv = ["guestfish", "--ro", "-a", str(overlay), "run", ":",
            "mount-ro", root, "/"]
    for command in commands:
        argv += [":", *command]
    result = subprocess.run(argv, capture_output=True, text=True, timeout=900)
    if result.returncode != 0:
        raise HomeReadError(result.stderr.strip()[:400])
    return result.stdout


def _stat_fields(overlay: Path, root: str, path: str) -> dict | None:
    """lstat of one path, or None when it does not exist.

    `lstatlist` is used rather than `stat` so a symlink reports itself instead
    of reporting whatever it points at — the distinction the whole assertion
    exists for.
    """
    parent, _, name = path.rpartition("/")
    try:
        out = _guestfish(overlay, root,
                         ["lstatlist", parent or "/", name])
    except HomeReadError:
        return None
    fields: dict[str, int] = {}
    for line in out.splitlines():
        match = re.match(r"^(\w+):\s*(-?\d+)$", line.strip())
        if match:
            fields[match.group(1)] = int(match.group(2))
    return fields or None


def _selinux_context(overlay: Path, root: str, path: str) -> str | None:
    try:
        out = _guestfish(overlay, root, ["getxattr", path,
                                         "security.selinux"])
    except HomeReadError:
        return None
    text = out.strip().replace("\x00", "")
    return text or None


def _file_type(mode: int) -> str:
    kind = mode & 0o170000
    return {0o040000: "directory", 0o100000: "regular-file",
            0o120000: "symlink", 0o060000: "block-device",
            0o020000: "character-device", 0o010000: "fifo",
            0o140000: "socket"}.get(kind, f"unknown-{kind:o}")


def assert_home(overlay: Path, root: str, home: str, uid: int,
                gid: int, reported_as: str | None = None) -> dict:
    """Every filesystem fact dsq-2 needs about one account's home.

    `home` is the path on the offline image; `reported_as` is the path the
    guest resolves. They differ on an ostree system, where the running /var is
    the stateroot's and there is no /var at the disk root at all. Reading one
    and reporting the other keeps the record a statement about the running
    system while the lookup goes where the bytes are.
    """
    shown = reported_as or home
    result: dict = {"home": shown, "homeOnDisk": home,
                    "expectedUid": uid, "expectedGid": gid,
                    "directories": {}, "problems": []}

    home_stat = _stat_fields(overlay, root, home)
    if home_stat is None:
        result["problems"].append(
            f"{shown}: the home directory does not exist in the overlay "
            f"(looked at {home}); no first login can have happened")
        result["homeExists"] = False
        return result
    result["homeExists"] = True

    for relative in REQUIRED_DIRECTORIES:
        path = f"{home}/{relative}"
        reported = f"{shown}/{relative}"
        entry: dict = {"path": reported, "pathOnDisk": path}
        stat_fields = _stat_fields(overlay, root, path)
        if stat_fields is None:
            entry["present"] = False
            entry["type"] = None
            result["problems"].append(
                f"{reported}: absent after a first login. This is the state that "
                "failed mount-namespace setup with 226/NAMESPACE on every "
                "dsq-1 boot")
            result["directories"][relative] = entry
            continue

        mode = stat_fields.get("st_mode", 0)
        entry["present"] = True
        entry["type"] = _file_type(mode)
        entry["mode"] = mode & 0o7777
        entry["uid"] = stat_fields.get("st_uid")
        entry["gid"] = stat_fields.get("st_gid")
        entry["inode"] = stat_fields.get("st_ino")
        entry["selinuxContext"] = _selinux_context(overlay, root, path)

        if entry["type"] == "symlink":
            result["problems"].append(
                f"{reported}: is a symbolic link. The correction refuses a link "
                "here rather than following it; a link present after a run "
                "means something else created it")
        elif entry["type"] != "directory":
            result["problems"].append(
                f"{reported}: is a {entry['type']}, not a directory")
        if entry["uid"] != uid:
            result["problems"].append(
                f"{reported}: owned by uid {entry['uid']}, expected {uid} — the "
                "account that logged in")
        if entry["gid"] != gid:
            result["problems"].append(
                f"{reported}: group {entry['gid']}, expected {gid} — the "
                "account's primary group")
        if entry["mode"] != 0o700:
            result["problems"].append(
                f"{reported}: mode {entry['mode']:04o}, expected 0700")
        if entry["mode"] & 0o077:
            result["problems"].append(
                f"{reported}: mode {entry['mode']:04o} grants access outside the "
                "owning user")
        context = entry["selinuxContext"]
        if context is None:
            result["problems"].append(
                f"{reported}: carries no SELinux context; the image is labelled "
                "and a home directory without a label is not an expected "
                "state")
        elif not any(expected in context
                     for expected in EXPECTED_HOME_CONTEXTS):
            result["problems"].append(
                f"{reported}: SELinux context {context} is none of the expected "
                f"user configuration types {EXPECTED_HOME_CONTEXTS}")
        result["directories"][relative] = entry

    marker = f"{home}/{COMPLETION_MARKER}"
    marker_reported = f"{shown}/{COMPLETION_MARKER}"
    marker_stat = _stat_fields(overlay, root, marker)
    result["completionMarker"] = {
        "path": marker_reported,
        "pathOnDisk": marker,
        "present": marker_stat is not None,
        "mode": (marker_stat.get("st_mode", 0) & 0o7777) if marker_stat
                else None,
        "uid": marker_stat.get("st_uid") if marker_stat else None,
        "sizeBytes": marker_stat.get("st_size") if marker_stat else None,
    }
    if marker_stat is None:
        result["problems"].append(
            f"{marker_reported}: absent. bunny-first-boot.service writes this when it "
            "completes, so a first login that reports success without it did "
            "not run the flow")
    return result


def read_marker(overlay: Path, root: str, home: str) -> dict | None:
    """The first-run preferences, for the second-login idempotence check."""
    try:
        text = _guestfish(overlay, root,
                          ["cat", f"{home}/{COMPLETION_MARKER}"])
    except HomeReadError:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def compare_logins(first: dict, second: dict) -> dict:
    """Second-login idempotence, stated as what must not have changed.

    A second login must find the flow already complete and leave it alone.
    The inode is compared as well as the content because a directory that was
    removed and recreated with identical content is not a preserved
    directory — and it is the case a content-only check cannot see.
    """
    problems = []
    for relative in REQUIRED_DIRECTORIES:
        before = (first.get("directories") or {}).get(relative) or {}
        after = (second.get("directories") or {}).get(relative) or {}
        if not before.get("present") or not after.get("present"):
            problems.append(f"{relative}: not present on both logins")
            continue
        if before.get("inode") != after.get("inode"):
            problems.append(
                f"{relative}: inode changed {before.get('inode')} -> "
                f"{after.get('inode')}; the directory was replaced, not reused")
        for field in ("uid", "gid", "mode"):
            if before.get(field) != after.get(field):
                problems.append(
                    f"{relative}: {field} changed {before.get(field)} -> "
                    f"{after.get(field)} across logins")
    return {"problems": problems, "idempotent": not problems}
