# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import unittest
from unittest.mock import patch
import zipfile

from companion.character.errors import CharacterError, CharacterSecurityError
from companion.character.importer import CharacterPackageImporter, PackageRegistry
from companion.character.package import ValidationLimits
from companion.character.schema import PackageTrustState

from .character_support import CharacterPackageFixture


class ImportSuccessTests(CharacterPackageFixture, unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.registry = PackageRegistry(self.root / "registry")
        self.importer = CharacterPackageImporter(self.registry)

    def test_directory_import_is_integrity_verified_but_creator_untrusted(self) -> None:
        record = self.importer.import_package(self.package_root)
        self.assertEqual(record.trust_state, PackageTrustState.VERIFIED_INTEGRITY)
        self.assertEqual(record.previous_trust_state, PackageTrustState.IMPORTED_UNVERIFIED)
        self.assertTrue(record.integrity_verified)
        self.assertFalse(record.creator_trusted)
        self.assertTrue(record.path.is_dir())

    def test_valid_zip_archive_import(self) -> None:
        record = self.importer.import_package(self.archive())
        self.assertEqual(record.package_id, "org.bunny-os.default-bunny")
        self.assertTrue((record.path / "manifest.json").is_file())

    def test_import_does_not_activate_package(self) -> None:
        self.importer.import_package(self.package_root)
        self.assertIsNone(self.registry.selected())

    def test_select_records_exact_digest(self) -> None:
        record = self.importer.import_package(self.package_root)
        selected = self.registry.select(record.package_id, package_digest=record.package_digest)
        self.assertEqual(selected.package_digest, record.package_digest)
        self.assertEqual(self.registry.selected().package_digest, record.package_digest)

    def test_previous_working_version_is_preserved(self) -> None:
        first = self.importer.import_package(self.package_root)
        manifest = self.manifest(); manifest["packageVersion"] = "1.0.1"; self.write_manifest(manifest)
        second = self.importer.import_package(self.package_root)
        self.assertNotEqual(first.path, second.path)
        self.assertTrue(first.path.is_dir())
        self.assertTrue(second.path.is_dir())
        self.assertEqual(len(self.registry.list()), 2)

    def test_reimport_is_idempotent_and_does_not_overwrite_in_place(self) -> None:
        first = self.importer.import_package(self.package_root)
        second = self.importer.import_package(self.package_root)
        self.assertEqual(first.path, second.path)
        self.assertEqual(len(self.registry.list()), 1)

    def test_quarantine_disables_selection(self) -> None:
        record = self.importer.import_package(self.package_root)
        self.registry.select(record.package_id)
        changed = self.registry.set_trust_state(record.package_digest, PackageTrustState.QUARANTINED)
        self.assertEqual(changed.trust_state, PackageTrustState.QUARANTINED)
        self.assertIsNone(self.registry.selected())
        with self.assertRaises(CharacterSecurityError):
            self.registry.select(record.package_id)

    def test_corruption_after_install_is_detected_at_selection(self) -> None:
        record = self.importer.import_package(self.package_root)
        (record.path / "assets" / "idle-1.png").write_bytes(b"corrupt")
        with self.assertRaises(CharacterError):
            self.registry.select(record.package_id)

    def test_tampered_registry_path_cannot_escape_install_root(self) -> None:
        self.importer.import_package(self.package_root)
        document = json.loads(self.registry.registry_path.read_text(encoding="utf-8"))
        document["packages"][0]["path"] = str(self.package_root)
        self.registry.registry_path.write_text(
            json.dumps(document), encoding="utf-8", newline="\n"
        )
        with self.assertRaisesRegex(CharacterError, "escapes the package registry"):
            self.registry.list()


class ImportRefusalTests(CharacterPackageFixture, unittest.TestCase):
    def importer(self, limits: ValidationLimits | None = None) -> CharacterPackageImporter:
        return CharacterPackageImporter(PackageRegistry(self.root / "registry"), limits=limits)

    def one_entry_zip(self, name: str, data: bytes = b"x", *, info: zipfile.ZipInfo | None = None) -> Path:
        output = self.root / "hostile.zip"
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            if info is None:
                archive.writestr(name, data)
            else:
                archive.writestr(info, data)
        return output

    def test_unsupported_archive_type(self) -> None:
        source = self.root / "character.tar"; source.write_bytes(b"not a package")
        with self.assertRaisesRegex(CharacterSecurityError, "only package directories"):
            self.importer().import_package(source)

    def test_archive_path_traversal(self) -> None:
        with self.assertRaisesRegex(CharacterSecurityError, "escapes"):
            self.importer().import_package(self.one_entry_zip("../escape.png"))

    def test_archive_absolute_path(self) -> None:
        with self.assertRaisesRegex(CharacterSecurityError, "escapes"):
            self.importer().import_package(self.one_entry_zip("/absolute.png"))

    def test_archive_drive_qualified_path(self) -> None:
        with self.assertRaisesRegex(CharacterSecurityError, "drive-qualified"):
            self.importer().import_package(self.one_entry_zip("C:/escape.png"))

    def test_archive_symlink(self) -> None:
        info = zipfile.ZipInfo("assets/link.png")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        with self.assertRaisesRegex(CharacterSecurityError, "symlink"):
            self.importer().import_package(self.one_entry_zip(info.filename, b"idle-1.png", info=info))

    def test_archive_executable_file(self) -> None:
        archive = self.archive()
        with zipfile.ZipFile(archive, "a", zipfile.ZIP_DEFLATED) as output:
            output.writestr("assets/run.py", "print('no')")
        with self.assertRaises(CharacterSecurityError):
            self.importer().import_package(archive)

    def test_compression_bomb_shape(self) -> None:
        with self.assertRaisesRegex(CharacterSecurityError, "decompression bomb"):
            self.importer().import_package(self.one_entry_zip("bomb.txt", b"A" * 1_000_000))

    def test_compressed_size_limit(self) -> None:
        archive = self.archive()
        with patch("companion.character.importer.MAX_ARCHIVE_BYTES", 1):
            with self.assertRaisesRegex(CharacterSecurityError, "compressed archive"):
                self.importer().import_package(archive)

    def test_extracted_size_limit(self) -> None:
        limits = ValidationLimits(maximum_files=512, maximum_total_bytes=1024, maximum_manifest_bytes=1024 * 1024)
        with self.assertRaisesRegex(CharacterSecurityError, "size"):
            self.importer(limits).import_package(self.package_root)

    def test_file_count_limit(self) -> None:
        limits = ValidationLimits(maximum_files=2, maximum_total_bytes=256 * 1024 * 1024)
        with self.assertRaisesRegex(CharacterSecurityError, "file-count"):
            self.importer(limits).import_package(self.package_root)

    def test_directory_hard_link(self) -> None:
        source = self.package_root / "assets" / "idle-1.png"
        link = self.package_root / "assets" / "hardlink.png"
        try:
            os.link(source, link)
        except OSError as exc:
            self.skipTest(f"hard links unavailable: {exc}")
        with self.assertRaises(CharacterSecurityError):
            self.importer().import_package(self.package_root)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "device-like FIFO unavailable")
    def test_directory_special_file(self) -> None:
        fifo = self.package_root / "assets" / "device.png"
        try:
            os.mkfifo(fifo)
        except OSError as exc:
            self.skipTest(f"FIFO creation unavailable: {exc}")
        with self.assertRaisesRegex(CharacterSecurityError, "special file"):
            self.importer().import_package(self.package_root)


if __name__ == "__main__":
    unittest.main()
