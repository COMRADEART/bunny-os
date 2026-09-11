#!/usr/bin/python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""User generator: extra ReadWritePaths for a relocated Pictures directory.

``bunny-companion.service`` ships ``ReadWritePaths=-%h/Pictures``. systemd
resolves that when the unit loads, so a user who pointed XDG_PICTURES_DIR
somewhere else still hits EROFS on the trusted copy-out.

This generator reads ``user-dirs.dirs`` (or ``XDG_PICTURES_DIR``) and, when
the resolved path is a different directory still inside the home, writes a
drop-in. It does **not** widen ProtectHome. Paths outside the home, through
a symlink escape, or named like a credential directory are refused.

A portal is still the right long-term export. This is the safe interim.
Runtime evidence that the drop-in was loaded in a graphical session is
NOT_RUN on hosts that do not boot Bunny Shell.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import sys


UNIT = "bunny-companion.service"
FORBIDDEN_COMPONENTS = frozenset({
    ".ssh", ".gnupg", ".pki", ".password-store", ".aws", ".azure", ".config",
    ".local", ".mozilla", ".thunderbird", ".netrc", ".docker", ".kube",
    ".gnome2_private", ".authinfo", ".git-credentials", ".secrets",
})
_ASSIGNMENT = re.compile(
    r'^XDG_PICTURES_DIR=(["\']?)(.+)\1\s*$'
)


def _home() -> Path:
    raw = os.environ.get("HOME") or os.environ.get("BUNNY_GENERATOR_HOME") or ""
    return Path(raw).expanduser() if raw else Path.home()


def _config_dir(home: Path) -> Path:
    configured = os.environ.get("XDG_CONFIG_HOME", "").strip()
    return Path(configured) if configured else home / ".config"


def parse_user_dirs(text: str, home: Path) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _ASSIGNMENT.match(stripped)
        if not match:
            continue
        value = match.group(2).replace("$HOME", str(home))
        return value
    return None


def resolve_pictures(home: Path, config_dir: Path) -> Path | None:
    env = os.environ.get("XDG_PICTURES_DIR", "").strip()
    if env:
        candidate = Path(env)
    else:
        dirs_file = config_dir / "user-dirs.dirs"
        if not dirs_file.is_file():
            return None
        try:
            parsed = parse_user_dirs(dirs_file.read_text(encoding="utf-8"), home)
        except OSError:
            return None
        if not parsed:
            return None
        candidate = Path(parsed)
    resolved = Path(os.path.realpath(str(candidate)))
    home_real = Path(os.path.realpath(str(home)))
    try:
        resolved.relative_to(home_real)
    except ValueError:
        return None
    if resolved == home_real:
        return None
    if any(part in FORBIDDEN_COMPONENTS for part in resolved.parts):
        return None
    default = Path(os.path.realpath(str(home_real / "Pictures")))
    if resolved == default:
        return None
    return resolved


def write_dropin(destination: Path, pictures: Path) -> None:
    directory = destination / f"{UNIT}.d"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "pictures-xdg.conf"
    path.write_text(
        "[Service]\n"
        f"ReadWritePaths=-{pictures}\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        return 0
    dest = Path(args[0])
    home = _home()
    pictures = resolve_pictures(home, _config_dir(home))
    if pictures is None:
        return 0
    try:
        write_dropin(dest, pictures)
    except OSError:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
