#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Grade the Phase 7 recovery journey. Fail closed.

Inputs: the breakage record and broken-boot log (step 1), the recovery
session log (step 2), and the repaired-boot log (step 3). The journey the
verdict encodes is the one RECOVERY_DEFINITION.md fixed before any of it ran:

    cannot boot -> recovery boots -> inspect -> repair -> boots again

Every step is measured from the recorded logs; the breakage is a control (a
"broken" disk that reached a target fails the whole journey), and the repair
must have been derived on the recovery system, not restored from a stash —
witnessed by the driver's entry-before/derived-dir/entry-after markers.

Exit codes: 0 PASS, 4 FAIL, 5 NOT_RUN, 2 usage.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_HEALTH = re.compile(
    r"Graphical Interface|Multi-User System|GNOME Display Manager|Reached target"
)
_CMDLINE_OSTREE = re.compile(
    r"ostree=/ostree/boot\.[0-9]+/[^/ ]+/([a-f0-9]{64})/[0-9]+"
)


def grade(
    breakage: dict | None,
    broken_log: str | None,
    session_log: str | None,
    repaired_log: str | None,
) -> dict:
    result: dict = {"journey": "phase7-recovery", "verdict": None, "reasons": [], "steps": {}}
    reasons = result["reasons"]
    steps = result["steps"]

    if breakage is None or broken_log is None:
        reasons.append("NOT_RUN: no breakage record; the journey never had a broken machine")
        result["verdict"] = "NOT_RUN"
        return result

    # Step 1 — the machine cannot boot normally, measured.
    if _HEALTH.search(broken_log):
        reasons.append("FAIL: the 'broken' disk reached a boot target; the breakage control failed")
        result["verdict"] = "FAIL"
        return result
    steps["cannotBootNormally"] = True

    if session_log is None:
        reasons.append("NOT_RUN: no recovery session ran")
        result["verdict"] = "NOT_RUN"
        return result

    # Step 2a — the recovery medium reached its environment with the broken
    # disk attached: the driver only runs once the target is up.
    if "BUNNY-P7R: BEGIN recovery driver" not in session_log:
        reasons.append("NOT_RUN: the recovery driver never started; the medium did not reach its target")
        result["verdict"] = "NOT_RUN"
        return result
    steps["recoveryMediaBooted"] = True

    # Step 2b — the installation was inspected: at least one deployment
    # enumerated with its origin or os-release identity.
    inspected = re.findall(r"BUNNY-P7R: deployment=([a-f0-9]{64})\.0", session_log)
    if not inspected:
        reasons.append("FAIL: the recovery environment inspected no deployment on the attached disk")
    steps["installationInspected"] = sorted(set(inspected))

    # Step 2c — the repair happened and was derived, not restored: the driver
    # must record the broken entry, the directory it derived from the disk,
    # and the rewritten entry naming that directory.
    before = re.search(r"BUNNY-P7R: entry-before-linux=linux (\S+)", session_log)
    derived = re.search(r"BUNNY-P7R: derived-dir=(\S+)", session_log)
    after = re.search(r"BUNNY-P7R: entry-after-linux=linux (\S+)", session_log)
    if not (before and derived and after and "BUNNY-P7R: REPAIRED" in session_log):
        reasons.append("FAIL: the repair did not complete on the recovery system")
        result["verdict"] = "FAIL"
        return result
    if derived.group(1) not in after.group(1):
        reasons.append("FAIL: the rewritten entry does not name the derived kernel directory")
    if before.group(1) == after.group(1):
        reasons.append("FAIL: the entry did not change; nothing was repaired")
    expected_csum = breakage.get("realChecksumDir")
    if expected_csum and expected_csum not in after.group(1):
        reasons.append("FAIL: the repaired entry does not name the real kernel checksum directory")
    steps["repairPerformed"] = {"before": before.group(1), "after": after.group(1)}

    # Step 3 — the outcome, verified: the repaired disk boots to a healthy
    # target on the deployment the breakage record names.
    if repaired_log is None:
        reasons.append("NOT_RUN: the repaired disk was never booted; the outcome is unverified")
        result["verdict"] = "NOT_RUN"
        return result
    if not _HEALTH.search(repaired_log):
        reasons.append("FAIL: the repaired disk did not reach a healthy boot target")
    booted = _CMDLINE_OSTREE.search(repaired_log)
    if booted is None:
        reasons.append("FAIL: the repaired boot shows no ostree identity")
    elif expected_csum and booted.group(1) != expected_csum:
        reasons.append(
            f"FAIL: the repaired disk booted deployment {booted.group(1)[:12]}, "
            f"not the installation's own {expected_csum[:12]}"
        )
    else:
        steps["outcomeVerified"] = booted.group(1) if booted else None

    result["verdict"] = "FAIL" if any(r.startswith("FAIL") for r in reasons) else "PASS"
    if result["verdict"] == "PASS":
        reasons.append(
            "PASS: the machine could not boot, recovery booted independently, inspected "
            "the installation, repaired the boot entry from on-disk truth, and the "
            "repaired machine boots its own deployment"
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("breakage_json")
    parser.add_argument("broken_log")
    parser.add_argument("session_log")
    parser.add_argument("repaired_log")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    def read(path: str) -> str | None:
        p = Path(path)
        return p.read_text(encoding="utf-8", errors="replace") if p.is_file() else None

    breakage_text = read(args.breakage_json)
    breakage = json.loads(breakage_text) if breakage_text else None
    result = grade(breakage, read(args.broken_log), read(args.session_log), read(args.repaired_log))
    rendered = json.dumps(result, indent=1, sort_keys=True)
    print(rendered)
    if args.out:
        Path(args.out).write_text(rendered + "\n", encoding="utf-8", newline="\n")
    return {"PASS": 0, "FAIL": 4, "NOT_RUN": 5}[result["verdict"]]


if __name__ == "__main__":
    sys.exit(main())
