# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from companion.approval import (
    ApprovalCentre,
    ApprovalExpired,
    ApprovalReplay,
    ApprovalResolution,
    ApprovalScopeMismatch,
    SupersededPlan,
)
from companion.coordination import (
    AgentCoordinator,
    CoordinationError,
    CoordinationLimitExceeded,
    CoordinationLimits,
    ExecutionProposal,
    ExecutionResult,
    ExecutorAdapter,
    HarmlessLocalExecutor,
    ReadOnlyReviewContext,
    ReviewerAdapter,
)
from companion.events import observed_event
from companion.model import AgentIdentity, CostPolicy, ReviewerObservation, TaskSession


def make_task(task_id: str = "task-agents", *, request: str = "secret request body") -> TaskSession:
    return TaskSession(
        task_id=task_id,
        session_id="session-agents",
        user_request=request,
        display_summary="Sanitized display summary",
        task_classification="local_test",
        data_locality_requirements=("local-only",),
        offline_required=True,
    )


class CountingExecutor(ExecutorAdapter):
    def __init__(self, *, cost: int = 0, fail: bool = False) -> None:
        self.calls = 0
        self.cost = cost
        self.fail = fail
        self._identity = AgentIdentity("test/executor")

    @property
    def identity(self):
        return self._identity

    def plan(self, task):
        return ExecutionProposal("plan-test", "transition-test", "operation-test", "tool.test", "Test action", False)

    def execute(self, task, proposal):
        self.calls += 1
        if self.fail:
            raise RuntimeError("provider failed")
        return ExecutionResult(proposal.operation_id, True, "Completed", "result:test", cost_minor_units=self.cost)

    def cancel(self, task_id):
        return True


class FixedReviewer(ReviewerAdapter):
    def __init__(self, name: str, action: str) -> None:
        self._identity = AgentIdentity(name)
        self.action = action
        self.context: ReadOnlyReviewContext | None = None

    @property
    def identity(self):
        return self._identity

    def observe(self, context):
        self.context = context
        return ReviewerObservation(
            reviewer=self.identity.agent_id,
            severity="warning",
            category="correctness",
            summary="A bounded reviewer observation.",
            suggested_action=self.action,
        )


class TimeoutReviewer(FixedReviewer):
    def observe(self, context):
        raise TimeoutError("bounded timeout")


class MalformedReviewer(FixedReviewer):
    def observe(self, context):
        return {"not": "an observation"}


