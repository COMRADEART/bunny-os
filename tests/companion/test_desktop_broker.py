# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""§10, §11, §12, §16, §17, §20 and §15: what the broker does once it acts.

The security file next door is about refusals. This one is about the behaviour
that has to be right when nothing is being attacked — which is where the
distinctions §12 draws either survive or quietly collapse into "it worked".

Four properties get the most attention here, because each of them is easy to
lose and hard to notice losing:

* an acknowledgement never becomes a confirmation;
* an undo is a new action, and is not offered for a state nobody read;
* a cancellation records what it actually prevented;
* a restart leaves completed actions completed and unsettled ones unknown.

The last group exercises the whole route — a real
:class:`companion.runtime.CompanionRuntime`, a real approval gate, a real plan —
so that "the ToolBroker is the only gateway" is a run rather than a diagram.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from companion.clock import FrozenClock
from companion.desktop.ledger import LedgerEntry, OperationLedger
from companion.desktop.result import Observation
from companion.desktop.undo import undo_plan_for

from .desktop_support import FakeAdapters, build_broker, make_paths, sample_parameters


def _prepare(broker, action_id, parameters=None, *, path_context=None, operation_id="op-1"):
    return broker.prepare(
        action_id,
        parameters if parameters is not None else sample_parameters(action_id),
        request_id=f"dreq-{operation_id}",
        session_id="session-1",
        task_id="task-1",
        lifecycle_epoch=0,
        plan_id="plan-1",
        operation_id=operation_id,
        cancellation_token=f"cancel-{operation_id}",
        path_context=path_context,
    )


def _run(broker, prepared, **kwargs):
    return broker.execute(
        prepared.request.with_approval("approval-1"),
        approved_binding=prepared.binding,
        **kwargs,
    )


class Dispatch(unittest.TestCase):
    def setUp(self) -> None:
        self.broker, self.adapters = build_broker()
        self.addCleanup(self.broker.stop)

    def test_a_notification_is_accepted_and_not_confirmed(self) -> None:
        result = _run(self.broker, _prepare(self.broker, "desktop.notification.show"))
        self.assertEqual(result.state, "accepted-not-confirmed")
        self.assertEqual(result.confidence, "reported")
        self.assertEqual(result.observation.kind, "acknowledgement")
        self.assertFalse(result.undo_available)

    def test_a_volume_change_is_confirmed_by_read_back(self) -> None:
        result = _run(self.broker, _prepare(self.broker, "desktop.audio.set-volume"))
        self.assertEqual(result.state, "confirmed")
        self.assertEqual(result.confidence, "verified")
        self.assertEqual(result.observation.kind, "read-back")
        self.assertIs(result.observation.matched, True)
        self.assertEqual(result.previous_state["percent"], 35)
        self.assertTrue(result.undo_available)

    def test_a_clipboard_write_is_confirmed_by_ownership(self) -> None:
        result = _run(self.broker, _prepare(self.broker, "desktop.clipboard.copy-text"))
        self.assertEqual(result.state, "confirmed")
        self.assertEqual(result.observation.kind, "ownership")
        self.assertEqual(self.adapters.clipboard.outstanding, 1)
        self.adapters.clipboard.release_all("test cleanup")

    def test_a_uri_is_opened_through_the_parsed_form(self) -> None:
        result = _run(self.broker, _prepare(self.broker, "desktop.uri.open"))
        self.assertEqual(result.state, "accepted-not-confirmed")
        self.assertEqual(self.adapters.state["opened"], ["https://example.com/docs"])

    def test_a_reveal_uses_the_resolved_real_path(self) -> None:
        context, base = make_paths("report.pdf")
        prepared = _prepare(self.broker, "desktop.file.reveal", path_context=context)
        result = _run(self.broker, prepared, path_context=context)
        self.assertEqual(result.state, "accepted-not-confirmed")
        revealed = self.adapters.state["revealed"]
        self.assertEqual(len(revealed), 1)
        self.assertTrue(revealed[0].endswith("report.pdf"))

    def test_an_application_that_cannot_be_raised_reports_unsupported(self) -> None:
        from companion.desktop import broker as module

        entry = _fake_entry(dbus_activatable=False)
        original = module.__dict__.get("resolve_application")
        prepared = _prepare(self.broker, "desktop.application.present")
        with _patched_entry(entry):
            result = _run(self.broker, prepared)
        self.assertEqual(result.state, "unsupported")
        self.assertIn("DBusActivatable", result.explanation)
        self.assertIsNone(original)

    def test_a_backend_failure_is_a_failure_and_not_an_unknown(self) -> None:
        self.adapters.state["sink"] = "some-other-sink"
        prepared = _prepare(self.broker, "desktop.audio.set-volume")
        # The sink named in the approval vanished between preparation and act.
        self.adapters.state["sink"] = "gone"
        result = _run(self.broker, prepared)
        self.assertEqual(result.state, "failed")
        self.assertIn("no longer present", result.explanation)


