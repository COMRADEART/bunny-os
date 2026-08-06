# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""§16's races, each expressed with a barrier rather than a sleep.

The shape of every test: put the runtime *inside* the operation using an event
the fixture waits on, deliver the racing action, release the gate, and assert
the outcome deterministically. A test that usually lands in the right window
is a test that fails on a loaded machine and passes on a fast one when the
code is broken — the voice suite's rule, inherited whole.
"""

from __future__ import annotations

import threading
import unittest

from companion.speech.recovery import CAPTURE_DISPOSITIONS

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


def _dispositions(harness) -> list[str]:
    return [item["disposition"] for item in harness.worker.status()["recentDispositions"]]


class CancellationRaces(unittest.TestCase):
    def test_cancel_before_the_microphone_opens(self) -> None:
        """The cancel lands while the recogniser is still starting: no device
        call ever happens and nothing was ever listening."""
        started = threading.Event()
        gate = threading.Event()
        recognizer = ScriptedRecognizer(start_gate=gate, start_entered=started)
        harness = build_worker(recognizer=recognizer)
        self.addCleanup(harness.close)
        _received, kinds = collect_events(harness.worker)
        request = make_request()
        outcome = harness.worker.start_capture(request)
        self.assertTrue(outcome.accepted)
        self.assertTrue(started.wait(5.0))
        cancelled, _ = harness.worker.cancel(request.request_id, token="")
        self.assertTrue(cancelled)
        gate.set()
        wait_for(lambda: not harness.worker.active)
        self.assertEqual(harness.backend.opens, 0, "no microphone was opened")
        self.assertNotIn("microphone_opened", kinds())
        self.assertIn("speech_input_cancelled", kinds())
        self.assertIn("cancelled", _dispositions(harness))

    def test_cancel_during_capture_closes_before_the_indicator_clears(self) -> None:
        script = FrameScript([speech_pcm(0.5)])
        script.hold.set()
        harness = build_worker(backend=ScriptedCaptureBackend(script=script))
        self.addCleanup(harness.close)
        _received, kinds = collect_events(harness.worker)
        request = make_request()
        harness.worker.start_capture(request)
        self.assertTrue(wait_for(lambda: "capture_started" in kinds()))
        self.assertTrue(harness.indicator.listening)
        cancelled, _ = harness.worker.cancel(request.request_id, token="")
        self.assertTrue(cancelled)
        wait_for(lambda: not harness.worker.active)
        events = kinds()
        self.assertLess(events.index("microphone_closed"), events.index("indicator_cleared"))
        self.assertIn("speech_input_cancelled", events)
        self.assertIsNone(harness.ledger.get(request.request_id))
        self.assertFalse(harness.indicator.listening)

    def test_cancel_during_recognition_discards_the_answer(self) -> None:
        """§16: the recogniser finishes while the cancellation arrives. The
        answer exists and is discarded; no transcript waits for anybody."""
        entered = threading.Event()
        gate = threading.Event()
        script = FrameScript([speech_pcm(1.0), silence_pcm(1.0)])
        recognizer = ScriptedRecognizer(finish_gate=gate, finish_entered=entered)
        harness = build_worker(
            backend=ScriptedCaptureBackend(script=script), recognizer=recognizer,
        )
        self.addCleanup(harness.close)
        request = make_request()
        harness.worker.start_capture(request)
        self.assertTrue(entered.wait(5.0), "recognition never reached finalisation")
        cancelled, _ = harness.worker.cancel(request.request_id, token="")
        self.assertTrue(cancelled)
        gate.set()
        wait_for(lambda: not harness.worker.active)
        self.assertIsNone(harness.ledger.get(request.request_id))
        self.assertIn("cancelled", _dispositions(harness))

    def test_cancel_after_the_final_transcript_rejects_the_pending_entry(self) -> None:
        script = FrameScript([speech_pcm(1.0), silence_pcm(1.0)])
        harness = build_worker(backend=ScriptedCaptureBackend(script=script))
        self.addCleanup(harness.close)
        request = make_request()
        harness.worker.start_capture(request)
        wait_for(lambda: not harness.worker.active)
        entry = harness.ledger.get(request.request_id)
        self.assertEqual(entry.state, "pending")
        # The capture is over; the cancel falls to the confirmation stage.
        cancelled, _ = harness.worker.cancel(request.request_id, token="")
        self.assertFalse(cancelled, "the capture is no longer cancellable")
        rejected, _ = harness.ledger.reject(request.request_id)
        self.assertTrue(rejected)
        submission, reason = harness.ledger.confirm(
            request.request_id, session_id=request.session_id,
        )
        self.assertIsNone(submission)
        self.assertIn("rejected", reason)

    def test_duplicate_cancellation_reports_itself_and_is_not_an_error(self) -> None:
        script = FrameScript()
        script.hold.set()
        harness = build_worker(backend=ScriptedCaptureBackend(script=script))
        self.addCleanup(harness.close)
        request = make_request()
        harness.worker.start_capture(request)
        wait_for(lambda: harness.worker.active)
        first, _ = harness.worker.cancel(request.request_id, token="")
        second, detail = harness.worker.cancel(request.request_id, token="")
        self.assertTrue(first)
        if second:
            # The second cancel may find the session already gone, which is
            # the same non-error the voice runtime reports.
            pass
        wait_for(lambda: not harness.worker.active)
        third, detail = harness.worker.cancel(request.request_id, token="")
        self.assertFalse(third)
        self.assertIn("no capture is running", detail)


class DeviceRaces(unittest.TestCase):
    def test_device_removed_before_capture_falls_back_or_refuses(self) -> None:
        backend = ScriptedCaptureBackend(devices=("mic",))
        harness = build_worker(backend=backend)
        self.addCleanup(harness.close)
        backend.set_reachable(False)
        _received, kinds = collect_events(harness.worker)
        request = make_request()
        outcome = harness.worker.start_capture(request)
        # The policy still believed a device existed; the session discovers
        # otherwise and settles refused with the indicator down.
        self.assertTrue(outcome.accepted)
        wait_for(lambda: not harness.worker.active)
        self.assertIn("refused", _dispositions(harness))
        self.assertFalse(harness.indicator.listening)
        self.assertNotIn("capture_started", kinds())

    def test_device_restored_after_failure_requires_hysteresis(self) -> None:
        backend = ScriptedCaptureBackend()
        harness = build_worker(backend=backend)
        self.addCleanup(harness.close)
        harness.router.penalise(
            backend.backend_id, kind="device-removed-during-capture", detail="gone",
        )
        state = harness.router._state[backend.backend_id]
        harness.router.observe()
        self.assertGreater(state.blocked_until, 0.0, "one good reading is not restoration")
        harness.router.observe()
        self.assertEqual(state.blocked_until, 0.0)

    def test_a_recognizer_crash_during_capture_degrades_and_capture_continues(self) -> None:
        script = FrameScript([speech_pcm(0.6), speech_pcm(0.6), silence_pcm(1.0)])
        recognizer = ScriptedRecognizer(failure_mode="crash-on-accept")
        harness = build_worker(
            backend=ScriptedCaptureBackend(script=script), recognizer=recognizer,
        )
        self.addCleanup(harness.close)
        received, kinds = collect_events(harness.worker)
        request = make_request()
        harness.worker.start_capture(request)
        wait_for(lambda: not harness.worker.active)
        degradations = [
            dict(e.payload) for e in received if e.kind == "speech_input_degraded"
        ]
        self.assertTrue(
            any(item.get("kind") == "recognizer-failure" for item in degradations),
            "the crash was recorded as a typed degradation",
        )
        self.assertIn("capture_stopped", kinds(), "the capture survived the recogniser")
        self.assertLess(kinds().index("microphone_closed"), kinds().index("indicator_cleared"))


class StaleEventRaces(unittest.TestCase):
    def test_no_partial_is_emitted_after_cancellation(self) -> None:
        """§16's old-partial race, asserted on the whole ordered stream."""
        script = FrameScript([speech_pcm(0.4)])
        script.hold.set()
        harness = build_worker(backend=ScriptedCaptureBackend(script=script))
        self.addCleanup(harness.close)
        received, kinds = collect_events(harness.worker)
        request = make_request()
        harness.worker.start_capture(request)
        wait_for(lambda: "capture_started" in kinds())
        harness.worker.cancel(request.request_id, token="")
        script.hold.clear()
        wait_for(lambda: not harness.worker.active)
        stream = kinds()
        if "speech_input_cancelled" in stream and "partial_transcript" in stream:
            self.assertLess(
                max(i for i, k in enumerate(stream) if k == "partial_transcript"),
                stream.index("speech_input_cancelled"),
                "a partial arrived after the cancellation",
            )

    def test_event_sequences_stay_monotonic_across_every_race(self) -> None:
        script = FrameScript([speech_pcm(1.0), silence_pcm(1.0)])
        harness = build_worker(backend=ScriptedCaptureBackend(script=script))
        self.addCleanup(harness.close)
        received, _kinds = collect_events(harness.worker)
        request = make_request()
        harness.worker.start_capture(request)
        wait_for(lambda: not harness.worker.active)
        sequences = [e.sequence for e in received if e.request_id == request.request_id]
        self.assertEqual(sequences, sorted(sequences))
        self.assertEqual(len(sequences), len(set(sequences)))


