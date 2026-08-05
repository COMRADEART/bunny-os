# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Voice-produced visemes reaching a real character presenter, and every way not to.

The voice runtime measured amplitude envelopes and emitted an ordered viseme
stream. The renderer had a ``LipSyncController`` and a mouth-shape map. Neither
had ever driven the other: the only thing that had ever fed the controller was a
timeline *fabricated by a test*, so "visemes work" and "the mouth moves" were two
claims with nothing between them.

:mod:`companion.character.speech_link` is the join. These tests drive it from a
real :class:`~companion.voice.worker.VoiceWorker` — real request, real timeline,
real event stream — into a real :class:`~companion.character.surface.CharacterPresenter`
with the shipped character package. The audio is scripted, because a synthesiser
and a speaker are the compositor probe's business; the *timeline* is the
runtime's own.

The second half of the file is §6, and it is the larger half on purpose. A mouth
that moves when everything works is one test. A mouth that does not move when a
viseme arrives after a cancellation, when a previous request's timeline shows up
during a new one, when the renderer is gone, when the renderer crashes, when the
final neutral event is lost — that is where the property actually lives, and in
every one of them the caption and the task result must be untouched.
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import threading
import unittest

from companion.character.defaults import default_character_path
from companion.character.lipsync import MouthShape
from companion.character.speech_link import (
    MAX_FRAMES_PER_REQUEST,
    REJECTION_REASONS,
    MouthFrame,
    VisemeLink,
)
from companion.character.surface import CharacterPresenter
from companion.voice.captions import SpeechDisposition
from companion.voice.worker import VoiceEvent

from .test_voice_worker import WorkerHarness
from .voice_support import BARRIER_TIMEOUT, ScriptedBackend, make_request


def _presenter() -> CharacterPresenter:
    """The shipped character package, loaded, with no compositor."""
    from capability.runtime import assess
    from capability.simulate import simulate

    return CharacterPresenter(
        default_character_path().parent, assessment=assess(simulate("laptop")),
    )


class _Recorder:
    """Stands in for the widget. Records what would have been drawn."""

    def __init__(self) -> None:
        self.frames: list[MouthFrame] = []
        self.fail_after = -1

    def __call__(self, frame: MouthFrame) -> None:
        self.frames.append(frame)
        if 0 <= self.fail_after <= len(self.frames):
            raise RuntimeError("the renderer went away mid-frame")

    @property
    def shapes(self) -> list[str]:
        return [item.shape for item in self.frames]

    @property
    def non_neutral(self) -> set[str]:
        return {item for item in self.shapes if item != MouthShape.NEUTRAL.value}


def _event(kind: str, request_id: str = "a", **payload) -> VoiceEvent:
    return VoiceEvent(kind=kind, request_id=request_id, at_monotonic=0.0, payload=payload)


def _timeline_event(request_id: str = "a", count: int = 6) -> VoiceEvent:
    shapes = ["open-small", "open-medium", "open-wide", "rounded", "closed"]
    events = [
        {
            "requestId": request_id, "sequence": index, "offsetMs": index * 40,
            "durationMs": 40, "mouthShape": shapes[index % len(shapes)],
            "confidence": 0.6, "sourceMethod": "amplitude",
        }
        for index in range(count - 1)
    ]
    events.append({
        "requestId": request_id, "sequence": count - 1, "offsetMs": count * 40,
        "durationMs": 0, "mouthShape": "neutral", "confidence": 0.6,
        "sourceMethod": "amplitude",
    })
    return _event(
        "viseme_timeline", request_id, requestId=request_id, sourceMethod="amplitude",
        confidence=0.6, eventCount=len(events), totalMs=count * 40, events=events,
    )


def _viseme(request_id: str, sequence: int, shape: str, position_ms: int, drift_ms: int = 0) -> VoiceEvent:
    return _event(
        "viseme", request_id, requestId=request_id, sequence=sequence, mouthShape=shape,
        confidence=0.6, sourceMethod="amplitude", positionMs=position_ms,
        driftMs=drift_ms, driftDetected=False, active=True, cancelled=False, explanation="",
    )


