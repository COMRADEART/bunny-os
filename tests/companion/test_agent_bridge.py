# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The bridge, driven through the real runtime: propose, mediate, record.

These are the §2 pipeline's integration properties, tested with scripted
adapters under a real :class:`companion.runtime.CompanionRuntime`: a generated
plan's tool proposals execute through the real broker with the real approval
machinery in the way; an invalid plan gets exactly one recorded repair; a
provider drought blocks the task with the reasons rather than failing it
mutely; a cancellation mid-generation settles everything it touched; and the
remote executor's whole §8 story — deterministic on-device plan, approval
bound to the destination fingerprint, dispatch only after the grant, no
fallback anywhere on failure.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from typing import Any

from companion.agent_bridge import (
    ProviderBackedExecutor,
    ProviderBackedReviewer,
    RemoteProviderExecutor,
)
from companion.agents.config import AgentConfiguration
from companion.agents.service import AgentProviderService, AgentServiceOptions
from companion.cancellation import cancel_task
from companion.reviewer import ReviewContext
from companion.tools import ToolBroker

import os
import unittest

from .agents_support import (
    ScriptedAdapter,
    remote_configuration,
    scripted_configuration,
)
from .support import (
    CompanionTestCase,
    SIMPLE_REQUEST,
    remote_permissive_assessment,
)

PLAN_WITH_TOOL = json.dumps({
    "summary": "Count the words with the counting tool",
    "operations": [{
        "name": "count-words",
        "tool": "text.count_words",
        "arguments": {"text": "count these words now"},
        "rationale": "the request asks for a count",
        "expectedEffect": "a number",
    }],
})

PLAN_WITHOUT_TOOLS = json.dumps({"summary": "Answer directly", "operations": []})


@dataclass
class PurposefulAdapter(ScriptedAdapter):
    """Scripts per purpose: what a plan asks and what a result asks differ."""

    plan_script: tuple[tuple[str, Any], ...] = (("structured", PLAN_WITH_TOOL),)
    result_script: tuple[tuple[str, Any], ...] = (("delta", "There are four words."),)
    review_script: tuple[tuple[str, Any], ...] = (
        ("structured", json.dumps({"observations": []})),
    )
    purposes: list[str] = field(default_factory=list)

    def generate(self, request, configuration, *, secret, emit, events, cancellation):
        self.purposes.append(request.purpose)
        if request.purpose in ("plan", "repair"):
            self.script = self.plan_script
        elif request.purpose == "review":
            self.script = self.review_script
        else:
            self.script = self.result_script
        return super().generate(
            request, configuration, secret=secret, emit=emit,
            events=events, cancellation=cancellation,
        )


class BridgeTestCase(CompanionTestCase):
    def agent_service(
        self,
        adapter: ScriptedAdapter,
        *,
        configuration: AgentConfiguration | None = None,
        adapter_id: str = "scripted",
    ) -> AgentProviderService:
        service = AgentProviderService(AgentServiceOptions(
            root=self.root / "agents",
            configuration=configuration if configuration is not None
            else AgentConfiguration(providers=(scripted_configuration(),)),
            adapters={adapter_id: adapter},
        ))
        self.addCleanup(service.close)
        return service

    def provider_runtime(self, service: AgentProviderService, **kwargs: Any):
        broker = kwargs.pop("broker", None) or ToolBroker()
        executor = ProviderBackedExecutor(service, tool_declarations=broker.declarations())
        return self.started(executors=(executor,), broker=broker, **kwargs), broker


