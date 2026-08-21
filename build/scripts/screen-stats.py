#!/usr/bin/python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Summarise a captured frame, so "the screen had something on it" is a measurement.

The harness converts each capture to PNG and deletes the PPM, which keeps the
evidence directory small but leaves nothing a checker can read. This runs on the
PPM first and records a few numbers beside the image.

What it is for and what it is not for: it can say a frame is blank, or uniform,
or that one frame differs from another. It cannot say what is drawn. A boot
checkpoint that depends on recognising a user interface is reported as needing a
look, and these numbers accompany the claim rather than standing in for it —
a coverage number once passed on a character whose working pose was a shrug.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def read_ppm(path: Path) -> tuple[int, int, bytes]:
    """Width, height and RGB bytes of a binary (P6) PPM."""
    data = path.read_bytes()
    if not data.startswith(b"P6"):
        raise ValueError(f"{path} is not a binary PPM (expected the P6 magic)")
    fields: list[int] = []
    offset = 2
    while len(fields) < 3:
        while offset < len(data) and data[offset : offset + 1].isspace():
            offset += 1
        if data[offset : offset + 1] == b"#":
            while offset < len(data) and data[offset] != 0x0A:
                offset += 1
            continue
        start = offset
        while offset < len(data) and not data[offset : offset + 1].isspace():
            offset += 1
        fields.append(int(data[start:offset]))
    offset += 1  # the single whitespace byte after the maximum value
    width, height, _maximum = fields
    return width, height, data[offset : offset + width * height * 3]


def summarise(path: Path) -> dict:
    width, height, pixels = read_ppm(path)
    count = len(pixels) // 3
    if count == 0:
        return {"path": path.name, "width": width, "height": height,
                "pixels": 0, "blank": True}

    # Sample rather than walk every pixel: at 1280x1024 that is 1.3 million
    # triples in pure Python for a number that only has to distinguish "blank"
    # from "not blank". Every 37th pixel is a stride coprime with the row width,
    # so the sample crosses rows instead of striping one column.
    stride = 37
    total = 0
    total_squares = 0
    colours: set[int] = set()
    sampled = 0
    for index in range(0, count, stride):
        red, green, blue = pixels[index * 3 : index * 3 + 3]
        luminance = (red * 299 + green * 587 + blue * 114) // 1000
        total += luminance
        total_squares += luminance * luminance
        colours.add((red << 16) | (green << 8) | blue)
        sampled += 1

    mean = total / sampled
    variance = max(0.0, total_squares / sampled - mean * mean)
    return {
        "path": path.name,
        "width": width,
        "height": height,
        "pixels": count,
        "sampled": sampled,
        "meanLuminance": round(mean, 2),
        "standardDeviation": round(variance ** 0.5, 2),
        "distinctColours": len(colours),
        # A frame with one colour and no spread is a blank screen. Both
        # conditions, because a uniform grey is as blank as a uniform black and
        # neither is a rendered interface.
        "blank": len(colours) <= 2 and variance < 1.0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ppm", required=True, type=Path)
    parser.add_argument("--json", required=True, type=Path)
    arguments = parser.parse_args(argv)
    try:
        report = summarise(arguments.ppm)
    except (OSError, ValueError) as error:
        print(f"screen-stats: {error}", file=sys.stderr)
        return 2
    arguments.json.parent.mkdir(parents=True, exist_ok=True)
    arguments.json.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"screen-stats: {report['path']} {report['width']}x{report['height']} "
          f"colours={report.get('distinctColours', 0)} "
          f"sd={report.get('standardDeviation', 0)} "
          f"blank={report['blank']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
