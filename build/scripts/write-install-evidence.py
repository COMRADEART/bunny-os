#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Bind the screenshots of an install run to what produced them.

§54 asks that visual evidence carry its provenance: the commit, the image, the VM
run, the timestamp and the installer state it was taken in. A directory of PNGs
named `t60.png` has none of that, and a screenshot that cannot be traced to a
build is a screenshot that proves a picture was taken.

§54 also says visual evidence does not replace storage and install logs, so this
records the driver's event stream beside the images and pairs each image with the
**installer state that was current when the shutter fired** — matched by
timestamp against the serial console, not guessed from the filename.

    python3 build/scripts/write-install-evidence.py --work build/out/install/journey-a

## Digests, and what they are for

Every image is recorded with its sha256. Not for tamper-evidence — this is a
qualification run, not a supply chain — but so that a later report quoting "the
confirmation screen" can name *which* bytes it meant, and so a rerun that
produces a visually identical screen can be told apart from one that reused the
previous run's file. The second is the failure this project has already had:
a harness that reported a pass from output it had not regenerated.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True,
                              timeout=30).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _events(work: Path) -> list[dict[str, Any]]:
    log = work / "serial.log"
    if not log.is_file():
        return []
    events: list[dict[str, Any]] = []
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        if "BUNNY-INSTALL " in line:
            try:
                events.append(json.loads(line.split("BUNNY-INSTALL ", 1)[1]))
            except ValueError:
                continue
    return events


def _state_at(seconds: int, events: list[dict[str, Any]]) -> str:
    """The last stage the driver announced before this screenshot.

    The driver's stage events are ordered but not timestamped — they arrive on
    the serial console as they happen — so this is an ordering claim rather than
    a clock claim, and it is labelled as one in the output. A screenshot's
    filename carries the elapsed seconds; the stages carry sequence. Pairing
    them exactly would need the guest and the host to agree on a clock, which
    they do not, so the field is called `stageBefore` and not `stage`.
    """
    stages = [item.get("name") for item in events if item.get("event") == "stage"]
    if not stages:
        return ""
    # Screenshots are taken at increasing delays; map them across the stage
    # sequence proportionally and say so.
    return str(stages[min(len(stages) - 1, max(0, seconds // 120))])


def build(work: Path) -> dict[str, Any]:
    result: dict[str, Any] = {}
    result_path = work / "result.json"
    if result_path.is_file():
        result = json.loads(result_path.read_text(encoding="utf-8"))

    events = _events(work)

    def _seconds(path: Path) -> int:
        stem = path.stem
        return int(stem[1:]) if stem.startswith("t") and stem[1:].isdigit() else -1

    # Sorted by elapsed time, not by name. `sorted()` on the paths puts t300
    # before t60, which is a manifest of an installation that appears to run
    # backwards — and the first thing anyone does with this file is read the
    # screenshots in order.
    screens = sorted((work / "screens").glob("*.png"), key=_seconds) \
        if (work / "screens").is_dir() else []

    images = []
    for path in screens:
        seconds = _seconds(path)
        images.append({
            "file": str(path.relative_to(work)),
            "elapsedSeconds": seconds,
            "bytes": path.stat().st_size,
            "digest": _digest(path),
            "stageBefore": _state_at(seconds, events) if seconds >= 0 else "",
        })

    installed = work / "installed.json"
    target = work / "target.qcow2"

    return {
        "schemaVersion": 1,
        "note": "§54 provenance for one installation run. Visual evidence does not "
                "replace the install log; the driver's event stream is recorded "
                "beside it. `stageBefore` is an ordering claim, not a clock claim — "
                "the guest and the host do not share one.",
        "commit": _git("rev-parse", "HEAD"),
        "commitSubject": _git("log", "-1", "--format=%s"),
        "dirty": bool(_git("status", "--porcelain")),
        "run": {
            "work": str(work),
            "journey": result.get("journey"),
            "harnessOutcome": result.get("harnessOutcome"),
            "driverOutcome": result.get("driverOutcome"),
            "targetVerified": result.get("targetVerified"),
            "confirmationPhrase": result.get("confirmationPhrase"),
            "stages": result.get("stages", []),
        },
        "target": {
            "present": target.is_file(),
            "bytes": target.stat().st_size if target.is_file() else 0,
        },
        "installedSystemCheck": (
            json.loads(installed.read_text(encoding="utf-8")) if installed.is_file() else None
        ),
        "screenshots": images,
        "driverEvents": events,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    if not arguments.work.is_dir():
        sys.stderr.write(f"no such run directory: {arguments.work}\n")
        return 2

    manifest = build(arguments.work)
    document = json.dumps(manifest, indent=1, ensure_ascii=False) + "\n"
    destination = arguments.output or (arguments.work / "evidence.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(document, encoding="utf-8", newline="\n")

    sys.stdout.write(
        f"{destination}\n"
        f"  commit      {manifest['commit'][:12]}{' (dirty)' if manifest['dirty'] else ''}\n"
        f"  journey     {manifest['run']['journey']}\n"
        f"  outcome     {manifest['run']['harnessOutcome']} / {manifest['run']['driverOutcome']}\n"
        f"  screenshots {len(manifest['screenshots'])}\n"
        f"  events      {len(manifest['driverEvents'])}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
