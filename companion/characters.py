# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Data-only Bunny character package schema and hostile-input validation."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
from typing import Any, Mapping
import zipfile

from . import CHARACTER_PACKAGE_SCHEMA_VERSION
from .model import bounded_text, safe_identifier

REQUIRED_ANIMATIONS = (
    "idle",
    "greeting",
    "listening",
    "thinking",
    "planning",
    "typing",
    "researching",
    "speaking",
    "presenting",
    "success",
    "warning",
    "error",
    "waiting",
    "sleeping",
    "repositioning",
)
SUPPORTED_RENDERERS = {"static-image", "animated-2d", "lightweight-3d", "full-3d"}
ALLOWED_ASSET_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".webp", ".gif",
    ".glb", ".gltf", ".bin", ".json", ".wav", ".ogg",
}
EXECUTABLE_SUFFIXES = {
    ".app", ".bat", ".cmd", ".com", ".desktop", ".dll", ".dylib",
    ".exe", ".jar", ".js", ".mjs", ".msi", ".ps1", ".py", ".pyc",
    ".sh", ".so", ".vbs", ".wasm",
}
MAX_ASSET_BYTES = 64 * 1024 * 1024
MAX_PACKAGE_BYTES = 256 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 512
MAX_COMPRESSION_RATIO = 200
MAX_DECLARED_MEMORY_BYTES = 16 * 1024 * 1024 * 1024
MAX_DECLARED_VRAM_BYTES = 16 * 1024 * 1024 * 1024

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SENSITIVE_METADATA = re.compile(r"(?i)(api.?key|authorization|credential|password|private.?key|secret|token)")


class CharacterPackageError(ValueError):
    pass


