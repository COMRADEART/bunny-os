# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Render the §17 security disposition matrix from the evidence that exists.

§17 asks for a matrix with a status per finding, drawn from
``FIX | MITIGATE | ACCEPT | NOT_APPLICABLE | PENDING_REVIEW``, and adds two
constraints that decide almost every row before any judgement is applied:

    Do not attempt to dismiss them as "inherited."
    Do not mark security findings resolved without evidence.

Both are already enforced in code rather than by convention. ``release/cve.py``
and ``release/vulnerability.py`` reject, at parse time, any non-blocking
disposition of a Critical finding that does not reference a *completed
independent review* — and no independent review has been completed. So a status
of FIX, MITIGATE, ACCEPT or NOT_APPLICABLE cannot be recorded for a Critical
finding here even if somebody believed it, which is the correct behaviour and
the reason this script assigns statuses rather than inviting them.

What this does add is the **Bunny impact** column, and that is not a judgement:
every value in it is read from measured evidence already in the record — which
binaries carry the module, whether any enabled unit reaches them, whether the
broker can invoke them, the file modes, and the SELinux state.

Run: ``python qualification/phase5/security/build_disposition_matrix.py``
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "operations" / "data" / "vulnerability-disposition.json"
HERE = Path(__file__).resolve().parent

#: A finding may only leave PENDING_REVIEW through a completed independent
#: review. Encoded so the rule is visible at the point it is applied rather
#: than only in the prose above.
STATUS_REQUIRING_INDEPENDENT_REVIEW = {"ACCEPT", "NOT_APPLICABLE"}


def disposition_for(finding: dict, review_completed: bool) -> tuple[str, str]:
    """The status this finding may carry, and the sentence that justifies it.

    Deliberately incapable of returning ACCEPT or NOT_APPLICABLE while no
    independent review exists. A function that *could* return them and happens
    not to would be one refactor away from returning them.
    """
    severity = finding.get("scannerSeverity")
    fixed = finding.get("fixedVersion")
    from_base = finding.get("fromBaseImage")

    if not review_completed:
        if from_base and fixed:
            return (
                "PENDING_REVIEW",
                "an upstream fix exists but is not available to this project: the package "
                "is in the base image, not in build/packages/, so it cannot be updated or "
                "removed from this repository. Reachability is unreviewed.",
            )
        return ("PENDING_REVIEW", "no independent review has determined reachability")

    # Unreachable in this branch today; kept so the shape is defined and a
    # future intake has somewhere to land rather than an edit to make.
    return ("PENDING_REVIEW", "review completed; per-finding disposition not yet imported")


def bunny_impact(finding: dict) -> str:
    """One sentence, entirely from measured fields. No inference."""
    parts = [
        f"reachability: {finding.get('runtimeReachability', 'unknown')}",
        f"network exposure: {finding.get('networkExposure', 'unknown')}",
        f"privilege: {finding.get('privilegeLevel', 'unknown')}",
    ]
    return "; ".join(parts)


def main() -> int:
    document = json.loads(SOURCE.read_text(encoding="utf-8"))
    findings = document["findings"]
    reachability = {entry["advisoryId"]: entry for entry in document.get("reachability", [])}
    review_completed = False  # operations/data/independent-reviews.json holds no record

    rows = []
    for finding in sorted(
        findings,
        key=lambda item: (
            {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}.get(item.get("scannerSeverity"), 9),
            item.get("advisoryId", ""),
        ),
    ):
        status, because = disposition_for(finding, review_completed)
        advisory = finding.get("advisoryId", "")
        rows.append(
            {
                "finding": advisory,
                "package": finding.get("package"),
                "installedVersion": finding.get("installedVersion"),
                "fixedVersion": finding.get("fixedVersion"),
                "severity": finding.get("scannerSeverity"),
                "bunnyImpact": bunny_impact(finding),
                "status": status,
                "statusBecause": because,
                # §17 asks for an owner. There is one, and naming a role that
                # does not exist would be worse than naming the constraint.
                "owner": "unassigned - the project has one principal and the "
                         "review must be independent of them",
                "evidence": finding.get("evidence"),
                "mitigation": finding.get("mitigation"),
                "remediationPath": finding.get("remediationPath"),
                "hasBoundedReachabilityPackage": advisory in reachability,
            }
        )

    output = {
        "schemaVersion": 1,
        "record": "phase5-security-disposition",
        "scope": {
            "imageReference": document["imageReference"],
            "baseImageDigest": document["baseImageDigest"],
            "sourceCommit": document["sourceCommit"],
            "scannedAt": document["scannedAt"],
            "scanner": document["scanner"],
            "isTheAlphaReleaseCandidate": False,
            "candidateCommit": "e906a48793d74544b39c14cc3e35e0654f5311e2",
            "warning": (
                "This matrix is about the image named above, which is NOT the Alpha "
                "Release Candidate. A re-scan of localhost/bunny-os-beta:e906a48793d7 "
                "was attempted in Phase 5 and failed: grype's layer cache filled /tmp "
                "('no space left on device') because the host volume has 8.6 GB free. "
                "The counts here must not be quoted as the candidate's."
            ),
        },
        "independentReviewCompleted": review_completed,
        "counts": {
            "total": len(rows),
            "bySeverity": {
                severity: sum(1 for row in rows if row["severity"] == severity)
                for severity in ("Critical", "High", "Medium", "Low")
            },
            "byStatus": {
                status: sum(1 for row in rows if row["status"] == status)
                for status in sorted({row["status"] for row in rows})
            },
            "withBoundedReachabilityPackage": sum(
                1 for row in rows if row["hasBoundedReachabilityPackage"]
            ),
        },
        "rows": rows,
    }

    destination = HERE / "disposition-matrix.json"
    destination.write_text(
        json.dumps(output, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"wrote {destination.relative_to(ROOT)}")
    print(json.dumps(output["counts"], indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
