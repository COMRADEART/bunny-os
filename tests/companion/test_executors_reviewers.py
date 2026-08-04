# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Executor selection, and the boundary reviewers may not cross."""

from __future__ import annotations

from dataclasses import replace
import unittest

from companion.coordination import CoordinationPolicy, ExecutorLeases, reviewer_context, run_review_round
from companion.errors import (
    CoordinationLimitExceeded,
    MalformedOutput,
    ReviewerViolation,
)
from companion.executor import DeterministicLocalExecutor, ExecutorDeclaration, PlannedOperation, TaskPlan
from companion.reviewer import DeterministicLocalReviewer, ReviewObservation, observation_from_json
from companion.tools import ToolBroker

from .support import (
    FULL_REQUEST,
    SIMPLE_REQUEST,
    ChattyReviewer,
    CompanionTestCase,
    CostlyExecutor,
    MalformedExecutor,
    RemoteExecutor,
    SlowReviewer,
    ToolCallingReviewer,
    UnavailableExecutor,
    remote_permissive_assessment,
)


class ExecutorSelectionTests(CompanionTestCase):
    def test_exactly_one_executor_holds_a_task(self) -> None:
        leases = ExecutorLeases()
        leases.acquire("task-1", "local.deterministic", now=0.0)
        with self.assertRaisesRegex(CoordinationLimitExceeded, "already held"):
            leases.acquire("task-1", "local.other", now=1.0)
        leases.release("task-1")
        leases.acquire("task-1", "local.other", now=2.0)
        self.assertEqual(leases.holder("task-1"), "local.other")

    def test_the_lease_is_released_when_a_task_finishes(self) -> None:
        runtime = self.started()
        session, task = self.completed_task(runtime)
        self.assertEqual(runtime.leases.holder(task.task_id), "")

    def test_an_unavailable_executor_blocks_the_task_and_says_why(self) -> None:
        runtime = self.started(executors=(UnavailableExecutor(),))
        session = runtime.create_session("Unavailable")
        task = runtime.submit_task(session.session_id, SIMPLE_REQUEST)
        final = runtime.run_task(session.session_id, task.task_id)
        self.assertEqual(final.state, "blocked")
        self.assertIn("not installed", " ".join(item.summary for item in final.errors))

    def test_a_malformed_plan_fails_the_task_rather_than_being_coerced(self) -> None:
        runtime = self.started(executors=(MalformedExecutor(broken="plan"),), reviewers=())
        session = runtime.create_session("Malformed plan")
        task = runtime.submit_task(session.session_id, SIMPLE_REQUEST)
        final = runtime.run_task(session.session_id, task.task_id)
        self.assertEqual(final.state, "failed")
        self.assertIn("TaskPlan", " ".join(item.summary for item in final.errors))

    def test_a_malformed_result_fails_the_task(self) -> None:
        runtime = self.started(executors=(MalformedExecutor(broken="result"),), reviewers=())
        session = runtime.create_session("Malformed result")
        task = runtime.submit_task(session.session_id, SIMPLE_REQUEST)
        final = runtime.run_task(session.session_id, task.task_id)
        self.assertEqual(final.state, "failed")
        self.assertIn("TaskResult", " ".join(item.summary for item in final.errors))

    def test_a_capability_incompatible_executor_is_not_selected(self) -> None:
        narrow = DeterministicLocalExecutor()
        narrow.declaration = replace(narrow.declaration, supported_task_types=("summarise",))
        runtime = self.started(executors=(narrow,))
        session = runtime.create_session("Wrong type")
        task = runtime.submit_task(session.session_id, SIMPLE_REQUEST)  # classifies as compute
        final = runtime.run_task(session.session_id, task.task_id)
        self.assertEqual(final.state, "blocked")
        self.assertIn("does not serve task type", " ".join(item.summary for item in final.errors) + " ".join(
            str(event.payload) for event in runtime.events(session.session_id, task_id=task.task_id)
        ))

    def test_a_privacy_incompatible_executor_is_not_selected(self) -> None:
        limited = DeterministicLocalExecutor()
        limited.declaration = replace(limited.declaration, maximum_privacy_class="public")
        runtime = self.started(executors=(limited,))
        session = runtime.create_session("Too private")
        task = runtime.submit_task(session.session_id, SIMPLE_REQUEST)  # personal by default
        final = runtime.run_task(session.session_id, task.task_id)
        self.assertEqual(final.state, "blocked")
        reasons = " ".join(
            str(event.payload) for event in runtime.events(session.session_id, task_id=task.task_id)
            if event.event_type == "capability_checked"
        )
        self.assertIn("may hold data up to public", reasons)

    def test_a_paid_executor_with_no_budget_is_not_selected(self) -> None:
        runtime = self.started(executors=(CostlyExecutor(),))
        session = runtime.create_session("No budget")
        task = runtime.submit_task(session.session_id, SIMPLE_REQUEST, cost_limit_units=0)
        final = runtime.run_task(session.session_id, task.task_id)
        self.assertEqual(final.state, "blocked")
        reasons = " ".join(
            str(event.payload) for event in runtime.events(session.session_id, task_id=task.task_id)
            if event.event_type == "capability_checked"
        )
        self.assertIn("permits no spend", reasons)

    def test_local_incapability_is_never_an_argument_for_remote(self) -> None:
        # The router's rule, asserted through the companion: a session that does
        # not permit remote gets a blocked task, never a quiet dispatch.
        runtime = self.started(
            executors=(RemoteExecutor(),),
            assessment=remote_permissive_assessment(),
        )
        session = runtime.create_session("No remote permission")
        task = runtime.submit_task(session.session_id, SIMPLE_REQUEST)
        final = runtime.run_task(session.session_id, task.task_id)
        self.assertEqual(final.state, "blocked")
        self.assertEqual(final.executor_id, "")

    def test_a_cost_ceiling_stops_an_expensive_plan(self) -> None:
        # Consent is granted so that the spend is refused by the *ceiling* and
        # not by the earlier approval gate — which would pass the test for the
        # wrong reason and leave the ceiling untested.
        runtime = self.started(
            executors=(CostlyExecutor(units=5),),
            reviewers=(),
            consent=self.granting("paid_provider"),
            policy=CoordinationPolicy(cost_ceiling_units=1),
        )
        session = runtime.create_session("Too expensive")
        task = runtime.submit_task(session.session_id, SIMPLE_REQUEST, cost_limit_units=10)
        final = runtime.run_task(session.session_id, task.task_id)
        self.assertEqual(final.state, "failed")
        self.assertIn("ceiling", " ".join(item.summary for item in final.errors))

    def test_a_tool_call_ceiling_stops_a_runaway_plan(self) -> None:
        runtime = self.started(reviewers=(), policy=CoordinationPolicy(maximum_tool_calls=0))
        session = runtime.create_session("Too many calls")
        task = runtime.submit_task(session.session_id, SIMPLE_REQUEST)
        final = runtime.run_task(session.session_id, task.task_id)
        self.assertEqual(final.state, "failed")
        self.assertIn("tool calls", " ".join(item.summary for item in final.errors))

    def test_an_undeclared_executor_fails_closed(self) -> None:
        with self.assertRaisesRegex(MalformedOutput, "unknown task types"):
            ExecutorDeclaration(
                executor_id="x", provider_id="y", implementation_id="z",
                supported_task_types=("telepathy",),
            )
        bare = ExecutorDeclaration(executor_id="x", provider_id="y", implementation_id="z")
        self.assertFalse(bare.fully_declared)

    def test_a_remote_executor_cannot_declare_a_secret_ceiling(self) -> None:
        with self.assertRaisesRegex(MalformedOutput, "secret data never leaves"):
            ExecutorDeclaration(
                executor_id="x", provider_id="y", implementation_id="z",
                local=False, supported_task_types=("compute",), maximum_privacy_class="secret",
            )


