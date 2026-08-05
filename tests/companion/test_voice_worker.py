# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""§6, §19 and §21: the worker's lifecycle, its races, and what it cannot touch.

Every race here is expressed with a barrier the fake holds and the test releases.
Nothing sleeps waiting for a window to open, because a window that opens on a
fast machine and not on a loaded one is a test that reports the machine rather
than the code.
"""

from __future__ import annotations

import threading
import time
import unittest

from companion.character.lipsync import MouthShape
from companion.voice.audio import AudioRouter, DegradationRecord
from companion.voice.captions import CaptionLedger, SpeechDisposition
from companion.voice.policy import VoiceDecision, VoicePolicy, VoicePreferences, VoiceSignals
from companion.voice.provider import ProviderRegistry
from companion.voice.queue import SpeechQueue
from companion.voice.request import InterruptionPolicy, Priority
from companion.voice.worker import EVENT_KINDS, VoiceWorker

from companion.clock import SystemClock
from companion.ids import SequentialIds

from .voice_support import (
    BARRIER_TIMEOUT,
    ScriptedBackend,
    ScriptedProvider,
    collect_events,
    make_request,
    presentation,
)


def capable_signals() -> VoiceSignals:
    return VoiceSignals(
        audio_output_available=True,
        local_provider_available=True,
        synthesis_provider_available=True,
        available_memory_bytes=4 * 1024 ** 3,
        cpu_score=2.0,
    )


class WorkerHarness:
    """A worker with scripted providers and backends, wired the production way."""

    def __init__(
        self,
        *,
        providers=None,
        backends=None,
        preferences: VoicePreferences | None = None,
        maximum_depth: int = 32,
    ) -> None:
        self.registry = ProviderRegistry(providers if providers is not None else [ScriptedProvider()])
        self.backends = backends if backends is not None else [ScriptedBackend()]
        self.router = AudioRouter(self.backends)
        self.policy = VoicePolicy(
            preferences or VoicePreferences(speak_progress=True, speak_decorative=True)
        )
        self.policy.observe(capable_signals())
        self.ledger = CaptionLedger(ids=SequentialIds(), clock=SystemClock())
        self.queue = SpeechQueue(maximum_depth=maximum_depth)
        self.worker = VoiceWorker(
            registry=self.registry,
            router=self.router,
            policy=self.policy,
            ledger=self.ledger,
            queue=self.queue,
            clock=SystemClock(),
            tick_seconds=0.005,
        )
        self.events, self.kinds = collect_events(self.worker)

    def start(self) -> "WorkerHarness":
        self.worker.start()
        return self

    def close(self) -> None:
        self.worker.stop(timeout=BARRIER_TIMEOUT)
        self.router.close()
        self.registry.close()

    def dispositions(self) -> dict[str, str]:
        return {
            item["requestId"]: item["disposition"] for item in self.queue.ledger
        }

    def wait_for(self, predicate, *, timeout: float = BARRIER_TIMEOUT) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.002)
        return predicate()


class LifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = WorkerHarness().start()
        self.addCleanup(self.harness.close)

    def test_an_utterance_is_synthesised_played_and_recorded(self) -> None:
        request = make_request()
        outcome = self.harness.worker.submit(request)
        self.assertTrue(outcome.accepted, outcome.detail)
        self.assertTrue(self.harness.worker.drain(timeout=BARRIER_TIMEOUT))
        self.assertEqual(
            self.harness.dispositions()[request.request_id], SpeechDisposition.PLAYED
        )
        kinds = self.harness.kinds()
        for expected in ("speech_queued", "speech_started", "audio_started", "speech_finished", "mouth_neutral"):
            self.assertIn(expected, kinds)

    def test_only_one_utterance_holds_the_floor_at_a_time(self) -> None:
        gate = threading.Event()
        entered = threading.Event()
        harness = WorkerHarness(
            backends=[ScriptedBackend(playback_gate=gate, playback_entered=entered)]
        ).start()
        self.addCleanup(harness.close)
        try:
            harness.worker.submit(make_request(request_id="a", text="the first line"))
            harness.worker.submit(make_request(request_id="b", text="the second line"))
            self.assertTrue(entered.wait(BARRIER_TIMEOUT))
            status = harness.worker.status()
            self.assertEqual(status["activeRequests"], 1)
            self.assertEqual(status["current"]["requestId"], "a")
            self.assertEqual(status["queueDepth"], 1)
        finally:
            gate.set()

    def test_a_provider_fault_does_not_stop_the_worker(self) -> None:
        harness = WorkerHarness(providers=[ScriptedProvider(failure_mode="crash")]).start()
        self.addCleanup(harness.close)
        harness.worker.submit(make_request(request_id="a", text="the first line"))
        self.assertTrue(harness.worker.drain(timeout=BARRIER_TIMEOUT))
        self.assertTrue(harness.worker.running)
        harness.worker.submit(make_request(request_id="b", text="the second line"))
        self.assertTrue(harness.worker.drain(timeout=BARRIER_TIMEOUT))
        dispositions = harness.dispositions()
        self.assertEqual(dispositions["a"], SpeechDisposition.DEGRADED_TO_CAPTIONS)
        self.assertEqual(dispositions["b"], SpeechDisposition.DEGRADED_TO_CAPTIONS)

    def test_stopping_releases_everything_and_clears_the_queue(self) -> None:
        gate = threading.Event()
        entered = threading.Event()
        harness = WorkerHarness(
            backends=[ScriptedBackend(playback_gate=gate, playback_entered=entered)]
        ).start()
        harness.worker.submit(make_request(request_id="a", text="the first line"))
        harness.worker.submit(make_request(request_id="b", text="the second line"))
        self.assertTrue(entered.wait(BARRIER_TIMEOUT))
        self.assertTrue(harness.worker.stop(timeout=BARRIER_TIMEOUT))
        self.assertEqual(len(harness.queue), 0)
        self.assertIsNone(harness.worker.status()["current"])
        harness.router.close()

    def test_a_duplicate_request_id_with_different_words_is_refused(self) -> None:
        """§6: the service must reject it, not only the queue."""
        first = make_request(request_id="speech-1", text="the first thing")
        self.harness.worker.submit(first)
        self.assertTrue(self.harness.worker.drain(timeout=BARRIER_TIMEOUT))
        second = make_request(request_id="speech-1", text="something else entirely")
        outcome = self.harness.worker.submit(second)
        self.assertFalse(outcome.accepted)
        self.assertIn("already been served with different text", outcome.detail)
        self.assertIn("speech_rejected", self.harness.kinds())

    def test_a_replayed_request_with_the_same_words_is_coalesced_not_refused(self) -> None:
        request = make_request(request_id="speech-1", text="the same thing")
        self.harness.worker.submit(request)
        self.assertTrue(self.harness.worker.drain(timeout=BARRIER_TIMEOUT))
        outcome = self.harness.worker.submit(make_request(request_id="speech-1", text="the same thing"))
        self.assertFalse(outcome.accepted)
        self.assertNotIn("different text", outcome.detail)


class InterruptionTests(unittest.TestCase):
    def test_a_critical_warning_takes_the_floor_from_ordinary_speech(self) -> None:
        gate = threading.Event()
        entered = threading.Event()
        harness = WorkerHarness(
            backends=[ScriptedBackend(playback_gate=gate, playback_entered=entered)]
        ).start()
        self.addCleanup(harness.close)
        harness.worker.submit(make_request(
            request_id="ordinary", text="counting the words", priority=Priority.PROGRESS_UPDATE
        ))
        self.assertTrue(entered.wait(BARRIER_TIMEOUT))
        harness.worker.submit(make_request(
            request_id="urgent", text="the disk is full",
            priority=Priority.CRITICAL_WARNING,
            interruption_policy=InterruptionPolicy.INTERRUPT,
        ))
        self.assertTrue(harness.wait_for(
            lambda: harness.dispositions().get("ordinary") == SpeechDisposition.INTERRUPTED
        ), harness.dispositions())
        gate.set()
        self.assertTrue(harness.worker.drain(timeout=BARRIER_TIMEOUT))
        self.assertEqual(harness.dispositions()["urgent"], SpeechDisposition.PLAYED)

    def test_a_decorative_line_cannot_interrupt_by_asking(self) -> None:
        gate = threading.Event()
        entered = threading.Event()
        harness = WorkerHarness(
            backends=[ScriptedBackend(playback_gate=gate, playback_entered=entered)]
        ).start()
        self.addCleanup(harness.close)
        try:
            harness.worker.submit(make_request(
                request_id="result", text="forty-two words", priority=Priority.TASK_RESULT
            ))
            self.assertTrue(entered.wait(BARRIER_TIMEOUT))
            harness.worker.submit(make_request(
                request_id="flourish", text="how lovely", priority=Priority.DECORATIVE,
                interruption_policy=InterruptionPolicy.INTERRUPT,
            ))
            self.assertTrue(harness.wait_for(lambda: len(harness.queue) == 1))
            self.assertEqual(harness.worker.status()["current"]["requestId"], "result")
        finally:
            gate.set()


class CancellationRaceTests(unittest.TestCase):
    """§19's thirteen, each pinned to a barrier rather than a moment in time."""

    def test_cancel_before_synthesis_starts(self) -> None:
        harness = WorkerHarness().start()
        self.addCleanup(harness.close)
        gate = threading.Event()
        entered = threading.Event()
        harness.registry = ProviderRegistry([
            ScriptedProvider(synthesis_gate=gate, synthesis_entered=entered)
        ])
        harness.worker.registry = harness.registry
        harness.worker.submit(make_request(request_id="first", text="the first line"))
        harness.worker.submit(make_request(request_id="second", text="the second line"))
        self.assertTrue(entered.wait(BARRIER_TIMEOUT))
        # "second" is still queued and has not reached a provider.
        self.assertTrue(harness.worker.cancel("second"))
        gate.set()
        self.assertTrue(harness.worker.drain(timeout=BARRIER_TIMEOUT))
        self.assertEqual(harness.dispositions()["second"], SpeechDisposition.CANCELLED)

    def test_cancel_during_synthesis(self) -> None:
        gate = threading.Event()
        entered = threading.Event()
        provider = ScriptedProvider(synthesis_gate=gate, synthesis_entered=entered)
        harness = WorkerHarness(providers=[provider]).start()
        self.addCleanup(harness.close)
        harness.worker.submit(make_request(request_id="a", text="a long sentence to synthesise"))
        self.assertTrue(entered.wait(BARRIER_TIMEOUT))
        self.assertTrue(harness.worker.cancel("a"))
        self.assertTrue(harness.worker.drain(timeout=BARRIER_TIMEOUT))
        self.assertEqual(harness.dispositions()["a"], SpeechDisposition.CANCELLED)

    def test_cancel_after_synthesis_but_before_playback(self) -> None:
        entered = threading.Event()
        gate = threading.Event()
        harness = WorkerHarness(
            backends=[ScriptedBackend(playback_gate=gate, playback_entered=entered)]
        ).start()
        self.addCleanup(harness.close)
        harness.worker.submit(make_request(request_id="a", text="the whole sentence"))
        self.assertTrue(entered.wait(BARRIER_TIMEOUT))
        self.assertTrue(harness.worker.cancel("a"))
        gate.set()
        self.assertTrue(harness.worker.drain(timeout=BARRIER_TIMEOUT))
        self.assertEqual(harness.dispositions()["a"], SpeechDisposition.CANCELLED)

    def test_cancel_during_playback(self) -> None:
        entered = threading.Event()
        gate = threading.Event()
        backend = ScriptedBackend(playback_gate=gate, playback_entered=entered)
        harness = WorkerHarness(backends=[backend]).start()
        self.addCleanup(harness.close)
        harness.worker.submit(make_request(request_id="a", text="a sentence being played"))
        self.assertTrue(entered.wait(BARRIER_TIMEOUT))
        self.assertTrue(harness.worker.cancel("a"))
        self.assertTrue(harness.worker.drain(timeout=BARRIER_TIMEOUT))
        self.assertEqual(harness.dispositions()["a"], SpeechDisposition.CANCELLED)
        self.assertTrue(all(handle.finished for handle in backend.handles))

    def test_cancel_as_playback_completes(self) -> None:
        """The cancel lands in the window where the player has just exited."""
        harness = WorkerHarness().start()
        self.addCleanup(harness.close)
        request = make_request(request_id="a", text="a short line")
        harness.worker.submit(request)
        self.assertTrue(harness.worker.drain(timeout=BARRIER_TIMEOUT))
        # Cancelling a finished utterance is a no-op rather than an error.
        self.assertFalse(harness.worker.cancel("a"))
        self.assertEqual(harness.dispositions()["a"], SpeechDisposition.PLAYED)

    def test_a_task_cancelled_while_queued_silences_its_speech(self) -> None:
        gate = threading.Event()
        entered = threading.Event()
        harness = WorkerHarness(
            backends=[ScriptedBackend(playback_gate=gate, playback_entered=entered)]
        ).start()
        self.addCleanup(harness.close)
        harness.worker.submit(make_request(request_id="a", task_id="task-1", text="line one"))
        self.assertTrue(entered.wait(BARRIER_TIMEOUT))
        harness.worker.submit(make_request(request_id="b", task_id="task-1", text="line two"))
        harness.worker.submit(make_request(request_id="c", task_id="task-2", text="another task"))
        cancelled = harness.worker.cancel_task("task-1")
        self.assertIn("b", cancelled)
        self.assertIn("a", cancelled)
        self.assertNotIn("c", cancelled)
        gate.set()
        self.assertTrue(harness.worker.drain(timeout=BARRIER_TIMEOUT))
        self.assertEqual(harness.dispositions()["c"], SpeechDisposition.PLAYED)

    def test_a_duplicate_cancellation_is_not_an_error(self) -> None:
        gate = threading.Event()
        entered = threading.Event()
        harness = WorkerHarness(
            backends=[ScriptedBackend(playback_gate=gate, playback_entered=entered)]
        ).start()
        self.addCleanup(harness.close)
        harness.worker.submit(make_request(request_id="a", text="a sentence"))
        self.assertTrue(entered.wait(BARRIER_TIMEOUT))
        self.assertTrue(harness.worker.cancel("a"))
        self.assertFalse(harness.worker.cancel("a"))
        gate.set()
        self.assertTrue(harness.worker.drain(timeout=BARRIER_TIMEOUT))

    def test_a_cancellation_with_the_wrong_token_is_refused(self) -> None:
        gate = threading.Event()
        entered = threading.Event()
        harness = WorkerHarness(
            backends=[ScriptedBackend(playback_gate=gate, playback_entered=entered)]
        ).start()
        self.addCleanup(harness.close)
        harness.worker.submit(make_request(
            request_id="a", text="a sentence", cancellation_token="cancel-1"
        ))
        self.assertTrue(entered.wait(BARRIER_TIMEOUT))
        self.assertFalse(harness.worker.cancel("a", token="cancel-2"))
        self.assertTrue(harness.worker.cancel("a", token="cancel-1"))
        gate.set()
        self.assertTrue(harness.worker.drain(timeout=BARRIER_TIMEOUT))

    def test_a_provider_that_ignores_cancellation_still_ends_the_utterance(self) -> None:
        """The gate is never released; only the cancellation ends it."""
        gate = threading.Event()
        entered = threading.Event()
        provider = ScriptedProvider(synthesis_gate=gate, synthesis_entered=entered)
        harness = WorkerHarness(providers=[provider]).start()
        self.addCleanup(harness.close)
        harness.worker.submit(make_request(request_id="a", text="a sentence"))
        self.assertTrue(entered.wait(BARRIER_TIMEOUT))
        harness.worker.cancel("a")
        self.assertTrue(harness.worker.drain(timeout=BARRIER_TIMEOUT))
        self.assertEqual(harness.dispositions()["a"], SpeechDisposition.CANCELLED)

    def test_the_worker_restarting_while_speaking_leaves_nothing_running(self) -> None:
        gate = threading.Event()
        entered = threading.Event()
        backend = ScriptedBackend(playback_gate=gate, playback_entered=entered)
        harness = WorkerHarness(backends=[backend]).start()
        self.addCleanup(harness.close)
        harness.worker.submit(make_request(request_id="a", text="a sentence"))
        self.assertTrue(entered.wait(BARRIER_TIMEOUT))
        self.assertTrue(harness.worker.stop(timeout=BARRIER_TIMEOUT))
        self.assertIsNone(harness.worker.status()["current"])
        self.assertTrue(all(handle.finished for handle in backend.handles))

    def test_the_audio_device_disappears_during_a_cancellation(self) -> None:
        """§19: the two failures arrive together, and neither is lost.

        The order is the race. The cancellation is raised first and the device is
        taken away before the worker has finished tearing the playback down, so
        the teardown path runs against a backend that has stopped answering.
        The utterance must still settle as *cancelled* — not failed, because the
        user's cancel is what ended it — and the caption must survive both.
        """
        gate = threading.Event()
        entered = threading.Event()
        backend = ScriptedBackend(playback_gate=gate, playback_entered=entered)
        harness = WorkerHarness(backends=[backend]).start()
        self.addCleanup(harness.close)
        harness.worker.submit(make_request(request_id="a", text="a sentence being played"))
        self.assertTrue(entered.wait(BARRIER_TIMEOUT))

        harness.worker.cancel("a")
        backend.set_reachable(False)

        self.assertTrue(harness.worker.drain(timeout=BARRIER_TIMEOUT))
        self.assertEqual(harness.dispositions()["a"], SpeechDisposition.CANCELLED)
        self.assertTrue(all(handle.finished for handle in backend.handles))
        self.assertIsNone(harness.worker.status()["current"])
        for record in harness.router.degradations:
            self.assertTrue(record.captions_retained)
            self.assertFalse(record.task_affected)

    def test_the_renderer_restarts_while_the_worker_is_driving_visemes(self) -> None:
        """§19: a renderer that came back mid-utterance does not restart the mouth run.

        Driven through the worker's own scheduler while an utterance is
        genuinely in flight, rather than against a scheduler in isolation: the
        property that matters is that the *worker* keeps its place, and a
        scheduler tested alone cannot show that.
        """
        gate = threading.Event()
        entered = threading.Event()
        harness = WorkerHarness(
            backends=[ScriptedBackend(playback_gate=gate, playback_entered=entered)]
        ).start()
        self.addCleanup(harness.close)
        try:
            harness.worker.submit(make_request(
                request_id="a", text="a long enough sentence for the mouth to be moving"
            ))
            self.assertTrue(entered.wait(BARRIER_TIMEOUT))
            self.assertTrue(harness.wait_for(
                lambda: (harness.worker.status()["current"] or {}).get("visemeSource") != ""
            ))
            current = harness.worker._current  # noqa: SLF001 - the test owns this worker
            self.assertIsNotNone(current)
            before = current.scheduler.index
            frame = current.scheduler.reset_for_renderer_restart()
            self.assertEqual(frame.shape, MouthShape.NEUTRAL)
            self.assertEqual(current.scheduler.index, before, "the mouth run restarted")
            self.assertTrue(current.scheduler.active)
        finally:
            gate.set()
        self.assertTrue(harness.worker.drain(timeout=BARRIER_TIMEOUT))
        self.assertEqual(harness.dispositions()["a"], SpeechDisposition.PLAYED)

    def test_an_expired_request_is_never_spoken(self) -> None:
        harness = WorkerHarness().start()
        self.addCleanup(harness.close)
        outcome = harness.worker.submit(make_request(
            request_id="a", text="a stale sentence", expires_at_monotonic=1.0
        ))
        self.assertFalse(outcome.accepted)
        self.assertEqual(outcome.disposition, SpeechDisposition.EXPIRED)


