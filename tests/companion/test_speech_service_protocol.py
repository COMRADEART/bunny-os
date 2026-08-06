# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Speech input over the real service and the real socket, end to end.

The service builds its own speech runtime; the tests then point its router and
registry at scripted devices — the same substitution the stress gates perform —
and drive everything through :class:`companion.protocol.CompanionClient`, so
what is exercised is the whole path a GTK window takes: protocol validation,
the gateway's delegation, the worker's lifecycle, and the one seam where a
confirmed transcript becomes a task.
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import time
import unittest

from companion.protocol import CompanionClient, CompanionClientError
from companion.service import CompanionService, ServiceOptions

from .speech_support import (
    FrameScript,
    RecordingSink,
    ScriptedCaptureBackend,
    ScriptedRecognizer,
    silence_pcm,
    speech_pcm,
    wait_for,
)


def _service(root: Path) -> CompanionService:
    return CompanionService(ServiceOptions(
        root=root / "store",
        endpoint=root / "run" / "runtime.sock",
        machine="laptop",
        consent_wait_seconds=5.0,
    )).start()


def _script_speech(service: CompanionService, *, script: FrameScript | None = None,
                   recognizer: ScriptedRecognizer | None = None) -> tuple[ScriptedCaptureBackend, ScriptedRecognizer, RecordingSink]:
    """Point the service's own speech runtime at scripted devices."""
    speech = service.speech
    assert speech is not None
    backend = ScriptedCaptureBackend(script=script or FrameScript(
        [speech_pcm(1.0), silence_pcm(1.0)]
    ))
    speech.router.backends.clear()
    speech.router.backends.append(backend)
    recognizer = recognizer or ScriptedRecognizer(final_text="count the words in this note")
    speech.registry.add(recognizer)
    sink = RecordingSink()
    speech.attach_indicator_sink(sink)
    # The service observed this host before the scripted devices existed, and
    # machine-signal hysteresis holds a degraded outcome across single good
    # readings. A preference re-set is the doorway that takes effect at once —
    # the same one a user flipping the setting walks through.
    speech.set_preferences(speech.options.preferences)
    return backend, recognizer, sink


