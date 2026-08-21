#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Turn the sweep's screenshots into the accessibility evidence record.

Same method as the record it supersedes (`a11y-b09f523`): every accessibility
screenshot is compared pixel-for-pixel against the default-settings baseline,
and the run carries its own control — a screenshot taken at the *same*
settings as the baseline after everything is restored, whose difference is
the noise floor (clocks tick, gauges move). A measurement that cannot state
its own noise floor cannot claim its signal.

Runs beside the sweep output; writes `accessibility.json` in the established
schemaVersion-1 shape, extended with the sweep's own set-and-read-back record
and the AT-SPI control-geometry result, so the evidence file alone carries
what the matrix row asserts.

    python3 compare_screens.py <sweep-work-dir> <output.json> <artifact-tag> <image-digest>
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

from PIL import Image


def load(path: Path):
    return Image.open(path).convert("RGB")


def compare(baseline: Image.Image, other: Image.Image):
    from PIL import ImageChops

    diff = ImageChops.difference(baseline, other)
    bbox = diff.getbbox()
    differing = 0
    if bbox:
        histogram = diff.convert("L").point(lambda p: 255 if p else 0).histogram()
        differing = histogram[255]
    width, height = baseline.size
    return {
        "pixelsDiffering": differing,
        "shareOfScreen": round(differing / float(width * height), 6),
        "boundingBox": (
            None if bbox is None else
            {"x": bbox[0], "y": bbox[1], "width": bbox[2] - bbox[0], "height": bbox[3] - bbox[1]}
        ),
    }


def main() -> int:
    work = Path(sys.argv[1])
    output = Path(sys.argv[2])
    artifact = sys.argv[3]
    image_digest = sys.argv[4]
    screens = work / "screens"
    interaction = json.loads((work / "interaction.json").read_text(encoding="utf-8"))
    accessibility = interaction["accessibility"]

    baseline = load(screens / "a11y-01-default.ppm")
    comparisons = []
    for name, is_control in (
        ("a11y-02-reduced-motion", False),
        ("a11y-03-large-text", False),
        ("a11y-04-high-contrast", False),
        ("a11y-06-text-125", False),
        ("a11y-07-text-200", False),
        ("a11y-05-restored", True),
    ):
        path = screens / f"{name}.ppm"
        if not path.is_file():
            continue
        entry = compare(baseline, load(path))
        entry["screenshot"] = name
        entry["isTheControl"] = is_control
        comparisons.append(entry)

    noise = next(
        (c["shareOfScreen"] for c in comparisons if c["isTheControl"]), None
    )

    scaling = accessibility.get("textScaling") or {}
    text_by_size = accessibility.get("textScalingBySize") or {}
    changes = accessibility.get("changes") or []
    read_back_ok = all(c.get("tookEffect") for c in changes) and bool(changes)

    shots = {}
    for png in sorted(screens.glob("a11y-*.png")):
        shots[png.name] = hashlib.sha256(png.read_bytes()).hexdigest()

    width, height = baseline.size
    document = {
        "schemaVersion": 1,
        "section": "accessibility",
        "artifact": artifact,
        "imageDigest": image_digest,
        "measurements": {
            "screen": {"width": width, "height": height},
            "comparisons": comparisons,
            "noiseFloorShare": noise,
            "settingsReadBack": read_back_ok,
            "settingChanges": changes,
            "atSpiControlGrowth": {
                "scale": scaling.get("scale"),
                "conclusive": scaling.get("conclusive"),
                "grewCount": scaling.get("grewCount"),
                "shrankCount": scaling.get("shrankCount"),
                "unchangedCount": scaling.get("unchangedCount"),
                "controlsComparable": scaling.get("controlsComparable"),
                "examples": (scaling.get("grew") or [])[:6],
            },
            "atSpiBySize": text_by_size,
            "screenReader": accessibility.get("screenReader"),
        },
        "screenshots": shots,
    }
    output.write_text(
        json.dumps(document, indent=1, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n",
    )
    for c in comparisons:
        label = "control" if c["isTheControl"] else "      "
        print(f"{label} {c['screenshot']}: {c['shareOfScreen']:.4%}")
    print(f"noise floor: {noise:.4%}" if noise is not None else "NO CONTROL SHOT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