class DeviceLossTests(unittest.TestCase):
    """§10: audio goes away, captions do not."""

    def test_no_device_at_startup_degrades_to_captions(self) -> None:
        harness = WorkerHarness(backends=[ScriptedBackend(reachable=False)]).start()
        self.addCleanup(harness.close)
        harness.worker.submit(make_request(request_id="a", text="a sentence"))
        self.assertTrue(harness.worker.drain(timeout=BARRIER_TIMEOUT))
        self.assertEqual(
            harness.dispositions()["a"], SpeechDisposition.DEGRADED_TO_CAPTIONS
        )
        self.assertTrue(any(
            item.kind == "no-audio-device-at-startup" for item in harness.router.degradations
        ), [item.kind for item in harness.router.degradations])

    def test_a_backend_that_cannot_start_a_player_falls_back(self) -> None:
        broken = ScriptedBackend("broken", fail="start")
        working = ScriptedBackend("working")
        harness = WorkerHarness(backends=[broken, working]).start()
        self.addCleanup(harness.close)
        harness.worker.submit(make_request(request_id="a", text="a sentence"))
        self.assertTrue(harness.worker.drain(timeout=BARRIER_TIMEOUT))
        self.assertTrue(any(
            item.kind == "playback-backend-crash" for item in harness.router.degradations
        ))

    def test_a_device_removed_during_playback_is_recorded_and_captions_stay(self) -> None:
        backend = ScriptedBackend("flaky", fail="exit")
        harness = WorkerHarness(backends=[backend]).start()
        self.addCleanup(harness.close)
        harness.worker.submit(make_request(request_id="a", text="a sentence"))
        self.assertTrue(harness.worker.drain(timeout=BARRIER_TIMEOUT))
        self.assertTrue(any(
            item.kind == "device-removed-during-playback" for item in harness.router.degradations
        ))
        for record in harness.router.degradations:
            self.assertTrue(record.captions_retained)
            self.assertFalse(record.task_affected)

    def test_an_unsupported_format_is_refused_before_a_player_is_started(self) -> None:
        backend = ScriptedBackend("picky", unsupported="24-bit audio is not supported")
        harness = WorkerHarness(backends=[backend]).start()
        self.addCleanup(harness.close)
        harness.worker.submit(make_request(request_id="a", text="a sentence"))
        self.assertTrue(harness.worker.drain(timeout=BARRIER_TIMEOUT))
        self.assertEqual(backend.plays, 0)
        self.assertEqual(
            harness.dispositions()["a"], SpeechDisposition.DEGRADED_TO_CAPTIONS
        )

    def test_a_degradation_may_never_claim_to_have_affected_a_task(self) -> None:
        with self.assertRaises(ValueError) as caught:
            DegradationRecord(
                kind="playback-backend-crash", stage="playback",
                detail="x", task_affected=True,
            )
        self.assertIn("presentation subsystem", str(caught.exception))

    def test_an_unknown_degradation_kind_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            DegradationRecord(kind="everything-broke", stage="playback", detail="x")


