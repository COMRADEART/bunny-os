# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""§5, §25, §26 and §27: the package contract, the built-in, and importing one.

The through-line of this file is that the built-in 3D character is not special.
§25 says so explicitly — "the default package must pass exactly the same
validator used for imported packages; do not create a built-in validation
bypass" — and the strongest way to test that is to *import* the built-in package
through the ordinary importer and assert that what comes out the far end has the
same digest. If a bypass existed, that round trip is where it would show.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest
import zipfile

from companion.character.defaults import (
    default_3d_character_path,
    default_character_path,
    default_character_paths,
)
from companion.character.errors import (
    CharacterError,
    CharacterIntegrityError,
    CharacterSchemaError,
    CharacterSecurityError,
)
from companion.character.importer import CharacterPackageImporter, PackageRegistry
from companion.character.package import validate_package_directory
from companion.character.schema import (
    IMPLEMENTED_PRESENTATIONS,
    THREE_D_PRESENTATIONS,
    PackageTrustState,
)
from companion.character.three_d.package3d import (
    MANDATORY_ANIMATION_STATES,
    RENDERER_FEATURES,
    ThreeDSection,
)


def _built_in_or_skip() -> Path:
    root = default_3d_character_path()
    if not root.is_dir():
        raise unittest.SkipTest("the built-in 3D package is not installed here")
    return root


class BuiltInPackageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = _built_in_or_skip()
        self.package = validate_package_directory(
            self.root, trust_state=PackageTrustState.BUILT_IN
        )

    def test_the_built_in_3d_package_validates(self) -> None:
        self.assertIsNotNone(self.package.model)
        self.assertEqual(self.package.manifest.package_id, "bunny-default-3d")
        self.assertIn(self.package.manifest.presentation_type.value, THREE_D_PRESENTATIONS)

    def test_it_is_a_human_shaped_rigged_character(self) -> None:
        model = self.package.model
        skeleton = model.skeleton
        for bone in ("root", "hips", "spine", "chest", "neck", "head"):
            self.assertTrue(skeleton.has(bone), f"the built-in character has no {bone}")
        for side in ("left", "right"):
            for limb in ("upper_arm", "lower_arm", "hand", "upper_leg", "lower_leg", "foot"):
                self.assertTrue(skeleton.has(f"{side}_{limb}"))
        self.assertGreater(model.bounds.height, 1.0, "a person-sized figure")
        self.assertLess(model.bounds.height, 2.5)

    def test_it_carries_every_state_animation_section_25_names(self) -> None:
        section = self.package.manifest.three_dimensional
        for state in (
            "idle", "listening", "planning", "working", "reviewing", "speaking",
            "success", "warning", "error", "sleeping",
        ):
            self.assertIn(state, section.animation_map, f"no clip for {state}")
        for name in section.animation_map.values():
            self.assertIsNotNone(self.package.model.clip(name))

    def test_it_carries_facial_expressions_and_mouth_morphs(self) -> None:
        section = self.package.manifest.three_dimensional
        self.assertGreaterEqual(len(section.morph_targets), 8)
        self.assertIn("happy", section.expression_map)
        self.assertIn("open-wide", section.viseme_map)
        for shape in ("open-small", "open-medium", "open-wide", "rounded", "smile"):
            self.assertIn(shape, section.viseme_map)

    def test_it_retains_a_static_and_an_animated_2d_fallback(self) -> None:
        """§5: a 3D package keeps the rungs below it inside itself."""
        section = self.package.manifest.three_dimensional
        manifest = self.package.manifest
        self.assertIn(section.static_fallback_asset, {asset.asset_id for asset in manifest.assets})
        self.assertIn(section.animated_fallback_state, manifest.state_map)
        self.assertTrue(
            any(animation.kind == "frame-sequence" for animation in manifest.animations.values()),
            "no animated-2D fallback",
        )

    def test_it_describes_every_mapped_state_for_a_screen_reader(self) -> None:
        section = self.package.manifest.three_dimensional
        for state in section.animation_map:
            self.assertIn(state, section.accessibility_states)
            self.assertGreater(len(section.accessibility_states[state]), 10)

    def test_the_declared_budget_bounds_the_actual_model(self) -> None:
        section = self.package.manifest.three_dimensional
        model = self.package.model
        self.assertLessEqual(model.triangle_count, section.maximum_triangles)
        self.assertLessEqual(model.vertex_count, section.maximum_vertices)
        self.assertLessEqual(len(model.joints), section.maximum_joints)
        self.assertLessEqual(len(model.morph_target_names), section.maximum_morph_targets)
        self.assertLessEqual(model.estimated_gpu_bytes, section.declared_gpu_bytes)
        self.assertLessEqual(model.decoded_texture_bytes, section.declared_decoded_bytes)

    def test_the_declared_digest_is_the_model_on_disk(self) -> None:
        import hashlib

        section = self.package.manifest.three_dimensional
        data = (self.root / Path(section.model_file)).read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), section.model_digest)
        self.assertEqual(self.package.model.digest, section.model_digest)

    def test_provenance_records_what_section_26_asks_for(self) -> None:
        provenance = json.loads((self.root / "PROVENANCE.json").read_text(encoding="utf-8"))
        for field in (
            "creator", "creationSource", "generated", "handCreated", "tool",
            "generationWorkflow", "modificationHistory", "licence",
        ):
            self.assertIn(field, provenance)
        self.assertTrue(provenance["generated"])
        self.assertFalse(provenance["handCreated"])
        self.assertEqual(provenance["derivedFrom"], "nothing")
        self.assertEqual(provenance["thirdPartyContent"], "none")

    def test_the_licence_is_the_repositorys_own(self) -> None:
        licence = (self.root / "LICENSE.txt").read_text(encoding="utf-8")
        self.assertIn("GPL-3.0-or-later", licence)
        self.assertIn("ComradeArt", licence)
        for forbidden in ("mixamo", "unreal", "unity asset", "sketchfab", "turbosquid"):
            self.assertNotIn(forbidden, licence.casefold())

    def test_the_package_contains_no_executable_content(self) -> None:
        for path in self.root.rglob("*"):
            if path.is_dir():
                continue
            self.assertIn(
                path.suffix.casefold(), {".png", ".glb", ".txt", ".json"},
                f"{path.name} is not a data asset",
            )

    def test_the_2d_default_still_exists_and_is_still_the_default(self) -> None:
        """§24: adding a 3D character must not change what a machine draws."""
        paths = default_character_paths()
        self.assertEqual(default_character_path().name, "default-bunny")
        self.assertLess(
            [path.name for path in paths].index("default-bunny"),
            [path.name for path in paths].index("default-bunny-3d"),
        )


class SectionSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        root = _built_in_or_skip()
        self.document = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        self.section = dict(self.document["threeDimensional"])

    def _parse(self, **changes):
        payload = dict(self.section)
        payload.update(changes)
        return ThreeDSection.from_json(payload)

    def test_the_built_in_section_parses(self) -> None:
        parsed = self._parse()
        self.assertEqual(parsed.gltf_version, "2.0")
        self.assertEqual(parsed.skeleton_profile, "bunny-humanoid-1")

    def test_an_unknown_field_is_refused(self) -> None:
        with self.assertRaisesRegex(CharacterSchemaError, "unsupported fields"):
            self._parse(runScript="rm -rf /")

    def test_a_future_schema_version_is_refused(self) -> None:
        with self.assertRaisesRegex(CharacterSchemaError, "schemaVersion"):
            self._parse(schemaVersion=99)

    def test_a_foreign_renderer_api_major_is_refused(self) -> None:
        with self.assertRaisesRegex(CharacterSchemaError, "rendererApiVersion"):
            self._parse(rendererApiVersion="9.0")

    def test_an_unknown_skeleton_profile_is_refused(self) -> None:
        with self.assertRaisesRegex(CharacterSchemaError, "skeletonProfile"):
            self._parse(skeletonProfile="vrm-1.0")

    def test_a_missing_mandatory_animation_state_is_refused(self) -> None:
        reduced = {
            name: clip for name, clip in self.section["animationMap"].items()
            if name != "error"
        }
        with self.assertRaisesRegex(CharacterSchemaError, "animationMap must define"):
            self._parse(animationMap=reduced)
        for state in MANDATORY_ANIMATION_STATES:
            self.assertIn(state, self.section["animationMap"])

    def test_an_unknown_animation_state_is_refused(self) -> None:
        extended = dict(self.section["animationMap"])
        extended["dance"] = "idle"
        with self.assertRaisesRegex(CharacterSchemaError, "unknown animation state"):
            self._parse(animationMap=extended)

    def test_an_expression_naming_an_undeclared_morph_is_refused(self) -> None:
        with self.assertRaisesRegex(CharacterSchemaError, "morphTargets does not declare"):
            self._parse(expressionMap={"happy": {"not_a_target": 1.0}})

    def test_a_weight_outside_zero_to_one_is_refused(self) -> None:
        target = self.section["morphTargets"][0]
        with self.assertRaisesRegex(CharacterSchemaError, "between 0.0 and 1.0"):
            self._parse(expressionMap={"happy": {target: 4.0}})

    def test_an_unknown_renderer_feature_is_refused(self) -> None:
        with self.assertRaisesRegex(CharacterSchemaError, "does not implement"):
            self._parse(requiredRendererFeatures=["ray-tracing"])
        for feature in self.section["requiredRendererFeatures"]:
            self.assertIn(feature, RENDERER_FEATURES)

    def test_a_state_without_an_accessibility_description_is_refused(self) -> None:
        reduced = {
            name: text for name, text in self.section["accessibilityStates"].items()
            if name != "idle"
        }
        with self.assertRaisesRegex(CharacterSchemaError, "accessibilityStates must describe"):
            self._parse(accessibilityStates=reduced)

    def test_a_declared_limit_cannot_exceed_the_build_ceiling(self) -> None:
        with self.assertRaisesRegex(CharacterSchemaError, "renderer ceiling"):
            self._parse(maximumTriangles=10_000_000)

    def test_inverted_model_bounds_are_refused(self) -> None:
        with self.assertRaisesRegex(CharacterSchemaError, "strictly below"):
            self._parse(modelBounds={"min": [1.0, 1.0, 1.0], "max": [0.0, 0.0, 0.0]})


