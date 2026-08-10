# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Non-executing, bounded character package import and trust registry."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import re
import stat
import tempfile
from typing import Any, Iterable, Mapping
import zipfile

from .errors import (
    CharacterError,
    CharacterIntegrityError,
    CharacterSchemaError,
    CharacterSecurityError,
)
from .package import MANIFEST_NAME, ValidatedPackage, ValidationLimits, validate_package_directory
from .schema import (
    IMPLEMENTED_PRESENTATIONS,
    MAX_PACKAGE_BYTES,
    MAX_PACKAGE_FILES,
    PackageTrustState,
)

MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100
REGISTRY_SCHEMA_VERSION = 1
_REGISTRY_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_REGISTRY_VERSION = re.compile(r"^[0-9]+(?:\.[0-9]+){1,3}(?:[-+][A-Za-z0-9.-]+)?$")
_REGISTRY_DIGEST = re.compile(r"^[0-9a-f]{64}$")


def _registry_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, child in pairs:
        if key in value:
            raise CharacterIntegrityError(f"character registry repeats field {key!r}")
        value[key] = child
    return value


@dataclass(frozen=True)
class InstalledPackage:
    package_id: str
    package_version: str
    package_digest: str
    character_name: str
    presentation_type: str
    path: Path
    trust_state: PackageTrustState
    integrity_verified: bool
    creator_trusted: bool = False
    previous_trust_state: PackageTrustState | None = None

    def to_json(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "packageId": self.package_id,
            "packageVersion": self.package_version,
            "packageDigest": self.package_digest,
            "characterName": self.character_name,
            "presentationType": self.presentation_type,
            "path": str(self.path),
            "trustState": self.trust_state.value,
            "integrityVerified": self.integrity_verified,
            "creatorTrusted": self.creator_trusted,
        }
        if self.previous_trust_state is not None:
            value["previousTrustState"] = self.previous_trust_state.value
        return value

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "InstalledPackage":
        try:
            package_id = value["packageId"]
            package_version = value["packageVersion"]
            package_digest = value["packageDigest"]
            character_name = value["characterName"]
            presentation_type = value["presentationType"]
            stored_path = value["path"]
            integrity = value["integrityVerified"]
            creator_trusted = value.get("creatorTrusted", False)
            if not isinstance(package_id, str) or not _REGISTRY_IDENTIFIER.fullmatch(package_id):
                raise ValueError("packageId is invalid")
            if not isinstance(package_version, str) or not _REGISTRY_VERSION.fullmatch(package_version):
                raise ValueError("packageVersion is invalid")
            if not isinstance(package_digest, str) or not _REGISTRY_DIGEST.fullmatch(package_digest):
                raise ValueError("packageDigest is invalid")
            if not isinstance(character_name, str) or not character_name.strip():
                raise ValueError("characterName is invalid")
            if presentation_type not in set(IMPLEMENTED_PRESENTATIONS):
                # Read from the schema's own list rather than repeated here. It
                # was a literal pair until the 3D renderer landed, at which point
                # every 3D package in the registry became unreadable — a second
                # copy of a vocabulary, drifting on the first day the first one
                # changed.
                raise ValueError("presentationType is invalid")
            if not isinstance(stored_path, str) or not stored_path or "\x00" in stored_path:
                raise ValueError("path is invalid")
            if not isinstance(integrity, bool) or not isinstance(creator_trusted, bool):
                raise ValueError("registry trust flags must be boolean")
            return cls(
                package_id=package_id,
                package_version=package_version,
                package_digest=package_digest,
                character_name=character_name,
                presentation_type=presentation_type,
                path=Path(stored_path),
                trust_state=PackageTrustState(str(value["trustState"])),
                integrity_verified=integrity,
                creator_trusted=creator_trusted,
                previous_trust_state=(
                    PackageTrustState(str(value["previousTrustState"]))
                    if value.get("previousTrustState") else None
                ),
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise CharacterIntegrityError(f"package registry record is invalid: {exc}") from exc


class PackageRegistry:
    """Small atomic registry; integrity is distinct from creator trust."""

    def __init__(self, root: Path, *, built_in_paths: Iterable[Path] = ()) -> None:
        self.root = Path(root)
        self.packages_root = self.root / "packages"
        self.registry_path = self.root / "registry.json"
        self.built_in_paths = tuple(Path(path) for path in built_in_paths)

    def _read(self) -> dict[str, Any]:
        if not self.registry_path.exists():
            return {"schemaVersion": REGISTRY_SCHEMA_VERSION, "selectedDigest": None, "packages": []}
        try:
            value = json.loads(
                self.registry_path.read_text(encoding="utf-8"),
                object_pairs_hook=_registry_object,
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CharacterIntegrityError(f"character registry cannot be read: {exc}") from exc
        if not isinstance(value, Mapping) or value.get("schemaVersion") != REGISTRY_SCHEMA_VERSION:
            raise CharacterIntegrityError("character registry schema is unsupported")
        if not isinstance(value.get("packages"), list):
            raise CharacterIntegrityError("character registry package list is invalid")
        selected = value.get("selectedDigest")
        if selected is not None and (
            not isinstance(selected, str) or not _REGISTRY_DIGEST.fullmatch(selected)
        ):
            raise CharacterIntegrityError("character registry selected digest is invalid")
        return dict(value)

    def _validate_record_path(self, record: InstalledPackage) -> InstalledPackage:
        try:
            package_root = self.packages_root.resolve(strict=False)
            candidate = record.path.resolve(strict=False)
        except OSError as exc:
            raise CharacterIntegrityError(f"registered package path cannot be resolved: {exc}") from exc
        if package_root != candidate and package_root not in candidate.parents:
            raise CharacterIntegrityError("registered package path escapes the package registry")
        if record.trust_state is PackageTrustState.BUILT_IN:
            raise CharacterIntegrityError("built-in trust cannot be asserted by the user registry")
        return record

    def _write(self, value: Mapping[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        descriptor, temporary = tempfile.mkstemp(prefix=".registry-", suffix=".tmp", dir=self.root)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.registry_path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    def _built_ins(self) -> list[InstalledPackage]:
        result: list[InstalledPackage] = []
        for path in self.built_in_paths:
            if not path.is_dir():
                continue
            try:
                package = validate_package_directory(path, trust_state=PackageTrustState.BUILT_IN)
            except CharacterError:
                continue
            result.append(_record_for(package, previous=None, creator_trusted=True))
        return result

    def built_ins(self) -> tuple[InstalledPackage, ...]:
        """Return built-ins independently of digest-deduplicated user records."""
        return tuple(self._built_ins())

    def list(self) -> tuple[InstalledPackage, ...]:
        document = self._read()
        records = [
            self._validate_record_path(InstalledPackage.from_json(item))
            for item in document["packages"]
        ]
        by_digest = {item.package_digest: item for item in records}
        for item in self._built_ins():
            by_digest.setdefault(item.package_digest, item)
        return tuple(sorted(by_digest.values(), key=lambda item: (item.package_id, item.package_version, item.package_digest)))

    def selected(self) -> InstalledPackage | None:
        document = self._read()
        digest = document.get("selectedDigest")
        if digest:
            for item in self.list():
                if item.package_digest == digest:
                    return item
        built_ins = self._built_ins()
        return built_ins[0] if built_ins else None

    def inspect(self, package_id: str) -> tuple[InstalledPackage, ...]:
        matches = tuple(item for item in self.list() if item.package_id == package_id)
        if not matches:
            raise CharacterSchemaError(f"no character package with id {package_id!r} is installed")
        return matches

    def add(self, record: InstalledPackage) -> None:
        self._validate_record_path(record)
        document = self._read()
        records = [
            self._validate_record_path(InstalledPackage.from_json(item))
            for item in document["packages"]
        ]
        by_digest = {item.package_digest: item for item in records}
        by_digest[record.package_digest] = record
        document["packages"] = [item.to_json() for item in sorted(
            by_digest.values(), key=lambda entry: (entry.package_id, entry.package_version, entry.package_digest)
        )]
        self._write(document)

    def select(self, package_id: str, *, package_digest: str | None = None) -> InstalledPackage:
        candidates = list(self.inspect(package_id))
        if package_digest is not None:
            candidates = [item for item in candidates if item.package_digest == package_digest]
        if not candidates:
            raise CharacterSchemaError("requested package version is not installed")
        allowed = [item for item in candidates if item.trust_state not in {
            PackageTrustState.DISABLED, PackageTrustState.QUARANTINED,
            PackageTrustState.INCOMPATIBLE, PackageTrustState.CORRUPT,
        }]
        if not allowed:
            raise CharacterSecurityError("requested character package is not eligible for selection")
        selected = sorted(allowed, key=lambda item: (item.package_version, item.package_digest))[-1]
        trust = PackageTrustState.BUILT_IN if selected.trust_state is PackageTrustState.BUILT_IN else PackageTrustState.VERIFIED_INTEGRITY
        validate_package_directory(selected.path, trust_state=trust)
        document = self._read()
        document["selectedDigest"] = selected.package_digest
        self._write(document)
        return selected

    def set_trust_state(self, package_digest: str, state: PackageTrustState) -> InstalledPackage:
        document = self._read()
        records = [
            self._validate_record_path(InstalledPackage.from_json(item))
            for item in document["packages"]
        ]
        changed: InstalledPackage | None = None
        updated: list[InstalledPackage] = []
        for record in records:
            if record.package_digest == package_digest:
                changed = replace(record, trust_state=state)
                updated.append(changed)
            else:
                updated.append(record)
        if changed is None:
            raise CharacterSchemaError("package digest is not registered")
        if state in {PackageTrustState.DISABLED, PackageTrustState.QUARANTINED, PackageTrustState.CORRUPT}:
            if document.get("selectedDigest") == package_digest:
                document["selectedDigest"] = None
        document["packages"] = [item.to_json() for item in updated]
        self._write(document)
        return changed


def _record_for(
    package: ValidatedPackage,
    *,
    previous: PackageTrustState | None,
    creator_trusted: bool = False,
) -> InstalledPackage:
    return InstalledPackage(
        package_id=package.manifest.package_id,
        package_version=package.manifest.package_version,
        package_digest=package.package_digest,
        character_name=package.manifest.character_name,
        presentation_type=package.manifest.presentation_type.value,
        path=package.root,
        trust_state=package.trust_state,
        integrity_verified=True,
        creator_trusted=creator_trusted,
        previous_trust_state=previous,
    )


def _archive_path(name: str) -> PurePosixPath:
    if not name or "\x00" in name or "\\" in name:
        raise CharacterSecurityError("archive contains an invalid path")
    path = PurePosixPath(name.rstrip("/"))
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise CharacterSecurityError("archive path escapes the package root")
    if not path.parts or ":" in path.parts[0] or len(path.parts) > 16:
        raise CharacterSecurityError("archive contains an absolute or drive-qualified path")
    return path


def _inspect_zip(archive: zipfile.ZipFile, *, limits: ValidationLimits) -> tuple[zipfile.ZipInfo, ...]:
    entries = tuple(archive.infolist())
    files = [entry for entry in entries if not entry.is_dir()]
    if len(files) > limits.maximum_files + 1:
        raise CharacterSecurityError("archive exceeds the file-count limit")
    extracted = compressed = 0
    seen: set[str] = set()
    for entry in entries:
        path = _archive_path(entry.filename)
        normalized = path.as_posix()
        if normalized in seen:
            raise CharacterSecurityError("archive repeats a path")
        seen.add(normalized)
        if entry.flag_bits & 0x1:
            raise CharacterSecurityError("encrypted character archives are unsupported")
        if entry.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
            raise CharacterSecurityError("archive compression method is unsupported")
        mode = (entry.external_attr >> 16) & 0xFFFF
        file_type = stat.S_IFMT(mode)
        if file_type and file_type not in {stat.S_IFREG, stat.S_IFDIR}:
            raise CharacterSecurityError("archive contains a symlink, device, or special file")
        if not entry.is_dir() and os.name != "nt" and mode & 0o111:
            raise CharacterSecurityError("archive contains an executable file")
        if entry.file_size < 0 or entry.compress_size < 0:
            raise CharacterSecurityError("archive contains an invalid size")
        extracted += entry.file_size
        compressed += entry.compress_size
        if extracted > limits.maximum_total_bytes + limits.maximum_manifest_bytes:
            raise CharacterSecurityError("archive exceeds the extracted-size limit")
        if entry.file_size > 0 and entry.compress_size == 0:
            raise CharacterSecurityError("archive entry has an impossible compression ratio")
        if entry.compress_size and entry.file_size / entry.compress_size > MAX_COMPRESSION_RATIO:
            raise CharacterSecurityError("archive entry resembles a decompression bomb")
    if compressed and extracted / compressed > MAX_COMPRESSION_RATIO:
        raise CharacterSecurityError("archive resembles a decompression bomb")
    return entries


def _extract_zip(source: Path, target: Path, *, limits: ValidationLimits) -> None:
    if source.stat().st_size > MAX_ARCHIVE_BYTES:
        raise CharacterSecurityError("compressed archive exceeds the input limit")
    try:
        with zipfile.ZipFile(source, "r") as archive:
            entries = _inspect_zip(archive, limits=limits)
            written = 0
            for entry in entries:
                relative = _archive_path(entry.filename)
                destination = target.joinpath(*relative.parts)
                if entry.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry, "r") as incoming, destination.open("xb") as outgoing:
                    while block := incoming.read(1024 * 1024):
                        written += len(block)
                        if written > limits.maximum_total_bytes + limits.maximum_manifest_bytes:
                            raise CharacterSecurityError("archive exceeded its size limit while extracting")
                        outgoing.write(block)
                    outgoing.flush()
                    os.fsync(outgoing.fileno())
    except zipfile.BadZipFile as exc:
        raise CharacterSchemaError(f"character archive is corrupt: {exc}") from exc


def _copy_directory(source: Path, target: Path, *, limits: ValidationLimits) -> None:
    # Validate first, then copy only the paths named by the validated manifest.
    package = validate_package_directory(source, limits=limits)
    target.mkdir(parents=True, exist_ok=False)
    files = [Path(MANIFEST_NAME), *(Path(asset.path) for asset in package.manifest.assets)]
    for relative in files:
        incoming = source / relative
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(incoming, flags)
        try:
            with os.fdopen(descriptor, "rb", closefd=False) as stream, destination.open("xb") as output:
                shutil.copyfileobj(stream, output, length=1024 * 1024)
                output.flush()
                os.fsync(output.fileno())
        finally:
            os.close(descriptor)


class CharacterPackageImporter:
    def __init__(self, registry: PackageRegistry, *, limits: ValidationLimits | None = None) -> None:
        self.registry = registry
        self.limits = limits or ValidationLimits()

    def import_package(self, source: Path) -> InstalledPackage:
        """Inspect, verify, and atomically install a directory or .zip package."""
        source = Path(source)
        if not source.exists():
            raise CharacterSchemaError("character package source does not exist")
        self.registry.root.mkdir(parents=True, exist_ok=True)
        staging_root = self.registry.root / ".staging"
        staging_root.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix="import-", dir=staging_root))
        payload = staging / "package"
        try:
            if source.is_dir():
                _copy_directory(source, payload, limits=self.limits)
            elif source.is_file() and source.suffix.casefold() == ".zip":
                payload.mkdir(parents=True, exist_ok=False)
                _extract_zip(source, payload, limits=self.limits)
            else:
                raise CharacterSecurityError("only package directories and .zip archives are supported")
            unverified = validate_package_directory(
                payload, trust_state=PackageTrustState.IMPORTED_UNVERIFIED, limits=self.limits
            )
            verified = replace(unverified, trust_state=PackageTrustState.VERIFIED_INTEGRITY)
            destination_parent = self.registry.packages_root / verified.manifest.package_id
            destination_parent.mkdir(parents=True, exist_ok=True)
            destination = destination_parent / (
                f"{verified.manifest.package_version}-{verified.package_digest[:16]}"
            )
            if destination.exists():
                existing = validate_package_directory(
                    destination, trust_state=PackageTrustState.VERIFIED_INTEGRITY, limits=self.limits
                )
                if existing.package_digest != verified.package_digest:
                    raise CharacterIntegrityError("installed package path contains different bytes")
                record = _record_for(existing, previous=PackageTrustState.IMPORTED_UNVERIFIED)
            else:
                os.replace(payload, destination)
                installed = validate_package_directory(
                    destination, trust_state=PackageTrustState.VERIFIED_INTEGRITY, limits=self.limits
                )
                record = _record_for(installed, previous=PackageTrustState.IMPORTED_UNVERIFIED)
            self.registry.add(record)
            return record
        except CharacterError:
            raise
        except (OSError, ValueError) as exc:
            raise CharacterSecurityError(f"character package import failed safely: {exc}") from exc
        finally:
            shutil.rmtree(staging, ignore_errors=True)