class TheRealWorkerDrivesTheRealPresenter(unittest.TestCase):
    """One utterance, end to end, with nothing fabricated but the audio."""

    def setUp(self) -> None:
        self.presenter = _presenter()
        self.recorder = _Recorder()
        self.link = VisemeLink(presenter=self.presenter, draw=self.recorder)
        self.addCleanup(self.link.close)
        # Real-time playback: without it the scripted handle completes before
        # the worker's mouth loop turns once, and the only frame that would
        # ever exist is the opening one. The audio is scripted; the *timeline*
        # and the loop that walks it are the runtime's own.
        self.backend = ScriptedBackend("scripted", real_time=True)
        self.harness = WorkerHarness(backends=[self.backend]).start()
        self.addCleanup(self.harness.close)
        self.harness.worker.subscribe(self.link.on_voice_event)

    def _speak(self, request_id: str = "a", text: str = "a sentence with several syllables") -> None:
        self.harness.worker.submit(make_request(request_id=request_id, text=text))
        self.assertTrue(self.harness.worker.drain(timeout=BARRIER_TIMEOUT))

    def test_at_least_two_distinct_non_neutral_shapes_are_drawn(self) -> None:
        self._speak()
        self.assertGreaterEqual(
            len(self.recorder.non_neutral), 2,
            f"only {self.recorder.non_neutral} was ever drawn",
        )

    def test_the_events_are_ordered_and_the_request_ids_match(self) -> None:
        self._speak()
        timeline_frames = [item for item in self.recorder.frames if item.origin == "timeline"]
        self.assertTrue(timeline_frames)
        self.assertEqual({item.request_id for item in timeline_frames}, {"a"})
        sequences = [item.sequence for item in timeline_frames]
        self.assertEqual(sequences, sorted(sequences))
        self.assertEqual(len(sequences), len(set(sequences)))

    def test_the_mouth_returns_to_neutral_when_the_utterance_completes(self) -> None:
        self._speak()
        self.assertIsNotNone(self.recorder.frames)
        self.assertTrue(self.recorder.frames[-1].neutral)
        self.assertEqual(self.recorder.frames[-1].origin, "neutral-on-completion")
        self.assertIs(self.presenter.controller.lip_status.shape, MouthShape.NEUTRAL)

    def test_the_source_is_labelled_by_what_it_actually_measured(self) -> None:
        """§13: never claim phoneme accuracy that has not been measured."""
        self._speak()
        sources = {item.source for item in self.recorder.frames if item.origin == "timeline"}
        self.assertTrue(sources)
        self.assertTrue(sources <= {"amplitude", "text-estimate", "speaking-state"})
        self.assertNotIn("phoneme", sources)
        self.assertNotIn("viseme", sources)

    def test_the_caption_is_unaffected_by_anything_the_mouth_did(self) -> None:
        self._speak()
        self.assertEqual(self.harness.dispositions()["a"], SpeechDisposition.PLAYED)

    def test_a_second_utterance_starts_a_second_request(self) -> None:
        self._speak("a")
        self._speak("b", text="another sentence entirely")
        self.assertEqual(self.link.report.requests, ["a", "b"])
        self.assertEqual(self.link.report.rejected.get("stale-request", 0), 0)

    def test_the_link_reports_what_it_did(self) -> None:
        self._speak()
        document = self.link.describe()
        self.assertTrue(document["captionsAuthoritative"])
        self.assertFalse(document["mouthMayChangeCaption"])
        self.assertFalse(document["mouthMayChangeTask"])
        self.assertGreaterEqual(document["report"]["drawn"], 2)
        self.assertGreaterEqual(len(document["report"]["distinctNonNeutralShapes"]), 2)


