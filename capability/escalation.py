# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""ADR 0012 escalation ladder: deterministic observables, never confidence.

Escalation is a *permission to consider* a more capable destination, not a
silent failover. The model's self-reported confidence is not an input — the
type has no field for it, so it cannot gate a decision.

Observables, ranked as ADR 0012 names them:

1. plan step count
2. tool-call schema failure
3. repeated no-progress turns
4. context exceeding the model's true ``n_ctx`` (unknown ``n_ctx`` does not fire)
5. a missing declared capability
6. provider health

Locality is a security boundary. A candidate on the far side of that
boundary is rejected loudly (a reconstructible reason, consent required)
rather than filtered out of a failover chain.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = [
    "LOCALITY_RANK",
    "NO_PROGRESS_TURNS_AT",
    "PLAN_STEPS_AT",
    "SCHEMA_FAILURES_AT",
    "EscalationDecision",
    "EscalationObservables",
    "assess_escalation",
    "crosses_privacy_boundary",
    "refuse_silent_failover",
]

#: Plan length at which a local-only run is allowed to *consider* escalation.
#: Tuned to be sticky-local: short plans stay local; long agency may ask.
PLAN_STEPS_AT = 8
SCHEMA_FAILURES_AT = 2
NO_PROGRESS_TURNS_AT = 2

#: Increasing publicity. Crossing upward is a consent event.
LOCALITY_RANK = {
    "loopback": 0,
    "device-only": 0,
    "local": 0,
    "private-network": 1,
    "trusted-remote": 1,
    "hosted": 2,
    "any": 2,
}


@dataclass(frozen=True)
class EscalationObservables:
    """What the runtime actually saw. No confidence, no TOPS, no guesses."""

    plan_step_count: int = 0
    tool_schema_failures: int = 0
    no_progress_turns: int = 0
    estimated_context_tokens: int = 0
    #: ``None`` means the true window was not read (no ``/props``, no probe).
    #: Unknown does not fire the n_ctx observable.
    true_n_ctx: int | None = None
    missing_capability: str = ""
    provider_healthy: bool = True
    local_generation_failed: bool = False
    current_locality: str = "loopback"
    candidate_locality: str = "hosted"
    user_consented: bool = False

    def __post_init__(self) -> None:
        for name, value in (
            ("plan_step_count", self.plan_step_count),
            ("tool_schema_failures", self.tool_schema_failures),
            ("no_progress_turns", self.no_progress_turns),
            ("estimated_context_tokens", self.estimated_context_tokens),
        ):
            if value < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.true_n_ctx is not None and self.true_n_ctx < 0:
            raise ValueError("true_n_ctx must be non-negative when known")

    def to_json(self) -> dict[str, Any]:
        return {
            "planStepCount": self.plan_step_count,
            "toolSchemaFailures": self.tool_schema_failures,
            "noProgressTurns": self.no_progress_turns,
            "estimatedContextTokens": self.estimated_context_tokens,
            "trueNCtx": self.true_n_ctx,
            "trueNCtxKnown": self.true_n_ctx is not None,
            "missingCapability": self.missing_capability,
            "providerHealthy": self.provider_healthy,
            "localGenerationFailed": self.local_generation_failed,
            "currentLocality": self.current_locality,
            "candidateLocality": self.candidate_locality,
            "userConsented": self.user_consented,
        }


@dataclass(frozen=True)
class EscalationDecision:
    """Whether remote may be *considered*, and every reason."""

    consider_remote: bool
    consent_required: bool
    silent_failover_refused: bool
    fired: tuple[str, ...]
    reasons: tuple[str, ...]
    action: str = "stay-local"

    def to_json(self) -> dict[str, Any]:
        return {
            "considerRemote": self.consider_remote,
            "consentRequired": self.consent_required,
            "silentFailoverRefused": self.silent_failover_refused,
            "fired": list(self.fired),
            "reasons": list(self.reasons),
            "action": self.action,
        }


def crosses_privacy_boundary(current: str, candidate: str) -> bool:
    """True when the candidate is strictly more public than the current side."""
    here = LOCALITY_RANK.get(current, 0)
    there = LOCALITY_RANK.get(candidate, 2)
    return there > here


