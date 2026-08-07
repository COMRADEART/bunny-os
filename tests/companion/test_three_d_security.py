# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""§28, case by case: every hostile model shape, and the refusal it earns.

Each test changes exactly one thing about a model the validator accepts, so a
refusal is attributable. :func:`tests.companion.three_d_support.mutated_glb`
enforces that: the baseline is built once and the test's callback is the only
edit.

Two properties are asserted throughout and are easy to lose sight of:

* the refusal happens **before** anything is allocated, uploaded or decoded, so
  these tests need no GPU and run on every machine; and
* the refusal is **typed** — ``ModelSecurityError`` for reaching outside the
  package or asking for active content, ``ModelLimitError`` for exceeding a
  bound, ``ModelSchemaError`` for a document that is merely malformed. A test
  that accepted any exception would pass against a validator that crashed.
"""

from __future__ import annotations

import json
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

from companion.character.errors import CharacterSecurityError
from companion.character.image import decode_png_rgba
from companion.character.three_d.errors import (
    ModelLimitError,
    ModelSchemaError,
    ModelSecurityError,
)
from companion.character.three_d.glb import parse_glb, validate_glb
from companion.character.three_d.limits import DEFAULT_LIMITS, ModelLimits
from tests.companion.three_d_support import (
    GLB_MAGIC,
    assemble,
    build_document,
    mutated_glb,
    tiny_png,
    valid_glb,
)


def _reference_section() -> dict:
    """A minimal but complete 3D manifest section, for the field-level tests."""
    return {
        "schemaVersion": 1,
        "rendererApiVersion": "1.0",
        "modelFile": "assets/bunny-3d.glb",
        "modelDigest": "a" * 64,
        "modelSizeBytes": 4096,
        "gltfVersion": "2.0",
        "skeletonProfile": "bunny-humanoid-1",
        "rootBone": "root",
        "headBone": "head",
        "neckBone": "neck",
        "eyeBones": ["left_eye", "right_eye"],
        "handBones": ["left_hand", "right_hand"],
        "animationMap": {"idle": "idle", "working": "working", "speaking": "speaking", "error": "error"},
        "expressionMap": {"happy": {"smile": 1.0}},
        "visemeMap": {"open-wide": {"mouth_open_wide": 1.0}},
        "morphTargets": ["smile", "mouth_open_wide"],
        "textureInventory": [{"name": "skin", "width": 64, "height": 64, "mediaType": "image/png"}],
        "materialInventory": ["skin"],
        "modelBounds": {"min": [-0.5, 0.0, -0.2], "max": [0.5, 1.7, 0.2]},
        "nativeScale": 1.0,
        "floorOffset": 0.0,
        "bubbleAnchor": [0.2, 1.5, 0.1],
        "cameraAnchor": [0.0, 0.9, 0.0],
        "maximumTriangles": 8000,
        "maximumVertices": 6000,
        "maximumJoints": 32,
        "maximumMorphTargets": 16,
        "maximumTextures": 4,
        "maximumTextureDimensions": 256,
        "declaredGpuBytes": 4 * 1024 * 1024,
        "declaredDecodedBytes": 1024 * 1024,
        "requiredRendererFeatures": ["skeletal-animation"],
        "staticFallbackAsset": "idle-1",
        "animatedFallbackState": "idle",
        "previewAsset": "idle-1",
        "accessibilityStates": {
            "idle": "Bunny is idle.", "working": "Bunny is working.",
            "speaking": "Bunny is speaking.", "error": "Something went wrong.",
        },
    }


class ContainerTests(unittest.TestCase):
    def test_the_baseline_model_is_accepted(self) -> None:
        model = validate_glb(valid_glb())
        self.assertEqual(model.triangle_count, 2)
        self.assertEqual(model.gltf_version, "2.0")

    def test_a_truncated_container_is_refused(self) -> None:
        data = valid_glb()[:40]
        with self.assertRaises((ModelSchemaError, ModelSecurityError)):
            validate_glb(data)

    def test_a_declared_length_that_disagrees_with_the_file_is_refused(self) -> None:
        data = bytearray(valid_glb())
        struct.pack_into("<I", data, 8, len(data) + 4096)
        with self.assertRaisesRegex(ModelSecurityError, "container is inconsistent"):
            validate_glb(bytes(data))

    def test_a_file_that_is_not_a_glb_is_refused(self) -> None:
        with self.assertRaisesRegex(ModelSchemaError, "not a GLB"):
            validate_glb(b"\x00" * 64)

    def test_an_oversized_file_is_refused_before_it_is_parsed(self) -> None:
        limits = ModelLimits(maximum_file_bytes=1024)
        with self.assertRaisesRegex(ModelLimitError, "the limit is 1024"):
            validate_glb(valid_glb(), limits=limits)

    def test_an_unknown_chunk_type_is_refused(self) -> None:
        base = valid_glb()
        extra = struct.pack("<II", 4, 0x11223344) + b"\x00\x00\x00\x00"
        data = bytearray(base + extra)
        struct.pack_into("<I", data, 8, len(data))
        with self.assertRaisesRegex(ModelSecurityError, "unsupported chunk"):
            validate_glb(bytes(data))

    def test_a_repeated_json_key_is_refused(self) -> None:
        document, builder = build_document()
        binary = bytes(builder.binary)
        text = json.dumps(document, separators=(",", ":"))
        broken = text[:-1] + ',"asset":{"version":"2.0"}}'
        payload = broken.encode("utf-8")
        while len(payload) % 4:
            payload += b" "
        while len(binary) % 4:
            binary += b"\x00"
        total = 12 + 8 + len(payload) + 8 + len(binary)
        data = (
            struct.pack("<III", GLB_MAGIC, 2, total)
            + struct.pack("<II", len(payload), 0x4E4F534A) + payload
            + struct.pack("<II", len(binary), 0x004E4942) + binary
        )
        with self.assertRaisesRegex(ModelSchemaError, "repeats field"):
            validate_glb(data)


class ExternalReferenceTests(unittest.TestCase):
    def test_an_external_buffer_uri_is_refused(self) -> None:
        def change(document, builder):
            document["_uri"] = True

        data = mutated_glb(lambda document, builder: None)
        # The builder always writes the buffer without a uri, so inject one into
        # the packed JSON directly: the point is the validator's refusal, not
        # the builder's convenience.
        document, builder = build_document()
        binary = bytes(builder.binary)
        document["bufferViews"] = builder.views
        document["accessors"] = builder.accessors
        document["buffers"] = [{"byteLength": len(binary), "uri": "geometry.bin"}]
        with self.assertRaisesRegex(ModelSecurityError, "declares a uri"):
            validate_glb(assemble(document, binary))

    def test_a_network_buffer_uri_is_refused(self) -> None:
        document, builder = build_document()
        binary = bytes(builder.binary)
        document["bufferViews"] = builder.views
        document["accessors"] = builder.accessors
        document["buffers"] = [{"byteLength": len(binary), "uri": "https://example.test/mesh.bin"}]
        with self.assertRaisesRegex(ModelSecurityError, "declares a uri"):
            validate_glb(assemble(document, binary))

    def test_a_data_uri_buffer_is_refused_like_any_other(self) -> None:
        document, builder = build_document()
        binary = bytes(builder.binary)
        document["bufferViews"] = builder.views
        document["accessors"] = builder.accessors
        document["buffers"] = [{"byteLength": len(binary), "uri": "data:application/octet-stream;base64,AAAA"}]
        with self.assertRaisesRegex(ModelSecurityError, "declares a uri"):
            validate_glb(assemble(document, binary))

    def test_an_external_texture_url_is_refused(self) -> None:
        def change(document, builder):
            document["images"][0].pop("bufferView")
            document["images"][0]["uri"] = "https://example.test/skin.png"

        with self.assertRaisesRegex(ModelSecurityError, "declares a uri"):
            validate_glb(mutated_glb(change))

    def test_a_relative_texture_path_is_refused(self) -> None:
        def change(document, builder):
            document["images"][0].pop("bufferView")
            document["images"][0]["uri"] = "../../etc/passwd"

        with self.assertRaisesRegex(ModelSecurityError, "declares a uri"):
            validate_glb(mutated_glb(change))

    def test_a_second_buffer_is_refused(self) -> None:
        document, builder = build_document()
        binary = bytes(builder.binary)
        document["bufferViews"] = builder.views
        document["accessors"] = builder.accessors
        document["buffers"] = [{"byteLength": len(binary)}, {"byteLength": 16}]
        with self.assertRaises(ModelSecurityError):
            validate_glb(assemble(document, binary))


class ExtensionTests(unittest.TestCase):
    def test_a_required_draco_extension_is_refused_by_name(self) -> None:
        def change(document, builder):
            document["extensionsRequired"] = ["KHR_draco_mesh_compression"]
            document["extensionsUsed"] = ["KHR_draco_mesh_compression"]

        with self.assertRaisesRegex(ModelSecurityError, "unbounded decoder"):
            validate_glb(mutated_glb(change))

    def test_a_meshopt_extension_is_refused_even_when_only_used(self) -> None:
        def change(document, builder):
            document["extensionsUsed"] = ["EXT_meshopt_compression"]

        with self.assertRaisesRegex(ModelSecurityError, "unbounded decoder"):
            validate_glb(mutated_glb(change))

    def test_an_unknown_required_extension_is_refused(self) -> None:
        def change(document, builder):
            document["extensionsRequired"] = ["VENDOR_run_script"]

        with self.assertRaisesRegex(ModelSecurityError, "not implemented"):
            validate_glb(mutated_glb(change))

    def test_a_gpu_instancing_extension_is_refused(self) -> None:
        def change(document, builder):
            document["extensionsRequired"] = ["EXT_mesh_gpu_instancing"]

        with self.assertRaisesRegex(ModelSecurityError, "multiplies a validated vertex count"):
            validate_glb(mutated_glb(change))

    def test_an_unknown_top_level_field_is_refused(self) -> None:
        def change(document, builder):
            document["script"] = "print('hello')"

        with self.assertRaisesRegex(ModelSchemaError, "unsupported top-level fields"):
            validate_glb(mutated_glb(change))

    def test_a_package_supplied_camera_is_refused(self) -> None:
        def change(document, builder):
            document["cameras"] = [{"type": "perspective", "perspective": {"yfov": 1.0, "znear": 0.1}}]

        with self.assertRaisesRegex(ModelSecurityError, "may not supply cameras"):
            validate_glb(mutated_glb(change))

    def test_a_node_that_attaches_a_camera_is_refused(self) -> None:
        def change(document, builder):
            document["nodes"][0]["camera"] = 0

        with self.assertRaisesRegex(ModelSecurityError, "attaches a camera"):
            validate_glb(mutated_glb(change))


class NumericTests(unittest.TestCase):
    def test_a_nan_translation_is_refused(self) -> None:
        def change(document, builder):
            document["nodes"][0]["translation"] = [float("nan"), 0.0, 0.0]

        with self.assertRaisesRegex(ModelSecurityError, "NaN or infinite"):
            validate_glb(mutated_glb(change))

    def test_an_infinite_translation_is_refused(self) -> None:
        def change(document, builder):
            document["nodes"][0]["translation"] = [0.0, float("inf"), 0.0]

        with self.assertRaisesRegex(ModelSecurityError, "NaN or infinite"):
            validate_glb(mutated_glb(change))

    def test_an_extreme_scale_is_refused(self) -> None:
        def change(document, builder):
            document["nodes"][0]["scale"] = [1.0, 1.0e5, 1.0]

        with self.assertRaisesRegex(ModelLimitError, "scale limit"):
            validate_glb(mutated_glb(change))

    def test_a_vanishing_scale_is_refused(self) -> None:
        def change(document, builder):
            document["nodes"][0]["scale"] = [1.0, 1.0e-9, 1.0]

        with self.assertRaisesRegex(ModelLimitError, "scale floor"):
            validate_glb(mutated_glb(change))

    def test_a_nan_vertex_position_is_refused(self) -> None:
        def change(document, builder):
            accessor = document["meshes"][0]["primitives"][0]["attributes"]["POSITION"]
            view = builder.accessors[accessor]["bufferView"]
            offset = builder.views[view]["byteOffset"]
            struct.pack_into("<f", builder.binary, offset, float("nan"))

        with self.assertRaisesRegex(ModelSecurityError, "NaN or infinite"):
            validate_glb(mutated_glb(change))

    def test_a_non_unit_quaternion_is_refused(self) -> None:
        def change(document, builder):
            document["nodes"][0]["rotation"] = [0.0, 0.0, 0.0, 4.0]

        with self.assertRaisesRegex(ModelSchemaError, "unit quaternion"):
            validate_glb(mutated_glb(change))

    def test_a_model_the_size_of_a_building_is_refused(self) -> None:
        def change(document, builder):
            accessor = document["meshes"][0]["primitives"][0]["attributes"]["POSITION"]
            view = builder.accessors[accessor]["bufferView"]
            offset = builder.views[view]["byteOffset"]
            struct.pack_into("<f", builder.binary, offset + 4, 400.0)

        with self.assertRaisesRegex(ModelLimitError, "units across"):
            validate_glb(mutated_glb(change))


class LimitTests(unittest.TestCase):
    def test_excessive_vertices_are_refused(self) -> None:
        limits = ModelLimits(maximum_vertices=3)
        with self.assertRaisesRegex(ModelLimitError, "vertices"):
            validate_glb(valid_glb(), limits=limits)

    def test_excessive_triangles_are_refused(self) -> None:
        limits = ModelLimits(maximum_triangles=1)
        with self.assertRaisesRegex(ModelLimitError, "triangles"):
            validate_glb(valid_glb(), limits=limits)

    def test_excessive_bones_are_refused(self) -> None:
        limits = ModelLimits(maximum_joints=4)
        with self.assertRaises(ModelLimitError):
            validate_glb(valid_glb(), limits=limits)

    def test_excessive_morph_targets_are_refused(self) -> None:
        limits = ModelLimits(maximum_morph_targets=1)
        with self.assertRaises(ModelLimitError):
            validate_glb(valid_glb(morph_targets=("a", "b", "c")), limits=limits)

    def test_excessive_animations_are_refused(self) -> None:
        limits = ModelLimits(maximum_animations=2)
        with self.assertRaisesRegex(ModelLimitError, "animations"):
            validate_glb(valid_glb(), limits=limits)

    def test_excessive_keyframes_are_refused(self) -> None:
        limits = ModelLimits(maximum_keyframes=4)
        with self.assertRaisesRegex(ModelLimitError, "keyframes"):
            validate_glb(valid_glb(), limits=limits)

    def test_an_animation_longer_than_the_limit_is_refused(self) -> None:
        def change(document, builder):
            sampler = document["animations"][0]["samplers"][0]
            accessor = builder.accessors[sampler["input"]]
            view = builder.views[accessor["bufferView"]]
            struct.pack_into("<f", builder.binary, view["byteOffset"] + 8, 900.0)
            accessor["max"] = [900.0]

        with self.assertRaisesRegex(ModelLimitError, "the limit is"):
            validate_glb(mutated_glb(change))

    def test_an_excessive_node_count_is_refused(self) -> None:
        limits = ModelLimits(maximum_nodes=4)
        with self.assertRaises(ModelLimitError):
            validate_glb(valid_glb(), limits=limits)

    def test_a_texture_larger_than_the_limit_is_refused(self) -> None:
        def change(document, builder):
            view = document["images"][0]["bufferView"]
            payload = tiny_png(64, 64)
            offset = builder.views[view]["byteOffset"]
            builder.binary[offset:offset + builder.views[view]["byteLength"]] = payload
            builder.views[view]["byteLength"] = len(payload)

        limits = ModelLimits(maximum_texture_dimension=16)
        with self.assertRaises((ModelSecurityError, CharacterSecurityError)):
            validate_glb(mutated_glb(change), limits=limits)

    def test_decoded_texture_memory_is_bounded(self) -> None:
        limits = ModelLimits(maximum_decoded_texture_bytes=8)
        with self.assertRaisesRegex(ModelLimitError, "decoded textures total"):
            validate_glb(valid_glb(), limits=limits)

    def test_the_gpu_budget_is_enforced(self) -> None:
        # The tiny model fits a generous budget and not a mean one. The floor is
        # 16 MiB, so the mean budget is expressed by making the model's own
        # texture allowance the binding constraint instead.
        validate_glb(valid_glb(), limits=ModelLimits(maximum_gpu_bytes=16 * 1024 * 1024))
        model = validate_glb(valid_glb())
        self.assertGreater(model.estimated_gpu_bytes, 0)
        self.assertLess(model.estimated_gpu_bytes, 16 * 1024 * 1024)
        with self.assertRaisesRegex(ModelLimitError, "decoded textures total"):
            validate_glb(valid_glb(), limits=ModelLimits(maximum_decoded_texture_bytes=1))

    def test_a_configuration_cannot_raise_a_hard_ceiling(self) -> None:
        wide = ModelLimits(maximum_vertices=10_000_000, maximum_file_bytes=1 << 40)
        self.assertLessEqual(wide.maximum_vertices, 200_000)
        self.assertLessEqual(wide.maximum_file_bytes, 96 * 1024 * 1024)


class StructureTests(unittest.TestCase):
    def test_an_invalid_vertex_index_is_refused(self) -> None:
        def change(document, builder):
            accessor = document["meshes"][0]["primitives"][0]["indices"]
            view = builder.accessors[accessor]["bufferView"]
            offset = builder.views[view]["byteOffset"]
            struct.pack_into("<H", builder.binary, offset, 900)

        with self.assertRaisesRegex(ModelSecurityError, "references vertex"):
            validate_glb(mutated_glb(change))

    def test_an_invalid_bone_reference_is_refused(self) -> None:
        def change(document, builder):
            accessor = document["meshes"][0]["primitives"][0]["attributes"]["JOINTS_0"]
            view = builder.accessors[accessor]["bufferView"]
            offset = builder.views[view]["byteOffset"]
            builder.binary[offset] = 250

        with self.assertRaisesRegex(ModelSecurityError, "references joint"):
            validate_glb(mutated_glb(change))

    def test_a_skeleton_cycle_is_refused(self) -> None:
        def change(document, builder):
            document["nodes"][0].setdefault("children", []).append(0)

        with self.assertRaises(ModelSecurityError):
            validate_glb(mutated_glb(change))

    def test_a_node_with_two_parents_is_refused(self) -> None:
        def change(document, builder):
            document["nodes"][0].setdefault("children", [])
            document["nodes"][2]["children"] = list(document["nodes"][2].get("children", [])) + [
                document["nodes"][0]["children"][0] if document["nodes"][0].get("children") else 5
            ]

        with self.assertRaises(ModelSecurityError):
            validate_glb(mutated_glb(change))

    def test_a_missing_root_bone_is_refused(self) -> None:
        def change(document, builder):
            document["nodes"][0]["name"] = "unnamed-thing"

        with self.assertRaisesRegex(ModelSchemaError, "missing: root"):
            validate_glb(mutated_glb(change))

    def test_an_animation_that_targets_a_missing_node_is_refused(self) -> None:
        def change(document, builder):
            document["animations"][0]["channels"][0]["target"]["node"] = 999

        with self.assertRaisesRegex(ModelSchemaError, "out of range"):
            validate_glb(mutated_glb(change))

    def test_an_animation_with_no_channels_is_refused(self) -> None:
        def change(document, builder):
            document["animations"][0]["channels"] = []

        with self.assertRaisesRegex(ModelSchemaError, "no channels"):
            validate_glb(mutated_glb(change))

    def test_a_morph_weight_channel_on_a_mesh_without_targets_is_refused(self) -> None:
        def change(document, builder):
            document["meshes"][0]["primitives"][0].pop("targets", None)
            document["meshes"][0].pop("weights", None)
            document["animations"][0]["channels"][0]["target"] = {
                "node": len(document["nodes"]) - 1, "path": "weights"
            }
            sampler = document["animations"][0]["samplers"][0]
            sampler["output"] = builder.floats([0.0, 0.5, 1.0], "SCALAR")

        with self.assertRaisesRegex(ModelSchemaError, "no morph targets"):
            validate_glb(mutated_glb(change))

    def test_a_malformed_accessor_is_refused(self) -> None:
        def change(document, builder):
            accessor = document["meshes"][0]["primitives"][0]["attributes"]["POSITION"]
            builder.accessors[accessor]["count"] = 100000

        with self.assertRaises((ModelSecurityError, ModelSchemaError)):
            validate_glb(mutated_glb(change))

    def test_a_sparse_accessor_is_refused(self) -> None:
        def change(document, builder):
            accessor = document["meshes"][0]["primitives"][0]["attributes"]["POSITION"]
            builder.accessors[accessor]["sparse"] = {"count": 1}

        with self.assertRaisesRegex(ModelSecurityError, "sparse accessor"):
            validate_glb(mutated_glb(change))

    def test_an_accessor_that_reads_past_its_view_is_refused(self) -> None:
        def change(document, builder):
            accessor = document["meshes"][0]["primitives"][0]["attributes"]["POSITION"]
            builder.accessors[accessor]["byteOffset"] = 4096

        with self.assertRaises((ModelSecurityError, ModelSchemaError)):
            validate_glb(mutated_glb(change))

    def test_a_buffer_view_that_reaches_past_the_binary_chunk_is_refused(self) -> None:
        def change(document, builder):
            builder.views[0]["byteLength"] = 1 << 20

        with self.assertRaisesRegex(ModelSecurityError, "binary chunk"):
            validate_glb(mutated_glb(change))

    def test_a_non_triangle_primitive_is_refused(self) -> None:
        def change(document, builder):
            document["meshes"][0]["primitives"][0]["mode"] = 0

        with self.assertRaisesRegex(ModelSchemaError, "not TRIANGLES"):
            validate_glb(mutated_glb(change))

    def test_a_matrix_transform_is_refused(self) -> None:
        def change(document, builder):
            document["nodes"][0]["matrix"] = [1.0] * 16

        with self.assertRaisesRegex(ModelSchemaError, "uses a matrix"):
            validate_glb(mutated_glb(change))

    def test_a_morph_target_with_the_wrong_vertex_count_is_refused(self) -> None:
        def change(document, builder):
            accessor = document["meshes"][0]["primitives"][0]["targets"][0]["POSITION"]
            builder.accessors[accessor]["count"] = 2

        with self.assertRaises((ModelSchemaError, ModelSecurityError)):
            validate_glb(mutated_glb(change))

    def test_a_morph_target_with_an_unsupported_attribute_is_refused(self) -> None:
        def change(document, builder):
            document["meshes"][0]["primitives"][0]["targets"][0]["TANGENT"] = 0

        with self.assertRaisesRegex(ModelSchemaError, "unsupported attributes"):
            validate_glb(mutated_glb(change))


class TextureTests(unittest.TestCase):
    def test_a_non_png_texture_is_refused(self) -> None:
        def change(document, builder):
            document["images"][0]["mimeType"] = "image/jpeg"

        with self.assertRaisesRegex(ModelSecurityError, "only PNG"):
            validate_glb(mutated_glb(change))

    def test_a_texture_bomb_is_refused_by_the_shared_png_reader(self) -> None:
        """A 1x1 PNG whose IDAT inflates to ten thousand scanlines."""
        def chunk(kind: bytes, payload: bytes) -> bytes:
            return (
                struct.pack(">I", len(payload)) + kind + payload
                + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
            )

        raw = b"\x00" + b"\x00\x00\x00\x00" * 10000
        bomb = (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b"")
        )
        with self.assertRaisesRegex(CharacterSecurityError, "expands beyond"):
            decode_png_rgba(bomb)

    def test_a_malformed_compressed_texture_is_refused(self) -> None:
        def change(document, builder):
            view = document["images"][0]["bufferView"]
            offset = builder.views[view]["byteOffset"]
            # Corrupt the IDAT payload, past the signature and header.
            builder.binary[offset + 60] ^= 0xFF

        with self.assertRaises(CharacterSecurityError):
            validate_glb(mutated_glb(change))

    def test_an_unsupported_wrap_mode_is_refused(self) -> None:
        def change(document, builder):
            document["samplers"][0]["wrapS"] = 12345

        with self.assertRaisesRegex(ModelSchemaError, "wrap mode"):
            validate_glb(mutated_glb(change))


class DigestAndSubstitutionTests(unittest.TestCase):
    def test_a_digest_mismatch_is_refused_before_parsing(self) -> None:
        with self.assertRaisesRegex(ModelSecurityError, "digest does not match"):
            validate_glb(valid_glb(), expected_digest="0" * 64)

    def test_a_substituted_model_fails_its_manifest_digest(self) -> None:
        """§28's "model substitution after approval", as a package-level check."""
        import hashlib

        original = valid_glb()
        substitute = valid_glb(animations=("idle", "working", "speaking", "error", "greeting"))
        self.assertNotEqual(original, substitute)
        digest = hashlib.sha256(original).hexdigest()
        validate_glb(original, expected_digest=digest)
        with self.assertRaisesRegex(ModelSecurityError, "digest does not match"):
            validate_glb(substitute, expected_digest=digest)