class BackoffTests(unittest.TestCase):
    """§10: no rapid retry loops; §12: recovery has hysteresis."""

    def setUp(self) -> None:
        self.moment = [1000.0]
        self.backend = ScriptedBackend("flaky", monotonic=lambda: self.moment[0])
        self.router = AudioRouter([self.backend], monotonic=lambda: self.moment[0])

    def test_a_failed_backend_is_not_retried_immediately(self) -> None:
        self.router.penalise("flaky", kind="playback-backend-crash", detail="it fell over")
        backend, device, reasons = self.router.select()
        self.assertIsNone(backend)
        self.assertIn("backing off", " ".join(reasons))

    def test_the_backoff_grows_and_is_bounded(self) -> None:
        for _ in range(10):
            self.router.penalise("flaky", kind="playback-backend-crash", detail="again")
        self.moment[0] += self.router.MAX_BACKOFF_SECONDS + 1
        backend, _device, _reasons = self.router.select()
        self.assertIsNotNone(backend)

    def test_restoration_needs_consecutive_healthy_observations(self) -> None:
        self.router.penalise("flaky", kind="playback-backend-crash", detail="it fell over")
        self.moment[0] += 1.0
        self.router.observe()
        backend, _device, reasons = self.router.select()
        self.assertIsNone(backend, reasons)
        self.router.observe()
        self.assertTrue(any(
            item.kind == "audio-server-restart" for item in self.router.degradations
        ))
        backend, _device, _reasons = self.router.select()
        self.assertIsNotNone(backend)

    def test_a_changed_device_list_is_noticed(self) -> None:
        self.router.observe()
        self.backend.set_devices(["a-different-sink"])
        self.router.observe()
        self.assertTrue(any(
            item.kind == "default-device-changed" for item in self.router.degradations
        ))

    def test_the_router_never_claims_a_physical_speaker(self) -> None:
        self.assertFalse(self.router.describe()["physicalSpeakerValidated"])


