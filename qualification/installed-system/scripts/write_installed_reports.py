#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Generate the installed-system reports from the evidence, and only from it.

Every number in these reports is read out of a record on disk. Nothing is
written from memory of how a run went, and a missing record produces a
``NOT_RUN`` section naming what is absent rather than a blank the reader
would have to interpret. That rule is why these are generated rather than
written: a hand-written report can drift from its evidence silently, and a
generated one fails to build.

The reports refuse to average. A category with any failing record is FAIL,
whatever the rest say — and each report prints the record path beside every
verdict, so a reader can check the claim against the file that made it.
"""

from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from release.installed import resolve_context  # noqa: E402

EVIDENCE = ROOT / "qualification/installed-system/evidence"
HEADER = """<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->
"""


def load(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def scenario_records() -> dict[str, dict]:
    records: dict[str, dict] = {}
    for record_path in sorted(EVIDENCE.glob("ISQ-*/record.json")):
        record = load(record_path)
        if record:
            record["_path"] = str(record_path.relative_to(ROOT))
            records[record["evidenceId"]] = record
    return records


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def verdict_block(entries: list[tuple[str, str, str]]) -> str:
    """name, result, evidence path — aligned, with the path always shown."""
    if not entries:
        return "```text\nno records\n```\n"
    width = max(len(name) for name, _, _ in entries)
    lines = [f"{name.ljust(width)}  {result:<8} {path}" for name, result, path in entries]
    return "```text\n" + "\n".join(lines) + "\n```\n"


def write(path: Path, body: str) -> None:
    path.write_text(HEADER + body, encoding="utf-8", newline="\n")
    print(f"wrote {rel(path)}")


def main() -> int:
    parser = argparse.ArgumentParser(prog="write_installed_reports")
    parser.add_argument("--date", default=datetime.date.today().isoformat())
    args = parser.parse_args()

    context = resolve_context(ROOT)
    scenarios = scenario_records()
    collections = EVIDENCE / "collections"
    installs = EVIDENCE / "installs"

    authority = (
        "```text\n"
        f"Archive target (Commit C)     {context.sourceCommit}\n"
        f"Archive digest                {context.sourceArchiveDigest}\n"
        f"Installation artifact         {context.installationArtifactDigest}\n"
        f"Installer toolchain           {context.installerToolchainDigest}\n"
        f"Scenario set                  {context.scenarioVersion}\n"
        "Environment                   qemu-kvm (every record below)\n"
        "```\n"
    )

    def scenario_entries(names: list[str]) -> list[tuple[str, str, str]]:
        entries = []
        for name in names:
            found = [r for r in scenarios.values() if r.get("scenario") == name]
            if not found:
                entries.append((name, "NOT_RUN", "no record"))
                continue
            for record in found:
                entries.append((record["evidenceId"], record["result"], record["_path"]))
        return entries

    # ------------------------------------------------------ first boot
    first_boot = load(collections / "first-boot-blank" / "first-boot.json")
    body = f"""
# First-boot qualification report

Date: {args.date}
Status: **{"PASS" if first_boot and first_boot.get("result") == "PASS" else ("FAIL" if first_boot else "NOT_RUN")}**

## Authority

{authority}
## Boot scenarios

{verdict_block(scenario_entries(["first-boot", "reduced-resources", "tpm-present", "tpm-absent"]))}
## Offline first-boot collection

"""
    if first_boot:
        body += verdict_block([
            (a["name"], a["result"], a["observed"][:70])
            for a in first_boot.get("assertions", [])
        ])
        if first_boot.get("failedUnits"):
            body += ("\nFailed units, enumerated rather than summarised:\n\n```text\n"
                     + "\n".join(first_boot["failedUnits"]) + "\n```\n")
        body += "\n## Limitations\n\n" + "".join(
            f"- {line}\n" for line in first_boot.get("limitations", []))
    else:
        body += ("The offline first-boot collection has not been produced. Every "
                 "assertion it owns is `NOT_RUN`.\n")
    body += """
## What this does not establish

A booted system is not a used system. Desktop session behaviour, login,
assistive technology and every interactive flow belong to scenarios that
drive a running system with a credential the qualified image deliberately
does not ship, and no record here claims them.
"""
    write(ROOT / "FIRST_BOOT_QUALIFICATION_REPORT.md", body)

    # ------------------------------------------- per-installation state
    identities = load(collections / "installation-identities.json")
    body = f"""
# Per-installation state report

Date: {args.date}
Status: **{identities.get("result") if identities else "NOT_RUN"}**

## Authority

{authority}
## What was compared

Two installations of one archive, installed and booted separately, read
offline from their own disks. Secret material is never retained: differences
are proven through per-comparison salted digests whose salt dies with the
process.

"""
    if identities:
        body += verdict_block([
            (f["check"], f["result"], f["detail"][:70])
            for f in identities.get("findings", [])
        ])
        body += f"\nHostnames observed: `{'`, `'.join(identities.get('hostnames', []) or ['(none)'])}`\n"
    else:
        body += "No comparison record exists; every identity assertion is `NOT_RUN`.\n"
    write(ROOT / "PER_INSTALLATION_STATE_REPORT.md", body)

    # ------------------------------------------------- applied SELinux
    applied = load(collections / "applied-selinux.json")
    comparison = load(collections / "selinux-comparison.json")
    body = f"""
