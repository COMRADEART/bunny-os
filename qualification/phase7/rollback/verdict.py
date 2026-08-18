#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Grade the Phase 7 rollback journey. Fail closed.

The verdict is computed from three inputs: the expectation written before any
boot, and the serial logs of the two journey boots. Nothing here re-reads the
disk; the grader sees exactly what the recorded evidence says, so replaying it
over a run that should fail is cheap — and the unit tests do exactly that with
constructed logs, because a grader whose FAIL branch has never executed is how
three rollback runs passed without rolling back.

Verdict semantics, fixed by the expectation before the journey ran:

  PASS     the machine was on the update-target deployment, ``bootc rollback``
           selected the before-update deployment, and the verify boot came up
           on that selected deployment — agreed independently by the kernel
           command line, by ``bootc status``, and by the per-deployment /etc
           identity marker — with every preserved marker byte-identical.
  FAIL     any of that is false. A healthy boot target on the wrong
           deployment is FAIL. Disagreeing identity sources are FAIL.
  NOT_RUN  a precondition was absent: a log is missing, the journey unit did
           not run, or the disk was not in the updated state to begin with —
           in which case no rollback was exercised and nothing may be passed.

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
_CSUM = re.compile(r"([a-f0-9]{64})")


def _after(line: str, tag: str) -> str:
    return line.split(tag, 1)[1].strip()


def parse_log(text: str) -> dict:
    """Extract the journey facts from one boot's serial log."""
    facts: dict = {
        "began": False,
        "ended": False,
        "step": None,
        "cmdlineBootChecksum": None,
        "etcIdentity": None,
        "hostnameFile": None,
        "locale": None,
        "rollbackExit": None,
        "bootcBootedChecksum": None,
        "bootcBootedImage": None,
        "ostreeAfterDefault": None,
        "markers": {},
        "healthy": bool(_HEALTH.search(text)),
    }
    bootc_lines: list[str] = []
    for raw in text.splitlines():
        if "BUNNY-P7-BOOTC: " in raw:
            bootc_lines.append(_after(raw, "BUNNY-P7-BOOTC: "))
            continue
        if "BUNNY-P7-OSTREE-AFTER: " in raw:
            if facts["ostreeAfterDefault"] is None:
                found = _CSUM.search(_after(raw, "BUNNY-P7-OSTREE-AFTER: "))
                if found:
                    facts["ostreeAfterDefault"] = found.group(1)
            continue
        if "BUNNY-P7-SHA: " in raw:
            payload = _after(raw, "BUNNY-P7-SHA: ")
            parts = payload.split(None, 1)
            if len(parts) == 2:
                sha, path = parts
                facts["markers"][path.strip()] = sha
            continue
        if "BUNNY-P7: " not in raw:
            continue
        line = _after(raw, "BUNNY-P7: ")
        if line.startswith("BEGIN step="):
            facts["began"] = True
            facts["step"] = line.split("=", 1)[1]
        elif line.startswith("END step="):
            facts["ended"] = True
        elif line.startswith("cmdline-bootcsum="):
            value = line.split("=", 1)[1].strip()
            if re.fullmatch(r"[a-f0-9]{64}", value):
                facts["cmdlineBootChecksum"] = value
        elif line.startswith("cmdline=") and facts["cmdlineBootChecksum"] is None:
            # Fallback for the long-form record; the short marker above is
            # authoritative because a long serial line can be split by kernel
            # messages mid-argument — measured on this harness's first run.
            found = _CMDLINE_OSTREE.search(line)
            if found:
                facts["cmdlineBootChecksum"] = found.group(1)
        elif line.startswith("etc-identity="):
            facts["etcIdentity"] = line.split("=", 1)[1]
        elif line.startswith("hostname-file="):
            facts["hostnameFile"] = line.split("=", 1)[1]
        elif line.startswith("locale="):
            facts["locale"] = line.split("=", 1)[1]
        elif line.startswith("rollback exit="):
            try:
                facts["rollbackExit"] = int(line.split("=", 1)[1])
            except ValueError:
                facts["rollbackExit"] = -1
    if bootc_lines:
        try:
            status = json.loads("\n".join(bootc_lines))
            booted = status.get("status", {}).get("booted") or {}
            facts["bootcBootedChecksum"] = (booted.get("ostree") or {}).get("checksum")
            image = ((booted.get("image") or {}).get("image") or {})
            facts["bootcBootedImage"] = image.get("image")
        except (json.JSONDecodeError, AttributeError):
            pass
    return facts


