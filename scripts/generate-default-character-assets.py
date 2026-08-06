#!/usr/bin/python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Generate the original deterministic pixel-art reference bunny PNG frames.

No image provider or external library is involved.  The small raster is kept
simple so package, renderer, transition, and import behaviour can be tested;
it is not intended as final production character art.
"""

from __future__ import annotations

import argparse
import binascii
from pathlib import Path
import struct
import zlib

WIDTH = HEIGHT = 96
TRANSPARENT = (0, 0, 0, 0)
INK = (57, 43, 70, 255)
FUR = (247, 239, 250, 255)
INNER = (246, 175, 198, 255)
ACCENT = (108, 92, 231, 255)


def canvas() -> list[list[tuple[int, int, int, int]]]:
    return [[TRANSPARENT for _x in range(WIDTH)] for _y in range(HEIGHT)]


def ellipse(pixels: list[list[tuple[int, int, int, int]]], cx: int, cy: int, rx: int, ry: int, colour: tuple[int, int, int, int]) -> None:
    for y in range(max(0, cy - ry), min(HEIGHT, cy + ry + 1)):
        for x in range(max(0, cx - rx), min(WIDTH, cx + rx + 1)):
            if ((x - cx) * (x - cx)) / (rx * rx) + ((y - cy) * (y - cy)) / (ry * ry) <= 1:
                pixels[y][x] = colour


def rectangle(pixels: list[list[tuple[int, int, int, int]]], x: int, y: int, width: int, height: int, colour: tuple[int, int, int, int]) -> None:
    for row in range(max(0, y), min(HEIGHT, y + height)):
        for column in range(max(0, x), min(WIDTH, x + width)):
            pixels[row][column] = colour


def bunny(state: str, variant: int = 0) -> list[list[tuple[int, int, int, int]]]:
    pixels = canvas()
    bob = 1 if variant else 0
    ear_tilt = 2 if state == "listening" else 0
    ellipse(pixels, 37 - ear_tilt, 24 + bob, 10, 23, INK)
    ellipse(pixels, 59 + ear_tilt, 24 + bob, 10, 23, INK)
    ellipse(pixels, 37 - ear_tilt, 24 + bob, 7, 20, FUR)
    ellipse(pixels, 59 + ear_tilt, 24 + bob, 7, 20, FUR)
    ellipse(pixels, 37 - ear_tilt, 23 + bob, 3, 13, INNER)
    ellipse(pixels, 59 + ear_tilt, 23 + bob, 3, 13, INNER)
    ellipse(pixels, 48, 58 + bob, 31, 30, INK)
    ellipse(pixels, 48, 57 + bob, 28, 27, FUR)
    ellipse(pixels, 22, 70 + bob, 9, 13, FUR)
    ellipse(pixels, 74, 70 + bob, 9, 13, FUR)
    ellipse(pixels, 48, 73 + bob, 18, 14, (237, 225, 243, 255))
    # eyes
    if state == "sleeping":
        rectangle(pixels, 35, 54 + bob, 9, 2, INK)
        rectangle(pixels, 53, 54 + bob, 9, 2, INK)
    elif state == "success":
        rectangle(pixels, 35, 53 + bob, 8, 2, INK)
        rectangle(pixels, 54, 53 + bob, 8, 2, INK)
        pixels[52 + bob][36] = INK; pixels[52 + bob][61] = INK
    else:
        ellipse(pixels, 39, 54 + bob, 3, 4, INK)
        ellipse(pixels, 57, 54 + bob, 3, 4, INK)
    ellipse(pixels, 48, 61 + bob, 3, 2, INNER)
    # mouth / state mark
    if state in {"speaking-open", "warning", "error"}:
        ellipse(pixels, 48, 68 + bob, 5 if state == "speaking-open" else 4, 6, INK)
        ellipse(pixels, 48, 69 + bob, 3, 3, INNER)
    elif state == "success":
        rectangle(pixels, 42, 67 + bob, 13, 2, INK)
        pixels[69 + bob][44] = INK; pixels[69 + bob][52] = INK
    else:
        rectangle(pixels, 45, 67 + bob, 7, 2, INK)
    if state == "thinking":
        ellipse(pixels, 78, 25, 4, 4, ACCENT)
        ellipse(pixels, 84, 17, 3, 3, ACCENT)
    elif state == "listening":
        ellipse(pixels, 82, 49, 5, 8, ACCENT)
        ellipse(pixels, 82, 49, 2, 4, FUR)
    elif state == "working":
        rectangle(pixels, 30, 76, 36, 12, ACCENT)
        rectangle(pixels, 35 + variant * 8, 79, 8, 3, FUR)
    elif state == "warning":
        rectangle(pixels, 77, 18, 5, 18, (240, 178, 54, 255))
        rectangle(pixels, 77, 40, 5, 5, (240, 178, 54, 255))
    elif state == "error":
        rectangle(pixels, 77, 18, 5, 18, (215, 70, 87, 255))
        rectangle(pixels, 77, 40, 5, 5, (215, 70, 87, 255))
    elif state == "moving":
        rectangle(pixels, 12, 82, 18, 3, ACCENT)
        rectangle(pixels, 66, 82, 18, 3, ACCENT)
    return pixels


def chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", binascii.crc32(kind + payload) & 0xFFFFFFFF)


def png(pixels: list[list[tuple[int, int, int, int]]]) -> bytes:
    raw = bytearray()
    for row in pixels:
        raw.append(0)
        for colour in row:
            raw.extend(colour)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", WIDTH, HEIGHT, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(raw), level=9))
        + chunk(b"IEND", b"")
    )


FRAMES = {
    "idle-1.png": ("idle", 0),
    "idle-2.png": ("idle", 1),
    "listening.png": ("listening", 0),
    "thinking.png": ("thinking", 0),
    "working-1.png": ("working", 0),
    "working-2.png": ("working", 1),
    "speaking-closed.png": ("speaking-closed", 0),
    "speaking-open.png": ("speaking-open", 0),
    "success.png": ("success", 0),
    "warning.png": ("warning", 0),
    "error.png": ("error", 0),
    "sleeping.png": ("sleeping", 0),
    "moving.png": ("moving", 0),
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("assets/companion/characters/default-bunny/assets"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    for name, (state, variant) in sorted(FRAMES.items()):
        (args.output / name).write_bytes(png(bunny(state, variant)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
