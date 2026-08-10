# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Gemini adapter: explicit configuration, silent probe, no smuggled URLs.

Speaks ``POST /models/{model}:streamGenerateContent?alt=sse``. The model id
is part of the request path — which is exactly why it is validated against a
strict ``^[A-Za-z0-9._-]+$`` before any path is built: a model id that could
carry ``/``, ``?``, ``#`` or ``..`` would be a request-line injection wearing
a configuration field, and it is refused as ``model-unavailable`` rather than
escaped into something the user never wrote. The wire layer refuses those
markers in a *base path*; the suffix is this adapter's to build, so the
refusal is this adapter's to make.

**This adapter serves only explicit remote configurations.** A configuration
without both ``remote: true`` and ``enabled: true`` is refused outright:
probe answers unavailable, generate answers a failed outcome, and neither
opens a socket first. The guard is the backstop that keeps the remote
adapters unreachable through a selection bug or a mislabelled local entry.

**The probe never touches the network.** A "harmless" model-list GET still
transmits the API key — the key is data, and §8 requires approval before
*any* remote transfer — so there is no request a credentialed probe could
make that is not already a disclosure. The probe signature cannot take a
secret, and deliberately so: a remote adapter's availability rung is
"configured and credential present", verified by the registry through
:func:`~companion.agents.credentials.credential_status` without any value
transiting, and the adapter's first real network contact is an approved
generation. ``probe`` therefore always returns unavailable with the reason
and an empty model listing; the emptiness is honesty, not a defect.

**Gemini's schema constraint is weaker than ours.** ``responseSchema`` takes
an OpenAPI-style subset that does not accept ``additionalProperties``, so the
module-local converter drops that keyword (and renders our tuples as lists)
before shipping the rest. The server-side constraint therefore admits fields
our schemas forbid — acceptable for the same reason it is everywhere else:
the local validator always runs, and it, not the provider, is the check.

**The credential exists at one call site.** The ``x-goog-api-key`` header is
built inline from ``secret.reveal()`` at the dispatch call and nowhere else —
not in a variable that outlives the call, not in an exception, not in a log,
not in anything this module returns. A generation given no secret is refused
with ``authentication`` before any connection opens.

Roles are mapped at the wire: ``assistant`` becomes ``model``; ``user`` and
``tool`` become ``user``; ``system`` messages are joined and lifted into
``systemInstruction``, which is where this provider reads policy. Usage
arrives as ``usageMetadata``, repeated across frames with the final frame
authoritative, so the last seen values are kept and recorded with basis
``reported``; a stream without them falls back to the byte estimate,
labelled ``estimated``. There is no ``[DONE]`` marker — the stream simply
ends — and a ``promptFeedback.blockReason`` is surfaced as an
``invalid-response`` failure naming the reason.
"""

from __future__ import annotations

import json
import re
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

__all__ = ["GeminiAdapter"]

#: What a model id may look like before it becomes part of a request path.
_MODEL_ID = re.compile(r"^[A-Za-z0-9._-]+$")


class GeminiAdapter:
    """One instance per service; connections are per-generation."""

    #: ``responseSchema`` constrains decoding, though to a weaker OpenAPI-style
    #: subset than ours; local validation remains the real check.
    supports_structured_output = True

    def __init__(self, *, session: WireSession | None = None) -> None:
        self._session = session if session is not None else WireSession()

    @property
    def adapter_id(self) -> str:
        return "gemini"

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
        if _MODEL_ID.match(request.model_id) is None:
            return GenerationOutcome(
                request_id=request.request_id, provider_id=request.provider_id,
                ok=False, failure_kind="model-unavailable",
                detail="model id carries path or query syntax; it does not name a model",
            )
        target = configuration.http
        system_text = "\n\n".join(
            item.content for item in request.messages if item.role == "system"
        )
        generation_config: dict[str, Any] = {
            "temperature": request.sampling.temperature,
            "topP": request.sampling.top_p,
            "maxOutputTokens": request.maximum_output_tokens,
            "seed": request.sampling.seed,
        }
        structured = bool(request.structured_schema_reference)
        if structured:
            generation_config["responseMimeType"] = "application/json"
            generation_config["responseSchema"] = _gemini_schema(
                schema_for(request.structured_schema_reference)
            )
        body: dict[str, Any] = {
            "contents": [
                {
                    "role": "model" if item.role == "assistant" else "user",
                    "parts": [{"text": item.content}],
                }
                for item in request.messages if item.role != "system"
            ],
            "generationConfig": generation_config,
        }
        if system_text:
            body["systemInstruction"] = {"parts": [{"text": system_text}]}
        started = False
        output_bytes = 0
        prompt_units = candidate_units = -1
        try:
            if cancellation.cancelled:
                return outcome_for_wire_error(
                    request, WireError("not dispatched", kind="connection"),
                    emit=emit, events=events, cancellation=cancellation, started=False,
                )
            for status, line in self._session.stream_lines(
                target, "POST",
                f"/models/{request.model_id}:streamGenerateContent?alt=sse",
                body=body,
                headers={"x-goog-api-key": secret.reveal()},
                timeout=request.deadline_seconds,
                request_id=request.request_id,
            ):
                if not started:
                    if status != 200:
                        raise WireError(
                            _error_text(line) or f"streamGenerateContent answered {status}",
                            kind=failure_kind_for_status(status),
                        )
                    emit(events.started())
                    started = True
                    continue
                if not line or not line.startswith("data:"):
                    continue
                payload = line[len("data:"):].strip()
                try:
                    frame = json.loads(payload)
                except json.JSONDecodeError:
                    raise WireError("gemini emitted a non-JSON SSE frame", kind="invalid-response") from None
                if not isinstance(frame, Mapping):
                    raise WireError("gemini emitted a non-object SSE frame", kind="invalid-response")
                feedback = frame.get("promptFeedback")
                if isinstance(feedback, Mapping) and feedback.get("blockReason"):
                    raise WireError(
                        f"gemini blocked the prompt: {str(feedback['blockReason'])[:200]}",
                        kind="invalid-response",
                    )
                usage_frame = frame.get("usageMetadata")
                if isinstance(usage_frame, Mapping):
                    if usage_frame.get("promptTokenCount") is not None:
                        prompt_units = int(usage_frame.get("promptTokenCount", 0) or 0)
                    if usage_frame.get("candidatesTokenCount") is not None:
                        candidate_units = int(usage_frame.get("candidatesTokenCount", 0) or 0)
                candidates = frame.get("candidates")
                if isinstance(candidates, (list, tuple)) and candidates:
                    first = candidates[0]
                    content = first.get("content") if isinstance(first, Mapping) else None
                    parts = content.get("parts", ()) if isinstance(content, Mapping) else ()
                    for part in parts:
                        if not isinstance(part, Mapping):
                            continue
                        text = str(part.get("text") or "")
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
        if prompt_units >= 0 and candidate_units >= 0:
            usage = reported_usage(
                request, input_units=prompt_units, output_units=candidate_units,
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


def _gemini_schema(value: Any) -> Any:
    """Our schema, in the OpenAPI-style subset ``responseSchema`` accepts.

    Drops ``additionalProperties`` (the subset has no such keyword) and
    renders tuples — including ``required`` — as lists; everything else maps
    through unchanged. What this loses server-side, local validation keeps.
    """
    if isinstance(value, Mapping):
        return {
            key: _gemini_schema(item)
            for key, item in value.items()
            if key != "additionalProperties"
        }
    if isinstance(value, tuple):
        return [_gemini_schema(item) for item in value]
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
