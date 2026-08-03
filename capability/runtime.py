# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""One call that runs the whole pipeline, for callers who want the answer.

Every stage is separately importable and separately testable, which is how the
rest of this package is built. This module exists so that the common case — *"I
have a machine, tell me what runs on it and why"* — does not require a caller to
know the stage order or to thread five values through it by hand.

It adds no logic. :class:`Assessment` holds the output of each stage, so a
caller that needs to inspect the budget behind a decision, or the score behind
the budget, can reach it without re-running anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .budget import Budget, compute_budget
from .discovery import DEFAULT_BUDGET_MS, discover
from .engine import evaluate
from .model import Inventory
from .plan import ExecutionPlan
from .policy import Policy, load_policy
from .registry import Registry, load_registry
from .scores import ScoreSet, compute_scores

__all__ = ["Assessment", "assess", "assess_current_machine"]


@dataclass(frozen=True)
class Assessment:
    """Every stage's output for one evaluation, kept so none is recomputed."""

    inventory: Inventory
    scores: ScoreSet
    budget: Budget
    plan: ExecutionPlan
    registry: Registry
    policy: Policy

    def to_json(self) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "inventory": self.inventory.to_json(),
            "scores": self.scores.to_json(),
            "budget": self.budget.to_json(),
            "plan": self.plan.to_json(),
            "policy": self.policy.to_json(),
        }


def assess(
    inventory: Inventory,
    *,
    policy: Policy | None = None,
    registry: Registry | None = None,
    previous: ExecutionPlan | None = None,
    now: float = 0.0,
) -> Assessment:
    """Score, budget and plan one inventory. Pure: nothing is probed here."""
    resolved_policy = policy if policy is not None else Policy()
    resolved_registry = registry if registry is not None else load_registry()
    scores = compute_scores(inventory)
    budget = compute_budget(
        inventory, scores, resolved_policy,
        essential_floor_bytes=resolved_registry.essential_floor_bytes(),
    )
    plan = evaluate(inventory, scores, budget, resolved_registry, resolved_policy, previous=previous, now=now)
    return Assessment(inventory, scores, budget, plan, resolved_registry, resolved_policy)


def assess_current_machine(
    *,
    budget_ms: int = DEFAULT_BUDGET_MS,
    policy_path: Path | None = None,
    user_policy_path: Path | None = None,
    service_directory: Path | None = None,
    probe_runtimes: bool = True,
) -> Assessment:
    """Discover this machine and assess it.

    The only function in the package that both touches hardware and reaches a
    decision. Reachability probing is enabled only when policy configured
    endpoints, so a default installation contacts nothing.
    """
    policy = load_policy(policy_path, user_path=user_policy_path)
    inventory = discover(
        budget_ms=budget_ms,
        probe_runtimes=probe_runtimes,
        probe_reachability=bool(policy.reachability_endpoints),
        endpoints=policy.reachability_endpoints,
    )
    return assess(inventory, policy=policy, registry=load_registry(service_directory))
