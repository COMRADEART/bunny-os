# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What a provider adapter has to be, and the two lies it is built not to tell.

**Lie one: succeeding while unavailable.** Every adapter method that touches
an endpoint returns structure — :class:`ProbeResult` or
:class:`GenerationOutcome` — with ``ok``/``available`` as data. An adapter
whose runtime is not installed constructs fine, probes to "unavailable" with
the reason, and generates to a failed outcome naming ``connection`` or
``model-unavailable``. Nothing raises to say "not here", because a raised
absence takes the worker down and a swallowed one becomes a silent skip; §4
requires the structured middle.

**Lie two: emitting a stream the record cannot check.** Adapters do not mint
their own sequence numbers or timestamps; they draw events from a
:class:`StreamEventFactory` bound to their request, and every event passes
through the worker's :class:`~companion.agents.stream.StreamAssembler`, which
enforces §11 whether or not the adapter meant to. The factory makes the
correct thing the easy thing; the assembler makes the wrong thing a failed
generation rather than a corrupted record.

The generation call receives the resolved :class:`~companion.agents.credentials.Secret`
(or ``None``), uses it for exactly one dispatch, and holds no reference
afterwards. Adapters never resolve credentials themselves — resolution policy
(approved directories, permission checks) belongs to the registry, and an
adapter that could resolve could also log.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol, runtime_checkable

from .credentials import Secret
from .errors import AgentSchemaError
from .health import FAILURE_KINDS
from .request import GenerationRequest
from .stream import AssembledOutput, StreamEvent
from .usage import UsageReport

__all__ = [
    "CancellationSignal",
    "GenerationOutcome",
    "ModelListing",
    "ProbeResult",
    "ProviderAdapter",
    "StreamEventFactory",
    "unavailable_probe",
]


class CancellationSignal:
    """A one-way latch the worker owns and the adapter watches.

    The same shape as the voice runtime's signal, re-stated here because this
    package may not import that one. ``cancel`` returns whether this call was
    the one that latched it, so exactly one place records the cause.
    """

    def __init__(self) -> None:
        self._event = threading.Event()
        self._guard = threading.Lock()
        self._reason = ""

    def cancel(self, reason: str = "cancelled") -> bool:
        with self._guard:
            if self._event.is_set():
                return False
            self._reason = reason or "cancelled"
            self._event.set()
            return True

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str:
        with self._guard:
            return self._reason

    def wait(self, timeout: float | None = None) -> bool:
        return self._event.wait(timeout)


@dataclass(frozen=True)
class ModelListing:
    """One model an endpoint offers, as observed by a probe."""

    model_id: str
    revision: str = ""
    context_limit_tokens: int = 0
    size_bytes: int = 0

    def to_json(self) -> dict[str, Any]:
        return {
            "modelId": self.model_id,
            "revision": self.revision,
            "contextLimitTokens": self.context_limit_tokens,
            "sizeBytes": self.size_bytes,
        }