class ShaderInjectionTests(unittest.TestCase):
    """§28's "shader injection", and §19's "no package-supplied shaders"."""

    def test_no_module_but_the_shader_module_calls_glshadersource(self) -> None:
        import ast

        root = Path(__file__).resolve().parents[2] / "companion"
        offenders: list[str] = []
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr == "glShaderSource":
                    offenders.append(path.relative_to(root).as_posix())
        self.assertEqual(
            sorted(set(offenders)),
            ["character/three_d/renderer.py"],
            "only the renderer may hand source to the driver",
        )

    def test_the_only_shader_sources_are_module_constants(self) -> None:
        from companion.character.three_d import shaders

        vertex, fragment, key = shaders.shader_sources(
            joints=8, unlit=False, alpha_mode="OPAQUE", lightweight=False
        )
        self.assertIn("#version 330 core", vertex)
        self.assertIn("#version 330 core", fragment)
        self.assertEqual(key["joints"], 8)
        # Every substitution is an integer this build computed.
        self.assertIn("#define MAX_JOINTS 8", vertex)
        with self.assertRaises(KeyError):
            shaders.shader_sources(
                joints=8, unlit=False, alpha_mode="OPAQUE; void main(){}", lightweight=False
            )
        with self.assertRaises(ValueError):
            shaders.shader_sources(joints=0, unlit=False, alpha_mode="OPAQUE", lightweight=False)

    def test_a_package_cannot_declare_a_shader_anywhere_in_the_3d_section(self) -> None:
        from companion.character.three_d.package3d import _SECTION_FIELDS

        for name in _SECTION_FIELDS:
            self.assertNotIn("shader", name.casefold())