class CoordinationTests(unittest.TestCase):
    def event(self, task):
        return observed_event(
            session_id=task.session_id,
            task_id=task.task_id,
            event_type="planning_started",
            source="test.executor",
        ).with_sequence(1)

    def test_one_executor_only(self) -> None:
        coordinator = AgentCoordinator()
        coordinator.assign_executor("task-agents", CountingExecutor())
        with self.assertRaises(CoordinationError):
            coordinator.assign_executor("task-agents", CountingExecutor())

    def test_reviewer_interface_has_no_tool_execution(self) -> None:
        reviewer = FixedReviewer("test/reviewer", "Proceed")
        self.assertFalse(hasattr(ReviewerAdapter, "execute"))
        self.assertFalse(hasattr(reviewer, "execute"))

    def test_reviewer_disagreement_is_preserved(self) -> None:
        task = make_task()
        coordinator = AgentCoordinator()
        coordinator.assign_executor(task.task_id, CountingExecutor())
        coordinator.add_reviewer(task.task_id, FixedReviewer("test/reviewer-a", "Proceed"))
        coordinator.add_reviewer(task.task_id, FixedReviewer("test/reviewer-b", "Revise first"))
        result = coordinator.review(task, (self.event(task),))
        self.assertEqual(len(result.observations), 2)
        self.assertEqual(len(result.disagreements), 1)
        self.assertTrue(result.user_escalation_required)
        self.assertFalse(result.to_json()["consensusGuaranteesCorrectness"])

    def test_reviewer_timeout_becomes_warning(self) -> None:
        task = make_task()
        coordinator = AgentCoordinator()
        coordinator.assign_executor(task.task_id, CountingExecutor())
        coordinator.add_reviewer(task.task_id, TimeoutReviewer("test/timeout", "Proceed"))
        result = coordinator.review(task, (self.event(task),))
        self.assertEqual(result.observations[0].category, "performance")
        self.assertIn("timed out", result.observations[0].summary)

    def test_malformed_observation_is_not_trusted(self) -> None:
        task = make_task()
        coordinator = AgentCoordinator()
        coordinator.assign_executor(task.task_id, CountingExecutor())
        coordinator.add_reviewer(task.task_id, MalformedReviewer("test/malformed", "Proceed"))
        result = coordinator.review(task, (self.event(task),))
        self.assertEqual(result.observations[0].category, "quality")
        self.assertIn("malformed", result.observations[0].summary)

    def test_sensitive_request_body_is_not_shared_with_reviewer(self) -> None:
        task = make_task(request="password=hunter2 full sensitive payload")
        reviewer = FixedReviewer("test/privacy", "Proceed")
        coordinator = AgentCoordinator()
        coordinator.assign_executor(task.task_id, CountingExecutor())
        coordinator.add_reviewer(task.task_id, reviewer)
        coordinator.review(task, (self.event(task),))
        encoded = str(reviewer.context.to_json())
        self.assertNotIn("hunter2", encoded)
        self.assertNotIn("userRequest", encoded)

    def test_review_round_limit(self) -> None:
        task = make_task()
        coordinator = AgentCoordinator(CoordinationLimits(maximum_review_rounds=1))
        coordinator.assign_executor(task.task_id, CountingExecutor())
        coordinator.review(task, (self.event(task),))
        with self.assertRaises(CoordinationLimitExceeded):
            coordinator.review(task, (self.event(task),))

    def test_paid_cost_is_refused_before_executor_call(self) -> None:
        task = make_task()
        executor = CountingExecutor(cost=1)
        coordinator = AgentCoordinator()
        coordinator.assign_executor(task.task_id, executor)
        proposal = ExecutionProposal(
            "plan-test", "transition-test", "operation-test", "tool.test", "Paid action", False,
            estimated_cost_units=1,
        )
        with self.assertRaises(CoordinationLimitExceeded):
            coordinator.execute(task, proposal)
        self.assertEqual(executor.calls, 0)

    def test_remote_execution_is_refused_by_locality_before_call(self) -> None:
        task = make_task()
        executor = CountingExecutor()
        coordinator = AgentCoordinator()
        coordinator.assign_executor(task.task_id, executor)
        proposal = ExecutionProposal(
            "plan-test", "transition-test", "operation-test", "tool.test", "Remote action", False,
            destination="remote", provider_id="provider.remote",
        )
        with self.assertRaises(CoordinationError):
            coordinator.execute(task, proposal)
        self.assertEqual(executor.calls, 0)

    def test_executor_or_provider_failure_is_not_relabelled_success(self) -> None:
        task = make_task()
        coordinator = AgentCoordinator()
        coordinator.assign_executor(task.task_id, CountingExecutor(fail=True))
        with self.assertRaises(RuntimeError):
            coordinator.execute(task, coordinator.plan(task))


class ApprovalCentreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.centre = ApprovalCentre(Path(self.directory.name) / "approvals.json")
        self.task = make_task("task-approval")
        self.agent = HarmlessLocalExecutor().identity

    def tearDown(self) -> None:
        self.directory.cleanup()

    def proposal(self, **changes) -> ExecutionProposal:
        values = {
            "plan_id": "plan-approval",
            "transition_id": "transition-approval",
            "operation_id": "operation-approval",
            "tool_id": "tool.approval",
            "action_summary": "Record a harmless local result.",
            "approval_required": True,
        }
        values.update(changes)
        return ExecutionProposal(**values)

    def resolution(self, view, **changes) -> ApprovalResolution:
        values = {
            "request_id": view.request_id,
            "decision": "approve",
            "plan_id": view.plan_id,
            "transition_id": view.transition_id,
            "destination": view.destination,
            "provider_destination": view.provider_destination,
        }
        values.update(changes)
        return ApprovalResolution(**values)

    def requested(self, proposal=None, *, now=100.0):
        record = self.centre.request(self.task, proposal or self.proposal(), self.agent, now=now)
        return self.centre.view(record, task_id=self.task.task_id, now=now)

    def test_unanswered_safe_default_authorizes_nothing(self) -> None:
        view = self.requested()
        self.assertEqual(view.status, "pending")
        self.assertEqual(view.safe_default, "denied")
        self.assertEqual(self.centre.store.approved_services(view.plan_id, 101.0), frozenset())

    def test_expired_request_is_rejected(self) -> None:
        view = self.requested(now=0.0)
        with self.assertRaises(ApprovalExpired):
            self.centre.resolve(self.resolution(view), current_plan_id=view.plan_id, now=901.0)

    def test_superseded_plan_is_rejected(self) -> None:
        view = self.requested()
        with self.assertRaises(SupersededPlan):
            self.centre.resolve(self.resolution(view), current_plan_id="plan-new", now=101.0)

    def test_replayed_decision_is_rejected(self) -> None:
        view = self.requested()
        self.centre.resolve(self.resolution(view), current_plan_id=view.plan_id, now=101.0)
        with self.assertRaises(ApprovalReplay):
            self.centre.resolve(self.resolution(view), current_plan_id=view.plan_id, now=102.0)

    def test_denial_grants_nothing(self) -> None:
        view = self.requested()
        outcome = self.centre.resolve(
            self.resolution(view, decision="deny"),
            current_plan_id=view.plan_id,
            now=101.0,
        )
        self.assertEqual(outcome.decision, "denied")
        self.assertEqual(self.centre.store.approved_services(view.plan_id, 102.0), frozenset())

    def test_transition_mismatch_is_rejected(self) -> None:
        view = self.requested()
        with self.assertRaises(ApprovalScopeMismatch):
            self.centre.resolve(
                self.resolution(view, transition_id="transition-other"),
                current_plan_id=view.plan_id,
                now=101.0,
            )

    def test_remote_paid_provider_is_fully_displayed_and_scoped(self) -> None:
        proposal = self.proposal(
            approval_action="paid_provider",
            destination="remote",
            provider_id="provider.example",
            estimated_cost_units=4,
            data_affected="sanitized prompt",
            alternatives=("Use the slower local executor.",),
        )
        view = self.requested(proposal)
        self.assertEqual(view.provider_destination, "provider.example")
        self.assertEqual(view.estimated_cost_units, 4)
        with self.assertRaises(ApprovalScopeMismatch):
            self.centre.resolve(
                self.resolution(view, provider_destination="provider.other"),
                current_plan_id=view.plan_id,
                now=101.0,
            )

    def test_destructive_action_requires_and_shows_alternative(self) -> None:
        view = self.requested(self.proposal(
            approval_action="discard_unsaved_state",
            alternatives=("Save the work and retry.",),
        ))
        self.assertEqual(view.safe_default, "denied")
        self.assertEqual(view.alternatives, ("Save the work and retry.",))

    def test_cancel_task_is_a_denial_plus_cancellation_signal(self) -> None:
        view = self.requested()
        outcome = self.centre.resolve(
            self.resolution(view, decision="cancel_task"),
            current_plan_id=view.plan_id,
            now=101.0,
        )
        self.assertTrue(outcome.cancel_task)
        self.assertEqual(outcome.record.decision, "denied")


if __name__ == "__main__":
    unittest.main()
