# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What models this machine has, which one is meant to be on, and which is.

The registry is metadata-first and executes nothing. It reads directories,
parses manifests, runs :mod:`companion.models.validation`, keeps a small
enabled/previous record, and asks a backend to apply or release. It does not
start processes, fetch anything, or run code an artifact supplied — a registry
that could would be a registry an artifact could talk into running something.

Three distinctions do most of the work here, and collapsing any of them is how
this sort of component goes wrong:

**discovered / valid / enabled / active.** A directory that exists is
*discovered*. One that passes every check is *valid*. One the user turned on is
*enabled* — that is an intent, and it survives restarts. One the backend has
confirmed is in effect is *active*. Only the last means a model is being used,
and :meth:`ModelRegistry.enable` returns the difference rather than reporting an
intent as an outcome.

**A bad artifact is a listed model, not a failed registry.** This is where the
registry deliberately differs from its nearest sibling,
:class:`catalog.registry.CatalogRegistry`, which fails the whole load if one
entry is malformed. The catalogue is curated and ships in the image, so a bad
entry means tampering. Artifacts arrive from outside, one at a time, and a
corrupt one must not make every other model unavailable — so each is validated
independently and a failure is a status on that model.

**Enabled and unusable is a normal state with a reason.** If the enabled model
cannot be activated — checksum mismatch, backend gone, base model absent — the
registry does not crash and does not quietly use it. It returns a
:class:`FallbackDecision` naming the code and the sentence, the Companion uses
its ordinary provider, and the model stays enabled so that fixing the cause is
enough to bring it back. Disabling never deletes an artifact, which is what
makes rollback a decision rather than a restore.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Mapping, Sequence

from ..agents.adapters.llamacli import trusted_model_directories
from ..support import companion_state_root
from . import MANIFEST_FILE_NAME
from .artifact import ModelManifest
from .errors import UnknownModel
from .events import ModelEvent, ModelEventLog, NullEventLog, utc_now
from .inference import (
    AdapterApplication,
    AdapterCapableBackend,
    BACKEND_UNAVAILABLE,
    NullAdapterBackend,
)
from .validation import (
    FAIL,
    PASS,
    RuntimeExpectations,
    UNKNOWN,
    ValidationReport,
    validate_artifact,
)

__all__ = [
    "FallbackDecision",
    "ModelRegistry",
    "RegisteredModel",
    "default_artifact_roots",
]

_STATE_FILE_NAME = "models.json"
_EVENTS_FILE_NAME = "model-events.jsonl"
_MAX_STATE_BYTES = 256 * 1024
_MAX_MODELS = 64


def default_artifact_roots() -> tuple[Path, ...]:
    """Where artifacts may live: the runtime's existing trusted model directories.

    Imported from :mod:`companion.agents.adapters.llamacli` rather than
    restated. That module owns "where trusted model material lives" for the
    agent runtime, and a second list here would be a second answer to the
    question that decides what the runtime is willing to open.
    """
    return trusted_model_directories()


@dataclass(frozen=True)
class RegisteredModel:
    """One artifact as the registry sees it."""

    model_id: str
    path: str
    report: ValidationReport
    enabled: bool = False
    application: AdapterApplication | None = None

    @property
    def manifest(self) -> ModelManifest | None:
        return self.report.manifest

    @property
    def status(self) -> str:
        return self.report.status

    @property
    def valid(self) -> bool:
        return self.report.status == PASS

    @property
    def active(self) -> bool:
        return bool(self.application and self.application.active)

    def to_json(self) -> dict[str, Any]:
        manifest = self.manifest
        return {
            "modelId": self.model_id,
            "path": self.path,
            "displayName": manifest.name if manifest else self.model_id,
            "status": self.status,
            "valid": self.valid,
            "enabled": self.enabled,
            "active": self.active,
            "adapterType": manifest.adapter_type if manifest else "",
            "adapterFormat": manifest.adapter_format if manifest else "",
            "baseModel": manifest.base_model.reference if manifest else "",
            "baseRevision": manifest.base_model.revision if manifest else "",
            "validation": self.report.to_json(),
            "application": self.application.to_json() if self.application else None,
        }


@dataclass(frozen=True)
class FallbackDecision:
    """Why no adapter is in effect, in a form a caller can render or branch on.

    ``model_id`` is empty when the runtime is using its ordinary provider with
    no adapter — which is the safe state, and the one every failure resolves to.
    """

    model_id: str = ""
    code: str = ""
    reason: str = ""
    #: The model the user asked for, when that is not the one in effect.
    requested_model_id: str = ""

    @property
    def using_adapter(self) -> bool:
        return bool(self.model_id)

    def to_json(self) -> dict[str, Any]:
        return {
            "modelId": self.model_id,
            "requestedModelId": self.requested_model_id,
            "usingAdapter": self.using_adapter,
            "code": self.code,
            "reason": self.reason,
        }


