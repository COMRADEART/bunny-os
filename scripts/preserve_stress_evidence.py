#!/usr/bin/python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Move stress results into the repository without editorialising them.

The results this preserves are the ones that make the later ones meaningful: a
28 % failure rate, the swallowed `[WinError 5]` that explained it, and the 2 %
rate that followed the first two fixes. A phase that improves a number and then
keeps only the improved number has published a claim rather than a measurement.

Each file is copied verbatim, its SHA-256 recorded, and a caption written
saying what it measured and *on which commit*. The captions are supplied by the
caller rather than inferred: a manifest that guessed at what a run meant would
be a second, worse record of the same thing.

Nothing here rewrites an existing record. Superseding results are added beside
the ones they supersede, and the manifest carries the ``supersedes`` link.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
from typing import Any


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            hasher.update(block)
    return hasher.hexdigest()


def summarise(document: Any) -> dict[str, Any]:
    """The few figures a reader wants without opening the file."""
    if not isinstance(document, dict):
        return {}
    summary = {
        key: document[key]
        for key in ("runs", "passed", "failed", "longestConsecutivePass", "target", "order")
        if key in document
    }
    iterations = document.get("iterations")
    if isinstance(iterations, list) and iterations:
        failed = [item for item in iterations if not item.get("ok")]
        summary["failingIterations"] = [item.get("iteration") for item in failed]
        seconds = [item.get("seconds") for item in iterations if isinstance(item.get("seconds"), (int, float))]
        if seconds:
            summary["secondsMin"] = min(seconds)
            summary["secondsMax"] = max(seconds)
        # The inventory deltas are the point of the harness, so they belong in
        # the summary rather than only in the body.
        final = iterations[-1].get("sinceBaseline")
        if isinstance(final, dict):
            summary["finalDeltaVsBaseline"] = {
                key: final[key]
                for key in ("threads", "descriptors", "socketDescriptors", "tcpListen",
                            "tcpTimeWait", "executorLeases", "consentWaiters",
                            "liveServices", "liveRuntimes", "tempDirectories")
                if key in final
            }
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--into", type=Path, required=True, help="directory to write into")
    parser.add_argument(
        "--entry",
        action="append",
        default=[],
        metavar="NAME=PATH=COMMIT=CAPTION",
        help="a result to preserve; repeatable",
    )
    parser.add_argument(
        "--note",
        action="append",
        default=[],
        metavar="NAME=COMMIT=CAPTION",
        help="a measurement with no file, recorded as a caption only; repeatable",
    )
    arguments = parser.parse_args(argv)

    arguments.into.mkdir(parents=True, exist_ok=True)
    manifest_path = arguments.into / "manifest.json"
    manifest: dict[str, Any] = {
        "schema": "bunny-os/preserved-stress-evidence/1",
        "entries": [],
    }
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if isinstance(existing, dict) and isinstance(existing.get("entries"), list):
            manifest["entries"] = existing["entries"]

    known = {entry["name"] for entry in manifest["entries"]}

    for specification in arguments.entry:
        name, _, rest = specification.partition("=")
        source, _, rest = rest.partition("=")
        commit, _, caption = rest.partition("=")
        origin = Path(source)
        if not origin.is_file():
            print(f"REFUSED: {origin} does not exist", file=sys.stderr)
            return 2
        if name in known:
            print(f"REFUSED: {name} is already preserved; preservation never overwrites",
                  file=sys.stderr)
            return 2
        destination = arguments.into / f"{name}.json"
        shutil.copyfile(origin, destination)
        try:
            document = json.loads(destination.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            document = None
        manifest["entries"].append({
            "name": name,
            "file": destination.name,
            "sha256": digest(destination),
            "bytes": destination.stat().st_size,
            "commit": commit,
            "caption": caption,
            "summary": summarise(document),
        })
        print(f"preserved {name} ({destination.stat().st_size} bytes)")

    for specification in arguments.note:
        name, _, rest = specification.partition("=")
        commit, _, caption = rest.partition("=")
        if name in known:
            print(f"REFUSED: {name} is already preserved", file=sys.stderr)
            return 2
        manifest["entries"].append({
            "name": name,
            "file": None,
            "commit": commit,
            "caption": caption,
            "note": (
                "No machine-readable artefact exists for this measurement; the run "
                "printed to a console. The caption is the record."
            ),
        })
        print(f"noted {name}")

    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"manifest: {len(manifest['entries'])} entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