class Cancellation(unittest.TestCase):
    """§10's points, each with what the record is allowed to claim."""

    def setUp(self) -> None:
        self.broker, self.adapters = build_broker()
        self.addCleanup(self.broker.stop)

    def test_a_cancel_before_approval_leaves_no_ledger_entry(self) -> None:
        prepared = _prepare(self.broker, "desktop.settings.open")
        result = self.broker.execute(
            prepared.request, approved_binding=prepared.binding, cancelled=lambda: True,
        )
        self.assertEqual(result.state, "cancelled")
        self.assertIs(result.effect_prevented, True)
        self.assertEqual(self.broker.ledger.entries, {})

    def test_a_cancel_after_approval_before_execution_prevents_the_effect(self) -> None:
        prepared = _prepare(self.broker, "desktop.settings.open")
        result = _run(self.broker, prepared, cancelled=lambda: True)
        self.assertEqual(result.state, "cancelled")
        self.assertIs(result.effect_prevented, True)
        self.assertEqual(self.adapters.called("settings.open_page"), ())

    def test_a_cancellation_that_could_not_prevent_the_effect_records_unknown(self) -> None:
        """The distinction §10 exists for, driven through the ledger.

        A cancellation whose ``effect_prevented`` is false leaves the same
        uncertainty a crash does — so the ledger records ``unknown``, not
        ``cancelled``, and the action is not repeatable.
        """
        from companion.desktop.errors import DesktopCancelled

        prepared = _prepare(self.broker, "desktop.uri.open")

        def refuse(*_args, **_kwargs):
            raise DesktopCancelled(
                "the portal call was aborted in flight",
                effect_known=False, effect_prevented=False,
            )

        self.adapters.uri.open = refuse  # type: ignore[assignment]
        result = _run(self.broker, prepared)
        self.assertEqual(result.state, "cancelled")
        self.assertIs(result.effect_prevented, False)
        entry = self.broker.ledger.get(prepared.request.idempotency_key)
        self.assertEqual(entry.state, "unknown")
        self.assertFalse(entry.repeatable)

    def test_cancelling_by_request_id_releases_what_is_held(self) -> None:
        prepared = _prepare(self.broker, "desktop.clipboard.copy-text")
        _run(self.broker, prepared)
        self.assertEqual(self.adapters.clipboard.outstanding, 1)
        # The attempt has settled, so there is nothing in flight to cancel —
        # and the answer says so rather than claiming to have stopped something.
        outcome = self.broker.cancel(request_id=prepared.request.request_id)
        self.assertFalse(outcome["cancelled"])
        self.assertIn("no attempt", outcome["reason"])
        self.adapters.clipboard.release_all("test cleanup")

    def test_stopping_the_broker_releases_every_resource(self) -> None:
        broker, adapters = build_broker()
        _run(broker, _prepare(broker, "desktop.clipboard.copy-text"))
        self.assertEqual(adapters.clipboard.outstanding, 1)
        released = broker.stop()
        self.assertEqual(released["clipboardOwners"], 1)
        self.assertEqual(adapters.clipboard.outstanding, 0)