class ModelRegistry:
    """Discovery, validation, enablement and activation for runtime adapters."""

    def __init__(
        self,
        *,
        roots: Sequence[Path] | None = None,
        state_root: Path | None = None,
        backend: AdapterCapableBackend | None = None,
        expectations: RuntimeExpectations | None = None,
        events: ModelEventLog | NullEventLog | None = None,
    ) -> None:
        self.roots: tuple[Path, ...] = tuple(
            Path(item) for item in (roots if roots is not None else default_artifact_roots())
        )
        self.state_root = Path(state_root) if state_root is not None else companion_state_root() / "models"
        self.backend = backend if backend is not None else NullAdapterBackend()
        self.events = events if events is not None else NullEventLog()
        self._expectations = expectations
        self._models: dict[str, RegisteredModel] = {}
        self._discovered = False

    # -- expectations ---------------------------------------------------- #

    def expectations(self, *, verify_base: bool = False) -> RuntimeExpectations:
        """What artifacts are judged against, filled in from the backend.

        The supported-format list comes from the backend rather than from a
        constant, so an artifact is refused as unusable on a machine whose
        backend cannot apply it and accepted on one whose backend can — a fact
        about the machine, not about the artifact.

        ``verify_base`` additionally hashes the base weights the backend says it
        has loaded, which is what lets compatibility be settled by digest rather
        than by a revision string nobody can check. It is off for listings and
        on for anything that could activate a model: hashing a few hundred
        megabytes to draw a list would make ``model list`` unusable, and
        skipping it before an activation would make the check theatre.
        """
        base = self._expectations or RuntimeExpectations()
        status = self.backend.describe()
        filled = replace(
            base,
            supported_formats=status.supported_formats,
            trusted_roots=base.trusted_roots or self.roots,
        )
        if not verify_base or filled.base_model_sha256 or not status.base_model_path:
            return filled
        loaded = Path(status.base_model_path)
        if not loaded.is_file():
            # The backend named weights this process cannot see — a server on
            # another machine, or a path inside a container. Not an error, and
            # not something to guess about: the digest rung is simply unavailable.
            return replace(filled, base_model_present=filled.base_model_present)
        try:
            digest = hashlib.sha256()
            with open(loaded, "rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
        except OSError:
            return filled
        return replace(
            filled,
            base_model_sha256=digest.hexdigest(),
            base_model_file=loaded.name,
            base_model_present=True,
        )

    # -- discovery ------------------------------------------------------- #

    def discover(self, *, verify_digest: bool = True) -> tuple[RegisteredModel, ...]:
        """Find every artifact under the trusted roots and validate each one.

        A root that does not exist is not an error: a machine with no models is
        the ordinary case, and the ordinary case does not warn.

        ``verify_digest`` governs both the per-adapter digests and the one-off
        hash of the backend's base weights, so a listing and an activation agree
        about a model's status. They did not at first — a list said ``UNKNOWN``
        for a model that ``enable`` then activated, because only ``enable``
        established the base by digest — and a status that changes depending on
        which command you typed is worse than a slow one. The base is hashed
        once per registry, not once per model.
        """
        wanted = self.expectations(verify_base=verify_digest)
        state = self._read_state()
        enabled_id = str(state.get("enabledModelId", ""))
        found: dict[str, RegisteredModel] = {}

        for root in self.roots:
            if not root.is_dir():
                continue
            try:
                entries = sorted(item for item in root.iterdir() if item.is_dir())
            except OSError:
                continue
            for directory in entries:
                if not (directory / MANIFEST_FILE_NAME).is_file():
                    continue
                if len(found) >= _MAX_MODELS:
                    break
                model_id = directory.name
                if model_id in found:
                    # First root wins: the user directory shadows the system
                    # one, the same precedence the catalogue uses, and the
                    # shadowed copy is not silently merged into the winner.
                    continue
                report = validate_artifact(
                    directory, expectations=wanted, verify_digest=verify_digest
                )
                found[model_id] = RegisteredModel(
                    model_id=report.model_id or model_id,
                    path=str(directory),
                    report=report,
                    enabled=model_id == enabled_id,
                )
                self.events.record(ModelEvent.build(
                    "model.discovered", modelId=model_id, artifactPath=str(directory),
                    status=report.status,
                ))

        self._models = found
        self._discovered = True
        return tuple(found[key] for key in sorted(found))

    def _ensure(self) -> None:
        if not self._discovered:
            self.discover()

    # -- reading --------------------------------------------------------- #

    def list(self) -> tuple[RegisteredModel, ...]:
        self._ensure()
        return tuple(self._models[key] for key in sorted(self._models))

    def get(self, model_id: str) -> RegisteredModel:
        self._ensure()
        model = self._models.get(model_id)
        if model is None:
            raise UnknownModel(
                f"no model {model_id!r} under {', '.join(str(item) for item in self.roots)}"
            )
        return model

    def validate(self, model_id: str) -> ValidationReport:
        """Re-validate one model, digest included, and record the outcome."""
        model = self.get(model_id)
        self.events.record(ModelEvent.build(
            "model.validation_started", modelId=model_id, artifactPath=model.path))
        report = validate_artifact(
            Path(model.path), expectations=self.expectations(verify_base=True),
            verify_digest=True,
        )
        self._models[model_id] = replace(model, report=report)
        kind = {
            PASS: "model.validation_passed",
            FAIL: "model.validation_failed",
            UNKNOWN: "model.validation_unknown",
        }[report.status]
        self.events.record(ModelEvent.build(
            kind, modelId=model_id, status=report.status, code=report.code,
            field=report.field, reason=report.message,
        ))
        return report

    def provenance(self, model_id: str) -> dict[str, Any]:
        """Everything the runtime can say about where a loaded model came from.

        Phase 12's list, plus the validation status, because "where this came
        from" and "whether we believe it" are the same question asked twice.
        """
        model = self.get(model_id)
        manifest = model.manifest
        if manifest is None:
            return {
                "modelId": model.model_id,
                "path": model.path,
                "validationStatus": model.status,
                "validationCode": model.report.code,
                "available": False,
            }
        return {
            "modelId": manifest.model_id,
            "displayName": manifest.name,
            "path": model.path,
            "artifactVersion": manifest.schema_version,
            "adapterType": manifest.adapter_type,
            "adapterFormat": manifest.adapter_format,
            "adapterSha256": manifest.adapter_sha256,
            "adapterBytes": manifest.adapter_bytes,
            "baseModel": manifest.base_model.reference,
            "baseRevision": manifest.base_model.revision,
            "baseRevisionPinned": manifest.base_model.revision_is_pinned,
            "trainingSource": manifest.training.created_by,
            "trainingJobId": manifest.training.job_id,
            "datasetSha256": manifest.training.dataset_sha256,
            "configSha256": manifest.training.config_sha256,
            "bunnyCommit": manifest.training.bunny_commit,
            "createdAt": manifest.training.created_at,
            "validationStatus": model.status,
            "validationCode": model.report.code,
            "enabled": model.enabled,
            "active": model.active,
            "available": True,
        }

    # -- state ----------------------------------------------------------- #

    @property
    def state_path(self) -> Path:
        return self.state_root / _STATE_FILE_NAME

    @property
    def events_path(self) -> Path:
        return self.state_root / _EVENTS_FILE_NAME

    def _read_state(self) -> dict[str, Any]:
        try:
            data = self.state_path.read_text(encoding="utf-8")
        except OSError:
            return {}
        if len(data) > _MAX_STATE_BYTES:
            return {}
        try:
            document = json.loads(data)
        except json.JSONDecodeError:
            return {}
        return document if isinstance(document, dict) else {}

    def _write_state(self, document: Mapping[str, Any]) -> None:
        self.state_root.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(dict(document), indent=2, sort_keys=True) + "\n"
        handle = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=self.state_root, delete=False, prefix=".models-", suffix=".tmp"
        )
        try:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            handle.close()
        for attempt in range(5):
            try:
                os.replace(handle.name, self.state_path)
                return
            except PermissionError:  # pragma: no cover - Windows sharing
                if attempt == 4:
                    Path(handle.name).unlink(missing_ok=True)
                    raise
                time.sleep(0.05 * (attempt + 1))

    def enabled_model_id(self) -> str:
        return str(self._read_state().get("enabledModelId", ""))

    def previous_model_id(self) -> str:
        return str(self._read_state().get("previousModelId", ""))

    # -- enabling -------------------------------------------------------- #

    def enable(self, model_id: str) -> FallbackDecision:
        """Turn a model on: validate, apply, verify. Never activate on a maybe.

        Validation runs again here with digests, whatever a listing said. A
        model is not enabled on the strength of a list drawn a minute ago.
        """
        model = self.get(model_id)
        report = self.validate(model_id)
        if report.status != PASS:
            self.events.record(ModelEvent.build(
                "model.load_failed", modelId=model_id, status=report.status,
                code=report.code, reason=report.message, field=report.field,
            ))
            return self._fallback(
                code=report.code,
                reason=(
                    f"{model_id} was not activated because validation returned "
                    f"{report.status}: {report.message}"
                ),
                requested=model_id,
            )

        manifest = report.manifest
        assert manifest is not None  # PASS implies a parsed manifest
        adapter_path = Path(model.path) / manifest.adapter_file
        application = self.backend.apply(model_id, adapter_path)
        if not application.active:
            self.events.record(ModelEvent.build(
                "model.load_failed", modelId=model_id, backendId=application.backend_id,
                code=application.code, reason=application.detail,
                adapterPath=str(adapter_path),
            ))
            return self._fallback(
                code=application.code,
                reason=f"{model_id} validated but the backend did not activate it: {application.detail}",
                requested=model_id,
            )

        state = self._read_state()
        previous = str(state.get("enabledModelId", ""))
        self._write_state({
            "enabledModelId": model_id,
            "previousModelId": previous if previous and previous != model_id else state.get("previousModelId", ""),
            "updatedAt": utc_now(),
        })
        self._models[model_id] = replace(model, enabled=True, report=report, application=application)
        for other_id, other in self._models.items():
            if other_id != model_id and other.enabled:
                self._models[other_id] = replace(other, enabled=False)
        self.events.record(ModelEvent.build(
            "model.loaded", modelId=model_id, backendId=application.backend_id,
            adapterSha256=manifest.adapter_sha256, adapterPath=str(adapter_path),
            baseModel=manifest.base_model.reference, baseRevision=manifest.base_model.revision,
            scale=application.scale, verified=application.verified,
        ))
        self.events.record(ModelEvent.build(
            "model.enabled", modelId=model_id, previousModelId=previous))
        return FallbackDecision(
            model_id=model_id, code="ACTIVE",
            reason=f"{model_id} is active: {application.detail}",
            requested_model_id=model_id,
        )

    def disable(self, model_id: str = "") -> FallbackDecision:
        """Turn the adapter off and fall back. The artifact is never deleted."""
        state = self._read_state()
        target = model_id or str(state.get("enabledModelId", ""))
        application = self.backend.release(target or "")
        self._write_state({
            "enabledModelId": "",
            "previousModelId": target,
            "updatedAt": utc_now(),
        })
        if target and target in self._models:
            self._models[target] = replace(self._models[target], enabled=False, application=None)
        self.events.record(ModelEvent.build(
            "model.disabled", modelId=target, backendId=application.backend_id,
            code=application.code, reason=application.detail,
        ))
        if application.code == BACKEND_UNAVAILABLE:
            return self._fallback(
                code=application.code,
                reason=(
                    f"{target or 'the adapter'} is disabled in the registry; the backend "
                    f"could not be reached to confirm it is off: {application.detail}"
                ),
                requested=target,
            )
        return self._fallback(
            code="DISABLED",
            reason=f"{target or 'no model'} is disabled; the default provider is in use",
            requested=target,
        )

    def _fallback(self, *, code: str, reason: str, requested: str = "") -> FallbackDecision:
        decision = FallbackDecision(model_id="", code=code, reason=reason, requested_model_id=requested)
        self.events.record(ModelEvent.build(
            "model.fallback_selected", modelId="", requestedModelId=requested, code=code, reason=reason))
        return decision

    # -- what is in effect ------------------------------------------------ #

    def active(self) -> FallbackDecision:
        """Which adapter is in effect right now, verified with the backend.

        Called by the Companion before it uses a provider. It re-asks the
        backend rather than trusting the registry's own memory, because the
        model server can be restarted underneath a long-lived runtime and a
        registry reporting a model that is no longer applied would be telling
        the user their adapter is on when it is not.
        """
        self._ensure()
        enabled = self.enabled_model_id()
        if not enabled:
            return FallbackDecision(code="NO_MODEL_ENABLED",
                                    reason="no adapter is enabled; the default provider is in use")
        if enabled not in self._models:
            return self._fallback(
                code="MODEL_NOT_FOUND",
                reason=f"{enabled} is enabled but no artifact by that name is installed",
                requested=enabled,
            )
        model = self._models[enabled]
        report = model.report
        if report.status != PASS:
            return self._fallback(
                code=report.code,
                reason=f"{enabled} is enabled but no longer validates: {report.message}",
                requested=enabled,
            )
        manifest = report.manifest
        assert manifest is not None
        application = self.backend.apply(enabled, Path(model.path) / manifest.adapter_file)
        self._models[enabled] = replace(model, application=application)
        if not application.active:
            return self._fallback(
                code=application.code,
                reason=f"{enabled} is enabled but not in effect: {application.detail}",
                requested=enabled,
            )
        return FallbackDecision(
            model_id=enabled, code="ACTIVE",
            reason=f"{enabled} is active: {application.detail}",
            requested_model_id=enabled,
        )
