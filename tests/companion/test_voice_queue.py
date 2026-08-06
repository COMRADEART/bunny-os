# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""§21 "Queue": priority, interruption, coalescing, supersession, bounds, drops."""

from __future__ import annotations

import unittest

from companion.voice.captions import SpeechDisposition
from companion.voice.policy import VoiceDecision, VoicePreferences, VoiceSignals, evaluate
from companion.voice.queue import SpeechQueue
from companion.voice.request import InterruptionPolicy, Priority

from .voice_support import make_request


def speaking_decision(minimum: Priority = Priority.DECORATIVE) -> VoiceDecision:
    return VoiceDecision(
        outcome="local-neural-or-system-voice",
        eligible="local-neural-or-system-voice",
        minimum_priority=minimum,
    )


class OrderingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.queue = SpeechQueue()
        self.decision = speaking_decision()

    def _submit(self, **kwargs):
        return self.queue.submit(make_request(**kwargs), decision=self.decision)

    def test_the_most_urgent_utterance_is_served_first(self) -> None:
        # One task each, so ordering is tested on its own: an error for the same
        # task would supersede that task's narration before ordering mattered.
        self._submit(request_id="a", task_id="task-1", text="progress one", priority=Priority.PROGRESS_UPDATE)
        self._submit(request_id="b", task_id="task-2", text="an error", priority=Priority.TASK_ERROR)
        self._submit(request_id="c", task_id="task-3", text="a warning", priority=Priority.CRITICAL_WARNING)
        self.assertEqual(
            [self.queue.pop().request.request_id for _ in range(3)], ["c", "b", "a"]
        )

    def test_equal_ranks_are_served_in_arrival_order(self) -> None:
        for index in range(4):
            self._submit(request_id=f"p{index}", text=f"progress {index}", priority=Priority.PROGRESS_UPDATE)
        self.assertEqual(
            [self.queue.pop().request.request_id for _ in range(4)],
            ["p0", "p1", "p2", "p3"],
        )

    def test_an_empty_queue_pops_nothing_rather_than_raising(self) -> None:
        self.assertIsNone(self.queue.pop())


class CoalescingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.queue = SpeechQueue()
        self.decision = speaking_decision()

    def test_identical_progress_text_is_said_once(self) -> None:
        first = self.queue.submit(
            make_request(request_id="a", text="still counting"), decision=self.decision
        )
        second = self.queue.submit(
            make_request(request_id="b", text="still counting"), decision=self.decision
        )
        self.assertTrue(first.accepted)
        self.assertFalse(second.accepted)
        self.assertEqual(second.disposition, SpeechDisposition.COALESCED)
        self.assertEqual(len(self.queue), 1)

    def test_the_same_words_for_a_different_task_are_not_coalesced(self) -> None:
        self.queue.submit(
            make_request(request_id="a", task_id="task-1", text="still counting"),
            decision=self.decision,
        )
        outcome = self.queue.submit(
            make_request(request_id="b", task_id="task-2", text="still counting"),
            decision=self.decision,
        )
        self.assertTrue(outcome.accepted)

    def test_words_being_spoken_right_now_are_coalesced(self) -> None:
        speaking = make_request(request_id="a", text="still counting")
        outcome = self.queue.submit(
            make_request(request_id="b", text="still counting"),
            decision=self.decision, speaking=speaking,
        )
        self.assertEqual(outcome.disposition, SpeechDisposition.COALESCED)

    def test_coalescing_releases_once_the_utterance_leaves_the_queue(self) -> None:
        """Otherwise the same status can never be said twice in a long task."""
        self.queue.submit(make_request(request_id="a", text="still counting"), decision=self.decision)
        self.queue.pop()
        outcome = self.queue.submit(
            make_request(request_id="b", text="still counting"), decision=self.decision
        )
        self.assertTrue(outcome.accepted)


class SupersessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.queue = SpeechQueue()
        self.decision = speaking_decision()

    def test_a_result_supersedes_this_task_s_queued_narration(self) -> None:
        self.queue.submit(
            make_request(request_id="p1", text="reading the note", priority=Priority.PROGRESS_UPDATE),
            decision=self.decision,
        )
        self.queue.submit(
            make_request(request_id="p2", text="counting the words", priority=Priority.PROGRESS_UPDATE),
            decision=self.decision,
        )
        outcome = self.queue.submit(
            make_request(request_id="r", text="forty-two words", priority=Priority.TASK_RESULT),
            decision=self.decision,
        )
        self.assertTrue(outcome.accepted)
        self.assertEqual(
            sorted(name for name, _ in outcome.displaced), ["p1", "p2"]
        )
        self.assertTrue(
            all(value == SpeechDisposition.SUPERSEDED for _, value in outcome.displaced)
        )
        self.assertEqual(len(self.queue), 1)
        self.assertEqual(self.queue.pop().request.request_id, "r")

    def test_a_result_does_not_supersede_another_task_s_narration(self) -> None:
        self.queue.submit(
            make_request(request_id="p1", task_id="task-2", text="reading", priority=Priority.PROGRESS_UPDATE),
            decision=self.decision,
        )
        outcome = self.queue.submit(
            make_request(request_id="r", task_id="task-1", text="done", priority=Priority.TASK_RESULT),
            decision=self.decision,
        )
        self.assertEqual(outcome.displaced, ())
        self.assertEqual(len(self.queue), 2)

    def test_a_result_does_not_supersede_an_error(self) -> None:
        """An error outranks a result and is not narration; it stays."""
        self.queue.submit(
            make_request(request_id="e", text="a step failed", priority=Priority.TASK_ERROR),
            decision=self.decision,
        )
        outcome = self.queue.submit(
            make_request(request_id="r", text="done anyway", priority=Priority.TASK_RESULT),
            decision=self.decision,
        )
        self.assertEqual(outcome.displaced, ())
        self.assertEqual(len(self.queue), 2)

    def test_an_error_also_retires_narration_that_is_no_longer_true(self) -> None:
        """A terminal outcome, not only a successful one.

        Narrating "counting the words" after "that failed" tells the user
        something that has stopped being true, and the caption for the progress
        line is still on screen either way.
        """
        self.queue.submit(
            make_request(request_id="p", text="counting the words", priority=Priority.PROGRESS_UPDATE),
            decision=self.decision,
        )
        outcome = self.queue.submit(
            make_request(request_id="e", text="that step failed", priority=Priority.TASK_ERROR),
            decision=self.decision,
        )
        self.assertEqual(outcome.displaced, (("p", SpeechDisposition.SUPERSEDED),))

    def test_an_interjection_does_not_discard_narration_that_is_still_true(self) -> None:
        """A warning and an approval interrupt; the task carries on, so they do not supersede.

        This is the case that caught the rule being written too widely: a
        critical warning had been emptying the queue of lines that were still
        accurate, because it merely outranked a result.
        """
        for index in range(3):
            self.queue.submit(
                make_request(
                    request_id=f"p{index}", text=f"step {index}",
                    priority=Priority.PROGRESS_UPDATE,
                ),
                decision=self.decision,
            )
        for request_id, priority in (
            ("w", Priority.CRITICAL_WARNING),
            ("k", Priority.APPROVAL_REQUIRED),
        ):
            outcome = self.queue.submit(
                make_request(request_id=request_id, text=f"interjection {request_id}", priority=priority),
                decision=self.decision,
            )
            self.assertEqual(outcome.displaced, (), f"{priority.wire} discarded live narration")
        self.assertEqual(len(self.queue), 5)