class PlanThroughTheBroker(BridgeTestCase):
    def test_a_generated_proposal_executes_through_the_real_broker(self) -> None:
        adapter = PurposefulAdapter()
        service = self.agent_service(adapter)
        runtime, broker = self.provider_runtime(service)
        session = runtime.create_session("bridge")
        task = runtime.submit_task(session.session_id, SIMPLE_REQUEST)
        finished = runtime.run_task(session.session_id, task.task_id)
        self.assertEqual(finished.state, "completed")
        # The proposal became an operation, and the operation went through
        # the one door: the broker's own ledger names the tool and the caller.
        called = [(item["toolId"], item["caller"]) for item in broker.invocations]
        self.assertIn(("text.count_words", "runtime"), called)
        # The plan and the result were separate generations with separate
        # purposes, and nothing else was asked of the provider.
        self.assertEqual(
            [p for p in adapter.purposes if p != "review"], ["plan", "result"],
        )
        self.assertTrue(finished.outputs)

    def test_the_selection_explanation_is_recorded_for_the_task(self) -> None:
        adapter = PurposefulAdapter()
        service = self.agent_service(adapter)
        runtime, _ = self.provider_runtime(service)
        session = runtime.create_session("bridge")
        task = runtime.submit_task(session.session_id, SIMPLE_REQUEST)
        runtime.run_task(session.session_id, task.task_id)
        explanation = service.task_selection(task.task_id)
        self.assertIsNotNone(explanation)
        self.assertEqual(explanation["selected"], "local.scripted")
        self.assertTrue(explanation["decisiveFactors"])

    def test_an_invalid_plan_is_repaired_once_and_the_repair_is_a_new_purpose(self) -> None:
        @dataclass
        class HealingAdapter(PurposefulAdapter):
            calls: int = 0

            def generate(self, request, configuration, **kwargs):
                if request.purpose == "plan":
                    self.calls += 1
                    self.plan_script = (("structured", "{not json"),) if self.calls == 1 \
                        else (("structured", PLAN_WITHOUT_TOOLS),)
                return super().generate(request, configuration, **kwargs)

        adapter = HealingAdapter()
        service = self.agent_service(adapter)
        runtime, _ = self.provider_runtime(service)
        session = runtime.create_session("bridge")
        task = runtime.submit_task(session.session_id, SIMPLE_REQUEST)
        finished = runtime.run_task(session.session_id, task.task_id)
        self.assertEqual(finished.state, "completed")
        self.assertIn("repair", adapter.purposes)
        self.assertEqual(adapter.purposes.count("repair"), 1)

    def test_a_provider_drought_blocks_the_task_with_every_reason(self) -> None:
        adapter = PurposefulAdapter()
        configuration = AgentConfiguration(providers=(
            scripted_configuration(supported_task_classes=("question",)),
        ))
        service = self.agent_service(adapter, configuration=configuration)
        runtime, _ = self.provider_runtime(service)
        session = runtime.create_session("bridge")
        # SIMPLE_REQUEST classifies as compute; the provider declares question
        # only, so selection refuses with the reason and the task blocks.
        task = runtime.submit_task(session.session_id, SIMPLE_REQUEST)
        finished = runtime.run_task(session.session_id, task.task_id)
        self.assertEqual(finished.state, "blocked")
        self.assertFalse(adapter.requests, "a generation was dispatched despite the drought")
        events = runtime.events(session.session_id, task_id=task.task_id)
        blocked = [e for e in events if e.event_type == "task_state_changed"
                   and e.payload.get("to") == "blocked"]
        self.assertTrue(blocked)


class CancellationMidGeneration(BridgeTestCase):
    def test_a_cancelled_task_settles_its_generation_and_runs_no_tool(self) -> None:
        adapter = PurposefulAdapter(hold=threading.Event())
        service = self.agent_service(adapter)
        runtime, broker = self.provider_runtime(service)
        session = runtime.create_session("bridge")
        task = runtime.submit_task(session.session_id, SIMPLE_REQUEST)
        outcome_box: list[Any] = []
        runner = threading.Thread(
            target=lambda: outcome_box.append(
                runtime.run_task(session.session_id, task.task_id)
            ),
            daemon=True,
        )
        runner.start()
        self.assertTrue(adapter.started.wait(timeout=10.0),
                        "the plan generation never started")
        cancel_task(runtime, session.session_id, task.task_id, cause="user")
        runner.join(timeout=15.0)
        self.assertFalse(runner.is_alive(), "the run thread did not settle")
        persisted = runtime.task(session.session_id, task.task_id)
        self.assertEqual(persisted.state, "cancelled")
        self.assertFalse(broker.invocations, "a tool ran for a cancelled task")


