# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The listening link: posture, never the mouth; decoration, never authority."""

from __future__ import annotations

from dataclasses import dataclass
import unittest

from companion.character.listening_link import ListeningLink, ListeningPosture

from .speech_support import (
    FrameScript,
    ScriptedCaptureBackend,
    build_worker,
    make_request,
    silence_pcm,
    speech_pcm,
    wait_for,
)


@dataclass
class _Event:
    kind: str
    request_id: str = "speechreq-1"
    sequence: int = 0


class PostureMapping(unittest.TestCase):
    def setUp(self) -> None:
        self.drawn: list[ListeningPosture] = []
        self.link = ListeningLink(draw=self.drawn.append)

    def _feed(self, *kinds: str) -> None:
        for index, kind in enumerate(kinds, start=1):
            self.link.on_speech_event(_Event(kind=kind, sequence=index))

    def test_the_capture_lifecycle_walks_the_postures(self) -> None:
        self._feed(
            "microphone_indicator_raised", "microphone_opened", "capture_started",
            "speech_detected", "capture_stopped", "recognition_finalizing",
            "final_transcript", "transcript_confirmation_requested",
            "transcript_confirmed",
        )
        postures = [item.posture for item in self.drawn]
        self.assertEqual(postures, ["listening", "transcribing", "waiting-for-user", "neutral"])
        self.assertEqual(self.link.report.neutral_returns, 1)

    def test_partials_are_not_the_renderers_business(self) -> None:
        self._feed("capture_started")
        before = len(self.drawn)
        self.link.on_speech_event(_Event(kind="partial_transcript", sequence=2))
        self.assertEqual(len(self.drawn), before)

    def test_cancellation_and_device_loss_return_to_neutral(self) -> None:
        for terminal in ("speech_input_cancelled", "device_lost", "recognition_failed"):
            with self.subTest(terminal=terminal):
                drawn: list[ListeningPosture] = []
                link = ListeningLink(draw=drawn.append)
                link.on_speech_event(_Event(kind="capture_started", sequence=1))
                link.on_speech_event(_Event(kind=terminal, sequence=2))
                self.assertEqual(drawn[-1].posture, "neutral")

    def test_a_posture_for_a_settled_request_is_refused_by_name(self) -> None:
        self._feed("capture_started", "speech_input_cancelled")
        self.link.on_speech_event(_Event(kind="speech_detected", sequence=9))
        self.assertEqual(self.link.report.rejected.get("after-settled", 0), 1)

    def test_out_of_order_events_are_refused(self) -> None:
        self.link.on_speech_event(_Event(kind="capture_started", sequence=5))
        self.link.on_speech_event(_Event(kind="speech_detected", sequence=3))
        self.assertEqual(self.link.report.rejected.get("out-of-order", 0), 1)

    def test_a_new_request_takes_the_link_over(self) -> None:
        self.link.on_speech_event(_Event(kind="capture_started", request_id="speechreq-a", sequence=1))
        self.link.on_speech_event(_Event(kind="capture_started", request_id="speechreq-b", sequence=1))
        self.assertEqual(self.link.describe()["requestId"], "speechreq-b")
        # The old request's late event is stale, not applied.
        self.link.on_speech_event(_Event(kind="speech_input_cancelled", request_id="speechreq-a", sequence=2))
        self.assertGreaterEqual(self.link.report.rejected.get("stale-request", 0), 1)


class RendererFailureIsNotACaptureFailure(unittest.TestCase):
    def test_a_broken_draw_is_counted_and_swallowed(self) -> None:
        def _broken(_posture: ListeningPosture) -> None:
            raise RuntimeError("the widget is gone")

        link = ListeningLink(draw=_broken)
        link.on_speech_event(_Event(kind="capture_started", sequence=1))
        self.assertEqual(link.report.renderer_failures, 1)

    def test_an_absent_renderer_still_validates_and_counts(self) -> None:
        link = ListeningLink()
        link.on_speech_event(_Event(kind="capture_started", sequence=1))
        self.assertEqual(link.report.rejected.get("renderer-absent", 0), 1)
        self.assertEqual(link.report.applied, 1)

    def test_gtk_restart_mid_capture_resets_to_neutral_and_capture_survives(self) -> None:
        """§16's GTK-restart race, at the link's grain and the worker's."""
        script = FrameScript([speech_pcm(1.0), silence_pcm(1.0)])
        harness = build_worker(backend=ScriptedCaptureBackend(script=script))
        self.addCleanup(harness.close)
        drawn: list[ListeningPosture] = []
        link = ListeningLink(draw=drawn.append)
        harness.worker.subscribe(link.on_speech_event)
        request = make_request()
        harness.worker.start_capture(request)
        wait_for(lambda: any(item.posture == "listening" for item in drawn))
        # The renderer dies and is replaced mid-capture.
        replacement: list[ListeningPosture] = []
        self.assertEqual(link.restart_renderer(replacement.append), "reset-to-neutral")
        wait_for(lambda: not harness.worker.active)
        # The capture finished on its own terms…
        self.assertIsNotNone(harness.ledger.get(request.request_id))
        # …and the new renderer received postures after the restart.
        self.assertTrue(replacement)

    def test_close_is_neutral_then_nothing(self) -> None:
        drawn: list[ListeningPosture] = []
        link = ListeningLink(draw=drawn.append)
        link.on_speech_event(_Event(kind="capture_started", sequence=1))
        link.close()
        self.assertEqual(drawn[-1].posture, "neutral")
        link.on_speech_event(_Event(kind="speech_detected", sequence=2))
        self.assertEqual(link.report.rejected.get("link-closed", 0), 1)

    def test_the_link_disclaims_the_mouth_in_its_own_description(self) -> None:
        link = ListeningLink()
        described = link.describe()
        self.assertFalse(described["drivesLipSync"])
        self.assertTrue(described["textIndicatorAuthoritative"])
        self.assertFalse(described["rendererFailureStopsCapture"])
        self.assertFalse(link.report.to_json()["lipSyncDriven"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
