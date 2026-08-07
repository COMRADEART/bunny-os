# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Read a hostile GLB and produce a descriptor, or refuse and say why.

The renderer never sees a file. It sees a :class:`ValidatedModel`: a frozen
descriptor whose every index has been proved in range, whose every float has
been proved finite, whose triangle and joint and keyframe counts are all under
their declared bounds, and whose vertex and texture bytes are already tightly
packed for upload. Between the file and that descriptor is this module, and the
whole of its job is to be the only thing that ever touches untrusted geometry.

Three rules shape it.

**Declared before observed.** Every count is checked against its limit from the
JSON *before* the corresponding bytes are read. A document that says it has four
billion accessors is refused at the length of a list, not after allocating them.
This is the difference between a bounded validator and a validator that is
bounded once it finishes.

**No second decoder.** Draco, meshopt and Basis are refused by name with the
reason attached, because each is an unbounded decompressor this project does not
own and cannot bound. So is every buffer ``uri`` — external, relative *and*
``data:`` — because glTF-Binary already has a place to put its bytes and an
alternative place is only ever useful for smuggling. §6's "compression bomb" is
not a hypothetical shape here; it is exactly what those extensions are.

**Refusals name the thing.** ``ModelSecurityError`` for reaching outside the
package or asking for active content, ``ModelLimitError`` for exceeding a bound,
``ModelSchemaError`` for a document that is merely wrong. A package author
fixing an export needs to know which, and a security review needs to know that
the three are not the same test.

What this module deliberately does *not* do is decide anything about
presentation. It does not know what state the character is in, which animation
should play, or whether a GPU exists.
"""

from __future__ import annotations

import array
from dataclasses import dataclass, field
import hashlib
import json
import math
import struct
import sys
from typing import Any, Mapping, Sequence

from . import SUPPORTED_GLTF_VERSION
from .errors import ModelLimitError, ModelSchemaError, ModelSecurityError
from .limits import (
    COMPONENT_TYPES,
    DEFAULT_LIMITS,
    ELEMENT_TYPES,
    KNOWN_REFUSED_EXTENSIONS,
    MAXIMUM_MODEL_EXTENT_METRES,
    MAXIMUM_SCALE,
    MAXIMUM_TRANSFORM_MAGNITUDE,
    MINIMUM_SCALE,
    ModelLimits,
    SUPPORTED_ANIMATION_PATHS,
    SUPPORTED_ATTRIBUTES,
    SUPPORTED_EXTENSIONS,
    SUPPORTED_IMAGE_MEDIA_TYPES,
    SUPPORTED_INTERPOLATIONS,
    SUPPORTED_MORPH_ATTRIBUTES,
    SUPPORTED_PRIMITIVE_MODE,
)
from .skeleton import SkeletonProfile, ancestry_violations, resolve_skeleton

GLB_MAGIC = 0x46546C67  # 'glTF'
CHUNK_JSON = 0x4E4F534A  # 'JSON'
CHUNK_BIN = 0x004E4942  # 'BIN\0'

_LITTLE_ENDIAN = sys.byteorder == "little"


# --------------------------------------------------------------------------- #
# Descriptor
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class VertexStream:
    """One vertex attribute, tightly packed and ready for a buffer object."""

    name: str
    component_type: int
    element_type: str
    components: int
    count: int
    normalized: bool
    data: bytes

    @property
    def byte_length(self) -> int:
        return len(self.data)


@dataclass(frozen=True)
class MorphTargetData:
    """One morph target's position and optional normal deltas."""

    index: int
    name: str
    positions: bytes
    normals: bytes | None

    @property
    def byte_length(self) -> int:
        return len(self.positions) + (len(self.normals) if self.normals else 0)


@dataclass(frozen=True)
class MaterialData:
    """The fixed material model. Nothing here comes from a package shader."""

    index: int
    name: str
    base_colour: tuple[float, float, float, float]
    metallic: float
    roughness: float
    emissive: tuple[float, float, float]
    base_colour_texture: int | None
    alpha_mode: str
    alpha_cutoff: float
    double_sided: bool
    unlit: bool

    def to_json(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "name": self.name,
            "baseColour": list(self.base_colour),
            "metallic": self.metallic,
            "roughness": self.roughness,
            "emissive": list(self.emissive),
            "baseColourTexture": self.base_colour_texture,
            "alphaMode": self.alpha_mode,
            "alphaCutoff": self.alpha_cutoff,
            "doubleSided": self.double_sided,
            "unlit": self.unlit,
        }


@dataclass(frozen=True)
class TextureData:
    """A decoded RGBA8 texture. Decoded here so the GPU path allocates nothing."""

    index: int
    width: int
    height: int
    rgba: bytes
    source_bytes: int
    wrap_s: int
    wrap_t: int
    min_filter: int
    mag_filter: int

    @property
    def decoded_bytes(self) -> int:
        return len(self.rgba)

    def to_json(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "width": self.width,
            "height": self.height,
            "decodedBytes": self.decoded_bytes,
            "encodedBytes": self.source_bytes,
        }


@dataclass(frozen=True)
class PrimitiveData:
    """One drawable primitive: TRIANGLES, indexed, with a validated material."""

    mesh_index: int
    primitive_index: int
    mesh_name: str
    attributes: Mapping[str, VertexStream]
    indices: bytes
    index_count: int
    vertex_count: int
    triangle_count: int
    material: MaterialData
    morph_targets: tuple[MorphTargetData, ...]
    dropped_attributes: tuple[str, ...]

    @property
    def byte_length(self) -> int:
        return (
            sum(stream.byte_length for stream in self.attributes.values())
            + len(self.indices)
            + sum(target.byte_length for target in self.morph_targets)
        )


@dataclass(frozen=True)
class NodeData:
    index: int
    name: str
    parent: int | None
    children: tuple[int, ...]
    translation: tuple[float, float, float]
    rotation: tuple[float, float, float, float]
    scale: tuple[float, float, float]
    mesh: int | None
    skin: int | None
    morph_weights: tuple[float, ...]


@dataclass(frozen=True)
class AnimationSamplerData:
    index: int
    input_times: tuple[float, ...]
    output: tuple[float, ...]
    stride: int
    interpolation: str

    @property
    def duration(self) -> float:
        return self.input_times[-1] if self.input_times else 0.0


@dataclass(frozen=True)
class AnimationChannelData:
    node: int
    path: str
    sampler: int


@dataclass(frozen=True)
class AnimationClipData:
    """One clip, bounded in time and in keyframes, targeting validated nodes."""

    index: int
    name: str
    duration: float
    samplers: tuple[AnimationSamplerData, ...]
    channels: tuple[AnimationChannelData, ...]
    keyframes: int

    def to_json(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "name": self.name,
            "durationSeconds": round(self.duration, 6),
            "channels": len(self.channels),
            "samplers": len(self.samplers),
            "keyframes": self.keyframes,
        }


@dataclass(frozen=True)
class ModelBounds:
    minimum: tuple[float, float, float]
    maximum: tuple[float, float, float]

    @property
    def extent(self) -> tuple[float, float, float]:
        return tuple(hi - lo for lo, hi in zip(self.minimum, self.maximum))  # type: ignore[return-value]

    @property
    def height(self) -> float:
        return self.maximum[1] - self.minimum[1]

    def to_json(self) -> dict[str, Any]:
        return {"min": list(self.minimum), "max": list(self.maximum), "height": self.height}


