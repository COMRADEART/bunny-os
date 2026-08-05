# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared fixtures for the companion suite.

Everything here is deterministic: a frozen clock, sequential identifiers and a
simulated machine. A test that produced a different event stream on each run
could not assert on the stream, and the stream is what most of these tests are
about.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
import tempfile
from typing import Any, Mapping, Sequence
import unittest

from capability.runtime import Assessment, assess
from capability.simulate import simulate

from companion.approvals import CompanionApprovalStore, ConsentSource, RefusingConsent, ScriptedConsent
from companion.clock import FrozenClock
from companion.coordination import CoordinationPolicy
from companion.executor import (
    DeterministicLocalExecutor,
    ExecutorDeclaration,
    ExecutorHealth,
    PlannedOperation,
    TaskContext,
    TaskPlan,
    TaskResult,
)
from companion.ids import SequentialIds
from companion.reviewer import DeterministicLocalReviewer, ReviewContext, ReviewObservation
from companion.runtime import CompanionRuntime, RuntimeOptions
from companion.store import CompanionStore
from companion.tools import ToolBroker

#: A request that exercises the whole loop: an operation, a validation step the
#: first plan omits, and a notice that needs consent.
FULL_REQUEST = "Count the words in this note, validate the count, and notify me when it is done."

#: The same without the notice, so a test can reach completion without consent.
SIMPLE_REQUEST = "Count the words in this note and validate the count."


def machine(name: str = "laptop") -> Assessment:
    return assess(simulate(name))


@dataclass
class Harness:
    """One store, and any number of runtimes over it."""

    root: Path
    assessment: Assessment
    approvals: CompanionApprovalStore
    consent: ConsentSource = field(default_factory=RefusingConsent)
    policy: CoordinationPolicy = field(default_factory=CoordinationPolicy)

    def runtime(
        self,
        *,
        executors: Sequence[Any] | None = None,
        reviewers: Sequence[Any] | None = None,
        consent: ConsentSource | None = None,
        policy: CoordinationPolicy | None = None,
        broker: ToolBroker | None = None,
        clock: FrozenClock | None = None,
        assessment: Assessment | None = None,
    ) -> CompanionRuntime:
        """Build a fresh runtime over the same store — that is what a restart is."""
        return CompanionRuntime(RuntimeOptions(
            store=CompanionStore(self.root / "store"),
            assessment=assessment or self.assessment,
            executors=tuple(executors if executors is not None else (DeterministicLocalExecutor(),)),
            reviewers=tuple(reviewers if reviewers is not None else (DeterministicLocalReviewer(),)),
            broker=broker or ToolBroker(),
            approvals=self.approvals,
            consent=consent or self.consent,
            policy=policy or self.policy,
            clock=clock or FrozenClock(),
            ids=SequentialIds(),
        )).start()


class CompanionTestCase(unittest.TestCase):
    """Base class that gives each test its own store directory."""

    machine_name = "laptop"

    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = Path(self._directory.name)
        self.harness = Harness(
            root=self.root,
            assessment=machine(self.machine_name),
            approvals=CompanionApprovalStore(path=self.root / "approvals.json"),
        )

    def granting(self, *actions: str) -> ScriptedConsent:
        return ScriptedConsent(granted_actions=actions or ("interrupt_user_work",))

    def started(self, **kwargs: Any) -> CompanionRuntime:
        runtime = self.harness.runtime(**kwargs)
        self.addCleanup(runtime.stop)
        return runtime

    def completed_task(self, runtime: CompanionRuntime, request: str = SIMPLE_REQUEST):
        session = runtime.create_session("Test session")
        task = runtime.submit_task(session.session_id, request)
        return session, runtime.run_task(session.session_id, task.task_id)


# --------------------------------------------------------------------------- #
# Doubles. Each one models exactly one way a component can misbehave, so a test
# that fails names the misbehaviour rather than "the mock".
# --------------------------------------------------------------------------- #


@dataclass
class UnavailableExecutor:
    """An executor that is configured and cannot take work."""

    declaration: ExecutorDeclaration = field(default_factory=lambda: ExecutorDeclaration(
        executor_id="local.unavailable", provider_id="local", implementation_id="unavailable-1",
        local=True, supported_task_types=("compute", "unclassified"), maximum_privacy_class="secret",
    ))
    detail: str = "the local model is not installed"

    def health(self) -> ExecutorHealth:
        return ExecutorHealth(available=False, healthy=False, detail=self.detail)

    def plan(self, context: TaskContext) -> TaskPlan:  # pragma: no cover - never reached
        raise AssertionError("an unavailable executor must never be asked to plan")

    def result(self, context: TaskContext) -> TaskResult:  # pragma: no cover
        raise AssertionError("an unavailable executor must never be asked for a result")

    def cancel(self, context: TaskContext, reason: str) -> None:  # pragma: no cover
        return None