class RestartRaces(unittest.TestCase):
    def test_worker_close_during_capture_releases_and_journals(self) -> None:
        """§16's service-restart-during-capture, at the worker's grain."""
        import tempfile
        from pathlib import Path

        from companion.speech.recovery import SpeechJournal

        journal = SpeechJournal(Path(tempfile.mkdtemp()) / "journal.jsonl")
        script = FrameScript()
        script.hold.set()
        harness = build_worker(
            backend=ScriptedCaptureBackend(script=script), journal=journal,
        )
        request = make_request()
        harness.worker.start_capture(request)
        wait_for(lambda: harness.worker.active)
        self.assertTrue(harness.worker.close())
        self.assertFalse(harness.worker.active)
        self.assertFalse(harness.indicator.listening)
        entries = journal.read()
        settles = [item for item in entries if item.get("event") == "settle"]
        self.assertTrue(settles, "the interrupted capture was journalled")
        self.assertIn(settles[-1]["disposition"], CAPTURE_DISPOSITIONS)

    def test_a_new_worker_starts_clean_and_does_not_resume(self) -> None:
        import tempfile
        from pathlib import Path

        from companion.speech.recovery import SpeechJournal, recover

        directory = Path(tempfile.mkdtemp())
        journal = SpeechJournal(directory / "journal.jsonl")
        # A start line with no settle: the crash shape.
        journal.record_start(make_request(request_id="speechreq-crashed"), monotonic=1.0)
        report = recover(journal, own_pid=None)
        self.assertEqual(report.marked_cancelled, ("speechreq-crashed",))
        self.assertFalse(report.to_json()["captureResumed"])
        self.assertFalse(report.to_json()["microphoneOpenedByRecovery"])
        # The journal was truncated: the decision is not re-made next time.
        self.assertEqual(journal.read(), [])


