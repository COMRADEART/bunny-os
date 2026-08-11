# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from companion.events import EventValidationError, generated_event, observed_event
from companion.model import CompanionPhase, CompanionState, TaskSession, utc_now
from companion.state import ALLOWED_TRANSITIONS, CompanionStateController, InvalidStateTransition
from companion.store import CompanionStore, DuplicateEventError, OutOfOrderEventError


def task() -> TaskSession:
    return TaskSession(
        task_id="task-state",
        session_id="session-state",
        user_request="A harmless local task",
        display_summary="A harmless local task",
    )


def state(phase: CompanionPhase) -> CompanionState:
    return CompanionState(
        session_id="session-state",
        task_id="task-state",
        state=phase,
        state_revision=0,
        started_at=utc_now(),
        status_text=f"State is {phase.value}.",
    )


class CompanionStateTests(unittest.TestCase):
    def test_every_required_state_exists(self) -> None:
        self.assertEqual(
            {item.value for item in CompanionPhase},
            {
                "unavailable", "starting", "idle", "greeting", "listening", "transcribing",
                "understanding", "waiting_for_user", "waiting_for_approval", "planning", "working",
                "reviewing", "speaking", "presenting_result", "success", "warning", "blocked",
                "degraded", "error", "paused", "cancelled", "disconnected", "sleeping",
            },
        )

    def test_every_declared_transition_is_accepted(self) -> None:
        for source, targets in ALLOWED_TRANSITIONS.items():
            for target in targets:
                with self.subTest(source=source.value, target=target.value):
                    controller = CompanionStateController(state(source))
                    projected = controller.transition(target, status_text="Observed transition.")
                    self.assertEqual(projected.state, target)
                    self.assertEqual(projected.state_revision, 1)

    def test_invalid_transition_from_every_state_is_rejected(self) -> None:
        phases = set(CompanionPhase)
        for source, targets in ALLOWED_TRANSITIONS.items():
            invalid = next(item for item in phases if item != source and item not in targets)
            with self.subTest(source=source.value, invalid=invalid.value):
                controller = CompanionStateController(state(source))
                with self.assertRaises(InvalidStateTransition):
                    controller.transition(invalid, status_text="This must be refused.")

    def test_self_transition_is_a_revision_update(self) -> None:
        controller = CompanionStateController(state(CompanionPhase.WORKING))
        projected = controller.transition(CompanionPhase.WORKING, status_text="Tool progress changed.")
        self.assertEqual(projected.state_revision, 1)


class EventStreamTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.store = CompanionStore(Path(self.directory.name) / "events.sqlite3")
        self.task = task()
        self.store.save_task(self.task)

    def tearDown(self) -> None:
        self.store.close()
        self.directory.cleanup()

    def event(self, **changes):
        values = {
            "session_id": self.task.session_id,
            "task_id": self.task.task_id,
            "event_type": "task_created",
            "source": "companion.runtime",
            "payload": {"status": "created"},
        }
        values.update(changes)
        return observed_event(**values)

    def test_order_and_replay(self) -> None:
        first = self.store.append(self.event()).event
        second = self.store.append(self.event(event_type="task_classified")).event
        self.assertEqual((first.sequence, second.sequence), (1, 2))
        self.assertEqual([item.event_id for item in self.store.replay(self.task.task_id)], [first.event_id, second.event_id])
        self.assertEqual([item.event_id for item in self.store.replay(self.task.task_id, after_sequence=1)], [second.event_id])

    def test_identical_replayed_event_is_deduplicated(self) -> None:
        event = self.event()
        first = self.store.append(event)
        replay = self.store.append(event)
        self.assertTrue(first.appended)
        self.assertFalse(replay.appended)
        self.assertEqual(self.store.event_count(self.task.task_id), 1)

    def test_replayed_id_with_different_content_is_rejected(self) -> None:
        event = self.event()
        self.store.append(event)
        changed = observed_event(
            session_id=event.session_id,
            task_id=event.task_id,
            event_type="task_created",
            source=event.source,
            payload={"status": "different"},
            event_id=event.event_id,
            occurred_at=event.occurred_at,
        )
        with self.assertRaises(DuplicateEventError):
            self.store.append(changed)

    def test_out_of_order_event_is_rejected(self) -> None:
        with self.assertRaises(OutOfOrderEventError):
            self.store.append(self.event(sequence=9))

    def test_sensitive_fields_and_text_are_redacted(self) -> None:
        event = self.event(payload={"apiKey": "top-secret", "detail": "password=hunter2"})
        stored = self.store.append(event).event
        self.assertEqual(stored.payload["apiKey"], "[REDACTED]")
        self.assertNotIn("hunter2", str(stored.payload))

    def test_generated_description_must_cite_observed_events(self) -> None:
        with self.assertRaises(EventValidationError):
            generated_event(
                session_id=self.task.session_id,
                task_id=self.task.task_id,
                event_type="response_drafting",
                source="companion.runtime",
                description="A generated summary.",
                evidence_references=(),
            )

    def test_task_recovery_round_trip(self) -> None:
        self.store.append(self.event())
        restored = self.store.load_task(self.task.task_id)
        self.assertIsNotNone(restored)
        self.assertEqual(restored.to_json(), self.task.to_json())


if __name__ == "__main__":
    unittest.main()
