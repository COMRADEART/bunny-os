# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Reading a manifest, strictly, without deciding anything about it.

This module parses. :mod:`companion.models.validation` judges. Keeping them
apart matters because "this file is not a manifest" and "this manifest
describes something we will not load" are different answers to different
questions, and a reader that conflates them ends up either raising at the wrong
layer or reporting a parse error as a security refusal.

Every section is closed. An unknown field is a refusal, following
:mod:`capsules.manifest` and :mod:`catalog.entry`, and the reason is sharper
here than tidiness: this document arrives from outside the image. A reader that
ignores fields it does not understand is a reader that can be handed a manifest
carrying something it will not look at.

Nothing in this module touches the adapter bytes, hashes anything, or reaches
the filesystem beyond reading the one file it was pointed at. Digest checking is
validation's job and happens after the shape is known to be sound, because
hashing a megabyte to then discover the manifest names the wrong field order is
work done in the wrong order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from typing import Any, Mapping

from . import ARTIFACT_SCHEMA_VERSION, MANIFEST_FILE_NAME
from .errors import ModelArtifactError

__all__ = [
    "ADAPTER_FORMATS",
    "ADAPTER_TYPES",
    "BaseModelReference",
    "INTENDED_RUNTIMES",
    "ModelManifest",
    "TrainingProvenance",
    "manifest_path_for",
    "parse_manifest",
    "read_manifest",
]

#: What this build knows how to describe. An artifact naming anything else is
#: refused by validation rather than attempted.
ADAPTER_TYPES: tuple[str, ...] = ("lora",)

#: On-disk encodings. ``gguf`` is what a llama.cpp backend can apply;
#: ``peft-safetensors`` is what Model Studio writes, and no backend shipped in
#: the image can apply it — an honest declaration, not a promise.
ADAPTER_FORMATS: tuple[str, ...] = ("gguf", "peft-safetensors")

INTENDED_RUNTIMES: tuple[str, ...] = ("companion",)

#: A manifest is small. Anything larger is not a manifest, and is refused
#: before a parser sees it.
_MAX_MANIFEST_BYTES = 64 * 1024

#: A model id is one path segment and can never widen into a path. The same
#: rule ``companion.agents.adapters.llamacli`` applies to model file names.
_MODEL_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_FILE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

_TOP_LEVEL_FIELDS = frozenset({
    "schemaVersion", "modelId", "displayName", "adapterType", "adapterFormat",
    "adapterFile", "adapterSha256", "adapterBytes", "baseModel", "training",
    "intendedRuntime", "networkRequired", "permissions", "notes",
})
_REQUIRED_FIELDS = (
    "schemaVersion", "modelId", "adapterType", "adapterFormat", "adapterFile",
    "adapterSha256", "baseModel", "intendedRuntime", "networkRequired", "permissions",
)
_BASE_MODEL_FIELDS = frozenset({
    "reference", "revision", "file", "sha256", "architecture", "parameterCount",
})
_TRAINING_FIELDS = frozenset({
    "createdBy", "createdAt", "jobId", "configSha256", "configCanonicalSha256",
    "datasetSha256", "datasetConversations", "bunnyCommit", "method", "precision",
    "steps", "finalLoss",
})

#: Revision strings that name something that moves. An adapter pinned to one of
#: these is pinned to nothing, and validation reports UNKNOWN rather than
#: pretending the base was verified.
MOVING_REVISIONS: frozenset[str] = frozenset({"", "main", "master", "head", "latest", "local-directory"})


@dataclass(frozen=True)
class BaseModelReference:
    """What the adapter modifies."""

    reference: str
    revision: str = ""
    file: str = ""
    sha256: str = ""
    architecture: str = ""
    parameter_count: int = 0

    @property
    def revision_is_pinned(self) -> bool:
        """Whether the revision names a fixed thing rather than a moving one."""
        return self.revision.strip().lower() not in MOVING_REVISIONS

    def to_json(self) -> dict[str, Any]:
        document: dict[str, Any] = {"reference": self.reference}
        if self.revision:
            document["revision"] = self.revision
        if self.file:
            document["file"] = self.file
        if self.sha256:
            document["sha256"] = self.sha256
        if self.architecture:
            document["architecture"] = self.architecture
        if self.parameter_count:
            document["parameterCount"] = self.parameter_count
        return document


