#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Generate the stable evidence record with digests computed from real files.

Digests are never typed by hand. Each record names a file that exists in the
working tree and this script hashes it, so a record cannot claim a digest for
content nobody produced. Re-running after regenerating evidence updates the
digests; a record whose file changed without a regeneration will fail
``stable-evidence-report`` rather than silently pass.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in os.sys.path:
    os.sys.path.insert(0, str(ROOT))

from release.evidence import EVIDENCE_CATEGORIES, file_digest

MATRICES = "operations/data/qualification-matrices.json"

#: (category, id, description, evidenceType, reference, result, reviewer, notes)
SPEC = [
    (
        "Build",
        "build-beta-image",
        "Beta profile built from digest-pinned base sha256:fb71f099 and normalised to a reproducible archive.",
        "command-output",
        "evidence/build/beta-archive-digest.txt",
        "PASS",
        "Bunny OS maintainer",
        "Two isolated workspaces produced byte-identical archives; see operations/data/builders.json.",
    ),
    (
        "Signing",
        "signing-production-keys",
        "Production release signing with a key from a recorded key ceremony.",
        "generated-report",
        "operations/data/signing-keys.json",
        "FAIL",
        "Bunny OS maintainer",
        "No production key of any role exists. The development signing drill passes all nine checks, "
        "but development keys are refused by require_production_key and can never satisfy this row.",
    ),
    (
        "Vulnerability",
        "vulnerability-position-beta",
        "Grype scan of the beta profile with a per-finding disposition for every Critical and High.",
        "command-output",
        "evidence/vulnerability/beta-grype.json",
        "FAIL",
        "Bunny OS maintainer",
        "59 fixable findings: 8 Critical, 28 High, 23 Medium. 24 unique Critical/High pairs are "
        "dispositioned Unknown because the vulnerable code path could not be shown inactive.",
    ),
    (
        "Licence",
        "licence-scan-and-decision",
        "Owner licence decision applied to the tree, plus a clean licence scan over the beta SBOM.",
        "command-output",
        "evidence/build/beta-license-scan.log",
        "PASS",
        "Project owner",
        "6077 SPDX records, 0 unresolved, no prohibited markers. Split licence recorded in "
        "operations/data/licence-decision.json and reflected by LICENSE, per-directory files and SPDX headers.",
    ),
    (
        "Installer",
        "installation-matrix",
        "Twelve disposable-disk installation scenarios.",
        "generated-report",
        MATRICES,
        "NOT_RUN",
        "Bunny OS maintainer",
        "The install harness is interactive and no live ISO has been built.",
    ),
    (
        "Encryption",
        "encryption-matrix",
        "Nine LUKS, recovery-key, TPM and Secure Boot interaction scenarios.",
        "generated-report",
        MATRICES,
        "NOT_RUN",
        "Bunny OS maintainer",
        "Depends on a completed installation; encrypted automation is interactive-only.",
    ),
    (
        "Secure Boot",
        "secure-boot",
        "Secure Boot positive and negative paths on firmware that enforces them.",
        "generated-report",
        MATRICES,
        "NOT_RUN",
        "Bunny OS maintainer",
        "Requires physical firmware. No virtual result substitutes for this row.",
    ),
    (
        "Update",
        "update-matrix",
        "Thirteen update scenarios including interrupted, invalid-signature and expired-metadata paths.",
        "generated-report",
        MATRICES,
        "NOT_RUN",
        "Bunny OS maintainer",
        "vm-upgrade-test exits 3: no signed update manifest has been published.",
    ),
    (
        "Rollback",
        "rollback-matrix",
        "Manual, automatic and recovery-assisted rollback.",
        "generated-report",
        MATRICES,
        "NOT_RUN",
        "Bunny OS maintainer",
        "vm-rollback-test exits 3: there is no previous release to roll back to.",
    ),
    (
        "Recovery",
        "recovery-media-matrix",
        "Eleven independent recovery-media capabilities.",
        "generated-report",
        MATRICES,
        "NOT_RUN",
        "Bunny OS maintainer",
        "vm-recovery-test exits 3: no signed recovery ISO exists. No claim may rest on source inspection.",
    ),
    (
        "Migration",
        "migration",
        "Supported migration between two real releases.",
        "generated-report",
        MATRICES,
        "NOT_RUN",
        "Bunny OS maintainer",
        "Requires two published releases. None exists.",
    ),
    (
        "Multi-user",
        "multi-user-isolation",
        "Cross-user isolation on an installed multi-user system.",
        "generated-report",
        MATRICES,
        "NOT_RUN",
        "Bunny OS maintainer",
        "Source tests pass; no installed system has been exercised.",
    ),
    (
        "Local-only",
        "local-only-operation",
        "An installed system operated offline with a local model.",
        "generated-report",
        MATRICES,
        "NOT_RUN",
        "Bunny OS maintainer",
        "Requires an installation.",
    ),
    (
        "Bunny-disabled",
        "bunny-disabled-operation",
        "An installed system operated with Bunny disabled.",
        "generated-report",
        MATRICES,
        "NOT_RUN",
        "Bunny OS maintainer",
        "Requires an installation.",
    ),
    (
        "Privacy",
        "privacy-runtime",
        "Traffic capture on an installed system plus an independent privacy review.",
        "generated-report",
        MATRICES,
        "NOT_RUN",
        "Bunny OS maintainer",
        "A quiet-boot capture of a booted image exists from an earlier run and disclosed NTP contact, "
        "but no installed-system capture and no independent review exist.",
    ),
    (
        "Accessibility",
        "accessibility-matrix",
        "Fourteen essential accessibility workflows driven with assistive technology.",
        "generated-report",
        MATRICES,
        "NOT_RUN",
        "Bunny OS maintainer",
        "No workflow has been driven. Static tests are explicitly not sufficient here.",
    ),
    (
        "Hardware",
        "physical-hardware",
        "At least one x86-64 UEFI physical machine qualified end to end.",
        "generated-report",
        "operations/data/hardware-evidence.json",
        "NOT_RUN",
        "Bunny OS maintainer",
        "The intake process exists and the reports array is empty. This needs a device, not more tests.",
    ),
    (
        "Performance",
        "performance-baseline",
        "Boot, session and interaction performance against the documented targets.",
        "generated-report",
        MATRICES,
        "NOT_RUN",
        "Bunny OS maintainer",
        "No installed system to measure.",
    ),
    (
        "Soak",
        "multi-day-soak",
        "Multi-day soak on a candidate build.",
        "generated-report",
        MATRICES,
        "NOT_RUN",
        "Bunny OS maintainer",
        "Requires an installed candidate and elapsed time.",
    ),
    (
        "Support",
        "support-capacity",
        "Confirmed maintenance and security-response capacity for a supported release.",
        "generated-report",
        "operations/data/pilot-requirements.json",
        "NOT_RUN",
        "Bunny OS maintainer",
        "One maintainer, no funded rota, no second release signer. See SUSTAINABILITY_REPORT.md.",
    ),
]


