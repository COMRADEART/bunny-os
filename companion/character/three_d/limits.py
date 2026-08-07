# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Every bound the GLB validator enforces, in one table.

Two properties are worth more than the numbers themselves.

**They are data, not conditionals.** :class:`ModelLimits` is a frozen dataclass
with a default instance, so a test can construct a stricter one and drive the
whole validator through it, and a capability configuration can lower a ceiling
without editing the validator. What it cannot do is *raise* one:
:meth:`ModelLimits.__post_init__` clamps every field against the hard ceiling
below. A configuration file that could widen a limit would be an attack surface
in the shape of a policy knob.

**They are declared before they are needed.** A limit checked only when a value
is used is a limit that a document can avoid by not reaching that code path. The
validator checks the *declared* count first — accessor counts, node counts,
animation counts, the byte length of every buffer view — and only then reads
anything, so a document that lies about its own size is refused before its lie
is allocated.

The numbers are sized for one desktop companion, not for a scene. A humanoid
that needs 300k triangles is not a desktop companion, it is a game asset that
would spend a laptop's battery drawing a person in the corner of a screen.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any

_MIB = 1024 * 1024

#: Hard ceilings. No configuration may exceed these; every field of
#: :class:`ModelLimits` is clamped to the matching entry.
HARD_CEILING: dict[str, int] = {
    "maximum_file_bytes": 96 * _MIB,
    "maximum_json_bytes": 8 * _MIB,
    "maximum_binary_bytes": 96 * _MIB,
    "maximum_vertices": 200_000,
    "maximum_triangles": 200_000,
    "maximum_nodes": 512,
    "maximum_node_depth": 32,
    "maximum_meshes": 32,
    "maximum_primitives": 64,
    "maximum_joints": 128,
    "maximum_skins": 4,
    "maximum_animations": 64,
    "maximum_animation_seconds": 60,
    "maximum_animation_channels": 1024,
    "maximum_animation_samplers": 1024,
    "maximum_keyframes": 200_000,
    "maximum_keyframes_per_sampler": 16_384,
    "maximum_morph_targets": 32,
    "maximum_textures": 16,
    "maximum_images": 16,
    "maximum_samplers": 16,
    "maximum_texture_dimension": 2048,
    "maximum_decoded_texture_bytes": 128 * _MIB,
    "maximum_materials": 32,
    "maximum_buffers": 4,
    "maximum_buffer_views": 512,
    "maximum_accessors": 512,
    "maximum_scenes": 4,
    "maximum_extension_names": 32,
    "maximum_name_length": 128,
    "maximum_gpu_bytes": 512 * _MIB,
}

#: The absolute value beyond which a transform component is refused. A scale of
#: 1e9 is not a character, and a translation of 1e30 puts a bone where a float
#: cannot represent the difference between it and the next one.
MAXIMUM_TRANSFORM_MAGNITUDE = 1.0e6

#: Uniform scale is additionally bounded, because a legitimate scale is a unit
#: choice (metres versus centimetres) and everything past that is a way to make
#: one triangle cover the screen.
MAXIMUM_SCALE = 1000.0
MINIMUM_SCALE = 1.0e-4

#: The model's own bounding box, in metres, after ``nativeScale``. A desktop
#: companion is a person-sized thing; 20 m is generous and 200 m is a bomb.
MAXIMUM_MODEL_EXTENT_METRES = 20.0

#: glTF extensions this validator understands. Everything else is refused when
#: required, and ignored-with-a-record when merely used — which is what the
#: specification asks for and is also the only safe reading, because an
#: extension the renderer does not implement changes what the file means.
#:
#: The set is deliberately empty of compression extensions.
#: ``KHR_draco_mesh_compression`` and ``KHR_texture_basisu`` are exactly the
#: "compression bomb" §6 names: a small file that expands into an unbounded one
#: inside a decoder this project does not own.
SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({
    "KHR_materials_unlit",
})

#: Extensions that are recognised by name so the refusal can say *why* rather
#: than "unknown extension", which is the difference between a package author
#: fixing their export and guessing at it.
KNOWN_REFUSED_EXTENSIONS: dict[str, str] = {
    "KHR_draco_mesh_compression": "Draco decompression is an unbounded decoder this build does not own",
    "KHR_texture_basisu": "Basis Universal transcoding is an unbounded decoder this build does not own",
    "EXT_meshopt_compression": "meshopt decompression is an unbounded decoder this build does not own",
    "KHR_materials_variants": "material variants let a package change its own appearance after validation",
    "KHR_animation_pointer": "animation pointers can target arbitrary document properties",
    "KHR_xmp_json_ld": "arbitrary linked-data metadata is not bounded by this contract",
    "EXT_mesh_gpu_instancing": "GPU instancing multiplies a validated vertex count after validation",
}

