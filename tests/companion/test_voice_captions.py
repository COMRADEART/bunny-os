# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""§21 "Captions and visemes": the caption is the output, the mouth is honest."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from companion.character.lipsync import LIP_SYNC_SOURCES, LipSyncController, MouthShape
from companion.clock import FrozenClock
from companion.ids import SequentialIds
from companion.voice.captions import (
    Caption,
    CaptionLedger,
    SpeechDisposition,
    SyncMeasurement,
    TOLERANCES,
    caption_from_state,
)
from companion.voice.pcm import PcmError, amplitude_envelope, probe_wav
from companion.voice.request import Priority
from companion.voice.visemes import (
    MAX_VISEME_EVENTS,
    SOURCE_CONFIDENCE,
    VisemeScheduler,
    estimated_duration_ms,
    from_amplitude,
    from_phoneme_timing,
    from_provider_timing,
    from_text,
    speaking_state,
    timeline_for,
)

from .voice_support import make_request, presentation, write_wav

from .support import temporary_root


class CaptionAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ledger = CaptionLedger(ids=SequentialIds(), clock=FrozenClock())

    def test_the_caption_comes_from_the_projection_and_is_not_composed(self) -> None:
        state = presentation(result_summary="There are forty-two words in your note.")
        caption = caption_from_state(state, caption_id="cap-1")
        self.assertEqual(caption.text, "There are forty-two words in your note.")
        self.assertTrue(caption.final)
        self.assertEqual(caption.revision, state.revision)

    def test_an_approval_outranks_an_error_outranks_a_result(self) -> None:
        """The same order the speech bubble applies, so the two agree."""
        approval = caption_from_state(
            presentation(
                phase="waiting_for_approval", approval_state="pending",
                status_text="May I publish the notice?",
            ),
            caption_id="c",
        )
        self.assertIn("publish", approval.text)
        self.assertFalse(approval.final)

        error = caption_from_state(
            presentation(phase="error", error_summary="the tool refused"), caption_id="c"
        )
        self.assertEqual(error.text, "the tool refused")
        self.assertTrue(error.final)

    def test_the_voice_runtime_cannot_invent_the_response(self) -> None:
        """A projection with nothing to say produces nothing to speak."""
        state = presentation(phase="idle", status_text="", result_summary="")
        caption = caption_from_state(state, caption_id="c")
        self.assertFalse(caption.speakable)
        request, reason = self.ledger.speak_once(caption)
        self.assertIsNone(request)
        self.assertIn("no text", reason)

    def test_speech_is_derived_from_the_caption_and_refers_back_to_it(self) -> None:
        caption = self.ledger.publish(presentation())
        request, reason = self.ledger.speak_once(caption)
        self.assertIsNotNone(request)
        self.assertEqual(request.caption_reference, caption.caption_id)
        self.assertEqual(request.presentation_revision, caption.revision)
        self.assertIn("forty-two", request.speech_text)

    def test_publishing_the_same_projection_twice_is_one_caption(self) -> None:
        state = presentation()
        first = self.ledger.publish(state)
        second = self.ledger.publish(state)
        self.assertEqual(first.caption_id, second.caption_id)

    def test_a_changed_projection_is_a_new_caption(self) -> None:
        first = self.ledger.publish(presentation(revision=1, result_summary="one"))
        second = self.ledger.publish(presentation(revision=2, result_summary="two"))
        self.assertNotEqual(first.caption_id, second.caption_id)

    def test_a_partial_caption_is_marked_non_final(self) -> None:
        caption = self.ledger.publish(
            presentation(phase="working", status_text="Counting.", result_summary="")
        )
        self.assertFalse(caption.final)
        self.assertTrue(caption.speakable)

    def test_the_ledger_never_returns_caption_text_in_its_description(self) -> None:
        self.ledger.publish(presentation())
        described = self.ledger.describe()
        self.assertNotIn("forty-two", repr(described))
        self.assertTrue(described["captionsAuthoritative"])
        self.assertFalse(described["voiceMayComposeText"])


class ReplayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ledger = CaptionLedger(ids=SequentialIds(), clock=FrozenClock())

    def test_a_spoken_caption_is_not_spoken_again(self) -> None:
        caption = self.ledger.publish(presentation())
        request, _ = self.ledger.speak_once(caption)
        self.ledger.record_disposition(caption.caption_id, request.request_id, SpeechDisposition.PLAYED)
        again, reason = self.ledger.speak_once(caption)
        self.assertIsNone(again)
        self.assertIn("already been spoken", reason)

    def test_an_interrupted_caption_is_also_not_replayed(self) -> None:
        """§20: interrupted is *heard*. Repeating it is the runtime deciding for you."""
        caption = self.ledger.publish(presentation())
        request, _ = self.ledger.speak_once(caption)
        self.ledger.record_disposition(
            caption.caption_id, request.request_id, SpeechDisposition.INTERRUPTED
        )
        again, reason = self.ledger.speak_once(caption)
        self.assertIsNone(again)

    def test_a_failed_utterance_leaves_the_caption_speakable(self) -> None:
        """A machine that could not speak has not spoken; asking again is fair."""
        caption = self.ledger.publish(presentation())
        request, _ = self.ledger.speak_once(caption)
        self.ledger.record_disposition(
            caption.caption_id, request.request_id, SpeechDisposition.FAILED
        )
        again, reason = self.ledger.speak_once(caption)
        self.assertIsNotNone(again, reason)

    def test_an_explicit_replay_is_permitted_and_is_a_new_request(self) -> None:
        caption = self.ledger.publish(presentation())
        first, _ = self.ledger.speak_once(caption)
        self.ledger.record_disposition(caption.caption_id, first.request_id, SpeechDisposition.PLAYED)
        second, reason = self.ledger.speak_once(caption, force=True)
        self.assertIsNotNone(second, reason)
        self.assertNotEqual(second.request_id, first.request_id)

    def test_repeated_identical_text_is_coalesced_before_it_reaches_the_queue(self) -> None:
        one = self.ledger.publish(presentation(revision=1, phase="working", status_text="Counting.", result_summary=""))
        two = self.ledger.publish(presentation(revision=2, phase="working", status_text="Counting.", result_summary=""))
        self.assertNotEqual(one.caption_id, two.caption_id)
        first, _ = self.ledger.speak_once(one)
        second, reason = self.ledger.speak_once(two)
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertIn("coalesced", reason)

    def test_releasing_a_request_lets_the_same_words_be_said_later(self) -> None:
        one = self.ledger.publish(presentation(revision=1, phase="working", status_text="Counting.", result_summary=""))
        first, _ = self.ledger.speak_once(one)
        self.ledger.release(first.request_id)
        two = self.ledger.publish(presentation(revision=2, phase="working", status_text="Counting.", result_summary=""))
        second, reason = self.ledger.speak_once(two)
        self.assertIsNotNone(second, reason)

    def test_an_unknown_disposition_cannot_be_recorded(self) -> None:
        with self.assertRaises(ValueError):
            self.ledger.record_disposition("cap-1", "speech-1", "spoke_fine")


class SynchronisationTests(unittest.TestCase):
    """§14: the offsets that are measured, and what counts as out of tolerance."""

    def measurement(self, **changes) -> SyncMeasurement:
        base = dict(
            request_id="speech-1", caption_id="cap-1",
            caption_shown_at=100.0, speech_requested_at=100.0,
            synthesis_started_at=100.05, synthesis_finished_at=100.3,
            audio_started_at=100.35, first_viseme_at=100.36,
            audio_finished_at=102.0, neutral_at=102.05,
            caption_finalised_at=102.1, viseme_source="amplitude",
        )
        base.update(changes)
        return SyncMeasurement(**base)

    def test_a_well_behaved_utterance_is_within_every_tolerance(self) -> None:
        measurement = self.measurement()
        self.assertTrue(measurement.within_tolerance, measurement.violations())
        self.assertEqual(measurement.caption_to_audio_ms, 350)
        self.assertEqual(measurement.viseme_to_audio_ms, 10)

    def test_audio_before_the_caption_is_a_violation(self) -> None:
        """§8: the caption is shown before or with the speech, never after."""
        measurement = self.measurement(caption_shown_at=100.5)
        self.assertFalse(measurement.within_tolerance)
        self.assertIn("must never trail", " ".join(measurement.violations()))

    def test_a_caption_far_ahead_of_the_audio_is_a_violation(self) -> None:
        measurement = self.measurement(audio_started_at=105.0)
        self.assertFalse(measurement.within_tolerance)
        self.assertIn("led the audio", " ".join(measurement.violations()))

    def test_a_mouth_out_of_step_with_the_sound_is_a_violation(self) -> None:
        measurement = self.measurement(first_viseme_at=100.9)
        self.assertFalse(measurement.within_tolerance)
        self.assertIn("from the audio", " ".join(measurement.violations()))

    def test_a_mouth_that_stays_moving_after_the_audio_is_a_violation(self) -> None:
        measurement = self.measurement(neutral_at=103.0)
        self.assertFalse(measurement.within_tolerance)
        self.assertIn("return to neutral", " ".join(measurement.violations()))

    def test_an_unmeasured_offset_is_never_counted_as_a_pass(self) -> None:
        """A missing reading must not average in as a perfect score."""
        measurement = self.measurement(caption_shown_at=None, first_viseme_at=None)
        self.assertIsNone(measurement.caption_to_audio_ms)
        self.assertIsNone(measurement.viseme_to_audio_ms)
        self.assertTrue(measurement.within_tolerance)
        document = measurement.to_json()
        self.assertIsNone(document["captionToAudioMs"])

    def test_the_tolerances_are_stated_and_labelled_as_development_figures(self) -> None:
        document = TOLERANCES.to_json()
        self.assertEqual(document["visemeOffsetMaximumMs"], 120)
        self.assertIn("no physical speaker", document["environment"])

    def test_the_ledger_records_the_zero_point_a_client_reports(self) -> None:
        ledger = CaptionLedger(ids=SequentialIds(), clock=FrozenClock())
        caption = ledger.publish(presentation())
        request, _ = ledger.speak_once(caption)
        ledger.mark_shown(caption.caption_id, monotonic=500.0)
        measurement = ledger.measurement(request.request_id)
        self.assertEqual(measurement.caption_shown_at, 500.0)


