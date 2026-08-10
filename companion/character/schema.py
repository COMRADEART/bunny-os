# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Versioned, strict data contract for Bunny character packages."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath
import re
from typing import Any, Mapping, Sequence

from . import CHARACTER_PACKAGE_SCHEMA_VERSION, CHARACTER_RENDERER_API_VERSION
from .errors import CharacterSchemaError, CharacterSecurityError

REQUIRED_CHARACTER_STATES = (
    "unavailable", "starting", "idle", "greeting", "listening", "transcribing",
    "understanding", "waiting_for_user", "waiting_for_approval", "planning",
    "working", "researching", "typing", "reviewing", "speaking",
    "presenting_result", "success", "warning", "blocked", "degraded", "error",
    "paused", "cancelled", "disconnected", "sleeping", "moving", "repositioning",
)
GENERIC_MOUTH_SHAPES = (
    "closed", "open-small", "open-medium", "open-wide", "rounded", "smile", "neutral",
)
IMPLEMENTED_PRESENTATIONS = ("static-image", "animated-2d")
RESERVED_PRESENTATIONS = (
    "sprite-sheet", "vector-animation", "skeletal-2d", "lightweight-3d",
    "full-3d", "remote-rendered",
)
TRANSITION_TYPES = (
    "immediate", "crossfade", "complete-current", "interruptible",
    "non-interruptible", "queue-next", "return-to-idle",
)
MAX_ASSET_BYTES = 64 * 1024 * 1024
MAX_PACKAGE_BYTES = 256 * 1024 * 1024
MAX_PACKAGE_FILES = 512
MAX_ANIMATION_FRAMES = 240
MAX_MEMORY_ESTIMATE_BYTES = 512 * 1024 * 1024
MAX_FRAME_RATE = 60.0

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_VERSION = re.compile(r"^[0-9]+(?:\.[0-9]+){1,3}(?:[-+][A-Za-z0-9.-]+)?$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SENSITIVE = re.compile(r"(?i)(api.?key|authorization|credential|password|private.?key|secret|token)")
_CREDENTIAL_VALUE = re.compile(
    r"(?i)(?:-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"(?:bearer\s+|sk-|gh[pousr]_|AKIA)[A-Za-z0-9._=+/-]{12,}|"
    r"(?:api.?key|token|password|secret)\s*[:=]\s*[^\s,;]{8,})"
)
_MANIFEST_FIELDS = frozenset({
    "schemaVersion", "packageId", "characterId", "characterName", "packageVersion",
    "creator", "license", "copyright", "licenseAsset", "supportedRendererVersions",
    "minimumBunnyOsVersion", "presentationType", "assetInventory", "fallbackAsset",
    "thumbnailAsset", "declaredDimensions", "declaredFrameRate", "declaredMemoryEstimateBytes",
    "animations", "stateMap", "expressionMap", "mouthShapeMap", "bubbleAnchor",
    "boundingBox", "safeMargins", "generationProvenance", "sourcePromptMetadata",
})
_ASSET_FIELDS = frozenset({
    "assetId", "path", "mediaType", "sha256", "sizeBytes", "width", "height", "purpose",
})
_ANIMATION_FIELDS = frozenset({"kind", "frames", "loop", "transition", "playbackSpeed"})
_FRAME_FIELDS = frozenset({"assetId", "durationMs"})


class PackagePresentation(str, Enum):
    STATIC_IMAGE = "static-image"
    ANIMATED_2D = "animated-2d"


class PackageTrustState(str, Enum):
    BUILT_IN = "built-in"
    LOCALLY_CREATED = "locally-created"
    IMPORTED_UNVERIFIED = "imported-unverified"
    VERIFIED_INTEGRITY = "verified-integrity"
    DISABLED = "disabled"
    QUARANTINED = "quarantined"
    INCOMPATIBLE = "incompatible"
    CORRUPT = "corrupt"


def _object(value: Any, name: str, fields: frozenset[str] | None = None) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CharacterSchemaError(f"{name} must be an object")
    if fields is not None:
        extra = set(map(str, value)).difference(fields)
        if extra:
            raise CharacterSchemaError(f"{name} contains unsupported fields: {', '.join(sorted(extra))}")
    return value


def _text(value: Any, name: str, *, maximum: int = 512, required: bool = True) -> str:
    if not isinstance(value, str):
        raise CharacterSchemaError(f"{name} must be text")
    if required and not value.strip():
        raise CharacterSchemaError(f"{name} is required")
    if len(value) > maximum or "\x00" in value:
        raise CharacterSchemaError(f"{name} exceeds its text limit")
    return value


def _identifier(value: Any, name: str) -> str:
    text = _text(value, name, maximum=128)
    if _IDENTIFIER.fullmatch(text) is None:
        raise CharacterSchemaError(f"{name} is not a safe identifier")
    return text


def _version(value: Any, name: str) -> str:
    text = _text(value, name, maximum=64)
    if _VERSION.fullmatch(text) is None:
        raise CharacterSchemaError(f"{name} is not a supported version string")
    return text


def safe_package_path(value: Any, name: str = "asset path") -> str:
    text = _text(value, name, maximum=240)
    if "\\" in text or "://" in text:
        raise CharacterSecurityError(f"{name} is not package-relative")
    path = PurePosixPath(text)
    if path.is_absolute() or path.drive or any(part in {"", ".", ".."} for part in path.parts):
        raise CharacterSecurityError(f"{name} escapes the package root")
    if ":" in path.parts[0] or len(path.parts) > 16:
        raise CharacterSecurityError(f"{name} is not package-relative")
    suffix = path.suffix.casefold()
    executable = {
        ".app", ".bat", ".cmd", ".com", ".desktop", ".dll", ".dylib", ".exe",
        ".html", ".htm", ".jar", ".js", ".mjs", ".msi", ".ps1", ".py", ".pyc",
        ".sh", ".so", ".svg", ".vbs", ".wasm", ".xml",
    }
    if suffix in executable:
        raise CharacterSecurityError(f"executable or active asset type is forbidden: {suffix}")
    if suffix not in {".png", ".webp", ".txt", ".md", ".json"}:
        raise CharacterSecurityError(f"unsupported data asset type: {suffix or '[none]'}")
    return path.as_posix()


def _bounded_metadata(value: Any, name: str, *, depth: int = 0) -> None:
    if depth > 8:
        raise CharacterSchemaError(f"{name} is nested too deeply")
    if isinstance(value, Mapping):
        if len(value) > 128:
            raise CharacterSchemaError(f"{name} contains too many fields")
        for key, child in value.items():
            key_text = _text(str(key), f"{name} key", maximum=128)
            if _SENSITIVE.search(key_text):
                raise CharacterSecurityError(f"credentials are forbidden in {name}.{key_text}")
            _bounded_metadata(child, f"{name}.{key_text}", depth=depth + 1)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if len(value) > 256:
            raise CharacterSchemaError(f"{name} contains too many items")
        for index, child in enumerate(value):
            _bounded_metadata(child, f"{name}[{index}]", depth=depth + 1)
    elif isinstance(value, str):
        _text(value, name, maximum=4096, required=False)
        if _CREDENTIAL_VALUE.search(value):
            raise CharacterSecurityError(f"credential-like content is forbidden in {name}")
    elif value is not None and not isinstance(value, (bool, int, float)):
        raise CharacterSchemaError(f"{name} contains a value that JSON cannot represent safely")


@dataclass(frozen=True)
class AssetRecord:
    asset_id: str
    path: str
    media_type: str
    sha256: str
    size_bytes: int
    width: int = 0
    height: int = 0
    purpose: str = "render"

    @classmethod
    def from_json(cls, value: Any) -> "AssetRecord":
        item = _object(value, "asset inventory item", _ASSET_FIELDS)
        asset_id = _identifier(item.get("assetId"), "assetId")
        path = safe_package_path(item.get("path"))
        media_type = _text(item.get("mediaType"), "asset mediaType", maximum=128)
        suffix = PurePosixPath(path).suffix.casefold()
        expected = {".png": "image/png", ".webp": "image/webp", ".txt": "text/plain", ".md": "text/markdown", ".json": "application/json"}[suffix]
        if media_type != expected:
            raise CharacterSchemaError(f"asset {asset_id!r} mediaType does not match {suffix}")
        digest = _text(item.get("sha256"), "asset sha256", maximum=64)
        if _SHA256.fullmatch(digest) is None:
            raise CharacterSchemaError("asset sha256 must be lowercase SHA-256")
        size = item.get("sizeBytes")
        if not isinstance(size, int) or isinstance(size, bool) or not 0 < size <= MAX_ASSET_BYTES:
            raise CharacterSchemaError("asset sizeBytes is outside the package limit")
        width = item.get("width", 0)
        height = item.get("height", 0)
        if not isinstance(width, int) or isinstance(width, bool) or width < 0:
            raise CharacterSchemaError("asset width is invalid")
        if not isinstance(height, int) or isinstance(height, bool) or height < 0:
            raise CharacterSchemaError("asset height is invalid")
        if media_type.startswith("image/") and (width <= 0 or height <= 0):
            raise CharacterSchemaError("image assets must declare positive width and height")
        if not media_type.startswith("image/") and (width or height):
            raise CharacterSchemaError("metadata assets cannot declare image dimensions")
        purpose = _text(item.get("purpose", "render"), "asset purpose", maximum=64)
        if purpose not in {"render", "thumbnail", "license", "metadata"}:
            raise CharacterSchemaError("asset purpose is unsupported")
        if purpose == "render" and not media_type.startswith("image/"):
            raise CharacterSchemaError("render assets must be raster images")
        return cls(asset_id, path, media_type, digest, size, width, height, purpose)

    def to_json(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "assetId": self.asset_id, "path": self.path, "mediaType": self.media_type,
            "sha256": self.sha256, "sizeBytes": self.size_bytes, "purpose": self.purpose,
        }
        if self.width:
            value["width"] = self.width
            value["height"] = self.height
        return value


@dataclass(frozen=True)
class FrameSpec:
    asset_id: str
    duration_ms: int

    @classmethod
    def from_json(cls, value: Any) -> "FrameSpec":
        item = _object(value, "animation frame", _FRAME_FIELDS)
        duration = item.get("durationMs")
        if not isinstance(duration, int) or isinstance(duration, bool) or not 16 <= duration <= 10_000:
            raise CharacterSchemaError("frame durationMs must be between 16 and 10000")
        return cls(_identifier(item.get("assetId"), "frame assetId"), duration)

    def to_json(self) -> dict[str, Any]:
        return {"assetId": self.asset_id, "durationMs": self.duration_ms}


@dataclass(frozen=True)
class AnimationSpec:
    name: str
    kind: str
    frames: tuple[FrameSpec, ...]
    loop: bool
    transition: str
    playback_speed: float = 1.0

    @classmethod
    def from_json(cls, name: str, value: Any) -> "AnimationSpec":
        item = _object(value, f"animation {name}", _ANIMATION_FIELDS)
        kind = item.get("kind")
        if kind not in {"static", "frame-sequence"}:
            raise CharacterSchemaError(f"animation {name!r} kind is not implemented")
        raw_frames = item.get("frames")
        if not isinstance(raw_frames, list) or not raw_frames or len(raw_frames) > MAX_ANIMATION_FRAMES:
            raise CharacterSchemaError(f"animation {name!r} has an invalid frame list")
        frames = tuple(FrameSpec.from_json(frame) for frame in raw_frames)
        if kind == "static" and len(frames) != 1:
            raise CharacterSchemaError("static animations contain exactly one frame")
        if sum(frame.duration_ms for frame in frames) > 120_000:
            raise CharacterSchemaError("animation duration exceeds two minutes")
        loop = item.get("loop")
        if not isinstance(loop, bool):
            raise CharacterSchemaError("animation loop must be boolean")
        transition = item.get("transition")
        if transition not in TRANSITION_TYPES:
            raise CharacterSchemaError("animation transition is unsupported")
        if loop and transition in {
            "complete-current", "non-interruptible", "queue-next", "return-to-idle"
        }:
            raise CharacterSchemaError(
                "a looping animation cannot use a completion-dependent transition"
            )
        speed = item.get("playbackSpeed", 1.0)
        if not isinstance(speed, (int, float)) or isinstance(speed, bool) or not 0.25 <= float(speed) <= 4.0:
            raise CharacterSchemaError("animation playbackSpeed must be between 0.25 and 4")
        return cls(_identifier(name, "animation name"), str(kind), frames, loop, str(transition), float(speed))

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "frames": [frame.to_json() for frame in self.frames],
            "loop": self.loop,
            "transition": self.transition,
            "playbackSpeed": self.playback_speed,
        }


