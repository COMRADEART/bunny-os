# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The OpenAI-compatible remote adapter: explicit configuration, silent probe.

Speaks the ``/chat/completions`` SSE surface that OpenAI defined and half the
industry now serves, over the one https target the user's configuration names.
Nothing about the dialect is assumed beyond what the llama.cpp adapter already
exercises against its local implementation of the same surface — the ``data:``
frames, the ``[DONE]`` terminator and the ``stream_options`` usage report are
one format, parsed one way, there and here.

**This adapter serves only explicit remote configurations.** A configuration
without both ``remote: true`` and ``enabled: true`` is refused outright:
probe answers unavailable, generate answers a failed outcome, and neither
opens a socket first. The configuration loader already refuses malformed
remote entries; this guard is the backstop that makes the remote adapters
impossible to reach through a selection bug or a mislabelled local entry.

**The probe never touches the network.** This is the design decision that
shapes the class. A "harmless" model-list GET still transmits the API key —
the key is data, and §8 requires approval before *any* remote transfer — so
there is no request a credentialed probe could make that is not already a
disclosure. The probe signature cannot take a secret anyway, and that is not
an accident to work around: a remote adapter's availability rung is
"configured and credential present", which the registry verifies through
:func:`~companion.agents.credentials.credential_status` without any value
transiting, and the adapter's first real network contact is an approved
generation. ``probe`` therefore always returns unavailable with the reason
and an empty model listing; the emptiness is honesty, not a defect.

**The credential exists at one call site.** The ``Authorization`` header is
built inline from ``secret.reveal()`` at the dispatch call and nowhere else —
not in a variable that outlives the call, not in an exception, not in a log,
not in anything this module returns. A generation given no secret is refused
with ``authentication`` before any connection opens.

Structured output uses ``response_format`` with a ``json_schema`` — always
one of ours — exactly as the llama.cpp adapter sends it. Local validation
still runs afterwards; server-side enforcement is an optimization, never the
check. Usage arrives in the final frame when ``stream_options`` asks for it
and is recorded with basis ``reported``; a stream that ends without one falls
back to the byte estimate, labelled ``estimated`` — the two never mix.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Mapping

from ..adapter import (
    CancellationSignal,
    GenerationOutcome,
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

__all__ = ["OpenAiCompatAdapter"]


class OpenAiCompatAdapter:
    """One instance per service; connections are per-generation."""

    #: ``response_format`` with a ``json_schema`` is part of the compatible
    #: surface; local validation still runs afterwards regardless.
    supports_structured_output = True

    def __init__(self, *, session: WireSession | None = None) -> None:
        self._session = session if session is not None else WireSession()

    @property
    def adapter_id(self) -> str:
        return "openai-compat"

    @property
    def endpoint_kind(self) -> str:
        return "remote-https"

    # -- the remote guard ----------------------------------------------------

    def _configuration_refusal(self, configuration: Any) -> str:
        """Why this configuration cannot be served, or empty when it can."""
        if not (getattr(configuration, "remote", False) and getattr(configuration, "enabled", False)):
            return "remote adapters serve only explicit remote configurations"
        if configuration.http is None:
            return "configuration names no HTTP target"
        return ""

    # -- probe ---------------------------------------------------------------

    def probe(self, configuration: Any, *, deadline_seconds: float = 5.0) -> ProbeResult:
        refusal = self._configuration_refusal(configuration)
        if refusal:
            return unavailable_probe(self.adapter_id, refusal)
        return unavailable_probe(
            self.adapter_id,
            "credential required for a remote probe; presence is checked by the registry",
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
        refusal = self._configuration_refusal(configuration)
        if refusal:
            return GenerationOutcome(
                request_id=request.request_id, provider_id=request.provider_id,
                ok=False, failure_kind="connection", detail=refusal,
            )
        if secret is None:
            return GenerationOutcome(
                request_id=request.request_id, provider_id=request.provider_id,
                ok=False, failure_kind="authentication",
                detail="no credential was resolved; remote dispatch without one is refused",
            )
        target = configuration.http
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
                target, "POST", "/chat/completions",
                body=body,
                headers={"Authorization": f"Bearer {secret.reveal()}"},
                timeout=request.deadline_seconds,
                request_id=request.request_id,
            ):
                if not started:
                    if status != 200:
                        raise WireError(
                            _error_text(line) or f"/chat/completions answered {status}",
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
                    raise WireError("provider emitted a non-JSON SSE frame", kind="invalid-response") from None
                if not isinstance(frame, Mapping):
                    raise WireError("provider emitted a non-object SSE frame", kind="invalid-response")
                if frame.get("error"):
                    raise WireError(f"provider reported: {str(frame['error'])[:200]}", kind="invalid-response")
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
    """Schemas store tuples; the wire wants lists."""
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
