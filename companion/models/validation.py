# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Everything that must be true before an adapter is allowed near a runtime.

This runs *before* loading, always, and it is the only thing standing between a
directory somebody put on the machine and a model the Companion will use. So it
is written to the same rule as the rest of Bunny's trust code: gather **all**
the reasons rather than the first, name each one with a code a machine can
branch on, and never let "we could not check" become "it checked out".

Three statuses, in decreasing severity, and the report takes the worst:

``FAIL``
    a requirement was checked and is not met. The artifact is refused.
``UNKNOWN``
    a requirement could **not** be checked. Also refused for activation — this
    is the whole point. An adapter whose base revision cannot be verified, or
    whose base weights are not on this machine, is not activated on the grounds
    that nothing said no.
``PASS``
    every requirement was checked and met.

The checks, in the order they run — cheap and structural first, so a manifest
that names the wrong runtime is refused without hashing a megabyte:

1.  the manifest exists and parses (closed sections, required fields);
2.  the format version is one this build supports;
3.  the artifact directory is inside a trusted root and is not loosely moded;
4.  the directory name and ``modelId`` agree;
5.  ``intendedRuntime`` is this runtime;
6.  ``permissions`` is empty — see :data:`PERMISSIONS_NOT_GRANTABLE`;
7.  ``networkRequired`` is false;
8.  the adapter type is supported;
9.  the adapter format is one some available backend can apply;
10. the adapter file exists;
11. its SHA-256 matches, and its size if declared;
12. the base model identity and revision are compatible with the runtime's.

Check 6 is the one this milestone exists for. A manifest carrying a non-empty
``permissions`` array is not sanitised, ignored, or logged and accepted — it is
refused with :data:`PERMISSIONS_NOT_GRANTABLE`, because an artifact that tried
to bring capabilities with it is an artifact whose author misunderstood the
boundary badly enough that nothing else it says should be trusted either.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
import stat
from typing import Any, Sequence

from . import ARTIFACT_SCHEMA_VERSION, MANIFEST_FILE_NAME
from .artifact import (
    ADAPTER_FORMATS,
    ADAPTER_TYPES,
    INTENDED_RUNTIMES,
    ModelManifest,
    read_manifest,
)
from .errors import ModelArtifactError

__all__ = [
    "FAIL",
    "PASS",
    "UNKNOWN",
    "RuntimeExpectations",
    "ValidationFinding",
    "ValidationReport",
    "validate_artifact",
    "validate_manifest",
]

PASS = "PASS"
FAIL = "FAIL"
UNKNOWN = "UNKNOWN"

#: Worst-wins. A report is as bad as its worst finding.
_SEVERITY = {PASS: 0, UNKNOWN: 1, FAIL: 2}

# -- codes ------------------------------------------------------------------ #
# Named constants rather than literals so a caller branching on one cannot
# branch on a typo, and so the set is enumerable for the tests.

MANIFEST_MISSING = "MANIFEST_MISSING"
MANIFEST_UNREADABLE = "MANIFEST_UNREADABLE"
UNSUPPORTED_FORMAT_VERSION = "UNSUPPORTED_FORMAT_VERSION"
ARTIFACT_PATH_UNTRUSTED = "ARTIFACT_PATH_UNTRUSTED"
ARTIFACT_MODE_LOOSE = "ARTIFACT_MODE_LOOSE"
MODEL_ID_MISMATCH = "MODEL_ID_MISMATCH"
INTENDED_RUNTIME_MISMATCH = "INTENDED_RUNTIME_MISMATCH"
PERMISSIONS_NOT_GRANTABLE = "PERMISSIONS_NOT_GRANTABLE"
NETWORK_REQUIRED_REFUSED = "NETWORK_REQUIRED_REFUSED"
UNSUPPORTED_ADAPTER_TYPE = "UNSUPPORTED_ADAPTER_TYPE"
UNSUPPORTED_ADAPTER_FORMAT = "UNSUPPORTED_ADAPTER_FORMAT"
NO_BACKEND_FOR_FORMAT = "NO_BACKEND_FOR_FORMAT"
ADAPTER_FILE_MISSING = "ADAPTER_FILE_MISSING"
ADAPTER_CHECKSUM_MISMATCH = "ADAPTER_CHECKSUM_MISMATCH"
ADAPTER_SIZE_MISMATCH = "ADAPTER_SIZE_MISMATCH"
ADAPTER_UNREADABLE = "ADAPTER_UNREADABLE"
BASE_MODEL_MISMATCH = "BASE_MODEL_MISMATCH"
BASE_MODEL_NOT_PRESENT = "BASE_MODEL_NOT_PRESENT"
BASE_REVISION_MISMATCH = "BASE_REVISION_MISMATCH"
BASE_REVISION_UNVERIFIED = "BASE_REVISION_UNVERIFIED"
BASE_MODEL_UNVERIFIED = "BASE_MODEL_UNVERIFIED"
VALID = "VALID"

