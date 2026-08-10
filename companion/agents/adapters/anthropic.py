# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Anthropic Messages adapter: explicit configuration, silent probe.

Speaks ``POST /v1/messages`` with its typed SSE events — ``message_start``,
``content_block_delta``, ``message_delta``, ``message_stop`` — rather than
the OpenAI chat dialect. The system prompt travels in the provider's separate
``system`` parameter: system-role messages are joined and lifted out of the
message list, because that is the provider's own contract and leaving policy
text inside the turn list would put it where this provider does not read
policy.

**This adapter serves only explicit remote configurations.** A configuration
without both ``remote: true`` and ``enabled: true`` is refused outright:
probe answers unavailable, generate answers a failed outcome, and neither
opens a socket first. The guard is the backstop that keeps the remote
adapters unreachable through a selection bug or a mislabelled local entry.

**The probe never touches the network.** A "harmless" authenticated GET
still transmits the API key — the key is data, and §8 requires approval
before *any* remote transfer — so there is no request a credentialed probe
could make that is not already a disclosure. The probe signature cannot take
a secret, and deliberately so: a remote adapter's availability rung is
"configured and credential present", verified by the registry through
:func:`~companion.agents.credentials.credential_status` without any value
transiting, and the adapter's first real network contact is an approved
generation. ``probe`` therefore always returns unavailable with the reason
and an empty model listing; the emptiness is honesty, not a defect.

**The sampling seed is not transmittable.** The Messages API has no seed
parameter, so this adapter does not claim determinism for this provider: the
same request may legitimately produce a different answer, and the §9
explanation for selecting it must not pretend otherwise. The seed stays in
the request record; it is simply never sent.

**Structured output has no server-side enforcement here.** There is no
``response_format`` on this surface; a structured request relies on
instruction-following, and the local validator — which always runs, for every
provider — is the actual check. The deltas are still emitted as
``structured_delta`` so the assembler routes them to the validating path;
weaker server-side constraint changes nothing about what is accepted.

**The credential exists at one call site.** The ``x-api-key`` header is
built inline from ``secret.reveal()`` at the dispatch call and nowhere else —
not in a variable that outlives the call, not in an exception, not in a log,
not in anything this module returns. A generation given no secret is refused
with ``authentication`` before any connection opens.

Usage: ``message_start`` carries the input token count, the final
``message_delta`` carries the cumulative output count; with both present the
figures are recorded with basis ``reported``, and a stream that ends without
either falls back to the byte estimate, labelled ``estimated`` — the two
never mix.
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
from ..wire import WireError, WireSession, failure_kind_for_status
from .common import chunked, estimated_usage, outcome_for_wire_error, reported_usage

__all__ = ["AnthropicAdapter"]

#: The API version header the Messages surface requires. A constant, not
#: configuration: the parsing below is written against this revision's frames.
_ANTHROPIC_VERSION = "2023-06-01"


class AnthropicAdapter:
    """One instance per service; connections are per-generation."""

    #: The Messages API has no ``response_format``; structured requests rely
    #: on instruction-following plus the local validation that always runs.
    #: Declared ``True`` because the adapter *can* honour the request — the
    #: enforcement is simply ours rather than the provider's.
    supports_structured_output = True

    def __init__(self, *, session: WireSession | None = None) -> None:
        self._session = session if session is not None else WireSession()

    @property
    def adapter_id(self) -> str:
        return "anthropic"

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
        system_text = "\n\n".join(
            item.content for item in request.messages if item.role == "system"
        )
        body: dict[str, Any] = {
            "model": request.model_id,
            "stream": True,
            "max_tokens": request.maximum_output_tokens,
            "temperature": request.sampling.temperature,
            "top_p": request.sampling.top_p,
            "messages": [
                {"role": item.role, "content": item.content}
                for item in request.messages if item.role != "system"
            ],
        }
        if system_text:
            body["system"] = system_text
        structured = bool(request.structured_schema_reference)
        started = False
        output_bytes = 0
        input_units = output_units = -1
        try:
            if cancellation.cancelled:
                return outcome_for_wire_error(
                    request, WireError("not dispatched", kind="connection"),
                    emit=emit, events=events, cancellation=cancellation, started=False,
                )
            for status, line in self._session.stream_lines(
                target, "POST", "/messages",
                body=body,
                headers={
                    "x-api-key": secret.reveal(),
                    "anthropic-version": _ANTHROPIC_VERSION,
                },
                timeout=request.deadline_seconds,
                request_id=request.request_id,
            ):
                if not started:
                    if status != 200:
                        raise WireError(
                            _error_text(line) or f"/messages answered {status}",
                            kind=failure_kind_for_status(status),
                        )
                    emit(events.started())
                    started = True
                    continue
                if not line or not line.startswith("data:"):
                    # ``event:`` lines restate the type carried in the JSON.
                    continue
                payload = line[len("data:"):].strip()
                try:
                    frame = json.loads(payload)
                except json.JSONDecodeError:
                    raise WireError("anthropic emitted a non-JSON SSE frame", kind="invalid-response") from None
                if not isinstance(frame, Mapping):
                    raise WireError("anthropic emitted a non-object SSE frame", kind="invalid-response")
                frame_type = str(frame.get("type", ""))
                if frame_type == "error":
                    raise _frame_error(frame)
                if frame_type == "message_start":
                    message = frame.get("message")
                    if isinstance(message, Mapping):
                        usage_frame = message.get("usage")
                        if isinstance(usage_frame, Mapping) and usage_frame.get("input_tokens") is not None:
                            input_units = int(usage_frame.get("input_tokens", 0) or 0)
                elif frame_type == "content_block_delta":
                    delta = frame.get("delta")
                    if isinstance(delta, Mapping) and delta.get("type") == "text_delta":
                        text = str(delta.get("text") or "")
                        if text:
                            output_bytes += len(text.encode("utf-8"))
                            for piece in chunked(text, bound=MAX_DELTA_BYTES):
                                emit(events.structured(piece) if structured else events.delta(piece))
                elif frame_type == "message_delta":
                    usage_frame = frame.get("usage")
                    if isinstance(usage_frame, Mapping) and usage_frame.get("output_tokens") is not None:
                        output_units = int(usage_frame.get("output_tokens", 0) or 0)
                elif frame_type == "message_stop":
                    break
                if cancellation.cancelled:
                    raise WireError("cancelled between frames", kind="connection")
        except WireError as error:
            return outcome_for_wire_error(
                request, error, emit=emit, events=events,
                cancellation=cancellation, started=started,
            )
        if input_units >= 0 and output_units >= 0:
            usage = reported_usage(
                request, input_units=input_units, output_units=output_units,
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


def _frame_error(frame: Mapping[str, Any]) -> WireError:
    """An in-stream ``error`` event, mapped to the §17 kind it names."""
    error = frame.get("error")
    error_type = ""
    message = ""
    if isinstance(error, Mapping):
        error_type = str(error.get("type", ""))
        message = str(error.get("message", ""))[:200]
    kind = "invalid-response"
    if error_type == "rate_limit_error":
        kind = "rate-limit"
    elif error_type == "authentication_error":
        kind = "authentication"
    return WireError(f"anthropic reported {error_type or 'error'}: {message}", kind=kind)


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
