# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Locks for the inputs a qualification build is allowed to consume.

Four things decide what a build produces: the base image, the tools that run,
the packages installed, and the clock. Before this module, three of the four
were unpinned in practice.

* The base was pinned **by digest** and the digest was garbage collected from
  upstream within days. A pinned reference records which base was used; it does
  not make that base obtainable. The local builder went on building against a
  base no independent party could fetch, and nothing reported it, because the
  machine holding the layers in its cache cannot observe the absence.
* The tools came from whatever the hosted runner image shipped that morning.
  ``ubuntu-24.04`` is a label, not an environment: two runs an hour apart had
  podman 4.9.3 and 5.8.4, and one of them wrote ``/etc/hostname`` into the image.
* The packages were resolved against live Fedora repositories, an hour apart.
  The two sets happened to agree, and agreeing was luck.

So every lock here refuses the same class of mistake: a reference that names
content without retaining it, and a version that names a tool without pinning
it. Each parser fails closed and names the field, because a lock that accepts an
ambiguous record is a lock that reports success for an unpinned build.

Tool classification is the one judgement call the model allows, and it is
constrained. ``verify-builder-independence`` previously refused a pair whose
``skopeo``, ``python3`` and ``image-builder`` versions differed, and the honest
analysis was that none of the three writes the archive. That analysis is not a
licence to wave a difference through: it has to be *declared*, per tool, with a
class and a reason, and ``unknown`` blocks. "This tool probably does not matter"
is the reasoning that lets a real difference through — podman was on that list
one run before it demonstrably changed the artifact.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import datetime as _datetime
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence

SCHEMA_VERSION = 1

#: A reference this project may build from. Anything else is a mutable tag.
DIGEST_PINNED = re.compile(r"^(?P<name>[^\s@]+)@sha256:(?P<digest>[0-9a-f]{64})$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
BARE_DIGEST = re.compile(r"^[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")

#: How a tool may relate to the bytes of the artifact.
#:
#: ``unknown`` is not a soft state. A tool nobody has classified is a tool whose
#: effect on the output nobody has established, and an unestablished effect
#: cannot be assumed to be none.
TOOL_CLASSES = (
    "output-affecting",
    "evidence-generation-only",
    "unavailable-but-unused",
    "unknown",
)

#: Classes that permit two builders to differ in that tool's version.
NON_BLOCKING_TOOL_CLASSES = frozenset({"evidence-generation-only", "unavailable-but-unused"})

#: Tools whose version must be pinned in a hermetic builder, whatever their
#: declared class. Listing a tool here does not assert it affects the output; it
#: asserts that leaving it unpinned means nobody can tell.
PINNED_TOOLS = (
    "podman",
    "buildah",
    "skopeo",
    "conmon",
    "crun",
    "runc",
    "python3",
    "rpm",
    "dnf5",
    "libdnf5",
    "tar",
    "gzip",
    "zstd",
    "syft",
    "grype",
    "createrepo_c",
    "policycoreutils",
    "libselinux-utils",
)


#: One architecture, two naming schemes. OCI image manifests use Go's names
#: (``amd64``, ``arm64``); rpm, uname and every Fedora package use the kernel's
#: (``x86_64``, ``aarch64``). The base-image lock is written from an OCI index
#: and the reproducibility lock from the package architecture, so a check that
#: compared the two strings directly reported that ``x86_64`` was not among
#: ``amd64, arm64, ppc64le, s390x`` — which is true of the strings and false of
#: the architectures.
#:
#: Normalising rather than accepting either name is deliberate: a genuine
#: mismatch — an x86_64 build against an arm64-only mirror — must still fail,
#: and it does, because the two normalise to different values.
_ARCHITECTURE_ALIASES = {
    "amd64": "x86_64",
    "x86_64": "x86_64",
    "arm64": "aarch64",
    "aarch64": "aarch64",
    "ppc64le": "ppc64le",
    "s390x": "s390x",
    "386": "i686",
    "i686": "i686",
    "riscv64": "riscv64",
}


def normalise_architecture(name: str) -> str:
    """Canonical kernel-style name for an architecture written either way."""
    return _ARCHITECTURE_ALIASES.get(str(name).strip().lower(), str(name).strip().lower())


class SupplyChainError(ValueError):
    """Raised when a lock is malformed, unpinned, or unverified."""


def _require(record: Mapping[str, Any], name: str, *, what: str) -> Any:
    if not isinstance(record, Mapping):
        raise SupplyChainError(f"{what} must be an object")
    value = record.get(name)
    if value in (None, "", [], {}):
        raise SupplyChainError(f"{what}: missing required field {name!r}")
    return value


def _digest_pinned(reference: str, *, what: str, field_name: str) -> str:
    """Return the digest of a pinned reference, or refuse the reference."""
    match = DIGEST_PINNED.match(str(reference))
    if not match:
        raise SupplyChainError(
            f"{what}: {field_name} {reference!r} is not digest-pinned. A mutable tag does not "
            "identify content: two builders can resolve the same tag to different images and the "
            "comparison would attribute the difference to the build"
        )
    return "sha256:" + match.group("digest")


def _timestamp(value: Any, *, what: str, field_name: str) -> str:
    try:
        _datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise SupplyChainError(f"{what}: {field_name} must be an RFC 3339 timestamp") from None
    return str(value)


# --------------------------------------------------------------------------
# Base image retention
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ManifestRecord:
    digest: str
    mediaType: str
    size: int
    architecture: str | None = None
    os: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "digest": self.digest,
            "mediaType": self.mediaType,
            "size": self.size,
            "architecture": self.architecture,
            "os": self.os,
        }