class BoundTests(unittest.TestCase):
    def test_the_queue_is_bounded_and_drops_its_least_urgent_entry(self) -> None:
        queue = SpeechQueue(maximum_depth=3)
        decision = speaking_decision()
        for index in range(3):
            queue.submit(
                make_request(
                    request_id=f"d{index}", text=f"decoration {index}",
                    priority=Priority.DECORATIVE,
                ),
                decision=decision,
            )
        self.assertEqual(len(queue), 3)
        outcome = queue.submit(
            make_request(request_id="w", text="a warning", priority=Priority.CRITICAL_WARNING),
            decision=decision,
        )
        self.assertTrue(outcome.accepted)
        self.assertEqual(len(queue), 3)
        self.assertEqual(outcome.displaced, (("d2", SpeechDisposition.DROPPED),))

    def test_a_full_queue_of_urgent_things_refuses_a_less_urgent_one(self) -> None:
        queue = SpeechQueue(maximum_depth=2)
        decision = speaking_decision()
        for index in range(2):
            queue.submit(
                make_request(
                    request_id=f"w{index}", text=f"warning {index}",
                    priority=Priority.CRITICAL_WARNING,
                ),
                decision=decision,
            )
        outcome = queue.submit(
            make_request(request_id="d", text="decoration", priority=Priority.DECORATIVE),
            decision=decision,
        )
        self.assertFalse(outcome.accepted)
        self.assertEqual(outcome.disposition, SpeechDisposition.DROPPED)
        self.assertEqual(len(queue), 2)

    def test_an_unbounded_narration_loop_cannot_grow_the_queue(self) -> None:
        """§7: the queue length is bounded, so a runaway emitter is bounded too."""
        queue = SpeechQueue(maximum_depth=4)
        decision = speaking_decision()
        for index in range(500):
            queue.submit(
                make_request(
                    request_id=f"n{index}", text=f"narration {index}",
                    priority=Priority.PROGRESS_UPDATE,
                ),
                decision=decision,
            )
        self.assertLessEqual(len(queue), 4)
        counts = queue.counts()
        self.assertGreater(counts[SpeechDisposition.DROPPED], 400)


class PolicyDropTests(unittest.TestCase):
    def test_speech_below_the_current_floor_is_dropped_with_a_reason(self) -> None:
        queue = SpeechQueue()
        decision = speaking_decision(minimum=Priority.TASK_RESULT)
        outcome = queue.submit(
            make_request(request_id="d", text="a flourish", priority=Priority.DECORATIVE),
            decision=decision,
        )
        self.assertFalse(outcome.accepted)
        self.assertEqual(outcome.disposition, SpeechDisposition.DROPPED)
        self.assertIn("below the current floor", outcome.detail)

    def test_captions_only_degrades_rather_than_drops(self) -> None:
        """The distinction matters: one is 'too chatty', the other is 'no voice'."""
        queue = SpeechQueue()
        decision = VoiceDecision(outcome="captions-only", eligible="captions-only")
        outcome = queue.submit(make_request(), decision=decision)
        self.assertEqual(outcome.disposition, SpeechDisposition.DEGRADED_TO_CAPTIONS)

    def test_drop_below_removes_queued_narration_under_pressure(self) -> None:
        queue = SpeechQueue()
        decision = speaking_decision()
        # A result would have superseded the decoration on its own, so the
        # utterance kept back here is an approval — which is not narration and
        # is above the floor either way.
        queue.submit(make_request(request_id="d", text="a flourish", priority=Priority.DECORATIVE), decision=decision)
        queue.submit(
            make_request(request_id="k", text="may I publish this?", priority=Priority.APPROVAL_REQUIRED),
            decision=decision,
        )
        dropped = queue.drop_below(Priority.TASK_RESULT, reason="the machine is thermally throttled")
        self.assertEqual(dropped, ("d",))
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue.pop().request.request_id, "k")


class DropIfBusyTests(unittest.TestCase):
    def test_drop_if_busy_is_dropped_when_something_is_speaking(self) -> None:
        queue = SpeechQueue()
        outcome = queue.submit(
            make_request(request_id="a", interruption_policy=InterruptionPolicy.DROP_IF_BUSY),
            decision=speaking_decision(),
            speaking=make_request(request_id="z", text="something else"),
        )
        self.assertFalse(outcome.accepted)
        self.assertEqual(outcome.disposition, SpeechDisposition.DROPPED)

    def test_drop_if_busy_is_queued_when_the_floor_is_free(self) -> None:
        queue = SpeechQueue()
        outcome = queue.submit(
            make_request(request_id="a", interruption_policy=InterruptionPolicy.DROP_IF_BUSY),
            decision=speaking_decision(),
        )
        self.assertTrue(outcome.accepted)


class CancellationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.queue = SpeechQueue()
        self.decision = speaking_decision()

    def test_one_queued_utterance_can_be_cancelled(self) -> None:
        self.queue.submit(make_request(request_id="a"), decision=self.decision)
        self.assertTrue(self.queue.cancel("a"))
        self.assertEqual(len(self.queue), 0)
        self.assertIsNone(self.queue.pop())

    def test_a_duplicate_cancellation_is_not_an_error(self) -> None:
        """§19: cancelling twice is a normal thing for a client to do."""
        self.queue.submit(make_request(request_id="a"), decision=self.decision)
        self.assertTrue(self.queue.cancel("a"))
        self.assertFalse(self.queue.cancel("a"))

    def test_a_cancellation_with_the_wrong_token_is_refused(self) -> None:
        self.queue.submit(
            make_request(request_id="a", cancellation_token="cancel-1"), decision=self.decision
        )
        self.assertFalse(self.queue.cancel("a", token="cancel-2"))
        self.assertTrue(self.queue.cancel("a", token="cancel-1"))

    def test_cancelling_a_task_silences_every_utterance_it_owns(self) -> None:
        for index in range(3):
            self.queue.submit(
                make_request(request_id=f"a{index}", task_id="task-1", text=f"line {index}"),
                decision=self.decision,
            )
        self.queue.submit(
            make_request(request_id="other", task_id="task-2", text="unrelated"),
            decision=self.decision,
        )
        cancelled = self.queue.cancel_task("task-1")
        self.assertEqual(sorted(cancelled), ["a0", "a1", "a2"])
        self.assertEqual(len(self.queue), 1)
        self.assertEqual(self.queue.pop().request.task_id, "task-2")


class ExpiryTests(unittest.TestCase):
    def test_an_expired_request_is_refused_at_submission(self) -> None:
        queue = SpeechQueue()
        outcome = queue.submit(
            make_request(expires_at_monotonic=100.0), decision=speaking_decision(), monotonic=200.0
        )
        self.assertEqual(outcome.disposition, SpeechDisposition.EXPIRED)

    def test_an_utterance_that_expires_while_queued_is_skipped_when_popped(self) -> None:
        queue = SpeechQueue()
        queue.submit(
            make_request(request_id="a", expires_at_monotonic=150.0),
            decision=speaking_decision(), monotonic=100.0,
        )
        queue.submit(
            make_request(request_id="b", text="still valid"),
            decision=speaking_decision(), monotonic=100.0,
        )
        entry = queue.pop(monotonic=200.0)
        self.assertIsNotNone(entry)
        self.assertEqual(entry.request.request_id, "b")
        self.assertEqual(queue.counts()[SpeechDisposition.EXPIRED], 1)


class DuplicateTests(unittest.TestCase):
    def test_the_same_id_with_different_words_is_refused(self) -> None:
        queue = SpeechQueue()
        queue.submit(make_request(request_id="a", text="the first thing"), decision=speaking_decision())
        outcome = queue.submit(
            make_request(request_id="a", text="something else entirely"),
            decision=speaking_decision(),
        )
        self.assertFalse(outcome.accepted)
        self.assertIn("already queued under this request id", outcome.detail)

    def test_the_same_id_with_the_same_words_coalesces(self) -> None:
        queue = SpeechQueue()
        queue.submit(make_request(request_id="a", text="the same"), decision=speaking_decision())
        outcome = queue.submit(make_request(request_id="a", text="the same"), decision=speaking_decision())
        self.assertEqual(outcome.disposition, SpeechDisposition.COALESCED)


class LedgerTests(unittest.TestCase):
    def test_every_utterance_ends_with_a_recorded_disposition(self) -> None:
        """§7: played, interrupted, cancelled, superseded, dropped, failed, degraded."""
        queue = SpeechQueue(maximum_depth=2)
        decision = speaking_decision()
        queue.submit(make_request(request_id="p", text="narration", priority=Priority.PROGRESS_UPDATE), decision=decision)
        queue.submit(make_request(request_id="r", text="the result", priority=Priority.TASK_RESULT), decision=decision)
        queue.cancel("r")
        queue.record(make_request(request_id="x", text="something"), SpeechDisposition.PLAYED, "played")
        queue.record(make_request(request_id="y", text="something else"), SpeechDisposition.FAILED, "failed")
        counts = queue.counts()
        self.assertEqual(counts[SpeechDisposition.SUPERSEDED], 1)
        self.assertEqual(counts[SpeechDisposition.CANCELLED], 1)
        self.assertEqual(counts[SpeechDisposition.PLAYED], 1)
        self.assertEqual(counts[SpeechDisposition.FAILED], 1)
        self.assertEqual(set(counts) - set(SpeechDisposition.ALL), set())

    def test_an_unknown_disposition_cannot_be_recorded(self) -> None:
        with self.assertRaises(ValueError):
            SpeechQueue().record(make_request(), "went_fine", "")

    def test_the_ledger_is_bounded(self) -> None:
        queue = SpeechQueue()
        for index in range(3000):
            queue.record(make_request(request_id=f"x{index}", text=f"line {index}"), SpeechDisposition.PLAYED)
        self.assertLessEqual(len(queue.ledger), 1024)