class Undo(unittest.TestCase):
    """§11: a new action, and never a promise the desktop cannot keep."""

    def setUp(self) -> None:
        self.broker, self.adapters = build_broker()
        self.addCleanup(self.broker.stop)

    def test_a_volume_change_offers_a_reversal_to_the_observed_value(self) -> None:
        prepared = _prepare(self.broker, "desktop.audio.set-volume")
        _run(self.broker, prepared)
        plan = self.broker.undo_plan(prepared.request.idempotency_key)
        self.assertEqual(plan.kind, "reverse")
        self.assertEqual(plan.action_id, "desktop.audio.set-volume")
        self.assertEqual(plan.parameters["percent"], 35)
        self.assertTrue(plan.requires_approval)
        self.assertEqual(plan.presentation, "Set the volume back to 35%")

    def test_an_undo_is_a_separate_entry_and_the_original_becomes_undone(self) -> None:
        first = _prepare(self.broker, "desktop.audio.set-volume", operation_id="op-1")
        _run(self.broker, first)
        plan = self.broker.undo_plan(first.request.idempotency_key)
        second = _prepare(
            self.broker, "desktop.audio.set-volume", dict(plan.parameters), operation_id="op-2",
        )
        _run(self.broker, second)
        self.broker.link_undo(
            original_key=first.request.idempotency_key,
            undo_key=second.request.idempotency_key,
        )
        original = self.broker.ledger.get(first.request.idempotency_key)
        undo = self.broker.ledger.get(second.request.idempotency_key)
        self.assertEqual(original.state, "undone")
        self.assertEqual(original.undone_by, second.request.idempotency_key)
        self.assertEqual(undo.undo_of, first.request.idempotency_key)
        self.assertEqual(self.adapters.state["percent"], 35)

    def test_no_undo_is_offered_when_the_previous_value_was_not_read(self) -> None:
        adapters = FakeAdapters(dnd=True, dndValue=False)
        broker, _ = build_broker(adapters=adapters)
        self.addCleanup(broker.stop)
        prepared = _prepare(broker, "desktop.notifications.set-do-not-disturb")
        # The read goes away between preparation and execution.
        adapters.state["dnd"] = True
        entry = LedgerEntry(
            key="k", action_id="desktop.notifications.set-do-not-disturb",
            task_id="t", session_id="s", lifecycle_epoch=0, plan_id="p",
            operation_id="o", state="completed", binding_digest="d",
        )
        plan = undo_plan_for(entry)
        self.assertEqual(plan.kind, "none")
        self.assertIn("not readable", plan.reason)

    def test_launching_an_application_is_never_undone_by_killing_it(self) -> None:
        entry = LedgerEntry(
            key="k", action_id="desktop.application.launch", task_id="t", session_id="s",
            lifecycle_epoch=0, plan_id="p", operation_id="o", state="completed",
            binding_digest="d",
        )
        plan = undo_plan_for(entry)
        self.assertEqual(plan.kind, "none")
        self.assertIn("stays started", plan.reason)
        self.assertIn("discard work", plan.reason)

    def test_a_clipboard_write_compensates_without_claiming_restoration(self) -> None:
        prepared = _prepare(self.broker, "desktop.clipboard.copy-text")
        _run(self.broker, prepared)
        plan = self.broker.undo_plan(prepared.request.idempotency_key)
        self.assertEqual(plan.kind, "compensate")
        self.assertFalse(plan.requires_approval)
        self.assertIn("does not restore", plan.reason)
        outcome = self.broker.compensate(prepared.request.idempotency_key)
        self.assertTrue(outcome["compensated"])
        self.assertEqual(self.adapters.clipboard.outstanding, 0)

    def test_a_clear_after_policy_releases_the_selection_and_leaves_no_thread(self) -> None:
        """§4.7's clear-after, which has to be a timer rather than a note.

        The parameter reaches the approval prompt, where a person reads
        "released again after N seconds" and decides on that basis. A schema
        that is closed so nothing can appear to take effect and not, and then
        carries a parameter that does not, has closed the wrong thing.
        """
        import threading
        import time as _time

        before = threading.active_count()
        prepared = _prepare(
            self.broker, "desktop.clipboard.copy-text",
            {"text": "briefly on the clipboard", "clearAfterSeconds": 1},
        )
        self.assertIn("released again after 1 seconds", prepared.request.presentation)
        result = _run(self.broker, prepared)
        self.assertEqual(result.state, "confirmed")
        self.assertEqual(self.adapters.clipboard.outstanding, 1)
        self.assertEqual(
            self.adapters.called("clipboard.copy")[0]["clearAfterSeconds"], 1.0
        )

        deadline = _time.monotonic() + 10.0
        while _time.monotonic() < deadline and self.adapters.clipboard.outstanding:
            _time.sleep(0.05)
        self.assertEqual(
            self.adapters.clipboard.outstanding, 0,
            "the clear-after policy did not release the selection",
        )
        # And the timer thread is gone, which is what §23's thread counter
        # would otherwise catch a hundred iterations later.
        deadline = _time.monotonic() + 5.0
        while _time.monotonic() < deadline and threading.active_count() > before:
            _time.sleep(0.05)
        self.assertLessEqual(threading.active_count(), before)

    def test_releasing_early_cancels_the_clear_after_timer(self) -> None:
        import threading

        before = threading.active_count()
        prepared = _prepare(
            self.broker, "desktop.clipboard.copy-text",
            {"text": "held briefly", "clearAfterSeconds": 3600},
        )
        _run(self.broker, prepared)
        self.assertEqual(threading.active_count(), before + 1, "no timer was started")
        self.broker.compensate(prepared.request.idempotency_key)
        self.assertEqual(self.adapters.clipboard.outstanding, 0)
        # `Timer.cancel` wakes the thread; the thread then has to be scheduled
        # before it leaves the count. Bounded, because the point is that it goes
        # *soon*, not that it goes synchronously — an hour-long timer that
        # survived would still be there at the end of this loop.
        import time as _time

        deadline = _time.monotonic() + 5.0
        while _time.monotonic() < deadline and threading.active_count() > before:
            _time.sleep(0.02)
        self.assertEqual(
            threading.active_count(), before,
            "an hour-long timer outlived the selection it was for",
        )

    def test_an_uncertain_action_is_not_undone(self) -> None:
        entry = LedgerEntry(
            key="k", action_id="desktop.audio.set-volume", task_id="t", session_id="s",
            lifecycle_epoch=0, plan_id="p", operation_id="o", state="unknown",
            binding_digest="d", previous_state={"percent": 20},
        )
        plan = undo_plan_for(entry)
        self.assertEqual(plan.kind, "none")
        self.assertIn("new decision", plan.reason)


