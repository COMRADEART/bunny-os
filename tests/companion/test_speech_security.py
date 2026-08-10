# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""§22's attacks, each refused at the layer that owns the refusal.

The tests name the attack they are about, and most of them assert a refusal
that earlier suites established structurally — deliberately: a security suite
that relied on those suites continuing to exist would be a security suite one
refactor away from asserting nothing.
"""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from companion.speech.events import SpeechInputEvent
from companion.speech.execution import CAPTURE_EXECUTABLES, SpeechWorkspace
from companion.speech.recognizer import RecognizerDeclaration
from companion.speech.recovery import sweep_workspaces
from companion.speech.request import SpeechInputRequestError
from companion.speech.activity import SpeechActivityDetector
from companion.voice.execution import ExecutableRefused

from .support import temporary_root
from .speech_support import (
    FrameScript,
    ScriptedCaptureBackend,
    ScriptedRecognizer,
    build_worker,
    collect_events,
    make_request,
    silence_pcm,
    speech_pcm,
    wait_for,
)


class SilentActivation(unittest.TestCase):
    def test_an_invented_activation_source_cannot_construct_a_request(self) -> None:
        for hostile in ("service-startup", "cron", "wake-word", "recovery"):
            with self.subTest(source=hostile):
                with self.assertRaises(SpeechInputRequestError):
                    make_request(activation_source=hostile)

    def test_a_worker_never_captures_without_a_displayed_indicator(self) -> None:
        from .speech_support import RecordingSink

        harness = build_worker(sink=RecordingSink(can_display=False))
        self.addCleanup(harness.close)
        outcome = harness.worker.start_capture(make_request())
        self.assertTrue(outcome.accepted)
        wait_for(lambda: not harness.worker.active)
        self.assertEqual(harness.backend.opens, 0)


class ExecutionAllowlist(unittest.TestCase):
    def test_the_capture_allowlist_is_recorders_and_discovery_only(self) -> None:
        self.assertEqual(CAPTURE_EXECUTABLES, frozenset({
            "parec", "pw-record", "arecord", "pactl", "pw-dump",
        }))

    def test_an_arbitrary_program_is_refused_by_name(self) -> None:
        from companion.speech.execution import resolve_capture_executable

        for hostile in ("bash", "curl", "espeak-ng", "python3", "../parec"):
            with self.subTest(program=hostile):
                with self.assertRaises(ExecutableRefused):
                    resolve_capture_executable(hostile)


class PathTraversalAndSymlinks(unittest.TestCase):
    def test_workspace_file_names_are_confined_to_the_workspace(self) -> None:
        """Traversal characters lose their meaning: separators are stripped,
        so whatever the name says, the file is a child of the private root."""
        workspace = SpeechWorkspace()
        self.addCleanup(workspace.close)
        path = workspace.file("../../etc/passwd", suffix=".pcm")
        self.assertEqual(path.parent, workspace.root)
        self.assertNotIn("/", path.name)
        self.assertNotIn("\\", path.name)
        self.assertEqual(path.resolve().parent, workspace.root.resolve())

    @unittest.skipUnless(os.name == "posix", "symlink semantics are POSIX")
    def test_the_sweep_refuses_a_symlink_wearing_the_prefix(self) -> None:
        parent = temporary_root(self)
        target = parent / "victim"
        target.mkdir()
        (target / "precious.txt").write_text("do not delete", encoding="utf-8")
        link = parent / f"{SpeechWorkspace.PREFIX}stolen"
        link.symlink_to(target)
        removed, skipped, _files = sweep_workspaces(
            parent=parent, stale_after_seconds=0.0,
        )
        self.assertEqual(removed, 0)
        self.assertTrue(any("symbolic link" in reason for reason in skipped))
        self.assertTrue((target / "precious.txt").exists())

    def test_the_sweep_leaves_young_and_foreign_directories(self) -> None:
        parent = temporary_root(self)
        fresh = parent / f"{SpeechWorkspace.PREFIX}fresh"
        fresh.mkdir()
        removed, skipped, _files = sweep_workspaces(parent=parent)
        self.assertEqual(removed, 0)
        self.assertTrue(any("below the" in reason for reason in skipped))


class OversizedAndMalformedInput(unittest.TestCase):
    def test_a_malformed_frame_cannot_crash_the_detector(self) -> None:
        detector = SpeechActivityDetector(
            sample_rate=16_000, channels=1,
            initial_silence_seconds=1.0, endpoint_silence_seconds=0.4,
            maximum_seconds=10.0,
        )
        state = detector.feed(b"\x01")            # odd length
        state = detector.feed(b"\xff" * 33)        # odd, hostile values
        state = detector.feed(os.urandom(4096))    # noise
        self.assertIn(state.phase, (
            "calibrating", "waiting-for-speech", "speech", "trailing-silence", "ended",
        ))

    def test_oversized_capture_is_ended_by_the_budget_not_buffered(self) -> None:
        request = make_request(maximum_capture_seconds=1.0)
        script = FrameScript([speech_pcm(10.0)])
        harness = build_worker(backend=ScriptedCaptureBackend(script=script))
        self.addCleanup(harness.close)
        harness.worker.start_capture(request)
        wait_for(lambda: not harness.worker.active)
        handle = harness.backend.handles[0]
        self.assertLessEqual(handle.buffer.total_bytes, request.maximum_capture_bytes)

    def test_a_recognizer_emitting_control_characters_fails_rather_than_leaks(self) -> None:
        """Recogniser output injection: hostile text is refused by the
        transcript type and reported as a recognition failure."""
        script = FrameScript([speech_pcm(1.0), silence_pcm(1.0)])
        recognizer = ScriptedRecognizer(final_text="innocent")
        recognizer.final_text = "evil\x00payload"
        harness = build_worker(
            backend=ScriptedCaptureBackend(script=script), recognizer=recognizer,
        )
        self.addCleanup(harness.close)
        _received, kinds = collect_events(harness.worker)
        request = make_request()
        harness.worker.start_capture(request)
        wait_for(lambda: not harness.worker.active)
        self.assertIn("recognition_failed", kinds())
        self.assertIsNone(harness.ledger.get(request.request_id))


class EventHygiene(unittest.TestCase):
    def test_raw_audio_bytes_cannot_travel_in_an_event(self) -> None:
        with self.assertRaises(ValueError) as caught:
            SpeechInputEvent(
                kind="capture_started",
                request_id="r-1",
                payload={"frames": b"\x00\x01"},
            )
        self.assertIn("raw bytes", str(caught.exception))

    def test_forbidden_field_names_are_removed_and_recorded(self) -> None:
        event = SpeechInputEvent(
            kind="capture_started",
            request_id="r-1",
            payload={"rawAudio": "not really audio", "detail": "fine"},
        )
        document = event.to_json()
        self.assertNotIn("rawAudio", document)
        self.assertIn("rawAudio", document.get("removedFields", ()))
        self.assertEqual(document["detail"], "fine")

    def test_the_journal_holds_identity_and_never_content(self) -> None:
        import json
        from companion.speech.recovery import SpeechJournal

        journal = SpeechJournal(temporary_root(self) / "journal.jsonl")
        journal.record_start(make_request(), monotonic=1.0)
        journal.record_settle("speechreq-1", "completed", monotonic=2.0)
        raw = journal.path.read_text(encoding="utf-8")
        for line in raw.splitlines():
            document = json.loads(line)
            self.assertLessEqual(set(document), {
                "event", "requestId", "sessionId", "activationSource",
                "disposition", "atMonotonic", "pid",
            })


class RemoteRefusals(unittest.TestCase):
    def test_a_remote_declaration_is_refused_by_the_contract(self) -> None:
        declaration = RecognizerDeclaration(
            provider_id="cloudy", implementation_id="cloudy/1",
            local=False, languages=("en",), sample_rates=(16_000,),
        )
        permitted, reasons = declaration.serves(make_request())
        self.assertFalse(permitted)
        self.assertTrue(any("not local" in reason for reason in reasons))

    def test_a_paid_declaration_is_refused(self) -> None:
        declaration = RecognizerDeclaration(
            provider_id="metered", implementation_id="metered/1",
            local=True, languages=("en",), sample_rates=(16_000,),
            cost_class="paid",
        )
        permitted, reasons = declaration.serves(make_request())
        self.assertFalse(permitted)
        self.assertTrue(any("bills for use" in reason for reason in reasons))

    def test_the_request_type_refuses_every_wider_locality(self) -> None:
        with self.assertRaises(SpeechInputRequestError):
            make_request(locality_requirement="any")


class FailureLeavesNothingOpen(unittest.TestCase):
    def test_a_recognizer_crash_leaves_no_open_microphone(self) -> None:
        script = FrameScript([speech_pcm(1.0), silence_pcm(1.0)])
        harness = build_worker(
            backend=ScriptedCaptureBackend(script=script),
            recognizer=ScriptedRecognizer(failure_mode="crash-on-finish"),
        )
        self.addCleanup(harness.close)
        harness.worker.start_capture(make_request())
        wait_for(lambda: not harness.worker.active)
        self.assertTrue(all(handle.closed for handle in harness.backend.handles))
        self.assertFalse(harness.indicator.listening)

    def test_a_backend_that_cannot_start_leaves_the_indicator_down(self) -> None:
        harness = build_worker(
            backend=ScriptedCaptureBackend(fail_start="permission denied"),
        )
        self.addCleanup(harness.close)
        _received, kinds = collect_events(harness.worker)
        harness.worker.start_capture(make_request())
        wait_for(lambda: not harness.worker.active)
        self.assertFalse(harness.indicator.listening)
        stream = kinds()
        if "indicator_cleared" in stream and "microphone_indicator_raised" in stream:
            self.assertLess(
                stream.index("microphone_indicator_raised"),
                stream.index("indicator_cleared"),
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