@dataclass(frozen=True)
class BaseImageLock:
    """What was mirrored, from where, and whether the copy was verified.

    ``upstreamDigest`` is what this project pinned. For ``fedora-bootc`` that is
    an **image index**, and an index is not what a build consumes: the build
    consumes one architecture's manifest. Both are recorded, and
    ``selectedManifestDigest`` must be one of the index's own children — so the
    lock cannot claim that an arbitrary manifest came from the pinned index.

    ``retainedDigest`` must equal ``selectedManifestDigest``. A content-addressed
    copy preserves the manifest digest; if it did not, the mirror re-encoded the
    image, and a re-encoded image is a different image however similar it looks.
    """

    schemaVersion: int
    upstreamReference: str
    upstreamDigest: str
    upstreamMediaType: str
    selectedArchitecture: str
    selectedManifestDigest: str
    retainedReference: str
    retainedDigest: str
    architectures: tuple[str, ...]
    manifests: tuple[ManifestRecord, ...]
    copiedAt: str
    verificationStatus: str
    blobCount: int = 0
    blobBytes: int = 0
    retainedLocation: str = ""
    upstreamStillAvailable: bool | None = None
    notes: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schemaVersion,
            "upstreamReference": self.upstreamReference,
            "upstreamDigest": self.upstreamDigest,
            "upstreamMediaType": self.upstreamMediaType,
            "selectedArchitecture": self.selectedArchitecture,
            "selectedManifestDigest": self.selectedManifestDigest,
            "retainedReference": self.retainedReference,
            "retainedDigest": self.retainedDigest,
            "retainedLocation": self.retainedLocation,
            "architectures": list(self.architectures),
            "manifests": [m.as_dict() for m in self.manifests],
            "copiedAt": self.copiedAt,
            "blobCount": self.blobCount,
            "blobBytes": self.blobBytes,
            "upstreamStillAvailable": self.upstreamStillAvailable,
            "verificationStatus": self.verificationStatus,
            "notes": self.notes,
        }


