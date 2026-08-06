# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded streaming: eight event kinds, one ordering contract, no exceptions.

The §11 requirements are all enforced in one place — :class:`StreamAssembler`
— so an adapter cannot honour half of them. Every event carries the provider's
identity and a strictly incrementing sequence; a duplicate, a regression, a
gap, an oversized delta, a delta after the terminal event, a second terminal
event, or a rate beyond the bound is a :class:`StreamViolation` that fails the
generation. The assembler never repairs a stream, because a repaired stream is
a stream whose order the record invented.

**Provisional versus final.** The UI may show the accumulated text at any
point (:meth:`StreamAssembler.provisional_text`), but only
:meth:`StreamAssembler.finalize` — which requires a terminal event and
re-digests everything received — produces the output the runtime may treat as
a result. Malformed partial structured output can therefore be *displayed*
(§11 permits provisional text) but can never be *presented as final*: the
final path runs through :mod:`companion.agents.structured` validation first.

UTF-8 correctness is owed by the wire layer: adapters decode network bytes
with an incremental decoder so a code point split across chunks reassembles,
and the assembler refuses a delta carrying unpaired surrogates — the shape a
byte-sliced decode produces when somebody skips the incremental decoder.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping

from .errors import AgentSchemaError, StreamViolation

__all__ = [
    "AssembledOutput",
    "MAX_DELTA_BYTES",
    "MAX_EVENTS_PER_SECOND",
    "MAX_STREAM_EVENTS",
    "STREAM_EVENT_KINDS",
    "StreamAssembler",
    "StreamEvent",
    "TERMINAL_KINDS",
]

STREAM_EVENT_KINDS = (
    "generation_started",
    "output_delta",
    "structured_delta",
    "tool_proposal",
    "usage_update",
    "generation_completed",
    "generation_cancelled",
    "generation_failed",
)

TERMINAL_KINDS = ("generation_completed", "generation_cancelled", "generation_failed")

MAX_DELTA_BYTES = 4096
MAX_STREAM_EVENTS = 8192
MAX_EVENTS_PER_SECOND = 200
_MAX_PAYLOAD_BYTES = 8192


@dataclass(frozen=True)
class StreamEvent:
    """One streaming event, provider identity included on every one."""

    kind: str
    request_id: str
    provider_id: str
    sequence: int
    monotonic: float
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in STREAM_EVENT_KINDS:
            raise AgentSchemaError(f"stream event kind {self.kind!r} is not one of {STREAM_EVENT_KINDS}")
        if not self.request_id or not self.provider_id:
            raise AgentSchemaError("a stream event names its request and its provider, always")
        if not isinstance(self.sequence, int) or self.sequence < 1:
            raise AgentSchemaError("stream sequence numbers begin at 1")
        try:
            encoded = json.dumps(dict(self.payload), ensure_ascii=False)
        except (TypeError, ValueError) as error:
            raise AgentSchemaError(f"stream payload is not JSON-representable: {error}") from None
        if len(encoded.encode("utf-8", errors="surrogatepass")) > _MAX_PAYLOAD_BYTES:
            raise AgentSchemaError(f"stream payload exceeds {_MAX_PAYLOAD_BYTES} bytes")
        if self.kind in ("output_delta", "structured_delta"):
            text = self.payload.get("text", "")
            if not isinstance(text, str) or not text:
                raise AgentSchemaError(f"{self.kind} carries a non-empty 'text' string")
            if len(text.encode("utf-8", errors="replace")) > MAX_DELTA_BYTES:
                raise AgentSchemaError(f"delta exceeds {MAX_DELTA_BYTES} bytes")

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "requestId": self.request_id,
            "providerId": self.provider_id,
            "sequence": self.sequence,
            "monotonic": self.monotonic,
            "payload": dict(self.payload),
        }


@dataclass(frozen=True)
class AssembledOutput:
    """What a finished stream adds up to — the only path to a final result."""

    request_id: str
    provider_id: str
    terminal_kind: str
    text: str
    structured_text: str
    digest: str
    event_count: int
    tool_proposals: tuple[Mapping[str, Any], ...]
    usage: Mapping[str, Any]
    detail: str = ""

    @property
    def completed(self) -> bool:
        return self.terminal_kind == "generation_completed"

    @property
    def cancelled(self) -> bool:
        return self.terminal_kind == "generation_cancelled"

    def to_json(self) -> dict[str, Any]:
        return {
            "requestId": self.request_id,
            "providerId": self.provider_id,
            "terminalKind": self.terminal_kind,
            "textBytes": len(self.text.encode("utf-8", errors="replace")),
            "structuredBytes": len(self.structured_text.encode("utf-8", errors="replace")),
            "digest": self.digest,
            "eventCount": self.event_count,
            "toolProposalCount": len(self.tool_proposals),
            "usage": dict(self.usage),
            "detail": self.detail,
        }


