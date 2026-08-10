# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Whole-directory validation for hostile Bunny character packages."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Iterable

from capability.apply.identity import canonical_json

from . import MINIMUM_BUNNY_OS_VERSION
from .errors import (
    CharacterCompatibilityError,
    CharacterIntegrityError,
    CharacterSchemaError,
    CharacterSecurityError,
)
from .image import ImageInfo, inspect_image
from .schema import (
    MAX_PACKAGE_BYTES,
    MAX_PACKAGE_FILES,
    CharacterManifest,
    PackageTrustState,
)

MANIFEST_NAME = "manifest.json"
MAX_MANIFEST_BYTES = 1024 * 1024
_CREDENTIAL_TEXT = re.compile(
    r"(?i)(?:-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"(?:bearer\s+|sk-|gh[pousr]_|AKIA)[A-Za-z0-9._=+/-]{12,}|"
    r"(?:api.?key|token|password|secret)\s*[:=]\s*[^\s,;]{8,})"
)


@dataclass(frozen=True)
class ValidationLimits:
    maximum_files: int = MAX_PACKAGE_FILES
    maximum_total_bytes: int = MAX_PACKAGE_BYTES
    maximum_manifest_bytes: int = MAX_MANIFEST_BYTES

    def __post_init__(self) -> None:
        if self.maximum_files <= 0 or self.maximum_files > MAX_PACKAGE_FILES:
            raise ValueError("file limit exceeds the renderer's hard ceiling")
        if self.maximum_total_bytes <= 0 or self.maximum_total_bytes > MAX_PACKAGE_BYTES:
            raise ValueError("size limit exceeds the renderer's hard ceiling")
        if self.maximum_manifest_bytes <= 0 or self.maximum_manifest_bytes > MAX_MANIFEST_BYTES:
            raise ValueError("manifest limit exceeds the renderer's hard ceiling")


@dataclass(frozen=True)
class ValidatedPackage:
    root: Path
    manifest: CharacterManifest
    package_digest: str
    trust_state: PackageTrustState
    image_info: dict[str, ImageInfo]
    total_bytes: int
    file_count: int

    def asset_path(self, asset_id: str) -> Path:
        asset = self.manifest.asset(asset_id)
        candidate = self.root.joinpath(*asset.path.split("/"))
        # The directory validator proved this relationship.  Keep the check in
        # the accessor as defence in depth for callers holding a deserialised
        # manifest from somewhere else.
        root = self.root.resolve(strict=True)
        resolved = candidate.resolve(strict=True)
        if root not in resolved.parents:
            raise CharacterSecurityError("validated asset no longer remains under its package root")
        return resolved

    def to_json(self) -> dict[str, Any]:
        declared_states = set(self.manifest.state_map)
        return {
            "packageId": self.manifest.package_id,
            "characterId": self.manifest.character_id,
            "characterName": self.manifest.character_name,
            "packageVersion": self.manifest.package_version,
            "packageDigest": self.package_digest,
            "presentationType": self.manifest.presentation_type.value,
            "trustState": self.trust_state.value,
            "creatorTrusted": self.trust_state in {PackageTrustState.BUILT_IN, PackageTrustState.LOCALLY_CREATED},
            "integrityVerified": True,
            "root": str(self.root),
            "fileCount": self.file_count,
            "totalBytes": self.total_bytes,
            "declaredMemoryEstimateBytes": self.manifest.memory_estimate_bytes,
            "declaredStates": sorted(declared_states),
        }


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, child in pairs:
        if key in value:
            raise CharacterSchemaError(f"JSON object repeats field {key!r}")
        value[key] = child
    return value


def _walk_package(root: Path) -> tuple[dict[str, tuple[Path, os.stat_result]], int]:
    """Walk without following links and reject anything but ordinary files/dirs."""
    found: dict[str, tuple[Path, os.stat_result]] = {}
    total = 0
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = sorted(os.scandir(current), key=lambda item: item.name)
        except OSError as exc:
            raise CharacterSecurityError(f"package directory cannot be inspected: {exc}") from exc
        for entry in entries:
            if entry.name in {"", ".", ".."} or "\x00" in entry.name:
                raise CharacterSecurityError("package contains an invalid filesystem name")
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise CharacterSecurityError(f"package entry cannot be inspected: {exc}") from exc
            mode = info.st_mode
            path = Path(entry.path)
            relative = path.relative_to(root).as_posix()
            if stat.S_ISLNK(mode) or entry.is_symlink():
                raise CharacterSecurityError(f"package contains a symlink: {relative}")
            if stat.S_ISDIR(mode):
                stack.append(path)
                continue
            if not stat.S_ISREG(mode):
                raise CharacterSecurityError(f"package contains a device or special file: {relative}")
            if getattr(info, "st_nlink", 1) > 1:
                raise CharacterSecurityError(f"package contains a hard-linked file: {relative}")
            if os.name != "nt" and mode & 0o111:
                raise CharacterSecurityError(f"package contains an executable file: {relative}")
            if relative in found:
                raise CharacterSecurityError(f"package repeats a filesystem path: {relative}")
            found[relative] = (path, info)
            total += info.st_size
    return found, total