@dataclass(frozen=True)
class TrainingProvenance:
    """Where the adapter came from. Recorded, never trusted as authority."""

    created_by: str = ""
    created_at: str = ""
    job_id: str = ""
    config_sha256: str = ""
    config_canonical_sha256: str = ""
    dataset_sha256: str = ""
    dataset_conversations: int = 0
    bunny_commit: str = ""
    method: str = ""
    precision: str = ""
    steps: int = 0
    final_loss: float | None = None

    def to_json(self) -> dict[str, Any]:
        document = {
            "createdBy": self.created_by,
            "createdAt": self.created_at,
            "jobId": self.job_id,
            "configSha256": self.config_sha256,
            "configCanonicalSha256": self.config_canonical_sha256,
            "datasetSha256": self.dataset_sha256,
            "datasetConversations": self.dataset_conversations,
            "bunnyCommit": self.bunny_commit,
            "method": self.method,
            "precision": self.precision,
            "steps": self.steps,
            "finalLoss": self.final_loss,
        }
        return {key: value for key, value in document.items() if value not in ("", 0, None)}


@dataclass(frozen=True)
class ModelManifest:
    """One artifact, as described by its own manifest. Nothing is checked yet."""

    schema_version: int
    model_id: str
    adapter_type: str
    adapter_format: str
    adapter_file: str
    adapter_sha256: str
    base_model: BaseModelReference
    intended_runtime: str
    network_required: bool
    permissions: tuple[str, ...]
    display_name: str = ""
    adapter_bytes: int = 0
    training: TrainingProvenance = field(default_factory=TrainingProvenance)
    notes: str = ""
    #: Where this was read from, when it was read from disk.
    source_path: str = ""

    @property
    def name(self) -> str:
        return self.display_name or self.model_id

    def to_json(self) -> dict[str, Any]:
        document: dict[str, Any] = {
            "schemaVersion": self.schema_version,
            "modelId": self.model_id,
            "adapterType": self.adapter_type,
            "adapterFormat": self.adapter_format,
            "adapterFile": self.adapter_file,
            "adapterSha256": self.adapter_sha256,
            "baseModel": self.base_model.to_json(),
            "intendedRuntime": self.intended_runtime,
            "networkRequired": self.network_required,
            "permissions": list(self.permissions),
        }
        if self.display_name:
            document["displayName"] = self.display_name
        if self.adapter_bytes:
            document["adapterBytes"] = self.adapter_bytes
        training = self.training.to_json()
        if training:
            document["training"] = training
        if self.notes:
            document["notes"] = self.notes
        return document


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #


def _text(section: Mapping[str, Any], key: str, *, where: str, default: str = "",
          maximum: int = 512, pattern: re.Pattern[str] | None = None) -> str:
    value = section.get(key, default)
    if value is None:
        value = default
    if not isinstance(value, str):
        raise ModelArtifactError(f"{where}.{key}: expected a string, found {type(value).__name__}")
    if len(value) > maximum:
        raise ModelArtifactError(f"{where}.{key}: longer than {maximum} characters")
    if pattern is not None and value and not pattern.match(value):
        raise ModelArtifactError(f"{where}.{key}: {value!r} is not in the accepted form")
    return value


def _integer(section: Mapping[str, Any], key: str, *, where: str, default: int = 0,
             minimum: int = 0) -> int:
    value = section.get(key, default)
    if value is None:
        value = default
    if isinstance(value, bool) or not isinstance(value, int):
        raise ModelArtifactError(f"{where}.{key}: expected an integer, found {value!r}")
    if value < minimum:
        raise ModelArtifactError(f"{where}.{key}: {value} is below {minimum}")
    return value


def _closed(section: Any, allowed: frozenset[str], *, where: str) -> dict[str, Any]:
    if section is None:
        return {}
    if not isinstance(section, Mapping):
        raise ModelArtifactError(f"{where}: expected an object, found {type(section).__name__}")
    unknown = sorted(set(section) - allowed)
    if unknown:
        raise ModelArtifactError(
            f"{where}: unknown field(s) {', '.join(repr(item) for item in unknown)}; "
            "a manifest read across a trust boundary is closed, and an unknown field "
            "is refused rather than ignored"
        )
    return dict(section)