class ReviewerBoundaryTests(CompanionTestCase):
    def test_a_reviewer_is_given_nothing_it_could_act_with(self) -> None:
        seen = ChattyReviewer()
        runtime = self.started(reviewers=(seen,))
        self.completed_task(runtime)
        self.assertTrue(seen.contexts)
        context = seen.contexts[0]
        # The whole surface a reviewer receives, enumerated. Anything added here
        # later has to be a deliberate decision rather than an accident.
        self.assertEqual(
            sorted(context),
            ["classification", "contextWithheld", "events", "plan", "roundNumber", "task"],
        )

    def test_the_broker_refuses_a_reviewer_that_reaches_for_a_tool(self) -> None:
        broker = ToolBroker()
        hostile = ToolCallingReviewer(broker=broker)
        runtime = self.started(reviewers=(hostile,), broker=broker)
        session, task = self.completed_task(runtime)
        self.assertIn("ReviewerViolation", hostile.raised)
        self.assertEqual(len(broker.refusals), 1)
        self.assertEqual(broker.refusals[0]["reason"], "reviewers may not execute tools")
        # The task still completed: a hostile reviewer is contained, not fatal.
        self.assertEqual(task.state, "completed")

    def test_the_broker_refuses_a_reviewer_caller_directly(self) -> None:
        broker = ToolBroker()
        with self.assertRaises(ReviewerViolation):
            broker.invoke("text.count_words", {"text": "x"}, caller="reviewer:anybody")

    def test_a_reviewer_that_never_answers_is_left_behind_and_recorded(self) -> None:
        runtime = self.started(
            reviewers=(SlowReviewer(),),
            policy=CoordinationPolicy(reviewer_timeout_seconds=0.05),
        )
        session, task = self.completed_task(runtime)
        self.assertEqual(task.state, "completed")
        absences = [
            event for event in runtime.events(session.session_id, task_id=task.task_id)
            if event.event_type == "reviewer_observation" and event.payload.get("absent")
        ]
        self.assertTrue(absences)
        self.assertIn("did not answer", absences[0]["summary"] if isinstance(absences[0], dict)
                      else absences[0].payload["summary"])

    def test_a_malformed_observation_is_refused_and_the_reviewer_recorded_absent(self) -> None:
        broken = DeterministicLocalReviewer(malformed=True)
        runtime = self.started(reviewers=(broken,))
        session, task = self.completed_task(runtime)
        self.assertEqual(task.state, "completed")
        absent = [
            event.payload for event in runtime.events(session.session_id, task_id=task.task_id)
            if event.event_type == "reviewer_observation" and event.payload.get("absent")
        ]
        self.assertTrue(absent)
        self.assertIn("may not speak for another", absent[0]["summary"])

    def test_a_reviewer_may_not_attribute_an_observation_to_another(self) -> None:
        with self.assertRaisesRegex(MalformedOutput, "may not speak for another"):
            observation_from_json(
                {"reviewerId": "someone.else", "severity": "info", "category": "correctness", "summary": "x"},
                reviewer_id="local.test-reviewer",
            )

    def test_a_disagreement_is_recorded_and_survives_the_revision(self) -> None:
        runtime = self.started()
        session, task = self.completed_task(runtime, SIMPLE_REQUEST)
        events = runtime.events(session.session_id, task_id=task.task_id)
        disagreements = [item for item in events if item.event_type == "reviewer_disagreement"]
        self.assertTrue(disagreements, "the first plan omits validation and should be objected to")
        # The task went on to complete, and the objection is still in the record.
        self.assertEqual(task.state, "completed")
        self.assertEqual(events[-1].event_type, "task_completed")
        self.assertLess(disagreements[0].sequence, events[-1].sequence)

    def test_the_review_round_ceiling_ends_the_loop_without_erasing_the_objection(self) -> None:
        always = ChattyReviewer(severity="blocking")
        runtime = self.started(reviewers=(always,), policy=CoordinationPolicy(maximum_review_rounds=2))
        session, task = self.completed_task(runtime, SIMPLE_REQUEST)
        self.assertEqual(task.state, "completed")
        self.assertEqual(task.review_rounds, 2)
        disagreements = [
            item for item in runtime.events(session.session_id, task_id=task.task_id)
            if item.event_type == "reviewer_disagreement"
        ]
        self.assertEqual(len(disagreements), 2)

    def test_sensitive_context_is_withheld_from_reviewers(self) -> None:
        seen = ChattyReviewer()
        runtime = self.started(reviewers=(seen,))
        session = runtime.create_session("Sensitive")
        task = runtime.submit_task(session.session_id, SIMPLE_REQUEST, classification="sensitive")
        runtime.run_task(session.session_id, task.task_id)
        context = seen.contexts[0]
        self.assertTrue(context["contextWithheld"])
        self.assertEqual(context["task"]["originalRequest"], "[withheld: sensitive]")
        # The plan's structure survives; its arguments do not.
        operations = context["plan"]["operations"]
        self.assertTrue(operations)
        self.assertEqual(operations[0]["name"], "count-words")
        self.assertEqual(set(operations[0]["arguments"].values()), {"[redacted]"})

    def test_reviewers_do_not_see_each_other(self) -> None:
        first = ChattyReviewer(reviewer_id="local.first")
        second = ChattyReviewer(reviewer_id="local.second")
        runtime = self.started(reviewers=(first, second))
        self.completed_task(runtime)
        for context in (*first.contexts, *second.contexts):
            text = str(context)
            self.assertNotIn("local.first seen", text)
            self.assertNotIn("local.second seen", text)

    def test_the_same_reviewer_selected_twice_runs_once(self) -> None:
        reviewer = DeterministicLocalReviewer()
        context = reviewer_context(
            task_view={"originalRequest": "validate this"},
            plan_view={"operations": []},
            event_views=[],
            classification="internal",
            policy=CoordinationPolicy(),
            round_number=1,
        )
        outcome = run_review_round((reviewer, reviewer), context, CoordinationPolicy(), round_number=1)
        self.assertEqual(len(outcome.absent), 1)
        self.assertIn("selected twice", outcome.absent[0][1])

    def test_too_many_reviewers_is_refused(self) -> None:
        policy = CoordinationPolicy(maximum_reviewers=1)
        with self.assertRaisesRegex(CoordinationLimitExceeded, "against a ceiling"):
            policy.check_reviewers(2)

    def test_zero_reviewers_is_a_valid_configuration(self) -> None:
        runtime = self.started(reviewers=())
        session, task = self.completed_task(runtime)
        self.assertEqual(task.state, "completed")
        self.assertEqual(task.review_rounds, 0)

    def test_an_observation_needs_a_reviewer_and_a_summary(self) -> None:
        with self.assertRaisesRegex(MalformedOutput, "must name its reviewer"):
            ReviewObservation(reviewer_id="", summary="x")
        with self.assertRaisesRegex(MalformedOutput, "says nothing"):
            ReviewObservation(reviewer_id="r", summary="")


