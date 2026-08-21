#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Assemble the independent-review package for the frozen Alpha candidate.

One machine-readable document a reviewer can work from and reproduce:
artifact identity, and every Critical and High finding with the §5 fields —
advisory, affected package, installed version, fixed version, affected
binary, exposure, exploitability where any evidence exists, and a current
disposition drawn only from {AFFECTED, NOT_AFFECTED, UNKNOWN,
REQUIRES_REVIEW}.

Two collapses this builder structurally refuses (§5):
  * "package vulnerable" never becomes "every binary vulnerable" — the
    per-binary rows from Phase 7 (Highs) and Phase 6 (Critical symbols) are
    carried verbatim, one entry per binary;
  * "one binary unaffected" never becomes "package fixed" — the
    finding-level disposition is computed independently of any single
    binary's verdict.

Disposition policy, stated once: every finding is REQUIRES_REVIEW — the
review this package exists for has not happened — except the rows whose
version evidence cannot be ordered at all (pseudo-versions), which are
UNKNOWN, exactly as unresolved as they are. Nothing here is NOT_AFFECTED,
because no evidence in this repository establishes that for any finding, and
UNKNOWN is never replaced by anything without evidence.

Deterministic: same inputs, same output. Fail-closed: a Critical/High row
this script cannot classify stops the build rather than passing through
unenriched.
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
HERE = pathlib.Path(__file__).resolve().parent

MATRIX = ROOT / "qualification/phase5/security/candidate-disposition-matrix.json"
GO_HIGH = ROOT / "qualification/phase7/security/high-go-version-analysis.json"
SYMBOLS = ROOT / "qualification/phase6/security/evidence/symbols.json"
EXPOSURE = ROOT / "qualification/phase6/security/evidence/exposure.json"
OUTPUT = HERE / "review-package.json"

ARTIFACT = {
    "identifier": "e906a48793d7",
    "imageDigest": "sha256:c87a6616008ce34f97840f63814e08fdb33574b52202fbb4841b7f5aa7f8562d",
    "qcow2Sha256": "497add9a77db2db02bf2541e85b04b0e285c1833d2c8220d193d0d413a6ce867",
    "isoSha256": "823d50caba35afe72452768affd5f6fa0ac8cfc13c164f0e1bc909fa887ab421",
    "ociTarSha256": "205a77f1b6cdf33915bce3afceb0914d6af25f97b434cf2128aec04d199b43dd",
    "rawSha256": "a6ee06dcbc0ed3aa22c9ea07c339882eb97c7f16ce906b654c9a1e1119849d46",
    "sourceCommit": "e906a48793d74544b39c14cc3e35e0654f5311e2",
    "sourceDateEpoch": 1786986334,
    "signingStatus": "UNSIGNED",
    "provenance": "BUNNY-MANIFEST.json and provenance.json in the retained archive; digests recomputed from bytes 2026-08-18 (qualification/phase7/baseline/freeze.log)",
    "frozen": True,
}

DISPOSITIONS = frozenset({"AFFECTED", "NOT_AFFECTED", "UNKNOWN", "REQUIRES_REVIEW"})


def load(path: pathlib.Path):
    return json.loads(path.read_text(encoding="utf-8"))


def build_go_row(row, go_high, symbols) -> dict:
    finding = row["finding"]
    binaries: dict = {}
    exploitability = "none available"
    disposition = "REQUIRES_REVIEW"

    if row["severity"] == "Critical":
        # Phase 6 measured the named vulnerable symbols per binary.
        for path, data in sorted(symbols["binaries"].items()):
            advisory = (data.get("advisories") or {}).get(finding)
            if advisory is None:
                continue
            binaries[path] = {
                "embeddedVersions": advisory.get("embeddedVersions"),
                "fixedVersion": advisory.get("fixedVersion"),
                "importPathPresent": advisory.get("importPathPresent"),
                "vulnerableSymbolsNamed": advisory.get("symbolsNamed"),
                "vulnerableSymbolsPresent": advisory.get("symbolsPresent"),
                "symbolsPresent": [s.get("symbol") for s in (advisory.get("present") or [])],
                "symbolsAbsent": advisory.get("absent"),
            }
        if binaries:
            exploitability = (
                "symbol-level: the advisory's named vulnerable functions were "
                "searched in each binary's bytes in both linker spellings "
                "(qualification/phase6/security/symbol_probe.py)"
            )
    else:
        analysed = next((r for r in go_high["rows"] if r["finding"] == finding), None)
        if analysed is None:
            raise SystemExit(f"REFUSED: Go High finding {finding} has no Phase 7 analysis row")
        for path, modules in sorted(analysed["binaries"].items()):
            binaries[path] = {
                module: {"installedVersion": data["embedded"], "versionVerdict": data["verdict"]}
                for module, data in sorted(modules.items())
            }
        verdicts = [
            data["verdict"]
            for modules in analysed["binaries"].values()
            for data in modules.values()
        ]
        if verdicts and all("UNDETERMINED" in v for v in verdicts):
            # The pseudo-version rows: explicitly unresolved, not guessed.
            disposition = "UNKNOWN"
        exploitability = "none available (symbols not named in shipped evidence for High findings)"

    return {
        "affectedBinaries": binaries,
        "exposure": (
            "modules embedded in the named binaries; the binaries are present on "
            "the image. Reachability is the reviewer's question - see "
            "qualification/phase6/security/REVIEW_PACKAGE.md section 4 for the one "
            "advisory (grpc server-side) where the project explicitly offers no view"
        ),
        "exploitability": exploitability,
        "disposition": disposition,
    }


