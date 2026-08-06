# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The capture worker's lifecycle: §4's ordering, §5's indicator, §13's ledger.

Every test drives the real :class:`companion.speech.worker.CaptureWorker` over
scripted collaborators implementing the real contracts. The assertions that
matter most are *orderings* — indicator before open, closed before cleared —
and they are read from the event stream the worker emitted, which is the same
stream a gate counts.
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from companion.speech.policy import SpeechInputPreferences
from companion.speech.recovery import SpeechJournal

from .speech_support import (
    FrameScript,
    RecordingSink,
    ScriptedCaptureBackend,
    ScriptedRecognizer,
    build_worker,
    collect_events,
    make_request,
    silence_pcm,
    speech_pcm,
    wait_for,
)


def _run_capture(harness, request, *, timeout: float = 10.0) -> None:
    outcome = harness.worker.start_capture(request)
    assert outcome.accepted, outcome.detail
    assert wait_for(lambda: not harness.worker.active, timeout), "the capture did not settle"


class HappyPath(unittest.TestCase):
    """One utterance, beginning to waiting-for-confirmation."""

    def setUp(self) -> None:
        script = FrameScript([speech_pcm(1.2), silence_pcm(1.0)])
        self.harness = build_worker(
            backend=ScriptedCaptureBackend(script=script),
            recognizer=ScriptedRecognizer(final_text="count the words in this note"),
        )
        self.addCleanup(self.harness.close)
        self.received, self.kinds = collect_events(self.harness.worker)

    def test_the_whole_ordering_holds(self) -> None:
        _run_capture(self.harness, make_request())
        kinds = self.kinds()
        for needed in (
            "speech_input_requested", "microphone_indicator_raised",
            "microphone_opened", "capture_started", "speech_detected",
            "silence_detected", "capture_stopped", "microphone_closed",
            "indicator_cleared", "recognition_finalizing", "final_transcript",
            "transcript_confirmation_requested",
        ):
            self.assertIn(needed, kinds, f"{needed} missing from {kinds}")
        # §4: the indicator precedes the open; §5: the close precedes the clear.
        self.assertLess(
            kinds.index("microphone_indicator_raised"), kinds.index("microphone_opened")
        )
        self.assertLess(
            kinds.index("microphone_closed"), kinds.index("indicator_cleared")
        )
        # §11: sequences are strictly monotonic per request.
        sequences = [event.sequence for event in self.received]
        self.assertEqual(sequences, sorted(sequences))
        self.assertEqual(len(sequences), len(set(sequences)))

    def test_partials_are_provisional_and_the_final_reaches_the_ledger(self) -> None:
        request = make_request()
        _run_capture(self.harness, request)
        partials = [event for event in self.received if event.kind == "partial_transcript"]
        self.assertTrue(partials, "the streaming path produced no partials")
        for event in partials:
            self.assertTrue(dict(event.payload)["provisional"])
        entry = self.harness.ledger.get(request.request_id)
        self.assertIsNotNone(entry)
        self.assertEqual(entry.state, "pending")
        self.assertEqual(entry.transcript.text, "count the words in this note")
        self.assertFalse(entry.transcript.user_edited)
        self.assertTrue(entry.transcript.audio_digest.startswith("sha256:"))

    def test_the_indicator_showed_for_the_whole_interval(self) -> None:
        _run_capture(self.harness, make_request())
        sink = self.harness.sink
        self.assertEqual(len(sink.shown), 1)
        self.assertEqual(len(sink.cleared), 1)
        self.assertLess(sink.shown_at[0], sink.cleared_at[0])
        self.assertFalse(sink.shown[0]["audioRetained"])
        self.assertEqual(sink.shown[0]["locality"], "local")

    def test_measurements_record_the_orderings(self) -> None:
        request = make_request()
        _run_capture(self.harness, request)
        measurement = self.harness.worker.measurement(request.request_id)
        self.assertIsNotNone(measurement)
        document = measurement.to_json()
        self.assertTrue(document["indicatorBeforeOpen"])
        self.assertTrue(document["indicatorClearedAfterClose"])
        self.assertIsNotNone(document["finalTranscriptLatencySeconds"])

    def test_the_journal_records_start_and_settle(self) -> None:
        journal = SpeechJournal(Path(tempfile.mkdtemp()) / "journal.jsonl")
        script = FrameScript([speech_pcm(1.0), silence_pcm(1.0)])
        harness = build_worker(
            backend=ScriptedCaptureBackend(script=script), journal=journal,
        )
        self.addCleanup(harness.close)
        request = make_request()
        _run_capture(harness, request)
        entries = journal.read()
        events = [(item["event"], item.get("disposition", "")) for item in entries]
        self.assertIn(("start", ""), events)
        self.assertIn(("settle", "completed"), events)