@dataclass(frozen=True)
class ValidatedModel:
    """Everything the renderer is allowed to know about a character's geometry."""

    digest: str
    file_bytes: int
    gltf_version: str
    generator: str
    nodes: tuple[NodeData, ...]
    root_nodes: tuple[int, ...]
    primitives: tuple[PrimitiveData, ...]
    joints: tuple[int, ...]
    inverse_bind_matrices: tuple[tuple[float, ...], ...]
    skeleton: SkeletonProfile
    clips: tuple[AnimationClipData, ...]
    textures: tuple[TextureData, ...]
    materials: tuple[MaterialData, ...]
    morph_target_names: tuple[str, ...]
    bounds: ModelBounds
    vertex_count: int
    triangle_count: int
    keyframe_count: int
    decoded_texture_bytes: int
    estimated_gpu_bytes: int
    ancestry_notes: tuple[str, ...] = ()
    ignored_extensions: tuple[str, ...] = ()
    limits: ModelLimits = field(default=DEFAULT_LIMITS)

    def clip(self, name: str) -> AnimationClipData | None:
        for clip in self.clips:
            if clip.name == name:
                return clip
        return None

    @property
    def clip_names(self) -> tuple[str, ...]:
        return tuple(clip.name for clip in self.clips)

    def to_json(self) -> dict[str, Any]:
        return {
            "digest": self.digest,
            "fileBytes": self.file_bytes,
            "gltfVersion": self.gltf_version,
            "generator": self.generator,
            "nodes": len(self.nodes),
            "primitives": len(self.primitives),
            "joints": len(self.joints),
            "vertices": self.vertex_count,
            "triangles": self.triangle_count,
            "animations": len(self.clips),
            "keyframes": self.keyframe_count,
            "morphTargets": len(self.morph_target_names),
            "morphTargetNames": list(self.morph_target_names),
            "textures": [texture.to_json() for texture in self.textures],
            "materials": [material.to_json() for material in self.materials],
            "decodedTextureBytes": self.decoded_texture_bytes,
            "estimatedGpuBytes": self.estimated_gpu_bytes,
            "bounds": self.bounds.to_json(),
            "skeleton": self.skeleton.to_json(),
            "clips": [clip.to_json() for clip in self.clips],
            "ancestryNotes": list(self.ancestry_notes),
            "ignoredExtensions": list(self.ignored_extensions),
        }


# --------------------------------------------------------------------------- #
# Primitive readers
# --------------------------------------------------------------------------- #


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, child in pairs:
        if key in value:
            raise ModelSchemaError(f"glTF JSON repeats field {key!r}")
        value[key] = child
    return value


