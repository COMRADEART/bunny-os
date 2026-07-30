#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Join the measured toolchain to its declared classification and emit the lock.

Two documents meet here. ``build/builder/toolchain.lock.json`` declares what
each tool is *for* — whether it can reach the artifact, and why somebody believes
so. The builder image reports what is actually installed. Neither alone is a
lock: a classification without a measurement describes an intention, and a
measurement without a classification is a version string nobody has reasoned
about.

A tool that is installed and unclassified therefore fails here rather than
being written out as ``unknown`` and failing later. ``unknown`` remains a valid
state in the schema — a lock can legitimately record one — but this generator
will not mint one silently, because the whole point of the classification is
that somebody looked.
"""

from __future__ import annotations

import argparse
import datetime as _datetime
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from release.paths import display_path  # noqa: E402
from release.supplychain import SCHEMA_VERSION, SupplyChainError, parse_builder_image_lock  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(prog="write-builder-lock")
    parser.add_argument("--toolchain", required=True, type=Path)
    parser.add_argument("--declared", required=True, type=Path)
    parser.add_argument("--builder-reference", required=True)
    parser.add_argument("--builder-digest", required=True)
    parser.add_argument("--base-reference", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--containerfile-digest", required=True)
    parser.add_argument("--lock", required=True, type=Path)
    args = parser.parse_args()

    measured = json.loads(args.toolchain.read_text(encoding="utf-8"))
    declared = json.loads(args.declared.read_text(encoding="utf-8"))
    classifications = declared.get("classifications") or {}
    absent = declared.get("absentTools") or {}

    tools: list[dict[str, str]] = []
    unclassified: list[str] = []
    missing: list[str] = []

    for entry in measured.get("tools", []):
        name = str(entry.get("name", ""))
        version = str(entry.get("version", ""))
        if version == "absent":
            if name not in absent:
                missing.append(name)
            continue
        declaration = classifications.get(name)
        if not declaration:
            unclassified.append(name)
            continue
        tools.append(
            {
                "name": name,
                "version": version,
                "classification": str(declaration.get("classification", "unknown")),
                "reason": str(declaration.get("reason", "")),
                "packageChecksum": str(entry.get("packageChecksum", "")),
                "nevra": str(entry.get("nevra", "")),
                "test": str(declaration.get("test", "")),
            }
        )

    if unclassified:
        raise SystemExit(
            "BLOCKED: these tools are installed in the builder image and carry no classification "
            "in build/builder/toolchain.lock.json: "
            + ", ".join(sorted(unclassified))
            + ".\nAn unclassified tool is one whose effect on the artifact nobody has established, "
            "and an unestablished effect cannot be assumed to be none."
        )
    if missing:
        raise SystemExit(
            "BLOCKED: these tools are absent from the builder image and are not declared absent: "
            + ", ".join(sorted(missing))
            + ".\nDeclare them in absentTools with a reason, or install them."
        )

    lock = {
        "schemaVersion": SCHEMA_VERSION,
        "builderReference": args.builder_reference,
        "builderDigest": args.builder_digest,
        "baseReference": args.base_reference,
        "baseDigest": args.base_reference.split("@", 1)[-1],
        "sourceCommit": args.source_commit,
        "containerfileDigest": args.containerfile_digest,
        "architecture": declared.get("architecture", "x86_64"),
        "tools": tools,
        "absentTools": absent,
        "builtAt": _datetime.datetime.now(_datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "runtimeRequirements": declared.get("runtimeRequirements") or {},
        "verificationStatus": "verified",
        "notes": (
            "Measured from inside the built image, joined to the declared classifications. Both "
            "builders must present this builderDigest; the hosts may differ in every other "
            "respect, which is what makes them independent."
        ),
    }

    try:
        parse_builder_image_lock(lock)
    except SupplyChainError as exc:
        raise SystemExit(f"BLOCKED: the emitted lock does not validate: {exc}") from None

    args.lock.parent.mkdir(parents=True, exist_ok=True)
    args.lock.write_text(
        json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )

    output_affecting = [t["name"] for t in tools if t["classification"] == "output-affecting"]
    evidence_only = [t["name"] for t in tools if t["classification"] == "evidence-generation-only"]
    print(f"    {len(tools)} tools pinned")
    print(f"      output-affecting        {len(output_affecting)}: {', '.join(sorted(output_affecting))}")
    print(f"      evidence-generation-only {len(evidence_only)}: {', '.join(sorted(evidence_only))}")
    print(f"      declared absent          {len(absent)}: {', '.join(sorted(absent))}")
    print(f"    wrote {display_path(args.lock, Path.cwd())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
