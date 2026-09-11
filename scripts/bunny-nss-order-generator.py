#!/usr/bin/python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""System generator: nss-user-lookup ordering for altfiles-backed User=.

chronyd was the one measured 217/USER failure. The class is wider: any unit
whose User=/Group= resolves through /usr/lib/passwd during the authselect
rewrite window. This generator scans the *installed* systemd tree at boot and
writes the same drop-in pattern chronyd already ships, for units that lack it.

It does not invent guest-boot evidence. On a host without Fedora's
/usr/lib/passwd it writes nothing and exits 0 (NOT_RUN). A booted Bunny OS
image is what proves the overlay landed; run ``nss_account_sweep.py`` there.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys


DROPIN = """\
[Unit]
# Written by bunny-nss-order-generator. Same contract as
# systemd/chronyd.service.d/50-bunny-nss-order.conf: pull in the passive
# identity-settled target, order after it and after authselect's rewrite.
# authselect is conditional, so this overlay never hard-depends on it.
# The consuming unit waits; it does not become a reverse-order peer.
Wants=nss-user-lookup.target
After=nss-user-lookup.target
After=authselect-apply-changes.service
"""


def _root() -> Path:
    configured = os.environ.get("BUNNY_NSS_ROOT", "").strip()
    return Path(configured) if configured else Path("/")


def _passwd_names(path: Path) -> frozenset[str]:
    names: set[str] = set()
    if not path.is_file():
        return frozenset()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return frozenset()
    for line in text.splitlines():
        if not line or line.startswith("#") or ":" not in line:
            continue
        name = line.split(":", 1)[0].strip()
        if name:
            names.add(name)
    return frozenset(names)


def _directives(path: Path) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return found
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith(";"):
            continue
        if "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        found.setdefault(key.strip(), []).append(value.strip())
    return found


def _identity(path: Path) -> tuple[str | None, str | None]:
    directives = _directives(path)
    users = directives.get("User", [])
    groups = directives.get("Group", [])
    user = users[-1] if users else None
    group = groups[-1] if groups else None
    return user, group


def _classify(name: str | None, etc: frozenset[str], alt: frozenset[str]) -> str:
    if name is None or not name.strip():
        return "none"
    stripped = name.strip()
    if stripped.lstrip("-").isdigit():
        return "numeric"
    if stripped in etc:
        return "etc"
    if stripped in alt:
        return "altfiles"
    return "unknown"


def _ordering_present(system_dir: Path, unit_name: str) -> bool:
    paths = [system_dir / unit_name]
    dropin = system_dir / f"{unit_name}.d"
    if dropin.is_dir():
        paths.extend(sorted(dropin.glob("*.conf")))
    wants: list[str] = []
    after: list[str] = []
    before: list[str] = []
    requires: list[str] = []
    for path in paths:
        directives = _directives(path)
        wants.extend(" ".join(directives.get("Wants", [])).split())
        after.extend(" ".join(directives.get("After", [])).split())
        before.extend(" ".join(directives.get("Before", [])).split())
        requires.extend(" ".join(directives.get("Requires", [])).split())
    if "nss-user-lookup.target" not in wants:
        return False
    if "nss-user-lookup.target" not in after:
        return False
    if "authselect-apply-changes.service" not in after:
        return False
    if "authselect-apply-changes.service" in requires:
        return False
    if before:
        return False
    return True


def units_needing_dropin(root: Path) -> list[str]:
    system_dir = root / "usr/lib/systemd/system"
    if not system_dir.is_dir():
        return []
    etc = _passwd_names(root / "etc/passwd")
    alt = _passwd_names(root / "usr/lib/passwd")
    if not alt:
        return []
    needed: list[str] = []
    for path in sorted(system_dir.glob("*.service")):
        user, group = _identity(path)
        if user is None and group is None:
            continue
        at_risk = (
            _classify(user, etc, alt) == "altfiles"
            or _classify(group, etc, alt) == "altfiles"
        )
        if not at_risk:
            continue
        if _ordering_present(system_dir, path.name):
            continue
        needed.append(path.name)
    return needed


def write_dropins(destination: Path, units: list[str]) -> None:
    for name in units:
        directory = destination / f"{name}.d"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "50-bunny-nss-order.conf").write_text(DROPIN, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        return 0
    dest = Path(args[0])
    try:
        dest.mkdir(parents=True, exist_ok=True)
        write_dropins(dest, units_needing_dropin(_root()))
    except OSError:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