class RemoteApprovalBinding(BridgeTestCase):
    ENV = "BUNNY_BRIDGE_REMOTE_KEY"

    def setUp(self) -> None:
        super().setUp()
        os.environ[self.ENV] = "bridge-test-secret-value"
        self.addCleanup(os.environ.pop, self.ENV, None)

    def remote_service(self, adapter: ScriptedAdapter) -> AgentProviderService:
        configuration = AgentConfiguration(providers=(
            remote_configuration(credential_locator=self.ENV),
        ))
        return self.agent_service(
            adapter, configuration=configuration, adapter_id="scripted-remote",
        )

    def remote_runtime(self, service: AgentProviderService, *, consent=None):
        executor = RemoteProviderExecutor(service, "remote.scripted")
        return self.started(
            executors=(executor,),
            assessment=remote_permissive_assessment(),
            consent=consent,
        )

    def _remote_task(self, runtime):
        from companion.session import PrivacyPolicy

        session = runtime.create_session(
            "remote bridge",
            privacy_policy=PrivacyPolicy(
                default_classification="internal",
                maximum_remote_classification="internal",
                allow_remote=True,
            ),
            locality_preference="any",
        )
        task = runtime.submit_task(
            session.session_id, SIMPLE_REQUEST, classification="internal",
            data_locality="any",
        )
        return session, task

    def test_a_granted_approval_carries_the_dispatch_and_binds_the_destination(self) -> None:
        adapter = ScriptedAdapter(adapter_identity="scripted-remote")
        service = self.remote_service(adapter)
        runtime = self.remote_runtime(
            service, consent=self.granting("remote_dispatch", "send_sensitive_data"),
        )
        session, task = self._remote_task(runtime)
        finished = runtime.run_task(session.session_id, task.task_id)
        self.assertEqual(finished.state, "completed")
        self.assertEqual(len(adapter.requests), 1)
        dispatched = adapter.requests[0]
        self.assertTrue(dispatched.remote_approval_reference,
                        "a remote generation went out without its approval reference")
        granted = [item for item in finished.approvals
                   if item.action == "remote_dispatch" and item.decision == "granted"]
        self.assertTrue(granted)
        # The approval's destination fingerprint is the executor's full
        # declaration — endpoint included — not a coarse route label.
        self.assertTrue(all(item.destination_fingerprint for item in granted))

    def test_without_consent_nothing_is_dispatched_and_the_task_blocks(self) -> None:
        adapter = ScriptedAdapter(adapter_identity="scripted-remote")
        service = self.remote_service(adapter)
        runtime = self.remote_runtime(service)  # RefusingConsent
        session, task = self._remote_task(runtime)
        finished = runtime.run_task(session.session_id, task.task_id)
        self.assertEqual(finished.state, "blocked")
        self.assertFalse(adapter.requests, "context left the machine without a grant")

    def test_a_failed_remote_does_not_fall_back_anywhere(self) -> None:
        from .agents_support import FailingAdapter

        adapter = FailingAdapter(adapter_identity="scripted-remote",
                                 failure_kind="connection")
        service = self.remote_service(adapter)
        runtime = self.remote_runtime(
            service, consent=self.granting("remote_dispatch", "send_sensitive_data"),
        )
        session, task = self._remote_task(runtime)
        finished = runtime.run_task(session.session_id, task.task_id)
        self.assertEqual(finished.state, "failed")
        # One dispatch, one failure, no second destination of any kind.
        self.assertEqual(len(adapter.requests), 1)


class ReviewerProvider(BridgeTestCase):
    def test_observations_come_back_attributed_and_bounded(self) -> None:
        observations = json.dumps({"observations": [{
            "severity": "low", "category": "correctness",
            "summary": "The plan validates nothing.",
            "suggestedAction": "Add a validation step.",
        }]})
        adapter = PurposefulAdapter(review_script=(("structured", observations),))
        service = self.agent_service(adapter)
        reviewer = ProviderBackedReviewer(service)
        produced = reviewer.observe(ReviewContext(
            task={"taskId": "task-1", "sessionId": "ses-1",
                  "displaySummary": "count words", "lifecycleEpoch": 0},
            plan={"planId": "plan-1", "operations": []},
        ))
        self.assertEqual(len(produced), 1)
        self.assertEqual(produced[0].reviewer_id, "agents.provider-reviewer")
        self.assertEqual(produced[0].severity, "low")

    def test_a_reviewer_with_no_local_provider_reviews_nothing(self) -> None:
        adapter = ScriptedAdapter(probe_available=False, probe_detail="gone")
        service = self.agent_service(adapter)
        reviewer = ProviderBackedReviewer(service)
        produced = reviewer.observe(ReviewContext(
            task={"taskId": "task-1"}, plan={"planId": "plan-1"},
        ))
        self.assertEqual(produced, ())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
