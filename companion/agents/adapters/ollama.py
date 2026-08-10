# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The genuine Ollama adapter: loopback NDJSON, nothing invented.

Speaks Ollama's own wire format — ``GET /api/version`` and ``GET /api/tags``
to probe, ``POST /api/chat`` with ``"stream": true`` to generate, one JSON
object per line. Structured output uses Ollama's ``format`` parameter, which
accepts a JSON schema and constrains decoding server-side; the schema sent is
always one of ours (:mod:`companion.agents.structured`), serialized here and
never taken from anywhere else. Local validation still runs afterwards —
server-side constraint is an optimization, not a trust decision.

Usage figures come from the final NDJSON object's ``prompt_eval_count`` and
``eval_count`` and are recorded with basis ``reported``. When a run ends
without them (an old server, a mid-stream failure) the fallback is the byte
estimate, labelled ``estimated`` — the two never mix.

Cancellation closes the connection under the reader (the wire session's one
mechanism); Ollama notices the disconnect and stops generating, which is the
documented behaviour and the reason no "stop" endpoint is called.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Mapping

from ..adapter import (
    CancellationSignal,
    GenerationOutcome,
    ModelListing,
    ProbeResult,
    StreamEventFactory,
    unavailable_probe,
)
from ..credentials import Secret
from ..request import GenerationRequest
from ..stream import MAX_DELTA_BYTES, StreamEvent
from ..structured import schema_for
from ..wire import WireError, WireSession
from .common import chunked, estimated_usage, outcome_for_wire_error, reported_usage

__all__ = ["OllamaAdapter"]

_PROBE_MODELS_BOUND = 64


