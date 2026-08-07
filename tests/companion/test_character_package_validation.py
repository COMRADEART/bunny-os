# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import json
from pathlib import Path
import shutil
import unittest

from companion.character.errors import (
    CharacterCompatibilityError,
    CharacterIntegrityError,
    CharacterSchemaError,
    CharacterSecurityError,
)
from companion.character.image import inspect_image
from companion.character.mapper import CharacterState
from companion.character.package import validate_package_directory
from companion.character.schema import PackageTrustState, REQUIRED_CHARACTER_STATES

from .character_support import CharacterPackageFixture


class ValidPackageTests(CharacterPackageFixture, unittest.TestCase):
    def test_default_animated_package_validates_every_asset(self) -> None:
        package = validate_package_directory(self.package_root, trust_state=PackageTrustState.BUILT_IN)
        self.assertEqual(package.manifest.presentation_type.value, "animated-2d")
        self.assertEqual(set(package.image_info), {
            item.asset_id for item in package.manifest.assets if item.media_type.startswith("image/")
        })
        self.assertTrue(package.package_digest)

    def test_valid_static_package(self) -> None:
        self.make_static()
        package = validate_package_directory(self.package_root)
        self.assertEqual(package.manifest.presentation_type.value, "static-image")

    def test_generation_provenance_is_optional_for_manual_art(self) -> None:
        package = validate_package_directory(self.package_root)
        self.assertIsNone(package.manifest.generation_provenance)
        self.assertIsNone(package.manifest.source_prompt_metadata)

    def test_all_required_character_states_are_in_the_contract(self) -> None:
        self.assertEqual(tuple(state.value for state in CharacterState), REQUIRED_CHARACTER_STATES)

    def test_every_default_frame_has_bounded_dimensions(self) -> None:
        package = validate_package_directory(self.package_root)
        for asset_id, info in package.image_info.items():
            with self.subTest(asset_id=asset_id):
                self.assertEqual((info.width, info.height), (96, 96))
                self.assertLessEqual(info.decoded_bytes, 64 * 1024 * 1024)


class InvalidManifestTests(CharacterPackageFixture, unittest.TestCase):
    def mutate(self, callback) -> None:
        value = self.manifest(); callback(value); self.write_manifest(value)

    def test_missing_manifest(self) -> None:
        self.manifest_path.unlink()
        with self.assertRaisesRegex(CharacterSchemaError, "missing manifest"):
            validate_package_directory(self.package_root)

    def test_invalid_schema_version(self) -> None:
        self.mutate(lambda value: value.__setitem__("schemaVersion", 99))
        with self.assertRaisesRegex(CharacterSchemaError, "schemaVersion"):
            validate_package_directory(self.package_root)

    def test_unknown_manifest_field_is_rejected(self) -> None:
        self.mutate(lambda value: value.__setitem__("runThis", "no"))
        with self.assertRaisesRegex(CharacterSchemaError, "unsupported fields"):
            validate_package_directory(self.package_root)

    def test_duplicate_json_field_is_rejected(self) -> None:
        text = self.manifest_path.read_text(encoding="utf-8")
        self.manifest_path.write_text(text.replace('"schemaVersion": 1,', '"schemaVersion": 1,\n  "schemaVersion": 1,'), encoding="utf-8")
        with self.assertRaisesRegex(CharacterSchemaError, "repeats field"):
            validate_package_directory(self.package_root)

    def test_missing_license_name(self) -> None:
        self.mutate(lambda value: value.__setitem__("license", ""))
        with self.assertRaisesRegex(CharacterSchemaError, "license is required"):
            validate_package_directory(self.package_root)

    def test_missing_fallback(self) -> None:
        self.mutate(lambda value: value.__setitem__("fallbackAsset", "absent"))
        with self.assertRaisesRegex(CharacterSchemaError, "fallbackAsset"):
            validate_package_directory(self.package_root)

    def test_duplicate_asset_is_rejected(self) -> None:
        self.mutate(lambda value: value["assetInventory"].append(dict(value["assetInventory"][0])))
        with self.assertRaisesRegex(CharacterSchemaError, "repeats"):
            validate_package_directory(self.package_root)

    def test_a_reserved_presentation_type_is_rejected(self) -> None:
        """``skeletal-2d`` is reserved and unimplemented, and says so.

        This test named ``full-3d`` until the 3D renderer landed, at which point
        ``full-3d`` stopped being a reserved name and became a rung. The
        property under test is not "3D is refused" — it is that a *reserved*
        name is refused with a message that says it is reserved rather than
        unknown, so a package author can tell "not yet" from "never".
        """
        self.mutate(lambda value: value.__setitem__("presentationType", "skeletal-2d"))
        with self.assertRaisesRegex(CharacterSchemaError, "reserved but not implemented"):
            validate_package_directory(self.package_root)

    def test_a_3d_presentation_without_a_3d_section_is_rejected(self) -> None:
        """A rung that exists is not a rung a 2D package may claim."""
        self.mutate(lambda value: value.__setitem__("presentationType", "full-3d"))
        with self.assertRaisesRegex(CharacterSchemaError, "renderer version|threeDimensional"):
            validate_package_directory(self.package_root)

    def test_external_runtime_asset_url_is_rejected(self) -> None:
        self.mutate(lambda value: value["assetInventory"][0].__setitem__("path", "https://example.test/bunny.png"))
        with self.assertRaisesRegex(CharacterSecurityError, "package-relative"):
            validate_package_directory(self.package_root)

    def test_parent_traversal_is_rejected(self) -> None:
        self.mutate(lambda value: value["assetInventory"][0].__setitem__("path", "../bunny.png"))
        with self.assertRaisesRegex(CharacterSecurityError, "escapes"):
            validate_package_directory(self.package_root)

    def test_absolute_path_is_rejected(self) -> None:
        self.mutate(lambda value: value["assetInventory"][0].__setitem__("path", "/tmp/bunny.png"))
        with self.assertRaisesRegex(CharacterSecurityError, "escapes"):
            validate_package_directory(self.package_root)

    def test_script_suffix_is_rejected(self) -> None:
        self.mutate(lambda value: value["assetInventory"][0].__setitem__("path", "assets/bunny.js"))
        with self.assertRaisesRegex(CharacterSecurityError, "forbidden"):
            validate_package_directory(self.package_root)

    def test_malicious_svg_is_rejected(self) -> None:
        self.mutate(lambda value: value["assetInventory"][0].__setitem__("path", "assets/bunny.svg"))
        with self.assertRaisesRegex(CharacterSecurityError, "forbidden"):
            validate_package_directory(self.package_root)

    def test_credentials_in_generation_metadata_are_rejected(self) -> None:
        self.mutate(lambda value: value.__setitem__("generationProvenance", {"apiKey": "not-allowed"}))
        with self.assertRaisesRegex(CharacterSecurityError, "credentials"):
            validate_package_directory(self.package_root)

    def test_credential_like_value_under_innocent_key_is_rejected(self) -> None:
        self.mutate(lambda value: value.__setitem__(
            "sourcePromptMetadata", {"note": "sk-abcdefghijklmnopqrstuvwxyz123456"}
        ))
        with self.assertRaisesRegex(CharacterSecurityError, "credential-like"):
            validate_package_directory(self.package_root)

    def test_minimum_bunny_version_is_enforced(self) -> None:
        self.mutate(lambda value: value.__setitem__("minimumBunnyOsVersion", "99.0"))
        with self.assertRaises(CharacterCompatibilityError):
            validate_package_directory(self.package_root)

    def test_excessive_image_dimensions_are_rejected(self) -> None:
        self.mutate(lambda value: value["declaredDimensions"].__setitem__("width", 5000))
        with self.assertRaisesRegex(CharacterSchemaError, "width"):
            validate_package_directory(self.package_root)

    def test_missing_idle_animation_is_rejected(self) -> None:
        self.mutate(lambda value: value["stateMap"].pop("idle"))
        with self.assertRaisesRegex(CharacterSchemaError, "define idle"):
            validate_package_directory(self.package_root)

    def test_loop_cannot_depend_on_completion_to_transition(self) -> None:
        self.mutate(lambda value: value["animations"]["idle"].__setitem__(
            "transition", "non-interruptible"
        ))
        with self.assertRaisesRegex(CharacterSchemaError, "looping animation"):
            validate_package_directory(self.package_root)


