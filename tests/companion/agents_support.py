# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Agent-provider fixtures: scripted adapters that misbehave one way each.

The house rule from :mod:`tests.companion.support` holds: doubles are
hand-written dataclasses, not mocks, and each one models exactly one way an
adapter can misbehave, so a failing test names the misbehaviour. The scripted
adapter here is the *well-behaved* one; every hostile variant is a subclass
that overrides exactly the step it lies about.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from companion.agents.adapter import (
    CancellationSignal,
    GenerationOutcome,
    ModelListing,
    ProbeResult,
    ProviderAdapter,
    StreamEventFactory,
)
from companion.agents.config import AgentConfiguration, ProviderConfiguration
from companion.agents.credentials import Secret
from companion.agents.descriptor import EndpointIdentity
from companion.agents.health import ProviderHealthMonitor
from companion.agents.journal import GenerationJournal
from companion.agents.registry import AgentProviderRegistry
from companion.agents.request import GenerationMessage, GenerationRequest
from companion.agents.stream import StreamEvent
from companion.agents.usage import UsageLedger
from companion.agents.worker import AgentWorker
from companion.clock import FrozenClock

BARRIER_TIMEOUT = 10.0


def scripted_configuration(
    *,
    provider_id: str = "local.scripted",
    adapter_id: str = "scripted",
    model_id: str = "scripted-model",
    enabled: bool = True,
    user_preferred: bool = False,
    supported_task_classes: tuple[str, ...] = ("question", "summarise", "transform", "compute"),
) -> ProviderConfiguration:
    return ProviderConfiguration(
        provider_id=provider_id,
        adapter_id=adapter_id,
        endpoint=EndpointIdentity(kind="subprocess", locator="scripted"),
        program="scripted",
        model_id=model_id,
        enabled=enabled,
        user_preferred=user_preferred,
        supported_task_classes=supported_task_classes,
    )


def remote_configuration(
    *,
    provider_id: str = "remote.scripted",
    adapter_id: str = "scripted-remote",
    credential_kind: str = "environment",
    credential_locator: str = "BUNNY_TEST_REMOTE_KEY",
    enabled: bool = True,
) -> ProviderConfiguration:
    from companion.agents.credentials import CredentialReference
    from companion.agents.wire import HttpTarget

    return ProviderConfiguration(
        provider_id=provider_id,
        adapter_id=adapter_id,
        endpoint=EndpointIdentity(kind="remote-https", locator="api.example.test:443/v1"),
        http=HttpTarget(scheme="https", host="api.example.test", port=443, base_path="/v1"),
        model_id="remote-model",
        enabled=enabled,
        remote=True,
        credential=CredentialReference(kind=credential_kind, locator=credential_locator),
        cost_class="metered",
        maximum_privacy_class="internal",
    )


@dataclass
class ScriptedAdapter:
    """A well-behaved adapter whose output is a script, not a model.

    ``script`` is what one generation emits: a tuple of ("delta"|"structured",
    text) or ("proposal", mapping) items, followed automatically by usage and
    completion. Requests and cancellations are recorded for assertions.
    """

    adapter_identity: str = "scripted"
    #: Declared like a real adapter's, so a double gets the capability it
    #: implements rather than one the registry guessed from its name.
    supports_structured_output: bool = True
    script: tuple[tuple[str, Any], ...] = (("delta", "scripted answer"),)
    probe_available: bool = True
    probe_detail: str = "scripted runtime"
    models: tuple[ModelListing, ...] = (ModelListing(model_id="scripted-model"),)
    requests: list[GenerationRequest] = field(default_factory=list)
    cancelled: list[str] = field(default_factory=list)
    closed: int = 0
    #: When set, generation blocks here until released — for cancellation
    #: races that need a generation reliably "in flight".
    hold: threading.Event | None = None
    started: threading.Event = field(default_factory=threading.Event)
    secrets_seen: list[bool] = field(default_factory=list)

    @property
    def adapter_id(self) -> str:
        return self.adapter_identity

    @property
    def endpoint_kind(self) -> str:
        return "subprocess"

    def probe(self, configuration: Any, *, deadline_seconds: float = 5.0) -> ProbeResult:
        return ProbeResult(
            adapter_id=self.adapter_id,
            available=self.probe_available,
            detail=self.probe_detail,
            implementation="scripted/1",
            models=self.models,
        )

    def generate(
        self,
        request: GenerationRequest,
        configuration: Any,
        *,
        secret: Secret | None,
        emit: Callable[[StreamEvent], None],
        events: StreamEventFactory,
        cancellation: CancellationSignal,
    ) -> GenerationOutcome:
        self.requests.append(request)
        self.secrets_seen.append(secret is not None)
        emit(events.started())
        self.started.set()
        if self.hold is not None:
            # A real adapter blocks on a socket here; the scripted one blocks
            # on a barrier, which is the same thing without the weather.
            while not cancellation.wait(timeout=0.05):
                if self.hold.is_set():
                    break
        if cancellation.cancelled:
            emit(events.cancelled(cancellation.reason))
            return GenerationOutcome(
                request_id=request.request_id, provider_id=request.provider_id,
                ok=False, cancelled=True, detail=cancellation.reason,
            )
        for kind, payload in self.script:
            if cancellation.cancelled:
                emit(events.cancelled(cancellation.reason))
                return GenerationOutcome(
                    request_id=request.request_id, provider_id=request.provider_id,
                    ok=False, cancelled=True, detail=cancellation.reason,
                )
            if kind == "delta":
                emit(events.delta(str(payload)))
            elif kind == "structured":
                emit(events.structured(str(payload)))
            elif kind == "proposal":
                emit(events.proposal(dict(payload)))
            else:  # pragma: no cover - a scripted test wrote a bad script
                raise AssertionError(f"unknown script item {kind!r}")
        from companion.agents.usage import UsageReport

        usage = UsageReport(
            request_id=request.request_id, provider_id=request.provider_id,
            input_units=7, output_units=11, basis="reported",
        )
        emit(events.usage(usage.to_json()))
        emit(events.completed())
        return GenerationOutcome(
            request_id=request.request_id, provider_id=request.provider_id,
            ok=True, usage=usage,
        )

    def cancel(self, request_id: str) -> bool:
        self.cancelled.append(request_id)
        return True

    def close(self) -> None:
        self.closed += 1