class OllamaAdapter:
    """One instance per service; connections are per-generation."""

    #: Ollama's ``format`` parameter constrains decoding to a JSON schema.
    supports_structured_output = True

    def __init__(self, *, session: WireSession | None = None) -> None:
        self._session = session if session is not None else WireSession()

    @property
    def adapter_id(self) -> str:
        return "ollama"

    @property
    def endpoint_kind(self) -> str:
        return "loopback-http"

    # -- probe ---------------------------------------------------------------

    def probe(self, configuration: Any, *, deadline_seconds: float = 5.0) -> ProbeResult:
        target = configuration.http
        if target is None:
            return unavailable_probe(self.adapter_id, "configuration names no HTTP target")
        try:
            status, version = self._session.request_json(
                target, "GET", "/api/version", timeout=deadline_seconds,
            )
            if status != 200 or not isinstance(version, Mapping):
                return unavailable_probe(
                    self.adapter_id, f"{target.locator} answered {status} to /api/version"
                )
            status, tags = self._session.request_json(
                target, "GET", "/api/tags", timeout=deadline_seconds,
            )
        except WireError as error:
            return unavailable_probe(self.adapter_id, str(error))
        models: list[ModelListing] = []
        if status == 200 and isinstance(tags, Mapping):
            for entry in tuple(tags.get("models", ()))[:_PROBE_MODELS_BOUND]:
                if not isinstance(entry, Mapping):
                    continue
                name = str(entry.get("name", "") or entry.get("model", ""))
                if not name:
                    continue
                models.append(ModelListing(
                    model_id=name,
                    revision=str(entry.get("digest", ""))[:71],
                    size_bytes=int(entry.get("size", 0) or 0),
                ))
        return ProbeResult(
            adapter_id=self.adapter_id,
            available=True,
            detail=f"ollama {version.get('version', 'unknown')} at {target.locator}",
            implementation=f"ollama/{version.get('version', 'unknown')}",
            models=tuple(models),
        )

    # -- generation ----------------------------------------------------------

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
        target = configuration.http
        if target is None:
            return GenerationOutcome(
                request_id=request.request_id, provider_id=request.provider_id,
                ok=False, failure_kind="connection", detail="configuration names no HTTP target",
            )
        body: dict[str, Any] = {
            "model": request.model_id,
            "stream": True,
            # No reasoning channel: §6 forbids hidden reasoning in the record,
            # and the honest way to exclude it is to ask the runtime not to
            # produce it rather than to receive it and drop it.
            "think": False,
            "messages": [
                {"role": item.role, "content": item.content} for item in request.messages
            ],
            "options": {
                "temperature": request.sampling.temperature,
                "top_p": request.sampling.top_p,
                "seed": request.sampling.seed,
                "num_predict": request.maximum_output_tokens,
            },
        }
        structured = bool(request.structured_schema_reference)
        if structured:
            # Ollama's `format` accepts a JSON schema; ours, always.
            body["format"] = _plain(schema_for(request.structured_schema_reference))
        started = False
        output_bytes = 0
        prompt_units = eval_units = -1
        duration = 0.0
        try:
            if cancellation.cancelled:
                return outcome_for_wire_error(
                    request, WireError("not dispatched", kind="connection"),
                    emit=emit, events=events, cancellation=cancellation, started=False,
                )
            for status, line in self._session.stream_lines(
                target, "POST", "/api/chat",
                body=body,
                timeout=request.deadline_seconds,
                request_id=request.request_id,
            ):
                if not started:
                    if status != 200:
                        detail = _error_line(line) or f"/api/chat answered {status}"
                        kind = "model-unavailable" if status == 404 else "invalid-response"
                        raise WireError(detail, kind=kind)
                    emit(events.started())
                    started = True
                    continue
                if not line:
                    continue
                try:
                    frame = json.loads(line)
                except json.JSONDecodeError:
                    raise WireError("ollama emitted a non-JSON stream line", kind="invalid-response") from None
                if not isinstance(frame, Mapping):
                    raise WireError("ollama emitted a non-object stream frame", kind="invalid-response")
                if frame.get("error"):
                    raise WireError(f"ollama reported: {str(frame['error'])[:200]}", kind="invalid-response")
                message = frame.get("message")
                if isinstance(message, Mapping):
                    text = str(message.get("content", ""))
                    if text:
                        output_bytes += len(text.encode("utf-8"))
                        for piece in chunked(text, bound=MAX_DELTA_BYTES):
                            emit(events.structured(piece) if structured else events.delta(piece))
                if frame.get("done"):
                    prompt_units = int(frame.get("prompt_eval_count", -1) or -1)
                    eval_units = int(frame.get("eval_count", -1) or -1)
                    duration = float(frame.get("total_duration", 0) or 0) / 1_000_000_000.0
                    break
                if cancellation.cancelled:
                    raise WireError("cancelled between frames", kind="connection")
        except WireError as error:
            return outcome_for_wire_error(
                request, error, emit=emit, events=events,
                cancellation=cancellation, started=started,
            )
        if prompt_units >= 0 and eval_units >= 0:
            usage = reported_usage(
                request, input_units=prompt_units, output_units=eval_units,
                generation_seconds=duration,
                units_per_kilotoken=configuration.estimated_units_per_kilotoken,
                pricing_reference=configuration.pricing_reference,
            )
        else:
            usage = estimated_usage(
                request, output_bytes=output_bytes, generation_seconds=duration,
                units_per_kilotoken=configuration.estimated_units_per_kilotoken,
                pricing_reference=configuration.pricing_reference,
            )
        emit(events.usage(usage.to_json()))
        emit(events.completed())
        return GenerationOutcome(
            request_id=request.request_id, provider_id=request.provider_id,
            ok=True, usage=usage,
        )

    def cancel(self, request_id: str) -> bool:
        return self._session.cancel(request_id)

    def close(self) -> None:
        self._session.close()


def _plain(value: Any) -> Any:
    """Schemas store tuples; the wire wants lists."""
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


def _error_line(line: str) -> str:
    if not line:
        return ""
    try:
        document = json.loads(line)
    except json.JSONDecodeError:
        return line[:200]
    if isinstance(document, Mapping) and document.get("error"):
        return str(document["error"])[:200]
    return line[:200]
