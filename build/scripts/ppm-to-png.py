#!/usr/bin/python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Convert QEMU's screendump PPMs to PNG with nothing installed.

The reference host has neither ImageMagick nor Pillow, and a screenshot nobody
can open is not evidence. PNG's required pieces are a signature, an IHDR, a
zlib-compressed IDAT and an IEND; zlib and struct are in the standard library,
so the whole converter is thirty lines and adds no build input.

It is a converter, not an encoder worth optimising: filter type 0 on every row,
one IDAT, default compression. A screenshot is written once and looked at once.
"""

from __future__ import annotations

from pathlib import Path
import struct
import sys
import zlib


def read_ppm(path: Path) -> tuple[int, int, bytes]:
    """Binary P6, which is what QEMU writes. Header fields may be split by any
    whitespace and a comment may appear between them."""
    data = path.read_bytes()
    if not data.startswith(b"P6"):
        raise ValueError(f"{path} is not a binary PPM")
    fields: list[int] = []
    index = 2
    while len(fields) < 3:
        while index < len(data) and data[index:index + 1].isspace():
            index += 1
        if data[index:index + 1] == b"#":
            while index < len(data) and data[index] != 0x0A:
                index += 1
            continue
        start = index
        while index < len(data) and not data[index:index + 1].isspace():
            index += 1
        fields.append(int(data[start:index]))
    index += 1  # the single whitespace byte after maxval
    width, height, maxval = fields
    if maxval != 255:
        raise ValueError(f"{path} has maxval {maxval}; only 8-bit is handled")
    expected = width * height * 3
    pixels = data[index:index + expected]
    if len(pixels) != expected:
        raise ValueError(f"{path} holds {len(pixels)} pixel bytes, expected {expected}")
    return width, height, pixels


def write_png(path: Path, width: int, height: int, pixels: bytes) -> None:
    raw = bytearray()
    stride = width * 3
    for row in range(height):
        raw.append(0)  # filter type 0: none
        raw += pixels[row * stride:(row + 1) * stride]

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (struct.pack(">I", len(body)) + kind + body
                + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF))

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + chunk(b"IEND", b"")
    )


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: ppm-to-png.py <directory-or-file>...", file=sys.stderr)
        return 2
    converted = 0
    for argument in sys.argv[1:]:
        base = Path(argument)
        targets = sorted(base.glob("*.ppm")) if base.is_dir() else [base]
        for source in targets:
            try:
                width, height, pixels = read_ppm(source)
                write_png(source.with_suffix(".png"), width, height, pixels)
            except (OSError, ValueError) as exc:
                print(f"ppm-to-png: {source}: {exc}", file=sys.stderr)
                continue
            converted += 1
            print(f"{source.with_suffix('.png')} ({width}x{height})")
    return 0 if converted else 1


if __name__ == "__main__":
    raise SystemExit(main())