def parse_base_image_lock(record: Mapping[str, Any]) -> BaseImageLock:
    what = "base-image-lock"
    if not isinstance(record, Mapping):
        raise SupplyChainError(f"{what} must be an object")
    if int(_require(record, "schemaVersion", what=what)) != SCHEMA_VERSION:
        raise SupplyChainError(f"{what}: schemaVersion must be {SCHEMA_VERSION}")

    upstream_ref = str(_require(record, "upstreamReference", what=what))
    upstream_digest_from_ref = _digest_pinned(
        upstream_ref, what=what, field_name="upstreamReference"
    )
    upstream_digest = str(_require(record, "upstreamDigest", what=what))
    if not DIGEST.match(upstream_digest):
        raise SupplyChainError(f"{what}: upstreamDigest must be sha256:<64 hex>")
    if upstream_digest != upstream_digest_from_ref:
        raise SupplyChainError(
            f"{what}: upstreamReference pins {upstream_digest_from_ref} but upstreamDigest is "
            f"{upstream_digest}; the two must name the same content"
        )

    retained_ref = str(_require(record, "retainedReference", what=what))
    retained_digest_from_ref = _digest_pinned(
        retained_ref, what=what, field_name="retainedReference"
    )
    retained_digest = str(_require(record, "retainedDigest", what=what))
    if not DIGEST.match(retained_digest):
        raise SupplyChainError(f"{what}: retainedDigest must be sha256:<64 hex>")
    if retained_digest != retained_digest_from_ref:
        raise SupplyChainError(
            f"{what}: retainedReference pins {retained_digest_from_ref} but retainedDigest is "
            f"{retained_digest}"
        )

    manifests_raw = _require(record, "manifests", what=what)
    if not isinstance(manifests_raw, Sequence) or isinstance(manifests_raw, (str, bytes)):
        raise SupplyChainError(f"{what}: manifests must be an array")
    manifests: list[ManifestRecord] = []
    for item in manifests_raw:
        if not isinstance(item, Mapping):
            raise SupplyChainError(f"{what}: each manifest entry must be an object")
        digest = str(item.get("digest", ""))
        if not DIGEST.match(digest):
            raise SupplyChainError(f"{what}: manifest digest {digest!r} must be sha256:<64 hex>")
        manifests.append(
            ManifestRecord(
                digest=digest,
                mediaType=str(item.get("mediaType", "")),
                size=int(item.get("size", 0)),
                architecture=(str(item["architecture"]) if item.get("architecture") else None),
                os=(str(item["os"]) if item.get("os") else None),
            )
        )
    if not manifests:
        raise SupplyChainError(f"{what}: manifests must not be empty")

    selected_architecture = str(_require(record, "selectedArchitecture", what=what))
    selected_digest = str(_require(record, "selectedManifestDigest", what=what))
    if not DIGEST.match(selected_digest):
        raise SupplyChainError(f"{what}: selectedManifestDigest must be sha256:<64 hex>")

    known = {m.digest for m in manifests}
    if selected_digest not in known:
        raise SupplyChainError(
            f"{what}: selectedManifestDigest {selected_digest} is not in the recorded manifest "
            "inventory. The lock would be asserting that a manifest came from the pinned index "
            "without recording that it did"
        )
    if retained_digest != selected_digest:
        raise SupplyChainError(
            f"{what}: retainedDigest {retained_digest} differs from selectedManifestDigest "
            f"{selected_digest}. A content-addressed copy preserves the manifest digest; a "
            "differing digest means the mirror re-encoded the image, and a re-encoded image is a "
            "different image"
        )

    architectures = tuple(str(a) for a in _require(record, "architectures", what=what))
    if selected_architecture not in architectures:
        raise SupplyChainError(
            f"{what}: selectedArchitecture {selected_architecture!r} is not listed in architectures"
        )

    status = str(_require(record, "verificationStatus", what=what))
    if status not in ("verified", "failed"):
        raise SupplyChainError(f"{what}: verificationStatus must be 'verified' or 'failed'")

    return BaseImageLock(
        schemaVersion=SCHEMA_VERSION,
        upstreamReference=upstream_ref,
        upstreamDigest=upstream_digest,
        upstreamMediaType=str(record.get("upstreamMediaType", "")),
        selectedArchitecture=selected_architecture,
        selectedManifestDigest=selected_digest,
        retainedReference=retained_ref,
        retainedDigest=retained_digest,
        architectures=architectures,
        manifests=tuple(manifests),
        copiedAt=_timestamp(_require(record, "copiedAt", what=what), what=what, field_name="copiedAt"),
        verificationStatus=status,
        blobCount=int(record.get("blobCount", 0)),
        blobBytes=int(record.get("blobBytes", 0)),
        retainedLocation=str(record.get("retainedLocation", "")),
        upstreamStillAvailable=(
            bool(record["upstreamStillAvailable"])
            if record.get("upstreamStillAvailable") is not None
            else None
        ),
        notes=str(record.get("notes", "")),
    )


# --------------------------------------------------------------------------
# Builder image
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolRecord:
    name: str
    version: str
    classification: str
    reason: str
    packageChecksum: str = ""

    @property
    def blocksOnMismatch(self) -> bool:
        return self.classification not in NON_BLOCKING_TOOL_CLASSES

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "classification": self.classification,
            "reason": self.reason,
            "packageChecksum": self.packageChecksum,
            "blocksOnMismatch": self.blocksOnMismatch,
        }


@dataclass(frozen=True)
class BuilderImageLock:
    schemaVersion: int
    builderReference: str
    builderDigest: str
    baseReference: str
    baseDigest: str
    sourceCommit: str
    containerfileDigest: str
    architecture: str
    tools: tuple[ToolRecord, ...]
    builtAt: str
    verificationStatus: str
    runtimeRequirements: Mapping[str, Any] = field(default_factory=dict)
    notes: str = ""

    @property
    def toolVersions(self) -> dict[str, str]:
        return {tool.name: tool.version for tool in self.tools}

    @property
    def unknownTools(self) -> tuple[str, ...]:
        return tuple(sorted(t.name for t in self.tools if t.classification == "unknown"))

    def as_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schemaVersion,
            "builderReference": self.builderReference,
            "builderDigest": self.builderDigest,
            "baseReference": self.baseReference,
            "baseDigest": self.baseDigest,
            "sourceCommit": self.sourceCommit,
            "containerfileDigest": self.containerfileDigest,
            "architecture": self.architecture,
            "tools": [t.as_dict() for t in self.tools],
            "builtAt": self.builtAt,
            "runtimeRequirements": dict(self.runtimeRequirements),
            "verificationStatus": self.verificationStatus,
            "notes": self.notes,
        }