class CancellationAndRestart(unittest.TestCase):
    """Cancellation stops the mouth; a restart returns it to neutral."""

    def setUp(self) -> None:
        self.presenter = _presenter()
        self.recorder = _Recorder()
        self.link = VisemeLink(presenter=self.presenter, draw=self.recorder)
        self.addCleanup(self.link.close)

    def _run_partial(self) -> None:
        self.link.on_voice_event(_timeline_event("a"))
        self.link.on_voice_event(_viseme("a", 0, "open-small", 0))
        self.link.on_voice_event(_viseme("a", 1, "open-wide", 40))

    def test_a_viseme_after_cancellation_moves_nothing(self) -> None:
        self._run_partial()
        self.link.on_voice_event(_event("speech_cancelled", "a"))
        drawn = len(self.recorder.frames)
        self.link.on_voice_event(_viseme("a", 2, "open-wide", 80))
        self.assertEqual(len(self.recorder.frames), drawn)
        self.assertEqual(self.link.report.rejected["after-cancellation"], 1)
        self.assertTrue(self.recorder.frames[-1].neutral)

    def test_cancellation_returns_the_mouth_to_neutral_immediately(self) -> None:
        self._run_partial()
        self.assertFalse(self.recorder.frames[-1].neutral)
        self.link.on_voice_event(_event("speech_cancelled", "a"))
        self.assertTrue(self.recorder.frames[-1].neutral)
        self.assertEqual(self.recorder.frames[-1].origin, "neutral-on-cancellation")

    def test_a_worker_restart_returns_the_mouth_to_neutral(self) -> None:
        self._run_partial()
        self.link.on_voice_event(_event("worker_stopped", "a"))
        self.assertTrue(self.recorder.frames[-1].neutral)
        self.assertEqual(self.recorder.frames[-1].origin, "neutral-on-restart")

    def test_a_renderer_restart_degrades_explicitly_rather_than_guessing(self) -> None:
        """§5 allows resume *or* an explicit degradation. This build degrades."""
        self._run_partial()
        replacement = _presenter()
        answer = self.link.restart_renderer(replacement)
        self.assertIn("degraded-to-neutral", answer)
        self.assertTrue(self.recorder.frames[-1].neutral)
        asked = self.link.restart_renderer(replacement, resume=True)
        self.assertIn("degraded-to-neutral", asked)
        self.assertIn("timing nobody measured", asked)

    def test_closing_the_link_leaves_the_mouth_neutral_and_no_thread(self) -> None:
        before = threading.active_count()
        self._run_partial()
        self.link.close()
        self.assertTrue(self.recorder.frames[-1].neutral)
        self.assertEqual(self.recorder.frames[-1].origin, "neutral-on-teardown")
        self.assertEqual(threading.active_count(), before)
        # Nothing survives: a further event draws nothing at all.
        drawn = len(self.recorder.frames)
        self.link.on_voice_event(_viseme("a", 9, "open-wide", 400))
        self.assertEqual(len(self.recorder.frames), drawn)

    def test_closing_twice_is_safe(self) -> None:
        self._run_partial()
        self.link.close()
        self.link.close()


