# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Consent: every way an answer stops counting.

Each test here is a way somebody could be made to appear to have agreed to
something they did not. The refusals are the feature.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import unittest

from capability.apply.approval import DEFAULT_APPROVAL_TTL_SECONDS

from companion.approvals import (
    ApprovalGate,
    ApprovalRequirement,
    CompanionApprovalStore,
    RefusingConsent,
    ScriptedConsent,
    destination_fingerprint,
    requirements_for,
)
from companion.errors import (
    ApprovalDenied,
    ApprovalExpired,
    ApprovalMismatch,
    ApprovalReplayed,
)
from companion.executor import PlannedOperation, TaskPlan
from companion.session import CompanionSession
from companion.task import CompanionTask
from companion.tools import ToolBroker

from .support import FULL_REQUEST, CompanionTestCase


def a_task(**kwargs: object) -> CompanionTask:
    task = CompanionTask.create(
        task_id="task-1", session_id="ses-1", request="Notify me", now=0.0
    )
    return replace(task, **kwargs) if kwargs else task


def a_plan(revision: int = 1, *, name: str = "publish-notice") -> TaskPlan:
    return TaskPlan(
        plan_id="plan-1", revision=revision, summary="notify",
        operations=(PlannedOperation(name=name, tool="notice.publish", arguments={"text": "hi"}),),
    )


def a_requirement(destination: str = "local") -> ApprovalRequirement:
    return ApprovalRequirement(
        action="interrupt_user_work",
        reason="This would interrupt you.",
        destination=destination,
        alternatives=("Do this later.",),
        operation_name="publish-notice",
    )


class RequirementDerivationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.session = CompanionSession.create(session_id="ses-1", title="t", now=0.0)
        self.broker = ToolBroker()

    def test_an_interrupting_tool_needs_consent_even_if_the_executor_says_otherwise(self) -> None:
        plan = TaskPlan(plan_id="p", revision=1, summary="s", operations=(
            PlannedOperation(name="publish-notice", tool="notice.publish", requires_approval=False),
        ))
        requirements = requirements_for(
            a_task(), self.session, plan,
            executor_is_local=True, broker=self.broker,
        )
        self.assertEqual([item.action for item in requirements], ["interrupt_user_work"])

    def test_a_local_free_plan_needs_no_consent(self) -> None:
        plan = TaskPlan(plan_id="p", revision=1, summary="s", operations=(
            PlannedOperation(name="count", tool="text.count_words"),
        ))
        self.assertEqual(
            requirements_for(a_task(), self.session, plan, executor_is_local=True, broker=self.broker),
            (),
        )

    def test_a_remote_executor_needs_dispatch_and_disclosure_consent(self) -> None:
        plan = TaskPlan(plan_id="p", revision=1, summary="s", operations=(
            PlannedOperation(name="count", tool="text.count_words"),
        ))
        requirements = requirements_for(
            a_task(classification="personal"), self.session, plan,
            executor_is_local=False, executor_provider_id="test-provider", broker=self.broker,
        )
        actions = [item.action for item in requirements]
        self.assertIn("remote_dispatch", actions)
        self.assertIn("send_sensitive_data", actions)

    def test_an_operation_with_an_external_destination_needs_consent(self) -> None:
        plan = TaskPlan(plan_id="p", revision=1, summary="s", operations=(
            PlannedOperation(name="ship", tool="text.count_words", destination="test-provider"),
        ))
        requirements = requirements_for(
            a_task(), self.session, plan, executor_is_local=True, broker=self.broker
        )
        self.assertIn("remote_dispatch", [item.action for item in requirements])

    def test_a_requirement_must_offer_an_alternative(self) -> None:
        with self.assertRaisesRegex(ApprovalMismatch, "what the user gets if they decline"):
            ApprovalRequirement(action="remote_dispatch", reason="because", alternatives=())

    def test_only_sensitive_actions_are_asked_about(self) -> None:
        with self.assertRaisesRegex(ApprovalMismatch, "not a sensitive action"):
            ApprovalRequirement(action="have_a_biscuit", reason="x", alternatives=("no",))


class GateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = CompanionApprovalStore()
        self.gate = ApprovalGate(self.store, consent=ScriptedConsent(granted_actions=("interrupt_user_work",)))

    def raise_one(self, task: CompanionTask, plan: TaskPlan, requirement: ApprovalRequirement, *, now: float = 100.0):
        transition = self.gate.transition_id(plan, 0, requirement)
        request, response, reference = self.gate.raise_request(
            task, requirement, plan, transition_id=transition, now=now
        )
        return transition, request, reference

    def test_a_granted_approval_authorises_its_own_step(self) -> None:
        task, plan, requirement = a_task(), a_plan(), a_requirement()
        transition, request, reference = self.raise_one(task, plan, requirement)
        task = task.with_approval(reference)
        resolved = self.gate.resolve(
            task, request.request_id, plan=plan, requirement=requirement,
            transition_id=transition, now=101.0,
        )
        self.assertEqual(resolved.decision, "granted")

    def test_no_response_is_a_refusal_and_nothing_happens(self) -> None:
        gate = ApprovalGate(CompanionApprovalStore(), consent=RefusingConsent())
        task, plan, requirement = a_task(), a_plan(), a_requirement()
        transition = gate.transition_id(plan, 0, requirement)
        request, _, reference = gate.raise_request(task, requirement, plan, transition_id=transition, now=100.0)
        task = task.with_approval(reference)
        with self.assertRaisesRegex(ApprovalDenied, "safe default is denial"):
            gate.resolve(task, request.request_id, plan=plan, requirement=requirement,
                         transition_id=transition, now=101.0)

    def test_a_denied_approval_is_a_refusal(self) -> None:
        gate = ApprovalGate(
            CompanionApprovalStore(),
            consent=ScriptedConsent(denied_actions=("interrupt_user_work",)),
        )
        task, plan, requirement = a_task(), a_plan(), a_requirement()
        transition = gate.transition_id(plan, 0, requirement)
        request, _, reference = gate.raise_request(task, requirement, plan, transition_id=transition, now=100.0)
        task = task.with_approval(reference)
        with self.assertRaises(ApprovalDenied):
            gate.resolve(task, request.request_id, plan=plan, requirement=requirement,
                         transition_id=transition, now=101.0)

    def test_an_expired_request_is_refused(self) -> None:
        gate = ApprovalGate(CompanionApprovalStore(), consent=RefusingConsent())
        task, plan, requirement = a_task(), a_plan(), a_requirement()
        transition = gate.transition_id(plan, 0, requirement)
        request, _, reference = gate.raise_request(task, requirement, plan, transition_id=transition, now=100.0)
        task = task.with_approval(reference)
        with self.assertRaises(ApprovalExpired):
            gate.resolve(
                task, request.request_id, plan=plan, requirement=requirement,
                transition_id=transition, now=100.0 + DEFAULT_APPROVAL_TTL_SECONDS + 1.0,
            )

    def test_an_expired_grant_is_refused(self) -> None:
        task, plan, requirement = a_task(), a_plan(), a_requirement()
        transition, request, reference = self.raise_one(task, plan, requirement)
        task = task.with_approval(reference)
        with self.assertRaises(ApprovalExpired):
            self.gate.resolve(
                task, request.request_id, plan=plan, requirement=requirement,
                transition_id=transition, now=100.0 + DEFAULT_APPROVAL_TTL_SECONDS + 1.0,
            )

    def test_an_approval_cannot_be_spent_twice(self) -> None:
        task, plan, requirement = a_task(), a_plan(), a_requirement()
        transition, request, reference = self.raise_one(task, plan, requirement)
        task = task.with_approval(reference)
        first = self.gate.resolve(task, request.request_id, plan=plan, requirement=requirement,
                                  transition_id=transition, now=101.0)
        task = task.with_approval(first)
        with self.assertRaisesRegex(ApprovalReplayed, "cannot be spent twice"):
            self.gate.resolve(task, request.request_id, plan=plan, requirement=requirement,
                              transition_id=transition, now=102.0)

    def test_an_approval_for_another_task_is_refused(self) -> None:
        task, plan, requirement = a_task(), a_plan(), a_requirement()
        transition, request, reference = self.raise_one(task, plan, requirement)
        other = replace(a_task(), task_id="task-2")
        with self.assertRaisesRegex(ApprovalMismatch, "does not belong to task"):
            self.gate.resolve(other, request.request_id, plan=plan, requirement=requirement,
                              transition_id=transition, now=101.0)

    def test_an_approval_for_another_transition_is_refused(self) -> None:
        task, plan, requirement = a_task(), a_plan(), a_requirement()
        transition, request, reference = self.raise_one(task, plan, requirement)
        task = task.with_approval(reference)
        with self.assertRaisesRegex(ApprovalMismatch, "is being used for"):
            self.gate.resolve(task, request.request_id, plan=plan, requirement=requirement,
                              transition_id="some-other-step", now=101.0)

    def test_a_superseded_plan_invalidates_its_approval(self) -> None:
        task, plan, requirement = a_task(), a_plan(), a_requirement()
        transition, request, reference = self.raise_one(task, plan, requirement)
        task = task.with_approval(reference)
        revised = a_plan(revision=2)
        with self.assertRaisesRegex(ApprovalMismatch, "superseded plan"):
            self.gate.resolve(task, request.request_id, plan=revised, requirement=requirement,
                              transition_id=transition, now=101.0)

    def test_a_changed_destination_invalidates_its_approval(self) -> None:
        task, plan, requirement = a_task(), a_plan(), a_requirement("local")
        transition, request, reference = self.raise_one(task, plan, requirement)
        task = task.with_approval(reference)
        moved = a_requirement("test-provider")
        with self.assertRaisesRegex(ApprovalMismatch, "has changed since the question was answered"):
            self.gate.resolve(task, request.request_id, plan=plan, requirement=moved,
                              transition_id=transition, now=101.0)

    def test_a_destination_fingerprint_covers_the_declaration_not_just_the_name(self) -> None:
        first = destination_fingerprint(
            destination="test-provider",
            provider_declaration={"retention": "none", "trainsOnInput": False},
        )
        second = destination_fingerprint(
            destination="test-provider",
            provider_declaration={"retention": "logged", "trainsOnInput": True},
        )
        self.assertNotEqual(first, second)

    def test_an_identical_replan_asks_the_same_question(self) -> None:
        # Consent is bound to the plan's content, so an executor that replans
        # into the same plan does not have to ask a person twice.
        plan = a_plan()
        same = TaskPlan(plan_id="plan-1", revision=9, summary="notify", operations=plan.operations)
        requirement = a_requirement()
        self.assertEqual(
            self.gate.transition_id(plan, 0, requirement),
            self.gate.transition_id(same, 0, requirement),
        )


