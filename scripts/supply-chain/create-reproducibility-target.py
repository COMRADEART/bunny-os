#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Create the reproducibility qualification target, and refuse to before it is earned.

A qualification target is a promise that two other builders can be pointed at
this commit and produce the same artifact. Creating one before the local gate
passes turns that promise into a guess, and the hosted runs into an expensive way
of discovering something the local builder already knew — which is what happened
the last time a hosted build was dispatched against an untested tree.

So every precondition is checked here, from evidence, before the target exists:

    local repeatability   REPRODUCIBLE, in qualification mode, all seventeen
    published inputs      base, builder and snapshot, each by digest
    cold pull             verified from a runner that held none of them
    source gate           passing

The target records what a hosted build must present, not what this machine
happens to have. Every field is a digest or an exact version, because a hosted
runner cannot be asked to match a description.

One asymmetry is recorded rather than smoothed over. The epoch lock names the
commit whose timestamp is the build epoch, and that cannot be this commit: the
lock is a file *inside* the commit, so writing this commit's own hash into it
would change the hash. The target therefore carries both — the candidate commit,
and the commit the epoch came from — and both builders read the epoch from the
same file, which is what the pin actually requires.

Exit codes:
    0   the target was created
    2   a precondition is not satisfied; nothing was written
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

REFUSED = 2


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def git(*arguments: str) -> str:
    result = subprocess.run(["git", *arguments], capture_output=True, text=True)
    return result.stdout.strip()


#: What build/Containerfile copies into the build context. Anything here reaches
#: a layer — even files a later step deletes, because deleting a path does not
#: remove the bytes an earlier layer already holds.
BUILD_AFFECTING = (
    "build",
    "config",
    "desktop-integration",
    "docs",
    "installer",
    "ARCHITECTURE.md",
    "README.md",
    "schemas",
    "scripts",
    "selinux",
    "services",
    "shell",
    "systemd",
    "tools",
)