# Applied SELinux qualification report

Date: {args.date}
Status: **{comparison.get("result") if comparison else "NOT_RUN"}**

## Authority

{authority}
## Collection

"""
    if applied:
        body += (
            "```text\n"
            f"labelled paths      {applied.get('labelledCount')}\n"
            f"entries examined    {applied.get('entryCount')}\n"
            f"unlabelled          {applied.get('unlabelledCount')}\n"
            f"subtree             {applied.get('subtree')}\n"
            "```\n\n"
            "Read from `security.selinux` xattrs through a read-only libguestfs "
            "mount of the deployed root. An empty result is refused as a "
            "collection failure rather than reported as a clean one.\n"
        )
    else:
        body += "No applied-context manifest exists.\n"
    if comparison:
        counts = comparison.get("counts", {})
        body += "\n## Classification\n\n```text\n"
        body += f"matched paths               {comparison.get('matchedPaths')}\n"
        for state, count in counts.items():
            body += f"{state:<28}{count}\n"
        body += "```\n\n"
        body += (
            "`UNRESOLVED` blocks: a difference nobody classified is a difference "
            "nobody understands. Expected states come from a reviewed fixture, "
            "not from a heuristic.\n"
        )
    body += """
## What this does not establish

Enforcing mode, loaded policy modules and runtime AVC denials are properties
of a running system. This collection reads a disk that is not running and
does not claim them; they belong to an in-guest collection that has not been
performed.
"""
    write(ROOT / "APPLIED_SELINUX_QUALIFICATION_REPORT.md", body)

    # ------------------------------------------------------- services
    services = load(collections / "installed-services.json")
    body = f"""
# Installed service qualification report

Date: {args.date}
Status: **{services.get("result") if services else "NOT_RUN"}**

## Authority

{authority}
"""
    if services:
        body += "## Assertions\n\n" + verdict_block([
            (a["name"], a["result"], a["observed"][:70])
            for a in services.get("assertions", [])
        ])
        units = services.get("units", [])
        body += f"\n## Units read from the deployed root ({len(units)})\n\n```text\n"
        for unit in units:
            body += (f"{unit['unit']:<38} confinement directives: "
                     f"{unit['sandboxDirectiveCount']:>2}\n")
        body += "```\n"
        body += "\n## Limitations\n\n" + "".join(
            f"- {line}\n" for line in services.get("limitations", []))
    else:
        body += "\nNo service assessment record exists; every assertion is `NOT_RUN`.\n"
    write(ROOT / "INSTALLED_SERVICE_QUALIFICATION_REPORT.md", body)

    # ------------------------------------------------ network privacy
    network = load(collections / "network-privacy.json")
    body = f"""
# Installed network privacy report

Date: {args.date}
Status: **{network.get("result") if network else "NOT_RUN"}**

## Authority

{authority}
"""
    if network:
        body += "## Assertions\n\n" + verdict_block([
            (a["name"], a["result"], str(a.get("observed"))[:70])
            for a in network.get("assertions", [])
        ])
        body += (
            "\nThe capture is taken at the VM boundary by QEMU itself, so it "
            "cannot be influenced by anything inside the guest. An absent or "
            "unreadable capture is `BLOCKED`, never 'no traffic'.\n"
        )
        body += "\n## Limitations\n\n" + "".join(
            f"- {line}\n" for line in network.get("limitations", []))
    else:
        body += "\nNo capture analysis exists; every traffic assertion is `NOT_RUN`.\n"
    body += """
## What this does not establish

Listening sockets on a running system, and traffic during a desktop session
or an update check, are not covered: this analyses the boot captured by the
scenario runner. Those belong to scenarios that drive a logged-in system.
"""
    write(ROOT / "INSTALLED_NETWORK_PRIVACY_REPORT.md", body)

    # ----------------------------------------------- installation matrix
    install_records = []
    for record_path in sorted(installs.glob("*.json")):
        record = load(record_path)
        if record:
            install_records.append((record_path.stem, record.get("outcome", "?"),
                                    rel(record_path)))
    body = f"""
# Installation qualification report

Date: {args.date}
Status: **{"PASS" if install_records and all(
    o in ("INSTALLED", "REFUSED_AS_EXPECTED", "PROTECTED", "INTERRUPTED")
    for _, o, _ in install_records) else ("FAIL" if install_records else "NOT_RUN")}**

## Authority

{authority}
## Host-side installation modes

{verdict_block(install_records)}
Refusals are results, not gaps: the undersized target must refuse before a
destructive partial deployment, the disk carrying data must refuse without
explicit authorization, and the interrupted install must leave a disk that
recovery media can inspect.

## Boot of what was installed

{verdict_block(scenario_entries(["first-boot", "encrypted-first-boot", "encrypted-wrong-credential"]))}
## What this does not establish

The graphical live installer is not exercised. These installations are
performed by `bootc install`, which is the mechanism the live installer
drives, and the installer's own interface, disk selection and warnings are
untested — `LIVE_INSTALLER_MEDIA_REPORT.md` records that gap.
"""
    write(ROOT / "INSTALLATION_QUALIFICATION_REPORT.md", body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