def _has_unpaired_surrogate(text: str) -> bool:
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return True
    return False


class StreamAssembler:
    """Enforces the ordering contract and accumulates the output.

    One assembler per generation. It is not thread-safe and does not need to
    be: the worker consumes the adapter's events on one thread, which is also
    the backpressure mechanism — an adapter can emit no faster than the
    assembler accepts.
    """

    def __init__(self, *, request_id: str, provider_id: str,
                 maximum_output_bytes: int, maximum_events: int = MAX_STREAM_EVENTS) -> None:
        self._request_id = request_id
        self._provider_id = provider_id
        self._maximum_output_bytes = maximum_output_bytes
        self._maximum_events = maximum_events
        self._expected_sequence = 1
        self._started = False
        self._terminal: StreamEvent | None = None
        self._text: list[str] = []
        self._text_bytes = 0
        self._structured: list[str] = []
        self._structured_bytes = 0
        self._proposals: list[Mapping[str, Any]] = []
        self._usage: Mapping[str, Any] = {}
        self._count = 0
        self._window_start = 0.0
        self._window_count = 0

    @property
    def terminal(self) -> StreamEvent | None:
        return self._terminal

    @property
    def event_count(self) -> int:
        return self._count

    def provisional_text(self) -> str:
        """For display only. Callers labelling this as a result are lying."""
        return "".join(self._text)

    def accept(self, event: StreamEvent) -> None:
        if event.request_id != self._request_id or event.provider_id != self._provider_id:
            raise StreamViolation(
                f"stream event names {event.provider_id!r}/{event.request_id!r}; "
                f"this stream is {self._provider_id!r}/{self._request_id!r}"
            )
        if self._terminal is not None:
            raise StreamViolation(f"event after terminal {self._terminal.kind!r}")
        if event.sequence != self._expected_sequence:
            raise StreamViolation(
                f"sequence {event.sequence} where {self._expected_sequence} was required; "
                "a duplicate or a gap is a lie about order"
            )
        self._count += 1
        if self._count > self._maximum_events:
            raise StreamViolation(f"more than {self._maximum_events} events in one generation")
        # Rate: a rolling one-second window on the event's own monotonic stamp.
        if event.monotonic - self._window_start >= 1.0:
            self._window_start = event.monotonic
            self._window_count = 0
        self._window_count += 1
        if self._window_count > MAX_EVENTS_PER_SECOND:
            raise StreamViolation(f"more than {MAX_EVENTS_PER_SECOND} events in one second")

        if not self._started:
            if event.kind != "generation_started":
                raise StreamViolation(f"first event was {event.kind!r}, not generation_started")
            self._started = True
        elif event.kind == "generation_started":
            raise StreamViolation("generation_started arrived twice")

        if event.kind in ("output_delta", "structured_delta"):
            text = str(event.payload["text"])
            if _has_unpaired_surrogate(text):
                raise StreamViolation("delta carries unpaired surrogates; the decode was not incremental")
            size = len(text.encode("utf-8"))
            if event.kind == "output_delta":
                self._text_bytes += size
                if self._text_bytes > self._maximum_output_bytes:
                    raise StreamViolation(
                        f"output exceeds the {self._maximum_output_bytes}-byte bound"
                    )
                self._text.append(text)
            else:
                self._structured_bytes += size
                if self._structured_bytes > self._maximum_output_bytes:
                    raise StreamViolation(
                        f"structured output exceeds the {self._maximum_output_bytes}-byte bound"
                    )
                self._structured.append(text)
        elif event.kind == "tool_proposal":
            proposal = event.payload.get("proposal")
            if not isinstance(proposal, Mapping):
                raise StreamViolation("tool_proposal carries no proposal mapping")
            self._proposals.append(dict(proposal))
        elif event.kind == "usage_update":
            self._usage = dict(event.payload)
        elif event.kind in TERMINAL_KINDS:
            self._terminal = event

        self._expected_sequence += 1

    def finalize(self) -> AssembledOutput:
        if self._terminal is None:
            raise StreamViolation("finalize before a terminal event; the stream is not over")
        text = "".join(self._text)
        structured = "".join(self._structured)
        digest_material = text if not structured else structured
        return AssembledOutput(
            request_id=self._request_id,
            provider_id=self._provider_id,
            terminal_kind=self._terminal.kind,
            text=text,
            structured_text=structured,
            digest=hashlib.sha256(digest_material.encode("utf-8", errors="replace")).hexdigest(),
            event_count=self._count,
            tool_proposals=tuple(self._proposals),
            usage=self._usage,
            detail=str(self._terminal.payload.get("detail", "")),
        )
