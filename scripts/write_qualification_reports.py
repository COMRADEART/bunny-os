#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Generate the qualification reports from the recorded matrix data.

The reports are generated rather than written by hand so they cannot drift from
``operations/data/qualification-matrices.json``. A report that says a scenario
passed while the data says otherwise is exactly the kind of discrepancy the
evidence model exists to prevent, and the cheapest way to prevent it is to have
one source.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in os.sys.path:
    os.sys.path.insert(0, str(ROOT))

from release.matrix import MATRICES, evaluate_matrix

REPORTS = {
    "recovery-media": (
        "RECOVERY_MEDIA_QUALIFICATION_REPORT.md",
        "Recovery media qualification report",
        "Recovery media must boot independently of the installed deployment, verify its own "
        "signature, and reach the installed system's data only with valid credentials. No claim "
        "here may rest on source inspection: `release/matrix.py` refuses a source-inspection pass "
        "in this matrix, because a recovery tool that has never booted is a hypothesis.",
        "`recovery-media-failure` is one of the five open stable-release blocker codes, and it "
        "stays open.",
    ),
    "installation": (
        "INSTALLATION_QUALIFICATION_REPORT.md",
        "Installation qualification report",
        "Twelve disposable-disk installation scenarios, from an empty UEFI disk through interrupted "
        "installation and bootloader failure. Every scenario is destructive by nature and is run "
        "against disposable virtual disks.",
        "No disk has been written. The installer source, its safety checks and its refusals are "
        "covered by 60 source tests that all pass; none of that is an installation.",
    ),
    "encryption": (
        "ENCRYPTION_QUALIFICATION_REPORT.md",
        "Encryption qualification report",
        "Nine scenarios covering LUKS password unlock, recovery key, incorrect password, missing "
        "recovery key, TPM fallback, Secure Boot interaction, and update, rollback and recovery "
        "media access against an encrypted installation.",
        "`encryption-failure` and `key-leakage` are non-waivable blockers, and the `Encryption` "
        "evidence category is one of six that `release/evidence.py` refuses to let anyone waive.",
    ),
    "update": (
        "UPDATE_QUALIFICATION_REPORT.md",
        "Update qualification report",
        "Thirteen scenarios covering the happy path and twelve failure paths, including interrupted "
        "download and staging, insufficient disk, invalid signature, expired metadata, wrong "
        "architecture, and failures of service health, graphical session and the Bunny contract.",
        "A signed manifest and a reachable registry are prerequisites. Neither exists.",
    ),
    "rollback": (
        "ROLLBACK_QUALIFICATION_REPORT.md",
        "Rollback qualification report",
        "Manual, automatic and recovery-assisted rollback, plus rollback after encryption and "
        "rollback with user data preserved.",
        "`untested-release-rollback` and `rollback-failure` are open blocker codes.",
    ),
    "accessibility": (
        "ACCESSIBILITY_QUALIFICATION_REPORT.md",
        "Accessibility qualification report",
        "Fourteen essential workflows, from installer keyboard navigation and screen reader through "
        "the encryption prompt, first run, login, the Bunny surfaces, update, rollback, recovery, "
        "diagnostics export, and the high-contrast, text-scaling and reduced-motion settings.",
        "Static accessibility tests are explicitly not sufficient. `release/matrix.py` refuses a "
        "source-inspection pass in this matrix. This is the gap where being wrong harms a user "
        "rather than merely leaving a box unticked: an inaccessible encryption prompt or recovery "
        "tool locks someone out of their own machine.",
    ),
    "preservation": (
        "DATA_PRESERVATION_QUALIFICATION_REPORT.md",
        "Data preservation qualification report",
        "Ten classes of user state that must survive an update or a rollback: `/home`, the Bunny "
        "database, Bunny memory, provider aliases, local models, plugins, workspaces, "
        "applications, settings and checkpoints.",
        "Preservation is measured across an update or a rollback. Both are blocked, so nothing has "
        "been preserved or lost yet.",
    ),
}


def render(matrix: str, title: str, intro: str, note: str, document: dict, commit: str) -> str:
    rows = document.get("matrices", {}).get(matrix, [])
    verdict = evaluate_matrix(matrix, rows, root=ROOT)
    payload = verdict.as_dict()
    reason = document.get("blockedReasons", {}).get(matrix, "")

    resolved = [r for r in verdict.results if r.outcome in ("PASS", "NOT_APPLICABLE")]
    failing = [r for r in verdict.results if r.outcome in ("FAIL", "BLOCKED")]
    untested = [r for r in verdict.results if r.outcome == "NOT_RUN"]

    lines = [
        f"# {title}",
        "",
        f"Date: {document.get('recordedOn', 'unknown')}  ",
        f"Source commit: `{commit}`  ",
        f"Result: **{'QUALIFIED' if verdict.complete else 'NOT QUALIFIED'}** — "
        f"{len(resolved)} of {len(MATRICES[matrix])} scenarios resolved, "
        f"{len(failing)} failing, {len(untested)} not run.",
        "",
        intro,
        "",
        "## Scenarios",
        "",
        "| Scenario | Outcome | Method | Evidence |",
        "|---|---|---|---|",
    ]
    for result in verdict.results:
        evidence = f"`{result.evidenceReference}`" if result.evidenceReference else "—"
        lines.append(
            f"| `{result.scenario}` | {result.outcome} | {result.method} | {evidence} |"
        )

    lines.extend(["", "## Why these scenarios have not run", "", reason or "Not recorded.", ""])

    if untested:
        lines.extend(
            [
                "## Unresolved",
                "",
                "Each of these is blocking. `NOT_RUN` is not a soft state:",
                "",
            ]
        )
        for result in untested:
            lines.append(f"- `{result.scenario}`")
        lines.append("")

    lines.extend(
        [
            "## Standing note",
            "",
            note,
            "",
            "## How to regenerate",
            "",
            "```text",
            f"python scripts/release.py test-matrix --name {matrix}",
            "python scripts/write_qualification_reports.py",
            "```",
            "",
            "This report is generated from `operations/data/qualification-matrices.json`. Edit the",
            "data, not the report: a report that disagrees with the evidence record is exactly what",
            "the evidence model exists to prevent.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", default=None)
    args = parser.parse_args()

    path = ROOT / "operations/data/qualification-matrices.json"
    document = json.loads(path.read_text(encoding="utf-8"))

    commit = args.commit
    if commit is None:
        import subprocess

        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()

    for matrix, (filename, title, intro, note) in REPORTS.items():
        text = render(matrix, title, intro, note, document, commit)
        (ROOT / filename).write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {filename}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
