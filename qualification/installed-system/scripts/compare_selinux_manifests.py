#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Compare applied SELinux contexts against the intended manifest, and classify.

Every difference lands in exactly one state, and one state blocks:

    EXPECTED_RUNTIME_PATH       paths the policy labels at runtime and the
                                archive never carries (declared, not inferred)
    FIRST_BOOT_GENERATED        paths first boot creates (declared list)
    POLICY_DEFECT               applied and intended disagree about a path
                                both know
    INSTALLER_LABELING_DEFECT   the installer deployed a file with no label
                                or the default label where policy intends
                                a specific one
    UNRESOLVED                  everything else — and UNRESOLVED blocks the
                                SELinux prerequisite, because a difference
                                nobody classified is a difference nobody
                                understands

The declared lists live beside the scenarios, in
``fixtures/selinux-expected-differences.json``, so a new expected path is a
reviewed change with a reason, not an edit to a comparison script.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
from pathlib import Path
import sys

STATES = (
    "EXPECTED_RUNTIME_PATH",
    "FIRST_BOOT_GENERATED",
    "POLICY_DEFECT",
    "INSTALLER_LABELING_DEFECT",
    "UNRESOLVED",
)


def normalise(context: str) -> str:
    """Compare user:role:type, not sensitivity ranges: intended manifests from
    matchpathcon carry s0 explicitly while xattrs sometimes elide categories.
    The type is the enforcement boundary; a range-only difference is recorded
    but does not make two contexts different types."""
    parts = context.split(":")
    return ":".join(parts[:3]) if len(parts) >= 3 else context


def main() -> int:
    parser = argparse.ArgumentParser(prog="compare_selinux_manifests")
    parser.add_argument("--intended", required=True, type=Path)
    parser.add_argument("--applied", required=True, type=Path)
    parser.add_argument("--expected-differences", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    intended_doc = json.loads(args.intended.read_text(encoding="utf-8"))
    applied_doc = json.loads(args.applied.read_text(encoding="utf-8"))
    declared = json.loads(args.expected_differences.read_text(encoding="utf-8"))

    intended = {
        "/" + path.lstrip("/"): context
        for path, context in (intended_doc.get("intendedSelinuxContexts") or {}).items()
    }
    applied = applied_doc.get("appliedSelinuxContexts") or {}
    if not intended or not applied:
        print("BLOCKED: an empty manifest on either side is a collection failure, "
              "not a comparison input.", file=sys.stderr)
        return 2

    runtime_globs = declared.get("expectedRuntimePaths") or []
    firstboot_globs = declared.get("firstBootGenerated") or []

    def declared_state(path: str) -> str | None:
        for glob in runtime_globs:
            if fnmatch.fnmatch(path, glob):
                return "EXPECTED_RUNTIME_PATH"
        for glob in firstboot_globs:
            if fnmatch.fnmatch(path, glob):
                return "FIRST_BOOT_GENERATED"
        return None

    differences: dict[str, list[dict]] = {state: [] for state in STATES}
    matched = 0

    for path in sorted(set(intended) | set(applied)):
        want = intended.get(path)
        have = applied.get(path)
        if want is not None and have is not None:
            if normalise(want) == normalise(have):
                matched += 1
                continue
            state = declared_state(path) or "POLICY_DEFECT"
        elif want is None:
            # Applied-only path: something on the installed system the archive
            # never described. Runtime and first-boot paths are the expected
            # shapes; anything else is unresolved until a human classifies it.
            state = declared_state(path) or "UNRESOLVED"
        else:
            # Intended-only path: policy describes it, the installed system
            # lacks it or lacks its label. A missing label where the deployer
            # was responsible is the installer's defect.
            if have is None and path in applied_doc.get("unlabelledPaths", []):
                state = "INSTALLER_LABELING_DEFECT"
            else:
                state = declared_state(path) or "UNRESOLVED"
        differences[state].append({
            "path": path, "intended": want, "applied": have,
        })

    unresolved = len(differences["UNRESOLVED"])
    defects = len(differences["POLICY_DEFECT"]) + len(differences["INSTALLER_LABELING_DEFECT"])
    result = "PASS" if unresolved == 0 and defects == 0 else "BLOCKED"

    document = {
        "schemaVersion": 1,
        "matchedPaths": matched,
        "counts": {state: len(entries) for state, entries in differences.items()},
        "differences": {
            state: entries[:500] for state, entries in differences.items()
        },
        "truncated": {
            state: max(0, len(entries) - 500) for state, entries in differences.items()
        },
        "result": result,
        "note": (
            "UNRESOLVED blocks: a difference nobody classified is a difference "
            "nobody understands. Expected states come from the declared fixture, "
            "which is a reviewed file, not a heuristic."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=1, sort_keys=True) + "\n",
                           encoding="utf-8")
    print(f"applied-selinux comparison: {result}")
    print(f"  matched {matched}")
    for state in STATES:
        if differences[state]:
            print(f"  {state:26} {len(differences[state])}")
    return 0 if result == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