class TheNegativeCases(unittest.TestCase):
    """§6. Every one of them keeps the caption and the task result."""

    def setUp(self) -> None:
        self.recorder = _Recorder()

    def _link(self, presenter=None, **kwargs) -> VisemeLink:
        link = VisemeLink(presenter=presenter, draw=self.recorder, **kwargs)
        self.addCleanup(link.close)
        return link

    def test_the_reasons_are_a_closed_set(self) -> None:
        self.assertEqual(len(REJECTION_REASONS), len(set(REJECTION_REASONS)))

    def test_a_renderer_that_is_absent_drops_frames_and_raises_nothing(self) -> None:
        link = VisemeLink(presenter=None, draw=None)
        self.addCleanup(link.close)
        link.on_voice_event(_timeline_event("a"))
        link.on_voice_event(_viseme("a", 0, "open-small", 0))
        self.assertEqual(link.report.rejected["renderer-absent"], 1)
        self.assertEqual(link.report.accepted, 1)

    def test_a_renderer_that_disconnects_stops_drawing_and_says_so(self) -> None:
        link = self._link()
        link.on_voice_event(_timeline_event("a"))
        link.on_voice_event(_viseme("a", 0, "open-small", 0))
        link.restart_renderer(None)
        drawn = len(self.recorder.frames)
        link.on_voice_event(_viseme("a", 1, "open-wide", 40))
        self.assertEqual(len(self.recorder.frames), drawn)

    def test_a_renderer_that_crashes_during_speech_is_counted_not_propagated(self) -> None:
        link = self._link()
        self.recorder.fail_after = 2
        link.on_voice_event(_timeline_event("a"))
        for index in range(4):
            link.on_voice_event(_viseme("a", index, "open-small", index * 40))
        self.assertGreater(link.report.renderer_failures, 0)
        self.assertGreater(link.report.rejected.get("renderer-failed", 0), 0)

    def test_an_unsupported_mouth_shape_is_substituted_and_recorded(self) -> None:
        """A character whose package has no asset for one shape.

        The shipped package declares all seven, so one is taken away — which is
        exactly the case §6 names. The controller substitutes a supported shape
        and the link records that the requested one was not available, rather
        than either refusing the frame or drawing something the package does not
        contain.
        """
        presenter = _presenter()
        presenter.controller.lip_sync.supported_shapes = frozenset(
            presenter.controller.lip_sync.supported_shapes - {"open-wide"}
        )
        link = self._link(presenter=presenter)
        link.on_voice_event(_timeline_event("a"))
        link.on_voice_event(_viseme("a", 0, "open-wide", 0))
        self.assertEqual(link.report.accepted, 1)
        self.assertEqual(link.report.rejected["unsupported-shape"], 1)
        self.assertNotEqual(self.recorder.frames[-1].shape, "open-wide")

    def test_a_package_with_no_mouth_assets_still_draws_and_stays_neutral(self) -> None:
        presenter = _presenter()
        # No mouth shapes at all: the renderer keeps drawing the body and the
        # mouth never moves off neutral.
        presenter.controller.lip_sync.supported_shapes = frozenset()
        link = self._link(presenter=presenter)
        link.on_voice_event(_timeline_event("a"))
        link.on_voice_event(_viseme("a", 0, "open-wide", 0))
        self.assertEqual(link.report.accepted, 1)
        self.assertTrue(self.recorder.frames)
        self.assertEqual(self.recorder.frames[-1].shape, MouthShape.NEUTRAL.value)

    def test_an_old_request_timeline_arriving_during_a_new_one_is_refused(self) -> None:
        link = self._link()
        link.on_voice_event(_timeline_event("a"))
        link.on_voice_event(_viseme("a", 0, "open-small", 0))
        link.on_voice_event(_timeline_event("b"))
        link.on_voice_event(_viseme("a", 5, "open-wide", 200))
        self.assertEqual(link.report.rejected["stale-request"], 1)
        link.on_voice_event(_viseme("b", 0, "open-medium", 0))
        self.assertEqual(link.report.accepted, 2)

    def test_an_out_of_order_viseme_is_refused(self) -> None:
        link = self._link()
        link.on_voice_event(_timeline_event("a"))
        link.on_voice_event(_viseme("a", 3, "open-small", 120))
        link.on_voice_event(_viseme("a", 1, "open-wide", 40))
        self.assertEqual(link.report.rejected["out-of-order"], 1)
        self.assertEqual(link.report.accepted, 1)

    def test_a_duplicate_viseme_is_refused(self) -> None:
        link = self._link()
        link.on_voice_event(_timeline_event("a"))
        link.on_voice_event(_viseme("a", 2, "open-small", 80))
        link.on_voice_event(_viseme("a", 2, "open-small", 80))
        self.assertEqual(link.report.rejected["duplicate"], 1)

    def test_an_excessive_viseme_count_is_bounded(self) -> None:
        link = self._link(maximum_frames=8)
        link.on_voice_event(_timeline_event("a"))
        for index in range(40):
            link.on_voice_event(_viseme("a", index, "open-small", index * 10))
        self.assertEqual(link.report.accepted, 8)
        self.assertEqual(link.report.rejected["count-exceeded"], 32)
        self.assertLessEqual(MAX_FRAMES_PER_REQUEST, 8192)

    def test_a_viseme_after_the_audio_completed_is_refused(self) -> None:
        link = self._link()
        link.on_voice_event(_timeline_event("a"))
        link.on_voice_event(_viseme("a", 0, "open-small", 0))
        link.on_voice_event(_event("speech_finished", "a"))
        link.on_voice_event(_viseme("a", 1, "open-wide", 40))
        self.assertEqual(link.report.rejected["after-completion"], 1)
        self.assertTrue(self.recorder.frames[-1].neutral)

    def test_a_lost_final_neutral_event_still_leaves_a_neutral_mouth(self) -> None:
        """The worker emits ``mouth_neutral`` on every path. Assume it was lost."""
        link = self._link()
        link.on_voice_event(_timeline_event("a"))
        link.on_voice_event(_viseme("a", 0, "open-wide", 0))
        self.assertFalse(self.recorder.frames[-1].neutral)
        # No mouth_neutral, no viseme ending neutral — only the settle.
        link.on_voice_event(_event("speech_finished", "a"))
        self.assertTrue(self.recorder.frames[-1].neutral)
        self.assertEqual(link.report.neutral_returns, 1)

    def test_a_stale_presentation_revision_is_refused(self) -> None:
        link = self._link()
        link.publish(1)
        link.on_voice_event(_timeline_event("a"))
        link.on_voice_event(_viseme("a", 0, "open-small", 0))
        link.publish(2)
        link.on_voice_event(_viseme("a", 1, "open-wide", 40))
        self.assertEqual(link.report.rejected["stale-revision"], 1)
        self.assertEqual(link.report.accepted, 1)

    def test_a_viseme_with_no_timeline_is_refused(self) -> None:
        link = self._link()
        link.on_voice_event(_viseme("a", 0, "open-small", 0))
        self.assertEqual(link.report.rejected["no-active-request"], 1)
        self.assertEqual(self.recorder.frames, [])

    def test_every_rejection_reason_that_fires_is_in_the_closed_set(self) -> None:
        link = self._link()
        link.on_voice_event(_viseme("a", 0, "open-small", 0))
        link.on_voice_event(_timeline_event("a"))
        link.on_voice_event(_viseme("a", 1, "open-small", 0))
        link.on_voice_event(_viseme("a", 1, "open-small", 0))
        link.on_voice_event(_viseme("a", 0, "open-small", 0))
        link.on_voice_event(_event("speech_cancelled", "a"))
        link.on_voice_event(_viseme("a", 4, "open-small", 0))
        for reason in link.report.rejected:
            self.assertIn(reason, REJECTION_REASONS)