class Recovery(unittest.TestCase):
    """§20: what a restarted runtime may conclude, and what it may not."""

    def setUp(self) -> None:
        self.path = Path(tempfile.mkdtemp()) / "ledger.json"

    def test_a_completed_action_survives_a_restart_as_completed(self) -> None:
        broker, adapters = build_broker(ledger_path=self.path)
        prepared = _prepare(broker, "desktop.settings.open")
        _run(broker, prepared)
        broker.stop()

        reopened = OperationLedger.load(self.path)
        entry = reopened.get(prepared.request.idempotency_key)
        self.assertEqual(entry.state, "completed")
        self.assertFalse(entry.repeatable)
        self.assertFalse(reopened.warnings)

    def test_an_unsettled_attempt_becomes_unknown_with_a_note(self) -> None:
        ledger = OperationLedger(path=self.path)
        ledger.begin(LedgerEntry(
            key="dact-1", action_id="desktop.uri.open", task_id="t", session_id="s",
            lifecycle_epoch=0, plan_id="p", operation_id="o", state="started",
            binding_digest="d", started_at="2026-01-01T00:00:00Z",
        ))
        reopened = OperationLedger.load(self.path)
        entry = reopened.get("dact-1")
        self.assertEqual(entry.state, "unknown")
        self.assertIn("not repeated", entry.recovery_note)
        self.assertTrue(reopened.warnings)

    def test_an_unknown_stays_unknown_across_a_second_restart(self) -> None:
        ledger = OperationLedger(path=self.path)
        ledger.begin(LedgerEntry(
            key="dact-1", action_id="desktop.uri.open", task_id="t", session_id="s",
            lifecycle_epoch=0, plan_id="p", operation_id="o", state="started",
            binding_digest="d",
        ))
        once = OperationLedger.load(self.path)
        once.save()
        twice = OperationLedger.load(self.path)
        self.assertEqual(twice.get("dact-1").state, "unknown")

    def test_a_restarted_broker_does_not_repeat_an_unknown(self) -> None:
        ledger = OperationLedger(path=self.path)
        broker, adapters = build_broker(ledger_path=self.path)
        prepared = _prepare(broker, "desktop.uri.open")
        ledger.begin(LedgerEntry(
            key=prepared.request.idempotency_key, action_id="desktop.uri.open",
            task_id="task-1", session_id="session-1", lifecycle_epoch=0, plan_id="plan-1",
            operation_id="op-1", state="started", binding_digest=prepared.binding.digest,
        ))
        broker.stop()

        restarted, restarted_adapters = build_broker(ledger_path=self.path)
        self.addCleanup(restarted.stop)
        self.assertTrue(restarted.recovery_warnings)
        again = _prepare(restarted, "desktop.uri.open")
        result = _run(restarted, again)
        self.assertEqual(result.state, "unknown")
        self.assertEqual(restarted_adapters.state["opened"], [])

    def test_the_status_surface_names_what_still_needs_a_decision(self) -> None:
        ledger = OperationLedger(path=self.path)
        ledger.begin(LedgerEntry(
            key="dact-1", action_id="desktop.uri.open", task_id="task-1", session_id="s",
            lifecycle_epoch=0, plan_id="p", operation_id="o", state="started",
            binding_digest="d",
        ))
        broker, _ = build_broker(ledger_path=self.path)
        self.addCleanup(broker.stop)
        status = broker.status()
        self.assertEqual(len(status["pendingDecisions"]), 1)
        self.assertIn("not known", status["pendingDecisions"][0]["explanation"])


