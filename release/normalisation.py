# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Deterministic normalisation of non-semantic archive properties.

``build/scripts/normalise-oci-archive.sh`` normalises an archive **in place** at
build time, so the build emits one deterministic artifact. This module does the
different job comparison needs: it produces a normalised *copy* and reports both
digests, leaving the original untouched.

That distinction is the point. A comparison that only ever sees normalised bytes
cannot tell the difference between "two builders produced the same image, packed
differently" and "two builders produced different images". So both digests are
always emitted, and :func:`classify_digest_pair` refuses to call a normalised
match a clean result while the raw digests differ without an explanation
attached.

What may be normalised is an allow-list, not a judgement call:

============================  ==========================================
Normalisable                  Why it carries no meaning
============================  ==========================================
``tarEntryOrder``             the order members appear in the stream
``entryTimestamps``           ``podman save`` stamps wall-clock mtimes
``ownershipMetadata``         the builder's uid
``groupMetadata``             the builder's gid
``ownerNames``                the builder's account names
``paxTimestampHeaders``       atime/ctime extended headers
``gzipTimestamp``             the mtime in a gzip member header
``filesystemTraversalOrder``  ``readdir`` order when packing a directory
============================  ==========================================

Everything else is semantic and normalising it would be falsification. The
deny-list is enforced rather than documented: :func:`assert_normalisation_scope`
raises on any request naming a protected property, so a future caller cannot
widen the scope by passing a longer list.
"""

from __future__ import annotations

from dataclasses import dataclass
import gzip
import hashlib
import io
from pathlib import Path
import tarfile
from typing import Any, Iterable, Mapping

SCHEMA_VERSION = 1

NORMALISABLE_PROPERTIES = (
    "tarEntryOrder",
    "entryTimestamps",
    "ownershipMetadata",
    "groupMetadata",
    "ownerNames",
    "paxTimestampHeaders",
    "gzipTimestamp",
    "filesystemTraversalOrder",
)

#: Normalising any of these would change what the artifact *is*. Named
#: explicitly so the refusal can say which line was crossed.
PROTECTED_PROPERTIES = (
    "binaryContents",
    "packageContents",
    "generatedConfiguration",
    "signatures",
    "manifests",
    "sourceCommitMetadata",
    "imageFilesystemDifferences",
)

#: The epoch normalised entries are stamped with. Zero rather than
#: SOURCE_DATE_EPOCH: this timestamp exists to be constant, not to be plausible.
NORMALISED_EPOCH = 0

_CHUNK = 1024 * 1024


class NormalisationError(ValueError):
    """Raised when normalisation is asked to alter something semantic."""


def assert_normalisation_scope(properties: Iterable[str]) -> tuple[str, ...]:
    """Validate a requested normalisation scope, returning it sorted."""
    requested = tuple(sorted(set(properties)))
    protected = [name for name in requested if name in PROTECTED_PROPERTIES]
    if protected:
        raise NormalisationError(
            "refusing to normalise semantic properties: "
            + ", ".join(protected)
            + ". Normalising these would hide a real difference between two builds"
        )
    unknown = [
        name for name in requested if name not in NORMALISABLE_PROPERTIES
    ]
    if unknown:
        raise NormalisationError(
            "unknown normalisation properties: "
            + ", ".join(unknown)
            + f". Normalisable properties are: {', '.join(NORMALISABLE_PROPERTIES)}"
        )
    return requested


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _open_source(path: Path) -> tuple[io.BufferedIOBase, bool]:
    """Return a readable stream over the tar bytes, and whether it was gzipped."""
    with Path(path).open("rb") as handle:
        magic = handle.read(2)
    if magic == b"\x1f\x8b":
        return gzip.open(path, "rb"), True  # type: ignore[return-value]
    return Path(path).open("rb"), False  # type: ignore[return-value]


def member_digests(path: Path) -> dict[str, str]:
    """Digest every regular member's *content*, keyed by member name.

    This is the semantic view of an archive: it is unaffected by entry order,
    timestamps and ownership, and it is affected by every byte that matters.
    """
    stream, _ = _open_source(Path(path))
    digests: dict[str, str] = {}
    try:
        with tarfile.open(fileobj=stream, mode="r|*") as archive:
            for member in archive:
                if not member.isfile():
                    # Directories, links and devices carry no content; their
                    # names and targets are compared as metadata instead.
                    digests[member.name] = f"<{member.type.decode() if isinstance(member.type, bytes) else member.type}>"
                    continue
                extracted = archive.extractfile(member)
                if extracted is None:  # pragma: no cover - defensive
                    digests[member.name] = "<unreadable>"
                    continue
                digest = hashlib.sha256()
                for chunk in iter(lambda: extracted.read(_CHUNK), b""):
                    digest.update(chunk)
                digests[member.name] = digest.hexdigest()
    finally:
        stream.close()
    return digests


@dataclass(frozen=True)
class NormalisationResult:
    source: str
    normalisedPath: str
    rawDigest: str
    normalisedDigest: str
    memberCount: int
    appliedProperties: tuple[str, ...]
    gzipped: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "source": self.source,
            "normalisedPath": self.normalisedPath,
            "rawDigest": self.rawDigest,
            "normalisedDigest": self.normalisedDigest,
            "memberCount": self.memberCount,
            "appliedProperties": list(self.appliedProperties),
            "gzipped": self.gzipped,
            "protectedProperties": list(PROTECTED_PROPERTIES),
            "note": (
                "The normalised digest is comparable between builders. The raw digest is not "
                "discarded: a normalised match with differing raw digests is a packing difference "
                "that must still be explained."
            ),
        }


def normalise_archive(source: Path, destination: Path) -> NormalisationResult:
    """Write a normalised copy of ``source`` to ``destination``.

    Member *contents* are copied byte for byte. Only the properties in
    :data:`NORMALISABLE_PROPERTIES` are rewritten.
    """
    source = Path(source)
    destination = Path(destination)
    if not source.is_file():
        raise NormalisationError(f"{source} does not exist")
    if destination.resolve() == source.resolve():
        raise NormalisationError(
            "normalisation must write to a separate path; overwriting the source would destroy "
            "the raw digest the comparison needs"
        )

    applied = assert_normalisation_scope(NORMALISABLE_PROPERTIES)
    raw_digest = file_digest(source)

    stream, gzipped = _open_source(source)
    try:
        with tarfile.open(fileobj=stream, mode="r|*") as archive:
            # Buffer contents rather than seeking: a streamed tar cannot be
            # re-read, and sorting entry order requires holding them.
            entries: list[tuple[tarfile.TarInfo, bytes | None]] = []
            for member in archive:
                payload: bytes | None = None
                if member.isfile():
                    handle = archive.extractfile(member)
                    payload = handle.read() if handle is not None else b""
                entries.append((member, payload))
    finally:
        stream.close()

    # tarEntryOrder + filesystemTraversalOrder: one deterministic order.
    entries.sort(key=lambda item: item[0].name)

    destination.parent.mkdir(parents=True, exist_ok=True)
    raw_sink = destination.open("wb")
    # filename="" matters. GzipFile infers the stored original filename from
    # fileobj.name and writes it into the gzip header, so two normalised copies
    # written to different paths would differ in their headers — a normaliser that
    # introduces variance of its own. Caught by normalising one archive to two
    # destinations and comparing.
    sink: Any = (
        gzip.GzipFile(filename="", fileobj=raw_sink, mode="wb", mtime=NORMALISED_EPOCH)
        if gzipped
        else raw_sink
    )
    try:
        # GNU format handles long names without emitting the varying pax
        # atime/ctime headers that posix format would.
        with tarfile.open(fileobj=sink, mode="w", format=tarfile.GNU_FORMAT) as output:
            for member, payload in entries:
                info = tarfile.TarInfo(member.name)
                info.size = member.size if payload is None else len(payload)
                info.mode = member.mode
                info.type = member.type
                info.linkname = member.linkname
                info.devmajor = member.devmajor
                info.devminor = member.devminor
                # entryTimestamps, ownershipMetadata, groupMetadata, ownerNames
                info.mtime = NORMALISED_EPOCH
                info.uid = 0
                info.gid = 0
                info.uname = ""
                info.gname = ""
                # paxTimestampHeaders
                info.pax_headers = {}
                output.addfile(info, io.BytesIO(payload) if payload is not None else None)
    finally:
        if sink is not raw_sink:
            sink.close()
        raw_sink.close()

    return NormalisationResult(
        source=str(source),
        normalisedPath=str(destination),
        rawDigest=raw_digest,
        normalisedDigest=file_digest(destination),
        memberCount=len(entries),
        appliedProperties=applied,
        gzipped=gzipped,
    )


def classify_digest_pair(
    *,
    rawDigests: tuple[str, str],
    normalisedDigests: tuple[str, str],
    memberDigests: tuple[Mapping[str, str], Mapping[str, str]],
    rawVarianceExplanation: str | None = None,
) -> dict[str, Any]:
    """Classify a two-builder archive comparison.

    A normalised match with differing raw digests is a real result — the archives
    carry the same content packed differently — but it is a *weaker* result than
    a raw match, and it is only reportable when the packing difference is
    explained. An unexplained raw difference is inconclusive, not reproducible.
    """
    raw_match = rawDigests[0] == rawDigests[1]
    normalised_match = normalisedDigests[0] == normalisedDigests[1]
    left, right = memberDigests
    differing = tuple(
        sorted(name for name in set(left) | set(right) if left.get(name) != right.get(name))
    )
    content_match = not differing

    reasons: list[str] = []
    if not content_match:
        outcome = "NON_REPRODUCIBLE"
        reasons.append(f"{len(differing)} archive member(s) differ in content")
    elif raw_match and normalised_match:
        outcome = "REPRODUCIBLE"
    elif normalised_match and not raw_match:
        if rawVarianceExplanation and rawVarianceExplanation.strip():
            outcome = "CONTENT_REPRODUCIBLE_ARCHIVE_VARIANCE"
            reasons.append(f"raw archive digests differ; explanation recorded: {rawVarianceExplanation.strip()}")
        else:
            outcome = "INCONCLUSIVE"
            reasons.append(
                "raw archive digests differ and no explanation is recorded. A normalised match "
                "does not excuse an unexplained raw difference"
            )
    else:
        outcome = "INCONCLUSIVE"
        reasons.append(
            "member contents match but the normalised digests differ, which should not happen; "
            "the normaliser or the member enumeration is wrong"
        )

    return {
        "schemaVersion": SCHEMA_VERSION,
        "rawDigests": list(rawDigests),
        "normalisedDigests": list(normalisedDigests),
        "rawDigestsMatch": raw_match,
        "normalisedDigestsMatch": normalised_match,
        "memberContentsMatch": content_match,
        "differingMembers": list(differing[:200]),
        "differingMemberCount": len(differing),
        "outcome": outcome,
        "reasons": reasons,
        "satisfiesProductionGate": outcome == "REPRODUCIBLE",
    }


__all__ = [
    "NORMALISABLE_PROPERTIES",
    "NORMALISED_EPOCH",
    "PROTECTED_PROPERTIES",
    "NormalisationError",
    "NormalisationResult",
    "assert_normalisation_scope",
    "classify_digest_pair",
    "file_digest",
    "member_digests",
    "normalise_archive",
]