#: Every code this module can produce. The tests assert the set, so a new code
#: has to be added deliberately rather than appearing in a message somewhere.
CODES: tuple[str, ...] = (
    MANIFEST_MISSING, MANIFEST_UNREADABLE, UNSUPPORTED_FORMAT_VERSION,
    ARTIFACT_PATH_UNTRUSTED, ARTIFACT_MODE_LOOSE, MODEL_ID_MISMATCH,
    INTENDED_RUNTIME_MISMATCH, PERMISSIONS_NOT_GRANTABLE, NETWORK_REQUIRED_REFUSED,
    UNSUPPORTED_ADAPTER_TYPE, UNSUPPORTED_ADAPTER_FORMAT, NO_BACKEND_FOR_FORMAT,
    ADAPTER_FILE_MISSING, ADAPTER_CHECKSUM_MISMATCH, ADAPTER_SIZE_MISMATCH,
    ADAPTER_UNREADABLE, BASE_MODEL_MISMATCH, BASE_MODEL_NOT_PRESENT,
    BASE_REVISION_MISMATCH, BASE_REVISION_UNVERIFIED, BASE_MODEL_UNVERIFIED, VALID,
)

_READ_BLOCK = 1024 * 1024


@dataclass(frozen=True)
class ValidationFinding:
    """One checked requirement and how it came out."""

    status: str
    code: str
    message: str
    field: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "code": self.code,
            "message": self.message,
            "field": self.field,
        }


@dataclass(frozen=True)
class ValidationReport:
    """The verdict, and every reason behind it."""

    model_id: str
    path: str
    findings: tuple[ValidationFinding, ...]
    manifest: ModelManifest | None = None

    @property
    def status(self) -> str:
        return max((finding.status for finding in self.findings),
                   key=lambda value: _SEVERITY[value], default=PASS)

    @property
    def ok(self) -> bool:
        return self.status == PASS

    @property
    def decisive(self) -> ValidationFinding:
        """The finding a caller should show first: the worst, then the earliest."""
        worst = self.status
        for finding in self.findings:
            if finding.status == worst:
                return finding
        return ValidationFinding(PASS, VALID, "every requirement was checked and met")

    # The brief's single-object shape, so a caller that wants one answer has one.
    @property
    def code(self) -> str:
        return self.decisive.code

    @property
    def message(self) -> str:
        return self.decisive.message

    @property
    def field(self) -> str:
        return self.decisive.field

    def problems(self) -> tuple[ValidationFinding, ...]:
        return tuple(item for item in self.findings if item.status != PASS)

    def to_json(self) -> dict[str, Any]:
        return {
            "modelId": self.model_id,
            "path": self.path,
            "status": self.status,
            "code": self.code,
            "message": self.message,
            "field": self.field,
            "findings": [item.to_json() for item in self.findings],
            "checksRun": len(self.findings),
        }


