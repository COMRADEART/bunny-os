# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Acquisition of Fedora sources, binaries and debuginfo, by manifest.

Answering "is the vulnerable function in the shipped binary" needs the shipped
binary, the source it was built from, and the debuginfo that maps between them.
None of those can live in this repository: a single podman debuginfo package is
larger than the entire source tree.

So the repository stores the *manifest* — what was fetched, from where, at what
version, with what checksum — and the artifacts live outside it. That makes the
acquisition auditable without making the repository unusable, and it makes one
specific fraud impossible: a manifest naming a package version that is not the
installed version is rejected, so an analysis cannot be performed against a
convenient build and reported against the shipped one.

Two constraints are enforced rather than documented:

**Trusted repositories only.** Fedora's own infrastructure, and nothing else. A
debuginfo RPM from an arbitrary mirror is an arbitrary binary, and the analysis
that rests on it is worth exactly as much as the host that served it.

**Exact version and architecture matching.** ``podman-5.8.4-1.fc44.x86_64`` is
analysed with ``podman-debuginfo-5.8.4-1.fc44.x86_64`` and nothing else. Off-by-one
release numbers are the ``source and binary version mismatch`` adversarial case.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse

SCHEMA_VERSION = 1

#: Hosts that may serve an artifact used in a reachability analysis. Fedora's
#: own infrastructure only. Adding to this list is a security decision.
TRUSTED_HOSTS = (
    "dl.fedoraproject.org",
    "download.fedoraproject.org",
    "kojipkgs.fedoraproject.org",
    "koji.fedoraproject.org",
    "src.fedoraproject.org",
    "debuginfod.fedoraproject.org",
    "mirrors.fedoraproject.org",
)

#: The nine artifact kinds an analysis may need.
ARTIFACT_KINDS = (
    "source-rpm",
    "binary-rpm",
    "debuginfo-rpm",
    "debugsource-rpm",
    "package-metadata",
    "changelog",
    "build-id",
    "spec-file",
    "applied-patches",
)

#: Kinds without which a "Not present" or "Present but unreachable" conclusion
#: cannot be reached for a stripped binary.
KINDS_REQUIRED_FOR_MAPPING = ("binary-rpm", "source-rpm", "debuginfo-rpm", "debugsource-rpm")

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
#: An RPM NEVRA: name-version-release.arch
_NEVRA = re.compile(r"^(?P<name>[A-Za-z0-9._+\-]+?)-(?P<version>[0-9][^-]*)-(?P<release>[^-]+)\.(?P<arch>[a-z0-9_]+)$")

ARCHITECTURES = ("x86-64", "x86_64", "noarch", "src")


class AcquisitionError(ValueError):
    """Raised when an acquisition record is malformed or untrusted."""


def _normalise_arch(value: str) -> str:
    return "x86_64" if value in {"x86-64", "x86_64"} else value


def parse_nevra(nevra: str) -> dict[str, str]:
    match = _NEVRA.match(nevra.strip())
    if not match:
        raise AcquisitionError(
            f"{nevra!r} is not an RPM name-version-release.arch; an approximate package name cannot "
            "be matched against an installed version"
        )
    return match.groupdict()


@dataclass(frozen=True)
class AcquisitionRecord:
    kind: str
    nevra: str
    packageName: str
    version: str
    release: str
    architecture: str
    repository: str
    url: str
    sha256: str
    sizeBytes: int
    acquiredAt: str
    repositoryMetadataDigest: str
    storedOutsideRepository: bool
    notes: str = ""

    @property
    def upstreamVersion(self) -> str:
        return self.version

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "nevra": self.nevra,
            "packageName": self.packageName,
            "version": self.version,
            "release": self.release,
            "architecture": self.architecture,
            "repository": self.repository,
            "url": self.url,
            "sha256": self.sha256,
            "sizeBytes": self.sizeBytes,
            "acquiredAt": self.acquiredAt,
            "repositoryMetadataDigest": self.repositoryMetadataDigest,
            "storedOutsideRepository": self.storedOutsideRepository,
            "notes": self.notes,
        }