class ManifestCrossCheckTests(unittest.TestCase):
    """The 3D section and the 2D body must agree, or the package is refused."""

    def setUp(self) -> None:
        source = _built_in_or_skip()
        self.temporary = tempfile.TemporaryDirectory(prefix="bunny-3d-package-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "package"
        shutil.copytree(source, self.root)
        self.manifest_path = self.root / "manifest.json"

    def _mutate(self, change) -> None:
        document = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        change(document)
        self.manifest_path.write_text(
            json.dumps(document, indent=2), encoding="utf-8", newline="\n"
        )

    def test_the_copy_still_validates(self) -> None:
        package = validate_package_directory(self.root)
        self.assertIsNotNone(package.model)

    def test_a_digest_that_disagrees_with_the_inventory_is_refused(self) -> None:
        self._mutate(lambda document: document["threeDimensional"].__setitem__("modelDigest", "b" * 64))
        with self.assertRaisesRegex(CharacterSchemaError, "disagrees with the asset inventory"):
            validate_package_directory(self.root)

    def test_a_model_file_not_in_the_inventory_is_refused(self) -> None:
        self._mutate(
            lambda document: document["threeDimensional"].__setitem__("modelFile", "assets/other.glb")
        )
        with self.assertRaisesRegex(CharacterSchemaError, "not in the asset inventory"):
            validate_package_directory(self.root)

    def test_an_animation_map_naming_a_missing_clip_is_refused(self) -> None:
        self._mutate(
            lambda document: document["threeDimensional"]["animationMap"].__setitem__("idle", "nope")
        )
        with self.assertRaisesRegex(CharacterIntegrityError, "clips the model does not carry"):
            validate_package_directory(self.root)

    def test_a_morph_target_the_model_lacks_is_refused(self) -> None:
        def change(document):
            document["threeDimensional"]["morphTargets"].append("phantom_target")

        self._mutate(change)
        with self.assertRaisesRegex(CharacterIntegrityError, "targets the model does not carry"):
            validate_package_directory(self.root)

    def test_a_gpu_declaration_smaller_than_the_model_is_refused(self) -> None:
        """The declaration becomes the validator's own limit, so it refuses first.

        A manifest may only make the validator stricter, and a package that
        declares less GPU memory than its model needs is refused *inside* the
        model validator rather than by a later cross-check. The distinction
        matters for the message a package author sees: they are told which
        limit their model exceeded, not that two numbers disagreed.
        """
        self._mutate(
            lambda document: document["threeDimensional"].__setitem__("declaredGpuBytes", 1024)
        )
        with self.assertRaisesRegex(CharacterSecurityError, "GPU memory"):
            validate_package_directory(self.root)

    def test_a_substituted_model_file_is_refused(self) -> None:
        """§28: the package is not what it was when its digest was recorded."""
        model = self.root / "assets" / "bunny-3d.glb"
        data = bytearray(model.read_bytes())
        data[-8] ^= 0xFF
        model.write_bytes(bytes(data))
        with self.assertRaises(CharacterIntegrityError):
            validate_package_directory(self.root)

    def test_a_3d_presentation_without_an_animated_2d_fallback_is_refused(self) -> None:
        def change(document):
            for animation in document["animations"].values():
                if animation["kind"] == "frame-sequence":
                    animation["kind"] = "static"
                    animation["frames"] = animation["frames"][:1]
                    animation["loop"] = False

        self._mutate(change)
        with self.assertRaisesRegex(CharacterSchemaError, "animated-2D fallback"):
            validate_package_directory(self.root)


class ImportTests(unittest.TestCase):
    """§27: the flow, and §25's no-bypass rule proved by a round trip."""

    def setUp(self) -> None:
        self.source = _built_in_or_skip()
        self.temporary = tempfile.TemporaryDirectory(prefix="bunny-3d-import-")
        self.addCleanup(self.temporary.cleanup)
        self.registry_root = Path(self.temporary.name) / "characters"
        self.registry = PackageRegistry(self.registry_root, built_in_paths=())
        self.importer = CharacterPackageImporter(self.registry)

    def test_the_built_in_package_imports_through_the_ordinary_path(self) -> None:
        record = self.importer.import_package(self.source)
        self.assertEqual(record.package_id, "bunny-default-3d")
        self.assertEqual(record.trust_state, PackageTrustState.VERIFIED_INTEGRITY)
        imported = validate_package_directory(
            record.path, trust_state=PackageTrustState.VERIFIED_INTEGRITY
        )
        built_in = validate_package_directory(
            self.source, trust_state=PackageTrustState.BUILT_IN
        )
        self.assertEqual(imported.package_digest, built_in.package_digest)
        self.assertEqual(imported.model.digest, built_in.model.digest)

    def test_a_zip_of_the_package_imports_identically(self) -> None:
        archive = Path(self.temporary.name) / "bunny-3d.zip"
        with zipfile.ZipFile(archive, "w") as handle:
            for path in sorted(self.source.rglob("*")):
                if path.is_file():
                    handle.write(path, path.relative_to(self.source).as_posix())
        record = self.importer.import_package(archive)
        imported = validate_package_directory(
            record.path, trust_state=PackageTrustState.VERIFIED_INTEGRITY
        )
        self.assertIsNotNone(imported.model)

    def test_a_package_with_a_broken_model_never_becomes_active(self) -> None:
        staged = Path(self.temporary.name) / "broken"
        shutil.copytree(self.source, staged)
        model = staged / "assets" / "bunny-3d.glb"
        data = bytearray(model.read_bytes())
        data[24] ^= 0xFF
        model.write_bytes(bytes(data))
        with self.assertRaises(CharacterError):
            self.importer.import_package(staged)
        self.assertEqual(self.registry.list(), ())
        installed = list((self.registry_root / "packages").rglob("manifest.json"))
        self.assertEqual(installed, [], "a refused package left content behind")

    def test_a_failed_import_leaves_the_previous_character_selected(self) -> None:
        record = self.importer.import_package(self.source)
        self.registry.select(record.package_id, package_digest=record.package_digest)
        before = self.registry.selected()
        staged = Path(self.temporary.name) / "broken-2"
        shutil.copytree(self.source, staged)
        (staged / "assets" / "bunny-3d.glb").write_bytes(b"not a glb at all")
        with self.assertRaises(CharacterError):
            self.importer.import_package(staged)
        self.assertEqual(self.registry.selected().package_digest, before.package_digest)

    def test_an_archive_that_escapes_its_root_is_refused(self) -> None:
        archive = Path(self.temporary.name) / "traversal.zip"
        with zipfile.ZipFile(archive, "w") as handle:
            handle.writestr("../escape.txt", "no")
        with self.assertRaises(CharacterSecurityError):
            self.importer.import_package(archive)


if __name__ == "__main__":
    unittest.main()
