# SPDX-License-Identifier: GPL-3.0-or-later
"""The state machine's transition law and the durable event chain beneath it.

The projection half (``CompanionStateTests``) is pure and travels unchanged
from the prototype that wrote it. The stream half speaks this build's store:
appends are refused unless they continue the chain under the session lock, so
the defences live in different places than the prototype put them — an
out-of-order or replayed record dies at :meth:`CompanionStore.append` on its
sequence and hash, while a reused *identifier* survives the append and is
refused when the chain is next verified. Both places are pinned here, because
a repair that moves one without noticing the other reads as a regression.
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from companion.errors import IntegrityError
from companion.events import EventValidationError, generated_event, observed_event
from companion.model import CompanionPhase, CompanionState, utc_now
from companion.state import ALLOWED_TRANSITIONS, CompanionStateController, InvalidStateTransition
from companion.store import CompanionStore
from companion.task import CompanionTask


def task() -> CompanionTask:
    return CompanionTask(
        task_id="task-state",
        session_id="session-state",
        original_request="A harmless local task",
        display_summary="A harmless local task",
        created_at=utc_now(),
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
        self.store = CompanionStore(Path(self.directory.name) / "store")
        self.task = task()
        self.store.save_task(self.task)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def append(self, event_type: str, payload: dict | None = None, **changes):
        """Build the next record against the current tip and append it."""
        sequence, tip_hash = self.store.tip(self.task.session_id)
        values = {
            "session_id": self.task.session_id,
            "task_id": self.task.task_id,
            "event_type": event_type,
            "source": "test.runtime",
            "payload": payload,
            "sequence": sequence + 1,
            "previous_hash": tip_hash,
        }
        values.update(changes)
        event = observed_event(**values)
        self.store.append(event)
        return event

    def test_order_and_replay(self) -> None:
        first = self.append("task_created", {"summary": "A harmless local task"})
        second = self.append(
            "task_classified",
            {"taskType": "local_test", "classification": "internal", "requiredCapabilities": []},
        )
        self.assertEqual((first.sequence, second.sequence), (1, 2))
        replayed = self.store.read_events(self.task.session_id, task_id=self.task.task_id)
        self.assertEqual([item.event_id for item in replayed], [first.event_id, second.event_id])
        self.assertEqual([item.event_id for item in replayed[1:]], [second.event_id])

    def test_replayed_record_is_refused_at_append(self) -> None:
        event = self.append("task_created", {"summary": "A harmless local task"})
        with self.assertRaises(IntegrityError):
            self.store.append(event)
        self.assertEqual(len(self.store.read_events(self.task.session_id)), 1)

    def test_replayed_identifier_with_different_content_is_refused_on_read(self) -> None:
        # The append path checks that a record continues the chain — sequence
        # and hash alone. Identifier uniqueness is enforced when the stream is
        # verified, which is what makes a forged-but-well-chained record fail
        # loudly instead of sitting quietly in the file.
        first = self.append("task_created", {"summary": "A harmless local task"})
        _, tip_hash = self.store.tip(self.task.session_id)
        forged = observed_event(
            session_id=self.task.session_id,
            task_id=self.task.task_id,
            event_type="task_classified",
            source="test.runtime",
            payload={"taskType": "other", "classification": "internal", "requiredCapabilities": []},
            event_id=first.event_id,
            sequence=first.sequence + 1,
            previous_hash=tip_hash,
        )
        self.store.append(forged)
        with self.assertRaises(IntegrityError):
            self.store.read_events(self.task.session_id)

    def test_out_of_order_event_is_rejected(self) -> None:
        with self.assertRaises(IntegrityError):
            self.append("task_created", {"summary": "A harmless local task"}, sequence=9)

    def test_sensitive_fields_and_text_are_redacted(self) -> None:
        stored = self.append(
            "task_created",
            {"summary": "check password=hunter2", "apiKey": "top-secret"},
        )
        encoded = str(stored.to_json())
        self.assertNotIn("top-secret", encoded)
        self.assertNotIn("hunter2", encoded)
        self.assertNotIn("apiKey", stored.payload)
        # The removal is recorded, not silent: the record says what it refused.
        self.assertTrue(stored.redactions)

    def test_generated_description_must_cite_observed_events(self) -> None:
        with self.assertRaises(EventValidationError):
            generated_event(
                session_id=self.task.session_id,
                task_id=self.task.task_id,
                event_type="response_drafting",
                source="test.runtime",
                description="A generated summary.",
                evidence_references=(),
            )

    def test_task_recovery_round_trip(self) -> None:
        self.append("task_created", {"summary": "A harmless local task"})
        restored = self.store.load_task(self.task.session_id, self.task.task_id)
        self.assertIsNotNone(restored)
        self.assertEqual(restored.to_json(), self.task.to_json())


if __name__ == "__main__":
    unittest.main()
