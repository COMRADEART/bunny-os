# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The genuine llama.cpp server adapter: loopback SSE, the model's own template.

Talks to ``llama-server`` through its OpenAI-compatible surface —
``GET /health`` and ``GET /v1/models`` (plus best-effort ``GET /props``) to
probe, ``POST /v1/chat/completions`` with ``"stream": true`` to generate.
The chat endpoint is chosen over the native ``/completion`` deliberately: the
server applies the chat template recorded in the GGUF's own metadata, so this
adapter never hard-codes a template that silently mismatches somebody's
model.

Structured output uses ``response_format`` with a ``json_schema`` — always
one of ours — which llama-server compiles to a grammar and enforces during
decoding. Local validation still runs afterwards; the grammar is an
optimization, not the check.

The SSE frames are line-delimited ``data: {json}`` with a ``data: [DONE]``
terminator. Usage arrives in the final frame when ``stream_options`` asks for
it and is recorded with basis ``reported``; a stream that ends without one
falls back to the byte estimate, labelled ``estimated``.
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
from ..wire import WireError, WireSession, failure_kind_for_status
from .common import chunked, estimated_usage, outcome_for_wire_error, reported_usage

__all__ = ["LlamaCppAdapter"]


class LlamaCppAdapter:
    def __init__(self, *, session: WireSession | None = None) -> None:
        self._session = session if session is not None else WireSession()

    @property
    def adapter_id(self) -> str:
        return "llamacpp"

    @property
    def endpoint_kind(self) -> str:
        return "loopback-http"

    # -- probe ---------------------------------------------------------------

    def probe(self, configuration: Any, *, deadline_seconds: float = 5.0) -> ProbeResult:
        target = configuration.http
        if target is None:
            return unavailable_probe(self.adapter_id, "configuration names no HTTP target")
        try:
            status, health = self._session.request_json(
                target, "GET", "/health", timeout=deadline_seconds,
            )
        except WireError as error:
            return unavailable_probe(self.adapter_id, str(error))
        if status == 503:
            return unavailable_probe(
                self.adapter_id, f"llama-server at {target.locator} is still loading its model"
            )
        if status != 200:
            return unavailable_probe(self.adapter_id, f"{target.locator} answered {status} to /health")
        models: list[ModelListing] = []
        implementation = "llama-server"
        context_limit = 0
        try:
            status, props = self._session.request_json(
                target, "GET", "/props", timeout=deadline_seconds,
            )
            if status == 200 and isinstance(props, Mapping):
                build = str(props.get("build_info", "") or "")
                if build:
                    implementation = f"llama-server/{build}"
                settings = props.get("default_generation_settings")
                if isinstance(settings, Mapping):
                    context_limit = int(settings.get("n_ctx", 0) or 0)
        except WireError:
            # /props is informative only; a server without it is still a server.
            pass
        try:
            status, listing = self._session.request_json(
                target, "GET", "/v1/models", timeout=deadline_seconds,
            )
        except WireError as error:
            return unavailable_probe(self.adapter_id, str(error))
        if status == 200 and isinstance(listing, Mapping):
            for entry in tuple(listing.get("data", ()))[:8]:
                if isinstance(entry, Mapping) and entry.get("id"):
                    models.append(ModelListing(
                        model_id=str(entry["id"]),
                        context_limit_tokens=context_limit,
                    ))
        detail = f"{implementation} at {target.locator}"
        health_detail = health if isinstance(health, Mapping) else {}
        if health_detail.get("status") not in (None, "ok"):
            detail += f" (health: {health_detail.get('status')})"
        return ProbeResult(
            adapter_id=self.adapter_id,
            available=True,
            detail=detail,
            implementation=implementation,
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
            "stream_options": {"include_usage": True},
            "messages": [
                {"role": item.role, "content": item.content} for item in request.messages
            ],
            "temperature": request.sampling.temperature,
            "top_p": request.sampling.top_p,
            "seed": request.sampling.seed,
            "max_tokens": request.maximum_output_tokens,
        }
        structured = bool(request.structured_schema_reference)
        if structured:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": request.structured_schema_reference.replace("/", "-"),
                    "strict": True,
                    "schema": _plain(schema_for(request.structured_schema_reference)),
                },
            }
        started = False
        output_bytes = 0
        prompt_units = completion_units = -1
        try:
            if cancellation.cancelled:
                return outcome_for_wire_error(
                    request, WireError("not dispatched", kind="connection"),
                    emit=emit, events=events, cancellation=cancellation, started=False,
                )
            for status, line in self._session.stream_lines(
                target, "POST", "/v1/chat/completions",
                body=body,
                timeout=request.deadline_seconds,
                request_id=request.request_id,
            ):
                if not started:
                    if status != 200:
                        raise WireError(
                            _error_text(line) or f"/v1/chat/completions answered {status}",
                            kind=failure_kind_for_status(status),
                        )
                    emit(events.started())
                    started = True
                    continue
                if not line or not line.startswith("data:"):
                    continue
                payload = line[len("data:"):].strip()
                if payload == "[DONE]":
                    break
                try:
                    frame = json.loads(payload)
                except json.JSONDecodeError:
                    raise WireError("llama-server emitted a non-JSON SSE frame", kind="invalid-response") from None
                if not isinstance(frame, Mapping):
                    raise WireError("llama-server emitted a non-object SSE frame", kind="invalid-response")
                if frame.get("error"):
                    raise WireError(f"llama-server reported: {str(frame['error'])[:200]}", kind="invalid-response")
                usage_frame = frame.get("usage")
                if isinstance(usage_frame, Mapping) and usage_frame.get("completion_tokens") is not None:
                    prompt_units = int(usage_frame.get("prompt_tokens", 0) or 0)
                    completion_units = int(usage_frame.get("completion_tokens", 0) or 0)
                for choice in frame.get("choices", ()):
                    if not isinstance(choice, Mapping):
                        continue
                    delta = choice.get("delta")
                    if isinstance(delta, Mapping):
                        text = str(delta.get("content") or "")
                        if text:
                            output_bytes += len(text.encode("utf-8"))
                            for piece in chunked(text, bound=MAX_DELTA_BYTES):
                                emit(events.structured(piece) if structured else events.delta(piece))
                if cancellation.cancelled:
                    raise WireError("cancelled between frames", kind="connection")
        except WireError as error:
            return outcome_for_wire_error(
                request, error, emit=emit, events=events,
                cancellation=cancellation, started=started,
            )
        if prompt_units >= 0 and completion_units >= 0:
            usage = reported_usage(
                request, input_units=prompt_units, output_units=completion_units,
                units_per_kilotoken=configuration.estimated_units_per_kilotoken,
                pricing_reference=configuration.pricing_reference,
            )
        else:
            usage = estimated_usage(
                request, output_bytes=output_bytes,
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
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


def _error_text(line: str) -> str:
    if not line:
        return ""
    try:
        document = json.loads(line)
    except json.JSONDecodeError:
        return line[:200]
    if isinstance(document, Mapping):
        error = document.get("error")
        if isinstance(error, Mapping):
            return str(error.get("message", ""))[:200]
        if error:
            return str(error)[:200]
    return line[:200]
