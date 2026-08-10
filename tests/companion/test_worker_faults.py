# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""A fault the worker survives must still be findable afterwards.

The single worker thread swallows exceptions on purpose: one task that faults
must not take every later task with it. But *swallowing* an exception and
*destroying* it are separable, and only the first was ever necessary. Losing the
second one cost two phases — a store write failed, the worker caught it as an
ordinary refusal and moved on, and the task sat in ``waiting_for_executor`` with
nothing running, nothing queued and no explanation anywhere.

These tests hold the line at both ends: the worker keeps running, and the fault
is still there to be asked about. The record is structured, because the
questions asked of it are structured, and sanitized, because a fault log is read
by whoever is debugging and that is not necessarily whoever owns the data.
"""

from __future__ import annotations

import threading
import unittest

from companion.errors import CompanionError, StoreError
from companion.service import (
    MAX_FAULT_MESSAGE,
    CompanionService,
    ServiceOptions,
    _sanitise_fault_message,
)

from .support import SIMPLE_REQUEST, CompanionTestCase


class SanitisationTests(unittest.TestCase):
    """What must never reach a fault record."""

    def test_a_windows_user_path_is_replaced(self) -> None:
        message = _sanitise_fault_message(
            OSError(r"C:\Users\someone\AppData\Local\store\task.json could not be written")
        )
        self.assertNotIn("someone", message)
        self.assertIn("<user-path>", message)

    def test_a_posix_home_path_is_replaced(self) -> None:
        message = _sanitise_fault_message(OSError("/home/someone/store/task.json is unreadable"))
        self.assertNotIn("someone", message)
        self.assertIn("<user-path>", message)

    def test_anything_calling_itself_a_secret_loses_its_value(self) -> None:
        for text in (
            "token=9f8e7d6c5b4a39281706",
            "API_KEY: sk-abcdef123456",
            "password foobarbaz",
            "Bearer aaaabbbbccccdddd",
        ):
            with self.subTest(text=text):
                message = _sanitise_fault_message(RuntimeError(text))
                self.assertIn("<redacted>", message)

    def test_a_long_hex_run_is_replaced(self) -> None:
        """A request token and a content digest look the same from here."""
        message = _sanitise_fault_message(RuntimeError("digest 4c4d7757e99c9e6abeedf0fa81b7b7fd bad"))
        self.assertNotIn("4c4d7757", message)
        self.assertIn("<hex>", message)

    def test_a_message_is_bounded(self) -> None:
        message = _sanitise_fault_message(RuntimeError("x" * 5000))
        self.assertLessEqual(len(message), MAX_FAULT_MESSAGE)


class ObservabilityTests(CompanionTestCase):
    """A swallowed fault survives as a record, and the worker survives too."""

    def _service(self) -> CompanionService:
        service = CompanionService(ServiceOptions(
            root=self.root / "service",
            endpoint=self.root / "run" / "runtime.sock",
            machine="laptop",
            consent_wait_seconds=5.0,
        ))
        self.addCleanup(service.close)
        return service

    def test_a_swallowed_fault_is_recorded_and_reported_through_health(self) -> None:
        service = self._service()
        session = service.gateway.create_session(
            title="fault session", locality="device-only", allowRemote=False,
            taskLimitUnits=0, sessionLimitUnits=0,
        )
        session_id = str(session["session"]["sessionId"])
        task = service.gateway.submit_task(
            sessionId=session_id, request=SIMPLE_REQUEST,
            classification="personal", costLimitUnits=0, run=False,
        )
        task_id = str(task["task"]["taskId"])

        # A fault the runtime classifies, raised from the run itself.
        def explode(_session_id: str, _task_id: str) -> None:
            raise StoreError(r"C:\Users\someone\store\task.json could not be written")

        service.gateway.runtime.run_task = explode  # type: ignore[assignment]

        service.gateway._schedule(task_id)
        worker = service.gateway.start_worker()
        self.addCleanup(service.gateway.stop_worker)

        deadline = threading.Event()
        for _ in range(500):
            if service.gateway.recent_faults():
                break
            deadline.wait(0.01)

        faults = service.gateway.recent_faults()
        self.assertTrue(faults, "the swallowed fault left no record")
        fault = faults[-1]

        # Structured, with every field §2 asks for.
        for key in (
            "faultType", "taskId", "operation", "lifecyclePhase", "at", "message",
            "retryAttempted", "taskStateChanged", "userVisibleRecoveryRequired",
        ):
            self.assertIn(key, fault)
        self.assertEqual(fault["faultType"], "StoreError")
        self.assertEqual(fault["taskId"], task_id)
        self.assertEqual(fault["operation"], "run_task")
        self.assertFalse(fault["retryAttempted"])

        # Sanitized on the way in.
        self.assertNotIn("someone", fault["message"])
        self.assertIn("<user-path>", fault["message"])

        # Reachable the way an operator would reach it.
        self.assertEqual(service.gateway.health()["recentWorkerFaults"], faults)

        # And the worker is still alive to take the next task.
        self.assertTrue(worker.is_alive())

    def test_an_unclassified_fault_is_marked_as_needing_a_person(self) -> None:
        """Third-party code failing in a way the runtime never described."""
        service = self._service()
        session = service.gateway.create_session(
            title="fault session", locality="device-only", allowRemote=False,
            taskLimitUnits=0, sessionLimitUnits=0,
        )
        session_id = str(session["session"]["sessionId"])
        task = service.gateway.submit_task(
            sessionId=session_id, request=SIMPLE_REQUEST,
            classification="personal", costLimitUnits=0, run=False,
        )
        task_id = str(task["task"]["taskId"])

        def explode(_session_id: str, _task_id: str) -> None:
            raise ZeroDivisionError("an executor divided by zero")

        service.gateway.runtime.run_task = explode  # type: ignore[assignment]
        service.gateway._schedule(task_id)
        service.gateway.start_worker()
        self.addCleanup(service.gateway.stop_worker)

        pause = threading.Event()
        for _ in range(500):
            if service.gateway.recent_faults():
                break
            pause.wait(0.01)

        fault = service.gateway.recent_faults()[-1]
        self.assertEqual(fault["faultType"], "ZeroDivisionError")
        self.assertFalse(fault["classified"])
        # Nothing told the user anything, so somebody has to.
        self.assertTrue(fault["userVisibleRecoveryRequired"])

    def test_the_record_is_bounded(self) -> None:
        """A long-running service must not grow a fault log without limit."""
        service = self._service()
        for index in range(80):
            service.gateway._record_fault(
                f"task-{index:032x}", CompanionError("a refusal"), classified=True
            )
        faults = service.gateway.recent_faults()
        self.assertLessEqual(len(faults), 32)
        # The most recent are the ones kept.
        self.assertEqual(faults[-1]["taskId"], f"task-{79:032x}")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