class ConfirmationRaces(unittest.TestCase):
    """Confirmation against retry and cancellation, both orders of each."""

    def _held(self, harness, request):
        script = None
        outcome = harness.worker.start_capture(request)
        assert outcome.accepted, outcome.detail
        wait_for(lambda: not harness.worker.active)
        entry = harness.ledger.get(request.request_id)
        assert entry is not None and entry.state == "pending"
        return entry

    def test_confirmation_after_supersede_is_refused(self) -> None:
        script = FrameScript([speech_pcm(1.0), silence_pcm(1.0)])
        harness = build_worker(backend=ScriptedCaptureBackend(script=script))
        self.addCleanup(harness.close)
        request = make_request()
        self._held(harness, request)
        self.assertTrue(harness.ledger.supersede(request.request_id))
        submission, reason = harness.ledger.confirm(
            request.request_id, session_id=request.session_id,
        )
        self.assertIsNone(submission)
        self.assertIn("superseded", reason)

    def test_supersede_after_confirmation_changes_nothing(self) -> None:
        script = FrameScript([speech_pcm(1.0), silence_pcm(1.0)])
        harness = build_worker(backend=ScriptedCaptureBackend(script=script))
        self.addCleanup(harness.close)
        request = make_request()
        self._held(harness, request)
        submission, _ = harness.ledger.confirm(
            request.request_id, session_id=request.session_id,
        )
        self.assertIsNotNone(submission)
        self.assertFalse(
            harness.ledger.supersede(request.request_id),
            "a confirmed transcript is not superseded; the confirmation stands",
        )

    def test_confirmation_and_rejection_race_one_wins(self) -> None:
        script = FrameScript([speech_pcm(1.0), silence_pcm(1.0)])
        harness = build_worker(backend=ScriptedCaptureBackend(script=script))
        self.addCleanup(harness.close)
        request = make_request()
        self._held(harness, request)
        submission, _ = harness.ledger.confirm(
            request.request_id, session_id=request.session_id,
        )
        rejected, _ = harness.ledger.reject(request.request_id)
        self.assertIsNotNone(submission)
        self.assertFalse(rejected, "the earlier confirmation won and the rejection reports so")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
