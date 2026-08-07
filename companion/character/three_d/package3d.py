# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""§5's versioned 3D section of the character package manifest.

A 3D character package is **a 2D character package with a 3D section**, not a
different kind of thing. It carries the same raster inventory, the same
``animations``, the same ``stateMap``, the same ``fallbackAsset`` and the same
accessibility descriptions that a 2D package does — and then a
``threeDimensional`` block describing a GLB beside them.

That is a deliberate structural choice and it is what makes §22's degradation
honest. When a machine drops from ``full-3d`` to ``animated-2d`` there is no
second package to find, validate, decode and swap in: the fallback is already
validated, already declared, already in the same directory, and the renderer
below simply changes. A design where the 2D fallback lived in *another* package
would have made the moment of degradation — the moment the machine is already in
trouble — the moment a second package had to be loaded.

The consequence is stated in :func:`validate_three_d_section` and enforced
there: a package that declares ``full-3d`` and has no working 2D body is
refused. §5's "every 3D package must retain a static fallback" is not a
recommendation here, it is a validation rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from companion.character.errors import CharacterSchemaError, CharacterSecurityError
from companion.character.schema import (
    _identifier,
    _object,
    _text,
    safe_package_path,
)

from . import THREE_D_PACKAGE_SCHEMA_VERSION, THREE_D_RENDERER_API_VERSION
from .animation import ANIMATION_STATES
from .face import EXPRESSIONS, MOUTH_OPENNESS
from .limits import DEFAULT_LIMITS, ModelLimits
from .skeleton import OPTIONAL_BONES, REQUIRED_BONES

_SECTION_FIELDS = frozenset({
    "schemaVersion", "rendererApiVersion", "modelFile", "modelDigest", "modelSizeBytes",
    "gltfVersion", "skeletonProfile", "boneMap", "rootBone", "headBone", "neckBone",
    "eyeBones", "handBones", "animationMap", "expressionMap", "visemeMap",
    "morphTargets", "textureInventory", "materialInventory", "modelBounds",
    "nativeScale", "floorOffset", "bubbleAnchor", "cameraAnchor",
    "maximumTriangles", "maximumVertices", "maximumJoints", "maximumMorphTargets",
    "maximumTextures", "maximumTextureDimensions", "declaredGpuBytes",
    "declaredDecodedBytes", "requiredRendererFeatures", "staticFallbackAsset",
    "animatedFallbackState", "accessibilityStates", "previewAsset",
})

#: Renderer features a package may require. Closed: a package that requires a
#: feature this build does not know is refused rather than loaded and then found
#: to look wrong.
RENDERER_FEATURES: frozenset[str] = frozenset({
    "skeletal-animation",
    "morph-targets",
    "alpha-blending",
    "double-sided",
    "vertex-colours",
    "base-colour-texture",
    "unlit-materials",
})

#: The animation states a package must map. Everything else may fall back
#: through :data:`companion.character.three_d.animation.CANDIDATES`, but these
#: four have no candidate above them and a package without them cannot draw a
#: task at all.
MANDATORY_ANIMATION_STATES: tuple[str, ...] = ("idle", "working", "speaking", "error")

_SHA256_LENGTH = 64