def _deployment_for(expectation: dict, *, commit=None, bootcsum=None):
    for dep in expectation["deployments"]:
        if commit is not None and dep["deployCommit"] == commit:
            return dep
        if bootcsum is not None and dep["bootChecksum"] == bootcsum:
            return dep
    return None


def grade(
    expectation: dict,
    restage_log: str | None,
    rollback_log: str | None,
    verify_log: str | None,
) -> dict:
    """Return the verdict document. Never raises on bad evidence; grades it."""
    result: dict = {
        "journey": "phase7-rollback",
        "verdict": None,
        "reasons": [],
        "identities": {},
        "state": {},
    }
    reasons = result["reasons"]

    deployments = expectation.get("deployments") or []
    before_update = next(
        (d for d in deployments if d.get("originImage") and "e906a48793d7" in d["originImage"]),
        None,
    )
    update_target = next(
        (d for d in deployments if d.get("originImage") and "e501218f2fe0" in d["originImage"]),
        None,
    )
    if before_update is None or update_target is None:
        reasons.append("NOT_RUN: the expectation does not bind both deployments to their images")
        result["verdict"] = "NOT_RUN"
        return result
    result["identities"]["beforeUpdateDeployment"] = before_update["deployCommit"]
    result["identities"]["updateTargetDeployment"] = update_target["deployCommit"]

    if restage_log is None or rollback_log is None or verify_log is None:
        reasons.append("NOT_RUN: a journey log is missing")
        result["verdict"] = "NOT_RUN"
        return result

    boot_s = parse_log(restage_log)
    boot_r = parse_log(rollback_log)
    boot_v = parse_log(verify_log)

    # --- The restage boot: whatever the disk booted, it must end selecting
    # the update target, so the qualified rollback runs N+1 -> N.
    if not boot_s["began"] or boot_s["step"] != "restage":
        reasons.append("NOT_RUN: the journey unit did not run its restage step")
        result["verdict"] = "NOT_RUN"
        return result
    restage_booted = _deployment_for(expectation, commit=boot_s["etcIdentity"])
    result["identities"]["restageBooted"] = (
        restage_booted["deployCommit"] if restage_booted else None
    )
    if boot_s["ostreeAfterDefault"] != update_target["deployCommit"]:
        reasons.append(
            "NOT_RUN: the restage boot did not leave the update target selected; "
            "the N+1 -> N rollback could not be exercised"
        )
        result["verdict"] = "NOT_RUN"
        return result

    if not boot_r["began"] or boot_r["step"] != "rollback":
        reasons.append("NOT_RUN: the journey unit did not run its rollback step")
        result["verdict"] = "NOT_RUN"
        return result

    # --- Which deployment was the machine on when it rolled back? Three
    # sources; all must exist and agree before anything else is judged.
    sources_r = {
        "cmdline": _deployment_for(expectation, bootcsum=boot_r["cmdlineBootChecksum"]),
        "bootc": _deployment_for(expectation, commit=boot_r["bootcBootedChecksum"]),
        "etcIdentity": _deployment_for(expectation, commit=boot_r["etcIdentity"]),
    }
    if any(v is None for v in sources_r.values()):
        missing = [k for k, v in sources_r.items() if v is None]
        reasons.append(f"NOT_RUN: booted identity unreadable in the rollback boot from: {', '.join(missing)}")
        result["verdict"] = "NOT_RUN"
        return result
    commits_r = {v["deployCommit"] for v in sources_r.values()}
    if len(commits_r) != 1:
        reasons.append("FAIL: the identity sources disagree about the deployment that ran the rollback")
        result["verdict"] = "FAIL"
        return result
    booted_before = commits_r.pop()
    result["identities"]["bootedBeforeRollback"] = booted_before

    if booted_before != update_target["deployCommit"]:
        # The restage boot selected the update target and the machine booted
        # something else anyway: selection-did-not-take, the exact defect the
        # grubenv harness hid for three runs. FAIL, not NOT_RUN — a selection
        # was made and the boot contradicts it.
        health = "healthy" if boot_r["healthy"] else "unhealthy"
        reasons.append(
            f"FAIL: the restage selected the update target but the machine booted "
            f"{booted_before[:12]} ({health} boot target reached); selection did not take"
        )
        result["verdict"] = "FAIL"
        return result

    if boot_r["rollbackExit"] != 0:
        reasons.append(f"FAIL: bootc rollback exited {boot_r['rollbackExit']!r}")
    if boot_r["ostreeAfterDefault"] is None:
        reasons.append("FAIL: the post-rollback deployment order was not recorded")
        result["verdict"] = "FAIL"
        return result
    selected = boot_r["ostreeAfterDefault"]
    result["identities"]["selectedRollbackTarget"] = selected
    if selected != before_update["deployCommit"]:
        reasons.append(
            "FAIL: bootc rollback selected a deployment other than the before-update deployment"
        )

    # --- The verify boot: the deployment that ACTUALLY booted.
    if not boot_v["began"]:
        reasons.append("FAIL: the verify boot left no journey evidence")
        result["verdict"] = "FAIL"
        return result
    sources_v = {
        "cmdline": _deployment_for(expectation, bootcsum=boot_v["cmdlineBootChecksum"]),
        "bootc": _deployment_for(expectation, commit=boot_v["bootcBootedChecksum"]),
        "etcIdentity": _deployment_for(expectation, commit=boot_v["etcIdentity"]),
    }
    result["identities"]["actuallyBooted"] = {
        k: (v["deployCommit"] if v else None) for k, v in sources_v.items()
    }
    if any(v is None for v in sources_v.values()):
        missing = [k for k, v in sources_v.items() if v is None]
        reasons.append(f"FAIL: booted identity unreadable in the verify boot from: {', '.join(missing)}")
        result["verdict"] = "FAIL"
        return result
    commits_v = {v["deployCommit"] for v in sources_v.values()}
    if len(commits_v) != 1:
        reasons.append("FAIL: the identity sources disagree about the deployment that booted after rollback")
        result["verdict"] = "FAIL"
        return result
    actually = commits_v.pop()

    if actually != selected:
        # The §3 sentence, verbatim: a healthy machine booting the wrong
        # deployment is FAIL — the health of the target makes it worse, not
        # better, because health is exactly what the old harness mistook for
        # proof.
        health = "healthy" if boot_v["healthy"] else "unhealthy"
        reasons.append(
            f"FAIL: the machine booted deployment {actually[:12]} instead of the "
            f"selected rollback target {selected[:12]} ({health} boot target reached)"
        )
    if not boot_v["healthy"]:
        reasons.append("FAIL: the rolled-back system did not reach a healthy boot target")

    # --- User state against the pre-boot expectation.
    expected_markers = expectation["rules"]["preservedByteIdentical"]
    state = result["state"]
    for path, sha in sorted(expected_markers.items()):
        seen = boot_v["markers"].get(path)
        state[path] = {"expected": sha, "observed": seen}
        if seen != sha:
            reasons.append(f"FAIL: preserved marker changed or vanished: {path}")
    if boot_v["etcIdentity"] != before_update["deployCommit"]:
        reasons.append("FAIL: /etc did not switch to the rollback target's per-deployment /etc")
    if boot_v["hostnameFile"] != "ABSENT":
        reasons.append("FAIL: /etc/hostname appeared where the expectation says ABSENT")
    if boot_v["locale"] != 'LANG="C.UTF-8"':
        reasons.append(f"FAIL: locale read {boot_v['locale']!r}, expected the recorded fallback")

    result["verdict"] = "FAIL" if any(r.startswith("FAIL") for r in reasons) else "PASS"
    if result["verdict"] == "PASS":
        reasons.append(
            "PASS: rollback selected the before-update deployment, three independent "
            "sources agree it booted, and every preserved marker is byte-identical"
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("expectation")
    parser.add_argument("restage_log")
    parser.add_argument("rollback_log")
    parser.add_argument("verify_log")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    expectation = json.loads(Path(args.expectation).read_text(encoding="utf-8"))

    def read(path: str) -> str | None:
        p = Path(path)
        if not p.is_file():
            return None
        return p.read_text(encoding="utf-8", errors="replace")

    result = grade(
        expectation, read(args.restage_log), read(args.rollback_log), read(args.verify_log)
    )
    rendered = json.dumps(result, indent=1, sort_keys=True)
    print(rendered)
    if args.out:
        Path(args.out).write_text(rendered + "\n", encoding="utf-8", newline="\n")
    return {"PASS": 0, "FAIL": 4, "NOT_RUN": 5}[result["verdict"]]


if __name__ == "__main__":
    sys.exit(main())