class ActivationGate(unittest.TestCase):
    """§4's conditions, each as the refusal it produces."""

    def test_a_disabled_preference_refuses_before_anything_exists(self) -> None:
        harness = build_worker(preferences=SpeechInputPreferences(enabled=False))
        self.addCleanup(harness.close)
        outcome = harness.worker.start_capture(make_request())
        self.assertFalse(outcome.accepted)
        self.assertIn("typed", outcome.detail.lower() + outcome.to_json()["detail"].lower())
        self.assertEqual(harness.backend.opens, 0)

    def test_an_expired_activation_is_refused(self) -> None:
        harness = build_worker()
        self.addCleanup(harness.close)
        outcome = harness.worker.start_capture(make_request(expires_at_monotonic=1.0))
        self.assertFalse(outcome.accepted)
        self.assertIn("lapsed", outcome.detail)
        self.assertEqual(harness.backend.opens, 0)

    def test_no_recognizer_refuses_with_typed_input_preserved(self) -> None:
        harness = build_worker(recognizer=ScriptedRecognizer(available=False))
        self.addCleanup(harness.close)
        outcome = harness.worker.start_capture(make_request())
        self.assertFalse(outcome.accepted)
        self.assertTrue(outcome.to_json()["typedInputPreserved"])
        self.assertEqual(harness.backend.opens, 0)

    def test_an_undisplayable_indicator_keeps_the_microphone_shut(self) -> None:
        """§4's sentence: if the indicator cannot be raised, do not open."""
        harness = build_worker(sink=RecordingSink(can_display=False))
        self.addCleanup(harness.close)
        _received, kinds = collect_events(harness.worker)
        outcome = harness.worker.start_capture(make_request())
        self.assertTrue(outcome.accepted, "the refusal happens inside the session")
        wait_for(lambda: not harness.worker.active)
        self.assertEqual(harness.backend.opens, 0, "the microphone was never opened")
        self.assertNotIn("microphone_opened", kinds())
        degradations = [
            dict(event.payload) for event in _received
            if event.kind == "speech_input_degraded"
        ]
        self.assertTrue(any(item.get("kind") == "indicator-unavailable" for item in degradations))

    def test_immediate_submission_without_the_preference_is_refused(self) -> None:
        harness = build_worker()
        self.addCleanup(harness.close)
        outcome = harness.worker.start_capture(make_request(confirmation_required=False))
        self.assertFalse(outcome.accepted)
        self.assertIn("immediate submission", outcome.detail)

    def test_a_second_capture_is_refused_while_one_runs(self) -> None:
        script = FrameScript()
        script.hold.set()  # a device that stays open delivering nothing yet
        harness = build_worker(backend=ScriptedCaptureBackend(script=script))
        self.addCleanup(harness.close)
        first = harness.worker.start_capture(make_request(request_id="speechreq-a"))
        self.assertTrue(first.accepted)
        wait_for(lambda: harness.backend.opens == 1)
        second = harness.worker.start_capture(make_request(request_id="speechreq-b"))
        self.assertFalse(second.accepted)
        self.assertIn("one microphone, one capture", second.detail)
        harness.worker.cancel("speechreq-a", token="")
        wait_for(lambda: not harness.worker.active)

    def test_a_reused_request_id_is_refused(self) -> None:
        script = FrameScript([speech_pcm(0.5), silence_pcm(1.0)])
        harness = build_worker(backend=ScriptedCaptureBackend(script=script))
        self.addCleanup(harness.close)
        _run_capture(harness, make_request(request_id="speechreq-dup"))
        again = harness.worker.start_capture(make_request(request_id="speechreq-dup"))
        self.assertFalse(again.accepted)
        self.assertIn("already been used", again.detail)


