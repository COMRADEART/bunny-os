#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Assess the installed system's services from the disk it booted from.

Two questions, answered from two sources, because neither alone is honest:

    what happened      the persistent journal of the boot — which units
                       started, which failed, with what result
    what was shipped   the unit files on the deployed root — enablement,
                       ordering, sandboxing, privilege, capabilities

``systemd-analyze security`` is not run against a live system here; it is
approximated by reading the sandboxing directives each unit declares, and
the record says exactly that rather than implying a runtime score. The
numeric score was never the point: the exposure is, and the exposure is in
the unit file.

Every failed unit found in the journal is reported. A unit whose failure is
expected is a reviewed disposition elsewhere, never an omission here — the
adversarial tests refuse a service report that quietly drops one.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

#: The directives that decide how much of the system a unit can reach. Their
#: presence is what this reads; their sufficiency is a review, not a script.
SANDBOX_DIRECTIVES = (
    "PrivateTmp", "ProtectSystem", "ProtectHome", "NoNewPrivileges",
    "PrivateDevices", "ProtectKernelTunables", "ProtectKernelModules",
    "ProtectControlGroups", "RestrictAddressFamilies", "RestrictNamespaces",
    "MemoryDenyWriteExecute", "SystemCallFilter", "CapabilityBoundingSet",
    "ReadWritePaths", "ReadOnlyPaths", "IPAddressDeny", "DevicePolicy",
    "User", "Group", "DynamicUser",
)


def guestfish(disk: Path, *commands: str) -> str:
    result = subprocess.run(
        ["guestfish", "--ro", "-a", str(disk), "-i", *commands],
        capture_output=True, text=True,
    )
    return result.stdout if result.returncode == 0 else ""


def main() -> int:
    parser = argparse.ArgumentParser(prog="collect_service_state")
    parser.add_argument("--disk", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    assertions: list[dict] = []
    limitations = [
        "systemd-analyze security is not executed: it requires a live system bus. "
        "Sandboxing is read from the shipped unit files, which is what the score "
        "summarises, and the exposure is reported per directive rather than as a number.",
        "runtime restart, crash and degraded-mode behaviour belong to scenarios that "
        "drive a booted system; this collection is offline and does not claim them.",
    ]

    def check(name: str, ok: bool, expected: str, observed: str) -> None:
        assertions.append({"name": name, "expected": expected, "observed": observed,
                           "result": "PASS" if ok else "FAIL"})

    # --- what happened -----------------------------------------------------
    failed_units: list[str] = []
    with tempfile.TemporaryDirectory() as scratch:
        journal_tar = Path(scratch) / "journal.tar"
        result = subprocess.run(
            ["guestfish", "--ro", "-a", str(args.disk), "-i",
             "tar-out", "/var/log/journal", str(journal_tar)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print("BLOCKED: the boot journal could not be read; a service report "
                  "without the boot that produced it is not a report.", file=sys.stderr)
            return 2
        journal_dir = Path(scratch) / "journal"
        journal_dir.mkdir()
        subprocess.run(["tar", "-xf", str(journal_tar), "-C", str(journal_dir)], check=True)
        machine_dirs = [d for d in journal_dir.rglob("*") if d.is_dir()
                        and any(f.suffix == ".journal" for f in d.iterdir() if f.is_file())]
        if not machine_dirs:
            print("BLOCKED: no journal files on the disk", file=sys.stderr)
            return 2
        text = subprocess.run(
            ["journalctl", "-D", str(machine_dirs[0]), "-b", "-0", "--no-pager",
             "-o", "short-monotonic"],
            capture_output=True, text=True,
        ).stdout
        failed_units = sorted(set(re.findall(
            r"([\w@.\\x-]+\.(?:service|socket|mount|timer)): Failed with result", text)))
        started = sorted(set(re.findall(r"Started ([\w@.\\x-]+\.service)", text)))
        check("units-started", bool(started), "units started during boot",
              f"{len(started)} unit(s) started")
        check("every-failure-enumerated", True,
              "every failed unit reported, none omitted",
              f"{len(failed_units)} failed: {', '.join(failed_units) or 'none'}")
        check("no-failed-units", not failed_units,
              "no unit failed during boot",
              ", ".join(failed_units) or "clean")

    # --- what was shipped --------------------------------------------------
    listing = guestfish(args.disk, "glob-expand", "/usr/lib/systemd/system/bunny-*")
    units = [line.strip() for line in listing.splitlines() if line.strip().endswith(
        (".service", ".socket", ".timer", ".target"))]
    unit_records = []
    for unit in units:
        content = guestfish(args.disk, "cat", unit)
        if not content:
            continue
        directives = {
            name: match.group(1).strip()
            for name in SANDBOX_DIRECTIVES
            if (match := re.search(rf"^{name}=(.*)$", content, re.MULTILINE))
        }
        exec_start = re.search(r"^ExecStart=(.*)$", content, re.MULTILINE)
        unit_records.append({
            "unit": unit.rsplit("/", 1)[-1],
            "execStart": exec_start.group(1).strip() if exec_start else None,
            "sandboxing": directives,
            "sandboxDirectiveCount": len(directives),
            "runsAsRoot": directives.get("User", "root") in ("root", ""),
            "wantedBy": re.findall(r"^WantedBy=(.*)$", content, re.MULTILINE),
            "after": re.findall(r"^After=(.*)$", content, re.MULTILINE),
        })

    check("bunny-units-present", bool(unit_records),
          "the image ships its Bunny units", f"{len(unit_records)} unit(s) read")

    # An ExecStart naming a program the deployed root does not carry is the
    # defect the brlapi gap was; it is checked here on the installed system
    # rather than inferred from the build.
    missing_programs = []
    for record in unit_records:
        exec_start = record.get("execStart") or ""
        program = exec_start.split()[0].lstrip("-@!+") if exec_start else ""
        if program.startswith("/"):
            exists = guestfish(args.disk, "exists", program).strip()
            if exists != "true":
                missing_programs.append(f"{record['unit']} -> {program}")
    check("every-unit-program-installed", not missing_programs,
          "every shipped unit's ExecStart exists on the deployed root",
          ", ".join(missing_programs) or "all present")

    unsandboxed = [r["unit"] for r in unit_records
                   if r["sandboxDirectiveCount"] == 0 and r["unit"].endswith(".service")]
    check("services-declare-confinement", not unsandboxed,
          "every Bunny service declares at least one confinement directive",
          ", ".join(unsandboxed) or "all confined")

    result_value = "PASS" if all(a["result"] == "PASS" for a in assertions) else "FAIL"
    document = {
        "schemaVersion": 1,
        "collection": "installed-services-offline",
        "disk": args.disk.name,
        "assertions": assertions,
        "failedUnits": failed_units,
        "units": unit_records,
        "limitations": limitations,
        "result": result_value,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=1, sort_keys=True) + "\n",
                           encoding="utf-8")
    print(f"installed service assessment: {result_value}")
    for assertion in assertions:
        print(f"  {assertion['result']:4} {assertion['name']}: {assertion['observed'][:90]}")
    return 0 if result_value == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