@dataclass(frozen=True)
class ProbeResult:
    """What probing an endpoint established. Unavailability is a result."""

    adapter_id: str
    available: bool
    detail: str = ""
    implementation: str = ""
    models: tuple[ModelListing, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {
            "adapterId": self.adapter_id,
            "available": self.available,
            "detail": self.detail,
            "implementation": self.implementation,
            "models": [item.to_json() for item in self.models],
        }


def unavailable_probe(adapter_id: str, detail: str) -> ProbeResult:
    """The §4 structured unavailable result, so no adapter writes its own shape."""
    return ProbeResult(adapter_id=adapter_id, available=False, detail=detail)


@dataclass(frozen=True)
class GenerationOutcome:
    """How one generation ended. Failure is named, never raised.

    ``failure_kind`` is one of :data:`companion.agents.health.FAILURE_KINDS`
    when ``ok`` is false — the health monitor counts what this names.
    ``assembled`` is present whenever a stream got far enough to finalize,
    including cancelled and failed streams, whose text is provisional history
    only.
    """

    request_id: str
    provider_id: str
    ok: bool
    failure_kind: str = ""
    detail: str = ""
    assembled: AssembledOutput | None = None
    usage: UsageReport | None = None
    retry_hint_seconds: float = 0.0
    cancelled: bool = False

    def __post_init__(self) -> None:
        if self.ok and self.failure_kind:
            raise AgentSchemaError("a successful outcome does not name a failure kind")
        if not self.ok and not self.cancelled and self.failure_kind not in FAILURE_KINDS:
            raise AgentSchemaError(
                f"a failed outcome names one of {FAILURE_KINDS}, not {self.failure_kind!r}"
            )
        if self.retry_hint_seconds < 0:
            raise AgentSchemaError("retry hint must be non-negative")

    def to_json(self) -> dict[str, Any]:
        return {
            "requestId": self.request_id,
            "providerId": self.provider_id,
            "ok": self.ok,
            "cancelled": self.cancelled,
            "failureKind": self.failure_kind,
            "detail": self.detail,
            "assembled": self.assembled.to_json() if self.assembled is not None else None,
            "usage": self.usage.to_json() if self.usage is not None else None,
            "retryHintSeconds": self.retry_hint_seconds,
        }


class StreamEventFactory:
    """Mints correctly-sequenced events for one generation.

    Not thread-safe; an adapter emits from one thread, which is the
    backpressure path. The monotonic source is injected by the worker so
    adapters never read a clock.
    """

    def __init__(self, *, request_id: str, provider_id: str,
                 monotonic: Callable[[], float]) -> None:
        self._request_id = request_id
        self._provider_id = provider_id
        self._monotonic = monotonic
        self._sequence = 0

    def _event(self, kind: str, payload: Mapping[str, Any]) -> StreamEvent:
        self._sequence += 1
        return StreamEvent(
            kind=kind,
            request_id=self._request_id,
            provider_id=self._provider_id,
            sequence=self._sequence,
            monotonic=self._monotonic(),
            payload=payload,
        )

    def started(self) -> StreamEvent:
        return self._event("generation_started", {})

    def delta(self, text: str) -> StreamEvent:
        return self._event("output_delta", {"text": text})

    def structured(self, text: str) -> StreamEvent:
        return self._event("structured_delta", {"text": text})

    def proposal(self, proposal: Mapping[str, Any]) -> StreamEvent:
        return self._event("tool_proposal", {"proposal": dict(proposal)})

    def usage(self, figures: Mapping[str, Any]) -> StreamEvent:
        return self._event("usage_update", dict(figures))

    def completed(self, detail: str = "") -> StreamEvent:
        return self._event("generation_completed", {"detail": detail})

    def cancelled(self, detail: str = "") -> StreamEvent:
        return self._event("generation_cancelled", {"detail": detail})

    def failed(self, detail: str = "") -> StreamEvent:
        return self._event("generation_failed", {"detail": detail})


@runtime_checkable
class ProviderAdapter(Protocol):
    """The complete adapter surface. Note what no method takes: a file path a
    provider chose, a URL a response suggested, a schema a model supplied, or
    a credential the adapter resolved for itself.
    """

    @property
    def adapter_id(self) -> str: ...

    @property
    def endpoint_kind(self) -> str: ...

    #: Whether this adapter can honour a structured-output request — a class
    #: attribute, declared not probed, so an honest "no" (llama-cli) routes
    #: structured work to the adapters that can.
    supports_structured_output: bool

    def probe(self, configuration: Any, *, deadline_seconds: float = 5.0) -> ProbeResult:
        """Reach the endpoint, honestly. Absence is a result, not an exception."""
        ...

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
        """Run one generation, emitting through the worker's assembler."""
        ...

    def cancel(self, request_id: str) -> bool:
        """Best-effort interrupt of an in-flight generation; True if one was found."""
        ...

    def close(self) -> None:
        """Release every connection and child. Safe twice."""
        ...