class Endings(unittest.TestCase):
    """The non-happy settlements, each with its cleanup asserted."""

    def test_pure_silence_settles_as_no_speech_with_no_transcript(self) -> None:
        script = FrameScript([silence_pcm(3.0)])
        harness = build_worker(backend=ScriptedCaptureBackend(script=script))
        self.addCleanup(harness.close)
        request = make_request(initial_silence_seconds=1.0)
        _run_capture(harness, request)
        self.assertIsNone(harness.ledger.get(request.request_id))
        status = harness.worker.status()
        dispositions = [item["disposition"] for item in status["recentDispositions"]]
        self.assertIn("no-speech", dispositions)

    def test_device_loss_preserves_an_incomplete_transcript_and_no_task(self) -> None:
        """§17, end to end: stop, close, clear after close, preserve marked."""
        script = FrameScript([speech_pcm(1.0)])
        backend = ScriptedCaptureBackend(script=script)
        harness = build_worker(
            backend=backend,
            recognizer=ScriptedRecognizer(final_text="count the words"),
        )
        self.addCleanup(harness.close)
        received, kinds = collect_events(harness.worker)
        request = make_request()
        outcome = harness.worker.start_capture(request)
        self.assertTrue(outcome.accepted)
        wait_for(lambda: any(k == "speech_detected" for k in kinds()))
        script.end()  # the device dies mid-capture
        wait_for(lambda: not harness.worker.active)
        self.assertIn("device_lost", kinds())
        self.assertLess(kinds().index("microphone_closed"), kinds().index("indicator_cleared"))
        entry = harness.ledger.get(request.request_id)
        self.assertIsNotNone(entry, "the provisional transcript was preserved")
        self.assertTrue(entry.transcript.incomplete)
        lost = [dict(e.payload) for e in received if e.kind == "device_lost"]
        self.assertTrue(lost[0]["typedInputPreserved"])
        self.assertTrue(lost[0]["retryAvailable"])

    def test_a_recognizer_crash_at_finalisation_offers_retry_and_typing(self) -> None:
        script = FrameScript([speech_pcm(1.0), silence_pcm(1.0)])
        harness = build_worker(
            backend=ScriptedCaptureBackend(script=script),
            recognizer=ScriptedRecognizer(failure_mode="crash-on-finish"),
        )
        self.addCleanup(harness.close)
        received, kinds = collect_events(harness.worker)
        request = make_request()
        _run_capture(harness, request)
        self.assertIn("recognition_failed", kinds())
        failures = [dict(e.payload) for e in received if e.kind == "recognition_failed"]
        self.assertTrue(any(item.get("retryAvailable") for item in failures))
        self.assertIsNone(harness.ledger.get(request.request_id))
        # The indicator still cleared after the close, crash or not.
        self.assertLess(kinds().index("microphone_closed"), kinds().index("indicator_cleared"))

    def test_manual_stop_overrides_the_automatic_endpoints(self) -> None:
        script = FrameScript([speech_pcm(0.6)])
        script.hold.set()
        harness = build_worker(backend=ScriptedCaptureBackend(script=script))
        self.addCleanup(harness.close)
        _received, kinds = collect_events(harness.worker)
        request = make_request(initial_silence_seconds=30.0, maximum_capture_seconds=60.0)
        outcome = harness.worker.start_capture(request)
        self.assertTrue(outcome.accepted)
        wait_for(lambda: "capture_started" in kinds())
        script.hold.clear()
        wait_for(lambda: "speech_detected" in kinds())
        stopped, _reason = harness.worker.stop_capture(request.request_id)
        self.assertTrue(stopped)
        wait_for(lambda: not harness.worker.active)
        stops = [k for k in kinds() if k == "capture_stopped"]
        self.assertTrue(stops)
        self.assertIsNotNone(harness.ledger.get(request.request_id))

    def test_the_byte_budget_ends_the_capture(self) -> None:
        request = make_request(maximum_capture_seconds=1.0)
        # Far more audio than one second's budget, delivered instantly.
        script = FrameScript([speech_pcm(6.0)])
        harness = build_worker(backend=ScriptedCaptureBackend(script=script))
        self.addCleanup(harness.close)
        outcome = harness.worker.start_capture(request)
        self.assertTrue(outcome.accepted)
        wait_for(lambda: not harness.worker.active)
        status = harness.worker.status()
        dispositions = [item["disposition"] for item in status["recentDispositions"]]
        self.assertTrue(
            any(item in ("completed", "no-speech") for item in dispositions),
            f"the budgeted capture settled: {dispositions}",
        )