@dataclass(frozen=True)
class NormalizedRect:
    x: float
    y: float
    width: float
    height: float

    @classmethod
    def from_json(cls, value: Any, name: str) -> "NormalizedRect":
        item = _object(value, name, frozenset({"x", "y", "width", "height"}))
        numbers = []
        for field in ("x", "y", "width", "height"):
            number = item.get(field)
            if not isinstance(number, (int, float)) or isinstance(number, bool):
                raise CharacterSchemaError(f"{name}.{field} must be numeric")
            numbers.append(float(number))
        result = cls(*numbers)
        if result.x < 0 or result.y < 0 or result.width <= 0 or result.height <= 0:
            raise CharacterSchemaError(f"{name} has invalid normalized dimensions")
        if result.x + result.width > 1 or result.y + result.height > 1:
            raise CharacterSchemaError(f"{name} extends outside the character canvas")
        return result

    def to_json(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}


@dataclass(frozen=True)
class BubbleAnchor:
    x: float
    y: float
    preferred_side: str

    @classmethod
    def from_json(cls, value: Any) -> "BubbleAnchor":
        item = _object(value, "bubbleAnchor", frozenset({"x", "y", "preferredSide"}))
        x, y = item.get("x"), item.get("y")
        if not isinstance(x, (int, float)) or isinstance(x, bool) or not 0 <= float(x) <= 1:
            raise CharacterSchemaError("bubbleAnchor.x must be normalized")
        if not isinstance(y, (int, float)) or isinstance(y, bool) or not 0 <= float(y) <= 1:
            raise CharacterSchemaError("bubbleAnchor.y must be normalized")
        side = item.get("preferredSide")
        if side not in {"auto", "left", "right", "above", "below"}:
            raise CharacterSchemaError("bubbleAnchor.preferredSide is invalid")
        return cls(float(x), float(y), str(side))

    def to_json(self) -> dict[str, Any]:
        return {"x": self.x, "y": self.y, "preferredSide": self.preferred_side}