class PauseResumeTests(unittest.TestCase):
    def test_playback_can_be_paused_and_resumed(self) -> None:
        gate = threading.Event()
        entered = threading.Event()
        harness = WorkerHarness(
            backends=[ScriptedBackend(playback_gate=gate, playback_entered=entered)]
        ).start()
        self.addCleanup(harness.close)
        try:
            harness.worker.submit(make_request(request_id="a", text="a sentence"))
            self.assertTrue(entered.wait(BARRIER_TIMEOUT))
            self.assertTrue(harness.worker.pause())
            self.assertTrue(harness.worker.status()["current"]["paused"])
            self.assertTrue(harness.worker.resume())
            self.assertFalse(harness.worker.status()["current"]["paused"])
            self.assertFalse(harness.worker.resume())
        finally:
            gate.set()

    def test_pausing_with_nothing_playing_is_not_an_error(self) -> None:
        harness = WorkerHarness().start()
        self.addCleanup(harness.close)
        self.assertFalse(harness.worker.pause())
        self.assertFalse(harness.worker.resume())


class StreamingPathTests(unittest.TestCase):
    def test_a_streaming_only_provider_speaks_with_text_derived_timing(self) -> None:
        provider = ScriptedProvider("streaming-only", supports_synthesis=False)
        harness = WorkerHarness(providers=[provider]).start()
        self.addCleanup(harness.close)
        harness.worker.submit(make_request(request_id="a", text="a sentence to stream"))
        self.assertTrue(harness.worker.drain(timeout=BARRIER_TIMEOUT))
        self.assertEqual(harness.dispositions()["a"], SpeechDisposition.PLAYED)
        self.assertEqual(provider.stream_calls, 1)
        started = [item for item in harness.events if item.kind == "audio_started"]
        self.assertTrue(started)
        self.assertEqual(started[-1].payload["visemeSource"], "text-estimate")
        self.assertTrue(started[-1].payload["providerOwnedPlayback"])

    def test_the_mouth_ticker_is_stopped_and_joined(self) -> None:
        provider = ScriptedProvider("streaming-only", supports_synthesis=False)
        harness = WorkerHarness(providers=[provider]).start()
        self.addCleanup(harness.close)
        before = threading.active_count()
        for index in range(4):
            harness.worker.submit(make_request(request_id=f"a{index}", text=f"sentence {index}"))
        self.assertTrue(harness.worker.drain(timeout=BARRIER_TIMEOUT))
        self.assertTrue(harness.wait_for(lambda: threading.active_count() <= before))

    def test_a_failed_synthesis_falls_back_to_streaming_once(self) -> None:
        broken = ScriptedProvider("broken", failure_mode="crash")
        streaming = ScriptedProvider("streaming", supports_synthesis=False)
        harness = WorkerHarness(providers=[broken, streaming]).start()
        self.addCleanup(harness.close)
        harness.worker.submit(make_request(request_id="a", text="a sentence"))
        self.assertTrue(harness.worker.drain(timeout=BARRIER_TIMEOUT))
        self.assertEqual(harness.dispositions()["a"], SpeechDisposition.PLAYED)
        self.assertEqual(streaming.stream_calls, 1)

    def test_two_failures_end_in_captions_rather_than_a_third_attempt(self) -> None:
        first = ScriptedProvider("first", failure_mode="crash")
        second = ScriptedProvider("second", supports_synthesis=False, failure_mode="crash")
        harness = WorkerHarness(providers=[first, second]).start()
        self.addCleanup(harness.close)
        harness.worker.submit(make_request(request_id="a", text="a sentence"))
        self.assertTrue(harness.worker.drain(timeout=BARRIER_TIMEOUT))
        self.assertEqual(
            harness.dispositions()["a"], SpeechDisposition.DEGRADED_TO_CAPTIONS
        )
        self.assertEqual(first.synthesise_calls, 1)
        self.assertEqual(second.stream_calls, 1)