def _version_tuple(value: str) -> tuple[int, ...]:
    base = value.split("-", 1)[0].split("+", 1)[0]
    return tuple(int(part) for part in base.split("."))


def _digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _validate_metadata_asset(path: Path, media_type: str) -> None:
    data = path.read_bytes()
    if b"\x00" in data:
        raise CharacterSecurityError("text metadata contains binary or executable content")
    if data.startswith((b"#!", b"MZ", b"\x7fELF")):
        raise CharacterSecurityError("metadata file has an executable signature")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CharacterSchemaError("text metadata must be UTF-8") from exc
    if _CREDENTIAL_TEXT.search(text):
        raise CharacterSecurityError("credential-like content is forbidden in package metadata")
    if media_type == "application/json":
        try:
            json.loads(text, object_pairs_hook=_no_duplicate_keys)
        except json.JSONDecodeError as exc:
            raise CharacterSchemaError(f"metadata JSON is invalid: {exc}") from exc


def validate_package_directory(
    root: Path,
    *,
    trust_state: PackageTrustState = PackageTrustState.IMPORTED_UNVERIFIED,
    bunny_os_version: str = MINIMUM_BUNNY_OS_VERSION,
    limits: ValidationLimits | None = None,
) -> ValidatedPackage:
    """Validate every byte and reference in a data-only package directory."""
    limits = limits or ValidationLimits()
    root = Path(root)
    try:
        root_info = root.lstat()
    except OSError as exc:
        raise CharacterSchemaError(f"character package directory is unavailable: {exc}") from exc
    if stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode):
        raise CharacterSecurityError("character package root must be a real directory")
    root = root.resolve(strict=True)
    files, total = _walk_package(root)
    if len(files) > limits.maximum_files + 1:
        raise CharacterSecurityError("package exceeds the file-count limit")
    if total > limits.maximum_total_bytes + limits.maximum_manifest_bytes:
        raise CharacterSecurityError("package exceeds the extracted-size limit")
    manifest_entry = files.get(MANIFEST_NAME)
    if manifest_entry is None:
        raise CharacterSchemaError("character package is missing manifest.json")
    manifest_path, manifest_info = manifest_entry
    if manifest_info.st_size <= 0 or manifest_info.st_size > limits.maximum_manifest_bytes:
        raise CharacterSchemaError("manifest.json is empty or oversized")
    if total - manifest_info.st_size > limits.maximum_total_bytes:
        raise CharacterSecurityError("package exceeds the extracted asset-size limit")
    try:
        document = json.loads(
            manifest_path.read_text(encoding="utf-8"), object_pairs_hook=_no_duplicate_keys
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CharacterSchemaError(f"manifest.json is invalid JSON: {exc}") from exc
    manifest = CharacterManifest.from_json(document)
    if manifest.minimum_bunny_os_version is not None:
        if _version_tuple(bunny_os_version) < _version_tuple(manifest.minimum_bunny_os_version):
            raise CharacterCompatibilityError(
                f"package requires Bunny OS {manifest.minimum_bunny_os_version} or later"
            )
    declared = {asset.path for asset in manifest.assets}
    observed = set(files).difference({MANIFEST_NAME})
    undeclared = sorted(observed.difference(declared))
    missing = sorted(declared.difference(observed))
    if undeclared:
        raise CharacterSecurityError("package contains undeclared files: " + ", ".join(undeclared))
    if missing:
        raise CharacterIntegrityError("package is missing declared files: " + ", ".join(missing))
    if len(observed) > limits.maximum_files:
        raise CharacterSecurityError("package exceeds the asset file-count limit")

    image_info: dict[str, ImageInfo] = {}
    for asset in manifest.assets:
        path, info = files[asset.path]
        if info.st_size != asset.size_bytes:
            raise CharacterIntegrityError(f"asset {asset.asset_id!r} size does not match its manifest")
        digest = _digest_file(path)
        if digest != asset.sha256:
            raise CharacterIntegrityError(f"asset {asset.asset_id!r} content digest does not match")
        if asset.media_type.startswith("image/"):
            observed_image = inspect_image(path)
            if observed_image.media_type != asset.media_type:
                raise CharacterIntegrityError(f"asset {asset.asset_id!r} media type does not match")
            if (observed_image.width, observed_image.height) != (asset.width, asset.height):
                raise CharacterIntegrityError(f"asset {asset.asset_id!r} dimensions do not match")
            image_info[asset.asset_id] = observed_image
        else:
            _validate_metadata_asset(path, asset.media_type)

    license_path = files[manifest.asset(manifest.license_asset).path][0]
    if not license_path.read_text(encoding="utf-8").strip():
        raise CharacterSchemaError("the declared license file is empty")
    digest_material = {
        "manifest": manifest.to_json(),
        "assets": [
            {"path": asset.path, "sha256": asset.sha256, "sizeBytes": asset.size_bytes}
            for asset in sorted(manifest.assets, key=lambda item: item.path)
        ],
    }
    package_digest = hashlib.sha256(canonical_json(digest_material).encode("utf-8")).hexdigest()
    return ValidatedPackage(
        root=root,
        manifest=manifest,
        package_digest=package_digest,
        trust_state=trust_state,
        image_info=image_info,
        total_bytes=total,
        file_count=len(observed),
    )
