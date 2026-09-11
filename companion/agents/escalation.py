# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Agent-side ADR 0012 ladder: wrap the capability observables, add n_ctx.

The capability package owns the ladder so the task router and the companion
registry cannot drift. This module only adapts provider descriptors and
generation failures into those observables. There is still no confidence
input.
"""

from __future__ import annotations

from capability.escalation import (
    NO_PROGRESS_TURNS_AT,
    PLAN_STEPS_AT,
    SCHEMA_FAILURES_AT,
    EscalationDecision,
    EscalationObservables,
    assess_escalation,
    crosses_privacy_boundary,
    refuse_silent_failover,
)

__all__ = [
    "NO_PROGRESS_TURNS_AT",
    "PLAN_STEPS_AT",
    "SCHEMA_FAILURES_AT",
    "EscalationDecision",
    "EscalationObservables",
    "assess_escalation",
    "crosses_privacy_boundary",
    "observables_from_descriptor",
    "refuse_silent_failover",
]


def observables_from_descriptor(
    *,
    context_limit_tokens: int,
    estimated_context_tokens: int,
    provider_healthy: bool,
    missing_capability: str = "",
    plan_step_count: int = 0,
    tool_schema_failures: int = 0,
    no_progress_turns: int = 0,
    local_generation_failed: bool = False,
    current_locality: str = "loopback",
    candidate_locality: str = "hosted",
    user_consented: bool = False,
) -> EscalationObservables:
    """Build observables from a descriptor's *true* window when it is known.

    A context limit of ``0`` is unknown (the descriptor default), not a
    zero-token window, so it does not fire n_ctx overflow.
    """
    true_n_ctx = context_limit_tokens if context_limit_tokens > 0 else None
    return EscalationObservables(
        plan_step_count=plan_step_count,
        tool_schema_failures=tool_schema_failures,
        no_progress_turns=no_progress_turns,
        estimated_context_tokens=estimated_context_tokens,
        true_n_ctx=true_n_ctx,
        missing_capability=missing_capability,
        provider_healthy=provider_healthy,
        local_generation_failed=local_generation_failed,
        current_locality=current_locality,
        candidate_locality=candidate_locality,
        user_consented=user_consented,
    )