class PolicyLadderTests(unittest.TestCase):
    """§11 and §12, through :func:`companion.voice.policy.evaluate`."""

    def base(self, **changes):
        defaults = dict(
            audio_output_available=True,
            local_provider_available=True,
            synthesis_provider_available=True,
            available_memory_bytes=4 * 1024 ** 3,
            cpu_score=2.0,
        )
        defaults.update(changes)
        return VoiceSignals(**defaults)

    def test_a_capable_machine_gets_the_full_local_voice(self) -> None:
        decision = evaluate(self.base(), VoicePreferences(speak_progress=True))
        self.assertEqual(decision.outcome, "local-neural-or-system-voice")
        self.assertTrue(decision.speaks)

    def test_no_provider_means_captions(self) -> None:
        decision = evaluate(self.base(local_provider_available=False))
        self.assertEqual(decision.outcome, "captions-only")
        self.assertFalse(decision.speaks)

    def test_no_audio_device_means_captions(self) -> None:
        decision = evaluate(self.base(audio_output_available=False))
        self.assertEqual(decision.outcome, "captions-only")

    def test_a_provider_that_keeps_its_samples_is_the_lighter_rung(self) -> None:
        decision = evaluate(self.base(synthesis_provider_available=False))
        self.assertEqual(decision.outcome, "local-lightweight-voice")
        self.assertTrue(decision.prefer_streaming)

    def test_memory_pressure_selects_the_lighter_path(self) -> None:
        decision = evaluate(self.base(available_memory_bytes=100 * 1024 * 1024))
        self.assertEqual(decision.outcome, "local-lightweight-voice")

    def test_severe_memory_pressure_stops_speech(self) -> None:
        decision = evaluate(self.base(available_memory_bytes=32 * 1024 * 1024))
        self.assertEqual(decision.outcome, "captions-only")

    def test_thermal_pressure_disables_decorative_speech(self) -> None:
        decision = evaluate(self.base(thermal_throttled=True), VoicePreferences(speak_decorative=True))
        self.assertTrue(decision.speaks)
        self.assertFalse(decision.permits(Priority.DECORATIVE))
        self.assertTrue(decision.permits(Priority.TASK_RESULT))

    def test_a_critical_battery_suppresses_nonessential_narration(self) -> None:
        decision = evaluate(self.base(on_battery=True, battery_percent=8.0))
        self.assertEqual(decision.outcome, "captions-only")
        low = evaluate(self.base(on_battery=True, battery_percent=20.0))
        self.assertTrue(low.speaks)
        self.assertFalse(low.permits(Priority.TASK_RESULT))
        self.assertTrue(low.permits(Priority.TASK_ERROR))

    def test_foreground_workload_gives_way_to_the_work(self) -> None:
        decision = evaluate(self.base(foreground_workload=3), VoicePreferences(speak_progress=True))
        self.assertFalse(decision.permits(Priority.PROGRESS_UPDATE))
        self.assertEqual(decision.synthesis_concurrency, 1)

    def test_accessibility_keeps_narration_under_pressure(self) -> None:
        preferences = VoicePreferences(accessibility_required=True, speak_progress=True)
        decision = evaluate(self.base(thermal_throttled=True, foreground_workload=4), preferences)
        self.assertTrue(decision.permits(Priority.PROGRESS_UPDATE))
        self.assertFalse(decision.permits(Priority.DECORATIVE))

    def test_a_screen_reader_silences_speech_and_keeps_captions(self) -> None:
        decision = evaluate(self.base(), VoicePreferences(screen_reader_active=True))
        self.assertEqual(decision.outcome, "silent-text-only")
        self.assertFalse(decision.speaks)

    def test_speech_turned_off_is_distinct_from_a_machine_that_cannot(self) -> None:
        off = evaluate(self.base(), VoicePreferences(enabled=False))
        broken = evaluate(self.base(audio_output_available=False))
        self.assertEqual(off.outcome, "silent-text-only")
        self.assertEqual(broken.outcome, "captions-only")

    def test_local_incapability_never_authorises_remote_speech(self) -> None:
        for signals in (
            self.base(local_provider_available=False),
            self.base(audio_output_available=False),
            self.base(available_memory_bytes=1024),
        ):
            self.assertFalse(evaluate(signals).remote_permitted)

    def test_no_named_machine_modes_appear_in_an_outcome(self) -> None:
        """§11 forbids them, so the vocabulary must not contain one."""
        from companion.voice.policy import VOICE_OUTCOMES

        self.assertEqual(
            VOICE_OUTCOMES,
            (
                "local-neural-or-system-voice", "local-lightweight-voice",
                "captions-only", "silent-text-only",
            ),
        )