class DurableApprovalTests(unittest.TestCase):
    def test_answers_from_a_previous_run_do_not_survive(self) -> None:
        import tempfile

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "approvals.json"

        first = CompanionApprovalStore(path=path)
        gate = ApprovalGate(first, consent=ScriptedConsent(granted_actions=("interrupt_user_work",)))
        task, plan, requirement = a_task(), a_plan(), a_requirement()
        transition = gate.transition_id(plan, 0, requirement)
        request, _, reference = gate.raise_request(task, requirement, plan, transition_id=transition, now=100.0)
        self.assertEqual(first.decision_for(request.request_id).decision, "granted")

        second = CompanionApprovalStore.load(path)
        self.assertEqual(second.decision_for(request.request_id).decision, "expired")
        self.assertTrue(second.warnings)
        self.assertIn("does not survive a restart", second.warnings[0])
        # The question itself survives, so a user can see what was asked.
        self.assertIn(request.request_id, second.requests)

    def test_a_pending_request_from_a_previous_run_is_expired(self) -> None:
        import tempfile

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "approvals.json"

        store = CompanionApprovalStore(path=path)
        gate = ApprovalGate(store, consent=RefusingConsent())
        task, plan, requirement = a_task(), a_plan(), a_requirement()
        transition = gate.transition_id(plan, 0, requirement)
        request, _, _ = gate.raise_request(task, requirement, plan, transition_id=transition, now=100.0)
        store.save()

        reloaded = CompanionApprovalStore.load(path)
        self.assertEqual(reloaded.decision_for(request.request_id).decision, "expired")
        self.assertEqual(reloaded.pending(), ())

    def test_a_superseded_plan_invalidates_stored_grants(self) -> None:
        store = CompanionApprovalStore()
        gate = ApprovalGate(store, consent=ScriptedConsent(granted_actions=("interrupt_user_work",)))
        task, plan, requirement = a_task(), a_plan(), a_requirement()
        transition = gate.transition_id(plan, 0, requirement)
        request, _, _ = gate.raise_request(task, requirement, plan, transition_id=transition, now=100.0)
        lapsed = store.invalidate_for_plan("plan-2")
        self.assertEqual(lapsed, (request.request_id,))
        self.assertEqual(store.decision_for(request.request_id).decision, "expired")


