# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import base64
import binascii
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

from companion.character.defaults import default_character_path
from companion.character.errors import CharacterSecurityError
from companion.character.image import PNG_SIGNATURE, inspect_image


def chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", binascii.crc32(kind + payload) & 0xFFFFFFFF)


class ImageDecoderBoundaryTests(unittest.TestCase):
    def temporary_image(self, data: bytes, suffix: str) -> tuple[tempfile.TemporaryDirectory, Path]:
        temporary = tempfile.TemporaryDirectory(prefix="bunny-image-")
        path = Path(temporary.name) / f"image{suffix}"
        path.write_bytes(data)
        return temporary, path

    def test_valid_png_is_fully_inflated_with_bounds(self) -> None:
        path = default_character_path() / "assets" / "idle-1.png"
        info = inspect_image(path)
        self.assertEqual((info.media_type, info.width, info.height), ("image/png", 96, 96))

    def test_valid_static_webp_is_supported(self) -> None:
        # Public 1x1 lossless WebP bitstream; no external decoder is required.
        data = base64.b64decode("UklGRhoAAABXRUJQVlA4TA0AAAAvAAAAEAcQERGIiP4HAA==")
        temporary, path = self.temporary_image(data, ".webp"); self.addCleanup(temporary.cleanup)
        info = inspect_image(path)
        self.assertEqual((info.media_type, info.width, info.height), ("image/webp", 1, 1))

    def test_animated_webp_is_rejected_in_favour_of_frame_sequences(self) -> None:
        payload = b"ANIM" + struct.pack("<I", 6) + b"\x00" * 6
        if len(payload) & 1:
            payload += b"\x00"
        data = b"RIFF" + struct.pack("<I", len(payload) + 4) + b"WEBP" + payload
        temporary, path = self.temporary_image(data, ".webp"); self.addCleanup(temporary.cleanup)
        with self.assertRaisesRegex(CharacterSecurityError, "animated WebP"):
            inspect_image(path)

    def test_apng_control_chunk_is_rejected(self) -> None:
        source = (default_character_path() / "assets" / "idle-1.png").read_bytes()
        ihdr_end = 8 + 4 + 4 + 13 + 4
        data = source[:ihdr_end] + chunk(b"acTL", struct.pack(">II", 2, 0)) + source[ihdr_end:]
        temporary, path = self.temporary_image(data, ".png"); self.addCleanup(temporary.cleanup)
        with self.assertRaisesRegex(CharacterSecurityError, "APNG"):
            inspect_image(path)

    def test_png_decompression_bomb_shape_is_rejected(self) -> None:
        ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
        raw = b"\x00" + b"\x00\x00\x00\x00" * 10000
        data = PNG_SIGNATURE + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
        temporary, path = self.temporary_image(data, ".png"); self.addCleanup(temporary.cleanup)
        with self.assertRaisesRegex(CharacterSecurityError, "expands beyond"):
            inspect_image(path)

    def test_png_crc_corruption_is_rejected(self) -> None:
        data = bytearray((default_character_path() / "assets" / "idle-1.png").read_bytes())
        data[20] ^= 0x1
        temporary, path = self.temporary_image(bytes(data), ".png"); self.addCleanup(temporary.cleanup)
        with self.assertRaisesRegex(CharacterSecurityError, "checksum"):
            inspect_image(path)

    def test_excessive_png_dimensions_are_rejected_before_inflate(self) -> None:
        ihdr = struct.pack(">IIBBBBB", 5000, 1, 8, 6, 0, 0, 0)
        data = PNG_SIGNATURE + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(b"\x00")) + chunk(b"IEND", b"")
        temporary, path = self.temporary_image(data, ".png"); self.addCleanup(temporary.cleanup)
        with self.assertRaisesRegex(CharacterSecurityError, "dimensions"):
            inspect_image(path)

    def test_unknown_image_magic_is_rejected(self) -> None:
        temporary, path = self.temporary_image(b"not an image", ".png"); self.addCleanup(temporary.cleanup)
        with self.assertRaisesRegex(CharacterSecurityError, "not a supported"):
            inspect_image(path)


if __name__ == "__main__":
    unittest.main()