class Environment(unittest.TestCase):
    """§16: availability from the services, and the four postures."""

    def test_everything_available_is_the_top_posture(self) -> None:
        broker, _ = build_broker()
        self.addCleanup(broker.stop)
        report = broker.environment(refresh=True)
        self.assertEqual(report.posture, "desktop-actions-available")
        self.assertEqual(len(report.available_actions), 9)

    def test_a_missing_service_produces_limited_actions_with_a_reason(self) -> None:
        broker, _ = build_broker(adapters=FakeAdapters(audio=False, dnd=False))
        self.addCleanup(broker.stop)
        report = broker.environment(refresh=True)
        self.assertEqual(report.posture, "limited-desktop-actions")
        self.assertIn("desktop.audio.set-volume", report.unavailable_actions)
        self.assertNotIn("desktop.audio.set-volume", report.available_actions)

    def test_a_headless_machine_with_a_notifier_is_notification_only(self) -> None:
        import os

        previous = {
            name: os.environ.get(name) for name in ("WAYLAND_DISPLAY", "DISPLAY")
        }

        def restore() -> None:
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value

        self.addCleanup(restore)
        broker, _ = build_broker(
            adapters=FakeAdapters(audio=False), graphical=False,
        )
        self.addCleanup(broker.stop)
        report = broker.environment(refresh=True)
        self.assertEqual(report.posture, "notification-only")
        self.assertEqual(report.available_actions, ("desktop.notification.show",))

    def test_a_probe_that_raises_is_reported_unavailable_rather_than_crashing(self) -> None:
        adapters = FakeAdapters()

        def explode() -> None:
            raise RuntimeError("the bus went away")

        adapters.notification.probe = explode  # type: ignore[assignment]
        broker, _ = build_broker(adapters=adapters)
        self.addCleanup(broker.stop)
        report = broker.environment(refresh=True)
        self.assertNotIn("desktop.notification.show", report.available_actions)
        self.assertIn("the probe failed", report.unavailable_actions["desktop.notification.show"])