class ProtocolValidation(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(tempfile.mkdtemp())
        cls.service = _service(cls.root)
        cls.client = CompanionClient(cls.service.server.endpoint)
        session = cls.client.call("create_session", {"title": "speech protocol"})
        cls.session_id = session["session"]["sessionId"]

    @classmethod
    def tearDownClass(cls) -> None:
        cls.service.close()

    def test_an_undeclared_parameter_is_refused_not_ignored(self) -> None:
        with self.assertRaises(CompanionClientError) as caught:
            self.client.call("speech_input_start", {
                "sessionId": self.session_id,
                "activationSource": "push-to-talk-button",
                "modelPath": "/tmp/evil",
            })
        self.assertEqual(caught.exception.code, "invalid_request")
        self.assertIn("modelPath", str(caught.exception))

    def test_a_silent_activation_is_refused_at_the_protocol(self) -> None:
        with self.assertRaises(CompanionClientError) as caught:
            self.client.call("speech_input_start", {
                "sessionId": self.session_id,
                "activationSource": "wake-word",
            })
        self.assertEqual(caught.exception.code, "invalid_request")
        self.assertIn("explicit", str(caught.exception))

    def test_a_capture_for_an_unknown_session_is_refused(self) -> None:
        with self.assertRaises(CompanionClientError):
            self.client.call("speech_input_start", {
                "sessionId": "session-invented",
                "activationSource": "push-to-talk-button",
            })

    def test_bounds_on_durations_are_the_protocols_own(self) -> None:
        with self.assertRaises(CompanionClientError):
            self.client.call("speech_input_start", {
                "sessionId": self.session_id,
                "activationSource": "push-to-talk-button",
                "maxCaptureMs": 10_000_000,
            })

    def test_health_and_devices_answer_without_a_capture(self) -> None:
        health = self.client.call("speech_input_health")
        self.assertTrue(health["available"])
        boundaries = health["boundaries"]
        self.assertFalse(boundaries["wakeWordSupported"])
        self.assertFalse(boundaries["remoteRecognitionConfigured"])
        self.assertTrue(boundaries["confirmationRequiredByDefault"])
        devices = self.client.call("speech_input_devices")
        self.assertTrue(devices["available"])
        self.assertFalse(devices["monitorSourcesSelectable"])

    def test_the_microphone_is_closed_at_startup_and_says_so(self) -> None:
        health = self.client.call("health")
        self.assertFalse(health["microphoneActive"])
        self.assertTrue(health["speechInputAvailable"])


class EndToEnd(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.service = _service(self.root)
        self.addCleanup(self.service.close)
        self.client = CompanionClient(self.service.server.endpoint)
        session = self.client.call("create_session", {"title": "speech e2e"})
        self.session_id = session["session"]["sessionId"]
        self.backend, self.recognizer, self.sink = _script_speech(self.service)

    def _capture(self, **overrides) -> dict:
        params = {
            "sessionId": self.session_id,
            "activationSource": "push-to-talk-button",
            "maxCaptureMs": 8_000,
            "initialSilenceMs": 2_000,
            "endpointSilenceMs": 400,
        }
        params.update(overrides)
        answer = self.client.call("speech_input_start", params)
        self.assertTrue(answer["accepted"], answer.get("detail"))
        self.assertTrue(wait_for(lambda: not self.service.speech.worker.active))
        return answer

    def test_dictation_confirmation_and_exactly_one_task(self) -> None:
        started = self._capture()
        request_id = started["requestId"]
        # The transcript waits; the microphone reports closed again.
        health = self.client.call("health")
        self.assertFalse(health["microphoneActive"])
        entry = self.service.speech.ledger.get(request_id)
        self.assertEqual(entry.state, "pending")
        before = len(self.client.call("list_tasks", {"sessionId": self.session_id})["tasks"])
        confirmed = self.client.call("speech_input_confirm", {
            "requestId": request_id,
            "sessionId": self.session_id,
            "text": "count the words in this short note",
            "cancellationToken": started["cancellationToken"],
        })
        self.assertTrue(confirmed["confirmed"])
        self.assertTrue(confirmed["submitted"])
        self.assertTrue(confirmed["userEdited"])
        self.assertTrue(confirmed["taskCreated"])
        after = self.client.call("list_tasks", {"sessionId": self.session_id})["tasks"]
        self.assertEqual(len(after), before + 1)
        task_id = confirmed["task"]["taskId"]
        # The dictated task runs the same canonical path a typed one does.
        self.assertTrue(wait_for(
            lambda: self.client.call("get_task", {"taskId": task_id})["task"]["state"]
            in ("completed", "failed", "blocked", "waiting_for_approval", "executing",
                "planning", "classifying", "reviewing", "presenting"),
        ))

    def test_a_second_confirmation_is_a_replay_and_creates_nothing(self) -> None:
        started = self._capture()
        request_id = started["requestId"]
        first = self.client.call("speech_input_confirm", {
            "requestId": request_id,
            "sessionId": self.session_id,
            "cancellationToken": started["cancellationToken"],
        })
        self.assertTrue(first["submitted"])
        count = len(self.client.call("list_tasks", {"sessionId": self.session_id})["tasks"])
        second = self.client.call("speech_input_confirm", {
            "requestId": request_id,
            "sessionId": self.session_id,
            "cancellationToken": started["cancellationToken"],
        })
        self.assertFalse(second["confirmed"])
        self.assertIn("once", second["reason"])
        self.assertEqual(
            len(self.client.call("list_tasks", {"sessionId": self.session_id})["tasks"]),
            count,
        )

    def test_a_cross_session_confirmation_is_refused_over_the_wire(self) -> None:
        started = self._capture()
        other = self.client.call("create_session", {"title": "other"})["session"]["sessionId"]
        answer = self.client.call("speech_input_confirm", {
            "requestId": started["requestId"],
            "sessionId": other,
            "cancellationToken": started["cancellationToken"],
        })
        self.assertFalse(answer["confirmed"])
        self.assertIn("different session", answer["reason"])

    def test_retry_supersedes_and_the_old_transcript_cannot_be_confirmed(self) -> None:
        started = self._capture()
        old_request = started["requestId"]
        # Refill the device for the second take.
        self.backend.script.push(speech_pcm(1.0))
        self.backend.script.push(silence_pcm(1.0))
        retried = self.client.call("speech_input_retry", {
            "requestId": old_request,
            "activationSource": "push-to-talk-button",
        })
        self.assertTrue(retried["accepted"], retried.get("detail"))
        self.assertNotEqual(retried["requestId"], old_request)
        wait_for(lambda: not self.service.speech.worker.active)
        stale = self.client.call("speech_input_confirm", {
            "requestId": old_request,
            "sessionId": self.session_id,
            "cancellationToken": started["cancellationToken"],
        })
        self.assertFalse(stale["confirmed"])
        self.assertIn("superseded", stale["reason"])

    def test_cancel_after_final_rejects_instead_of_creating(self) -> None:
        started = self._capture()
        answer = self.client.call("speech_input_cancel", {
            "requestId": started["requestId"],
            "cancellationToken": started["cancellationToken"],
        })
        self.assertTrue(answer["cancelled"])
        self.assertEqual(answer["stage"], "confirmation")
        self.assertFalse(answer["taskCreated"])
        confirmed = self.client.call("speech_input_confirm", {
            "requestId": started["requestId"],
            "sessionId": self.session_id,
            "cancellationToken": started["cancellationToken"],
        })
        self.assertFalse(confirmed["confirmed"])

    def test_status_reports_the_flow_and_the_indicator_showed(self) -> None:
        self._capture()
        status = self.client.call("speech_input_status")
        self.assertTrue(status["available"])
        self.assertFalse(status["capturing"])
        kinds = [item["kind"] for item in status["recentEvents"]]
        self.assertIn("final_transcript", kinds)
        self.assertEqual(len(self.sink.shown), 1)
        self.assertEqual(len(self.sink.cleared), 1)


class WorkerRestart(unittest.TestCase):
    def test_restart_mid_capture_cancels_and_the_task_surface_is_untouched(self) -> None:
        root = Path(tempfile.mkdtemp())
        service = _service(root)
        self.addCleanup(service.close)
        client = CompanionClient(service.server.endpoint)
        session_id = client.call("create_session", {"title": "restart"})["session"]["sessionId"]
        script = FrameScript()
        script.hold.set()
        _backend, _recognizer, _sink = _script_speech(service, script=script)
        started = client.call("speech_input_start", {
            "sessionId": session_id,
            "activationSource": "push-to-talk-button",
        })
        self.assertTrue(started["accepted"], started.get("detail"))
        wait_for(lambda: service.speech.worker.active)
        report = service.speech.restart_worker(timeout=10.0)
        self.assertFalse(service.speech.worker.active)
        self.assertFalse(client.call("health")["microphoneActive"])
        # No capture resumes; a fresh start is required and works.
        self.assertFalse(service.speech.worker.status()["capturing"])
        outcome = client.call("speech_input_start", {
            "sessionId": session_id,
            "activationSource": "push-to-talk-button",
        })
        self.assertTrue(outcome["accepted"], outcome.get("detail"))
        service.speech.worker.cancel(outcome["requestId"], token="")
        wait_for(lambda: not service.speech.worker.active)


class DisabledSpeech(unittest.TestCase):
    def test_a_service_without_speech_answers_honestly(self) -> None:
        root = Path(tempfile.mkdtemp())
        service = CompanionService(ServiceOptions(
            root=root / "store", endpoint=root / "run" / "runtime.sock",
            machine="laptop", speech_enabled=False,
        )).start()
        self.addCleanup(service.close)
        client = CompanionClient(service.server.endpoint)
        answer = client.call("speech_input_health")
        self.assertFalse(answer["available"])
        self.assertTrue(answer["typedInputPreserved"])
        health = client.call("health")
        self.assertFalse(health["speechInputAvailable"])
        self.assertFalse(health["microphoneActive"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