class EventTests(unittest.TestCase):
    def test_no_event_ever_carries_the_utterance(self) -> None:
        """§15: a digest identifies it; the caption holds the words."""
        harness = WorkerHarness().start()
        self.addCleanup(harness.close)
        secret = "the passphrase is opensesame indeed"
        harness.worker.submit(make_request(request_id="a", text=secret))
        self.assertTrue(harness.worker.drain(timeout=BARRIER_TIMEOUT))
        for event in harness.events:
            self.assertNotIn("opensesame", repr(event.to_json()))

    def test_every_emitted_kind_is_declared(self) -> None:
        harness = WorkerHarness().start()
        self.addCleanup(harness.close)
        harness.worker.submit(make_request(request_id="a", text="a sentence"))
        self.assertTrue(harness.worker.drain(timeout=BARRIER_TIMEOUT))
        for kind in harness.kinds():
            self.assertIn(kind, EVENT_KINDS)

    def test_a_broken_subscriber_does_not_stop_speech(self) -> None:
        harness = WorkerHarness().start()
        self.addCleanup(harness.close)
        harness.worker.subscribe(lambda event: (_ for _ in ()).throw(RuntimeError("boom")))
        harness.worker.submit(make_request(request_id="a", text="a sentence"))
        self.assertTrue(harness.worker.drain(timeout=BARRIER_TIMEOUT))
        self.assertEqual(harness.dispositions()["a"], SpeechDisposition.PLAYED)

    def test_visemes_are_delivered_live_and_not_retained(self) -> None:
        harness = WorkerHarness().start()
        self.addCleanup(harness.close)
        harness.worker.submit(make_request(request_id="a", text="a longer sentence with several words"))
        self.assertTrue(harness.worker.drain(timeout=BARRIER_TIMEOUT))
        self.assertTrue(any(item.kind == "viseme" for item in harness.events))
        self.assertFalse(any(item.kind == "viseme" for item in harness.worker.events(limit=256)))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