def parse_builder_image_lock(record: Mapping[str, Any]) -> BuilderImageLock:
    what = "builder-image-lock"
    if not isinstance(record, Mapping):
        raise SupplyChainError(f"{what} must be an object")
    if int(_require(record, "schemaVersion", what=what)) != SCHEMA_VERSION:
        raise SupplyChainError(f"{what}: schemaVersion must be {SCHEMA_VERSION}")

    builder_ref = str(_require(record, "builderReference", what=what))
    builder_digest = _digest_pinned(builder_ref, what=what, field_name="builderReference")
    declared = str(_require(record, "builderDigest", what=what))
    if declared != builder_digest:
        raise SupplyChainError(
            f"{what}: builderReference pins {builder_digest} but builderDigest is {declared}"
        )

    base_ref = str(_require(record, "baseReference", what=what))
    base_digest = _digest_pinned(base_ref, what=what, field_name="baseReference")
    declared_base = str(_require(record, "baseDigest", what=what))
    if declared_base != base_digest:
        raise SupplyChainError(
            f"{what}: baseReference pins {base_digest} but baseDigest is {declared_base}"
        )

    commit = str(_require(record, "sourceCommit", what=what))
    if not COMMIT.match(commit):
        raise SupplyChainError(f"{what}: sourceCommit must be a full 40-character SHA")

    containerfile = str(_require(record, "containerfileDigest", what=what))
    if not BARE_DIGEST.match(containerfile):
        raise SupplyChainError(f"{what}: containerfileDigest must be 64 hex characters")

    tools_raw = _require(record, "tools", what=what)
    if not isinstance(tools_raw, Sequence) or isinstance(tools_raw, (str, bytes)):
        raise SupplyChainError(f"{what}: tools must be an array")
    tools: list[ToolRecord] = []
    seen: set[str] = set()
    for item in tools_raw:
        if not isinstance(item, Mapping):
            raise SupplyChainError(f"{what}: each tool entry must be an object")
        name = str(item.get("name", ""))
        if not name:
            raise SupplyChainError(f"{what}: a tool entry has no name")
        if name in seen:
            raise SupplyChainError(f"{what}: tool {name!r} is recorded twice")
        seen.add(name)
        version = str(item.get("version", ""))
        if not version:
            raise SupplyChainError(
                f"{what}: tool {name!r} has no version. A named tool with no version is not pinned"
            )
        classification = str(item.get("classification", "unknown"))
        if classification not in TOOL_CLASSES:
            raise SupplyChainError(
                f"{what}: tool {name!r} classification {classification!r} must be one of "
                + ", ".join(TOOL_CLASSES)
            )
        reason = str(item.get("reason", ""))
        if classification in NON_BLOCKING_TOOL_CLASSES and not reason:
            raise SupplyChainError(
                f"{what}: tool {name!r} is classified {classification!r} with no reason. A "
                "classification that lets two builders differ must say why the difference cannot "
                "reach the artifact"
            )
        tools.append(
            ToolRecord(
                name=name,
                version=version,
                classification=classification,
                reason=reason,
                packageChecksum=str(item.get("packageChecksum", "")),
            )
        )

    missing = [name for name in PINNED_TOOLS if name not in seen]
    unresolved = [name for name in missing if name not in _optional_tools(record)]
    if unresolved:
        raise SupplyChainError(
            f"{what}: these tools are neither pinned nor declared absent: "
            + ", ".join(sorted(unresolved))
            + ". A tool that is present at build time and absent from the lock is unpinned"
        )

    status = str(_require(record, "verificationStatus", what=what))
    if status not in ("verified", "failed"):
        raise SupplyChainError(f"{what}: verificationStatus must be 'verified' or 'failed'")

    return BuilderImageLock(
        schemaVersion=SCHEMA_VERSION,
        builderReference=builder_ref,
        builderDigest=builder_digest,
        baseReference=base_ref,
        baseDigest=base_digest,
        sourceCommit=commit,
        containerfileDigest=containerfile,
        architecture=str(_require(record, "architecture", what=what)),
        tools=tuple(tools),
        builtAt=_timestamp(_require(record, "builtAt", what=what), what=what, field_name="builtAt"),
        verificationStatus=status,
        runtimeRequirements=dict(record.get("runtimeRequirements") or {}),
        notes=str(record.get("notes", "")),
    )