class ExecutorContractTests(unittest.TestCase):
    def test_a_plan_fingerprint_changes_with_its_operations(self) -> None:
        first = TaskPlan(plan_id="p", revision=1, summary="s", operations=(
            PlannedOperation(name="a", tool="text.count_words"),
        ))
        second = TaskPlan(plan_id="p", revision=1, summary="s", operations=(
            PlannedOperation(name="a", tool="text.count_words"),
            PlannedOperation(name="b", tool="text.checksum"),
        ))
        self.assertNotEqual(first.fingerprint, second.fingerprint)
        # And the same plan fingerprints the same, which is what makes an
        # approval carry across an identical replan.
        repeat = TaskPlan(plan_id="p", revision=9, summary="s", operations=first.operations)
        self.assertEqual(first.fingerprint, repeat.fingerprint)

    def test_an_operation_key_identifies_the_act_not_its_position(self) -> None:
        plan = TaskPlan(plan_id="p", revision=1, summary="s", operations=(
            PlannedOperation(name="a", tool="text.count_words", arguments={"text": "x"}),
        ))
        self.assertEqual(plan.keys_for("task-1"), plan.keys_for("task-1"))
        self.assertNotEqual(plan.keys_for("task-1"), plan.keys_for("task-2"))

        # The same act under a later revision, a different plan id, and at a
        # different position keeps its key. This is what makes the completed-key
        # skip reachable at all; keying the position instead made every replan
        # produce fresh keys and silently re-ran work the record proved done.
        revised = TaskPlan(plan_id="other-plan", revision=7, summary="s", operations=(
            PlannedOperation(name="z", tool="text.checksum", arguments={"text": "x"}),
            PlannedOperation(name="a", tool="text.count_words", arguments={"text": "x"}),
        ))
        self.assertEqual(plan.keys_for("task-1")[0], revised.keys_for("task-1")[1])

    def test_an_operation_key_changes_with_the_act(self) -> None:
        def key(**kwargs) -> str:
            base = {"name": "a", "tool": "text.count_words", "arguments": {"text": "x"}}
            base.update(kwargs)
            return TaskPlan(
                plan_id="p", revision=1, summary="s",
                operations=(PlannedOperation(**base),),
            ).keys_for("task-1")[0]

        original = key()
        self.assertNotEqual(original, key(name="b"))
        self.assertNotEqual(original, key(tool="text.checksum"))
        self.assertNotEqual(original, key(arguments={"text": "y"}))
        self.assertNotEqual(original, key(destination="test-provider"))

    def test_a_plan_revision_starts_at_one(self) -> None:
        with self.assertRaisesRegex(MalformedOutput, "begin at 1"):
            TaskPlan(plan_id="p", revision=0, summary="s")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
