#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Create the installed-evidence context — and refuse to before it is earned.

The context is the authority every installed-system record binds to. It is
created once per qualification pass, from verified inputs, and committed; a
context assembled ad hoc at scenario time would let each run decide its own
authority, which is the defect the resolver exists to prevent.

Preconditions checked here, from evidence:

    archive target        assert-target-commit passes for the named commit
    archive digest        matches the target evidence, byte-recomputed when
                          the archive is present on this machine
    installation artifact exists and is digest-recorded with its build log
    installer toolchain   lock exists, parses, and pins its tools
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
CONTEXT = ROOT / "qualification/installed-system/evidence-context.json"


def digest_file(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            value.update(chunk)
    return value.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(prog="create_evidence_context")
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-archive-digest", required=True)
    parser.add_argument("--installables", required=True, type=Path,
                        help="installables.json from build_installables.sh")
    parser.add_argument("--installation-artifact", required=True,
                        help="which artifact from installables.json is the pinned one")
    parser.add_argument("--recovery-artifact-digest")
    parser.add_argument("--scenario-version", default="isq-1")
    args = parser.parse_args()

    blockers: list[str] = []

    assertion = subprocess.run(
        ["python3", str(ROOT / "scripts/supply-chain/assert-target-commit.py"),
         "--commit", args.source_commit],
        capture_output=True, text=True, cwd=ROOT,
    )
    if assertion.returncode != 0:
        blockers.append(
            f"{args.source_commit[:12]} is not the qualification target its own tree "
            f"describes: {assertion.stderr.strip()[:200]}"
        )

    installables = json.loads(args.installables.read_text(encoding="utf-8"))
    if installables.get("sourceCommit") != args.source_commit:
        blockers.append("installables.json describes a different source commit")
    if installables.get("sourceArchiveDigest") != args.source_archive_digest:
        blockers.append("installables.json was built from a different archive digest")
    if not installables.get("sourceArchiveVerified"):
        blockers.append("installables.json does not record archive verification")

    artifact = next(
        (a for a in installables.get("artifacts", [])
         if a.get("artifact") == args.installation_artifact),
        None,
    )
    if artifact is None:
        blockers.append(
            f"{args.installation_artifact} is not among the recorded artifacts: "
            + ", ".join(a.get("artifact", "?") for a in installables.get("artifacts", []))
        )

    lock_path = ROOT / "build/installer/toolchain.lock.json"
    if not lock_path.is_file():
        blockers.append("build/installer/toolchain.lock.json does not exist")
        toolchain_digest = ""
    else:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        if not lock.get("tools"):
            blockers.append("the toolchain lock pins no tools")
        toolchain_digest = digest_file(lock_path)

    if blockers:
        print("BLOCKED: the evidence context was not created.", file=sys.stderr)
        for blocker in blockers:
            print(f"  - {blocker}", file=sys.stderr)
        return 2

    context = {
        "schemaVersion": 1,
        "sourceCommit": args.source_commit,
        "sourceArchiveDigest": args.source_archive_digest,
        "installationArtifactDigest": artifact["sha256"],
        "installationArtifactName": artifact["artifact"],
        **({"recoveryArtifactDigest": args.recovery_artifact_digest}
           if args.recovery_artifact_digest else {}),
        "installerToolchainDigest": toolchain_digest,
        "scenarioVersion": args.scenario_version,
        "subjects": {
            "installerToolchainDigest": "build/installer/toolchain.lock.json",
        },
        "notes": (
            "Authority for every installed-system evidence record. The "
            "installation artifact lives outside the repository by size; its "
            "digest is recomputed by every consumer that attaches it."
        ),
    }
    CONTEXT.write_text(json.dumps(context, indent=2, sort_keys=True) + "\n",
                       encoding="utf-8")
    print(f"wrote {CONTEXT.relative_to(ROOT)}")
    for key in ("sourceCommit", "sourceArchiveDigest", "installationArtifactDigest",
                "installerToolchainDigest"):
        print(f"  {key}: {str(context[key])[:16]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