def build_rpm_row(row, exposure) -> dict:
    packages = {}
    for entry in row.get("affectedPackages") or []:
        name = entry.split(" ")[0]
        record = (exposure.get("rpmPackages") or {}).get(name)
        packages[name] = {
            "installedVersion": entry.split(" ", 1)[1] if " " in entry else None,
            "presenceMeasured": None if record is None else record.get("installed"),
            "rpmRecord": None if record is None else record.get("record"),
        }
    return {
        "affectedBinaries": {
            "rpm-owned files": "the package's own binary/library set; per-file "
            "attribution not derived - the rpm record above is the unit"
        },
        "affectedPackagesDetail": packages,
        "exposure": "installed on the image, confirmed by rpm query in a container from the image (Phase 6 exposure probe)",
        "exploitability": "none available",
        "disposition": "REQUIRES_REVIEW",
    }


def build_python_row(row, exposure) -> dict:
    return {
        "affectedBinaries": {"python distributions": exposure.get("pythonDistributions")},
        "exposure": "distribution present under /usr/lib/python3.14/site-packages (Phase 6 exposure probe)",
        "exploitability": "none available",
        "disposition": "REQUIRES_REVIEW",
    }


def build_unmapped_row(row) -> dict:
    return {
        "affectedBinaries": {},
        "exposure": (
            "the scanner mapped this advisory to no package type; the installed "
            "kernel is named in affectedPackages and its version exceeds every "
            "listed fixed version - recorded as a fact for the reviewer, decided "
            "by nobody here"
        ),
        "exploitability": "none available",
        "disposition": "REQUIRES_REVIEW",
    }


def main() -> int:
    matrix = load(MATRIX)
    go_high = load(GO_HIGH)
    symbols = load(SYMBOLS)
    exposure = load(EXPOSURE)

    findings = []
    for row in matrix["rows"]:
        severity = row.get("severity")
        if severity not in ("Critical", "High"):
            continue
        kinds = row.get("artifactTypes") or []
        if kinds == ["go-module"]:
            enriched = build_go_row(row, go_high, symbols)
        elif kinds == ["rpm"]:
            enriched = build_rpm_row(row, exposure)
        elif kinds == ["python"]:
            enriched = build_python_row(row, exposure)
        elif kinds == ["UnknownPackage"]:
            enriched = build_unmapped_row(row)
        else:
            raise SystemExit(f"REFUSED: unclassifiable Critical/High row {row.get('finding')}: {kinds}")
        if enriched["disposition"] not in DISPOSITIONS:
            raise SystemExit(f"REFUSED: illegal disposition for {row['finding']}")
        findings.append({
            "advisory": row["finding"],
            "severity": severity,
            "affectedPackages": row.get("affectedPackages"),
            "fixedVersions": row.get("fixedVersions"),
            "artifactTypes": kinds,
            **enriched,
        })

    criticals = sum(1 for f in findings if f["severity"] == "Critical")
    highs = sum(1 for f in findings if f["severity"] == "High")
    if criticals != 8 or highs != 36:
        raise SystemExit(f"REFUSED: expected 8 Critical + 36 High, built {criticals}+{highs}")

    package = {
        "schemaVersion": 1,
        "purpose": "independent security review of the frozen Alpha candidate",
        "artifact": ARTIFACT,
        "allowedReviewOutcomes": ["APPROVED", "APPROVED_WITH_CONDITIONS", "BLOCKED", "MORE_EVIDENCE_REQUIRED"],
        "dispositionVocabulary": sorted(DISPOSITIONS),
        "counts": {
            "critical": criticals,
            "high": highs,
            "dispositionUnknown": sum(1 for f in findings if f["disposition"] == "UNKNOWN"),
            "dispositionRequiresReview": sum(1 for f in findings if f["disposition"] == "REQUIRES_REVIEW"),
        },
        "findings": sorted(findings, key=lambda f: (f["severity"] != "Critical", f["advisory"])),
        "reproduction": {
            "inventory": "qualification/phase5/security/candidate-disposition-matrix.json",
            "perBinaryHighAnalysis": "qualification/phase7/security/high-go-version-analysis.json + analyze_high_go.py (deterministic)",
            "criticalSymbols": "qualification/phase6/security/evidence/symbols.json + symbol_probe.py",
            "exposure": "qualification/phase6/security/evidence/exposure.json + exposure_probe.py",
            "thisPackage": "qualification/phase8/security-review/build_package.py (deterministic; rerun and diff)",
        },
    }
    OUTPUT.write_text(
        json.dumps(package, indent=1, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n",
    )
    print(f"{criticals} Critical + {highs} High findings packaged; "
          f"{package['counts']['dispositionUnknown']} UNKNOWN (pseudo-versions), "
          f"{package['counts']['dispositionRequiresReview']} REQUIRES_REVIEW")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