def _positive_int(value: Any, name: str, *, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise CharacterSchemaError(f"{name} must be a positive integer")
    if value > maximum:
        raise CharacterSchemaError(f"{name} exceeds the renderer ceiling of {maximum}")
    return value


def _number(value: Any, name: str, *, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CharacterSchemaError(f"{name} must be a number")
    number = float(value)
    if not low <= number <= high:
        raise CharacterSchemaError(f"{name} must be between {low} and {high}")
    return number


def _weight_map(value: Any, name: str, allowed_keys: Sequence[str]) -> dict[str, dict[str, float]]:
    raw = _object(value, name)
    permitted = set(allowed_keys)
    result: dict[str, dict[str, float]] = {}
    for key, mapping in raw.items():
        key_text = _text(str(key), f"{name} key", maximum=64)
        if key_text not in permitted:
            raise CharacterSchemaError(f"{name} names an unsupported key: {key_text}")
        targets = _object(mapping, f"{name}.{key_text}")
        if len(targets) > 16:
            raise CharacterSchemaError(f"{name}.{key_text} drives too many morph targets")
        weights: dict[str, float] = {}
        for target, weight in targets.items():
            target_name = _identifier(target, f"{name}.{key_text} target")
            weights[target_name] = _number(weight, f"{name}.{key_text}.{target_name}", low=0.0, high=1.0)
        result[key_text] = weights
    return result


@dataclass(frozen=True)
class ThreeDSection:
    """One package's declared 3D body. Every field is bounded before it exists."""

    schema_version: int
    renderer_api_version: str
    model_file: str
    model_digest: str
    model_size_bytes: int
    gltf_version: str
    skeleton_profile: str
    bone_map: Mapping[str, str]
    animation_map: Mapping[str, str]
    expression_map: Mapping[str, Mapping[str, float]]
    viseme_map: Mapping[str, Mapping[str, float]]
    morph_targets: tuple[str, ...]
    texture_inventory: tuple[Mapping[str, Any], ...]
    material_inventory: tuple[str, ...]
    model_bounds: Mapping[str, Sequence[float]]
    native_scale: float
    floor_offset: float
    bubble_anchor: tuple[float, float, float]
    camera_anchor: tuple[float, float, float]
    maximum_triangles: int
    maximum_vertices: int
    maximum_joints: int
    maximum_morph_targets: int
    maximum_textures: int
    maximum_texture_dimensions: int
    declared_gpu_bytes: int
    declared_decoded_bytes: int
    required_renderer_features: tuple[str, ...]
    static_fallback_asset: str
    animated_fallback_state: str
    preview_asset: str
    accessibility_states: Mapping[str, str]

    def limits(self) -> ModelLimits:
        """The package's own declaration, as validator limits.

        A package may only ever make the validator *stricter*:
        :class:`ModelLimits` clamps each field to the build's hard ceiling, so a
        manifest claiming a million triangles gets the build's number and the
        model is refused against that.
        """
        return ModelLimits(
            maximum_triangles=self.maximum_triangles,
            maximum_vertices=self.maximum_vertices,
            maximum_joints=self.maximum_joints,
            maximum_morph_targets=self.maximum_morph_targets,
            maximum_textures=self.maximum_textures,
            maximum_texture_dimension=self.maximum_texture_dimensions,
            maximum_decoded_texture_bytes=self.declared_decoded_bytes,
            maximum_gpu_bytes=self.declared_gpu_bytes,
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "rendererApiVersion": self.renderer_api_version,
            "modelFile": self.model_file,
            "modelDigest": self.model_digest,
            "modelSizeBytes": self.model_size_bytes,
            "gltfVersion": self.gltf_version,
            "skeletonProfile": self.skeleton_profile,
            "boneMap": dict(self.bone_map),
            "animationMap": dict(self.animation_map),
            "expressionMap": {key: dict(value) for key, value in self.expression_map.items()},
            "visemeMap": {key: dict(value) for key, value in self.viseme_map.items()},
            "morphTargets": list(self.morph_targets),
            "textureInventory": [dict(item) for item in self.texture_inventory],
            "materialInventory": list(self.material_inventory),
            "modelBounds": {key: list(value) for key, value in self.model_bounds.items()},
            "nativeScale": self.native_scale,
            "floorOffset": self.floor_offset,
            "bubbleAnchor": list(self.bubble_anchor),
            "cameraAnchor": list(self.camera_anchor),
            "maximumTriangles": self.maximum_triangles,
            "maximumVertices": self.maximum_vertices,
            "maximumJoints": self.maximum_joints,
            "maximumMorphTargets": self.maximum_morph_targets,
            "maximumTextures": self.maximum_textures,
            "maximumTextureDimensions": self.maximum_texture_dimensions,
            "declaredGpuBytes": self.declared_gpu_bytes,
            "declaredDecodedBytes": self.declared_decoded_bytes,
            "requiredRendererFeatures": list(self.required_renderer_features),
            "staticFallbackAsset": self.static_fallback_asset,
            "animatedFallbackState": self.animated_fallback_state,
            "previewAsset": self.preview_asset,
            "accessibilityStates": dict(self.accessibility_states),
        }

    @classmethod
    def from_json(cls, value: Any) -> "ThreeDSection":
        item = _object(value, "threeDimensional", _SECTION_FIELDS)
        missing = sorted(_SECTION_FIELDS.difference({"boneMap", "previewAsset"}).difference(map(str, item)))
        if missing:
            raise CharacterSchemaError("threeDimensional is missing: " + ", ".join(missing))
        schema_version = item.get("schemaVersion")
        if schema_version != THREE_D_PACKAGE_SCHEMA_VERSION:
            raise CharacterSchemaError("unsupported threeDimensional schemaVersion")
        renderer_api = _text(item.get("rendererApiVersion"), "rendererApiVersion", maximum=32)
        if renderer_api.split(".")[0] != THREE_D_RENDERER_API_VERSION.split(".")[0]:
            raise CharacterSchemaError("threeDimensional rendererApiVersion major differs from this build")

        model_file = safe_package_path(item.get("modelFile"), "modelFile")
        if not model_file.casefold().endswith(".glb"):
            raise CharacterSecurityError("modelFile must be a .glb")
        digest = _text(item.get("modelDigest"), "modelDigest", maximum=_SHA256_LENGTH)
        if len(digest) != _SHA256_LENGTH or any(character not in "0123456789abcdef" for character in digest):
            raise CharacterSchemaError("modelDigest must be a lowercase SHA-256")
        size = _positive_int(item.get("modelSizeBytes"), "modelSizeBytes", maximum=DEFAULT_LIMITS.maximum_file_bytes)
        gltf_version = _text(item.get("gltfVersion"), "gltfVersion", maximum=16)
        if gltf_version != "2.0":
            raise CharacterSchemaError("only glTF 2.0 is supported")

        skeleton_profile = _text(item.get("skeletonProfile"), "skeletonProfile", maximum=64)
        if skeleton_profile != "bunny-humanoid-1":
            raise CharacterSchemaError("skeletonProfile is not a profile this build implements")

        bone_map_raw = _object(item.get("boneMap", {}), "boneMap")
        bone_map: dict[str, str] = {}
        for logical, node in bone_map_raw.items():
            logical_name = _text(str(logical), "boneMap key", maximum=64)
            bone_map[logical_name] = _text(node, f"boneMap.{logical_name}", maximum=128)
        # The four §5 names singly, so a manifest states them explicitly and a
        # reader does not have to search a map for the head.
        for field, logical in (
            ("rootBone", "root"), ("headBone", "head"), ("neckBone", "neck"),
        ):
            bone_map[logical] = _text(item.get(field), field, maximum=128)
        for field, names in (("eyeBones", ("left_eye", "right_eye")), ("handBones", ("left_hand", "right_hand"))):
            declared = item.get(field)
            if not isinstance(declared, list) or len(declared) not in (0, 2):
                raise CharacterSchemaError(f"{field} must be a list of two node names, or empty")
            for logical, node in zip(names, declared):
                bone_map[logical] = _text(node, f"{field}.{logical}", maximum=128)
        for logical in bone_map:
            if logical not in REQUIRED_BONES and logical not in OPTIONAL_BONES:
                raise CharacterSchemaError(f"boneMap names an unknown logical bone: {logical}")

        animation_raw = _object(item.get("animationMap"), "animationMap")
        animation_map: dict[str, str] = {}
        for state, clip in animation_raw.items():
            state_name = _text(str(state), "animationMap key", maximum=64)
            if state_name not in ANIMATION_STATES:
                raise CharacterSchemaError(f"animationMap names an unknown animation state: {state_name}")
            animation_map[state_name] = _text(clip, f"animationMap.{state_name}", maximum=128)
        absent = [name for name in MANDATORY_ANIMATION_STATES if name not in animation_map]
        if absent:
            raise CharacterSchemaError("animationMap must define: " + ", ".join(absent))

        expression_map = _weight_map(item.get("expressionMap"), "expressionMap", EXPRESSIONS)
        viseme_map = _weight_map(item.get("visemeMap"), "visemeMap", tuple(MOUTH_OPENNESS))

        morph_raw = item.get("morphTargets")
        if not isinstance(morph_raw, list) or len(morph_raw) > DEFAULT_LIMITS.maximum_morph_targets:
            raise CharacterSchemaError("morphTargets must be a bounded list")
        morph_targets = tuple(_identifier(name, "morphTargets entry") for name in morph_raw)
        if len(set(morph_targets)) != len(morph_targets):
            raise CharacterSchemaError("morphTargets repeats a name")
        for label, mapping in (("expressionMap", expression_map), ("visemeMap", viseme_map)):
            for key, weights in mapping.items():
                for target in weights:
                    if target not in morph_targets:
                        raise CharacterSchemaError(
                            f"{label}.{key} names morph target {target!r} which morphTargets does not declare"
                        )

        texture_raw = item.get("textureInventory")
        if not isinstance(texture_raw, list) or len(texture_raw) > DEFAULT_LIMITS.maximum_textures:
            raise CharacterSchemaError("textureInventory must be a bounded list")
        textures: list[Mapping[str, Any]] = []
        for index, entry in enumerate(texture_raw):
            texture = _object(entry, f"textureInventory[{index}]", frozenset({"name", "width", "height", "mediaType"}))
            media = _text(texture.get("mediaType"), "texture mediaType", maximum=64)
            if media != "image/png":
                raise CharacterSecurityError("only PNG textures are decoded by this renderer")
            textures.append({
                "name": _text(texture.get("name"), "texture name", maximum=128),
                "width": _positive_int(texture.get("width"), "texture width", maximum=DEFAULT_LIMITS.maximum_texture_dimension),
                "height": _positive_int(texture.get("height"), "texture height", maximum=DEFAULT_LIMITS.maximum_texture_dimension),
                "mediaType": media,
            })

        material_raw = item.get("materialInventory")
        if not isinstance(material_raw, list) or not material_raw or len(material_raw) > DEFAULT_LIMITS.maximum_materials:
            raise CharacterSchemaError("materialInventory must be a bounded non-empty list")
        materials = tuple(_text(name, "materialInventory entry", maximum=128) for name in material_raw)

        bounds_raw = _object(item.get("modelBounds"), "modelBounds", frozenset({"min", "max"}))
        bounds: dict[str, Sequence[float]] = {}
        for key in ("min", "max"):
            values = bounds_raw.get(key)
            if not isinstance(values, list) or len(values) != 3:
                raise CharacterSchemaError(f"modelBounds.{key} must have three components")
            bounds[key] = [
                _number(value, f"modelBounds.{key}", low=-1000.0, high=1000.0) for value in values
            ]
        if any(low >= high for low, high in zip(bounds["min"], bounds["max"])):
            raise CharacterSchemaError("modelBounds.min is not strictly below modelBounds.max")

        def _anchor(field: str) -> tuple[float, float, float]:
            values = item.get(field)
            if not isinstance(values, list) or len(values) != 3:
                raise CharacterSchemaError(f"{field} must have three components")
            return tuple(  # type: ignore[return-value]
                _number(value, field, low=-100.0, high=100.0) for value in values
            )

        features_raw = item.get("requiredRendererFeatures")
        if not isinstance(features_raw, list) or len(features_raw) > 16:
            raise CharacterSchemaError("requiredRendererFeatures must be a bounded list")
        features = tuple(_text(name, "requiredRendererFeatures entry", maximum=64) for name in features_raw)
        unknown = sorted(set(features).difference(RENDERER_FEATURES))
        if unknown:
            raise CharacterSchemaError(
                "requiredRendererFeatures names features this renderer does not implement: "
                + ", ".join(unknown)
            )

        accessibility_raw = _object(item.get("accessibilityStates"), "accessibilityStates")
        accessibility: dict[str, str] = {}
        for state, description in accessibility_raw.items():
            state_name = _text(str(state), "accessibilityStates key", maximum=64)
            if state_name not in ANIMATION_STATES:
                raise CharacterSchemaError(f"accessibilityStates names an unknown state: {state_name}")
            accessibility[state_name] = _text(description, f"accessibilityStates.{state_name}", maximum=240)
        missing_descriptions = [name for name in animation_map if name not in accessibility]
        if missing_descriptions:
            raise CharacterSchemaError(
                "accessibilityStates must describe every mapped animation state; missing: "
                + ", ".join(sorted(missing_descriptions))
            )

        animated_fallback = _text(item.get("animatedFallbackState"), "animatedFallbackState", maximum=64)
        return cls(
            schema_version=int(schema_version),
            renderer_api_version=renderer_api,
            model_file=model_file,
            model_digest=digest,
            model_size_bytes=size,
            gltf_version=gltf_version,
            skeleton_profile=skeleton_profile,
            bone_map=bone_map,
            animation_map=animation_map,
            expression_map=expression_map,
            viseme_map=viseme_map,
            morph_targets=morph_targets,
            texture_inventory=tuple(textures),
            material_inventory=materials,
            model_bounds=bounds,
            native_scale=_number(item.get("nativeScale"), "nativeScale", low=0.01, high=100.0),
            floor_offset=_number(item.get("floorOffset"), "floorOffset", low=-10.0, high=10.0),
            bubble_anchor=_anchor("bubbleAnchor"),
            camera_anchor=_anchor("cameraAnchor"),
            maximum_triangles=_positive_int(item.get("maximumTriangles"), "maximumTriangles", maximum=DEFAULT_LIMITS.maximum_triangles),
            maximum_vertices=_positive_int(item.get("maximumVertices"), "maximumVertices", maximum=DEFAULT_LIMITS.maximum_vertices),
            maximum_joints=_positive_int(item.get("maximumJoints"), "maximumJoints", maximum=DEFAULT_LIMITS.maximum_joints),
            maximum_morph_targets=_positive_int(item.get("maximumMorphTargets"), "maximumMorphTargets", maximum=DEFAULT_LIMITS.maximum_morph_targets),
            maximum_textures=_positive_int(item.get("maximumTextures"), "maximumTextures", maximum=DEFAULT_LIMITS.maximum_textures),
            maximum_texture_dimensions=_positive_int(item.get("maximumTextureDimensions"), "maximumTextureDimensions", maximum=DEFAULT_LIMITS.maximum_texture_dimension),
            declared_gpu_bytes=_positive_int(item.get("declaredGpuBytes"), "declaredGpuBytes", maximum=DEFAULT_LIMITS.maximum_gpu_bytes),
            declared_decoded_bytes=_positive_int(item.get("declaredDecodedBytes"), "declaredDecodedBytes", maximum=DEFAULT_LIMITS.maximum_decoded_texture_bytes),
            required_renderer_features=features,
            static_fallback_asset=_identifier(item.get("staticFallbackAsset"), "staticFallbackAsset"),
            animated_fallback_state=animated_fallback,
            preview_asset=_identifier(item.get("previewAsset", item.get("staticFallbackAsset")), "previewAsset"),
            accessibility_states=accessibility,
        )


__all__ = [
    "MANDATORY_ANIMATION_STATES",
    "RENDERER_FEATURES",
    "ThreeDSection",
]