def refuse_silent_failover(
    *,
    current_locality: str,
    candidate_locality: str,
    user_consented: bool,
) -> EscalationDecision | None:
    """Loud refusal when a failover would cross a locality boundary without consent.

    ``None`` means this candidate is not a cross-boundary act.
    """
    if not crosses_privacy_boundary(current_locality, candidate_locality):
        return None
    if user_consented:
        return None
    reason = (
        f"locality is a security boundary: {candidate_locality!r} is more public "
        f"than {current_locality!r}; silent failover is refused and consent is required"
    )
    return EscalationDecision(
        consider_remote=False,
        consent_required=True,
        silent_failover_refused=True,
        fired=("cross-boundary",),
        reasons=(reason,),
        action="consent-required",
    )


def _fired(observables: EscalationObservables) -> tuple[str, ...]:
    fired: list[str] = []
    if observables.plan_step_count >= PLAN_STEPS_AT:
        fired.append("plan-step-count")
    if observables.tool_schema_failures >= SCHEMA_FAILURES_AT:
        fired.append("tool-schema-failure")
    if observables.no_progress_turns >= NO_PROGRESS_TURNS_AT:
        fired.append("no-progress")
    if (
        observables.true_n_ctx is not None
        and observables.estimated_context_tokens > observables.true_n_ctx
    ):
        fired.append("n_ctx-overflow")
    if observables.missing_capability:
        fired.append("missing-capability")
    if not observables.provider_healthy:
        fired.append("provider-health")
    return tuple(fired)


def assess_escalation(
    observables: EscalationObservables,
    *,
    local_feasible: bool = True,
) -> EscalationDecision:
    """Decide whether remote may be considered.

    Observables are necessary, never sufficient on their own: a long plan that
    still fits locally stays local. Remote is considered only when something
    actually cannot continue here (local infeasible, local generation failed,
    n_ctx overflow, missing capability, or an unhealthy provider) *and* at
    least one observable fired.

    Crossing a locality boundary never returns a silent remote action.
    """
    fired = _fired(observables)
    local_stuck = (
        not local_feasible
        or observables.local_generation_failed
        or "n_ctx-overflow" in fired
        or "missing-capability" in fired
        or "provider-health" in fired
    )
    boundary = refuse_silent_failover(
        current_locality=observables.current_locality,
        candidate_locality=observables.candidate_locality,
        user_consented=observables.user_consented,
    )

    if not fired:
        return EscalationDecision(
            consider_remote=False,
            consent_required=False,
            silent_failover_refused=False,
            fired=(),
            reasons=("no ADR 0012 observable fired; staying local",),
            action="stay-local",
        )

    reasons = tuple(
        {
            "plan-step-count": (
                f"plan has {observables.plan_step_count} steps "
                f"(escalate-at {PLAN_STEPS_AT})"
            ),
            "tool-schema-failure": (
                f"tool-call schema failed {observables.tool_schema_failures} times "
                f"(escalate-at {SCHEMA_FAILURES_AT})"
            ),
            "no-progress": (
                f"no-progress for {observables.no_progress_turns} turns "
                f"(escalate-at {NO_PROGRESS_TURNS_AT})"
            ),
            "n_ctx-overflow": (
                f"context of ~{observables.estimated_context_tokens} tokens exceeds "
                f"true n_ctx {observables.true_n_ctx}"
            ),
            "missing-capability": (
                f"declared capability {observables.missing_capability!r} is missing"
            ),
            "provider-health": "the selected provider is not healthy",
        }[name]
        for name in fired
    )

    if not local_stuck:
        return EscalationDecision(
            consider_remote=False,
            consent_required=False,
            silent_failover_refused=False,
            fired=fired,
            reasons=(*reasons, "local execution is still feasible; observables do not override local-first"),
            action="stay-local",
        )

    if boundary is not None:
        return EscalationDecision(
            consider_remote=False,
            consent_required=True,
            silent_failover_refused=True,
            fired=(*fired, "cross-boundary"),
            reasons=(*reasons, *boundary.reasons),
            action="consent-required",
        )

    return EscalationDecision(
        consider_remote=True,
        consent_required=crosses_privacy_boundary(
            observables.current_locality, observables.candidate_locality
        ),
        silent_failover_refused=False,
        fired=fired,
        reasons=reasons,
        action="consider-remote" if not observables.user_consented else "remote-consented",
    )