class ApprovalThroughTheRuntimeTests(CompanionTestCase):
    def test_nobody_answering_blocks_the_task_and_performs_nothing(self) -> None:
        runtime = self.started()  # RefusingConsent by default
        session = runtime.create_session("Refusing")
        task = runtime.submit_task(session.session_id, FULL_REQUEST)
        final = runtime.run_task(session.session_id, task.task_id)
        self.assertEqual(final.state, "blocked")
        self.assertFalse(
            any(item["toolId"] == "notice.publish" for item in runtime.broker.invocations),
            "the interrupting tool must not run without consent",
        )
        self.assertEqual([item.decision for item in final.approvals], ["denied"])

    def test_consent_lets_the_interrupting_operation_run(self) -> None:
        runtime = self.started(consent=self.granting("interrupt_user_work"))
        session = runtime.create_session("Granting")
        task = runtime.submit_task(session.session_id, FULL_REQUEST)
        final = runtime.run_task(session.session_id, task.task_id)
        self.assertEqual(final.state, "completed")
        self.assertTrue(any(item["toolId"] == "notice.publish" for item in runtime.broker.invocations))

    def test_a_revision_withdraws_the_consent_given_for_the_previous_plan(self) -> None:
        runtime = self.started(consent=self.granting("interrupt_user_work"))
        session = runtime.create_session("Revising")
        task = runtime.submit_task(session.session_id, FULL_REQUEST)
        runtime.run_task(session.session_id, task.task_id)
        withdrawals = [
            event for event in runtime.events(session.session_id, task_id=task.task_id)
            if event.event_type == "approval_resolved" and event.payload.get("decision") == "expired"
        ]
        self.assertTrue(withdrawals, "the superseded plan's approval should be withdrawn on the record")
        self.assertIn("supersededPlanId", withdrawals[0].payload)

    def test_every_approval_question_is_in_the_record_with_its_alternatives(self) -> None:
        runtime = self.started(consent=self.granting("interrupt_user_work"))
        session = runtime.create_session("Recorded")
        task = runtime.submit_task(session.session_id, FULL_REQUEST)
        runtime.run_task(session.session_id, task.task_id)
        asked = [
            event.payload for event in runtime.events(session.session_id, task_id=task.task_id)
            if event.event_type == "approval_requested" and not event.payload.get("batch")
        ]
        self.assertTrue(asked)
        for payload in asked:
            self.assertTrue(payload["request"]["alternatives"])
            self.assertEqual(payload["request"]["safeDefault"], "denied")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