class VisemeSourceTests(unittest.TestCase):
    """§13: every event says how its timing was arrived at, and never overclaims."""

    def test_the_renderer_vocabulary_covers_every_source_this_module_uses(self) -> None:
        self.assertEqual(set(SOURCE_CONFIDENCE), set(LIP_SYNC_SOURCES))

    def test_confidence_orders_measurement_above_estimate_above_guess(self) -> None:
        self.assertGreater(SOURCE_CONFIDENCE["amplitude"], SOURCE_CONFIDENCE["text-estimate"])
        self.assertGreater(SOURCE_CONFIDENCE["text-estimate"], SOURCE_CONFIDENCE["speaking-state"])
        self.assertGreater(SOURCE_CONFIDENCE["phoneme"], SOURCE_CONFIDENCE["amplitude"])

    def test_provider_native_timing_refuses_rather_than_fabricating(self) -> None:
        with self.assertRaises(NotImplementedError) as caught:
            from_provider_timing("speech-1", [])
        self.assertIn("unmeasured accuracy", str(caught.exception))

    def test_phoneme_timing_refuses_because_no_provider_emits_boundaries(self) -> None:
        with self.assertRaises(NotImplementedError) as caught:
            from_phoneme_timing("speech-1", [])
        self.assertIn("without times", str(caught.exception))


class VisemeTimelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = temporary_root(self)

    def test_amplitude_timing_is_derived_from_the_samples_that_will_be_played(self) -> None:
        path = write_wav(self.directory / "speech.wav", seconds=0.6)
        probe = probe_wav(path)
        envelope = amplitude_envelope(probe)
        timeline = from_amplitude(
            "speech-1", envelope, total_ms=int(probe.duration_seconds * 1000),
            sample_rate=probe.sample_rate,
        )
        self.assertEqual(timeline.source, "amplitude")
        self.assertIn("root-mean-square", timeline.derivation)
        self.assertIn("22050 Hz", timeline.derivation)
        shapes = {event.shape for event in timeline.events}
        self.assertGreater(len(shapes), 1, "a varying waveform must move the mouth")

    def test_a_silent_file_produces_a_closed_mouth_rather_than_a_moving_one(self) -> None:
        path = write_wav(self.directory / "silent.wav", seconds=0.3, shape="silent")
        probe = probe_wav(path)
        timeline = from_amplitude("speech-1", amplitude_envelope(probe), total_ms=300)
        shapes = {event.shape for event in timeline.events}
        self.assertLessEqual(shapes, {MouthShape.CLOSED, MouthShape.NEUTRAL})

    def test_text_timing_is_labelled_an_estimate(self) -> None:
        timeline = from_text("speech-1", "hello there, the answer is six", total_ms=1500)
        self.assertEqual(timeline.source, "text-estimate")
        self.assertAlmostEqual(timeline.confidence, 0.35)
        self.assertIn("a measured 1500 ms", timeline.derivation)

    def test_text_timing_says_so_when_the_duration_was_estimated_too(self) -> None:
        timeline = from_text("speech-1", "hello there")
        self.assertIn("an estimated", timeline.derivation)

    def test_bilabials_close_the_mouth_and_rounded_vowels_round_it(self) -> None:
        timeline = from_text("speech-1", "mob", total_ms=300)
        shapes = [event.shape for event in timeline.events]
        self.assertIn(MouthShape.CLOSED, shapes)
        self.assertIn(MouthShape.ROUNDED, shapes)

    def test_a_smile_is_never_generated_as_a_viseme(self) -> None:
        """It is an expression; the canonical phase drives it, not the sound."""
        for timeline in (
            from_text("speech-1", "a happy sentence indeed", total_ms=900),
            speaking_state("speech-1", total_ms=900),
        ):
            self.assertNotIn(MouthShape.SMILE, [event.shape for event in timeline.events])

    def test_every_event_carries_the_fields_the_specification_names(self) -> None:
        timeline = from_text("speech-1", "hello there", total_ms=600)
        document = timeline.events[0].to_json()
        for field in (
            "requestId", "sequence", "offsetMs", "durationMs",
            "mouthShape", "confidence", "sourceMethod",
        ):
            self.assertIn(field, document, f"§13 requires {field}")

    def test_offsets_are_ordered_and_sequences_are_consecutive(self) -> None:
        timeline = from_text("speech-1", "the quick brown fox jumps over", total_ms=2000)
        offsets = [event.offset_ms for event in timeline.events]
        self.assertEqual(offsets, sorted(offsets))
        self.assertEqual(
            [event.sequence for event in timeline.events], list(range(len(timeline.events)))
        )

    def test_every_timeline_ends_neutral(self) -> None:
        for timeline in (
            from_text("speech-1", "some words here", total_ms=800),
            speaking_state("speech-1", total_ms=800),
            from_amplitude("speech-1", [(0, 0.9), (40, 0.1)], total_ms=80),
        ):
            self.assertIs(timeline.events[-1].shape, MouthShape.NEUTRAL)

    def test_the_event_count_is_bounded(self) -> None:
        timeline = from_text("speech-1", "ab " * 1300, total_ms=60_000)
        self.assertLessEqual(len(timeline.events), MAX_VISEME_EVENTS)

    def test_consecutive_identical_shapes_are_merged(self) -> None:
        """A mouth told to re-enter the shape it is in restarts its animation."""
        timeline = from_amplitude("speech-1", [(index * 40, 0.9) for index in range(20)], total_ms=800)
        self.assertEqual(len(timeline.events), 2)

    def test_the_renderer_event_type_is_produced_without_it_knowing_this_module(self) -> None:
        timeline = from_text("speech-1", "hello there", total_ms=600)
        events = timeline.lipsync_events()
        controller = LipSyncController(supported_shapes=[item.value for item in MouthShape])
        status = controller.start(events)
        self.assertTrue(status.active)

    def test_the_ladder_takes_the_best_evidence_available(self) -> None:
        request = make_request()
        with_samples = timeline_for(request, envelope=[(0, 0.9), (40, 0.2)], audio_seconds=0.08)
        self.assertEqual(with_samples.source, "amplitude")
        without = timeline_for(request, envelope=None, audio_seconds=1.2)
        self.assertEqual(without.source, "text-estimate")

    def test_the_estimated_duration_follows_the_synthesiser_s_own_pace(self) -> None:
        self.assertGreater(estimated_duration_ms("one two three four five"), 1000)
        self.assertLess(
            estimated_duration_ms("one two three four five", rate=2.0),
            estimated_duration_ms("one two three four five"),
        )
        self.assertGreaterEqual(estimated_duration_ms("hi"), 300)


class VisemeSchedulerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.timeline = from_text("speech-1", "the answer is forty two words", total_ms=2000)
        self.scheduler = VisemeScheduler()

    def test_the_mouth_starts_neutral_and_advances_in_order(self) -> None:
        frame = self.scheduler.start(self.timeline)
        self.assertIs(frame.shape, MouthShape.NEUTRAL)
        seen = []
        for position in range(0, 2100, 100):
            seen.append(self.scheduler.advance(position, audio_clock_ms=position).shape)
        self.assertGreater(len(set(seen)), 1)
        self.assertIs(seen[-1], MouthShape.NEUTRAL)

    def test_the_mouth_returns_to_neutral_when_the_timeline_completes(self) -> None:
        self.scheduler.start(self.timeline)
        frame = self.scheduler.advance(5000, audio_clock_ms=5000)
        self.assertIs(frame.shape, MouthShape.NEUTRAL)
        self.assertFalse(frame.active)

    def test_cancellation_returns_the_mouth_to_neutral(self) -> None:
        self.scheduler.start(self.timeline)
        self.scheduler.advance(400, audio_clock_ms=400)
        frame = self.scheduler.cancel("the user cancelled")
        self.assertIs(frame.shape, MouthShape.NEUTRAL)
        self.assertTrue(frame.cancelled)
        self.assertFalse(frame.active)

    def test_a_single_drifting_reading_is_tolerated(self) -> None:
        self.scheduler.start(self.timeline)
        frame = self.scheduler.advance(400, audio_clock_ms=900)
        self.assertTrue(frame.drift_detected)
        self.assertEqual(frame.source, "text-estimate")

    def test_sustained_drift_degrades_to_speaking_state_rather_than_lying(self) -> None:
        """§14: when synchronisation cannot be held, the mouth stops claiming to."""
        self.scheduler.start(self.timeline)
        frame = None
        for index in range(3):
            frame = self.scheduler.advance(400 + index, audio_clock_ms=900 + index)
        self.assertTrue(self.scheduler.degraded)
        self.assertEqual(self.scheduler.timeline.source, "speaking-state")
        self.assertIn("degraded to speaking-state", frame.explanation)

    def test_a_degraded_scheduler_still_ends_neutral(self) -> None:
        self.scheduler.start(self.timeline)
        for index in range(4):
            self.scheduler.advance(400 + index, audio_clock_ms=900 + index)
        frame = self.scheduler.finish()
        self.assertIs(frame.shape, MouthShape.NEUTRAL)

    def test_a_renderer_restart_resets_the_mouth_without_replaying_the_utterance(self) -> None:
        """Replaying from zero would run the whole mouth against the end of the audio."""
        self.scheduler.start(self.timeline)
        self.scheduler.advance(1200, audio_clock_ms=1200)
        index_before = self.scheduler.index
        frame = self.scheduler.reset_for_renderer_restart()
        self.assertIs(frame.shape, MouthShape.NEUTRAL)
        self.assertEqual(self.scheduler.index, index_before)
        self.assertTrue(self.scheduler.active)

    def test_advancing_with_no_timeline_is_not_an_error(self) -> None:
        frame = self.scheduler.advance(100)
        self.assertFalse(frame.active)
        self.assertIs(frame.shape, MouthShape.NEUTRAL)

    def test_a_negative_position_is_refused(self) -> None:
        self.scheduler.start(self.timeline)
        with self.assertRaises(ValueError):
            self.scheduler.advance(-1)


class PcmTests(unittest.TestCase):
    """The artifact check that turns "exit 0" into "there is audio"."""

    def setUp(self) -> None:
        self.directory = temporary_root(self)

    def test_a_missing_file_is_reported_rather_than_raising_an_os_error(self) -> None:
        with self.assertRaises(PcmError) as caught:
            probe_wav(self.directory / "absent.wav")
        self.assertIn("no file", str(caught.exception))

    def test_an_empty_file_is_not_audio(self) -> None:
        target = self.directory / "empty.wav"
        target.write_bytes(b"")
        with self.assertRaises(PcmError):
            probe_wav(target)

    def test_a_file_that_is_not_a_wav_is_refused(self) -> None:
        target = self.directory / "nonsense.wav"
        target.write_bytes(b"this is not a RIFF header at all")
        with self.assertRaises(PcmError):
            probe_wav(target)

    def test_a_wav_with_no_frames_is_refused(self) -> None:
        """The eSpeak NG empty-input case, which exits zero and writes a header."""
        import wave

        target = self.directory / "headeronly.wav"
        with wave.open(str(target), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(22_050)
            handle.writeframes(b"")
        with self.assertRaises(PcmError) as caught:
            probe_wav(target)
        self.assertIn("no audio frames", str(caught.exception))

    def test_a_valid_file_reports_what_is_in_it(self) -> None:
        path = write_wav(self.directory / "good.wav", seconds=0.5, sample_rate=22_050)
        probe = probe_wav(path)
        self.assertEqual(probe.sample_rate, 22_050)
        self.assertEqual(probe.channels, 1)
        self.assertAlmostEqual(probe.duration_seconds, 0.5, places=2)
        self.assertFalse(probe.silent)

    def test_eight_bit_audio_is_centred_before_it_is_measured(self) -> None:
        """Unsigned PCM measured from zero would read as constantly loud."""
        path = write_wav(self.directory / "eight.wav", seconds=0.3, sample_width=1, shape="silent")
        envelope = amplitude_envelope(probe_wav(path))
        self.assertTrue(all(level < 0.5 for _, level in envelope), envelope[:4])

    def test_the_envelope_is_bounded_for_a_long_utterance(self) -> None:
        path = write_wav(self.directory / "long.wav", seconds=30.0)
        envelope = amplitude_envelope(probe_wav(path), maximum_windows=64)
        self.assertLessEqual(len(envelope), 70)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