def _optional_tools(record: Mapping[str, Any]) -> frozenset[str]:
    """Tools the lock explicitly declares absent, with a stated reason."""
    declared = record.get("absentTools") or {}
    if not isinstance(declared, Mapping):
        raise SupplyChainError("builder-image-lock: absentTools must be an object of name -> reason")
    for name, reason in declared.items():
        if not str(reason).strip():
            raise SupplyChainError(
                f"builder-image-lock: absentTools[{name!r}] has no reason. Declaring a tool absent "
                "without saying why is indistinguishable from forgetting to pin it"
            )
    return frozenset(str(name) for name in declared)


# --------------------------------------------------------------------------
# Package snapshot
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PackageRecord:
    name: str
    epoch: str
    version: str
    release: str
    architecture: str
    checksum: str
    size: int
    sourceRepository: str
    signingKey: str
    signatureVerified: bool
    sourceRpm: str = ""
    licence: str = ""
    location: str = ""

    @property
    def nevra(self) -> str:
        epoch = f"{self.epoch}:" if self.epoch not in ("", "0", None) else ""
        return f"{self.name}-{epoch}{self.version}-{self.release}.{self.architecture}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "epoch": self.epoch,
            "version": self.version,
            "release": self.release,
            "architecture": self.architecture,
            "checksum": self.checksum,
            "size": self.size,
            "sourceRepository": self.sourceRepository,
            "signingKey": self.signingKey,
            "signatureVerified": self.signatureVerified,
            "sourceRpm": self.sourceRpm,
            "licence": self.licence,
            "location": self.location,
            "nevra": self.nevra,
        }


_REQUIRED_PACKAGE_FIELDS = (
    "name",
    "version",
    "release",
    "architecture",
    "checksum",
    "size",
    "sourceRepository",
    "signingKey",
)


def parse_package_record(item: Mapping[str, Any], *, what: str) -> PackageRecord:
    if not isinstance(item, Mapping):
        raise SupplyChainError(f"{what}: each package entry must be an object")
    missing = [name for name in _REQUIRED_PACKAGE_FIELDS if item.get(name) in (None, "")]
    if missing:
        raise SupplyChainError(
            f"{what}: package {item.get('name', '<unnamed>')!r} is missing "
            + ", ".join(sorted(missing))
        )
    checksum = str(item["checksum"])
    if not BARE_DIGEST.match(checksum) and not DIGEST.match(checksum):
        raise SupplyChainError(
            f"{what}: package {item['name']!r} checksum {checksum!r} is not a SHA-256 digest"
        )
    verified = item.get("signatureVerified")
    if verified is not True:
        raise SupplyChainError(
            f"{what}: package {item['name']!r} does not record signatureVerified=true. Every RPM "
            "must retain its original trusted signature and that signature must have been checked"
        )
    return PackageRecord(
        name=str(item["name"]),
        epoch=str(item.get("epoch", "0")),
        version=str(item["version"]),
        release=str(item["release"]),
        architecture=str(item["architecture"]),
        checksum=checksum.removeprefix("sha256:"),
        size=int(item["size"]),
        sourceRepository=str(item["sourceRepository"]),
        signingKey=str(item["signingKey"]),
        signatureVerified=True,
        sourceRpm=str(item.get("sourceRpm", "")),
        licence=str(item.get("licence", "")),
        location=str(item.get("location", "")),
    )


@dataclass(frozen=True)
class PackageSnapshotLock:
    schemaVersion: int
    snapshotId: str
    profile: str
    architecture: str
    packages: tuple[PackageRecord, ...]
    repositoryMetadataDigest: str
    manifestDigest: str
    signature: Mapping[str, Any]
    createdAt: str
    retainedLocation: str
    verificationStatus: str
    upstreamRepositories: tuple[str, ...] = ()

    @property
    def nevras(self) -> tuple[str, ...]:
        return tuple(sorted(p.nevra for p in self.packages))

    def as_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schemaVersion,
            "snapshotId": self.snapshotId,
            "profile": self.profile,
            "architecture": self.architecture,
            "packageCount": len(self.packages),
            "packages": [p.as_dict() for p in self.packages],
            "repositoryMetadataDigest": self.repositoryMetadataDigest,
            "manifestDigest": self.manifestDigest,
            "signature": dict(self.signature),
            "createdAt": self.createdAt,
            "retainedLocation": self.retainedLocation,
            "upstreamRepositories": list(self.upstreamRepositories),
            "verificationStatus": self.verificationStatus,
        }