class HysteresisTests(unittest.TestCase):
    """§12: degradation is immediate, recovery is not."""

    def setUp(self) -> None:
        from companion.voice.policy import VoicePolicy

        self.policy = VoicePolicy(VoicePreferences(speak_progress=True), restore_observations=3)
        self.good = VoiceSignals(
            audio_output_available=True, local_provider_available=True,
            synthesis_provider_available=True, available_memory_bytes=4 * 1024 ** 3,
            cpu_score=2.0,
        )
        self.bad = VoiceSignals(
            audio_output_available=False, local_provider_available=True,
            synthesis_provider_available=True, available_memory_bytes=4 * 1024 ** 3,
            cpu_score=2.0,
        )

    def test_degradation_takes_effect_immediately(self) -> None:
        self.policy.observe(self.good)
        self.assertEqual(self.policy.decision.outcome, "local-neural-or-system-voice")
        self.policy.observe(self.bad)
        self.assertEqual(self.policy.decision.outcome, "captions-only")

    def test_restoration_needs_consecutive_good_readings(self) -> None:
        self.policy.observe(self.good)
        self.policy.observe(self.bad)
        self.policy.observe(self.good)
        self.assertEqual(self.policy.decision.outcome, "captions-only")
        self.policy.observe(self.good)
        self.assertEqual(self.policy.decision.outcome, "captions-only")
        self.policy.observe(self.good)
        self.assertEqual(self.policy.decision.outcome, "local-neural-or-system-voice")

    def test_a_flapping_server_does_not_oscillate_the_outcome(self) -> None:
        # A baseline and then a genuine failure, so what follows is a machine
        # coming and going rather than a first reading.
        self.policy.observe(self.good)
        self.policy.observe(self.bad)
        self.assertEqual(self.policy.decision.outcome, "captions-only")
        outcomes = []
        for index in range(12):
            self.policy.observe(self.good if index % 2 == 0 else self.bad)
            outcomes.append(self.policy.decision.outcome)
        self.assertEqual(set(outcomes), {"captions-only"})

    def test_the_first_reading_is_adopted_without_waiting(self) -> None:
        """The placeholder is not a degradation to climb out of.

        This is the test that caught a good machine needing three refresh cycles
        before it would speak: the policy starts at ``captions-only`` because a
        policy nobody has asked anything must not speak, and the restoration
        hysteresis was treating that as an observed failure.
        """
        from companion.voice.policy import VoicePolicy

        policy = VoicePolicy(VoicePreferences(), restore_observations=3)
        self.assertEqual(policy.decision.outcome, "captions-only")
        policy.observe(self.good)
        self.assertEqual(policy.decision.outcome, "local-neural-or-system-voice")

    def test_a_user_turning_speech_on_does_not_wait_for_hysteresis(self) -> None:
        self.policy.observe(self.good)
        self.policy.set_preferences(VoicePreferences(enabled=False))
        self.policy.observe(self.good)
        self.assertEqual(self.policy.decision.outcome, "silent-text-only")
        self.policy.set_preferences(VoicePreferences(enabled=True, speak_progress=True))
        self.policy.observe(self.good)
        self.assertEqual(self.policy.decision.outcome, "local-neural-or-system-voice")

    def test_transitions_are_recorded_with_their_reasons(self) -> None:
        self.policy.observe(self.good)
        self.policy.observe(self.bad)
        transitions = self.policy.transitions
        self.assertTrue(any(item["kind"] == "degraded" for item in transitions))
        self.assertTrue(any("audio output" in " ".join(item["reasons"]) for item in transitions))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