def _asset_path(value: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise CharacterPackageError("asset path is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts or len(path.parts) > 16:
        raise CharacterPackageError(f"asset path escapes the package: {value!r}")
    if ":" in path.parts[0]:
        raise CharacterPackageError("drive-qualified asset paths are forbidden")
    suffix = path.suffix.casefold()
    if suffix in EXECUTABLE_SUFFIXES or suffix not in ALLOWED_ASSET_SUFFIXES:
        raise CharacterPackageError(f"asset type is not data-only: {suffix or '[none]'}")
    return path


def _no_sensitive_metadata(value: Any, *, path: str = "metadata", depth: int = 0) -> None:
    if depth > 8:
        raise CharacterPackageError(f"{path} is nested too deeply")
    if isinstance(value, Mapping):
        for key, item in value.items():
            text = str(key)
            if _SENSITIVE_METADATA.search(text):
                raise CharacterPackageError(f"provider credentials are forbidden in {path}.{text}")
            _no_sensitive_metadata(item, path=f"{path}.{text}", depth=depth + 1)
    elif isinstance(value, list):
        if len(value) > 256:
            raise CharacterPackageError(f"{path} contains too many items")
        for index, item in enumerate(value):
            _no_sensitive_metadata(item, path=f"{path}[{index}]", depth=depth + 1)
    elif isinstance(value, str) and len(value) > 4096:
        raise CharacterPackageError(f"{path} contains oversized text")


@dataclass(frozen=True)
class CharacterAsset:
    path: str
    sha256: str
    size_bytes: int
    media_type: str

    def __post_init__(self) -> None:
        _asset_path(self.path)
        if _SHA256.fullmatch(self.sha256) is None:
            raise CharacterPackageError("asset hash must be lowercase SHA-256")
        if not 0 < self.size_bytes <= MAX_ASSET_BYTES:
            raise CharacterPackageError("asset size is outside the package limit")
        bounded_text(self.media_type, "asset media type", 128)

    def to_json(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "sizeBytes": self.size_bytes,
            "mediaType": self.media_type,
        }

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "CharacterAsset":
        return cls(
            path=str(value.get("path", "")),
            sha256=str(value.get("sha256", "")),
            size_bytes=int(value.get("sizeBytes", 0)),
            media_type=str(value.get("mediaType", "application/octet-stream")),
        )


@dataclass(frozen=True)
class CharacterPackage:
    package_id: str
    creator: str
    license: str
    character_name: str
    version: str
    supported_renderer: str
    assets: tuple[CharacterAsset, ...]
    thumbnail: str
    fallback_image: str
    skeleton: Mapping[str, Any]
    animation_map: Mapping[str, str]
    lip_sync: Mapping[str, Any]
    facial_expressions: Mapping[str, str]
    resource_estimates: Mapping[str, int]
    minimum_rendering_capability: str
    prompt_provenance: Mapping[str, Any] | None = None
    generation_metadata: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        safe_identifier(self.package_id, "character package id")
        bounded_text(self.creator, "character creator", 256)
        bounded_text(self.license, "character license", 256)
        bounded_text(self.character_name, "character name", 256)
        safe_identifier(self.version, "character version")
        if self.supported_renderer not in SUPPORTED_RENDERERS:
            raise CharacterPackageError("character renderer is unsupported")
        if not self.assets:
            raise CharacterPackageError("character package has no assets")
        if len(self.assets) > MAX_ARCHIVE_ENTRIES - 1:
            raise CharacterPackageError("character package has too many assets")
        asset_paths = {item.path for item in self.assets}
        if len(asset_paths) != len(self.assets):
            raise CharacterPackageError("character package repeats an asset path")
        _asset_path(self.thumbnail)
        _asset_path(self.fallback_image)
        if self.thumbnail not in asset_paths or self.fallback_image not in asset_paths:
            raise CharacterPackageError("thumbnail and fallback image must be declared assets")
        if PurePosixPath(self.fallback_image).suffix.casefold() not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise CharacterPackageError("fallback image must be a static raster asset")
        missing_animations = set(REQUIRED_ANIMATIONS).difference(self.animation_map)
        if missing_animations:
            raise CharacterPackageError(
                "character package is missing animation states: " + ", ".join(sorted(missing_animations))
            )
        for state, path in self.animation_map.items():
            bounded_text(str(state), "animation state", 64)
            _asset_path(str(path))
            if path not in asset_paths:
                raise CharacterPackageError(f"animation {state!r} names an undeclared asset")
        for expression, path in self.facial_expressions.items():
            bounded_text(str(expression), "facial expression", 64)
            _asset_path(str(path))
            if path not in asset_paths:
                raise CharacterPackageError(f"facial expression {expression!r} names an undeclared asset")
        total = sum(item.size_bytes for item in self.assets)
        if total > MAX_PACKAGE_BYTES:
            raise CharacterPackageError("declared character assets exceed the package size limit")
        memory = int(self.resource_estimates.get("memoryBytes", 0))
        vram = int(self.resource_estimates.get("vramBytes", 0))
        if memory < 0 or memory > MAX_DECLARED_MEMORY_BYTES:
            raise CharacterPackageError("declared character memory requirement is excessive")
        if vram < 0 or vram > MAX_DECLARED_VRAM_BYTES:
            raise CharacterPackageError("declared character VRAM requirement is excessive")
        if self.minimum_rendering_capability not in SUPPORTED_RENDERERS:
            raise CharacterPackageError("minimum rendering capability is unsupported")
        _no_sensitive_metadata(self.skeleton, path="skeleton")
        _no_sensitive_metadata(self.lip_sync, path="lipSync")
        if self.prompt_provenance is not None:
            _no_sensitive_metadata(self.prompt_provenance, path="promptProvenance")
        if self.generation_metadata is not None:
            _no_sensitive_metadata(self.generation_metadata, path="generationMetadata")

    def to_json(self) -> dict[str, Any]:
        value = {
            "schemaVersion": CHARACTER_PACKAGE_SCHEMA_VERSION,
            "packageId": self.package_id,
            "creator": self.creator,
            "license": self.license,
            "characterName": self.character_name,
            "version": self.version,
            "supportedRenderer": self.supported_renderer,
            "assetFiles": [item.to_json() for item in self.assets],
            "thumbnail": self.thumbnail,
            "fallbackImage": self.fallback_image,
            "skeleton": dict(self.skeleton),
            "animationMap": dict(self.animation_map),
            "lipSync": dict(self.lip_sync),
            "facialExpressionMap": dict(self.facial_expressions),
            "resourceEstimates": dict(self.resource_estimates),
            "minimumRenderingCapability": self.minimum_rendering_capability,
        }
        if self.prompt_provenance is not None:
            value["promptProvenance"] = dict(self.prompt_provenance)
        if self.generation_metadata is not None:
            value["generationMetadata"] = dict(self.generation_metadata)
        return value

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "CharacterPackage":
        if value.get("schemaVersion") != CHARACTER_PACKAGE_SCHEMA_VERSION:
            raise CharacterPackageError("unsupported character package schemaVersion")
        assets = value.get("assetFiles")
        if not isinstance(assets, list):
            raise CharacterPackageError("assetFiles must be an array")
        required_objects = ("skeleton", "animationMap", "lipSync", "facialExpressionMap", "resourceEstimates")
        for name in required_objects:
            if not isinstance(value.get(name), Mapping):
                raise CharacterPackageError(f"{name} must be an object")
        return cls(
            package_id=str(value.get("packageId", "")),
            creator=str(value.get("creator", "")),
            license=str(value.get("license", "")),
            character_name=str(value.get("characterName", "")),
            version=str(value.get("version", "")),
            supported_renderer=str(value.get("supportedRenderer", "")),
            assets=tuple(CharacterAsset.from_json(item) for item in assets if isinstance(item, Mapping)),
            thumbnail=str(value.get("thumbnail", "")),
            fallback_image=str(value.get("fallbackImage", "")),
            skeleton=dict(value.get("skeleton") or {}),
            animation_map={str(key): str(item) for key, item in (value.get("animationMap") or {}).items()},
            lip_sync=dict(value.get("lipSync") or {}),
            facial_expressions={str(key): str(item) for key, item in (value.get("facialExpressionMap") or {}).items()},
            resource_estimates={str(key): int(item) for key, item in (value.get("resourceEstimates") or {}).items()},
            minimum_rendering_capability=str(value.get("minimumRenderingCapability", "")),
            prompt_provenance=dict(value["promptProvenance"]) if isinstance(value.get("promptProvenance"), Mapping) else None,
            generation_metadata=dict(value["generationMetadata"]) if isinstance(value.get("generationMetadata"), Mapping) else None,
        )


def _digest_stream(handle: Any) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    while True:
        chunk = handle.read(1024 * 1024)
        if not chunk:
            break
        size += len(chunk)
        if size > MAX_ASSET_BYTES:
            raise CharacterPackageError("asset exceeds the package size limit while reading")
        digest.update(chunk)
    return digest.hexdigest(), size


def validate_directory(root: Path) -> CharacterPackage:
    root = Path(root).resolve()
    manifest_path = root / "package.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise CharacterPackageError("character package has no regular package.json")
    if manifest_path.stat().st_size > 1024 * 1024:
        raise CharacterPackageError("character package manifest is oversized")
    try:
        package = CharacterPackage.from_json(json.loads(manifest_path.read_text(encoding="utf-8")))
    except json.JSONDecodeError as exc:
        raise CharacterPackageError("character package manifest is invalid JSON") from exc
    declared = {item.path: item for item in package.assets}
    for relative, asset in declared.items():
        candidate = root.joinpath(*PurePosixPath(relative).parts)
        if candidate.is_symlink() or not candidate.is_file():
            raise CharacterPackageError(f"declared asset is missing or symlinked: {relative}")
        resolved = candidate.resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise CharacterPackageError(f"declared asset escapes the package: {relative}") from exc
        if os.name == "posix" and candidate.stat().st_mode & 0o111:
            raise CharacterPackageError(f"asset is marked executable: {relative}")
        with candidate.open("rb") as handle:
            digest, size = _digest_stream(handle)
        if size != asset.size_bytes:
            raise CharacterPackageError(f"asset size mismatch: {relative}")
        if digest != asset.sha256:
            raise CharacterPackageError(f"asset hash mismatch: {relative}")
    for candidate in root.rglob("*"):
        if candidate.is_symlink():
            raise CharacterPackageError(f"symlinks are forbidden in character packages: {candidate.name}")
        if candidate.is_file() and candidate != manifest_path:
            relative = candidate.relative_to(root).as_posix()
            _asset_path(relative)
            if relative not in declared:
                raise CharacterPackageError(f"undeclared file in character package: {relative}")
    return package


def _zip_symlink(info: zipfile.ZipInfo) -> bool:
    return ((info.external_attr >> 16) & 0o170000) == 0o120000


def validate_archive(path: Path) -> CharacterPackage:
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise CharacterPackageError("character archive is not a regular file")
    if path.stat().st_size > MAX_PACKAGE_BYTES:
        raise CharacterPackageError("character archive is oversized")
    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise CharacterPackageError("character archive is malformed") from exc
    with archive:
        entries = archive.infolist()
        if not entries or len(entries) > MAX_ARCHIVE_ENTRIES:
            raise CharacterPackageError("character archive entry count is invalid")
        names: set[str] = set()
        total = 0
        for info in entries:
            name = info.filename.rstrip("/")
            if not name:
                continue
            pure = PurePosixPath(name)
            if pure.is_absolute() or ".." in pure.parts or "\\" in name or ":" in pure.parts[0]:
                raise CharacterPackageError("character archive contains path traversal")
            if name in names:
                raise CharacterPackageError("character archive repeats an entry")
            names.add(name)
            if info.flag_bits & 0x1:
                raise CharacterPackageError("encrypted character archive entries are forbidden")
            if _zip_symlink(info):
                raise CharacterPackageError("character archive contains a symlink")
            mode = (info.external_attr >> 16) & 0o777
            if mode & 0o111:
                raise CharacterPackageError("character archive contains an executable entry")
            if not info.is_dir() and name != "package.json":
                _asset_path(name)
            total += info.file_size
            if info.file_size > MAX_ASSET_BYTES or total > MAX_PACKAGE_BYTES:
                raise CharacterPackageError("character archive expands beyond its size limit")
            if info.compress_size == 0 and info.file_size > 0:
                raise CharacterPackageError("character archive has an invalid compression ratio")
            if info.compress_size and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO:
                raise CharacterPackageError("character archive has a suspicious compression ratio")
        if "package.json" not in names:
            raise CharacterPackageError("character archive has no package.json")
        manifest_info = archive.getinfo("package.json")
        if manifest_info.file_size > 1024 * 1024:
            raise CharacterPackageError("character archive manifest is oversized")
        try:
            package = CharacterPackage.from_json(json.loads(archive.read("package.json").decode("utf-8")))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CharacterPackageError("character archive manifest is invalid JSON") from exc
        declared = {item.path: item for item in package.assets}
        extra = {name for name in names if name != "package.json" and not name.endswith("/")}.difference(declared)
        missing = set(declared).difference(names)
        if extra:
            raise CharacterPackageError("character archive contains undeclared files")
        if missing:
            raise CharacterPackageError("character archive is missing declared assets")
        for relative, asset in declared.items():
            with archive.open(relative, "r") as handle:
                digest, size = _digest_stream(handle)
            if size != asset.size_bytes or digest != asset.sha256:
                raise CharacterPackageError(f"asset integrity mismatch: {relative}")
        return package