def parse_manifest(document: Any, *, source_path: str = "") -> ModelManifest:
    """Turn a parsed JSON document into a manifest, or say why it is not one.

    Raises rather than reporting, because everything here is "this is not a
    manifest at all". Judgements about a well-formed manifest — supported
    version, matching digests, compatible base — belong to
    :mod:`companion.models.validation`, which reports them.

    One judgement *is* made here, and only because the type cannot represent
    the alternative: ``permissions`` must be a list of strings to be parsed at
    all. Whether a non-empty list is acceptable is validation's call, and it
    is not.
    """
    if not isinstance(document, Mapping):
        raise ModelArtifactError(
            f"a manifest is a JSON object, found {type(document).__name__}"
        )
    body = _closed(document, _TOP_LEVEL_FIELDS, where="manifest")
    missing = [name for name in _REQUIRED_FIELDS if name not in body]
    if missing:
        raise ModelArtifactError(f"manifest is missing required field(s): {', '.join(missing)}")

    version = _integer(body, "schemaVersion", where="manifest", minimum=1)

    permissions = body.get("permissions")
    if not isinstance(permissions, list) or any(
        not isinstance(item, str) for item in permissions
    ):
        raise ModelArtifactError("manifest.permissions: expected an array of strings")

    network_required = body.get("networkRequired")
    if not isinstance(network_required, bool):
        raise ModelArtifactError("manifest.networkRequired: expected true or false")

    base_section = _closed(body.get("baseModel"), _BASE_MODEL_FIELDS, where="manifest.baseModel")
    if not base_section:
        raise ModelArtifactError("manifest.baseModel: required")
    reference = _text(base_section, "reference", where="manifest.baseModel")
    if not reference.strip():
        raise ModelArtifactError("manifest.baseModel.reference: required")
    base = BaseModelReference(
        reference=reference.strip(),
        revision=_text(base_section, "revision", where="manifest.baseModel", maximum=128),
        file=_text(base_section, "file", where="manifest.baseModel", maximum=128, pattern=_FILE_NAME),
        sha256=_text(base_section, "sha256", where="manifest.baseModel", maximum=64, pattern=_SHA256),
        architecture=_text(base_section, "architecture", where="manifest.baseModel", maximum=64),
        parameter_count=_integer(base_section, "parameterCount", where="manifest.baseModel"),
    )

    training_section = _closed(body.get("training"), _TRAINING_FIELDS, where="manifest.training")
    final_loss = training_section.get("finalLoss")
    if final_loss is not None and (isinstance(final_loss, bool) or not isinstance(final_loss, (int, float))):
        raise ModelArtifactError("manifest.training.finalLoss: expected a number or null")
    training = TrainingProvenance(
        created_by=_text(training_section, "createdBy", where="manifest.training", maximum=128),
        created_at=_text(training_section, "createdAt", where="manifest.training", maximum=32),
        job_id=_text(training_section, "jobId", where="manifest.training", maximum=128),
        config_sha256=_text(training_section, "configSha256", where="manifest.training", maximum=64, pattern=_SHA256),
        config_canonical_sha256=_text(
            training_section, "configCanonicalSha256", where="manifest.training", maximum=64, pattern=_SHA256
        ),
        dataset_sha256=_text(training_section, "datasetSha256", where="manifest.training", maximum=64, pattern=_SHA256),
        dataset_conversations=_integer(training_section, "datasetConversations", where="manifest.training"),
        bunny_commit=_text(training_section, "bunnyCommit", where="manifest.training", maximum=128),
        method=_text(training_section, "method", where="manifest.training", maximum=32),
        precision=_text(training_section, "precision", where="manifest.training", maximum=16),
        steps=_integer(training_section, "steps", where="manifest.training"),
        final_loss=float(final_loss) if final_loss is not None else None,
    )

    return ModelManifest(
        schema_version=version,
        model_id=_text(body, "modelId", where="manifest", maximum=64, pattern=_MODEL_ID),
        adapter_type=_text(body, "adapterType", where="manifest", maximum=32),
        adapter_format=_text(body, "adapterFormat", where="manifest", maximum=32),
        adapter_file=_text(body, "adapterFile", where="manifest", maximum=128, pattern=_FILE_NAME),
        adapter_sha256=_text(body, "adapterSha256", where="manifest", maximum=64, pattern=_SHA256),
        base_model=base,
        intended_runtime=_text(body, "intendedRuntime", where="manifest", maximum=32),
        network_required=network_required,
        permissions=tuple(permissions),
        display_name=_text(body, "displayName", where="manifest", maximum=128),
        adapter_bytes=_integer(body, "adapterBytes", where="manifest"),
        training=training,
        notes=_text(body, "notes", where="manifest", maximum=1024),
        source_path=source_path,
    )


def manifest_path_for(directory: Path | str) -> Path:
    return Path(directory) / MANIFEST_FILE_NAME


def read_manifest(directory: Path | str) -> ModelManifest:
    """Read and parse the manifest in ``directory``. Touches nothing else."""
    path = manifest_path_for(directory)
    try:
        data = path.read_bytes()
    except FileNotFoundError as exc:
        raise ModelArtifactError(f"no {MANIFEST_FILE_NAME} in {directory}") from exc
    except OSError as exc:
        raise ModelArtifactError(f"cannot read {path}: {exc}") from exc
    if len(data) > _MAX_MANIFEST_BYTES:
        raise ModelArtifactError(
            f"{path} is {len(data)} bytes; a manifest is at most {_MAX_MANIFEST_BYTES}"
        )
    try:
        document = json.loads(data.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ModelArtifactError(f"{path} is not UTF-8: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ModelArtifactError(f"{path} is not valid JSON: {exc}") from exc
    return parse_manifest(document, source_path=str(path))


def supported_schema_versions() -> tuple[int, ...]:
    return (ARTIFACT_SCHEMA_VERSION,)