def source_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--generated-at", default="2026-07-29T23:00:00Z")
    parser.add_argument("--out", type=Path, default=ROOT / "operations/data/release-evidence.json")
    args = parser.parse_args()

    commit = source_commit()
    records = []
    missing = []
    for category, identifier, description, kind, reference, result, reviewer, notes in SPEC:
        target = ROOT / reference
        if not target.is_file():
            missing.append(reference)
            continue
        records.append(
            {
                "id": identifier,
                "category": category,
                "description": description,
                "evidenceType": kind,
                "evidenceReference": reference,
                "contentDigest": file_digest(target),
                "generatedAt": args.generated_at,
                "sourceCommit": commit,
                "result": result,
                "reviewer": reviewer,
                "notes": notes,
            }
        )

    if missing:
        print("BLOCKED: these evidence artifacts do not exist:")
        for name in missing:
            print(f"  {name}")
        return 2

    covered = {record["category"] for record in records}
    uncovered = [name for name in EVIDENCE_CATEGORIES if name not in covered]
    if uncovered:
        print("BLOCKED: no record written for: " + ", ".join(uncovered))
        return 2

    payload = {
        "schemaVersion": 1,
        "recordedOn": args.generated_at[:10],
        "sourceCommit": commit,
        "note": (
            "Generated by scripts/build_evidence_record.py. Digests are computed from the files on "
            "disk. Two of twenty categories pass. Everything else is blocking, and each record says "
            "why."
        ),
        "records": sorted(records, key=lambda item: (item["category"], item["id"])),
    }
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")

    passing = sum(1 for record in records if record["result"] == "PASS")
    print(f"wrote {args.out}")
    print(f"{len(records)} records across {len(covered)} categories; {passing} PASS, {len(records) - passing} blocking")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