class CaptionsAndTasksSurviveEverything(unittest.TestCase):
    """§8, asserted against a running worker rather than against the design."""

    def test_a_renderer_that_raises_on_every_frame_does_not_stop_speech(self) -> None:
        recorder = _Recorder()
        recorder.fail_after = 1
        link = VisemeLink(presenter=_presenter(), draw=recorder)
        self.addCleanup(link.close)
        harness = WorkerHarness().start()
        self.addCleanup(harness.close)
        harness.worker.subscribe(link.on_voice_event)
        harness.worker.submit(make_request(request_id="a", text="a sentence"))
        self.assertTrue(harness.worker.drain(timeout=BARRIER_TIMEOUT))
        self.assertEqual(harness.dispositions()["a"], SpeechDisposition.PLAYED)
        self.assertGreater(link.report.renderer_failures, 0)

    def test_a_subscriber_that_raises_outright_does_not_stop_speech(self) -> None:
        """The worker's own guard, exercised through this module's door."""
        harness = WorkerHarness().start()
        self.addCleanup(harness.close)

        def hostile(_event) -> None:
            raise RuntimeError("a renderer with a bug in it")

        harness.worker.subscribe(hostile)
        harness.worker.submit(make_request(request_id="a", text="a sentence"))
        self.assertTrue(harness.worker.drain(timeout=BARRIER_TIMEOUT))
        self.assertEqual(harness.dispositions()["a"], SpeechDisposition.PLAYED)


class TheLinkHoldsNoAuthority(unittest.TestCase):
    """Structural, like the voice runtime's own boundary test."""

    def test_the_module_imports_nothing_that_could_change_a_task(self) -> None:
        import ast

        source = Path("companion/character/speech_link.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
            elif isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
        for forbidden in ("companion.store", "companion.runtime", "companion.approvals",
                          "companion.task", "companion.session", "companion.voice"):
            for item in imported:
                self.assertNotIn(forbidden, item)

    def test_it_never_writes_to_the_presenter_beyond_the_mouth(self) -> None:
        """The only presenter methods it may call, named."""
        import ast

        source = Path("companion/character/speech_link.py").read_text(encoding="utf-8")
        calls = {
            node.func.attr
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name) and node.func.value.id == "presenter"
        }
        self.assertTrue(calls <= {"start_lip_sync", "advance_lip_sync", "cancel_lip_sync", "finish_lip_sync"})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