#: Accessor component types glTF defines, with their byte widths. A type absent
#: from this table is refused rather than guessed at.
COMPONENT_TYPES: dict[int, tuple[str, int]] = {
    5120: ("BYTE", 1),
    5121: ("UNSIGNED_BYTE", 1),
    5122: ("SHORT", 2),
    5123: ("UNSIGNED_SHORT", 2),
    5125: ("UNSIGNED_INT", 4),
    5126: ("FLOAT", 4),
}

#: Accessor element types, with their component counts.
ELEMENT_TYPES: dict[str, int] = {
    "SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4,
    "MAT2": 4, "MAT3": 9, "MAT4": 16,
}

#: The only primitive topology this renderer draws. Points and lines are not a
#: character, and strips and fans complicate index validation for no gain here.
SUPPORTED_PRIMITIVE_MODE = 4  # TRIANGLES

#: Vertex attributes the renderer consumes. An attribute outside this set is
#: recorded and dropped: it cannot reach a shader, so it cannot mean anything.
SUPPORTED_ATTRIBUTES: frozenset[str] = frozenset({
    "POSITION", "NORMAL", "TANGENT", "TEXCOORD_0", "COLOR_0", "JOINTS_0", "WEIGHTS_0",
})

#: Morph-target attributes. Positions are required of a target; normals are
#: optional and tangents are not implemented.
SUPPORTED_MORPH_ATTRIBUTES: frozenset[str] = frozenset({"POSITION", "NORMAL"})

#: Animation paths this renderer applies. ``weights`` drives morph targets.
SUPPORTED_ANIMATION_PATHS: frozenset[str] = frozenset({
    "translation", "rotation", "scale", "weights",
})

#: Animation interpolations. ``CUBICSPLINE`` is accepted structurally and
#: sampled as its own tangents describe; nothing is silently downgraded.
SUPPORTED_INTERPOLATIONS: frozenset[str] = frozenset({"LINEAR", "STEP", "CUBICSPLINE"})

#: Image media types. PNG only, and validated by the repository's own bounded
#: PNG reader before a pixel reaches a texture. JPEG would need a second decoder
#: with a second set of bombs.
SUPPORTED_IMAGE_MEDIA_TYPES: frozenset[str] = frozenset({"image/png"})


@dataclass(frozen=True)
class ModelLimits:
    """Bounds for one validation. Never exceeds :data:`HARD_CEILING`."""

    maximum_file_bytes: int = 32 * _MIB
    maximum_json_bytes: int = 4 * _MIB
    maximum_binary_bytes: int = 32 * _MIB
    maximum_vertices: int = 120_000
    maximum_triangles: int = 120_000
    maximum_nodes: int = 256
    maximum_node_depth: int = 24
    maximum_meshes: int = 16
    maximum_primitives: int = 32
    maximum_joints: int = 96
    maximum_skins: int = 2
    maximum_animations: int = 48
    maximum_animation_seconds: int = 30
    maximum_animation_channels: int = 512
    maximum_animation_samplers: int = 512
    maximum_keyframes: int = 120_000
    maximum_keyframes_per_sampler: int = 8_192
    maximum_morph_targets: int = 24
    maximum_textures: int = 8
    maximum_images: int = 8
    maximum_samplers: int = 8
    maximum_texture_dimension: int = 1024
    maximum_decoded_texture_bytes: int = 48 * _MIB
    maximum_materials: int = 16
    maximum_buffers: int = 1
    maximum_buffer_views: int = 256
    maximum_accessors: int = 256
    maximum_scenes: int = 1
    maximum_extension_names: int = 16
    maximum_name_length: int = 128
    maximum_gpu_bytes: int = 256 * _MIB

    def __post_init__(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"model limit {field.name} must be a positive integer")
            ceiling = HARD_CEILING[field.name]
            if value > ceiling:
                # Clamped rather than raised: a configuration that asks for more
                # than the build supports gets the build's answer, and the
                # caller is not offered a way to turn the ceiling off.
                object.__setattr__(self, field.name, ceiling)

    def to_json(self) -> dict[str, Any]:
        return {field.name: getattr(self, field.name) for field in fields(self)}


#: What an ordinary validation uses.
DEFAULT_LIMITS = ModelLimits()

__all__ = [
    "COMPONENT_TYPES",
    "DEFAULT_LIMITS",
    "ELEMENT_TYPES",
    "HARD_CEILING",
    "KNOWN_REFUSED_EXTENSIONS",
    "MAXIMUM_MODEL_EXTENT_METRES",
    "MAXIMUM_SCALE",
    "MAXIMUM_TRANSFORM_MAGNITUDE",
    "MINIMUM_SCALE",
    "ModelLimits",
    "SUPPORTED_ANIMATION_PATHS",
    "SUPPORTED_ATTRIBUTES",
    "SUPPORTED_EXTENSIONS",
    "SUPPORTED_IMAGE_MEDIA_TYPES",
    "SUPPORTED_INTERPOLATIONS",
    "SUPPORTED_MORPH_ATTRIBUTES",
    "SUPPORTED_PRIMITIVE_MODE",
]