class BatchPath(unittest.TestCase):
    def test_a_non_streaming_recognizer_runs_batch_with_no_partials(self) -> None:
        script = FrameScript([speech_pcm(1.0), silence_pcm(1.0)])
        recognizer = ScriptedRecognizer(
            supports_streaming=False, supports_partials=False,
            final_text="batch answer",
        )
        harness = build_worker(
            backend=ScriptedCaptureBackend(script=script), recognizer=recognizer,
        )
        self.addCleanup(harness.close)
        received, kinds = collect_events(harness.worker)
        request = make_request()
        _run_capture(harness, request)
        self.assertNotIn("partial_transcript", kinds())
        entry = harness.ledger.get(request.request_id)
        self.assertIsNotNone(entry)
        self.assertEqual(entry.transcript.recognition_mode, "batch")
        self.assertEqual(entry.transcript.text, "batch answer")


class PartialsUnderPressure(unittest.TestCase):
    def test_the_partial_cap_suppresses_with_a_typed_degradation(self) -> None:
        # Hundreds of small chunks, one word of growth each: the cap is
        # reached long before the audio ends. One long waveform sliced, not
        # many short ones — a restarted envelope is all quiet first-block and
        # calibrates itself into the floor.
        body = speech_pcm(7.0)
        script = FrameScript(
            [body[i:i + 640] for i in range(0, len(body), 640)] + [silence_pcm(1.0)]
        )
        recognizer = ScriptedRecognizer(
            final_text=" ".join(f"w{i}" for i in range(800)),
            bytes_per_partial=640,
        )
        harness = build_worker(
            backend=ScriptedCaptureBackend(script=script), recognizer=recognizer,
        )
        self.addCleanup(harness.close)
        received, kinds = collect_events(harness.worker)
        _run_capture(harness, make_request())
        partials = [e for e in received if e.kind == "partial_transcript"]
        from companion.speech.worker import MAX_PARTIALS_PER_CAPTURE

        self.assertLessEqual(len(partials), MAX_PARTIALS_PER_CAPTURE)
        degradations = [
            dict(e.payload) for e in received if e.kind == "speech_input_degraded"
        ]
        self.assertTrue(
            any(item.get("kind") == "partial-transcripts-suppressed" for item in degradations)
        )
        # Final recognition is unaffected by the suppression.
        self.assertIn("final_transcript", kinds())


class WorkerLifecycle(unittest.TestCase):
    def test_close_cancels_and_releases_everything(self) -> None:
        script = FrameScript()
        script.hold.set()
        harness = build_worker(backend=ScriptedCaptureBackend(script=script))
        outcome = harness.worker.start_capture(make_request())
        self.assertTrue(outcome.accepted)
        wait_for(lambda: harness.backend.opens == 1)
        self.assertTrue(harness.worker.close())
        self.assertFalse(harness.worker.active)
        self.assertTrue(all(handle.closed for handle in harness.backend.handles))
        self.assertFalse(harness.indicator.listening)

    def test_a_closed_worker_refuses_new_captures(self) -> None:
        harness = build_worker()
        harness.worker.close()
        outcome = harness.worker.start_capture(make_request())
        self.assertFalse(outcome.accepted)
        self.assertIn("stopped", outcome.detail)

    def test_the_status_names_every_boundary(self) -> None:
        harness = build_worker()
        self.addCleanup(harness.close)
        boundaries = harness.worker.status()["boundaries"]
        for name, expected in (
            ("microphoneOpensOnExplicitActionOnly", True),
            ("indicatorBeforeOpen", True),
            ("indicatorClearedAfterClose", True),
            ("mayCreateTask", False),
            ("mayResolveApprovals", False),
            ("mayExecuteTools", False),
            ("remoteTransmission", False),
            ("wakeWordSupported", False),
            ("continuousListeningSupported", False),
            ("voiceBiometricsSupported", False),
            ("speakerIdentificationSupported", False),
            ("rawAudioRetainedByDefault", False),
        ):
            self.assertEqual(boundaries[name], expected, name)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