def parse_package_snapshot_lock(record: Mapping[str, Any]) -> PackageSnapshotLock:
    what = "package-snapshot-lock"
    if not isinstance(record, Mapping):
        raise SupplyChainError(f"{what} must be an object")
    if int(_require(record, "schemaVersion", what=what)) != SCHEMA_VERSION:
        raise SupplyChainError(f"{what}: schemaVersion must be {SCHEMA_VERSION}")

    packages_raw = _require(record, "packages", what=what)
    if not isinstance(packages_raw, Sequence) or isinstance(packages_raw, (str, bytes)):
        raise SupplyChainError(f"{what}: packages must be an array")
    packages = tuple(parse_package_record(item, what=what) for item in packages_raw)

    seen: set[str] = set()
    for package in packages:
        if package.nevra in seen:
            raise SupplyChainError(f"{what}: package {package.nevra} is recorded twice")
        seen.add(package.nevra)

    signature = record.get("signature")
    if not isinstance(signature, Mapping) or not signature.get("value"):
        raise SupplyChainError(
            f"{what}: the snapshot manifest must be signed. An unsigned snapshot manifest can be "
            "edited without detection, which is the whole point of pinning one"
        )
    if str(signature.get("role", "")) != "snapshot-signing":
        raise SupplyChainError(f"{what}: signature.role must be 'snapshot-signing'")
    if signature.get("trust") not in ("development", "production"):
        raise SupplyChainError(
            f"{what}: signature.trust must state 'development' or 'production'. A development key "
            "must never be silently read as production trust"
        )

    metadata_digest = str(_require(record, "repositoryMetadataDigest", what=what))
    if not BARE_DIGEST.match(metadata_digest):
        raise SupplyChainError(f"{what}: repositoryMetadataDigest must be 64 hex characters")
    manifest_digest = str(_require(record, "manifestDigest", what=what))
    if not BARE_DIGEST.match(manifest_digest):
        raise SupplyChainError(f"{what}: manifestDigest must be 64 hex characters")

    status = str(_require(record, "verificationStatus", what=what))
    if status not in ("verified", "failed"):
        raise SupplyChainError(f"{what}: verificationStatus must be 'verified' or 'failed'")

    return PackageSnapshotLock(
        schemaVersion=SCHEMA_VERSION,
        snapshotId=str(_require(record, "snapshotId", what=what)),
        profile=str(_require(record, "profile", what=what)),
        architecture=str(_require(record, "architecture", what=what)),
        packages=packages,
        repositoryMetadataDigest=metadata_digest,
        manifestDigest=manifest_digest,
        signature=dict(signature),
        createdAt=_timestamp(
            _require(record, "createdAt", what=what), what=what, field_name="createdAt"
        ),
        retainedLocation=str(_require(record, "retainedLocation", what=what)),
        verificationStatus=status,
        upstreamRepositories=tuple(str(r) for r in record.get("upstreamRepositories") or ()),
    )


# --------------------------------------------------------------------------
# Build epoch
# --------------------------------------------------------------------------

#: Where a declared epoch may legitimately be applied. Anything not listed here
#: keeps real time, because a build-output timestamp and an evidence timestamp
#: are different concepts and conflating them falsifies the evidence.
EPOCH_APPLICABLE = (
    "container-image-config-created",
    "oci-archive-entry-mtimes",
    "rpm-transaction-install-time",
    "font-directory-mtimes",
    "generated-file-mtimes",
)

#: Where it must never be applied. Each of these is a security decision that
#: depends on the real clock.
EPOCH_FORBIDDEN = (
    "certificate-validity",
    "security-advisory-freshness",
    "package-signature-verification",
    "update-metadata-expiry",
    "evidence-timestamps",
)


@dataclass(frozen=True)
class ReproducibilityLock:
    schemaVersion: int
    candidateCommit: str
    sourceDateEpoch: int
    epochSource: str
    profile: str
    architecture: str
    baseImageDigest: str
    retainedBaseDigest: str
    builderImageDigest: str
    packageSnapshotDigest: str
    appliedTo: tuple[str, ...]
    neverAppliedTo: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schemaVersion,
            "candidateCommit": self.candidateCommit,
            "sourceDateEpoch": self.sourceDateEpoch,
            "epochSource": self.epochSource,
            "profile": self.profile,
            "architecture": self.architecture,
            "baseImageDigest": self.baseImageDigest,
            "retainedBaseDigest": self.retainedBaseDigest,
            "builderImageDigest": self.builderImageDigest,
            "packageSnapshotDigest": self.packageSnapshotDigest,
            "appliedTo": list(self.appliedTo),
            "neverAppliedTo": list(self.neverAppliedTo),
        }