@dataclass
class MalformedExecutor:
    """An executor whose output is not its contract."""

    declaration: ExecutorDeclaration = field(default_factory=lambda: ExecutorDeclaration(
        executor_id="local.malformed", provider_id="local", implementation_id="malformed-1",
        local=True, supported_task_types=("compute", "unclassified"), maximum_privacy_class="secret",
    ))
    #: "plan" or "result"
    broken: str = "plan"

    def health(self) -> ExecutorHealth:
        return ExecutorHealth()

    def plan(self, context: TaskContext) -> Any:
        if self.broken == "plan":
            return {"not": "a plan"}
        return TaskPlan(plan_id="plan-ok", revision=max(1, context.plan_revision), summary="fine",
                        operations=(PlannedOperation(name="count-words", tool="text.count_words",
                                                     arguments={"text": "x"}),))

    def result(self, context: TaskContext) -> Any:
        return "not a result"

    def cancel(self, context: TaskContext, reason: str) -> None:
        return None


@dataclass
class RemoteExecutor:
    """A non-local executor. There is no provider behind it and never will be.

    It exists so the tests can prove that remote execution is refused, gated and
    approved for — none of which can be tested with only local executors, and
    none of which requires an actual provider integration.
    """

    declaration: ExecutorDeclaration = field(default_factory=lambda: ExecutorDeclaration(
        executor_id="remote.test", provider_id="test-provider", implementation_id="remote-1",
        local=False, supported_task_types=("compute", "unclassified"),
        cost_class="paid", maximum_privacy_class="internal",
    ))

    def health(self) -> ExecutorHealth:
        return ExecutorHealth()

    def plan(self, context: TaskContext) -> TaskPlan:  # pragma: no cover - gated before use
        return TaskPlan(plan_id="plan-remote", revision=max(1, context.plan_revision), summary="remote")

    def result(self, context: TaskContext) -> TaskResult:  # pragma: no cover
        return TaskResult(result_id="result-remote", summary="remote")

    def cancel(self, context: TaskContext, reason: str) -> None:  # pragma: no cover
        return None


@dataclass
class CostlyExecutor:
    """A local executor whose plan wants to spend money."""

    units: int = 500
    declaration: ExecutorDeclaration = field(default_factory=lambda: ExecutorDeclaration(
        executor_id="local.costly", provider_id="local", implementation_id="costly-1",
        local=True, supported_task_types=("compute", "unclassified"),
        cost_class="paid", maximum_privacy_class="secret",
    ))

    def health(self) -> ExecutorHealth:
        return ExecutorHealth()

    def plan(self, context: TaskContext) -> TaskPlan:
        return TaskPlan(
            plan_id="plan-costly", revision=max(1, context.plan_revision), summary="spend",
            operations=(PlannedOperation(
                name="count-words", tool="text.count_words", arguments={"text": "x"},
                estimated_cost_units=self.units,
            ),),
        )

    def result(self, context: TaskContext) -> TaskResult:  # pragma: no cover
        return TaskResult(result_id="result-costly", summary="done")

    def cancel(self, context: TaskContext, reason: str) -> None:  # pragma: no cover
        return None


@dataclass
class ToolCallingReviewer:
    """A hostile reviewer that tries to execute a tool.

    Handed a broker it was never given by the runtime — modelling a reviewer
    that obtained one some other way — so that the broker's own refusal is what
    is under test rather than the absence of a reference.
    """

    broker: ToolBroker
    reviewer_id: str = "local.hostile-reviewer"
    raised: str = ""

    def observe(self, context: ReviewContext) -> Sequence[ReviewObservation]:
        try:
            self.broker.invoke("text.count_words", {"text": "x"}, caller=f"reviewer:{self.reviewer_id}")
        except Exception as exc:
            self.raised = f"{type(exc).__name__}: {exc}"
            raise
        raise AssertionError("the broker permitted a reviewer to execute a tool")


@dataclass
class SlowReviewer:
    """A reviewer that never answers."""

    reviewer_id: str = "local.slow-reviewer"
    seconds: float = 30.0

    def observe(self, context: ReviewContext) -> Sequence[ReviewObservation]:
        import time

        time.sleep(self.seconds)
        return ()  # pragma: no cover - the timeout fires first


@dataclass
class ChattyReviewer:
    """A reviewer that records what it was shown, to prove what it was not."""

    reviewer_id: str = "local.chatty-reviewer"
    contexts: list[Mapping[str, Any]] = field(default_factory=list)
    severity: str = "info"

    def observe(self, context: ReviewContext) -> Sequence[ReviewObservation]:
        self.contexts.append(context.to_json())
        return (ReviewObservation(
            reviewer_id=self.reviewer_id, severity=self.severity, category="correctness",
            summary=f"round {context.round_number} seen",
        ),)


def remote_permissive_assessment() -> Assessment:
    """An assessment whose policy permits remote execution.

    Built from the real policy object rather than a stub, so a test that passes
    here is a statement about the shipped policy engine.
    """
    from capability.policy import Policy, RemoteExecutionPolicy

    policy = Policy(
        metered_network_allowed=True,
        remote_execution=RemoteExecutionPolicy(
            enabled=True,
            require_user_approval=True,
            allow_sensitive_data=False,
            permitted_providers=("test-provider",),
        ),
    )
    return assess(simulate("laptop"), policy=policy)


__all__ = [
    "ChattyReviewer",
    "CompanionTestCase",
    "CostlyExecutor",
    "FULL_REQUEST",
    "Harness",
    "MalformedExecutor",
    "RemoteExecutor",
    "SIMPLE_REQUEST",
    "SlowReviewer",
    "ToolCallingReviewer",
    "UnavailableExecutor",
    "machine",
    "remote_permissive_assessment",
    "replace",
]
