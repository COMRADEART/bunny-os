# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What every HTTP adapter does the same way, written once.

The outcome-shaping rules live here so no adapter improvises them:

* A :class:`~companion.agents.wire.WireError` becomes a failed outcome carrying
  the error's §17 kind — unless the cancellation signal is set, in which case
  the broken read *is* the cancellation working (the wire layer cancels by
  closing the connection under the reader) and the outcome says ``cancelled``,
  not ``connection``.
* The stream's terminal event and the returned outcome must agree; the helper
  emits the terminal event itself so they cannot drift.
* Usage figures the provider reported keep basis ``reported``; figures we
  computed from byte counts keep basis ``estimated``; the two never merge.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from ..adapter import CancellationSignal, GenerationOutcome, StreamEventFactory
from ..request import GenerationRequest
from ..stream import StreamEvent
from ..usage import UsageReport
from ..wire import WireError

__all__ = [
    "chunked",
    "estimated_usage",
    "outcome_for_wire_error",
    "reported_usage",
]


def outcome_for_wire_error(
    request: GenerationRequest,
    error: WireError,
    *,
    emit: Callable[[StreamEvent], None],
    events: StreamEventFactory,
    cancellation: CancellationSignal,
    started: bool,
) -> GenerationOutcome:
    """Turn a wire failure into the outcome the worker records.

    ``started`` says whether ``generation_started`` was emitted; a stream that
    never started emits nothing (an assembler would refuse a terminal-first
    stream, and rightly).
    """
    if cancellation.cancelled:
        if started:
            emit(events.cancelled(cancellation.reason))
        return GenerationOutcome(
            request_id=request.request_id,
            provider_id=request.provider_id,
            ok=False,
            cancelled=True,
            detail=cancellation.reason,
        )
    if started:
        emit(events.failed(str(error)))
    return GenerationOutcome(
        request_id=request.request_id,
        provider_id=request.provider_id,
        ok=False,
        failure_kind=error.kind,
        detail=str(error),
        retry_hint_seconds=error.retry_hint_seconds,
    )


def reported_usage(
    request: GenerationRequest,
    *,
    input_units: int,
    output_units: int,
    cached_units: int = 0,
    generation_seconds: float = 0.0,
    units_per_kilotoken: int = 0,
    pricing_reference: str = "",
) -> UsageReport:
    """Provider-counted figures. The cost estimate stays labelled an estimate."""
    estimated_cost = 0
    if units_per_kilotoken:
        total = input_units + output_units
        estimated_cost = -(-total // 1000) * units_per_kilotoken
    return UsageReport(
        request_id=request.request_id,
        provider_id=request.provider_id,
        input_units=max(0, int(input_units)),
        output_units=max(0, int(output_units)),
        cached_units=max(0, int(cached_units)),
        generation_seconds=max(0.0, generation_seconds),
        estimated_cost_units=estimated_cost,
        pricing_reference=pricing_reference,
        basis="reported",
    )


def estimated_usage(
    request: GenerationRequest,
    *,
    output_bytes: int,
    generation_seconds: float = 0.0,
    units_per_kilotoken: int = 0,
    pricing_reference: str = "",
) -> UsageReport:
    """What we can honestly claim when the provider reported nothing."""
    input_bytes = sum(len(item.content.encode("utf-8")) for item in request.messages)
    input_units = max(1, input_bytes // 4)
    output_units = max(0, output_bytes // 4)
    estimated_cost = 0
    if units_per_kilotoken:
        estimated_cost = -(-(input_units + output_units) // 1000) * units_per_kilotoken
    return UsageReport(
        request_id=request.request_id,
        provider_id=request.provider_id,
        input_units=input_units,
        output_units=output_units,
        generation_seconds=max(0.0, generation_seconds),
        estimated_cost_units=estimated_cost,
        pricing_reference=pricing_reference,
        basis="estimated",
    )


def chunked(text: str, *, bound: int) -> tuple[str, ...]:
    """Split provider text into delta-sized pieces without breaking code points."""
    if not text:
        return ()
    pieces: list[str] = []
    current = ""
    current_bytes = 0
    for character in text:
        size = len(character.encode("utf-8", errors="replace"))
        if current and current_bytes + size > bound:
            pieces.append(current)
            current, current_bytes = "", 0
        current += character
        current_bytes += size
    if current:
        pieces.append(current)
    return tuple(pieces)