@dataclass(frozen=True)
class RuntimeExpectations:
    """What the runtime knows, against which an artifact is judged.

    Every field is optional and absence is honest: a runtime that does not know
    which base model it is using cannot establish compatibility, and the report
    says ``UNKNOWN`` rather than passing the artifact through. That is why this
    is a value the caller supplies rather than something guessed here.
    """

    #: The base model the runtime will actually use, as an upstream identity.
    base_model_reference: str = ""
    #: Its exact revision, when the runtime can name one.
    base_model_revision: str = ""
    #: Its local file name in a trusted model directory, when applicable.
    base_model_file: str = ""
    #: Its digest, when the runtime has computed one.
    base_model_sha256: str = ""
    #: Whether the base weights are present on this machine. ``None`` means the
    #: caller did not look, which is not the same as "absent".
    base_model_present: bool | None = None
    #: Adapter formats some available backend declares it can apply.
    supported_formats: tuple[str, ...] = ADAPTER_FORMATS
    #: Directories an artifact may live under.
    trusted_roots: tuple[Path, ...] = ()
    #: Whether to enforce POSIX mode checks. Off on platforms with no such modes.
    check_modes: bool = os.name == "posix"

    def to_json(self) -> dict[str, Any]:
        return {
            "baseModelReference": self.base_model_reference,
            "baseModelRevision": self.base_model_revision,
            "baseModelFile": self.base_model_file,
            "baseModelPresent": self.base_model_present,
            "supportedFormats": list(self.supported_formats),
            "trustedRoots": [str(item) for item in self.trusted_roots],
        }


def _under_trusted_root(directory: Path, roots: Sequence[Path]) -> bool:
    resolved = directory.resolve()
    for root in roots:
        try:
            resolved.relative_to(Path(root).resolve())
        except (ValueError, OSError):
            continue
        return True
    return False


def _loose_mode(path: Path) -> bool:
    """Whether ``path`` is writable by group or other.

    The same refusal ``companion.agents.adapters.llamacli`` applies to a
    program: a writable adapter is nobody's adapter, because the digest in the
    manifest was true when it was written and says nothing about now.
    """
    try:
        info = path.stat()
    except OSError:
        return False
    return bool(info.st_mode & (stat.S_IWGRP | stat.S_IWOTH))


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(_READ_BLOCK), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_manifest(
    manifest: ModelManifest,
    *,
    expectations: RuntimeExpectations | None = None,
) -> tuple[ValidationFinding, ...]:
    """The checks that need only the manifest. No filesystem, no hashing."""
    wanted = expectations or RuntimeExpectations()
    findings: list[ValidationFinding] = []

    if manifest.schema_version != ARTIFACT_SCHEMA_VERSION:
        findings.append(ValidationFinding(
            FAIL, UNSUPPORTED_FORMAT_VERSION,
            f"artifact format version {manifest.schema_version} is not supported by this "
            f"build, which reads version {ARTIFACT_SCHEMA_VERSION}. It is refused rather "
            "than read on the assumption that the parts it recognises mean the same thing.",
            "schemaVersion",
        ))
    else:
        findings.append(ValidationFinding(
            PASS, VALID, f"format version {manifest.schema_version}", "schemaVersion"))

    if manifest.intended_runtime not in INTENDED_RUNTIMES:
        findings.append(ValidationFinding(
            FAIL, INTENDED_RUNTIME_MISMATCH,
            f"intended for {manifest.intended_runtime!r}; this runtime is "
            f"{INTENDED_RUNTIMES[0]!r}",
            "intendedRuntime",
        ))
    else:
        findings.append(ValidationFinding(
            PASS, VALID, f"intended for {manifest.intended_runtime}", "intendedRuntime"))

    # The check this milestone is about.
    if manifest.permissions:
        findings.append(ValidationFinding(
            FAIL, PERMISSIONS_NOT_GRANTABLE,
            "the manifest declares permissions "
            f"({', '.join(repr(item) for item in manifest.permissions)}). A model "
            "artifact cannot carry, request or imply a capability: authority comes "
            "from the trust layer, the capability system and the person using the "
            "machine. The artifact is refused rather than loaded with the field "
            "ignored, because an artifact that tried to bring permissions is one "
            "whose other claims are not worth reading.",
            "permissions",
        ))
    else:
        findings.append(ValidationFinding(
            PASS, VALID, "declares no permissions, as required", "permissions"))

    if manifest.network_required:
        findings.append(ValidationFinding(
            FAIL, NETWORK_REQUIRED_REFUSED,
            "the manifest declares it requires the network. Loading a model does not "
            "introduce network access, and an artifact is not where that decision is "
            "made.",
            "networkRequired",
        ))
    else:
        findings.append(ValidationFinding(
            PASS, VALID, "requires no network", "networkRequired"))

    if manifest.adapter_type not in ADAPTER_TYPES:
        findings.append(ValidationFinding(
            FAIL, UNSUPPORTED_ADAPTER_TYPE,
            f"adapter type {manifest.adapter_type!r} is not one of {ADAPTER_TYPES}",
            "adapterType",
        ))
    else:
        findings.append(ValidationFinding(
            PASS, VALID, f"adapter type {manifest.adapter_type}", "adapterType"))

    if manifest.adapter_format not in ADAPTER_FORMATS:
        findings.append(ValidationFinding(
            FAIL, UNSUPPORTED_ADAPTER_FORMAT,
            f"adapter format {manifest.adapter_format!r} is not one of {ADAPTER_FORMATS}",
            "adapterFormat",
        ))
    elif manifest.adapter_format not in wanted.supported_formats:
        # UNKNOWN, not FAIL, and the distinction is worth being consistent
        # about: FAIL means something is wrong with the *artifact*, UNKNOWN
        # means the artifact may be perfectly good and this machine cannot
        # establish or use it. "No backend can apply this format" is the same
        # category as "the base model is not on this machine" — a fact about
        # the machine — and both refuse activation just as firmly.
        findings.append(ValidationFinding(
            UNKNOWN, NO_BACKEND_FOR_FORMAT,
            f"the artifact is {manifest.adapter_format!r} and no available backend "
            f"declares it can apply that format (available: "
            f"{', '.join(wanted.supported_formats) or 'none'}). The artifact is "
            "well-formed; this runtime simply cannot use it.",
            "adapterFormat",
        ))
    else:
        findings.append(ValidationFinding(
            PASS, VALID, f"adapter format {manifest.adapter_format} is applicable here",
            "adapterFormat"))

    findings.extend(_base_model_findings(manifest, wanted))
    return tuple(findings)