class RuntimeIntegration(unittest.TestCase):
    """§15: the whole route, through a real runtime and a real approval gate."""

    def _runtime(self, *, grant: bool):
        from companion.approvals import CompanionApprovalStore, ScriptedConsent
        from companion.capability_bridge import Assessment  # noqa: F401 - re-exported check
        from companion.desktop_bridge import DesktopSupport, register_desktop_tools
        from companion.ids import SequentialIds
        from companion.runtime import CompanionRuntime, RuntimeOptions
        from companion.store import CompanionStore
        from companion.tools import ToolBroker

        from .support import machine

        root = Path(tempfile.mkdtemp())
        adapters = FakeAdapters()
        support = DesktopSupport.create(adapters=adapters, ledger_path=root / "ledger.json")
        support.start()
        self.addCleanup(support.stop)
        broker = ToolBroker()
        register_desktop_tools(broker, support)
        classes = sorted({
            item.approval_class for item in __import__(
                "companion.desktop.catalogue", fromlist=["DESCRIPTORS"],
            ).DESCRIPTORS.values()
        })
        runtime = CompanionRuntime(RuntimeOptions(
            store=CompanionStore(root / "store"),
            assessment=machine(),
            executors=(_SliceExecutor(),),
            reviewers=(),
            broker=broker,
            approvals=CompanionApprovalStore(),
            consent=ScriptedConsent(granted_actions=tuple(classes) if grant else ()),
            clock=FrozenClock(),
            ids=SequentialIds(),
            desktop=support,
        ))
        runtime.start()
        self.addCleanup(runtime.stop)
        return runtime, support, adapters

    def test_an_approved_desktop_action_runs_once_and_is_recorded(self) -> None:
        runtime, support, adapters = self._runtime(grant=True)
        session = runtime.create_session("Desktop")
        task = runtime.submit_task(session.session_id, "please [settings] for me")
        final = runtime.run_task(session.session_id, task.task_id)
        self.assertEqual(final.state, "completed")
        self.assertEqual(len(adapters.called("settings.open_page")), 1)
        self.assertEqual(len(support.broker.ledger.entries), 1)

    def test_a_refused_approval_leaves_the_desktop_untouched(self) -> None:
        runtime, support, adapters = self._runtime(grant=False)
        session = runtime.create_session("Desktop")
        task = runtime.submit_task(session.session_id, "please [settings] for me")
        final = runtime.run_task(session.session_id, task.task_id)
        self.assertEqual(final.state, "blocked")
        self.assertEqual(adapters.called("settings.open_page"), ())
        self.assertEqual(support.broker.ledger.entries, {})

    def test_the_approval_question_carries_the_exact_sentence(self) -> None:
        runtime, support, adapters = self._runtime(grant=True)
        session = runtime.create_session("Desktop")
        task = runtime.submit_task(session.session_id, "please [settings] for me")
        runtime.run_task(session.session_id, task.task_id)
        requested = [
            item for item in runtime.events(session.session_id, task_id=task.task_id)
            if item.event_type == "approval_requested" and item.payload.get("requirement")
        ]
        self.assertTrue(requested)
        requirement = requested[0].payload["requirement"]
        self.assertEqual(requirement["action"], "open_settings_surface")
        self.assertIn("Open the sound settings page", requirement["reason"])
        self.assertEqual(requirement["destination"], "sound")

    def test_a_desktop_action_is_never_presented_as_leaving_the_device(self) -> None:
        """§18: the coarse locality a surface renders must say "here".

        The requirement's ``destination`` is the exact target — an application
        id, an address, a path — and the request's is the two-word locality the
        Approval Centre shows. Inferring the second from the first put the word
        "remote" in front of a user for opening their own sound settings.
        """
        runtime, support, adapters = self._runtime(grant=True)
        session = runtime.create_session("Desktop")
        task = runtime.submit_task(session.session_id, "please [settings] for me")
        runtime.run_task(session.session_id, task.task_id)
        asked = [
            item for item in runtime.events(session.session_id, task_id=task.task_id)
            if item.event_type == "approval_requested" and item.payload.get("requirement")
        ]
        self.assertTrue(asked)
        payload = asked[0].payload
        self.assertEqual(payload["requirement"]["destination"], "sound")
        self.assertIs(payload["requirement"]["leavesDevice"], False)
        self.assertEqual(payload["request"]["destination"], "local")

    def test_a_remote_destination_still_reads_as_remote(self) -> None:
        """The other direction, so the fix cannot have loosened the general case."""
        from companion.approvals import ApprovalRequirement

        remote = ApprovalRequirement(
            action="remote_dispatch", reason="somewhere else",
            destination="provider.example", alternatives=("Stay local.",),
        )
        self.assertTrue(remote.leaves_device)
        local = ApprovalRequirement(
            action="interrupt_user_work", reason="here", destination="local",
            alternatives=("Later.",),
        )
        self.assertFalse(local.leaves_device)

    def test_a_provider_naming_an_undeclared_tool_never_reaches_the_desktop(self) -> None:
        runtime, support, adapters = self._runtime(grant=True)
        session = runtime.create_session("Desktop")
        task = runtime.submit_task(session.session_id, "please [hostile] for me")
        runtime.run_task(session.session_id, task.task_id)
        self.assertEqual(support.broker.ledger.entries, {})
        self.assertTrue([
            item for item in runtime.broker.refusals if item["toolId"] == "shell.run"
        ])


