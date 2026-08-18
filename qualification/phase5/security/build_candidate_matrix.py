# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The §17 disposition matrix, built against the Alpha Release Candidate itself.

The first attempt at this matrix (:mod:`build_disposition_matrix`) was built
from ``operations/data/vulnerability-disposition.json`` — a 2026-07-29 scan of
``localhost/bunny-os-beta:79bb99ddb39d``, which is not the candidate.

The second was built from a ``grype dir:`` scan of the candidate's overlay,
mounted in place. That route reported **one** Critical finding where Phase 4
had eight, and the difference was not the product improving. grype matches Go
findings at *function* granularity when it can read the binary and at *module*
granularity when it is handed an SBOM, and the seven ``golang.org/x/crypto``
Criticals fall out at function granularity. The package is still in the image,
the advisories are still Critical in the database, and the ranges still apply
— ``SCAN_ROUTE_DISCREPANCY.md`` has the chain.

So this matrix is built from the **SBOM** scan: module granularity, which is
the granularity Phase 4's number is in, the granularity the release gate has
always used, and — by grype's own warning about the alternative "reporting
false positives" — the conservative one. Building it from the function-level
result would have disposed of seven Critical findings on a scanner's say-so,
which ``release/vulnerability.py`` rejects at parse time and §17 forbids in
words.

**Counting, which is the whole difficulty.** The scan reports 238 matches. That
is not 238 vulnerabilities. It is **80 distinct advisories**, inflated twice
over: once because an advisory is counted per affected package, and once
because the image carries an ostree repository whose objects are hardlinks to
the files in ``/usr``, so every Go binary is catalogued at two paths.

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
SCAN = HERE / "scan" / "candidate-sbom-fixed.json"

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
            "method": "grype sbom: over the candidate's own SPDX SBOM, catalogued by syft "
                      "from the image's overlay mounted in place (podman create + podman "
                      "mount). Module granularity.",
            "matchGranularity": "module",
            "whyNotTheFilesystemRoute": (
                "grype dir: over the same mounted overlay matches Go findings at function "
                "granularity and reports 1 Critical instead of 8, excluding the seven "
                "golang.org/x/crypto advisories because their vulnerable functions are not "
                "linked into /usr/bin/skopeo. The package is present, the advisories are "
                "active and Critical in the database, and the ranges apply. A scanner's "
                "symbol analysis is not the independent review release/vulnerability.py "
                "requires, so the conservative granularity is the one recorded. See "
                "SCAN_ROUTE_DISCREPANCY.md."
            ),
            "methodDiffersFromPhase4": (
                "build/scripts/security-scan.sh uses grype oci-archive: on an exported "
                "archive. That is also module granularity, so the Critical counts are "
                "comparable. It is not equivalent in coverage: the retained Phase 4 scans "
                "contain zero rpm findings, and this one contains 26 distinct rpm "
                "advisories from /usr/share/rpm/rpmdb.sqlite."
            ),
            "scope": "--only-fixed, the same scope as security-scan.sh",
        },
        "counting": {
            "rawMatches": len(matches),
            "distinctAdvisories": len(rows),
            "note": (
                "The raw match count is not a vulnerability count. It is inflated twice: "
                "an advisory is reported once per affected package "
                "(FEDORA-2026-c53019ed4f accounts for 15 matches from one rpmdb), and the "
                "image's ostree objects are hardlinks to the files in /usr, so every Go "
                "binary is catalogued at two paths. Every figure below counts distinct "
                "advisories."
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
            "likeForLike": (
                "Go modules only, module granularity, nineteen days apart: Phase 4 40 "
                "distinct (8 Critical, 17 High, 14 Medium); here 45 distinct (8 Critical, "
                "18 High, 17 Medium). Five new advisories, Criticals unchanged."
            ),
            "reading": (
                "The Critical count is 8, exactly as Phase 4 recorded it. The earlier "
                "Phase 5 figure of 1 was a function-granularity measurement compared "
                "against a module-granularity baseline and is withdrawn as a statement "
                "about this candidate's position. The larger totals here are coverage, "
                "not drift: Phase 4's scan catalogued no rpm at all."
            ),
        },
        "identicalAcrossBuilds": {
            "controlImage": "localhost/bunny-os-beta:376acf0e076f",
            "route": "the filesystem route, compared against itself",
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