def _base_model_findings(
    manifest: ModelManifest, wanted: RuntimeExpectations
) -> list[ValidationFinding]:
    """Base identity and revision, with "cannot tell" kept distinct from "wrong".

    A ladder, strongest rung first:

    1. **digest** — both sides name a SHA-256 for the base weights. This is
       identity, not a proxy for it, and it settles the revision question too:
       the bytes are the bytes, whatever anyone called the commit they came
       from. This is the rung a real deployment lands on, because the backend
       reports which file it loaded and the runtime can hash it.
    2. **reference** — an upstream identity string on both sides, then the
       revision compared separately, which may itself be ``UNKNOWN``.
    3. **neither** — ``UNKNOWN``. Not a pass.

    The ladder exists because the second rung cannot succeed in the one
    deployment that matters. An adapter trained against a Hugging Face revision
    and applied to a GGUF conversion of it has no revision string to compare;
    insisting on one would make every real configuration permanently
    unverifiable, which is a check that has stopped being a check.
    """
    findings: list[ValidationFinding] = []
    declared = manifest.base_model

    if declared.sha256 and wanted.base_model_sha256:
        if declared.sha256 != wanted.base_model_sha256:
            findings.append(ValidationFinding(
                FAIL, BASE_MODEL_MISMATCH,
                f"the artifact was exported against base weights with digest "
                f"{declared.sha256[:12]}… and the backend has loaded "
                f"{wanted.base_model_sha256[:12]}…. An adapter applied to different "
                "weights is a different model.",
                "baseModel.sha256",
            ))
            return findings
        findings.append(ValidationFinding(
            PASS, VALID,
            f"base weights match by digest ({declared.sha256[:12]}…), which settles "
            "identity and revision together",
            "baseModel.sha256",
        ))
        if wanted.base_model_reference and declared.reference.strip().lower() != \
                wanted.base_model_reference.strip().lower():
            findings.append(ValidationFinding(
                FAIL, BASE_MODEL_MISMATCH,
                f"the digests match but the names do not: artifact says "
                f"{declared.reference!r}, runtime says {wanted.base_model_reference!r}",
                "baseModel.reference",
            ))
        return findings

    if not wanted.base_model_reference:
        findings.append(ValidationFinding(
            UNKNOWN, BASE_MODEL_UNVERIFIED,
            f"the artifact names base model {declared.reference!r}; this check had no "
            "runtime base model to compare it against, so compatibility was not "
            "established. Not a pass: an adapter applied to the wrong base is a "
            "different model, not a worse one.",
            "baseModel.reference",
        ))
        return findings

    if declared.reference.strip().lower() != wanted.base_model_reference.strip().lower():
        findings.append(ValidationFinding(
            FAIL, BASE_MODEL_MISMATCH,
            f"the artifact was trained against {declared.reference!r} and the runtime "
            f"is using {wanted.base_model_reference!r}",
            "baseModel.reference",
        ))
        return findings

    findings.append(ValidationFinding(
        PASS, VALID, f"base model {declared.reference} matches the runtime's",
        "baseModel.reference"))

    if wanted.base_model_present is False:
        findings.append(ValidationFinding(
            UNKNOWN, BASE_MODEL_NOT_PRESENT,
            f"the base model {declared.reference!r} is not present on this machine. "
            "It is not fetched: a missing dependency is reported, never downloaded "
            "as a side effect of validating an adapter.",
            "baseModel.file",
        ))
        return findings

    if not declared.revision_is_pinned:
        findings.append(ValidationFinding(
            UNKNOWN, BASE_REVISION_UNVERIFIED,
            f"the artifact records base revision {declared.revision or '(absent)'!r}, "
            "which names something that moves rather than a fixed commit, so the "
            "revision it was trained against cannot be established.",
            "baseModel.revision",
        ))
    elif not wanted.base_model_revision:
        findings.append(ValidationFinding(
            UNKNOWN, BASE_REVISION_UNVERIFIED,
            f"the artifact pins base revision {declared.revision!r}; the runtime "
            "cannot say which revision its own base model is, so the two were not "
            "compared.",
            "baseModel.revision",
        ))
    elif declared.revision.strip() != wanted.base_model_revision.strip():
        findings.append(ValidationFinding(
            FAIL, BASE_REVISION_MISMATCH,
            f"the artifact pins base revision {declared.revision!r} and the runtime's "
            f"base model is {wanted.base_model_revision!r}",
            "baseModel.revision",
        ))
    else:
        findings.append(ValidationFinding(
            PASS, VALID, f"base revision {declared.revision} matches", "baseModel.revision"))

    if declared.sha256 and wanted.base_model_sha256:
        if declared.sha256 != wanted.base_model_sha256:
            findings.append(ValidationFinding(
                FAIL, BASE_MODEL_MISMATCH,
                "the artifact records a base-model digest that does not match the "
                "weights this runtime would use",
                "baseModel.sha256",
            ))
        else:
            findings.append(ValidationFinding(
                PASS, VALID, "base model digest matches", "baseModel.sha256"))
    return findings


