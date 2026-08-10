# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""§1's boundaries, asserted from the import graph and the object graph.

The claims: speech input may not create a task, resolve an approval, execute a
tool, select an executor or change task state; captured audio never leaves the
machine; and the one seam through which confirmed text becomes a task is the
gateway. Where a claim is structural, the test reads the structure — imports,
attributes — rather than trusting a flag.
"""

from __future__ import annotations

import ast
from pathlib import Path
import unittest

import companion.speech.worker
import companion.speech.service
from companion.speech.coordination import VoiceOutputCoordinator

from .speech_support import (
    FrameScript,
    ScriptedCaptureBackend,
    build_worker,
    make_request,
    silence_pcm,
    speech_pcm,
    wait_for,
)

#: Modules that hold task authority. Nothing under companion/speech/ may import
#: any of them, and the test below reads the AST of every speech module to say
#: so — the same proof-by-import-graph the voice worker carries.
_FORBIDDEN_IMPORTS = (
    "companion.runtime", "companion.store", "companion.task",
    "companion.approvals", "companion.executor", "companion.tools",
    "companion.session", "companion.reviewer",
)


class ImportGraph(unittest.TestCase):
    def test_no_speech_module_imports_task_authority(self) -> None:
        package = Path(companion.speech.worker.__file__).parent
        for module_path in sorted(package.glob("*.py")):
            tree = ast.parse(module_path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    # Relative imports resolve inside the companion package.
                    if node.level:
                        names = ["companion." + node.module]
                    else:
                        names = [node.module]
                for name in names:
                    for forbidden in _FORBIDDEN_IMPORTS:
                        self.assertFalse(
                            name == forbidden or name.startswith(forbidden + "."),
                            f"{module_path.name} imports {name}, which holds task authority",
                        )

    def test_the_listening_link_never_touches_lip_sync(self) -> None:
        """§18: microphone input never drives the mouth. Asserted from source."""
        import companion.character.listening_link as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                self.assertNotIn(
                    node.attr,
                    ("start_lip_sync", "advance_lip_sync"),
                    "the listening link reached for the mouth",
                )


class ObjectGraph(unittest.TestCase):
    def test_the_worker_holds_nothing_with_task_authority(self) -> None:
        harness = build_worker()
        self.addCleanup(harness.close)
        for attribute in vars(harness.worker).values():
            module = type(attribute).__module__
            for forbidden in _FORBIDDEN_IMPORTS:
                self.assertFalse(
                    module.startswith(forbidden),
                    f"the worker holds a {module} object",
                )

    def test_the_service_confirmation_returns_text_and_submits_nothing(self) -> None:
        """The seam: confirm_transcript hands back a value; the runtime is not
        reachable from the speech service to act on it."""
        from companion.speech.service import SpeechInputService

        self.assertFalse(hasattr(SpeechInputService, "submit_task"))
        self.assertFalse(hasattr(SpeechInputService, "runtime"))

    def test_every_boundary_flag_is_stated_and_false_where_it_must_be(self) -> None:
        harness = build_worker()
        self.addCleanup(harness.close)
        boundaries = harness.worker.status()["boundaries"]
        for forbidden in (
            "mayCreateTask", "mayResolveApprovals", "mayExecuteTools",
            "mayChangeTaskState", "remoteTransmission", "wakeWordSupported",
            "continuousListeningSupported", "voiceBiometricsSupported",
            "speakerIdentificationSupported", "rawAudioRetainedByDefault",
        ):
            self.assertIn(forbidden, boundaries)
            self.assertFalse(boundaries[forbidden], forbidden)


class OutputCoordination(unittest.TestCase):
    """§19 as behaviour: quiesce before, record honestly, never auto-replay."""

    class _FakeVoiceWorker:
        def __init__(self, *, current: dict | None = None, pausable: bool = True) -> None:
            self._current = current
            self._pausable = pausable
            self.paused = False
            self.resumed = False
            self.cancelled: list[str] = []

        def status(self) -> dict:
            return {"current": self._current}

        def pause(self) -> bool:
            self.paused = self._pausable
            return self._pausable

        def resume(self) -> bool:
            self.resumed = True
            return True

        def cancel(self, request_id: str) -> bool:
            self.cancelled.append(request_id)
            return True

    def test_nothing_playing_is_recorded_as_nothing(self) -> None:
        coordinator = VoiceOutputCoordinator(self._FakeVoiceWorker())
        record = coordinator.quiesce(capture_request_id="speechreq-1")
        self.assertFalse(record.output_was_active)
        self.assertEqual(record.action, "none")

    def test_noncritical_speech_is_cancelled(self) -> None:
        worker = self._FakeVoiceWorker(
            current={"requestId": "voice-1", "priority": "progress_update"},
        )
        coordinator = VoiceOutputCoordinator(worker)
        record = coordinator.quiesce(capture_request_id="speechreq-1")
        self.assertTrue(record.output_was_active)
        self.assertEqual(record.action, "cancelled")
        self.assertEqual(worker.cancelled, ["voice-1"])

    def test_essential_speech_is_paused(self) -> None:
        worker = self._FakeVoiceWorker(
            current={"requestId": "voice-2", "priority": "task_result"},
        )
        coordinator = VoiceOutputCoordinator(worker)
        record = coordinator.quiesce(capture_request_id="speechreq-1")
        self.assertEqual(record.action, "paused")
        self.assertTrue(worker.paused)

    def test_the_submission_path_never_resumes(self) -> None:
        """§19's last sentence, as the default of release()."""
        worker = self._FakeVoiceWorker(
            current={"requestId": "voice-3", "priority": "task_result"},
        )
        coordinator = VoiceOutputCoordinator(worker)
        coordinator.quiesce(capture_request_id="speechreq-1")
        record = coordinator.release()
        self.assertFalse(record.resumed)
        self.assertFalse(worker.resumed)
        self.assertFalse(record.to_json()["automaticReplayAfterSubmission"])

    def test_the_cancellation_path_may_resume_a_pause(self) -> None:
        worker = self._FakeVoiceWorker(
            current={"requestId": "voice-4", "priority": "task_result"},
        )
        coordinator = VoiceOutputCoordinator(worker)
        coordinator.quiesce(capture_request_id="speechreq-1")
        record = coordinator.release(resume_paused=True)
        self.assertTrue(record.resumed)
        self.assertTrue(worker.resumed)

    def test_a_voice_fault_cannot_stop_a_capture(self) -> None:
        class _Broken:
            def status(self):
                raise RuntimeError("voice fell over")

        coordinator = VoiceOutputCoordinator(_Broken())
        record = coordinator.quiesce(capture_request_id="speechreq-1")
        self.assertFalse(record.output_was_active)
        self.assertIn("could not be consulted", record.detail)

    def test_the_capture_records_output_state_in_its_flow(self) -> None:
        worker = self._FakeVoiceWorker(
            current={"requestId": "voice-5", "priority": "decorative"},
        )
        coordinator = VoiceOutputCoordinator(worker)
        script = FrameScript([speech_pcm(1.0), silence_pcm(1.0)])
        harness = build_worker(
            backend=ScriptedCaptureBackend(script=script), coordinator=coordinator,
        )
        self.addCleanup(harness.close)
        request = make_request()
        harness.worker.start_capture(request)
        wait_for(lambda: not harness.worker.active)
        self.assertEqual(worker.cancelled, ["voice-5"])
        self.assertFalse(worker.resumed, "a completed capture resumed nothing")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
