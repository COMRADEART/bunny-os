# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded metadata and structural validation for package raster images.

Image decoders are an untrusted-input boundary.  Bunny validates the complete
PNG container, checks its checksums, and performs a bounded inflate of its
scanlines before a desktop decoder is allowed to see it.  WebP is structurally
bounded here and remains isolated behind the platform decoder at display time.

This phase deliberately implements animated 2D as sequences of independently
validated static PNG or WebP frames.  APNG and animated WebP are rejected so a
package cannot smuggle a second, unbounded animation timeline through a frame.
"""

from __future__ import annotations

from dataclasses import dataclass
import binascii
from pathlib import Path
import struct
import zlib

from .errors import CharacterSecurityError

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_ENCODED_IMAGE_BYTES = 64 * 1024 * 1024
MAX_DECODED_IMAGE_BYTES = 64 * 1024 * 1024
MAX_IMAGE_DIMENSION = 4096
MAX_IMAGE_PIXELS = 16_777_216


@dataclass(frozen=True)
class ImageInfo:
    media_type: str
    width: int
    height: int
    decoded_bytes: int
    frames: int = 1

    def to_json(self) -> dict[str, int | str]:
        return {
            "mediaType": self.media_type,
            "width": self.width,
            "height": self.height,
            "decodedBytes": self.decoded_bytes,
            "frames": self.frames,
        }


def _bounded_dimensions(width: int, height: int) -> int:
    if width <= 0 or height <= 0:
        raise CharacterSecurityError("image dimensions must be positive")
    if width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION:
        raise CharacterSecurityError(
            f"image dimensions exceed {MAX_IMAGE_DIMENSION} pixels per side"
        )
    pixels = width * height
    if pixels > MAX_IMAGE_PIXELS:
        raise CharacterSecurityError("image pixel count exceeds the decoder limit")
    decoded = pixels * 4
    if decoded > MAX_DECODED_IMAGE_BYTES:
        raise CharacterSecurityError("decoded image size exceeds the memory limit")
    return decoded


def inspect_image(path: Path) -> ImageInfo:
    """Read and validate one static PNG or WebP without following another path."""
    path = Path(path)
    size = path.stat().st_size
    if size <= 0 or size > MAX_ENCODED_IMAGE_BYTES:
        raise CharacterSecurityError("encoded image size is outside the supported limit")
    data = path.read_bytes()
    if data.startswith(PNG_SIGNATURE):
        return _inspect_png(data)
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return _inspect_webp(data)
    raise CharacterSecurityError("asset is not a supported PNG or WebP image")


def _inspect_png(data: bytes) -> ImageInfo:
    offset = len(PNG_SIGNATURE)
    width = height = bit_depth = color_type = 0
    interlace = -1
    saw_ihdr = saw_iend = saw_palette = False
    compressed = bytearray()
    chunk_count = 0

    while offset < len(data):
        if offset + 12 > len(data):
            raise CharacterSecurityError("PNG contains a truncated chunk")
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        kind = data[offset + 4:offset + 8]
        end = offset + 12 + length
        if length > MAX_ENCODED_IMAGE_BYTES or end > len(data):
            raise CharacterSecurityError("PNG chunk length is invalid")
        payload = data[offset + 8:offset + 8 + length]
        expected_crc = struct.unpack(">I", data[offset + 8 + length:end])[0]
        observed_crc = binascii.crc32(kind + payload) & 0xFFFFFFFF
        if expected_crc != observed_crc:
            raise CharacterSecurityError(f"PNG {kind.decode('ascii', 'replace')} checksum is invalid")
        chunk_count += 1
        if chunk_count > 4096:
            raise CharacterSecurityError("PNG contains too many chunks")

        if kind == b"IHDR":
            if saw_ihdr or offset != len(PNG_SIGNATURE) or length != 13:
                raise CharacterSecurityError("PNG IHDR placement or size is invalid")
            width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", payload
            )
            if compression != 0 or filtering != 0 or interlace != 0:
                raise CharacterSecurityError("PNG compression, filter, or interlace mode is unsupported")
            valid_depths = {
                0: {1, 2, 4, 8, 16},
                2: {8, 16},
                3: {1, 2, 4, 8},
                4: {8, 16},
                6: {8, 16},
            }
            if color_type not in valid_depths or bit_depth not in valid_depths[color_type]:
                raise CharacterSecurityError("PNG colour type and bit depth are unsupported")
            _bounded_dimensions(width, height)
            saw_ihdr = True
        elif kind == b"PLTE":
            if not saw_ihdr or saw_iend or length == 0 or length % 3 or length > 768:
                raise CharacterSecurityError("PNG palette is invalid")
            saw_palette = True
        elif kind == b"IDAT":
            if not saw_ihdr or saw_iend:
                raise CharacterSecurityError("PNG image data is out of order")
            compressed.extend(payload)
            if len(compressed) > MAX_ENCODED_IMAGE_BYTES:
                raise CharacterSecurityError("PNG compressed scanlines exceed the input limit")
        elif kind == b"IEND":
            if length != 0 or saw_iend:
                raise CharacterSecurityError("PNG end marker is invalid")
            saw_iend = True
            if end != len(data):
                raise CharacterSecurityError("PNG has content after its end marker")
        elif kind in {b"acTL", b"fcTL", b"fdAT"}:
            raise CharacterSecurityError("APNG is not implemented; use validated frame sequences")
        elif kind and 65 <= kind[0] <= 90:
            # Unknown critical chunks alter decoding and cannot be ignored.
            if kind not in {b"IHDR", b"PLTE", b"IDAT", b"IEND"}:
                raise CharacterSecurityError("PNG contains an unsupported critical chunk")
        offset = end

    if not saw_ihdr or not saw_iend or not compressed:
        raise CharacterSecurityError("PNG is missing required image chunks")
    if color_type == 3 and not saw_palette:
        raise CharacterSecurityError("indexed PNG is missing its palette")

    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]
    row_bytes = (width * channels * bit_depth + 7) // 8
    expected = (row_bytes + 1) * height
    if expected > MAX_DECODED_IMAGE_BYTES + height:
        raise CharacterSecurityError("PNG scanlines exceed the bounded inflate limit")
    decoder = zlib.decompressobj()
    try:
        raw = decoder.decompress(bytes(compressed), expected + 1)
        if decoder.unconsumed_tail or len(raw) > expected:
            raise CharacterSecurityError("PNG expands beyond its declared dimensions")
        raw += decoder.flush(max(1, expected + 1 - len(raw)))
    except zlib.error as exc:
        raise CharacterSecurityError(f"PNG scanlines are corrupt: {exc}") from exc
    if len(raw) != expected or not decoder.eof or decoder.unused_data:
        raise CharacterSecurityError("PNG scanline stream does not match its declared dimensions")
    for row in range(height):
        if raw[row * (row_bytes + 1)] > 4:
            raise CharacterSecurityError("PNG uses an invalid scanline filter")
    return ImageInfo("image/png", width, height, _bounded_dimensions(width, height))


def _inspect_webp(data: bytes) -> ImageInfo:
    if len(data) < 20:
        raise CharacterSecurityError("WebP file is truncated")
    declared = struct.unpack("<I", data[4:8])[0]
    if declared + 8 != len(data):
        raise CharacterSecurityError("WebP RIFF length does not match the file")
    offset = 12
    width = height = 0
    saw_image = False
    chunks = 0
    while offset < len(data):
        if offset + 8 > len(data):
            raise CharacterSecurityError("WebP contains a truncated chunk")
        kind = data[offset:offset + 4]
        length = struct.unpack("<I", data[offset + 4:offset + 8])[0]
        start = offset + 8
        end = start + length
        padded_end = end + (length & 1)
        if end > len(data) or padded_end > len(data):
            raise CharacterSecurityError("WebP chunk length is invalid")
        payload = data[start:end]
        chunks += 1
        if chunks > 4096:
            raise CharacterSecurityError("WebP contains too many chunks")
        if kind in {b"ANIM", b"ANMF"}:
            raise CharacterSecurityError("animated WebP is not implemented; use validated frame sequences")
        if kind == b"VP8X":
            if length != 10:
                raise CharacterSecurityError("WebP extended header is invalid")
            if payload[0] & 0x02:
                raise CharacterSecurityError("animated WebP is not implemented")
            width = 1 + int.from_bytes(payload[4:7], "little")
            height = 1 + int.from_bytes(payload[7:10], "little")
        elif kind == b"VP8 ":
            if length < 10 or payload[3:6] != b"\x9d\x01\x2a":
                raise CharacterSecurityError("lossy WebP frame header is corrupt")
            width = struct.unpack("<H", payload[6:8])[0] & 0x3FFF
            height = struct.unpack("<H", payload[8:10])[0] & 0x3FFF
            saw_image = True
        elif kind == b"VP8L":
            if length < 5 or payload[0] != 0x2F:
                raise CharacterSecurityError("lossless WebP frame header is corrupt")
            packed = int.from_bytes(payload[1:5], "little")
            width = (packed & 0x3FFF) + 1
            height = ((packed >> 14) & 0x3FFF) + 1
            saw_image = True
        offset = padded_end
    if offset != len(data) or not saw_image:
        raise CharacterSecurityError("WebP has no complete static image frame")
    return ImageInfo("image/webp", width, height, _bounded_dimensions(width, height))
