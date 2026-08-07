# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""A GLB the tests can bend: valid by default, invalid on request.

Every §28 case is "a good model with one thing wrong", and writing eighteen
almost-identical GLBs by hand is how one of them ends up wrong in two ways and
passes its test for the wrong reason. So there is one builder here, it produces
a model the validator accepts, and each test names the single change it makes.

The builder is deliberately *not* the shipped generator. The shipped character
is a 300 KB figure with 2452 triangles and 22 clips; a security test that had to
parse it to change one accessor would be slow and would couple every refusal to
the art. This one is a two-triangle mesh with a three-bone skeleton — the
smallest thing that is still a skinned, animated, morphed humanoid-profile
model, so the checks it exercises are the real ones.
"""

from __future__ import annotations

import json
import struct
from typing import Any, Callable, Iterable, Mapping, Sequence
import zlib

from companion.character.three_d.skeleton import REQUIRED_BONES

GLB_MAGIC = 0x46546C67
CHUNK_JSON = 0x4E4F534A
CHUNK_BIN = 0x004E4942


def tiny_png(width: int = 4, height: int = 4, colour: tuple[int, int, int, int] = (200, 180, 160, 255)) -> bytes:
    raw = bytearray()
    for _ in range(height):
        raw.append(0)
        for _ in range(width):
            raw.extend(colour)

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload)) + kind + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + chunk(b"IEND", b"")
    )


class GlbBuilder:
    """Assemble a GLB from a JSON document and a binary chunk."""

    def __init__(self) -> None:
        self.binary = bytearray()
        self.views: list[dict[str, Any]] = []
        self.accessors: list[dict[str, Any]] = []

    def view(self, payload: bytes) -> int:
        while len(self.binary) % 4:
            self.binary.append(0)
        offset = len(self.binary)
        self.binary.extend(payload)
        self.views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(payload)})
        return len(self.views) - 1

    def accessor(
        self, payload: bytes, *, component_type: int, element_type: str, count: int,
        minimum: Sequence[float] | None = None, maximum: Sequence[float] | None = None,
    ) -> int:
        view = self.view(payload)
        entry: dict[str, Any] = {
            "bufferView": view, "componentType": component_type,
            "count": count, "type": element_type,
        }
        if minimum is not None:
            entry["min"] = list(minimum)
        if maximum is not None:
            entry["max"] = list(maximum)
        self.accessors.append(entry)
        return len(self.accessors) - 1

    def floats(self, values: Sequence[float], element_type: str, *, bounds: bool = False) -> int:
        components = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}[element_type]
        count = len(values) // components
        minimum = maximum = None
        if bounds:
            minimum = [min(values[index::components]) for index in range(components)]
            maximum = [max(values[index::components]) for index in range(components)]
        return self.accessor(
            struct.pack(f"<{len(values)}f", *values), component_type=5126,
            element_type=element_type, count=count, minimum=minimum, maximum=maximum,
        )

    def pack(self, document: Mapping[str, Any]) -> bytes:
        binary = bytes(self.binary)
        while len(binary) % 4:
            binary += b"\x00"
        payload = dict(document)
        payload.setdefault("bufferViews", self.views)
        payload.setdefault("accessors", self.accessors)
        payload["buffers"] = [{"byteLength": len(binary)}]
        return assemble(payload, binary)


def assemble(document: Mapping[str, Any], binary: bytes) -> bytes:
    """Wrap a document and a binary chunk into a well-formed GLB container."""
    json_bytes = json.dumps(document, separators=(",", ":")).encode("utf-8")
    while len(json_bytes) % 4:
        json_bytes += b" "
    binary = bytes(binary)
    while len(binary) % 4:
        binary += b"\x00"
    total = 12 + 8 + len(json_bytes) + (8 + len(binary) if binary else 0)
    output = struct.pack("<III", GLB_MAGIC, 2, total)
    output += struct.pack("<II", len(json_bytes), CHUNK_JSON) + json_bytes
    if binary:
        output += struct.pack("<II", len(binary), CHUNK_BIN) + binary
    return output


#: The three-joint chain the test model uses beyond the required profile names.
_EXTRA_BONES = ("jaw", "left_eye", "right_eye")


def build_document(
    *,
    joints: Sequence[str] = REQUIRED_BONES + _EXTRA_BONES,
    morph_targets: Sequence[str] = ("mouth_open_medium", "smile"),
    animations: Sequence[str] = ("idle", "working", "speaking", "error"),
    with_texture: bool = True,
) -> tuple[dict[str, Any], GlbBuilder]:
    """A valid document plus the builder that produced it, ready to be edited."""
    builder = GlbBuilder()
    positions = [
        0.0, 0.0, 0.0,
        0.10, 0.0, 0.0,
        0.05, 1.60, 0.0,
        0.0, 0.80, 0.02,
    ]
    normals = [0.0, 0.0, 1.0] * 4
    uvs = [0.0, 0.0, 1.0, 0.0, 0.5, 1.0, 0.5, 0.5]
    weights = [1.0, 0.0, 0.0, 0.0] * 4
    joint_indices = bytes([0, 0, 0, 0, 1, 0, 0, 0, 5, 0, 0, 0, 2, 0, 0, 0])
    indices = struct.pack("<6H", 0, 1, 2, 0, 2, 3)

    position_accessor = builder.floats(positions, "VEC3", bounds=True)
    normal_accessor = builder.floats(normals, "VEC3")
    uv_accessor = builder.floats(uvs, "VEC2")
    weight_accessor = builder.floats(weights, "VEC4")
    joints_accessor = builder.accessor(
        joint_indices, component_type=5121, element_type="VEC4", count=4
    )
    index_accessor = builder.accessor(
        indices, component_type=5123, element_type="SCALAR", count=6
    )

    targets: list[dict[str, int]] = []
    for index in range(len(morph_targets)):
        deltas = [0.0, 0.004 * (index + 1), 0.0] * 4
        targets.append({"POSITION": builder.floats(deltas, "VEC3", bounds=True)})

    inverse_bind: list[float] = []
    for order, _name in enumerate(joints):
        inverse_bind.extend([
            1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0,
            0.0, -0.05 * order, 0.0, 1.0,
        ])
    ibm_accessor = builder.floats(inverse_bind, "MAT4")

    parents = {
        "hips": "root", "spine": "hips", "chest": "spine", "neck": "chest", "head": "neck",
        "jaw": "head", "left_eye": "head", "right_eye": "head",
        "left_upper_arm": "chest", "left_lower_arm": "left_upper_arm", "left_hand": "left_lower_arm",
        "right_upper_arm": "chest", "right_lower_arm": "right_upper_arm", "right_hand": "right_lower_arm",
        "left_upper_leg": "hips", "left_lower_leg": "left_upper_leg", "left_foot": "left_lower_leg",
        "right_upper_leg": "hips", "right_lower_leg": "right_upper_leg", "right_foot": "right_lower_leg",
    }
    order = {name: index for index, name in enumerate(joints)}
    nodes: list[dict[str, Any]] = []
    for name in joints:
        node: dict[str, Any] = {"name": name, "translation": [0.0, 0.05, 0.0]}
        children = [order[child] for child in joints if parents.get(child) == name]
        if children:
            node["children"] = children
        nodes.append(node)
    mesh_node = len(nodes)
    nodes.append({
        "name": "Body", "mesh": 0, "skin": 0, "weights": [0.0] * len(morph_targets),
    })

    primitive: dict[str, Any] = {
        "attributes": {
            "POSITION": position_accessor, "NORMAL": normal_accessor,
            "TEXCOORD_0": uv_accessor, "JOINTS_0": joints_accessor,
            "WEIGHTS_0": weight_accessor,
        },
        "indices": index_accessor,
        "material": 0,
        "mode": 4,
    }
    if targets:
        primitive["targets"] = targets

    animation_entries: list[dict[str, Any]] = []
    for name in animations:
        times = builder.floats([0.0, 0.5, 1.0], "SCALAR", bounds=True)
        rotations = builder.floats(
            [0.0, 0.0, 0.0, 1.0, 0.0, 0.05, 0.0, 0.9987, 0.0, 0.0, 0.0, 1.0], "VEC4"
        )
        animation_entries.append({
            "name": name,
            "samplers": [{"input": times, "output": rotations, "interpolation": "LINEAR"}],
            "channels": [{"sampler": 0, "target": {"node": order["chest"], "path": "rotation"}}],
        })

    document: dict[str, Any] = {
        "asset": {"version": "2.0", "generator": "bunny-os test builder"},
        "scene": 0,
        "scenes": [{"nodes": [0, mesh_node]}],
        "nodes": nodes,
        "meshes": [{
            "name": "Body",
            "primitives": [primitive],
            "weights": [0.0] * len(morph_targets),
            "extras": {"targetNames": list(morph_targets)},
        }],
        "skins": [{
            "inverseBindMatrices": ibm_accessor,
            "joints": list(range(len(joints))),
            "skeleton": 0,
        }],
        "animations": animation_entries,
        "materials": [{
            "name": "test-skin",
            "pbrMetallicRoughness": {
                "baseColorFactor": [0.8, 0.7, 0.6, 1.0],
                "metallicFactor": 0.0,
                "roughnessFactor": 0.8,
            },
        }],
    }
    if with_texture:
        image_view = builder.view(tiny_png())
        document["images"] = [{"name": "skin", "mimeType": "image/png", "bufferView": image_view}]
        document["samplers"] = [{"magFilter": 9729, "minFilter": 9729, "wrapS": 10497, "wrapT": 10497}]
        document["textures"] = [{"sampler": 0, "source": 0}]
        document["materials"][0]["pbrMetallicRoughness"]["baseColorTexture"] = {"index": 0}
    return document, builder


def valid_glb(**arguments: Any) -> bytes:
    document, builder = build_document(**arguments)
    return builder.pack(document)


def mutated_glb(change: Callable[[dict[str, Any], GlbBuilder], None], **arguments: Any) -> bytes:
    """A valid model with exactly one thing changed by ``change``."""
    document, builder = build_document(**arguments)
    change(document, builder)
    return builder.pack(document)


__all__ = [
    "GlbBuilder",
    "assemble",
    "build_document",
    "mutated_glb",
    "tiny_png",
    "valid_glb",
]