@dataclass
class FailingAdapter(ScriptedAdapter):
    """Fails every generation with one declared kind."""

    failure_kind: str = "connection"
    detail: str = "scripted failure"

    def generate(self, request, configuration, *, secret, emit, events, cancellation):
        self.requests.append(request)
        return GenerationOutcome(
            request_id=request.request_id, provider_id=request.provider_id,
            ok=False, failure_kind=self.failure_kind, detail=self.detail,
        )


@dataclass
class MisorderedStreamAdapter(ScriptedAdapter):
    """Emits a duplicate sequence number — the stream lie the assembler exists for."""

    def generate(self, request, configuration, *, secret, emit, events, cancellation):
        self.requests.append(request)
        emit(events.started())
        first = events.delta("one")
        emit(first)
        # Re-emit the same event object: same sequence, a replay.
        emit(first)
        emit(events.completed())  # pragma: no cover - the assembler raises first
        return GenerationOutcome(  # pragma: no cover
            request_id=request.request_id, provider_id=request.provider_id, ok=True,
        )


def build_registry(
    *,
    configurations: tuple[ProviderConfiguration, ...] | None = None,
    adapters: Mapping[str, ProviderAdapter] | None = None,
    monitor: ProviderHealthMonitor | None = None,
    executor_preference: str = "deterministic",
    reviewer_provider_id: str = "",
) -> AgentProviderRegistry:
    scripted = ScriptedAdapter()
    configuration = AgentConfiguration(
        providers=configurations if configurations is not None else (scripted_configuration(),),
        executor_preference=executor_preference,
        reviewer_provider_id=reviewer_provider_id,
    )
    return AgentProviderRegistry(
        configuration,
        adapters if adapters is not None else {"scripted": scripted},
        monitor=monitor,
    )


def build_worker(
    root: Path,
    *,
    registry: AgentProviderRegistry | None = None,
    clock: FrozenClock | None = None,
    start: bool = True,
) -> tuple[AgentWorker, AgentProviderRegistry, UsageLedger, GenerationJournal, FrozenClock]:
    clock = clock if clock is not None else FrozenClock()
    registry = registry if registry is not None else build_registry()
    ledger = UsageLedger()
    journal = GenerationJournal(root / "agents" / "journal.jsonl")
    worker = AgentWorker(
        registry=registry, journal=journal, ledger=ledger, monotonic=clock.monotonic,
    )
    if start:
        worker.start()
    return worker, registry, ledger, journal, clock


def make_request(
    *,
    request_id: str = "gen-000001",
    provider_id: str = "local.scripted",
    purpose: str = "result",
    task_id: str = "task-000001",
    session_id: str = "ses-000001",
    structured_schema_reference: str = "",
    messages: tuple[GenerationMessage, ...] = (),
    remote_approval_reference: str = "",
    maximum_output_tokens: int = 256,
    deadline_seconds: float = 10.0,
    classification: str = "internal",
) -> GenerationRequest:
    return GenerationRequest(
        request_id=request_id,
        session_id=session_id if purpose != "probe" else "",
        task_id=task_id if purpose != "probe" else "",
        lifecycle_epoch=0,
        plan_id="plan-test",
        provider_id=provider_id,
        model_id="scripted-model",
        purpose=purpose,
        messages=messages or (GenerationMessage(role="user", content="count the words"),),
        system_policy_reference="bunny-agent-policy/1",
        maximum_input_tokens=4096,
        maximum_output_tokens=maximum_output_tokens,
        structured_schema_reference=structured_schema_reference,
        classification=classification,
        remote_approval_reference=remote_approval_reference,
        deadline_seconds=deadline_seconds,
        created_at="2026-01-01T00:00:00Z",
    )
