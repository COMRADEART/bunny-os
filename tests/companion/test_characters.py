# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import stat
import tempfile
import unittest
import zipfile

from companion.characters import (
    MAX_ASSET_BYTES,
    REQUIRED_ANIMATIONS,
    CharacterPackage,
    CharacterPackageError,
    validate_archive,
    validate_directory,
)


ASSET = b"not-a-real-image-but-a-bounded-data-asset"


def manifest(asset_path: str = "fallback.png") -> dict:
    return {
        "schemaVersion": 1,
        "packageId": "example.bunny",
        "creator": "Example Creator",
        "license": "CC-BY-4.0",
        "characterName": "Example Bunny",
        "version": "1.0.0",
        "supportedRenderer": "static-image",
        "assetFiles": [{
            "path": asset_path,
            "sha256": hashlib.sha256(ASSET).hexdigest(),
            "sizeBytes": len(ASSET),
            "mediaType": "image/png",
        }],
        "thumbnail": asset_path,
        "fallbackImage": asset_path,
        "skeleton": {},
        "animationMap": {name: asset_path for name in REQUIRED_ANIMATIONS},
        "lipSync": {},
        "facialExpressionMap": {},
        "resourceEstimates": {"memoryBytes": 1024 * 1024, "vramBytes": 0},
        "minimumRenderingCapability": "static-image",
    }


class CharacterDirectoryTests(unittest.TestCase):
    def package(self, document: dict | None = None, *, asset_path: str = "fallback.png"):
        directory = tempfile.TemporaryDirectory()
        root = Path(directory.name)
        (root / asset_path).parent.mkdir(parents=True, exist_ok=True)
        (root / asset_path).write_bytes(ASSET)
        (root / "package.json").write_text(json.dumps(document or manifest(asset_path)), encoding="utf-8")
        return directory, root

    def test_valid_static_package(self) -> None:
        directory, root = self.package()
        try:
            package = validate_directory(root)
            self.assertEqual(package.package_id, "example.bunny")
        finally:
            directory.cleanup()

    def test_invalid_schema_version(self) -> None:
        document = manifest()
        document["schemaVersion"] = 99
        directory, root = self.package(document)
        try:
            with self.assertRaises(CharacterPackageError):
                validate_directory(root)
        finally:
            directory.cleanup()

    def test_missing_fallback_is_rejected(self) -> None:
        document = manifest()
        document["fallbackImage"] = "missing.png"
        directory, root = self.package(document)
        try:
            with self.assertRaises(CharacterPackageError):
                validate_directory(root)
        finally:
            directory.cleanup()

    def test_unsupported_renderer_is_rejected(self) -> None:
        document = manifest()
        document["supportedRenderer"] = "provider-proprietary-renderer"
        directory, root = self.package(document)
        try:
            with self.assertRaises(CharacterPackageError):
                validate_directory(root)
        finally:
            directory.cleanup()

    def test_hash_mismatch_is_rejected(self) -> None:
        document = manifest()
        document["assetFiles"][0]["sha256"] = "0" * 64
        directory, root = self.package(document)
        try:
            with self.assertRaisesRegex(CharacterPackageError, "hash mismatch"):
                validate_directory(root)
        finally:
            directory.cleanup()

    def test_path_traversal_is_rejected(self) -> None:
        with self.assertRaises(CharacterPackageError):
            CharacterPackage.from_json(manifest("../escape.png"))

    def test_oversized_declared_asset_is_rejected(self) -> None:
        document = manifest()
        document["assetFiles"][0]["sizeBytes"] = MAX_ASSET_BYTES + 1
        with self.assertRaises(CharacterPackageError):
            CharacterPackage.from_json(document)

    def test_executable_asset_type_is_rejected(self) -> None:
        with self.assertRaises(CharacterPackageError):
            CharacterPackage.from_json(manifest("payload.py"))

    def test_missing_license_is_rejected(self) -> None:
        document = manifest()
        document["license"] = ""
        with self.assertRaises(ValueError):
            CharacterPackage.from_json(document)

    def test_missing_animation_state_is_rejected(self) -> None:
        document = manifest()
        del document["animationMap"]["listening"]
        with self.assertRaises(CharacterPackageError):
            CharacterPackage.from_json(document)

    def test_excessive_resource_requirement_is_rejected(self) -> None:
        document = manifest()
        document["resourceEstimates"]["memoryBytes"] = 1 << 50
        with self.assertRaises(CharacterPackageError):
            CharacterPackage.from_json(document)

    def test_provider_credentials_in_generation_metadata_are_rejected(self) -> None:
        document = manifest()
        document["generationMetadata"] = {"apiKey": "must-not-ship"}
        with self.assertRaises(CharacterPackageError):
            CharacterPackage.from_json(document)

    def test_undeclared_hidden_file_is_rejected(self) -> None:
        directory, root = self.package()
        try:
            (root / "hidden.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(CharacterPackageError, "undeclared"):
                validate_directory(root)
        finally:
            directory.cleanup()


class CharacterArchiveTests(unittest.TestCase):
    def archive(self, entries: dict[str, bytes], document: dict | None = None) -> tuple[tempfile.TemporaryDirectory, Path]:
        directory = tempfile.TemporaryDirectory()
        path = Path(directory.name) / "character.zip"
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr("package.json", json.dumps(document or manifest()).encode("utf-8"))
            for name, value in entries.items():
                archive.writestr(name, value)
        return directory, path

    def test_valid_archive(self) -> None:
        directory, path = self.archive({"fallback.png": ASSET})
        try:
            self.assertEqual(validate_archive(path).character_name, "Example Bunny")
        finally:
            directory.cleanup()

    def test_archive_path_traversal_is_rejected(self) -> None:
        directory, path = self.archive({"fallback.png": ASSET, "../escape.png": b"bad"})
        try:
            with self.assertRaises(CharacterPackageError):
                validate_archive(path)
        finally:
            directory.cleanup()

    def test_archive_executable_is_rejected(self) -> None:
        directory, path = self.archive({"fallback.png": ASSET, "payload.sh": b"echo no"})
        try:
            with self.assertRaises(CharacterPackageError):
                validate_archive(path)
        finally:
            directory.cleanup()

    def test_archive_symlink_is_rejected(self) -> None:
        directory = tempfile.TemporaryDirectory()
        path = Path(directory.name) / "symlink.zip"
        try:
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("package.json", json.dumps(manifest()))
                info = zipfile.ZipInfo("fallback.png")
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(info, b"target")
            with self.assertRaisesRegex(CharacterPackageError, "symlink"):
                validate_archive(path)
        finally:
            directory.cleanup()

    def test_compression_bomb_shape_is_rejected(self) -> None:
        directory = tempfile.TemporaryDirectory()
        path = Path(directory.name) / "compressed.zip"
        payload = b"0" * (1024 * 1024)
        document = manifest()
        document["assetFiles"][0].update({
            "sha256": hashlib.sha256(payload).hexdigest(),
            "sizeBytes": len(payload),
        })
        try:
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("package.json", json.dumps(document))
                archive.writestr("fallback.png", payload)
            with self.assertRaisesRegex(CharacterPackageError, "compression ratio"):
                validate_archive(path)
        finally:
            directory.cleanup()


if __name__ == "__main__":
    unittest.main()