def _build_affecting_changes(since: str, until: str) -> list[str]:
    changed = git("diff", "--name-only", f"{since}..{until}", "--", *BUILD_AFFECTING)
    return [line for line in changed.splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(prog="create-reproducibility-target")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--comparison",
        type=Path,
        default=Path("build/out/qualification/repeatability/comparison.json"),
    )
    parser.add_argument(
        "--publication", type=Path, default=Path("build/inputs/input-publication-lock.json")
    )
    parser.add_argument(
        "--cold-pull", type=Path, default=Path("build/out/qualification/cold-pull.json")
    )
    parser.add_argument("--profile", default="beta")
    parser.add_argument(
        "--allow-unpublished-inputs",
        action="store_true",
        help="record the target with the inputs unpublished. Only for a target that will never "
             "be dispatched to a hosted builder, and it is written into the target as a defect",
    )
    args = parser.parse_args()

    blockers: list[str] = []

    # ------------------------------------------------------------------ source
    if git("status", "--porcelain"):
        blockers.append(
            "the working tree is not clean. A target names a commit, and uncommitted work is in "
            "no commit"
        )
    commit = git("rev-parse", "HEAD")
    if len(commit) != 40:
        blockers.append("cannot read HEAD")

    # ---------------------------------------------------------- local gate
    comparison = read_json(args.comparison)
    if comparison is None:
        blockers.append(
            f"{args.comparison} is absent. The local repeatability comparison has not been run, "
            "so nothing establishes that this tree builds the same way twice"
        )
    else:
        evaluation = comparison.get("evaluation") or {}
        outcome = evaluation.get("outcome")
        if comparison.get("collectionMode") != "qualification":
            blockers.append(
                f"the local comparison was produced in {comparison.get('collectionMode')!r} mode. "
                "Only qualification-mode evidence may support a target"
            )
        # The comparison must be of *this* tree.
        #
        # Without this the target could be minted on the strength of a
        # REPRODUCIBLE result measured against a different artifact, which is
        # the most dangerous shape a stale piece of evidence can take: it is
        # genuine, it is passing, and it is about something else.
        #
        # Only the paths build/Containerfile copies matter. A change to a report
        # or a workflow does not reach the image, and requiring the whole tree to
        # be untouched would force a rebuild for every documentation edit and
        # teach everyone to bypass the check.
        measured_at = str(comparison.get("sourceCommit", ""))
        if not measured_at:
            blockers.append("the local comparison does not record which commit it measured")
        else:
            changed = _build_affecting_changes(measured_at, commit)
            if changed:
                blockers.append(
                    f"the local comparison measured {measured_at[:12]} and build-affecting paths "
                    f"have changed since: {', '.join(changed[:10])}"
                    + (f" and {len(changed) - 10} more" if len(changed) > 10 else "")
                    + ". A passing result about a different artifact is still about a different "
                    "artifact"
                )

        if outcome != "REPRODUCIBLE":
            differing = (evaluation.get("dimensionsByState") or {}).get("DIFFER") or []
            uncollected = (evaluation.get("dimensionsByState") or {}).get("NOT_COLLECTED") or []
            blockers.append(
                f"the local repeatability comparison is {outcome}, not REPRODUCIBLE"
                + (f"; differing: {', '.join(differing)}" if differing else "")
                + (f"; not collected: {', '.join(uncollected)}" if uncollected else "")
            )

    # ------------------------------------------------------- published inputs
    publication = read_json(args.publication)
    if publication is None or not publication.get("complete"):
        published = sorted((publication or {}).get("inputs") or {})
        message = (
            "the retained inputs are not published by digest"
            + (f" (published: {', '.join(published)})" if published else "")
            + ". A hosted builder cannot fetch what exists on one machine"
        )
        if args.allow_unpublished_inputs:
            print(f"warning: {message}", file=sys.stderr)
        else:
            blockers.append(message)

    cold_pull = read_json(args.cold_pull)
    if cold_pull is None or cold_pull.get("result") != "PASS":
        message = (
            "no passing cold-pull verification. Publishing an input and retrieving it from a "
            "machine that does not already have it are different claims"
        )
        if args.allow_unpublished_inputs:
            print(f"warning: {message}", file=sys.stderr)
        else:
            blockers.append(message)

    # ------------------------------------------------------------------ locks
    locks: dict[str, Any] = {}
    for name in (
        "base-image-lock",
        "builder-image-lock",
        "package-lock",
        "package-snapshot-lock",
        "reproducibility-lock",
    ):
        document = read_json(Path("build/inputs") / f"{name}.json")
        if document is None:
            blockers.append(f"build/inputs/{name}.json is absent or unreadable")
        else:
            locks[name] = document

    if blockers:
        print("BLOCKED: a reproducibility qualification target was not created.", file=sys.stderr)
        for blocker in blockers:
            print(f"  - {blocker}", file=sys.stderr)
        print(
            "\nA target created before these pass would send two hosted builders to measure "
            "something the local builder has not settled.",
            file=sys.stderr,
        )
        return REFUSED

    builder = locks["builder-image-lock"]
    epoch_lock = locks["reproducibility-lock"]
    sqlite = builder.get("sqlite") or {}
    tools = {tool["name"]: tool for tool in builder.get("tools", [])}

    def tool_version(name: str) -> str:
        return str(tools.get(name, {}).get("version", "unrecorded"))

    target = {
        "schemaVersion": 1,
        "targetKind": "reproducibility-qualification",
        # The target cannot name itself. This file is committed, and writing the
        # resulting hash into it would change that hash — so the field records
        # the parent, and the target commit is its child.
        #
        # What the hosted builders are pointed at is the *child*: the commit that
        # contains this file, so that a builder can read the target it is being
        # measured against. `assert_is_target_commit` below is what checks the
        # two agree, and it runs against a commit that exists.
        "parentCommit": commit,
        "parentCommitShort": commit[:12],
        "targetCommit": (
            "the child of parentCommit — the commit that contains this file. Recorded in "
            "THREE_BUILDER_REPRODUCIBILITY_REPORT.md and asserted by "
            "scripts/supply-chain/assert-target-commit.py, which refuses a commit whose "
            "qualification-target.json does not name that commit's own parent."
        ),
        "epochSourceCommit": epoch_lock.get("candidateCommit"),
        "epochSourceNote": (
            "The build epoch is the timestamp of the commit named in reproducibility-lock.json, "
            "which is this commit's ancestor rather than this commit. A lock inside a commit "
            "cannot carry that commit's own hash without changing it. Both builders read the "
            "epoch from the same file, which is what the pin requires; the asymmetry is recorded "
            "so nobody reads epochSourceCommit as the thing being built."
        ),
        "buildEpoch": epoch_lock.get("sourceDateEpoch"),
        "profile": args.profile,
        "architecture": epoch_lock.get("architecture", "x86_64"),
        "retainedBaseDigest": locks["base-image-lock"].get("retainedDigest"),
        "upstreamBaseDigest": locks["base-image-lock"].get("upstreamDigest"),
        "builderImageDigest": builder.get("builderDigest"),
        "packageSnapshotDigest": locks["package-snapshot-lock"].get("manifestDigest"),
        "packageSnapshotId": locks["package-snapshot-lock"].get("snapshotId"),
        "packageCount": len(locks["package-lock"].get("packages") or []),
        "toolchain": {
            "sqliteVersion": sqlite.get("libraryVersion", "unrecorded"),
            "sqliteCompileOptionsSha256": sqlite.get("compileOptionsSha256", "unrecorded"),
            "sqliteSourceId": sqlite.get("sourceId", "unrecorded"),
            "rpmVersion": tool_version("rpm"),
            "libdnf5Version": tool_version("libdnf5"),
            "syftVersion": tool_version("syft"),
            "podmanVersion": tool_version("podman"),
            "faketimeVersion": tool_version("libfaketime"),
            "faketimeLibrarySha256": (builder.get("faketimeLibrary") or {}).get(
                "sha256", "unrecorded"
            ),
        },
        "selinuxPolicyDigest": _selinux_policy_digest(),
        "publishedInputs": {
            kind: entry.get("digestReference")
            for kind, entry in ((publication or {}).get("inputs") or {}).items()
        },
        "localRepeatability": {
            "outcome": ((comparison or {}).get("evaluation") or {}).get("outcome"),
            "mode": (comparison or {}).get("collectionMode"),
            "builders": (comparison or {}).get("builders"),
        },
        "constraints": [
            "Both hosted builds must present builderImageDigest, retainedBaseDigest and "
            "packageSnapshotDigest exactly. A version string is not a pin.",
            "Both must run in qualification comparison mode and collect every archive-stage "
            "dimension. A missing dimension is INCONCLUSIVE, not a pass.",
            "Neither may reach a live package repository.",
            "Neither may have production signing access.",
            "They must run under separate workflow run IDs on separate runners. One run used "
            "twice is one measurement reported as two.",
            "No build-affecting source may change after this target is created. A later commit "
            "is a different target.",
        ],
        "note": (
            "This target is a statement of what must be reproduced and by what. It is not "
            "evidence that anything was: that comes from the three-builder comparison, imported "
            "separately, and the evidence commit must not become the candidate."
        ),
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(target, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    print(f"reproducibility qualification target for {commit[:12]}")
    print(f"  epoch    {target['buildEpoch']} (from {str(target['epochSourceCommit'])[:12]})")
    print(f"  base     {target['retainedBaseDigest']}")
    print(f"  builder  {target['builderImageDigest']}")
    print(f"  snapshot {target['packageSnapshotDigest']}")
    print(f"  sqlite   {target['toolchain']['sqliteVersion']}")
    print(f"  rpm      {target['toolchain']['rpmVersion']}")
    print(f"  libdnf5  {target['toolchain']['libdnf5Version']}")
    print(f"wrote {args.output}")
    print()
    print("Do not change build-affecting source after this point. A later commit is a")
    print("different target, and the hosted builds would be measuring something else.")
    return 0


def _selinux_policy_digest() -> str:
    """A digest over the SELinux policy sources this repository ships."""
    import hashlib

    policy = Path("selinux")
    if not policy.is_dir():
        return "unrecorded: this repository ships no selinux/ directory"
    value = hashlib.sha256()
    for path in sorted(p for p in policy.rglob("*") if p.is_file()):
        value.update(path.as_posix().encode("utf-8") + b"\0")
        value.update(path.read_bytes())
    return value.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
