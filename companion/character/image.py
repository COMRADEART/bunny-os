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


@dataclass(frozen=True)
class DecodedImage:
    """Straight-line RGBA8 pixels, produced only after the container validated."""

    width: int
    height: int
    rgba: bytes

    def to_json(self) -> dict[str, int]:
        return {"width": self.width, "height": self.height, "decodedBytes": len(self.rgba)}


@dataclass(frozen=True)
class _PngPayload:
    """What one validated PNG holds, before any pixel is reconstructed."""

    width: int
    height: int
    bit_depth: int
    color_type: int
    palette: bytes
    transparency: bytes
    scanlines: bytes


def _inspect_png(data: bytes) -> ImageInfo:
    payload = _read_png(data)
    return ImageInfo(
        "image/png", payload.width, payload.height,
        _bounded_dimensions(payload.width, payload.height),
    )


def _read_png(data: bytes) -> _PngPayload:
    """Walk, checksum and bounded-inflate a PNG. The only PNG reader here.

    Both :func:`inspect_image` and :func:`decode_png_rgba` go through this, and
    that is the point: a decoder that validated on one path and not the other
    would be a decoder with a way in. The bounded inflate, the filter check and
    the chunk rules below are the ones the character package validator has
    always applied; reconstructing pixels happens *after* they pass, never
    beside them.
    """
    offset = len(PNG_SIGNATURE)
    width = height = bit_depth = color_type = 0
    interlace = -1
    saw_ihdr = saw_iend = saw_palette = False
    palette = b""
    transparency = b""
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
            palette = bytes(payload)
            saw_palette = True
        elif kind == b"tRNS":
            if not saw_ihdr or saw_iend or transparency:
                raise CharacterSecurityError("PNG transparency chunk is misplaced or repeated")
            if color_type in {4, 6} or length > 256:
                raise CharacterSecurityError("PNG transparency chunk is invalid for its colour type")
            transparency = bytes(payload)
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
    _bounded_dimensions(width, height)
    return _PngPayload(width, height, bit_depth, color_type, palette, transparency, bytes(raw))