def parse_reproducibility_lock(record: Mapping[str, Any]) -> ReproducibilityLock:
    what = "reproducibility-lock"
    if not isinstance(record, Mapping):
        raise SupplyChainError(f"{what} must be an object")
    if int(_require(record, "schemaVersion", what=what)) != SCHEMA_VERSION:
        raise SupplyChainError(f"{what}: schemaVersion must be {SCHEMA_VERSION}")

    commit = str(_require(record, "candidateCommit", what=what))
    if not COMMIT.match(commit):
        raise SupplyChainError(f"{what}: candidateCommit must be a full 40-character SHA")

    epoch = _require(record, "sourceDateEpoch", what=what)
    try:
        epoch_value = int(epoch)
    except (TypeError, ValueError):
        raise SupplyChainError(f"{what}: sourceDateEpoch must be an integer") from None
    if epoch_value <= 0:
        raise SupplyChainError(f"{what}: sourceDateEpoch must be a positive Unix timestamp")

    applied = tuple(str(v) for v in record.get("appliedTo") or ())
    if not applied:
        raise SupplyChainError(
            f"{what}: appliedTo must name where the epoch is used. An epoch applied to an "
            "unrecorded set of things cannot be reviewed"
        )
    unknown_applied = sorted(set(applied) - set(EPOCH_APPLICABLE))
    if unknown_applied:
        raise SupplyChainError(
            f"{what}: appliedTo names sites that are not declared epoch-applicable: "
            + ", ".join(unknown_applied)
        )
    forbidden = sorted(set(applied) & set(EPOCH_FORBIDDEN))
    if forbidden:
        raise SupplyChainError(
            f"{what}: the build epoch must never be applied to: "
            + ", ".join(forbidden)
            + ". Falsifying these would trade a security decision for a matching digest"
        )

    never = tuple(str(v) for v in record.get("neverAppliedTo") or ())
    missing_forbidden = sorted(set(EPOCH_FORBIDDEN) - set(never))
    if missing_forbidden:
        raise SupplyChainError(
            f"{what}: neverAppliedTo must list every forbidden site explicitly; missing: "
            + ", ".join(missing_forbidden)
        )

    return ReproducibilityLock(
        schemaVersion=SCHEMA_VERSION,
        candidateCommit=commit,
        sourceDateEpoch=epoch_value,
        epochSource=str(_require(record, "epochSource", what=what)),
        profile=str(_require(record, "profile", what=what)),
        architecture=str(_require(record, "architecture", what=what)),
        baseImageDigest=str(_require(record, "baseImageDigest", what=what)),
        retainedBaseDigest=str(_require(record, "retainedBaseDigest", what=what)),
        builderImageDigest=str(_require(record, "builderImageDigest", what=what)),
        packageSnapshotDigest=str(_require(record, "packageSnapshotDigest", what=what)),
        appliedTo=applied,
        neverAppliedTo=never,
    )


# --------------------------------------------------------------------------
# Cross-lock consistency, and the independence decision
# --------------------------------------------------------------------------