def _object(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ModelSchemaError(f"{name} must be a JSON object")
    return value


def _list(value: Any, name: str, limit: int) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ModelSchemaError(f"{name} must be a JSON array")
    if len(value) > limit:
        raise ModelLimitError(f"{name} declares {len(value)} entries; the limit is {limit}")
    return value


def _index(value: Any, name: str, count: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ModelSchemaError(f"{name} must be an integer index")
    if not 0 <= value < count:
        raise ModelSchemaError(f"{name} is out of range: {value} (of {count})")
    return value


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ModelSchemaError(f"{name} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise ModelSecurityError(f"{name} is NaN or infinite")
    if abs(number) > MAXIMUM_TRANSFORM_MAGNITUDE:
        raise ModelLimitError(f"{name} exceeds the transform magnitude limit")
    return number


def _name(value: Any, limit: int, default: str = "") -> str:
    if value is None:
        return default
    if not isinstance(value, str):
        raise ModelSchemaError("a glTF name must be text")
    if len(value) > limit or "\x00" in value:
        raise ModelLimitError("a glTF name exceeds its length limit or contains NUL")
    return value


def parse_glb(data: bytes, *, limits: ModelLimits = DEFAULT_LIMITS) -> tuple[Mapping[str, Any], bytes]:
    """Split the container. Refuses anything that is not exactly one GLB 2.0.

    The three header fields are checked against each other and against the
    actual length, because a declared length that disagrees with the file is the
    first move in every container attack: the parser trusts one number and the
    reader trusts the other.
    """
    if len(data) < 12:
        raise ModelSchemaError("GLB is shorter than its own header")
    if len(data) > limits.maximum_file_bytes:
        raise ModelLimitError(
            f"GLB is {len(data)} bytes; the limit is {limits.maximum_file_bytes}"
        )
    magic, version, declared = struct.unpack_from("<III", data, 0)
    if magic != GLB_MAGIC:
        raise ModelSchemaError("file is not a GLB container")
    if version != 2:
        raise ModelSchemaError(f"GLB container version {version} is not supported")
    if declared != len(data):
        raise ModelSecurityError(
            f"GLB declares {declared} bytes and is {len(data)}; the container is inconsistent"
        )

    offset = 12
    json_chunk: bytes | None = None
    binary_chunk = b""
    chunks = 0
    while offset < len(data):
        if offset + 8 > len(data):
            raise ModelSchemaError("GLB chunk header is truncated")
        length, kind = struct.unpack_from("<II", data, offset)
        start = offset + 8
        end = start + length
        if length > len(data) or end > len(data):
            raise ModelSecurityError("GLB chunk length reaches past the end of the file")
        if length % 4:
            raise ModelSchemaError("GLB chunk length is not four-byte aligned")
        chunks += 1
        if chunks > 8:
            raise ModelLimitError("GLB contains too many chunks")
        payload = data[start:end]
        if kind == CHUNK_JSON:
            if json_chunk is not None or chunks != 1:
                raise ModelSchemaError("GLB JSON chunk is repeated or not first")
            if length > limits.maximum_json_bytes:
                raise ModelLimitError(
                    f"GLB JSON chunk is {length} bytes; the limit is {limits.maximum_json_bytes}"
                )
            json_chunk = payload
        elif kind == CHUNK_BIN:
            if binary_chunk or chunks != 2:
                raise ModelSchemaError("GLB binary chunk is repeated or misplaced")
            if length > limits.maximum_binary_bytes:
                raise ModelLimitError(
                    f"GLB binary chunk is {length} bytes; the limit is {limits.maximum_binary_bytes}"
                )
            binary_chunk = payload
        else:
            # The specification permits a client to ignore unknown chunks. This
            # one does not: an unknown chunk in a character package is content
            # nobody validated, carried into a user's session for a reason the
            # package has not stated.
            raise ModelSecurityError(
                f"GLB contains an unsupported chunk type 0x{kind:08x}"
            )
        offset = end

    if json_chunk is None:
        raise ModelSchemaError("GLB has no JSON chunk")
    try:
        text = json_chunk.rstrip(b" ").decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ModelSchemaError("GLB JSON chunk is not UTF-8") from exc
    try:
        document = json.loads(text, object_pairs_hook=_no_duplicate_keys)
    except json.JSONDecodeError as exc:
        raise ModelSchemaError(f"GLB JSON chunk is invalid JSON: {exc}") from exc
    return _object(document, "glTF document"), binary_chunk


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


class _Reader:
    """Accessor reads that are in-range by construction.

    Every accessor is resolved once, here, against its buffer view and against
    the single binary chunk. The class exists so that "is this read inside the
    file" is answered in one place rather than at each of the eleven call sites
    that need an accessor, which is how one of them ends up not asking.
    """

    def __init__(self, document: Mapping[str, Any], binary: bytes, limits: ModelLimits) -> None:
        self.document = document
        self.binary = binary
        self.limits = limits
        self.buffers = _list(document.get("buffers"), "buffers", limits.maximum_buffers)
        self.views = _list(document.get("bufferViews"), "bufferViews", limits.maximum_buffer_views)
        self.accessors = _list(document.get("accessors"), "accessors", limits.maximum_accessors)
        self._validate_buffers()
        self._validate_views()

    def _validate_buffers(self) -> None:
        if not self.buffers:
            raise ModelSchemaError("glTF declares no buffer")
        for index, entry in enumerate(self.buffers):
            buffer = _object(entry, f"buffers[{index}]")
            if "uri" in buffer:
                # Covers external files, absolute and relative paths, http(s)
                # URLs and data: URIs in one refusal, because all four are the
                # same mistake: bytes that arrive from somewhere the package
                # manifest did not hash.
                raise ModelSecurityError(
                    f"buffers[{index}] declares a uri; a character package's geometry "
                    "must live in the GLB binary chunk and nowhere else"
                )
            length = buffer.get("byteLength")
            if not isinstance(length, int) or isinstance(length, bool) or length < 0:
                raise ModelSchemaError(f"buffers[{index}].byteLength is invalid")
            if length > self.limits.maximum_binary_bytes:
                raise ModelLimitError(f"buffers[{index}].byteLength exceeds the binary limit")
            if index == 0 and length > len(self.binary):
                raise ModelSecurityError(
                    f"buffers[0] declares {length} bytes; the binary chunk holds {len(self.binary)}"
                )
            if index > 0:
                raise ModelSecurityError("glTF declares a second buffer; only the GLB chunk is permitted")

    def _validate_views(self) -> None:
        for index, entry in enumerate(self.views):
            view = _object(entry, f"bufferViews[{index}]")
            buffer_index = _index(view.get("buffer", 0), f"bufferViews[{index}].buffer", len(self.buffers))
            if buffer_index != 0:
                raise ModelSecurityError("a bufferView refers to a buffer other than the GLB chunk")
            offset = view.get("byteOffset", 0)
            length = view.get("byteLength")
            for name, value in (("byteOffset", offset), ("byteLength", length)):
                if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                    raise ModelSchemaError(f"bufferViews[{index}].{name} is invalid")
            assert isinstance(offset, int) and isinstance(length, int)
            if offset + length > len(self.binary):
                raise ModelSecurityError(
                    f"bufferViews[{index}] spans bytes {offset}..{offset + length} of a "
                    f"{len(self.binary)}-byte binary chunk"
                )
            stride = view.get("byteStride")
            if stride is not None:
                if not isinstance(stride, int) or isinstance(stride, bool) or not 4 <= stride <= 252 or stride % 4:
                    raise ModelSchemaError(f"bufferViews[{index}].byteStride is invalid")

    def accessor(self, index: int, name: str) -> Mapping[str, Any]:
        return _object(self.accessors[_index(index, name, len(self.accessors))], name)

    def describe(self, index: int, name: str) -> tuple[int, str, int, int, bool]:
        """``(componentType, type, components, count, normalized)`` — validated."""
        accessor = self.accessor(index, name)
        if "sparse" in accessor:
            # A sparse accessor is a second, independent index path into the
            # same data. Supporting it means validating two of everything;
            # refusing it costs a package one export option.
            raise ModelSecurityError(f"{name} is a sparse accessor, which is not supported")
        component_type = accessor.get("componentType")
        if component_type not in COMPONENT_TYPES:
            raise ModelSchemaError(f"{name}.componentType is unsupported")
        element_type = accessor.get("type")
        if element_type not in ELEMENT_TYPES:
            raise ModelSchemaError(f"{name}.type is unsupported")
        count = accessor.get("count")
        if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
            raise ModelSchemaError(f"{name}.count is invalid")
        normalized = accessor.get("normalized", False)
        if not isinstance(normalized, bool):
            raise ModelSchemaError(f"{name}.normalized must be boolean")
        return component_type, str(element_type), ELEMENT_TYPES[str(element_type)], count, normalized

    def raw(self, index: int, name: str) -> tuple[bytes, int, str, int, int, bool]:
        """Tightly-packed bytes for an accessor, de-interleaved if it was strided."""
        accessor = self.accessor(index, name)
        component_type, element_type, components, count, normalized = self.describe(index, name)
        width = COMPONENT_TYPES[component_type][1]
        element_bytes = width * components
        view_index = accessor.get("bufferView")
        if view_index is None:
            # A view-less accessor is defined to read as zeros. Materialising it
            # is cheap and keeps every downstream consumer from having to know.
            return b"\x00" * (element_bytes * count), component_type, element_type, components, count, normalized
        view = _object(self.views[_index(view_index, f"{name}.bufferView", len(self.views))], "bufferView")
        view_offset = int(view.get("byteOffset", 0))
        view_length = int(view["byteLength"])
        accessor_offset = accessor.get("byteOffset", 0)
        if not isinstance(accessor_offset, int) or isinstance(accessor_offset, bool) or accessor_offset < 0:
            raise ModelSchemaError(f"{name}.byteOffset is invalid")
        if accessor_offset % width:
            raise ModelSchemaError(f"{name}.byteOffset is not aligned to its component size")
        stride = view.get("byteStride") or element_bytes
        if stride < element_bytes:
            raise ModelSchemaError(f"{name} has a byteStride smaller than one element")
        span = accessor_offset + stride * (count - 1) + element_bytes
        if span > view_length:
            raise ModelSecurityError(
                f"{name} reads {span} bytes from a {view_length}-byte bufferView"
            )
        base = view_offset + accessor_offset
        if stride == element_bytes:
            return (
                bytes(self.binary[base:base + element_bytes * count]),
                component_type, element_type, components, count, normalized,
            )
        packed = bytearray(element_bytes * count)
        for item in range(count):
            source = base + stride * item
            packed[item * element_bytes:(item + 1) * element_bytes] = self.binary[source:source + element_bytes]
        return bytes(packed), component_type, element_type, components, count, normalized

    def floats(self, index: int, name: str) -> tuple[tuple[float, ...], int, int]:
        """Accessor contents as finite floats. Normalised integers are expanded."""
        data, component_type, _element, components, count, normalized = self.raw(index, name)
        values = _decode_components(data, component_type, normalized, name)
        if len(values) != components * count:
            raise ModelSchemaError(f"{name} decoded to the wrong number of components")
        return values, components, count

    def integers(self, index: int, name: str) -> tuple[tuple[int, ...], int, int]:
        data, component_type, _element, components, count, _normalized = self.raw(index, name)
        code = {5120: "b", 5121: "B", 5122: "h", 5123: "H", 5125: "I"}.get(component_type)
        if code is None:
            raise ModelSchemaError(f"{name} must have an integer component type")
        values = array.array(code)
        values.frombytes(data)
        if not _LITTLE_ENDIAN and values.itemsize > 1:
            values.byteswap()
        return tuple(values), components, count


def _decode_components(
    data: bytes, component_type: int, normalized: bool, name: str
) -> tuple[float, ...]:
    code = {5120: "b", 5121: "B", 5122: "h", 5123: "H", 5125: "I", 5126: "f"}[component_type]
    values = array.array(code)
    values.frombytes(data)
    if not _LITTLE_ENDIAN and values.itemsize > 1:
        values.byteswap()
    if component_type == 5126:
        for value in values:
            if not math.isfinite(value):
                raise ModelSecurityError(f"{name} contains a NaN or infinite value")
        return tuple(float(value) for value in values)
    if not normalized:
        return tuple(float(value) for value in values)
    divisor = {5120: 127.0, 5121: 255.0, 5122: 32767.0, 5123: 65535.0, 5125: 4294967295.0}[component_type]
    return tuple(max(-1.0, float(value) / divisor) for value in values)


def _transform(node: Mapping[str, Any], index: int) -> tuple[
    tuple[float, float, float], tuple[float, float, float, float], tuple[float, float, float]
]:
    if "matrix" in node:
        # A TRS decomposition of an arbitrary matrix is ambiguous for shears,
        # and a shear is not something a humanoid rig needs. Refusing it keeps
        # one representation of a transform in the whole renderer.
        raise ModelSchemaError(
            f"nodes[{index}] uses a matrix; this renderer requires translation/rotation/scale"
        )
    translation = node.get("translation", (0.0, 0.0, 0.0))
    rotation = node.get("rotation", (0.0, 0.0, 0.0, 1.0))
    scale = node.get("scale", (1.0, 1.0, 1.0))
    for value, size, label in ((translation, 3, "translation"), (rotation, 4, "rotation"), (scale, 3, "scale")):
        if not isinstance(value, (list, tuple)) or len(value) != size:
            raise ModelSchemaError(f"nodes[{index}].{label} must have {size} components")
    parsed_translation = tuple(_finite(value, f"nodes[{index}].translation") for value in translation)
    parsed_rotation = tuple(_finite(value, f"nodes[{index}].rotation") for value in rotation)
    parsed_scale = tuple(_finite(value, f"nodes[{index}].scale") for value in scale)
    for component in parsed_scale:
        magnitude = abs(component)
        if magnitude > MAXIMUM_SCALE:
            raise ModelLimitError(f"nodes[{index}].scale component {component} exceeds the scale limit")
        if magnitude and magnitude < MINIMUM_SCALE:
            raise ModelLimitError(f"nodes[{index}].scale component {component} is below the scale floor")
    length = math.sqrt(sum(component * component for component in parsed_rotation))
    if not 0.9 <= length <= 1.1:
        raise ModelSchemaError(f"nodes[{index}].rotation is not a unit quaternion")
    return parsed_translation, parsed_rotation, parsed_scale  # type: ignore[return-value]


def _material(entry: Any, index: int, textures: int, limits: ModelLimits, unlit_allowed: bool) -> MaterialData:
    material = _object(entry, f"materials[{index}]")
    pbr = _object(material.get("pbrMetallicRoughness", {}), f"materials[{index}].pbrMetallicRoughness")
    base = pbr.get("baseColorFactor", (1.0, 1.0, 1.0, 1.0))
    if not isinstance(base, (list, tuple)) or len(base) != 4:
        raise ModelSchemaError(f"materials[{index}].baseColorFactor must have four components")
    colour = tuple(min(1.0, max(0.0, _finite(value, f"materials[{index}].baseColorFactor"))) for value in base)
    metallic = min(1.0, max(0.0, _finite(pbr.get("metallicFactor", 1.0), f"materials[{index}].metallicFactor")))
    roughness = min(1.0, max(0.0, _finite(pbr.get("roughnessFactor", 1.0), f"materials[{index}].roughnessFactor")))
    emissive_raw = material.get("emissiveFactor", (0.0, 0.0, 0.0))
    if not isinstance(emissive_raw, (list, tuple)) or len(emissive_raw) != 3:
        raise ModelSchemaError(f"materials[{index}].emissiveFactor must have three components")
    emissive = tuple(
        min(1.0, max(0.0, _finite(value, f"materials[{index}].emissiveFactor"))) for value in emissive_raw
    )
    texture_index: int | None = None
    base_texture = pbr.get("baseColorTexture")
    if base_texture is not None:
        reference = _object(base_texture, f"materials[{index}].baseColorTexture")
        texture_index = _index(reference.get("index"), f"materials[{index}].baseColorTexture.index", textures)
        tex_coord = reference.get("texCoord", 0)
        if tex_coord != 0:
            raise ModelSchemaError(f"materials[{index}] uses a texture coordinate set this renderer does not bind")
    alpha_mode = material.get("alphaMode", "OPAQUE")
    if alpha_mode not in {"OPAQUE", "MASK", "BLEND"}:
        raise ModelSchemaError(f"materials[{index}].alphaMode is unsupported")
    cutoff = min(1.0, max(0.0, _finite(material.get("alphaCutoff", 0.5), f"materials[{index}].alphaCutoff")))
    double_sided = material.get("doubleSided", False)
    if not isinstance(double_sided, bool):
        raise ModelSchemaError(f"materials[{index}].doubleSided must be boolean")
    extensions = _object(material.get("extensions", {}), f"materials[{index}].extensions")
    unlit = "KHR_materials_unlit" in extensions
    if unlit and not unlit_allowed:
        raise ModelSecurityError(f"materials[{index}] uses KHR_materials_unlit without declaring it")
    for name in extensions:
        if name not in SUPPORTED_EXTENSIONS:
            raise ModelSecurityError(f"materials[{index}] uses unsupported extension {name}")
    return MaterialData(
        index=index,
        name=_name(material.get("name"), limits.maximum_name_length, f"material-{index}"),
        base_colour=colour,  # type: ignore[arg-type]
        metallic=metallic,
        roughness=roughness,
        emissive=emissive,  # type: ignore[arg-type]
        base_colour_texture=texture_index,
        alpha_mode=str(alpha_mode),
        alpha_cutoff=cutoff,
        double_sided=double_sided,
        unlit=unlit,
    )


DEFAULT_MATERIAL = MaterialData(
    index=-1,
    name="bunny-default",
    base_colour=(0.82, 0.78, 0.74, 1.0),
    metallic=0.0,
    roughness=0.85,
    emissive=(0.0, 0.0, 0.0),
    base_colour_texture=None,
    alpha_mode="OPAQUE",
    alpha_cutoff=0.5,
    double_sided=False,
    unlit=False,
)


def validate_glb(
    data: bytes,
    *,
    limits: ModelLimits = DEFAULT_LIMITS,
    bone_map: Mapping[str, str] | None = None,
    expected_digest: str | None = None,
    skeleton_profile_id: str = "bunny-humanoid-1",
) -> ValidatedModel:
    """The whole validator. Returns a descriptor or raises a typed refusal."""
    digest = hashlib.sha256(data).hexdigest()
    if expected_digest is not None and digest != expected_digest:
        raise ModelSecurityError("model digest does not match the manifest")

    document, binary = parse_glb(data, limits=limits)

    asset = _object(document.get("asset"), "asset")
    if str(asset.get("version")) != SUPPORTED_GLTF_VERSION:
        raise ModelSchemaError(f"glTF version {asset.get('version')!r} is not supported")
    generator = _name(asset.get("generator"), limits.maximum_name_length, "unknown")

    required = _list(document.get("extensionsRequired"), "extensionsRequired", limits.maximum_extension_names)
    used = _list(document.get("extensionsUsed"), "extensionsUsed", limits.maximum_extension_names)
    for name in required:
        text = _name(name, limits.maximum_name_length)
        if text in KNOWN_REFUSED_EXTENSIONS:
            raise ModelSecurityError(
                f"required extension {text} is refused: {KNOWN_REFUSED_EXTENSIONS[text]}"
            )
        if text not in SUPPORTED_EXTENSIONS:
            raise ModelSecurityError(f"required extension {text} is not implemented by this renderer")
    ignored: list[str] = []
    for name in used:
        text = _name(name, limits.maximum_name_length)
        if text in SUPPORTED_EXTENSIONS:
            continue
        if text in KNOWN_REFUSED_EXTENSIONS:
            raise ModelSecurityError(
                f"extension {text} is refused: {KNOWN_REFUSED_EXTENSIONS[text]}"
            )
        # Not required, not supported, not on the refusal list. It cannot change
        # what the renderer draws, because the renderer reads no extension it
        # does not implement — but it is recorded so a reviewer sees it.
        ignored.append(text)

    # Anything at the document root that is not part of the contract is refused.
    # An unexpected top-level key is either a newer specification this build has
    # not read or a payload for something that is not this renderer.
    permitted_root = {
        "asset", "scene", "scenes", "nodes", "meshes", "materials", "textures",
        "images", "samplers", "skins", "animations", "accessors", "bufferViews",
        "buffers", "extensionsUsed", "extensionsRequired", "extensions", "extras",
        "cameras",
    }
    unexpected = sorted(set(map(str, document)).difference(permitted_root))
    if unexpected:
        raise ModelSchemaError("glTF document contains unsupported top-level fields: " + ", ".join(unexpected))
    if "cameras" in document:
        # §17: the presentation camera is deterministic and renderer-owned. A
        # package-supplied camera is not read, so carrying one is a statement
        # about intent the manifest has not made.
        raise ModelSecurityError("a character package may not supply cameras; the presentation camera is renderer-owned")

    reader = _Reader(document, binary, limits)

    # -- textures ---------------------------------------------------------
    images = _list(document.get("images"), "images", limits.maximum_images)
    texture_entries = _list(document.get("textures"), "textures", limits.maximum_textures)
    samplers = _list(document.get("samplers"), "samplers", limits.maximum_samplers)
    textures: list[TextureData] = []
    decoded_total = 0
    for index, entry in enumerate(texture_entries):
        texture = _object(entry, f"textures[{index}]")
        source = texture.get("source")
        if source is None:
            raise ModelSchemaError(f"textures[{index}] has no image source")
        image = _object(images[_index(source, f"textures[{index}].source", len(images))], "image")
        if "uri" in image:
            raise ModelSecurityError(
                f"images[{source}] declares a uri; texture bytes must live in the GLB binary chunk"
            )
        media_type = image.get("mimeType")
        if media_type not in SUPPORTED_IMAGE_MEDIA_TYPES:
            raise ModelSecurityError(
                f"images[{source}] declares mimeType {media_type!r}; only PNG is decoded here"
            )
        view_index = image.get("bufferView")
        if view_index is None:
            raise ModelSchemaError(f"images[{source}] has neither a uri nor a bufferView")
        view = _object(reader.views[_index(view_index, f"images[{source}].bufferView", len(reader.views))], "bufferView")
        start = int(view.get("byteOffset", 0))
        length = int(view["byteLength"])
        encoded = bytes(binary[start:start + length])
        from companion.character.image import decode_png_rgba

        decoded = decode_png_rgba(encoded, maximum_dimension=limits.maximum_texture_dimension)
        decoded_total += len(decoded.rgba)
        if decoded_total > limits.maximum_decoded_texture_bytes:
            raise ModelLimitError(
                f"decoded textures total {decoded_total} bytes; the limit is "
                f"{limits.maximum_decoded_texture_bytes}"
            )
        sampler_index = texture.get("sampler")
        wrap_s = wrap_t = 10497  # REPEAT
        min_filter = 9987  # LINEAR_MIPMAP_LINEAR
        mag_filter = 9729  # LINEAR
        if sampler_index is not None:
            sampler = _object(
                samplers[_index(sampler_index, f"textures[{index}].sampler", len(samplers))], "sampler"
            )
            wrap_s = int(sampler.get("wrapS", wrap_s))
            wrap_t = int(sampler.get("wrapT", wrap_t))
            min_filter = int(sampler.get("minFilter", min_filter))
            mag_filter = int(sampler.get("magFilter", mag_filter))
            if wrap_s not in {10497, 33071, 33648} or wrap_t not in {10497, 33071, 33648}:
                raise ModelSchemaError(f"textures[{index}] uses an unsupported wrap mode")
            if min_filter not in {9728, 9729, 9984, 9985, 9986, 9987} or mag_filter not in {9728, 9729}:
                raise ModelSchemaError(f"textures[{index}] uses an unsupported filter")
        textures.append(TextureData(
            index=index, width=decoded.width, height=decoded.height, rgba=decoded.rgba,
            source_bytes=len(encoded), wrap_s=wrap_s, wrap_t=wrap_t,
            min_filter=min_filter, mag_filter=mag_filter,
        ))

    # -- materials --------------------------------------------------------
    material_entries = _list(document.get("materials"), "materials", limits.maximum_materials)
    unlit_allowed = "KHR_materials_unlit" in set(map(str, used)) | set(map(str, required))
    materials = tuple(
        _material(entry, index, len(textures), limits, unlit_allowed)
        for index, entry in enumerate(material_entries)
    )

    # -- nodes ------------------------------------------------------------
    node_entries = _list(document.get("nodes"), "nodes", limits.maximum_nodes)
    if not node_entries:
        raise ModelSchemaError("glTF declares no nodes")
    mesh_entries = _list(document.get("meshes"), "meshes", limits.maximum_meshes)
    skin_entries = _list(document.get("skins"), "skins", limits.maximum_skins)
    parent_of: dict[int, int | None] = {index: None for index in range(len(node_entries))}
    children_of: dict[int, tuple[int, ...]] = {}
    for index, entry in enumerate(node_entries):
        node = _object(entry, f"nodes[{index}]")
        unexpected_node = set(map(str, node)).difference({
            "name", "children", "translation", "rotation", "scale", "matrix",
            "mesh", "skin", "weights", "extensions", "extras", "camera",
        })
        if unexpected_node:
            raise ModelSchemaError(
                f"nodes[{index}] contains unsupported fields: " + ", ".join(sorted(unexpected_node))
            )
        if "camera" in node:
            raise ModelSecurityError(f"nodes[{index}] attaches a camera; the presentation camera is renderer-owned")
        children = _list(node.get("children"), f"nodes[{index}].children", limits.maximum_nodes)
        resolved: list[int] = []
        for child in children:
            child_index = _index(child, f"nodes[{index}].children", len(node_entries))
            if child_index == index:
                raise ModelSecurityError(f"nodes[{index}] is its own child")
            if parent_of[child_index] is not None:
                raise ModelSecurityError(
                    f"nodes[{child_index}] has more than one parent; the node graph is not a tree"
                )
            parent_of[child_index] = index
            resolved.append(child_index)
        if len(set(resolved)) != len(resolved):
            raise ModelSchemaError(f"nodes[{index}] repeats a child")
        children_of[index] = tuple(resolved)

    roots = tuple(index for index, parent in parent_of.items() if parent is None)
    if not roots:
        # Every node has a parent, which for a finite graph means a cycle.
        raise ModelSecurityError("the node graph has no root; it contains a cycle")

    depth_of: dict[int, int] = {}
    stack: list[tuple[int, int]] = [(root, 0) for root in roots]
    visited: set[int] = set()
    while stack:
        current, depth = stack.pop()
        if current in visited:
            raise ModelSecurityError("the node graph contains a cycle")
        visited.add(current)
        if depth > limits.maximum_node_depth:
            raise ModelLimitError(f"the node graph is deeper than {limits.maximum_node_depth}")
        depth_of[current] = depth
        for child in children_of[current]:
            stack.append((child, depth + 1))
    if len(visited) != len(node_entries):
        raise ModelSecurityError("some nodes are unreachable from any root; the graph is not a tree")

    nodes: list[NodeData] = []
    for index, entry in enumerate(node_entries):
        node = _object(entry, f"nodes[{index}]")
        translation, rotation, scale = _transform(node, index)
        mesh_index = node.get("mesh")
        if mesh_index is not None:
            mesh_index = _index(mesh_index, f"nodes[{index}].mesh", len(mesh_entries))
        skin_index = node.get("skin")
        if skin_index is not None:
            skin_index = _index(skin_index, f"nodes[{index}].skin", len(skin_entries))
            if mesh_index is None:
                raise ModelSchemaError(f"nodes[{index}] has a skin but no mesh")
        weights_raw = node.get("weights", ())
        weights = tuple(
            _finite(value, f"nodes[{index}].weights") for value in _list(
                list(weights_raw) if weights_raw else None,
                f"nodes[{index}].weights", limits.maximum_morph_targets,
            )
        )
        nodes.append(NodeData(
            index=index,
            name=_name(node.get("name"), limits.maximum_name_length, f"node-{index}"),
            parent=parent_of[index],
            children=children_of[index],
            translation=translation,
            rotation=rotation,
            scale=scale,
            mesh=mesh_index,
            skin=skin_index,
            morph_weights=weights,
        ))

    # -- skin -------------------------------------------------------------
    if len(skin_entries) != 1:
        raise ModelSchemaError(
            f"a Bunny character declares exactly one skin; this model declares {len(skin_entries)}"
        )
    skin = _object(skin_entries[0], "skins[0]")
    joint_list = _list(skin.get("joints"), "skins[0].joints", limits.maximum_joints)
    if not joint_list:
        raise ModelSchemaError("skins[0] declares no joints")
    joints = tuple(_index(value, "skins[0].joints", len(node_entries)) for value in joint_list)
    if len(set(joints)) != len(joints):
        raise ModelSchemaError("skins[0] repeats a joint")
    inverse_bind: tuple[tuple[float, ...], ...] = ()
    ibm_index = skin.get("inverseBindMatrices")
    if ibm_index is not None:
        values, components, count = reader.floats(ibm_index, "skins[0].inverseBindMatrices")
        if components != 16 or count != len(joints):
            raise ModelSchemaError("skins[0].inverseBindMatrices does not match the joint count")
        inverse_bind = tuple(
            tuple(values[item * 16:(item + 1) * 16]) for item in range(count)
        )
    else:
        identity = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)
        inverse_bind = tuple(identity for _ in joints)

    joint_names = tuple(nodes[index].name for index in joints)
    skeleton = resolve_skeleton(
        joint_names, joints, bone_map=bone_map, profile_id=skeleton_profile_id
    )
    notes = ancestry_violations(skeleton, parent_of)

    # -- meshes -----------------------------------------------------------
    primitives: list[PrimitiveData] = []
    total_vertices = 0
    total_triangles = 0
    total_primitives = 0
    morph_names: tuple[str, ...] = ()
    minimum = [math.inf, math.inf, math.inf]
    maximum = [-math.inf, -math.inf, -math.inf]

    for mesh_index, mesh_entry in enumerate(mesh_entries):
        mesh = _object(mesh_entry, f"meshes[{mesh_index}]")
        mesh_name = _name(mesh.get("name"), limits.maximum_name_length, f"mesh-{mesh_index}")
        target_names = mesh.get("extras", {})
        if isinstance(target_names, Mapping):
            declared = target_names.get("targetNames")
            if isinstance(declared, list) and declared:
                candidate = tuple(
                    _name(value, limits.maximum_name_length, "") for value in
                    _list(declared, "extras.targetNames", limits.maximum_morph_targets)
                )
                if morph_names and candidate != morph_names:
                    raise ModelSchemaError("meshes disagree about their morph-target names")
                morph_names = candidate
        mesh_primitives = _list(mesh.get("primitives"), f"meshes[{mesh_index}].primitives", limits.maximum_primitives)
        if not mesh_primitives:
            raise ModelSchemaError(f"meshes[{mesh_index}] declares no primitives")
        for primitive_index, primitive_entry in enumerate(mesh_primitives):
            total_primitives += 1
            if total_primitives > limits.maximum_primitives:
                raise ModelLimitError(f"the model declares more than {limits.maximum_primitives} primitives")
            label = f"meshes[{mesh_index}].primitives[{primitive_index}]"
            primitive = _object(primitive_entry, label)
            mode = primitive.get("mode", SUPPORTED_PRIMITIVE_MODE)
            if mode != SUPPORTED_PRIMITIVE_MODE:
                raise ModelSchemaError(f"{label}.mode is not TRIANGLES")
            attributes_raw = _object(primitive.get("attributes"), f"{label}.attributes")
            if "POSITION" not in attributes_raw:
                raise ModelSchemaError(f"{label} has no POSITION attribute")
            streams: dict[str, VertexStream] = {}
            dropped: list[str] = []
            vertex_count = 0
            for attribute, accessor_index in attributes_raw.items():
                attribute_name = str(attribute)
                if attribute_name not in SUPPORTED_ATTRIBUTES:
                    dropped.append(attribute_name)
                    continue
                data_bytes, component_type, element_type, components, count, normalized = reader.raw(
                    accessor_index, f"{label}.attributes.{attribute_name}"
                )
                if attribute_name == "POSITION":
                    if element_type != "VEC3" or component_type != 5126:
                        raise ModelSchemaError(f"{label}.POSITION must be float VEC3")
                    vertex_count = count
                    positions = _decode_components(data_bytes, component_type, normalized, f"{label}.POSITION")
                    for axis in range(3):
                        column = positions[axis::3]
                        if column:
                            minimum[axis] = min(minimum[axis], min(column))
                            maximum[axis] = max(maximum[axis], max(column))
                elif attribute_name in {"JOINTS_0"}:
                    if element_type != "VEC4" or component_type not in {5121, 5123}:
                        raise ModelSchemaError(f"{label}.JOINTS_0 must be VEC4 of unsigned bytes or shorts")
                    indices = array.array({5121: "B", 5123: "H"}[component_type])
                    indices.frombytes(data_bytes)
                    if not _LITTLE_ENDIAN and indices.itemsize > 1:
                        indices.byteswap()
                    for joint in indices:
                        if joint >= len(joints):
                            raise ModelSecurityError(
                                f"{label}.JOINTS_0 references joint {joint} of {len(joints)}"
                            )
                elif attribute_name == "WEIGHTS_0":
                    if element_type != "VEC4":
                        raise ModelSchemaError(f"{label}.WEIGHTS_0 must be VEC4")
                    _decode_components(data_bytes, component_type, normalized, f"{label}.WEIGHTS_0")
                elif attribute_name == "COLOR_0":
                    # The one attribute glTF permits in two shapes.
                    if element_type not in {"VEC3", "VEC4"}:
                        raise ModelSchemaError(f"{label}.COLOR_0 must be VEC3 or VEC4")
                    if component_type not in {5126, 5121, 5123}:
                        raise ModelSchemaError(f"{label}.COLOR_0 has an unsupported component type")
                    _decode_components(data_bytes, component_type, normalized, f"{label}.COLOR_0")
                elif attribute_name == "TEXCOORD_0":
                    if element_type != "VEC2":
                        raise ModelSchemaError(f"{label}.TEXCOORD_0 must be VEC2")
                    _decode_components(data_bytes, component_type, normalized, f"{label}.TEXCOORD_0")
                elif attribute_name == "NORMAL":
                    if element_type != "VEC3" or component_type != 5126:
                        raise ModelSchemaError(f"{label}.NORMAL must be float VEC3")
                    _decode_components(data_bytes, component_type, normalized, f"{label}.NORMAL")
                else:
                    _decode_components(data_bytes, component_type, normalized, f"{label}.{attribute_name}")
                streams[attribute_name] = VertexStream(
                    name=attribute_name, component_type=component_type, element_type=element_type,
                    components=components, count=count, normalized=normalized, data=data_bytes,
                )
            for attribute_name, stream in streams.items():
                if stream.count != vertex_count:
                    raise ModelSchemaError(
                        f"{label}.{attribute_name} has {stream.count} elements and POSITION has {vertex_count}"
                    )
            total_vertices += vertex_count
            if total_vertices > limits.maximum_vertices:
                raise ModelLimitError(
                    f"the model declares {total_vertices} vertices; the limit is {limits.maximum_vertices}"
                )

            index_accessor = primitive.get("indices")
            if index_accessor is None:
                raise ModelSchemaError(f"{label} is not indexed; this renderer requires indices")
            index_values, index_components, index_count = reader.integers(index_accessor, f"{label}.indices")
            if index_components != 1:
                raise ModelSchemaError(f"{label}.indices must be SCALAR")
            if index_count % 3:
                raise ModelSchemaError(f"{label}.indices count is not a multiple of three")
            triangles = index_count // 3
            total_triangles += triangles
            if total_triangles > limits.maximum_triangles:
                raise ModelLimitError(
                    f"the model declares {total_triangles} triangles; the limit is {limits.maximum_triangles}"
                )
            for value in index_values:
                if value >= vertex_count:
                    raise ModelSecurityError(
                        f"{label}.indices references vertex {value} of {vertex_count}"
                    )
            packed_indices = array.array("I", index_values)
            if not _LITTLE_ENDIAN:
                packed_indices.byteswap()

            material_index = primitive.get("material")
            if material_index is None:
                material = DEFAULT_MATERIAL
            else:
                material = materials[_index(material_index, f"{label}.material", len(materials))]

            targets_raw = _list(primitive.get("targets"), f"{label}.targets", limits.maximum_morph_targets)
            morph_targets: list[MorphTargetData] = []
            for target_index, target_entry in enumerate(targets_raw):
                target = _object(target_entry, f"{label}.targets[{target_index}]")
                unknown = set(map(str, target)).difference(SUPPORTED_MORPH_ATTRIBUTES)
                if unknown:
                    raise ModelSchemaError(
                        f"{label}.targets[{target_index}] uses unsupported attributes: "
                        + ", ".join(sorted(unknown))
                    )
                if "POSITION" not in target:
                    raise ModelSchemaError(f"{label}.targets[{target_index}] has no POSITION deltas")
                position_bytes, component_type, element_type, _components, count, normalized = reader.raw(
                    target["POSITION"], f"{label}.targets[{target_index}].POSITION"
                )
                if element_type != "VEC3" or component_type != 5126:
                    raise ModelSchemaError(f"{label}.targets[{target_index}].POSITION must be float VEC3")
                if count != vertex_count:
                    raise ModelSchemaError(
                        f"{label}.targets[{target_index}] has {count} deltas for {vertex_count} vertices"
                    )
                _decode_components(position_bytes, component_type, normalized, f"{label}.targets[{target_index}]")
                normal_bytes: bytes | None = None
                if "NORMAL" in target:
                    normal_bytes, normal_component, normal_element, _c, normal_count, normal_norm = reader.raw(
                        target["NORMAL"], f"{label}.targets[{target_index}].NORMAL"
                    )
                    if normal_element != "VEC3" or normal_component != 5126 or normal_count != vertex_count:
                        raise ModelSchemaError(f"{label}.targets[{target_index}].NORMAL is invalid")
                    _decode_components(normal_bytes, normal_component, normal_norm, f"{label}.targets NORMAL")
                morph_targets.append(MorphTargetData(
                    index=target_index,
                    name=morph_names[target_index] if target_index < len(morph_names) else f"morph-{target_index}",
                    positions=position_bytes,
                    normals=normal_bytes,
                ))
            if morph_names and morph_targets and len(morph_names) != len(morph_targets):
                raise ModelSchemaError("targetNames does not match the number of morph targets")

            primitives.append(PrimitiveData(
                mesh_index=mesh_index,
                primitive_index=primitive_index,
                mesh_name=mesh_name,
                attributes=streams,
                indices=packed_indices.tobytes(),
                index_count=index_count,
                vertex_count=vertex_count,
                triangle_count=triangles,
                material=material,
                morph_targets=tuple(morph_targets),
                dropped_attributes=tuple(sorted(dropped)),
            ))

    if not primitives:
        raise ModelSchemaError("the model draws nothing")
    if len(joints) > limits.maximum_joints:
        raise ModelLimitError(f"the model declares {len(joints)} joints; the limit is {limits.maximum_joints}")
    if morph_names and len(morph_names) > limits.maximum_morph_targets:
        raise ModelLimitError("the model declares more morph targets than the limit")

    if not all(math.isfinite(value) for value in minimum + maximum):
        raise ModelSchemaError("the model has no finite bounding box")
    bounds = ModelBounds(tuple(minimum), tuple(maximum))  # type: ignore[arg-type]
    extent = max(bounds.extent)
    if extent > MAXIMUM_MODEL_EXTENT_METRES:
        raise ModelLimitError(
            f"the model is {extent:.2f} units across; the limit is {MAXIMUM_MODEL_EXTENT_METRES}"
        )
    if extent <= 0:
        raise ModelSchemaError("the model has zero extent")

    # -- animations -------------------------------------------------------
    animation_entries = _list(document.get("animations"), "animations", limits.maximum_animations)
    clips: list[AnimationClipData] = []
    total_keyframes = 0
    total_channels = 0
    total_samplers = 0
    node_count = len(node_entries)
    for index, entry in enumerate(animation_entries):
        animation = _object(entry, f"animations[{index}]")
        sampler_entries = _list(
            animation.get("samplers"), f"animations[{index}].samplers", limits.maximum_animation_samplers
        )
        channel_entries = _list(
            animation.get("channels"), f"animations[{index}].channels", limits.maximum_animation_channels
        )
        total_samplers += len(sampler_entries)
        total_channels += len(channel_entries)
        if total_samplers > limits.maximum_animation_samplers:
            raise ModelLimitError("the model declares more animation samplers than the limit")
        if total_channels > limits.maximum_animation_channels:
            raise ModelLimitError("the model declares more animation channels than the limit")
        samplers_out: list[AnimationSamplerData] = []
        duration = 0.0
        for sampler_index, sampler_entry in enumerate(sampler_entries):
            sampler = _object(sampler_entry, f"animations[{index}].samplers[{sampler_index}]")
            interpolation = sampler.get("interpolation", "LINEAR")
            if interpolation not in SUPPORTED_INTERPOLATIONS:
                raise ModelSchemaError(f"animations[{index}] uses interpolation {interpolation!r}")
            times, time_components, time_count = reader.floats(
                sampler.get("input"), f"animations[{index}].samplers[{sampler_index}].input"
            )
            if time_components != 1:
                raise ModelSchemaError(f"animations[{index}] sampler input must be SCALAR")
            if time_count > limits.maximum_keyframes_per_sampler:
                raise ModelLimitError(
                    f"animations[{index}] sampler has {time_count} keyframes; the per-sampler limit is "
                    f"{limits.maximum_keyframes_per_sampler}"
                )
            previous = -math.inf
            for value in times:
                if value < 0:
                    raise ModelSchemaError(f"animations[{index}] has a negative keyframe time")
                if value < previous:
                    raise ModelSchemaError(f"animations[{index}] keyframe times are not monotonic")
                previous = value
            if times and times[-1] > limits.maximum_animation_seconds:
                raise ModelLimitError(
                    f"animations[{index}] is {times[-1]:.2f}s long; the limit is "
                    f"{limits.maximum_animation_seconds}s"
                )
            output, output_components, output_count = reader.floats(
                sampler.get("output"), f"animations[{index}].samplers[{sampler_index}].output"
            )
            expected = time_count * (3 if interpolation == "CUBICSPLINE" else 1)
            if output_count != expected:
                raise ModelSchemaError(
                    f"animations[{index}] sampler output has {output_count} elements; {expected} expected"
                )
            total_keyframes += time_count
            if total_keyframes > limits.maximum_keyframes:
                raise ModelLimitError(
                    f"the model declares {total_keyframes} keyframes; the limit is {limits.maximum_keyframes}"
                )
            duration = max(duration, times[-1] if times else 0.0)
            samplers_out.append(AnimationSamplerData(
                index=sampler_index, input_times=times, output=output,
                stride=output_components, interpolation=str(interpolation),
            ))
        channels_out: list[AnimationChannelData] = []
        for channel_index, channel_entry in enumerate(channel_entries):
            channel = _object(channel_entry, f"animations[{index}].channels[{channel_index}]")
            sampler_index = _index(
                channel.get("sampler"), f"animations[{index}].channels[{channel_index}].sampler",
                len(samplers_out),
            )
            target = _object(channel.get("target"), f"animations[{index}].channels[{channel_index}].target")
            node_index = target.get("node")
            if node_index is None:
                # A channel with no node targets nothing and is defined to be
                # ignored. Refused instead: a channel that does nothing in a
                # character package is a channel whose author believed it did.
                raise ModelSchemaError(f"animations[{index}] has a channel with no target node")
            node_index = _index(node_index, f"animations[{index}].channels[{channel_index}].target.node", node_count)
            path = target.get("path")
            if path not in SUPPORTED_ANIMATION_PATHS:
                raise ModelSchemaError(f"animations[{index}] targets unsupported path {path!r}")
            sampler = samplers_out[sampler_index]
            if path == "rotation" and sampler.stride != 4:
                raise ModelSchemaError(f"animations[{index}] rotation sampler is not VEC4")
            if path in {"translation", "scale"} and sampler.stride != 3:
                raise ModelSchemaError(f"animations[{index}] {path} sampler is not VEC3")
            if path == "weights":
                mesh_index = nodes[node_index].mesh
                if mesh_index is None:
                    raise ModelSchemaError(f"animations[{index}] animates weights on a node with no mesh")
                target_count = len(primitives[0].morph_targets) if primitives else 0
                for candidate in primitives:
                    if candidate.mesh_index == mesh_index:
                        target_count = len(candidate.morph_targets)
                        break
                if target_count == 0:
                    raise ModelSchemaError(f"animations[{index}] animates weights on a mesh with no morph targets")
            channels_out.append(AnimationChannelData(node=node_index, path=str(path), sampler=sampler_index))
        if not channels_out:
            raise ModelSchemaError(f"animations[{index}] has no channels")
        clip_name = _name(animation.get("name"), limits.maximum_name_length, f"animation-{index}")
        if any(clip.name == clip_name for clip in clips):
            raise ModelSchemaError(f"the model repeats animation name {clip_name!r}")
        clips.append(AnimationClipData(
            index=index, name=clip_name, duration=duration,
            samplers=tuple(samplers_out), channels=tuple(channels_out),
            keyframes=sum(len(sampler.input_times) for sampler in samplers_out),
        ))

    estimated = (
        sum(primitive.byte_length for primitive in primitives)
        + decoded_total
        + len(joints) * 64
    )
    if estimated > limits.maximum_gpu_bytes:
        raise ModelLimitError(
            f"the model would need about {estimated} bytes of GPU memory; the limit is "
            f"{limits.maximum_gpu_bytes}"
        )

    return ValidatedModel(
        digest=digest,
        file_bytes=len(data),
        gltf_version=SUPPORTED_GLTF_VERSION,
        generator=generator,
        nodes=tuple(nodes),
        root_nodes=roots,
        primitives=tuple(primitives),
        joints=joints,
        inverse_bind_matrices=inverse_bind,
        skeleton=skeleton,
        clips=tuple(clips),
        textures=tuple(textures),
        materials=materials,
        morph_target_names=morph_names or tuple(
            target.name for target in (primitives[0].morph_targets if primitives else ())
        ),
        bounds=bounds,
        vertex_count=total_vertices,
        triangle_count=total_triangles,
        keyframe_count=total_keyframes,
        decoded_texture_bytes=decoded_total,
        estimated_gpu_bytes=estimated,
        ancestry_notes=notes,
        ignored_extensions=tuple(sorted(ignored)),
        limits=limits,
    )


__all__ = [
    "AnimationChannelData",
    "AnimationClipData",
    "AnimationSamplerData",
    "MaterialData",
    "ModelBounds",
    "MorphTargetData",
    "NodeData",
    "PrimitiveData",
    "TextureData",
    "ValidatedModel",
    "VertexStream",
    "parse_glb",
    "validate_glb",
]