def _unfilter(payload: _PngPayload) -> bytearray:
    """Reverse the five PNG scanline filters. Bounded by the inflate above."""
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[payload.color_type]
    bits = channels * payload.bit_depth
    row_bytes = (payload.width * bits + 7) // 8
    step = max(1, bits // 8)
    output = bytearray(row_bytes * payload.height)
    previous = bytearray(row_bytes)
    source = payload.scanlines
    for row in range(payload.height):
        base = row * (row_bytes + 1)
        filter_type = source[base]
        line = bytearray(source[base + 1:base + 1 + row_bytes])
        if filter_type == 1:
            for index in range(step, row_bytes):
                line[index] = (line[index] + line[index - step]) & 0xFF
        elif filter_type == 2:
            for index in range(row_bytes):
                line[index] = (line[index] + previous[index]) & 0xFF
        elif filter_type == 3:
            for index in range(row_bytes):
                left = line[index - step] if index >= step else 0
                line[index] = (line[index] + ((left + previous[index]) >> 1)) & 0xFF
        elif filter_type == 4:
            for index in range(row_bytes):
                left = line[index - step] if index >= step else 0
                upper_left = previous[index - step] if index >= step else 0
                above = previous[index]
                estimate = left + above - upper_left
                distance_left = abs(estimate - left)
                distance_above = abs(estimate - above)
                distance_corner = abs(estimate - upper_left)
                if distance_left <= distance_above and distance_left <= distance_corner:
                    predictor = left
                elif distance_above <= distance_corner:
                    predictor = above
                else:
                    predictor = upper_left
                line[index] = (line[index] + predictor) & 0xFF
        output[row * row_bytes:(row + 1) * row_bytes] = line
        previous = line
    return output


def decode_png_rgba(data: bytes, *, maximum_dimension: int = MAX_IMAGE_DIMENSION) -> DecodedImage:
    """Validate a PNG and return straight RGBA8 bytes.

    Added for the 3D renderer, which needs pixels rather than a description of
    them, and deliberately placed beside the validator rather than in the
    renderer: a second PNG reader in this repository would be a second set of
    the bugs this one has already been hardened against.

    ``maximum_dimension`` is the *caller's* ceiling and is applied on top of the
    module's own. The 3D validator passes its texture limit, which is smaller
    than the 2D one because a texture is uploaded to a GPU rather than blitted.
    """
    payload = _read_png(data)
    if payload.width > maximum_dimension or payload.height > maximum_dimension:
        raise CharacterSecurityError(
            f"texture is {payload.width}x{payload.height}; the limit is {maximum_dimension} per side"
        )
    if payload.color_type == 3:
        if payload.bit_depth not in {1, 2, 4, 8}:
            raise CharacterSecurityError("indexed PNG bit depth is unsupported")
    elif payload.bit_depth not in {8, 16}:
        raise CharacterSecurityError("PNG bit depth is unsupported for decoding")

    raw = _unfilter(payload)
    width, height = payload.width, payload.height
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[payload.color_type]
    row_bytes = (width * channels * payload.bit_depth + 7) // 8
    rgba = bytearray(width * height * 4)

    def _sample(row: int, column: int) -> tuple[int, ...]:
        if payload.bit_depth == 16:
            base = row * row_bytes + column * channels * 2
            return tuple(raw[base + component * 2] for component in range(channels))
        if payload.bit_depth == 8:
            base = row * row_bytes + column * channels
            return tuple(raw[base + component] for component in range(channels))
        per_byte = 8 // payload.bit_depth
        mask = (1 << payload.bit_depth) - 1
        index = row * row_bytes + column // per_byte
        shift = 8 - payload.bit_depth * (column % per_byte + 1)
        return ((raw[index] >> shift) & mask,)

    transparent_grey = None
    transparent_rgb = None
    if payload.transparency and payload.color_type == 0 and len(payload.transparency) >= 2:
        transparent_grey = int.from_bytes(payload.transparency[:2], "big")
    if payload.transparency and payload.color_type == 2 and len(payload.transparency) >= 6:
        transparent_rgb = tuple(
            int.from_bytes(payload.transparency[item * 2:item * 2 + 2], "big") for item in range(3)
        )

    maximum = (1 << payload.bit_depth) - 1
    for row in range(height):
        for column in range(width):
            sample = _sample(row, column)
            if payload.color_type == 0:
                value = sample[0] if payload.bit_depth != 16 else sample[0]
                alpha = 0 if transparent_grey is not None and sample[0] == (
                    transparent_grey >> 8 if payload.bit_depth == 16 else transparent_grey
                ) else 255
                pixel = (value, value, value, alpha)
            elif payload.color_type == 2:
                alpha = 255
                if transparent_rgb is not None:
                    scaled = tuple(
                        component >> 8 if payload.bit_depth == 16 else component
                        for component in transparent_rgb
                    )
                    if tuple(sample) == scaled:
                        alpha = 0
                pixel = (sample[0], sample[1], sample[2], alpha)
            elif payload.color_type == 3:
                entry = sample[0]
                if entry * 3 + 2 >= len(payload.palette):
                    raise CharacterSecurityError("indexed PNG references a palette entry that does not exist")
                alpha = payload.transparency[entry] if entry < len(payload.transparency) else 255
                pixel = (
                    payload.palette[entry * 3],
                    payload.palette[entry * 3 + 1],
                    payload.palette[entry * 3 + 2],
                    alpha,
                )
            elif payload.color_type == 4:
                pixel = (sample[0], sample[0], sample[0], sample[1])
            else:
                pixel = (sample[0], sample[1], sample[2], sample[3])
            if payload.color_type == 3 and payload.bit_depth < 8:
                pixel = pixel  # palette entries are already eight-bit
            elif payload.bit_depth == 1 or payload.bit_depth == 2 or payload.bit_depth == 4:
                scale = 255 // maximum
                pixel = tuple(component * scale for component in pixel[:3]) + (pixel[3],)
            base = (row * width + column) * 4
            rgba[base:base + 4] = bytes(pixel)
    return DecodedImage(width, height, bytes(rgba))


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
