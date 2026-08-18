#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The per-advisory version analysis for the Go High findings, done.

Phase 6 named this as work outstanding: the eight Criticals got a
per-binary version-and-symbol analysis and the nineteen Go High findings did
not — while measuring that podman and skopeo carry *different* versions of
the same modules, so the module-level inventory's single row per advisory
merges two different questions.

This closes the version half, bound to the subject artifact rather than to
the scan image: the module versions come from the Go buildinfo embedded in
the four Go binaries on the subject disk itself
(``go-binaries-buildinfo.json``, extracted from the e906a48793d7 qcow2 by
inode-resolved path), and the advisories come from the committed inventory
(``qualification/phase5/security/candidate-disposition-matrix.json``).

What it deliberately does not do: name vulnerable symbols for these
advisories (the shipped evidence records none for them — recorded as
``symbols: not named in shipped evidence``), and it dispositions nothing.
A row here saying ``NOT_EMBEDDED`` is an argument a reviewer can check, not
a disposition.

Deterministic: same two inputs, same output. Run from the repository root:

    python qualification/phase7/security/analyze_high_go.py
"""

from __future__ import annotations

import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[3]
MATRIX = ROOT / "qualification/phase5/security/candidate-disposition-matrix.json"
BUILDINFO = pathlib.Path(__file__).resolve().parent / "go-binaries-buildinfo.json"
OUTPUT = pathlib.Path(__file__).resolve().parent / "high-go-version-analysis.json"

_NUMS = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)")


def parse_version(version: str):
    """A comparable tuple, or None when the version cannot be ordered.

    Pseudo-versions (``v5.0.0-20260626...-...+dirty``) cannot be ordered
    against a release number by their leading triple — the triple names the
    *next* release the snapshot precedes... except when it doesn't, because
    distro builds re-tag. Refusing to order them is the honest answer.
    """
    if "-2026" in version or "-2025" in version or "+dirty" in version or "+incompatible" in version:
        return None
    found = _NUMS.match(version)
    if not found:
        return None
    return tuple(int(part) for part in found.groups())


def main() -> int:
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    buildinfo = json.loads(BUILDINFO.read_text(encoding="utf-8"))
    binaries = buildinfo["binaries"]

    rows = []
    for row in matrix["rows"]:
        if row.get("severity") != "High":
            continue
        if "go-module" not in (row.get("artifactTypes") or []):
            continue
        finding = row["finding"]
        modules = sorted({p.split(" ")[0] for p in row.get("affectedPackages", [])})
        fixed = row.get("fixedVersions") or []
        fixed_parsed = sorted(v for v in (parse_version(f) for f in fixed) if v)
        per_binary = {}
        for path, info in sorted(binaries.items()):
            embedded = {}
            for module in modules:
                version = info["modules"].get(module)
                main_mod = info.get("main") or [None, None]
                if version is None and module == main_mod[0]:
                    version = main_mod[1]
                if version is None:
                    continue
                parsed = parse_version(version)
                if parsed is None:
                    verdict = "UNDETERMINED_BY_VERSION (pseudo-version; needs commit-level comparison)"
                elif not fixed_parsed:
                    verdict = "UNDETERMINED_BY_VERSION (no ordered fixed version)"
                elif parsed < fixed_parsed[0]:
                    verdict = "AFFECTED_BY_VERSION"
                else:
                    verdict = "AT_OR_ABOVE_FIX"
                embedded[module] = {"embedded": version, "verdict": verdict}
            if embedded:
                per_binary[path] = embedded
        rows.append({
            "finding": finding,
            "modules": modules,
            "fixedVersions": fixed,
            "binaries": per_binary,
            "symbols": "not named in shipped evidence",
            "position": "NOT_EMBEDDED_IN_ANY_GO_BINARY" if not per_binary else None,
        })

    affected = sum(
        1 for r in rows
        if any("AFFECTED" in m["verdict"] for b in r["binaries"].values() for m in b.values())
    )
    absent = sum(1 for r in rows if r["position"] == "NOT_EMBEDDED_IN_ANY_GO_BINARY")
    undetermined = sum(
        1 for r in rows
        if r["binaries"] and not any(
            "AFFECTED" in m["verdict"] for b in r["binaries"].values() for m in b.values()
        ) and any(
            "UNDETERMINED" in m["verdict"] for b in r["binaries"].values() for m in b.values()
        )
    )
    document = {
        "schemaVersion": 1,
        "subjectArtifact": buildinfo["artifact"],
        "deployCommit": buildinfo["deployCommit"],
        "inputs": {
            "inventory": str(MATRIX.relative_to(ROOT)).replace("\\", "/"),
            "buildinfo": "qualification/phase7/security/go-binaries-buildinfo.json",
        },
        "counts": {
            "goHighFindings": len(rows),
            "affectedByVersionSomewhere": affected,
            "undeterminedPseudoVersions": undetermined,
            "notEmbeddedInAnyGoBinary": absent,
        },
        "rows": rows,
    }
    OUTPUT.write_text(
        json.dumps(document, indent=1, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n",
    )
    print(f"{len(rows)} Go High findings analysed: "
          f"{affected} affected-by-version, {undetermined} undetermined (pseudo-versions), "
          f"{absent} not embedded in any Go binary")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
