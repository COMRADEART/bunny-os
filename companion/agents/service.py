# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The §21 operations: read, explain, test locally, cancel. Nothing configures.

Eight operations, validated against the same
:data:`companion.protocol.PROVIDER_OPERATIONS` objects the wire validates
against, so the schema a client is checked by and the schema this service
serves are one table read twice — the voice and speech services' arrangement,
kept.

What is deliberately not here: an operation that writes configuration, an
operation that takes an endpoint, an operation that returns a credential in
any form, and an operation that reaches a remote provider.
``provider_test_local`` is the strongest thing on this surface and it refuses
non-local providers by construction — a "test" that transmitted context to a
paid endpoint would be a remote dispatch wearing a diagnostic's name.

Recovery runs at construction, before the worker thread exists
(:func:`companion.agents.journal.reconcile`), so the §19 answer — nothing
interrupted is ever repeated — is settled while the subsystem is still
single-threaded.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from ..clock import Clock, SystemClock
from ..ids import IdSource, RandomIds
from ..protocol import PROVIDER_OPERATIONS, UnknownOperation
from .adapter import ProviderAdapter
from .config import AgentConfiguration, load_agent_configuration
from .context import ContextBuilder, SYSTEM_POLICY_REFERENCE
from .errors import AgentSchemaError
from .health import ProviderHealthMonitor
from .journal import GenerationJournal, reconcile
from .registry import AgentProviderRegistry, SelectionRequirement
from .request import GenerationMessage, GenerationRequest
from .usage import UsageLedger
from .worker import AgentWorker

__all__ = ["AgentProviderService", "AgentServiceOptions"]

_EXPLANATION_CACHE = 32
_TEST_OUTPUT_TOKENS = 48
_TEST_DEADLINE_SECONDS = 30.0


@dataclass
class AgentServiceOptions:
    """Everything injectable, nothing read from the ambient environment."""

    root: Path
    clock: Clock = field(default_factory=SystemClock)
    ids: IdSource = field(default_factory=RandomIds)
    configuration: AgentConfiguration | None = None
    adapters: Mapping[str, ProviderAdapter] | None = None
    monitor: ProviderHealthMonitor | None = None
    ledger: UsageLedger | None = None
    start_worker: bool = True