def toolchain_mismatches(
    first: Mapping[str, str],
    second: Mapping[str, str],
    *,
    classifications: Mapping[str, str],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Split tool-version differences into blocking, recorded, and unclassified.

    Returns ``(blocking, recorded, unclassified)``. A tool present on one side
    and absent on the other counts as a difference: "absent" is a version.
    """
    names = sorted(set(first) | set(second))
    blocking: list[str] = []
    recorded: list[str] = []
    unclassified: list[str] = []
    for name in names:
        left, right = first.get(name, "<absent>"), second.get(name, "<absent>")
        if left == right:
            continue
        classification = classifications.get(name, "unknown")
        if classification == "unknown":
            unclassified.append(name)
        elif classification in NON_BLOCKING_TOOL_CLASSES:
            recorded.append(name)
        else:
            blocking.append(name)
    return tuple(blocking), tuple(recorded), tuple(unclassified)


@dataclass(frozen=True)
class SupplyChainVerdict:
    result: str
    checks: tuple[tuple[str, bool, str], ...]

    @property
    def passed(self) -> bool:
        return self.result == "PASS"

    def as_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "result": self.result,
            "checks": [
                {"name": name, "ok": ok, "detail": detail} for name, ok, detail in self.checks
            ],
            "failed": [name for name, ok, _ in self.checks if not ok],
            "note": (
                "Every check fails closed. An absent lock is not a passing check: a build whose "
                "inputs were never recorded cannot be shown to have used the recorded inputs."
            ),
        }


def evaluate_input_locks(
    *,
    base: BaseImageLock | None,
    builder: BuilderImageLock | None,
    snapshot: PackageSnapshotLock | None,
    reproducibility: ReproducibilityLock | None,
) -> SupplyChainVerdict:
    """Whether the four input locks exist, verify, and agree with each other."""
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append((name, ok, detail))

    check(
        "base-image-lock-present",
        base is not None,
        "the retained base image lock is required; a build with no recorded base cannot be verified"
        if base is None
        else f"{base.retainedReference}",
    )
    check(
        "builder-image-lock-present",
        builder is not None,
        "the builder image lock is required" if builder is None else f"{builder.builderReference}",
    )
    check(
        "package-snapshot-lock-present",
        snapshot is not None,
        "the package snapshot lock is required"
        if snapshot is None
        else f"{snapshot.snapshotId} ({len(snapshot.packages)} packages)",
    )
    check(
        "reproducibility-lock-present",
        reproducibility is not None,
        "the reproducibility lock is required"
        if reproducibility is None
        else f"epoch {reproducibility.sourceDateEpoch}",
    )

    if base is not None:
        check(
            "base-verified",
            base.verificationStatus == "verified",
            f"verificationStatus={base.verificationStatus}",
        )
    if builder is not None:
        check(
            "builder-verified",
            builder.verificationStatus == "verified",
            f"verificationStatus={builder.verificationStatus}",
        )
        unknown = builder.unknownTools
        check(
            "builder-tools-classified",
            not unknown,
            "every pinned tool is classified"
            if not unknown
            else "unclassified tools block: " + ", ".join(unknown),
        )
    if snapshot is not None:
        check(
            "snapshot-verified",
            snapshot.verificationStatus == "verified",
            f"verificationStatus={snapshot.verificationStatus}",
        )
        unsigned = [p.nevra for p in snapshot.packages if not p.signatureVerified]
        check(
            "snapshot-signatures-verified",
            not unsigned,
            "every RPM retains a verified signature"
            if not unsigned
            else f"{len(unsigned)} packages without a verified signature",
        )

    if reproducibility is not None:
        if base is not None:
            check(
                "epoch-lock-names-retained-base",
                reproducibility.retainedBaseDigest == base.retainedDigest,
                f"{reproducibility.retainedBaseDigest} vs {base.retainedDigest}",
            )
        if builder is not None:
            check(
                "epoch-lock-names-builder-image",
                reproducibility.builderImageDigest == builder.builderDigest,
                f"{reproducibility.builderImageDigest} vs {builder.builderDigest}",
            )
        if snapshot is not None:
            check(
                "epoch-lock-names-snapshot",
                reproducibility.packageSnapshotDigest == snapshot.manifestDigest,
                f"{reproducibility.packageSnapshotDigest} vs {snapshot.manifestDigest}",
            )
        if base is not None:
            wanted = normalise_architecture(reproducibility.architecture)
            retained = {normalise_architecture(name) for name in base.architectures}
            selected = normalise_architecture(base.selectedArchitecture)
            if wanted != selected:
                check(
                    "architecture-retained",
                    False,
                    f"the build targets {wanted} and the mirror selected {selected}; a build "
                    "against the wrong architecture's manifest must fail before it starts",
                )
            elif wanted not in retained:
                check(
                    "architecture-retained",
                    False,
                    f"{wanted} is not among the retained architectures "
                    + ", ".join(sorted(retained)),
                )
            else:
                check(
                    "architecture-retained",
                    True,
                    f"{wanted} (recorded upstream as {base.selectedArchitecture})",
                )

    failed = [name for name, ok, _ in checks if not ok]
    return SupplyChainVerdict(
        result="BLOCKED" if failed else "PASS",
        checks=tuple(checks),
    )


def load(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_optional(path: str | Path) -> Any | None:
    location = Path(path)
    if not location.is_file():
        return None
    return json.loads(location.read_text(encoding="utf-8"))


__all__ = [
    "normalise_architecture",
    "DIGEST_PINNED",
    "EPOCH_APPLICABLE",
    "EPOCH_FORBIDDEN",
    "NON_BLOCKING_TOOL_CLASSES",
    "PINNED_TOOLS",
    "SCHEMA_VERSION",
    "TOOL_CLASSES",
    "BaseImageLock",
    "BuilderImageLock",
    "ManifestRecord",
    "PackageRecord",
    "PackageSnapshotLock",
    "ReproducibilityLock",
    "SupplyChainError",
    "SupplyChainVerdict",
    "ToolRecord",
    "evaluate_input_locks",
    "load",
    "load_optional",
    "parse_base_image_lock",
    "parse_builder_image_lock",
    "parse_package_record",
    "parse_package_snapshot_lock",
    "parse_reproducibility_lock",
    "toolchain_mismatches",
]
