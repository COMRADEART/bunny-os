#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Join two builders' collected dimensions into one comparison document.

``collect_comparison_dimensions.py`` measures one archive.
``release.comparison.evaluate_comparison`` decides what a pair of measurements
means. This is the join between them, and it exists as its own step because the
join is where an incomplete comparison used to become a favourable one: the
previous local run produced a document with four dimensions absent, and nothing
between the collector and the verdict refused it.

So the mode travels with the evidence rather than with the invocation. A
collection produced in diagnostic mode carries ``collectionMode: diagnostic``,
and a qualification join refuses it — which means a diagnostic run cannot be
promoted into qualification evidence by calling a different script on it later.

The SELinux dimension is assembled from the separate intended-context manifests
rather than from the archives, because an archive carries no applied context and
two empty sets compare equal.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from release.comparison import (  # noqa: E402
    COMPARISON_DIMENSIONS,
    evaluate_comparison,
    reduce_dimension,
)

REFUSED = 2

#: Every dimension except selinuxLabels, which is assembled from the intended
#: manifests instead of from the archive collections.
FROM_COLLECTION = tuple(
    name for name, _, _ in COMPARISON_DIMENSIONS if name != "selinuxLabels"
)


def load(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise SystemExit(f"BLOCKED: the {label} dimension collection does not exist: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(prog="build_comparison_document")
    parser.add_argument("--first-dimensions", required=True, type=Path)
    parser.add_argument("--second-dimensions", required=True, type=Path)
    parser.add_argument("--first-selinux", type=Path)
    parser.add_argument("--second-selinux", type=Path)
    parser.add_argument("--first-builder", required=True)
    parser.add_argument("--second-builder", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--base-image-digest", required=True)
    parser.add_argument("--claim", default="same-host-repeatability")
    parser.add_argument(
        "--independent",
        action="store_true",
        help="assert the two builders are independently administered; the gate checks this "
             "separately and a false claim here does not survive it",
    )
    parser.add_argument(
        "--raw-variance-explanation",
        default="",
        help="why the raw archive digests may differ; without one an unexplained raw difference "
             "is INCONCLUSIVE rather than tolerated",
    )
    parser.add_argument(
        "--mode",
        choices=("qualification", "diagnostic"),
        default="diagnostic",
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    first = load(args.first_dimensions, "first")
    second = load(args.second_dimensions, "second")

    if args.mode == "qualification":
        for label, document, path in (
            ("first", first, args.first_dimensions),
            ("second", second, args.second_dimensions),
        ):
            mode = document.get("collectionMode")
            if mode != "qualification":
                raise SystemExit(
                    f"BLOCKED: the {label} collection ({path}) was produced in "
                    f"{mode or 'an unrecorded'} mode, and this is a qualification join.\n"
                    "A collection that was allowed to omit dimensions cannot be promoted into "
                    "qualification evidence by comparing it later. Re-collect with "
                    "--mode qualification."
                )
            missing = document.get("missingRequiredDimensions") or []
            if missing:
                raise SystemExit(
                    f"BLOCKED: the {label} collection is missing required dimensions: "
                    + ", ".join(missing)
                )

        if not (args.first_selinux and args.second_selinux):
            raise SystemExit(
                "BLOCKED: qualification mode requires an intended SELinux context manifest from "
                "both builders. It is the archive-observable half of the SELinux dimension, and "
                "omitting it leaves the dimension NOT_COLLECTED — which makes the comparison "
                "INCONCLUSIVE no matter what else matched."
            )

    first_dimensions = first.get("dimensions") or {}
    second_dimensions = second.get("dimensions") or {}

    dimensions: dict[str, Any] = {}
    for name in FROM_COLLECTION:
        record, form, detail = reduce_dimension(
            first_dimensions.get(name), second_dimensions.get(name)
        )
        if detail:
            record["detail"] = detail
        record["reductionForm"] = form
        dimensions[name] = record

    # selinuxLabels is one dimension asked at two stages, and at the archive
    # stage the answerable half is the intended-context manifest.
    #
    # The archive collections both report the dimension as null, correctly: no
    # bootc image carries a security.selinux xattr, and two empty sets compare
    # equal. Leaving the dimension at those two nulls would make every complete
    # archive comparison NOT_COLLECTED on it and therefore INCONCLUSIVE — a
    # verdict no archive build could ever escape, for a subcheck that belongs to
    # installed-system qualification.
    #
    # So the dimension carries the archive-stage subcheck, which is a real
    # comparison of a real manifest, and `selinux` below carries the composite
    # that keeps the installed-system subcheck outstanding. Both are recorded:
    # satisfying this dimension never reports appliedSelinuxContexts as done.
    selinux: dict[str, Any] = {}
    if args.first_selinux and args.second_selinux:
        first_contexts = load(args.first_selinux, "first SELinux")
        second_contexts = load(args.second_selinux, "second SELinux")
        record, _, detail = reduce_dimension(
            first_contexts.get("intendedSelinuxContexts"),
            second_contexts.get("intendedSelinuxContexts"),
        )
        if detail:
            record["detail"] = detail
        selinux["intendedSelinuxContexts"] = record
        selinux["specifications"] = [
            first_contexts.get("specification"),
            second_contexts.get("specification"),
        ]
        selinux["resolvedCounts"] = [
            first_contexts.get("resolvedCount"),
            second_contexts.get("resolvedCount"),
        ]
        dimensions["selinuxLabels"] = dict(record)
        dimensions["selinuxLabels"]["detail"] = (
            "The archive-stage subcheck: the context every path is intended to receive, computed "
            "from the policy the image ships. No archive carries an applied security.selinux "
            "xattr — bootc install applies them on the target — so the applied subcheck stays "
            "outstanding under selinux.appliedSelinuxContexts and is not satisfied by this."
        )
    else:
        dimensions["selinuxLabels"] = {
            "first": first_dimensions.get("selinuxLabels"),
            "second": second_dimensions.get("selinuxLabels"),
            "detail": (
                "No intended-context manifest was supplied, so the archive-observable half of "
                "this dimension was not collected. The two nulls the archives report are not a "
                "match; they are two builders both measuring nothing."
            ),
        }

    # Entry mtimes travel as a diagnostic beside the dimensions, never as one.
    # When every content dimension matches and rawArchive does not, this is the
    # section that names the file.
    first_mtimes = (first.get("entryMtimes") or {}).get("byPath") or {}
    second_mtimes = (second.get("entryMtimes") or {}).get("byPath") or {}
    differing_mtimes = sorted(
        path
        for path in set(first_mtimes) | set(second_mtimes)
        if first_mtimes.get(path) != second_mtimes.get(path)
    )

    document: dict[str, Any] = {
        "schemaVersion": 1,
        "claim": args.claim,
        "collectionMode": args.mode,
        "sourceCommit": args.source_commit,
        "baseImageDigest": args.base_image_digest,
        "builders": [args.first_builder, args.second_builder],
        "dimensions": dimensions,
        "selinux": selinux or None,
        "entryMtimeDiagnostic": {
            "note": (
                "Not a dimension. Layer tar bytes include entry mtimes, so a file whose content "
                "matches and whose mtime does not still changes ociLayers and rawArchive."
            ),
            "differingCount": len(differing_mtimes),
            "differing": differing_mtimes[:200],
            "firstDigest": (first.get("entryMtimes") or {}).get("digest"),
            "secondDigest": (second.get("entryMtimes") or {}).get("digest"),
        },
    }
    if args.raw_variance_explanation:
        document["rawVarianceExplanation"] = args.raw_variance_explanation

    report = evaluate_comparison(
        document,
        independent=args.independent,
        selinuxStage="archive",
    )
    document["evaluation"] = report.as_dict()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(document, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    evaluation = document["evaluation"]
    by_state = evaluation["dimensionsByState"]
    print(f"outcome: {evaluation['outcome']}")
    print(f"  MATCH          {len(by_state['MATCH'])}: {', '.join(by_state['MATCH'])}")
    if by_state["DIFFER"]:
        print(f"  DIFFER         {len(by_state['DIFFER'])}: {', '.join(by_state['DIFFER'])}")
    if by_state["NOT_COLLECTED"]:
        print(
            f"  NOT_COLLECTED  {len(by_state['NOT_COLLECTED'])}: "
            f"{', '.join(by_state['NOT_COLLECTED'])}"
        )
    if differing_mtimes:
        print(f"  entry mtimes differ on {len(differing_mtimes)} paths, e.g. {differing_mtimes[0]}")
    for reason in evaluation["reasons"]:
        print(f"  - {reason}")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit as exc:
        if isinstance(exc.code, str):
            print(exc.code, file=sys.stderr)
            raise SystemExit(REFUSED) from None
        raise