class IntegrityAndFilesystemTests(CharacterPackageFixture, unittest.TestCase):
    def test_hash_mismatch(self) -> None:
        _record, path = self.asset("idle-1")
        path.write_bytes(path.read_bytes() + b"x")
        with self.assertRaisesRegex(CharacterIntegrityError, "size"):
            validate_package_directory(self.package_root)

    def test_undeclared_file(self) -> None:
        (self.package_root / "surprise.txt").write_text("undeclared", encoding="utf-8")
        with self.assertRaisesRegex(CharacterSecurityError, "undeclared"):
            validate_package_directory(self.package_root)

    def test_missing_declared_file(self) -> None:
        _record, path = self.asset("idle-1"); path.unlink()
        with self.assertRaisesRegex(CharacterIntegrityError, "missing declared"):
            validate_package_directory(self.package_root)

    def test_corrupt_image_is_rejected_even_when_its_hash_matches(self) -> None:
        _record, path = self.asset("idle-1")
        data = bytearray(path.read_bytes()); data[-8] ^= 0xFF; path.write_bytes(data)
        self.rehash("idle-1")
        with self.assertRaises(CharacterSecurityError):
            validate_package_directory(self.package_root)

    def test_empty_license_file(self) -> None:
        _record, path = self.asset("license"); path.write_text(" ", encoding="utf-8"); self.rehash("license")
        with self.assertRaisesRegex(CharacterSchemaError, "license file is empty"):
            validate_package_directory(self.package_root)

    @unittest.skipUnless(hasattr(Path, "symlink_to"), "symlinks unavailable")
    def test_symlink_is_rejected(self) -> None:
        _record, path = self.asset("idle-2")
        path.unlink()
        try:
            path.symlink_to(self.package_root / "assets" / "idle-1.png")
        except OSError as exc:
            self.skipTest(f"symlink creation unavailable: {exc}")
        with self.assertRaisesRegex(CharacterSecurityError, "symlink"):
            validate_package_directory(self.package_root)


class SchemaDocumentTests(CharacterPackageFixture, unittest.TestCase):
    def test_schema_document_is_strict_and_names_only_implemented_presentations(self) -> None:
        schema = json.loads(Path("schemas/companion-character-package-v1.schema.json").read_text(encoding="utf-8"))
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["presentationType"]["enum"], ["static-image", "animated-2d"])

    def test_default_manifest_conforms_when_jsonschema_is_available(self) -> None:
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema is not installed; strict manual validation still ran")
        schema = json.loads(Path("schemas/companion-character-package-v1.schema.json").read_text(encoding="utf-8"))
        jsonschema.validate(self.manifest(), schema)


if __name__ == "__main__":
    unittest.main()