def validate_artifact(
    directory: Path | str,
    *,
    expectations: RuntimeExpectations | None = None,
    verify_digest: bool = True,
) -> ValidationReport:
    """Validate an artifact directory end to end. Never raises for a bad artifact.

    ``verify_digest`` exists for the registry's listing path, which shows many
    artifacts and should not hash every adapter to draw a list. It defaults to
    ``True`` and the activation path never turns it off — a model is not enabled
    on the strength of a listing.
    """
    path = Path(directory)
    wanted = expectations or RuntimeExpectations()
    findings: list[ValidationFinding] = []

    try:
        manifest = read_manifest(path)
    except ModelArtifactError as exc:
        code = MANIFEST_MISSING if MANIFEST_FILE_NAME in str(exc) and "no " in str(exc) else MANIFEST_UNREADABLE
        return ValidationReport(
            model_id=path.name,
            path=str(path),
            findings=(ValidationFinding(FAIL, code, str(exc), "manifest"),),
        )

    if wanted.trusted_roots:
        if _under_trusted_root(path, wanted.trusted_roots):
            findings.append(ValidationFinding(
                PASS, VALID, "artifact is inside a trusted model directory", "path"))
        else:
            findings.append(ValidationFinding(
                FAIL, ARTIFACT_PATH_UNTRUSTED,
                f"{path} is not inside any trusted model directory "
                f"({', '.join(str(item) for item in wanted.trusted_roots)}). Bunny "
                "resolves model material against fixed directories, never against a "
                "path something else supplied.",
                "path",
            ))

    if wanted.check_modes and _loose_mode(path):
        findings.append(ValidationFinding(
            FAIL, ARTIFACT_MODE_LOOSE,
            f"{path} is group- or world-writable. A digest recorded in a manifest "
            "describes the bytes as they were; it says nothing about bytes anyone "
            "can replace.",
            "path",
        ))

    if manifest.model_id != path.name:
        findings.append(ValidationFinding(
            FAIL, MODEL_ID_MISMATCH,
            f"the manifest calls this model {manifest.model_id!r} and it is installed "
            f"as {path.name!r}. The registry keys on the directory name, so the two "
            "disagreeing means one of them is describing a different model.",
            "modelId",
        ))
    else:
        findings.append(ValidationFinding(PASS, VALID, f"model id {manifest.model_id}", "modelId"))

    findings.extend(validate_manifest(manifest, expectations=wanted))
    findings.extend(_adapter_findings(path, manifest, wanted, verify_digest))

    return ValidationReport(
        model_id=manifest.model_id,
        path=str(path),
        findings=tuple(findings),
        manifest=manifest,
    )