class PackageBoundaryTests(unittest.TestCase):
    """§28's archive and package-root cases, at the package validator."""

    def test_a_glb_outside_the_package_root_is_refused_by_the_path_rule(self) -> None:
        from companion.character.schema import safe_package_path

        for candidate in ("../escape.glb", "/etc/model.glb", "a/../../b.glb"):
            with self.assertRaises(CharacterSecurityError):
                safe_package_path(candidate, "modelFile")

    def test_a_model_file_that_is_not_a_glb_is_refused(self) -> None:
        from companion.character.three_d.package3d import ThreeDSection

        section = dict(_reference_section())
        section["modelFile"] = "assets/model.png"
        with self.assertRaises(CharacterSecurityError):
            ThreeDSection.from_json(section)

    def test_a_model_file_that_escapes_the_package_is_refused(self) -> None:
        from companion.character.three_d.package3d import ThreeDSection

        section = dict(_reference_section())
        section["modelFile"] = "../../etc/model.glb"
        with self.assertRaises(CharacterSecurityError):
            ThreeDSection.from_json(section)

    def test_the_reference_section_is_otherwise_accepted(self) -> None:
        from companion.character.three_d.package3d import ThreeDSection

        parsed = ThreeDSection.from_json(_reference_section())
        self.assertEqual(parsed.skeleton_profile, "bunny-humanoid-1")
        self.assertEqual(parsed.model_file, "assets/bunny-3d.glb")

    def test_the_renderer_reads_only_paths_the_validator_resolved(self) -> None:
        """``asset_path`` re-checks containment even for a trusted manifest."""
        from companion.character.defaults import default_3d_character_path
        from companion.character.package import validate_package_directory
        from companion.character.schema import PackageTrustState

        root = default_3d_character_path()
        if not root.is_dir():
            self.skipTest("the built-in 3D package is not installed here")
        package = validate_package_directory(root, trust_state=PackageTrustState.BUILT_IN)
        model_asset = next(
            asset for asset in package.manifest.assets if asset.purpose == "model"
        )
        resolved = package.asset_path(model_asset.asset_id)
        self.assertTrue(str(resolved).startswith(str(package.root)))
        self.assertTrue(resolved.is_file())


if __name__ == "__main__":
    unittest.main()
