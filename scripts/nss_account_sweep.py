#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Operator-facing NSS account-availability sweep for an installed system.

The race this addresses
=======================

``/etc/nsswitch.conf`` on the fedora-bootc base is a symlink to
``/etc/authselect/nsswitch.conf``. ``authselect-apply-changes.service`` rewrites
that file on first boot, and for the width of the rewrite the ``altfiles``
NSS source is not in effect — so every account provided by
``/usr/lib/passwd`` (the base-image user database) is transiently unresolvable.
Any unit that resolves a ``User=`` satisfied that way, spawning inside the
window, exits ``217/USER`` and does not retry. ``chronyd`` was the unit measured
failing; the mechanism is not chrony-specific.

The fix is ordering at the *consuming* unit, anchored on systemd's
``nss-user-lookup.target`` contract (the passive target systemd documents for
"identity sources are settled"), with ``Wants=`` to pull the passive target
into the transaction and ``After=`` on both the target and
``authselect-apply-changes.service``. No ``Requires=`` (authselect carries
``ConditionPathIsReadWrite=/etc`` — a Requires would turn a timing race into an
availability failure), no ``Before=`` (avoids an ordering cycle).

Why a build-time test is not enough
===================================

The build-time test in ``tests/first_login/test_nss_account_sweep.py`` scans
*repo-shipped* units only. It cannot see the base-image units the repo layers
on top of: ``quay.io/fedora/fedora-bootc:44`` contributes its own
``/usr/lib/systemd/system/*.service`` files, and the repo does not enumerate
them at build time. A base-image unit that resolves an altfiles-backed
``User=`` and lacks the ordering drop-in is at risk on every first boot, and
no build-time check the repo owns can catch it.

This script is the runtime complement. Given an installed system root (or a
mounted image), it scans that system's ``/usr/lib/systemd/system/*.service``
for ``User=``/``Group=`` identities that resolve through ``/usr/lib/passwd``
and reports which ones do not carry the ``nss-user-lookup.target`` ordering
drop-in. An operator runs it on a booted system, or against a mounted image
via ``--root``.

Honesty
=======

This script reports the absence of the ordering drop-in. It does **not** claim
that a listed unit will fail: the race is a window, and whether a given unit
spawns inside it depends on boot ordering the script does not simulate. A unit
listed here is *exposed*; proving it is *safe* needs boot evidence, not this
scan. Conversely, a unit the script does not list may still fail for reasons
unrelated to the altfiles window.

Usage
=====

    nss_account_sweep.py                 # scan the running system (root=/)
    nss_account_sweep.py --root /mnt     # scan a mounted image
    nss_account_sweep.py --json          # machine-readable output

Exit codes: 0 if no at-risk unit lacks the ordering, 2 if any does, 1 on a
usage or read error. The classifier and scanner are importable so the test
suite can exercise them without argv.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Sequence

# A valid passwd user/group name per shadow(5): [A-Za-z_][A-Za-z0-9_-]*
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")


@dataclass(frozen=True)
class UnitIdentity:
    """The ``User=``/``Group=`` declared by one unit, plus its location."""

    unit_path: Path
    unit_name: str  # foo.service, without the directory
    user: str | None
    group: str | None


@dataclass(frozen=True)
class AtRiskUnit:
    """A unit whose ``User=``/``Group=`` resolves through altfiles and which
    lacks the nss-user-lookup.target ordering drop-in."""

    unit_name: str
    user: str | None
    group: str | None
    reason: str
    dropin_dir: Path
    dropin_exists: bool


@dataclass
class SweepReport:
    at_risk: list[AtRiskUnit] = field(default_factory=list)
    scanned: int = 0
    with_identity: int = 0
    altfiles_backed: int = 0
    unknown_identity: list[UnitIdentity] = field(default_factory=list)
    etc_passwd_path: Path | None = None
    usr_lib_passwd_path: Path | None = None

    @property
    def passed(self) -> bool:
        return not self.at_risk


def read_passwd_names(path: Path) -> set[str]:
    """The account names in a passwd file, first colon-delimited field.

    Returns an empty set if the file is absent; the caller decides whether that
    is fatal. Numeric leads and blank lines are ignored.
    """
    if not path.is_file():
        return set()
    names: set[str] = set()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        name = line.split(":", 1)[0]
        if name and _NAME.match(name):
            names.add(name)
    return names


def classify_runtime(identity: str | None,
                     etc_names: Sequence[str],
                     usr_lib_names: Sequence[str]) -> str:
    """Classify a ``User=``/``Group=`` identity for the runtime sweep.

    Returns one of:

    * ``"none"`` — no identity declared (the unit does not drop privileges).
    * ``"numeric"`` — a raw UID/GID; systemd does not consult NSS, so the
      altfiles window cannot affect it.
    * ``"etc"`` — the name is in ``/etc/passwd``; resolved by the ``files``
      source which authselect does not rewrite.
    * ``"altfiles"`` — the name is in ``/usr/lib/passwd`` and not in
      ``/etc/passwd``; resolved through the ``altfiles`` source that is
      transiently absent during the authselect rewrite. At risk.
    * ``"unknown"`` — the name is in neither database. Could be a systemd
      ``DynamicUser=``, a typo, or a database the scan could not read. Reported
      separately and never silently treated as safe.
    """
    if identity is None:
        return "none"
    stripped = identity.strip()
    if not stripped:
        return "none"
    # A purely-numeric UID/GID does not go through NSS name resolution.
    if stripped.lstrip("-").isdigit():
        return "numeric"
    if stripped in etc_names:
        return "etc"
    if stripped in usr_lib_names:
        return "altfiles"
    return "unknown"


def parse_unit_directives(path: Path) -> dict[str, list[str]]:
    """Every value assigned to a key in the unit, ignoring comments.

    Drop-in files are concatenated by systemd; this parser does not need to
    model sections because ``User=``, ``Group=``, ``Wants=``, ``After=`` and
    ``Before=`` are unambiguous across the unit grammar. Repeated keys collect
    every value, matching systemd's own accumulation.
    """
    values: dict[str, list[str]] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith(";"):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            continue
        if "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values.setdefault(key.strip(), []).append(value.strip())
    return values


def iter_service_files(system_dir: Path) -> Iterator[Path]:
    """Every ``*.service`` under ``system_dir``, sorted for stable output."""
    if not system_dir.is_dir():
        return
    for path in sorted(system_dir.glob("*.service")):
        yield path


def unit_identities(system_dir: Path) -> list[UnitIdentity]:
    """Every ``User=``/``Group=`` declared by a service under ``system_dir``."""
    out: list[UnitIdentity] = []
    for path in iter_service_files(system_dir):
        directives = parse_unit_directives(path)
        user_values = directives.get("User", [])
        group_values = directives.get("Group", [])
        user = user_values[-1] if user_values else None
        group = group_values[-1] if group_values else None
        if user is None and group is None:
            continue
        out.append(UnitIdentity(
            unit_path=path,
            unit_name=path.name,
            user=user,
            group=group,
        ))
    return out


def has_nss_ordering_dropin(system_dir: Path, unit_name: str) -> tuple[bool, Path]:
    """Whether the drop-in directory for ``unit_name`` carries the pattern.

    The pattern is the one measured for chronyd and recorded in
    ``CHRONYD_NSS_ORDERING_REPORT.md``: ``Wants=nss-user-lookup.target`` (the
    passive target must be pulled in), ``After=nss-user-lookup.target``, and
    ``After=authselect-apply-changes.service``. No ``Requires=`` on
    authselect, no ``Before=`` (cycle). Returns ``(present, dropin_dir)``.
    """
    dropin_dir = system_dir / f"{unit_name}.d"
    if not dropin_dir.is_dir():
        return False, dropin_dir
    for conf in sorted(dropin_dir.glob("*.conf")):
        directives = parse_unit_directives(conf)
        wants = " ".join(directives.get("Wants", [])).split()
        after = " ".join(directives.get("After", [])).split()
        before = " ".join(directives.get("Before", [])).split()
        requires = " ".join(directives.get("Requires", [])).split()
        if "nss-user-lookup.target" not in wants:
            continue
        if "nss-user-lookup.target" not in after:
            continue
        if "authselect-apply-changes.service" not in after:
            continue
        if "authselect-apply-changes.service" in requires:
            continue
        if before:
            # The drop-in must add only outbound edges. A Before= on any unit
            # risks a cycle through the units we order after.
            continue
        return True, dropin_dir
    return False, dropin_dir


def scan_system(root: Path,
                system_dir: Path | None = None,
                etc_passwd: Path | None = None,
                usr_lib_passwd: Path | None = None) -> SweepReport:
    """Scan an installed system root for at-risk units lacking the ordering.

    ``root`` is the mounted filesystem root. ``system_dir`` defaults to
    ``root/usr/lib/systemd/system``; ``etc_passwd`` defaults to
    ``root/etc/passwd``; ``usr_lib_passwd`` defaults to ``root/usr/lib/passwd``.
    All paths are overridable so the test suite can drive the scanner against a
    built-up tempdir without touching the host.
    """
    root = Path(root)
    system_dir = system_dir or (root / "usr/lib/systemd/system")
    etc_passwd = etc_passwd or (root / "etc/passwd")
    usr_lib_passwd = usr_lib_passwd or (root / "usr/lib/passwd")

    report = SweepReport(
        etc_passwd_path=etc_passwd,
        usr_lib_passwd_path=usr_lib_passwd,
    )
    etc_names = read_passwd_names(etc_passwd)
    usr_lib_names = read_passwd_names(usr_lib_passwd)

    identities = unit_identities(system_dir)
    report.scanned = sum(1 for _ in iter_service_files(system_dir))
    report.with_identity = len(identities)

    for identity in identities:
        # Classify the unit once: it is altfiles-backed if *either* User= or
        # Group= resolves through /usr/lib/passwd. Counting per-field would
        # double-report a unit where both name the same altfiles account.
        user_kind = classify_runtime(identity.user, etc_names, usr_lib_names)
        group_kind = classify_runtime(identity.group, etc_names, usr_lib_names)
        altfields = [
            (name, value) for name, value, kind in (
                ("User", identity.user, user_kind),
                ("Group", identity.group, group_kind),
            ) if kind == "altfiles"
        ]
        if altfields:
            report.altfiles_backed += 1
            present, dropin_dir = has_nss_ordering_dropin(
                system_dir, identity.unit_name)
            if not present:
                fields = ", ".join(f"{name}={value!r}" for name, value in altfields)
                report.at_risk.append(AtRiskUnit(
                    unit_name=identity.unit_name,
                    user=identity.user,
                    group=identity.group,
                    reason=f"{fields} resolves through /usr/lib/passwd "
                           f"(altfiles); no nss-user-lookup.target ordering "
                           f"drop-in at {dropin_dir}",
                    dropin_dir=dropin_dir,
                    dropin_exists=dropin_dir.is_dir(),
                ))
        elif user_kind == "unknown" or group_kind == "unknown":
            report.unknown_identity.append(identity)

    return report


def render_text(report: SweepReport) -> str:
    lines: list[str] = []
    lines.append("NSS account-availability sweep")
    lines.append(f"  /etc/passwd:      {report.etc_passwd_path}")
    lines.append(f"  /usr/lib/passwd:  {report.usr_lib_passwd_path}")
    lines.append(f"  service files scanned: {report.scanned}")
    lines.append(f"  with User=/Group=:    {report.with_identity}")
    lines.append(f"  altfiles-backed:      {report.altfiles_backed}")
    if report.unknown_identity:
        lines.append(f"  unknown (in neither db): {len(report.unknown_identity)}")
    lines.append("")
    if not report.at_risk:
        lines.append("No at-risk unit lacks the nss-user-lookup.target ordering.")
    else:
        lines.append("AT-RISK units lacking the ordering drop-in:")
        for item in report.at_risk:
            lines.append(f"  {item.unit_name}")
            lines.append(f"    User={item.user} Group={item.group}")
            lines.append(f"    {item.reason}")
            lines.append(f"    drop-in dir exists: {item.dropin_exists}")
        lines.append("")
        lines.append("These units are EXPOSED to the altfiles window. This does")
        lines.append("not prove they will fail; proving they are safe needs boot")
        lines.append("evidence, not this scan.")
    if report.unknown_identity:
        lines.append("")
        lines.append("Identities not found in either passwd database (reported,")
        lines.append("not classified as at-risk):")
        for ident in report.unknown_identity:
            lines.append(f"  {ident.unit_name}: User={ident.user} Group={ident.group}")
    return "\n".join(lines) + "\n"


def render_json(report: SweepReport) -> str:
    return json.dumps({
        "etcPasswd": str(report.etc_passwd_path) if report.etc_passwd_path else None,
        "usrLibPasswd": str(report.usr_lib_passwd_path) if report.usr_lib_passwd_path else None,
        "scanned": report.scanned,
        "withIdentity": report.with_identity,
        "altfilesBacked": report.altfiles_backed,
        "atRisk": [
            {
                "unit": item.unit_name,
                "user": item.user,
                "group": item.group,
                "reason": item.reason,
                "dropinDir": str(item.dropin_dir),
                "dropinExists": item.dropin_exists,
            }
            for item in report.at_risk
        ],
        "unknown": [
            {
                "unit": ident.unit_name,
                "user": ident.user,
                "group": ident.group,
            }
            for ident in report.unknown_identity
        ],
        "passed": report.passed,
    }, indent=2, sort_keys=True) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scan an installed system for NSS account-availability races.")
    parser.add_argument("--root", default="/",
                        help="installed system root (default: /)")
    parser.add_argument("--json", action="store_true",
                        help="machine-readable output")
    args = parser.parse_args(argv)

    root = Path(args.root)
    try:
        report = scan_system(root)
    except OSError as error:
        print(f"nss_account_sweep: read error: {error}", file=sys.stderr)
        return 1

    if args.json:
        sys.stdout.write(render_json(report))
    else:
        sys.stdout.write(render_text(report))
    return 0 if report.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())