def _adapter_findings(
    path: Path, manifest: ModelManifest, wanted: RuntimeExpectations, verify_digest: bool
) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    adapter = path / manifest.adapter_file
    if not adapter.is_file():
        findings.append(ValidationFinding(
            FAIL, ADAPTER_FILE_MISSING,
            f"the manifest names adapter file {manifest.adapter_file!r} and it is not "
            f"in {path}",
            "adapterFile",
        ))
        return findings
    findings.append(ValidationFinding(
        PASS, VALID, f"adapter file {manifest.adapter_file} is present", "adapterFile"))

    if wanted.check_modes and _loose_mode(adapter):
        findings.append(ValidationFinding(
            FAIL, ARTIFACT_MODE_LOOSE,
            f"{adapter} is group- or world-writable", "adapterFile"))

    try:
        size = adapter.stat().st_size
    except OSError as exc:
        findings.append(ValidationFinding(
            FAIL, ADAPTER_UNREADABLE, f"cannot stat {adapter}: {exc}", "adapterFile"))
        return findings

    if manifest.adapter_bytes and size != manifest.adapter_bytes:
        findings.append(ValidationFinding(
            FAIL, ADAPTER_SIZE_MISMATCH,
            f"the manifest records {manifest.adapter_bytes} bytes and the file is {size}",
            "adapterBytes",
        ))

    if not verify_digest:
        findings.append(ValidationFinding(
            UNKNOWN, ADAPTER_CHECKSUM_MISMATCH,
            "the adapter's digest was not computed for this listing; it is always "
            "computed before a model is activated",
            "adapterSha256",
        ))
        return findings

    try:
        actual = _digest(adapter)
    except OSError as exc:
        findings.append(ValidationFinding(
            FAIL, ADAPTER_UNREADABLE, f"cannot read {adapter}: {exc}", "adapterFile"))
        return findings

    if actual != manifest.adapter_sha256:
        findings.append(ValidationFinding(
            FAIL, ADAPTER_CHECKSUM_MISMATCH,
            f"the adapter's SHA-256 is {actual} and the manifest records "
            f"{manifest.adapter_sha256}. The bytes are not the bytes that were "
            "trained, exported and recorded.",
            "adapterSha256",
        ))
    else:
        findings.append(ValidationFinding(
            PASS, VALID, f"adapter digest matches ({actual[:12]}…)", "adapterSha256"))
    return findings
