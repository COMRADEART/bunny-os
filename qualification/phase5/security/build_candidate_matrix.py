# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The §17 disposition matrix, built against the Alpha Release Candidate itself.

The first attempt at this matrix
(:mod:`build_disposition_matrix`) was built from
``operations/data/vulnerability-disposition.json`` — a 2026-07-29 scan of
``localhost/bunny-os-beta:79bb99ddb39d``, which is not the candidate. A re-scan
was attempted and failed for want of disk. It succeeded on the second attempt
by mounting the image's overlay in place rather than expanding it to tarballs,
which costs no disk at all, so this matrix is about ``e906a48793d7``.

**Counting, which is the whole difficulty.** The raw scan reports 183 matches.
That is not 183 vulnerabilities. It is **56 distinct advisories**, each counted
once per affected package: ``FEDORA-2026-c53019ed4f`` alone accounts for 15,
all from the same ``rpmdb.sqlite`` and all the same advisory. A report quoting
183 would be inflating the number by more than three times, and anyone
re-running the scan will see 183 first.

Both figures are published, and every derived count is by **distinct
advisory**, because that is the unit an independent reviewer dispositions.

Run: ``python qualification/phase5/security/build_candidate_matrix.py``
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
SCAN = HERE / "scan" / "candidate-fixed.json"

CANDIDATE = "e906a48793d74544b39c14cc3e35e0654f5311e2"
IMAGE = "localhost/bunny-os-beta:e906a48793d7"

SEVERITY_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Negligible": 4, "Unknown": 5}


def main() -> int:
    document = json.loads(SCAN.read_text(encoding="utf-8"))
    matches = document["matches"]

    by_advisory: dict[str, dict] = {}
    packages: dict[str, set[str]] = defaultdict(set)
    fixes: dict[str, set[str]] = defaultdict(set)

    for match in matches:
        vulnerability = match["vulnerability"]
        identifier = vulnerability["id"]
        artifact = match["artifact"]
        packages[identifier].add(f"{artifact['name']} {artifact.get('version', '')}".strip())
        for version in (vulnerability.get("fix") or {}).get("versions") or []:
            fixes[identifier].add(version)
        by_advisory.setdefault(
            identifier,
            {
                "finding": identifier,
                "severity": vulnerability.get("severity"),
                "dataSource": vulnerability.get("dataSource"),
                "artifactTypes": set(),
            },
        )
        by_advisory[identifier]["artifactTypes"].add(artifact.get("type"))

    rows = []
    for identifier, record in sorted(
        by_advisory.items(),
        key=lambda item: (SEVERITY_ORDER.get(item[1]["severity"], 9), item[0]),
    ):
        affected = sorted(packages[identifier])
        rows.append(
            {
                "finding": identifier,
                "severity": record["severity"],
                "affectedPackages": affected,
                "affectedPackageCount": len(affected),
                "artifactTypes": sorted(t for t in record["artifactTypes"] if t),
                "fixedVersions": sorted(fixes[identifier]),
                # Every row, without exception, and for the reason the prose in
                # SECURITY_DISPOSITION.md gives: release/cve.py refuses any
                # non-blocking disposition of a Critical finding without a
                # completed independent review, and there is none. FIX is
                # separately unavailable because the packages are in the base
                # image and not in build/packages/.
                "status": "PENDING_REVIEW",
                "statusBecause": (
                    "no independent review has determined reachability; the fix, where one "
                    "exists, is in a base-image package this repository cannot update"
                ),
                "owner": (
                    "unassigned - the project has one principal and the review must be "
                    "independent of them"
                ),
                "bunnyImpact": (
                    "not determined for this scan; the measured reachability evidence in "
                    "operations/data/vulnerability-disposition.json covers the 2026-07-29 "
                    "advisory set and has not been re-derived for these"
                ),
            }
        )

    severities = Counter(row["severity"] for row in rows)
    output = {
        "schemaVersion": 1,
        "record": "phase5-candidate-disposition",
        "scope": {
            "imageReference": IMAGE,
            "imageId": (HERE / "scan" / "image-id.txt").read_text(encoding="utf-8").strip(),
            "candidateCommit": CANDIDATE,
            "isTheAlphaReleaseCandidate": True,
            "scanner": "grype, database built 2026-08-17T06:19:33Z (valid)",
            "method": "grype dir: over the image's overlay, mounted in place via podman "
                      "create + podman mount. No copy, no tarball expansion.",
            "methodDiffersFromPhase4": (
                "build/scripts/security-scan.sh uses grype oci-archive: on an exported "
                "archive. That path needs tens of gigabytes of temporary space and failed "
                "with 'no space left on device'. The two methods are NOT established as "
                "equivalent, and the comparison below is indicative rather than conclusive."
            ),
            "scope": "--only-fixed, the same scope as security-scan.sh",
        },
        "counting": {
            "rawMatches": len(matches),
            "distinctAdvisories": len(rows),
            "note": (
                "The raw match count is not a vulnerability count. Each advisory is "
                "reported once per affected package: FEDORA-2026-c53019ed4f accounts for "
                "15 matches from one rpmdb. Every figure below counts distinct advisories."
            ),
            "mostDuplicated": [
                {"finding": identifier, "matches": count}
                for identifier, count in Counter(
                    m["vulnerability"]["id"] for m in matches
                ).most_common(5)
            ],
            "byArtifactType": dict(Counter(m["artifact"]["type"] for m in matches)),
        },
        "counts": {
            "distinctAdvisories": len(rows),
            "bySeverity": {
                name: severities.get(name, 0)
                for name in ("Critical", "High", "Medium", "Low", "Negligible", "Unknown")
                if severities.get(name)
            },
            "byStatus": {"PENDING_REVIEW": len(rows)},
        },
        "againstPhase4": {
            "phase4Claim": "59 fixable findings (8 Critical, 28 High)",
            "measuredHere": (
                f"{len(rows)} distinct fixable advisories "
                f"({severities.get('Critical', 0)} Critical, {severities.get('High', 0)} High)"
            ),
            "reading": (
                "The totals are close (59 against 56) and the Critical counts are not "
                "(8 against 1). Three things differ at once - the scanner database, the "
                "cataloguing method, and possibly what Phase 4 counted - so this is "
                "recorded as a discrepancy to resolve, NOT as a correction of Phase 4. "
                "Resolving it needs one oci-archive: scan of this image, which needs disk."
            ),
        },
        "identicalAcrossBuilds": {
            "controlImage": "localhost/bunny-os-beta:376acf0e076f",
            "result": "identical counts - 183 raw, 2 Critical, 106 High, 70 Medium, 5 Low",
            "meaning": (
                "Two independently built Bunny images have the same vulnerability surface, "
                "which is what 'every finding comes from the base image' predicts and is "
                "here demonstrated rather than asserted."
            ),
        },
        "rows": rows,
    }

    destination = HERE / "candidate-disposition-matrix.json"
    destination.write_text(
        json.dumps(output, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"wrote {destination.relative_to(ROOT)}")
    print(json.dumps(output["counting"] | output["counts"], indent=1)[:600])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