def parse_acquisition(record: Mapping[str, Any]) -> AcquisitionRecord:
    """Validate one acquisition manifest entry."""
    if not isinstance(record, Mapping):
        raise AcquisitionError("acquisition record must be an object")

    required = (
        "kind",
        "nevra",
        "repository",
        "url",
        "sha256",
        "sizeBytes",
        "acquiredAt",
        "repositoryMetadataDigest",
    )
    missing = [name for name in required if record.get(name) in (None, "")]
    if missing:
        raise AcquisitionError(f"acquisition record missing fields: {', '.join(sorted(missing))}")

    kind = str(record["kind"])
    if kind not in ARTIFACT_KINDS:
        raise AcquisitionError(f"kind must be one of {', '.join(ARTIFACT_KINDS)}")

    nevra = str(record["nevra"])
    parts = parse_nevra(nevra)
    architecture = _normalise_arch(parts["arch"])
    if architecture not in {_normalise_arch(name) for name in ARCHITECTURES}:
        raise AcquisitionError(
            f"{nevra}: architecture {parts['arch']!r} is not analysed by this project; the shipped "
            "image is x86_64"
        )

    url = str(record["url"])
    host = (urlparse(url).hostname or "").casefold()
    if host not in TRUSTED_HOSTS:
        raise AcquisitionError(
            f"{nevra}: {url} is served by {host or 'no host'}, which is not Fedora infrastructure. "
            "An analysis resting on an arbitrary third-party binary is worth what that host is worth. "
            f"Trusted hosts: {', '.join(TRUSTED_HOSTS)}"
        )

    digest = str(record["sha256"])
    if not _SHA256.match(digest):
        raise AcquisitionError(f"{nevra}: sha256 must be a 64-character hex digest")
    metadata_digest = str(record["repositoryMetadataDigest"])
    if not _SHA256.match(metadata_digest):
        raise AcquisitionError(
            f"{nevra}: repositoryMetadataDigest must be the SHA-256 of the repomd.xml the package "
            "was resolved against; without it the repository state is unrecorded"
        )

    try:
        size = int(record["sizeBytes"])
    except (TypeError, ValueError):
        raise AcquisitionError(f"{nevra}: sizeBytes must be an integer") from None
    if size <= 0:
        raise AcquisitionError(f"{nevra}: sizeBytes must be positive")

    stored_outside = record.get("storedOutsideRepository")
    if stored_outside is not True:
        raise AcquisitionError(
            f"{nevra}: storedOutsideRepository must be true. RPMs are not committed to this "
            "repository; the manifest and checksum are the committed evidence"
        )

    return AcquisitionRecord(
        kind=kind,
        nevra=nevra,
        packageName=parts["name"],
        version=parts["version"],
        release=parts["release"],
        architecture=architecture,
        repository=str(record["repository"]),
        url=url,
        sha256=digest,
        sizeBytes=size,
        acquiredAt=str(record["acquiredAt"]),
        repositoryMetadataDigest=metadata_digest,
        storedOutsideRepository=True,
        notes=str(record.get("notes", "")),
    )


def match_installed(record: AcquisitionRecord, *, installedNevra: str) -> tuple[bool, str]:
    """Whether an acquired artifact corresponds to the installed package.

    The debuginfo and debugsource packages carry the *same* version and release as
    the binary they describe, with a suffixed name. Anything else is a different
    build and cannot map source to binary.
    """
    installed = parse_nevra(installedNevra)
    expected_names = {
        installed["name"],
        f"{installed['name']}-debuginfo",
        f"{installed['name']}-debugsource",
        f"{installed['name']}-debuginfo-common",
    }
    if record.packageName not in expected_names:
        return False, (
            f"{record.nevra} names package {record.packageName!r}, which is not {installed['name']!r} "
            "or one of its debug subpackages"
        )
    if record.version != installed["version"] or record.release != installed["release"]:
        return False, (
            f"{record.nevra} is version {record.version}-{record.release} but the installed package "
            f"is {installed['version']}-{installed['release']}. An analysis of a different build "
            "establishes nothing about the shipped binary"
        )
    if record.kind != "source-rpm" and _normalise_arch(record.architecture) not in {
        _normalise_arch(installed["arch"]), "noarch"
    }:
        return False, (
            f"{record.nevra} is {record.architecture} but the installed package is {installed['arch']}"
        )
    return True, "corresponds to the installed package"