class _SliceExecutor:
    """A minimal executor for the integration tests. Proposes; performs nothing."""

    def __init__(self) -> None:
        from companion.executor import ExecutorDeclaration

        self.declaration = ExecutorDeclaration(
            executor_id="local.test-desktop",
            provider_id="local",
            implementation_id="test-1",
            local=True,
            supported_task_types=("unclassified", "question", "local_action"),
            supports_tools=True,
            maximum_privacy_class="secret",
        )

    def health(self):
        from companion.executor import ExecutorHealth

        return ExecutorHealth()

    def plan(self, context):
        from companion.executor import PlannedOperation, TaskPlan

        request = str(context.task.get("originalRequest", ""))
        if "[hostile]" in request:
            operation = PlannedOperation(
                name="hostile", tool="shell.run", arguments={"command": "id"},
            )
        else:
            operation = PlannedOperation(
                name="settings", tool="desktop.settings.open", arguments={"page": "sound"},
            )
        return TaskPlan(
            plan_id="plan-desktop", revision=max(1, context.plan_revision),
            summary="one desktop action", operations=(operation,),
        )

    def result(self, context):
        from companion.executor import ProducedOutput, TaskResult

        return TaskResult(
            result_id="result-1", summary="done",
            outputs=(ProducedOutput(output_id="o-1", content="done", classification="internal"),),
            classification="internal",
        )

    def cancel(self, context, reason):
        return None


# --------------------------------------------------------------------------- #
# Helpers for the present-adapter test
# --------------------------------------------------------------------------- #

def _fake_entry(**overrides):
    from .desktop_support import make_entry

    return make_entry(**overrides)


class _patched_entry:
    """Substitute entry resolution for the duration of one dispatch.

    The broker resolves the application by identifier at execution, which needs
    a real ``.desktop`` file. The *resolution* is tested exhaustively in the
    security file against real files; here the interest is in what the present
    adapter reports for an entry that is not activatable, so the resolution is
    stood in for.
    """

    def __init__(self, entry) -> None:
        self.entry = entry
        self._original = None

    def __enter__(self):
        from companion.desktop import entries as module

        self._original = module.resolve_application
        module.resolve_application = lambda *_a, **_k: self.entry  # type: ignore[assignment]
        return self.entry

    def __exit__(self, *_exc: object) -> None:
        from companion.desktop import entries as module

        module.resolve_application = self._original  # type: ignore[assignment]


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