class AgentProviderService:
    """Owns the registry, the worker, the ledger and the journal."""

    def __init__(self, options: AgentServiceOptions) -> None:
        self.options = options
        self.clock = options.clock
        self.ids = options.ids
        configuration = options.configuration
        if configuration is None:
            configuration = load_agent_configuration(options.root)
        adapters = options.adapters
        if adapters is None:
            from .adapters import default_adapters
            adapters = default_adapters()
        self.registry = AgentProviderRegistry(
            configuration, adapters,
            monitor=options.monitor if options.monitor is not None else ProviderHealthMonitor(),
        )
        self.ledger = options.ledger if options.ledger is not None else UsageLedger()
        self.builder = ContextBuilder()
        self.journal = GenerationJournal(options.root / "agents" / "journal.jsonl")
        # §19: settled before any thread exists. Interrupted work is recorded
        # interrupted; nothing is re-enqueued from here.
        self.recovery_report = reconcile(self.journal)
        self.worker = AgentWorker(
            registry=self.registry,
            journal=self.journal,
            ledger=self.ledger,
            monotonic=self.clock.monotonic,
        )
        self._guard = threading.Lock()
        self._explanations: "OrderedDict[str, Mapping[str, Any]]" = OrderedDict()
        self._closed = False
        if options.start_worker:
            self.worker.start()

    # -- lifecycle -----------------------------------------------------------

    def restart_worker(self, *, timeout: float = 10.0) -> None:
        """§23 step 22: restart generation without touching the task runtime."""
        self.worker.restart(timeout=timeout)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.worker.stop()
        self.registry.close()

    # -- the seam the bridge feeds ------------------------------------------

    def record_task_selection(self, task_id: str, explanation: Mapping[str, Any]) -> None:
        with self._guard:
            self._explanations[task_id] = dict(explanation)
            while len(self._explanations) > _EXPLANATION_CACHE:
                self._explanations.popitem(last=False)

    def task_selection(self, task_id: str) -> Mapping[str, Any] | None:
        with self._guard:
            value = self._explanations.get(task_id)
        return dict(value) if value is not None else None

    # -- dispatch ------------------------------------------------------------

    def dispatch(self, name: str, params: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        operation = PROVIDER_OPERATIONS.get(name)
        if operation is None:
            raise UnknownOperation(f"operation {name!r} is not an agent-provider operation")
        resolved = operation.validate(dict(params or {}))
        handler = getattr(self, name)
        return handler(**resolved)

    # -- operations ----------------------------------------------------------

    def providers_list(self) -> dict[str, Any]:
        now = self.clock.monotonic()
        return {
            "providers": [item.to_json() for item in self.registry.descriptors(monotonic=now)],
        }

    def providers_status(self) -> dict[str, Any]:
        now = self.clock.monotonic()
        descriptors = self.registry.descriptors(monotonic=now)
        remote_configured = any(not item.local for item in descriptors)
        return {
            "providers": [item.to_json() for item in descriptors],
            "health": self.registry.monitor.reports(),
            "worker": self.worker.status(),
            # The worker's own note ring: stream and settle summaries, kinds
            # and sequence numbers only — never delta text. This is how a
            # client proves streaming happened without the runtime keeping
            # transcript-shaped state for it.
            "workerEvents": [dict(item) for item in self.worker.events(limit=32)],
            "recovery": dict(self.recovery_report),
            "usage": self.ledger.status(),
            "remoteConfigured": remote_configured,
            # "Active" means an approved remote generation is in flight right
            # now — not "configured", not "possible". The §22 indicator reads
            # this and must be true before dispatch; the worker refuses a
            # remote request without an approval reference, so the two cannot
            # disagree for long enough to matter.
            "remoteActive": self._remote_active(),
            "boundaries": self.boundaries(),
        }

    def _remote_active(self) -> bool:
        status = self.worker.status()
        provider_id = status.get("activeProviderId", "")
        if not provider_id:
            return False
        config = self.registry.configuration_for(str(provider_id))
        return bool(config is not None and config.remote)

    def providers_explain(
        self,
        taskClass: str,
        classification: str = "internal",
        locality: str = "device-only",
        needsStructuredOutput: bool = False,
        needsToolProposals: bool = False,
    ) -> dict[str, Any]:
        try:
            requirement = SelectionRequirement(
                task_class=taskClass,
                classification=classification,
                locality=locality,
                needs_structured_output=needsStructuredOutput,
                needs_tool_proposals=needsToolProposals,
            )
        except AgentSchemaError as error:
            raise AgentSchemaError(f"providers_explain: {error}") from None
        explanation = self.registry.select(requirement, monotonic=self.clock.monotonic())
        return {"explanation": explanation.to_json()}

    def provider_models(self, providerId: str) -> dict[str, Any]:
        probe = self.registry.probe(providerId, monotonic=self.clock.monotonic(), refresh=True)
        return {"providerId": providerId, "probe": probe.to_json()}

    def provider_health(self, providerId: str | None = None) -> dict[str, Any]:
        if providerId:
            return {"health": {providerId: self.registry.monitor.report(providerId)}}
        return {"health": self.registry.monitor.reports()}

    def provider_test_local(self, providerId: str | None = None) -> dict[str, Any]:
        """One bounded real generation against a local provider. Never remote."""
        now = self.clock.monotonic()
        if providerId:
            config = self.registry.configuration_for(providerId)
            if config is None:
                return {"ran": False, "reason": f"provider {providerId!r} is not configured"}
            if config.remote:
                return {
                    "ran": False,
                    "reason": "provider_test_local refuses remote providers; "
                              "a remote test is a remote dispatch and needs the approval path",
                }
            candidates = (providerId,)
        else:
            explanation = self.registry.select(
                SelectionRequirement(task_class="question", locality="device-only"),
                monotonic=now,
            )
            if not explanation.found:
                return {
                    "ran": False,
                    "reason": "no local provider is eligible",
                    "explanation": explanation.to_json(),
                }
            candidates = (explanation.selected,)
        provider_id = candidates[0]
        descriptor = self.registry.descriptor(provider_id, monotonic=now, refresh=True)
        if not descriptor.standing.available or not descriptor.fully_declared:
            return {
                "ran": False,
                "reason": descriptor.availability_detail or "provider is not available",
                "provider": descriptor.to_json(),
            }
        request = GenerationRequest(
            request_id=self.ids.next("gen"),
            session_id="", task_id="", lifecycle_epoch=0, plan_id="",
            provider_id=provider_id,
            model_id=descriptor.model_id,
            purpose="probe",
            messages=(
                GenerationMessage(role="system", content="Answer with one short sentence."),
                GenerationMessage(role="user", content="Reply with the single word: ready"),
            ),
            system_policy_reference=SYSTEM_POLICY_REFERENCE,
            maximum_input_tokens=1024,
            maximum_output_tokens=_TEST_OUTPUT_TOKENS,
            deadline_seconds=_TEST_DEADLINE_SECONDS,
            created_at="",
        )
        started = self.clock.monotonic()
        outcome = self.worker.generate(request)
        elapsed = self.clock.monotonic() - started
        text = outcome.assembled.text if outcome.assembled is not None else ""
        return {
            "ran": True,
            "ok": outcome.ok,
            "providerId": provider_id,
            "modelId": descriptor.model_id,
            "seconds": round(elapsed, 3),
            "failureKind": outcome.failure_kind,
            "detail": outcome.detail,
            "textBytes": len(text.encode("utf-8", errors="replace")),
            "textPreview": text[:120],
            "usage": outcome.usage.to_json() if outcome.usage is not None else None,
        }

    def task_provider_status(self, taskId: str) -> dict[str, Any]:
        status = self.worker.status()
        explanation = self.task_selection(taskId)
        request_id, _ = self.worker.active_for_task(taskId)
        provisional = ""
        streaming = False
        if request_id:
            provisional = self.worker.provisional_text(request_id)
            streaming = True
        selected = ""
        selected_local = True
        if explanation is not None:
            selected = str(explanation.get("selected", ""))
            selected_local = bool(explanation.get("selectedLocal", True))
        return {
            "taskId": taskId,
            "selection": explanation,
            "selectedProviderId": selected,
            "selectedLocal": selected_local,
            "streaming": streaming,
            "provisionalTail": provisional[-512:],
            "worker": status,
            "spentUnits": self.ledger.task_spent_units(taskId),
        }

    def task_provider_cancel(self, taskId: str) -> dict[str, Any]:
        cancelled = self.worker.cancel_task(taskId, reason="cancelled by user request")
        return {"taskId": taskId, "cancelledGenerations": cancelled}

    # -- boundaries ----------------------------------------------------------

    @staticmethod
    def boundaries() -> dict[str, Any]:
        """What this subsystem cannot do, stated as data the gates assert on."""
        return {
            "executesTools": False,
            "resolvesApprovals": False,
            "createsTasks": False,
            "readsArbitraryFiles": False,
            "controlsDesktop": False,
            "mutatesConfiguration": False,
            "hiddenRemoteFallback": False,
            "storesCredentials": False,
        }

    def status(self) -> dict[str, Any]:
        return self.providers_status()
