# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Usage and cost: measured, reported and estimated are three different words.

§16's trap is treating an estimate as a billed amount. Every figure in this
module carries its ``basis`` — ``measured`` (we counted it), ``reported`` (the
provider said so), ``estimated`` (we computed it from a pricing reference) —
and nothing downstream may add two figures of different basis into one number
without keeping the weaker word. A ledger that says "spent 12 units" where 9
were reported and 3 were estimated says "at least 9, estimated 12", and the
:meth:`UsageLedger.spent_units` accessor returns both so a ceiling check can
be conservative in the direction that protects the wallet: ceilings are
checked against the *higher* of the two readings.

Ceilings are enforced **before** a generation starts
(:meth:`UsageLedger.check_budget`), because a ceiling noticed afterwards has
already been spent through. This mirrors ``CostPolicy``'s stance that zero
means "nothing may be spent" — there is deliberately no way to express "no
limit" with a number, only the explicit absence of a policy.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from .errors import AgentSchemaError, GenerationBudgetExceeded

__all__ = [
    "USAGE_BASES",
    "UsageLedger",
    "UsageReport",
]

USAGE_BASES = ("measured", "reported", "estimated")


@dataclass(frozen=True)
class UsageReport:
    """One generation's accounting, basis included.

    ``input_units`` and ``output_units`` are tokens where the provider counts
    tokens and the provider's own unit where it does not; ``unit_name`` says
    which. Cost figures are integer cost units (the same currency-free unit
    ``CompanionTask.cost_limit_units`` uses) plus an optional provider-reported
    currency amount kept separately — the two are never merged.
    """

    request_id: str
    provider_id: str
    input_units: int = 0
    output_units: int = 0
    cached_units: int = 0
    unit_name: str = "tokens"
    tool_rounds: int = 0
    generation_seconds: float = 0.0
    reported_cost_units: int = 0
    estimated_cost_units: int = 0
    currency: str = ""
    reported_currency_amount: float = 0.0
    pricing_reference: str = ""
    basis: str = "measured"

    def __post_init__(self) -> None:
        if self.basis not in USAGE_BASES:
            raise AgentSchemaError(f"usage basis {self.basis!r} is not one of {USAGE_BASES}")
        for name, value in (
            ("input units", self.input_units),
            ("output units", self.output_units),
            ("cached units", self.cached_units),
            ("tool rounds", self.tool_rounds),
            ("reported cost", self.reported_cost_units),
            ("estimated cost", self.estimated_cost_units),
        ):
            if not isinstance(value, int) or value < 0:
                raise AgentSchemaError(f"{name} must be a non-negative integer")
        if self.generation_seconds < 0 or self.reported_currency_amount < 0:
            raise AgentSchemaError("durations and amounts must be non-negative")
        if self.reported_currency_amount and not self.currency:
            raise AgentSchemaError("a currency amount without a currency is not an amount")

    @property
    def spent_units(self) -> int:
        """The conservative reading: the higher of reported and estimated."""
        return max(self.reported_cost_units, self.estimated_cost_units)

    def to_json(self) -> dict[str, Any]:
        return {
            "requestId": self.request_id,
            "providerId": self.provider_id,
            "inputUnits": self.input_units,
            "outputUnits": self.output_units,
            "cachedUnits": self.cached_units,
            "unitName": self.unit_name,
            "toolRounds": self.tool_rounds,
            "generationSeconds": self.generation_seconds,
            "reportedCostUnits": self.reported_cost_units,
            "estimatedCostUnits": self.estimated_cost_units,
            "spentUnits": self.spent_units,
            "currency": self.currency,
            "reportedCurrencyAmount": self.reported_currency_amount,
            "pricingReference": self.pricing_reference,
            "basis": self.basis,
        }


class UsageLedger:
    """Accumulates per task and per session, and refuses before overspending.

    Thread-safe because the worker records from its own thread while protocol
    operations read totals from the endpoint's. The ledger is process-local
    accounting for ceilings and display; the durable record of spending is the
    task document's ``spent_cost_units``, written by the runtime.
    """

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._by_task: dict[str, list[UsageReport]] = {}
        self._by_session: dict[str, int] = {}

    def record(self, session_id: str, task_id: str, report: UsageReport) -> None:
        with self._guard:
            self._by_task.setdefault(task_id, []).append(report)
            self._by_session[session_id] = (
                self._by_session.get(session_id, 0) + report.spent_units
            )

    def task_reports(self, task_id: str) -> tuple[UsageReport, ...]:
        with self._guard:
            return tuple(self._by_task.get(task_id, ()))

    def task_spent_units(self, task_id: str) -> int:
        with self._guard:
            return sum(item.spent_units for item in self._by_task.get(task_id, ()))

    def session_spent_units(self, session_id: str) -> int:
        with self._guard:
            return self._by_session.get(session_id, 0)

    def check_budget(
        self,
        *,
        session_id: str,
        task_id: str,
        task_limit_units: int,
        session_limit_units: int,
        next_generation_estimate_units: int = 0,
    ) -> None:
        """Refuse the next generation before it spends, not after.

        A zero limit means nothing may be spent — the ``CostPolicy`` meaning —
        so a paid generation against a zero ceiling is refused even when the
        ledger is empty.
        """
        task_spent = self.task_spent_units(task_id)
        session_spent = self.session_spent_units(session_id)
        projected_task = task_spent + next_generation_estimate_units
        projected_session = session_spent + next_generation_estimate_units
        if next_generation_estimate_units and projected_task > task_limit_units:
            raise GenerationBudgetExceeded(
                f"task has spent {task_spent} units and the next generation is "
                f"estimated at {next_generation_estimate_units}; the task ceiling is {task_limit_units}",
                limit="task-cost", measured=projected_task, allowed=task_limit_units,
            )
        if next_generation_estimate_units and projected_session > session_limit_units:
            raise GenerationBudgetExceeded(
                f"session has spent {session_spent} units and the next generation is "
                f"estimated at {next_generation_estimate_units}; the session ceiling is {session_limit_units}",
                limit="session-cost", measured=projected_session, allowed=session_limit_units,
            )
        if not next_generation_estimate_units:
            # A free generation still may not start once a ceiling is already
            # crossed: the ledger being at or over the line is the stop.
            if task_spent > task_limit_units:
                raise GenerationBudgetExceeded(
                    f"task has spent {task_spent} of {task_limit_units} units",
                    limit="task-cost", measured=task_spent, allowed=task_limit_units,
                )
            if session_spent > session_limit_units:
                raise GenerationBudgetExceeded(
                    f"session has spent {session_spent} of {session_limit_units} units",
                    limit="session-cost", measured=session_spent, allowed=session_limit_units,
                )

    def forget_task(self, task_id: str) -> None:
        """Drop per-task detail once the task is terminal; session totals remain."""
        with self._guard:
            self._by_task.pop(task_id, None)

    def status(self) -> dict[str, Any]:
        with self._guard:
            return {
                "tasksTracked": len(self._by_task),
                "sessionsTracked": len(self._by_session),
            }