@dataclass(frozen=True)
class SafeMargins:
    top: float
    right: float
    bottom: float
    left: float

    @classmethod
    def from_json(cls, value: Any) -> "SafeMargins":
        item = _object(value, "safeMargins", frozenset({"top", "right", "bottom", "left"}))
        numbers: list[float] = []
        for field in ("top", "right", "bottom", "left"):
            number = item.get(field)
            if not isinstance(number, (int, float)) or isinstance(number, bool) or not 0 <= float(number) <= 0.5:
                raise CharacterSchemaError(f"safeMargins.{field} must be between 0 and 0.5")
            numbers.append(float(number))
        return cls(*numbers)

    def to_json(self) -> dict[str, float]:
        return {"top": self.top, "right": self.right, "bottom": self.bottom, "left": self.left}


@dataclass(frozen=True)
class CharacterManifest:
    package_id: str
    character_id: str
    character_name: str
    package_version: str
    creator: str
    license: str
    copyright: str
    license_asset: str
    supported_renderer_versions: Mapping[str, str]
    minimum_bunny_os_version: str | None
    presentation_type: PackagePresentation
    assets: tuple[AssetRecord, ...]
    fallback_asset: str
    thumbnail_asset: str
    width: int
    height: int
    frame_rate: float
    memory_estimate_bytes: int
    animations: Mapping[str, AnimationSpec]
    state_map: Mapping[str, str]
    expression_map: Mapping[str, str]
    mouth_shape_map: Mapping[str, str]
    bubble_anchor: BubbleAnchor
    bounding_box: NormalizedRect
    safe_margins: SafeMargins
    generation_provenance: Mapping[str, Any] | None = None
    source_prompt_metadata: Mapping[str, Any] | None = None

    @classmethod
    def from_json(cls, value: Any) -> "CharacterManifest":
        item = _object(value, "character manifest", _MANIFEST_FIELDS)
        required = _MANIFEST_FIELDS.difference({
            "minimumBunnyOsVersion", "generationProvenance", "sourcePromptMetadata",
        })
        missing = sorted(required.difference(map(str, item)))
        if missing:
            raise CharacterSchemaError("character manifest is missing: " + ", ".join(missing))
        if item.get("schemaVersion") != CHARACTER_PACKAGE_SCHEMA_VERSION:
            raise CharacterSchemaError("unsupported character package schemaVersion")
        package_id = _identifier(item.get("packageId"), "packageId")
        character_id = _identifier(item.get("characterId"), "characterId")
        package_version = _version(item.get("packageVersion"), "packageVersion")
        renderer_versions_raw = _object(item.get("supportedRendererVersions"), "supportedRendererVersions")
        if not renderer_versions_raw:
            raise CharacterSchemaError("supportedRendererVersions cannot be empty")
        renderer_versions: dict[str, str] = {}
        allowed_renderers = set(IMPLEMENTED_PRESENTATIONS) | set(RESERVED_PRESENTATIONS)
        for renderer, version in renderer_versions_raw.items():
            if renderer not in allowed_renderers:
                raise CharacterSchemaError(f"unknown renderer contract: {renderer}")
            renderer_versions[str(renderer)] = _version(version, f"renderer version for {renderer}")
        presentation_raw = item.get("presentationType")
        if presentation_raw not in IMPLEMENTED_PRESENTATIONS:
            if presentation_raw in RESERVED_PRESENTATIONS:
                raise CharacterSchemaError(f"{presentation_raw} is reserved but not implemented")
            raise CharacterSchemaError("presentationType is unsupported")
        presentation = PackagePresentation(str(presentation_raw))
        if presentation.value not in renderer_versions:
            raise CharacterSchemaError("package does not declare its selected renderer version")
        if renderer_versions[presentation.value].split(".")[0] != CHARACTER_RENDERER_API_VERSION.split(".")[0]:
            raise CharacterSchemaError("package renderer major version is incompatible")

        raw_assets = item.get("assetInventory")
        if not isinstance(raw_assets, list) or not raw_assets or len(raw_assets) > MAX_PACKAGE_FILES:
            raise CharacterSchemaError("assetInventory is empty or exceeds the file limit")
        assets = tuple(AssetRecord.from_json(asset) for asset in raw_assets)
        asset_ids = {asset.asset_id for asset in assets}
        paths = {asset.path for asset in assets}
        if len(asset_ids) != len(assets) or len(paths) != len(assets):
            raise CharacterSchemaError("asset inventory repeats an id or path")
        if sum(asset.size_bytes for asset in assets) > MAX_PACKAGE_BYTES:
            raise CharacterSchemaError("declared package size exceeds the package limit")

        raw_animations = _object(item.get("animations"), "animations")
        if not raw_animations:
            raise CharacterSchemaError("animations cannot be empty")
        animations = {str(name): AnimationSpec.from_json(str(name), spec) for name, spec in raw_animations.items()}
        for animation in animations.values():
            for frame in animation.frames:
                if frame.asset_id not in asset_ids:
                    raise CharacterSchemaError(f"animation {animation.name!r} references an undeclared asset")
                asset = next(asset for asset in assets if asset.asset_id == frame.asset_id)
                if not asset.media_type.startswith("image/"):
                    raise CharacterSchemaError("animation frames must reference raster images")
        if presentation is PackagePresentation.STATIC_IMAGE and any(animation.kind != "static" for animation in animations.values()):
            raise CharacterSchemaError("static-image packages cannot contain frame-sequence animations")

        state_raw = _object(item.get("stateMap"), "stateMap")
        if "idle" not in state_raw:
            raise CharacterSchemaError("stateMap must define idle")
        state_map: dict[str, str] = {}
        allowed_states = set(REQUIRED_CHARACTER_STATES) | {"thinking", "static_fallback"}
        for state, animation in state_raw.items():
            if state not in allowed_states:
                raise CharacterSchemaError(f"stateMap names an unknown state: {state}")
            animation_name = _identifier(animation, f"animation for {state}")
            if animation_name not in animations:
                raise CharacterSchemaError(f"state {state!r} references a missing animation")
            state_map[str(state)] = animation_name

        def mapped_assets(name: str, allowed_keys: set[str] | None = None) -> dict[str, str]:
            raw = _object(item.get(name), name)
            result: dict[str, str] = {}
            for key, animation in raw.items():
                key_text = _text(str(key), f"{name} key", maximum=64)
                if allowed_keys is not None and key_text not in allowed_keys:
                    raise CharacterSchemaError(f"{name} names an unsupported key: {key_text}")
                animation_name = _identifier(animation, f"{name}.{key_text}")
                if animation_name not in animations:
                    raise CharacterSchemaError(f"{name}.{key_text} references a missing animation")
                result[key_text] = animation_name
            return result

        expression_map = mapped_assets("expressionMap")
        mouth_shape_map = mapped_assets("mouthShapeMap", set(GENERIC_MOUTH_SHAPES))
        fallback = _identifier(item.get("fallbackAsset"), "fallbackAsset")
        thumbnail = _identifier(item.get("thumbnailAsset"), "thumbnailAsset")
        license_asset = _identifier(item.get("licenseAsset"), "licenseAsset")
        by_id = {asset.asset_id: asset for asset in assets}
        for reference, name in ((fallback, "fallbackAsset"), (thumbnail, "thumbnailAsset"), (license_asset, "licenseAsset")):
            if reference not in by_id:
                raise CharacterSchemaError(f"{name} references an undeclared asset")
        if not by_id[fallback].media_type.startswith("image/") or not by_id[thumbnail].media_type.startswith("image/"):
            raise CharacterSchemaError("fallbackAsset and thumbnailAsset must be raster images")
        if by_id[license_asset].media_type not in {"text/plain", "text/markdown"}:
            raise CharacterSchemaError("licenseAsset must be plain text or Markdown")

        dimensions = _object(item.get("declaredDimensions"), "declaredDimensions", frozenset({"width", "height"}))
        width, height = dimensions.get("width"), dimensions.get("height")
        if not isinstance(width, int) or isinstance(width, bool) or not 1 <= width <= 4096:
            raise CharacterSchemaError("declaredDimensions.width is invalid")
        if not isinstance(height, int) or isinstance(height, bool) or not 1 <= height <= 4096:
            raise CharacterSchemaError("declaredDimensions.height is invalid")
        for asset in assets:
            if asset.media_type.startswith("image/") and (asset.width != width or asset.height != height):
                raise CharacterSchemaError("all frame images must use the declared canvas dimensions")
        frame_rate = item.get("declaredFrameRate")
        if not isinstance(frame_rate, (int, float)) or isinstance(frame_rate, bool) or not 1 <= float(frame_rate) <= MAX_FRAME_RATE:
            raise CharacterSchemaError("declaredFrameRate is outside 1-60 fps")
        memory = item.get("declaredMemoryEstimateBytes")
        if not isinstance(memory, int) or isinstance(memory, bool) or not 1 <= memory <= MAX_MEMORY_ESTIMATE_BYTES:
            raise CharacterSchemaError("declaredMemoryEstimateBytes is outside the renderer limit")
        minimum = item.get("minimumBunnyOsVersion")
        minimum_version = _version(minimum, "minimumBunnyOsVersion") if minimum is not None else None
        generation = item.get("generationProvenance")
        prompt = item.get("sourcePromptMetadata")
        if generation is not None:
            generation = dict(_object(generation, "generationProvenance"))
            _bounded_metadata(generation, "generationProvenance")
        if prompt is not None:
            prompt = dict(_object(prompt, "sourcePromptMetadata"))
            _bounded_metadata(prompt, "sourcePromptMetadata")
        return cls(
            package_id=package_id,
            character_id=character_id,
            character_name=_text(item.get("characterName"), "characterName", maximum=256),
            package_version=package_version,
            creator=_text(item.get("creator"), "creator", maximum=256),
            license=_text(item.get("license"), "license", maximum=256),
            copyright=_text(item.get("copyright"), "copyright", maximum=512),
            license_asset=license_asset,
            supported_renderer_versions=renderer_versions,
            minimum_bunny_os_version=minimum_version,
            presentation_type=presentation,
            assets=assets,
            fallback_asset=fallback,
            thumbnail_asset=thumbnail,
            width=width,
            height=height,
            frame_rate=float(frame_rate),
            memory_estimate_bytes=memory,
            animations=animations,
            state_map=state_map,
            expression_map=expression_map,
            mouth_shape_map=mouth_shape_map,
            bubble_anchor=BubbleAnchor.from_json(item.get("bubbleAnchor")),
            bounding_box=NormalizedRect.from_json(item.get("boundingBox"), "boundingBox"),
            safe_margins=SafeMargins.from_json(item.get("safeMargins")),
            generation_provenance=generation,
            source_prompt_metadata=prompt,
        )

    def asset(self, asset_id: str) -> AssetRecord:
        for asset in self.assets:
            if asset.asset_id == asset_id:
                return asset
        raise KeyError(asset_id)

    def animation(self, name: str) -> AnimationSpec:
        try:
            return self.animations[name]
        except KeyError:
            raise CharacterSchemaError(f"package has no animation {name!r}") from None

    def to_json(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "schemaVersion": CHARACTER_PACKAGE_SCHEMA_VERSION,
            "packageId": self.package_id,
            "characterId": self.character_id,
            "characterName": self.character_name,
            "packageVersion": self.package_version,
            "creator": self.creator,
            "license": self.license,
            "copyright": self.copyright,
            "licenseAsset": self.license_asset,
            "supportedRendererVersions": dict(self.supported_renderer_versions),
            "presentationType": self.presentation_type.value,
            "assetInventory": [asset.to_json() for asset in self.assets],
            "fallbackAsset": self.fallback_asset,
            "thumbnailAsset": self.thumbnail_asset,
            "declaredDimensions": {"width": self.width, "height": self.height},
            "declaredFrameRate": self.frame_rate,
            "declaredMemoryEstimateBytes": self.memory_estimate_bytes,
            "animations": {name: animation.to_json() for name, animation in self.animations.items()},
            "stateMap": dict(self.state_map),
            "expressionMap": dict(self.expression_map),
            "mouthShapeMap": dict(self.mouth_shape_map),
            "bubbleAnchor": self.bubble_anchor.to_json(),
            "boundingBox": self.bounding_box.to_json(),
            "safeMargins": self.safe_margins.to_json(),
        }
        if self.minimum_bunny_os_version is not None:
            value["minimumBunnyOsVersion"] = self.minimum_bunny_os_version
        if self.generation_provenance is not None:
            value["generationProvenance"] = dict(self.generation_provenance)
        if self.source_prompt_metadata is not None:
            value["sourcePromptMetadata"] = dict(self.source_prompt_metadata)
        return value