def evaluate_manifest(
    document: Mapping[str, Any],
    *,
    requiredKinds: Iterable[str] = KINDS_REQUIRED_FOR_MAPPING,
) -> dict[str, Any]:
    """Evaluate the acquisition manifest and report coverage per package."""
    if document.get("schemaVersion") != SCHEMA_VERSION:
        raise AcquisitionError(f"acquisition manifest schemaVersion must be {SCHEMA_VERSION}")
    targets = document.get("targets")
    if not isinstance(targets, list):
        raise AcquisitionError("acquisition manifest must carry a targets array")

    rows: list[dict[str, Any]] = []
    rejected: list[str] = []
    required = tuple(requiredKinds)

    for target in targets:
        if not isinstance(target, Mapping):
            rejected.append("target must be an object")
            continue
        installed = target.get("installedNevra")
        if not installed:
            rejected.append("target missing installedNevra")
            continue
        try:
            parse_nevra(str(installed))
        except AcquisitionError as exc:
            rejected.append(str(exc))
            continue

        acquired: list[AcquisitionRecord] = []
        for item in target.get("acquired", []):
            try:
                record = parse_acquisition(item)
            except AcquisitionError as exc:
                rejected.append(str(exc))
                continue
            ok, reason = match_installed(record, installedNevra=str(installed))
            if not ok:
                rejected.append(reason)
                continue
            acquired.append(record)

        present = {record.kind for record in acquired}
        rows.append(
            {
                "installedNevra": str(installed),
                "binaryPath": target.get("binaryPath"),
                "acquiredKinds": sorted(present),
                "missingKinds": sorted(set(required) - present),
                "complete": not (set(required) - present),
                "acquired": [record.as_dict() for record in acquired],
                "totalBytes": sum(record.sizeBytes for record in acquired),
            }
        )

    complete = [row for row in rows if row["complete"]]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "targetCount": len(rows),
        "completeTargets": [row["installedNevra"] for row in complete],
        "incompleteTargets": [row["installedNevra"] for row in rows if not row["complete"]],
        "rejected": rejected,
        "requiredKinds": list(required),
        "targets": rows,
        "totalBytesOutsideRepository": sum(row["totalBytes"] for row in rows),
        "result": "PASS" if complete and not rejected and len(complete) == len(rows) else "BLOCKED",
        "note": (
            "Artifacts are stored outside this repository; the manifest and checksums are the "
            "committed evidence. A missing debuginfo package blocks: an absent symbol in a stripped "
            "binary is not evidence of absent code, and debuginfo is how that question is answered."
        ),
    }


def acquisition_plan(targets: Iterable[Mapping[str, Any]], *, destination: str = "$BUNNY_CVE_CACHE") -> list[dict[str, Any]]:
    """Emit the exact commands that would acquire each target.

    A plan rather than an execution: this repository has no network access in the
    environments that run its gates, and a plan can be reviewed before it is run.
    """
    plan: list[dict[str, Any]] = []
    for target in targets:
        installed = str(target.get("installedNevra", ""))
        if not installed:
            continue
        parts = parse_nevra(installed)
        name = parts["name"]
        version_release = f"{parts['version']}-{parts['release']}"
        plan.append(
            {
                "installedNevra": installed,
                "binaryPath": target.get("binaryPath"),
                "commands": [
                    # --repo restricts resolution to Fedora's own repositories.
                    f"dnf download --destdir {destination} --repo fedora --repo updates {name}-{version_release}",
                    f"dnf download --source --destdir {destination} --repo fedora-source --repo updates-source {name}-{version_release}",
                    f"dnf debuginfo-install --downloadonly --destdir {destination} {name}-{version_release}",
                    f"dnf download --destdir {destination} --repo fedora-debuginfo --repo updates-debuginfo {name}-debugsource-{version_release}",
                    f"rpm -qi --changelog {name} > {destination}/{name}-changelog.txt",
                    f"rpm -q --queryformat '%{{SOURCERPM}}\\n' {name} > {destination}/{name}-sourcerpm.txt",
                    f"rpm2cpio {destination}/{name}-{version_release}.src.rpm | cpio -idmv '*.spec' '*.patch'",
                    f"eu-readelf -n {target.get('binaryPath', '<binary>')} | sed -n 's/.*Build ID: //p'",
                    f"sha256sum {destination}/*.rpm >> {destination}/SHA256SUMS",
                    f"curl -fsSL https://dl.fedoraproject.org/pub/fedora/linux/releases/44/Everything/x86_64/os/repodata/repomd.xml | sha256sum",
                ],
                "verification": [
                    "every downloaded file's sha256 must be recorded in the manifest",
                    "the repomd.xml digest must be recorded as repositoryMetadataDigest",
                    "rpm --checksig must pass on every RPM before it is opened",
                    "the NEVRA must equal the installed NEVRA, not merely the same upstream version",
                ],
            }
        )
    return plan


def load(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


__all__ = [
    "ARTIFACT_KINDS",
    "KINDS_REQUIRED_FOR_MAPPING",
    "TRUSTED_HOSTS",
    "AcquisitionError",
    "AcquisitionRecord",
    "acquisition_plan",
    "evaluate_manifest",
    "match_installed",
    "parse_acquisition",
    "parse_nevra",
]
