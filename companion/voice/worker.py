# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The one thing that speaks, and the one thing that owns everything speaking uses.

§6 asks for a dedicated worker with explicit lifecycle ownership, and lists what
it must own: the current request, the provider instance, the child process, the
audio stream, the playback handle, the temporary files, the viseme scheduler,
the caption timing, the cancellation state and the completion state. All ten are
fields of :class:`Utterance`, one instance of which exists at a time, created
when an utterance starts and released in a ``finally`` when it ends. If it is
not on that object it is not owned, and if it is on that object it is released.

**At most one foreground utterance.** Not a performance choice: two voices
talking over each other is unusable, and a queue that could start a second
utterance while the first was speaking would make §7's interruption rules
meaningless — everything would simply be spoken at once.

**The worker cannot touch a task.** It holds no store, no runtime, no session
and no approval object. Its imports are the proof: nothing from
:mod:`companion.runtime`, :mod:`companion.store`, :mod:`companion.task`,
:mod:`companion.approvals` or :mod:`companion.executor` appears in this file,
and §21 asserts that from the import graph rather than from a reading of it. The
only thing that flows *in* is a :class:`companion.voice.request.VoiceRequest`,
which is a sanitized derivative of a caption; the only things that flow *out*
are events and the disposition ledger.

**Restartable without disturbing the task.** :meth:`VoiceWorker.stop` cancels
the current utterance, reaps its child, releases its workspace and clears the
queue. :meth:`VoiceWorker.start` begins again with an empty queue and no
memory of what was in flight, because §20 forbids replaying it. A task running
through a voice restart notices nothing: no event it emits reaches this module
except through a caption somebody submits.

**Threads.** One worker thread, always. Plus, on the streaming path only, one
short-lived ticker that advances the mouth while the provider blocks holding its
own audio — created when that path is taken, stopped and *joined* before the
utterance is released. §22 measures the thread delta across a hundred runs
precisely because "created and joined" is easy to write and easy to get wrong.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import threading
import time
from typing import Any, Callable, Iterable, Mapping, Sequence

from ..character.lipsync import MouthShape
from ..clock import Clock, SystemClock
from .audio import (
    AudioRouter,
    DegradationRecord,
    PlaybackHandle,
    PlaybackOutcome,
    inspect_audio,
)
from .captions import CaptionLedger, SpeechDisposition, SyncMeasurement
from .execution import CancellationSignal, PrivateWorkspace
from .pcm import amplitude_envelope
from .policy import VoiceDecision, VoicePolicy
from .provider import ProviderRegistry, SelectionResult, SynthesisResult, VoiceProvider
from .queue import QueueOutcome, SpeechQueue
from .recovery import VoiceJournal
from .request import Priority, VoiceRequest
from .visemes import (
    VisemeScheduler,
    VisemeTimeline,
    estimated_duration_ms,
    from_amplitude,
    from_text,
    speaking_state,
)

__all__ = [
    "EVENT_KINDS",
    "Utterance",
    "VoiceEvent",
    "VoiceWorker",
]

#: Every event the worker emits. A closed set for the same reason the
#: dispositions are: a surface subscribing to events needs to know what it can
#: receive, and a gate counting them needs the names to be stable.
EVENT_KINDS = (
    "speech_queued",
    "speech_rejected",
    "speech_started",
    "audio_started",
    "viseme",
    "mouth_neutral",
    "speech_finished",
    "speech_interrupted",
    "speech_cancelled",
    "speech_failed",
    "speech_degraded",
    "worker_started",
    "worker_stopped",
)

#: How often the worker looks at a running playback to advance the mouth. 25 ms
#: is 40 updates a second — ahead of any renderer's frame rate, so the mouth is
#: never waiting on this — and slow enough that an utterance costs a few hundred
#: wakeups rather than a busy loop.
TICK_SECONDS = 0.025


@dataclass(frozen=True)
class VoiceEvent:
    """One thing that happened, in a shape a client can render and a gate can count.

    Never carries the utterance's text. ``textDigest`` identifies it, which is
    all a surface needs to correlate an event with the caption it already has —
    and the caption is where the words belong.
    """

    kind: str
    request_id: str = ""
    session_id: str = ""
    task_id: str = ""
    caption_reference: str = ""
    at_monotonic: float = 0.0
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in EVENT_KINDS:
            raise ValueError(f"unknown voice event kind: {self.kind!r}")

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "requestId": self.request_id,
            "sessionId": self.session_id,
            "taskId": self.task_id,
            "captionReference": self.caption_reference,
            "atMonotonic": self.at_monotonic,
            **dict(self.payload),
        }


@dataclass
class Utterance:
    """Everything one utterance owns. §6's list, as fields.

    Created when speech starts and released in a ``finally``. Nothing that
    needs releasing lives anywhere else, so "did we leak" is a question about
    one object rather than about the whole module.
    """

    request: VoiceRequest
    cancellation: CancellationSignal
    scheduler: VisemeScheduler
    measurement: SyncMeasurement | None = None
    workspace: PrivateWorkspace | None = None
    provider: VoiceProvider | None = None
    selection: SelectionResult | None = None
    synthesis: SynthesisResult | None = None
    timeline: VisemeTimeline | None = None
    handle: PlaybackHandle | None = None
    playback: PlaybackOutcome | None = None
    ticker: threading.Thread | None = None
    ticker_stop: threading.Event | None = None
    disposition: str = SpeechDisposition.QUEUED
    detail: str = ""
    degradations: list[DegradationRecord] = field(default_factory=list)
    started_at: float = 0.0
    interrupted_by: str = ""

    def release(self) -> None:
        """Give back every resource, in the order that cannot strand one.

        Playback before the workspace: a player still reading the file when its
        directory is removed is the "orphan audio stream" §6 forbids, and on
        Linux an unlinked open file keeps playing to a path nothing can find.
        The ticker before both, because it touches the handle.
        """
        stop = self.ticker_stop
        if stop is not None:
            stop.set()
        ticker = self.ticker
        if ticker is not None and ticker.is_alive():
            # Bounded. A ticker that will not stop is a bug, and hanging the
            # worker on it would turn a mouth that keeps moving into a companion
            # that stops speaking entirely.
            ticker.join(timeout=2.0)
        self.ticker = None
        self.ticker_stop = None

        handle = self.handle
        if handle is not None:
            handle.stop()
            handle._finish()  # noqa: SLF001 - the worker owns this handle's lifecycle
        self.handle = None

        provider = self.provider
        if provider is not None:
            provider.cancel(self.request.request_id)

        workspace = self.workspace
        if workspace is not None:
            workspace.close()
        self.workspace = None


class VoiceWorker:
    """The voice runtime's only speaking thread.

    Constructed with the pieces it drives and owning none of their policy: the
    registry decides which providers exist, the router decides which backends
    are reachable, the policy decides whether to speak at all, and the ledger
    owns captions. This class decides *order and lifecycle* and nothing else,
    which is why it is the one place a leak could come from and the one place
    the tests point at.
    """

    def __init__(
        self,
        *,
        registry: ProviderRegistry,
        router: AudioRouter,
        policy: VoicePolicy,
        ledger: CaptionLedger,
        queue: SpeechQueue | None = None,
        clock: Clock | None = None,
        observer: Callable[[VoiceEvent], None] | None = None,
        tick_seconds: float = TICK_SECONDS,
        journal: "VoiceJournal | None" = None,
    ) -> None:
        self.registry = registry
        self.router = router
        self.policy = policy
        self.ledger = ledger
        # ``is None``, not ``or``. :class:`SpeechQueue` defines ``__len__``, so an
        # empty queue is falsy and ``queue or SpeechQueue()`` silently replaced a
        # caller's queue with a fresh one — every utterance was spoken correctly
        # and every disposition was recorded into an object nobody could see.
        self.queue = SpeechQueue() if queue is None else queue
        self.clock = clock or SystemClock()
        self.tick_seconds = max(0.001, tick_seconds)
        #: Optional, and the runtime always supplies one. Without it the worker
        #: still works and §20's recovery has nothing to read, so a restart
        #: would treat every past utterance as unknown — which is why the
        #: service wires one in rather than leaving it to a default.
        self.journal = journal

        self._observers: list[Callable[[VoiceEvent], None]] = [observer] if observer else []
        self._events: list[VoiceEvent] = []
        self._current: Utterance | None = None
        self._seen: dict[str, str] = {}
        self._thread: threading.Thread | None = None
        self._running = threading.Event()
        self._wake = threading.Event()
        self._idle = threading.Event()
        self._idle.set()
        self._guard = threading.RLock()
        self._spoken = 0
        self._started_at = 0.0

    # ----------------------------------------------------------------- #
    # Lifecycle
    # ----------------------------------------------------------------- #

    def start(self) -> "VoiceWorker":
        """Begin speaking. Idempotent; a second call returns the same worker."""
        with self._guard:
            if self._thread is not None and self._thread.is_alive():
                return self
            self._running.set()
            self._started_at = self.clock.monotonic()
            self._thread = threading.Thread(
                target=self._serve, name="companion-voice", daemon=True
            )
            self._thread.start()
        self._emit(VoiceEvent(kind="worker_started", at_monotonic=self.clock.monotonic()))
        return self

    def stop(self, *, timeout: float = 10.0) -> bool:
        """Stop speaking and release everything. Returns whether it stopped cleanly.

        The current utterance is cancelled rather than allowed to finish. A
        service being asked to stop while a caption is being read should stop,
        and the caption stays on the screen either way — which is the whole
        reason stopping speech is safe.
        """
        with self._guard:
            thread = self._thread
            self._running.clear()
            current = self._current
        if current is not None:
            current.cancellation.cancel("the voice worker is stopping")
        self._wake.set()
        if thread is not None:
            thread.join(timeout=timeout)
        cleared = self.queue.clear(reason="the voice worker stopped")
        with self._guard:
            self._thread = None
            leftover = self._current
            self._current = None
        if leftover is not None:
            # The loop did not get to its own ``finally``. Releasing here rather
            # than trusting it is the difference between a bounded stop and a
            # stranded child process.
            leftover.release()
        self._emit(VoiceEvent(
            kind="worker_stopped",
            at_monotonic=self.clock.monotonic(),
            payload={"clearedFromQueue": len(cleared)},
        ))
        return thread is None or not thread.is_alive()

    @property
    def running(self) -> bool:
        return self._running.is_set()

    def drain(self, *, timeout: float = 30.0) -> bool:
        """Wait until the queue is empty and nothing is speaking.

        Used by the vertical slice and by every test that needs a barrier rather
        than a sleep. Returns ``False`` on timeout instead of raising: a caller
        that wanted to know is asking, and one that did not can ignore it.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not len(self.queue) and self._current is None:
                return True
            self._idle.wait(0.02)
            self._idle.clear()
            if not len(self.queue) and self._current is None:
                return True
        return not len(self.queue) and self._current is None

    def subscribe(self, observer: Callable[[VoiceEvent], None]) -> None:
        with self._guard:
            self._observers.append(observer)

    # ----------------------------------------------------------------- #
    # Submission
    # ----------------------------------------------------------------- #

    def submit(self, request: VoiceRequest) -> QueueOutcome:
        """Offer an utterance. Never raises; the outcome says what happened.

        The duplicate check is here rather than only in the queue because §6
        makes it a property of the *service*: an id that has already been served
        must not be reused for different words, even after the first has left
        the queue. Otherwise the record of what was said stops matching what was
        said, one restart later.
        """
        now = self.clock.monotonic()
        with self._guard:
            previous = self._seen.get(request.request_id)
            if previous is not None:
                # Two different answers for two different situations, and the
                # difference is the content.
                if previous != request.text_digest:
                    outcome = QueueOutcome(
                        accepted=False,
                        disposition=SpeechDisposition.DROPPED,
                        detail=(
                            "this request id has already been served with different text; "
                            "serving it again would make the record disagree with the speech"
                        ),
                        request_id=request.request_id,
                    )
                else:
                    # A retry: the same id and the same words. Submission is
                    # idempotent, so this is *not* a second utterance. A client
                    # that resent a request over a connection it was unsure of
                    # must not make the companion say it twice — §19 lists a
                    # replayed request as a race for exactly this reason.
                    outcome = QueueOutcome(
                        accepted=False,
                        disposition=SpeechDisposition.COALESCED,
                        detail=(
                            "this request has already been served; submission is idempotent, "
                            "and an explicit replay is a new request"
                        ),
                        request_id=request.request_id,
                    )
                self.queue.record(request, outcome.disposition, outcome.detail)
                self._emit(self._event("speech_rejected", request, {"detail": outcome.detail}))
                return outcome
            current = self._current

        decision = self.policy.decision
        speaking = current.request if current is not None else None
        outcome = self.queue.submit(
            request, decision=decision, monotonic=now, speaking=speaking
        )

        for displaced, disposition in outcome.displaced:
            self.ledger.release(displaced)
            self._emit(VoiceEvent(
                kind="speech_cancelled" if disposition == SpeechDisposition.CANCELLED
                else "speech_interrupted",
                request_id=displaced,
                at_monotonic=now,
                payload={"disposition": disposition},
            ))

        if not outcome.accepted:
            self.ledger.record_disposition(
                request.caption_reference, request.request_id, outcome.disposition
            )
            self.ledger.release(request.request_id)
            self._emit(self._event(
                "speech_rejected", request,
                {"disposition": outcome.disposition, "detail": outcome.detail},
            ))
            return outcome

        with self._guard:
            self._seen[request.request_id] = request.text_digest
            if len(self._seen) > 4096:
                for key in list(self._seen)[:1024]:
                    self._seen.pop(key, None)

        # §7: a more urgent utterance that asked to interrupt takes the floor.
        # Both conditions are checked inside ``may_interrupt`` — the policy must
        # ask and the priority must earn it — so a decorative line cannot cut off
        # an approval prompt by setting a field.
        if current is not None and request.may_interrupt(current.request):
            current.interrupted_by = request.request_id
            current.cancellation.cancel(
                f"interrupted by {request.priority.wire} {request.request_id}"
            )

        self._emit(self._event("speech_queued", request, {"depth": len(self.queue)}))
        self._wake.set()
        return outcome

    def cancel(self, request_id: str, *, token: str = "") -> bool:
        """Stop one utterance wherever it is: queued, synthesising or playing."""
        with self._guard:
            current = self._current
        if current is not None and current.request.request_id == request_id:
            if token and current.request.cancellation_token and token != current.request.cancellation_token:
                return False
            return current.cancellation.cancel("cancelled by request")
        return self.queue.cancel(request_id, token=token)

    def cancel_task(self, task_id: str, *, reason: str = "the task was cancelled") -> tuple[str, ...]:
        """§7: cancelling a task stops that task's speech, queued and current."""
        cancelled = list(self.queue.cancel_task(task_id, reason=reason))
        with self._guard:
            current = self._current
        if current is not None and current.request.task_id == task_id:
            if current.cancellation.cancel(reason):
                cancelled.append(current.request.request_id)
        return tuple(cancelled)

    def pause(self) -> bool:
        with self._guard:
            current = self._current
        handle = current.handle if current is not None else None
        return bool(handle is not None and handle.pause())

    def resume(self) -> bool:
        with self._guard:
            current = self._current
        handle = current.handle if current is not None else None
        return bool(handle is not None and handle.resume())

    # ----------------------------------------------------------------- #
    # The loop
    # ----------------------------------------------------------------- #

    def _serve(self) -> None:
        while self._running.is_set():
            entry = self.queue.pop(monotonic=self.clock.monotonic())
            if entry is None:
                self._idle.set()
                self._wake.wait(0.05)
                self._wake.clear()
                continue
            if entry.disposition != SpeechDisposition.QUEUED:
                # Popped already withdrawn. The queue logged it; nothing to do.
                continue
            self._idle.clear()
            try:
                self._speak(entry.request)
            except Exception as exc:  # noqa: BLE001
                # A fault in the voice runtime must not end the voice runtime,
                # and it must certainly not reach the task. Recorded, and the
                # loop continues with the next utterance.
                self.queue.record(
                    entry.request, SpeechDisposition.FAILED,
                    f"the voice worker faulted: {type(exc).__name__}",
                )
                self._emit(self._event(
                    "speech_failed", entry.request,
                    {"detail": f"the voice worker faulted: {type(exc).__name__}"},
                ))
            finally:
                with self._guard:
                    self._current = None
                self._idle.set()
        self._idle.set()

    # ----------------------------------------------------------------- #

    def _speak(self, request: VoiceRequest) -> None:
        now = self.clock.monotonic()
        utterance = Utterance(
            request=request,
            cancellation=CancellationSignal(name=request.request_id),
            scheduler=VisemeScheduler(),
            measurement=self.ledger.measurement(request.request_id),
            started_at=now,
        )
        with self._guard:
            self._current = utterance
        if self.journal is not None:
            # Written before anything can fail. A start line with no settle is
            # what §20 reads as "in flight when we died"; writing it after the
            # provider call would leave a crash during synthesis invisible.
            self.journal.record_start(request, monotonic=now)

        try:
            if request.expired(now):
                self._settle(utterance, SpeechDisposition.EXPIRED, "the utterance expired before it started")
                return

            decision = self.policy.decision
            if not decision.speaks:
                self._degrade(
                    utterance, "policy-suppressed", "selection",
                    f"speech is {decision.outcome}; the caption is the whole of the output",
                )
                self._settle(utterance, SpeechDisposition.DEGRADED_TO_CAPTIONS, "captions only")
                return
            if not decision.permits(request.priority):
                self._settle(
                    utterance, SpeechDisposition.DROPPED,
                    f"{request.priority.wire} is below the current floor of {decision.minimum_priority.wire}",
                )
                return

            self._emit(self._event("speech_started", request, {
                "priority": request.priority.wire,
                "outcome": decision.outcome,
            }))
            if utterance.measurement is not None:
                utterance.measurement.synthesis_started_at = self.clock.monotonic()

            selection = self.registry.select(request, monotonic=now)
            utterance.selection = selection
            if not selection.selected or selection.provider is None:
                self._degrade(
                    utterance, "no-eligible-provider", "selection",
                    selection.detail,
                )
                self._settle(utterance, SpeechDisposition.DEGRADED_TO_CAPTIONS, selection.detail)
                return
            utterance.provider = selection.provider

            wants_samples = (
                selection.provider.declaration.supports_synthesis
                and not (request.prefer_streaming or decision.prefer_streaming)
            )
            if wants_samples:
                if self._synthesise_and_play(utterance, decision):
                    return
                # Synthesis or playback failed and the fallback is one attempt at
                # the streaming path — §12's "fall back once, then captions".
                if not self._stream(utterance, decision, fallback=True):
                    self._settle(
                        utterance, SpeechDisposition.DEGRADED_TO_CAPTIONS,
                        utterance.detail or "no local path produced audio; the caption stands",
                    )
                return
            if not self._stream(utterance, decision, fallback=False):
                self._settle(
                    utterance, SpeechDisposition.DEGRADED_TO_CAPTIONS,
                    utterance.detail or "the provider could not speak; the caption stands",
                )
        finally:
            # Neutral before release, always. A mouth left mid-syllable is the
            # most visible symptom of a runtime that lost track of itself, and
            # this is the single place every path passes through.
            frame = utterance.scheduler.cancel("the utterance ended") \
                if utterance.scheduler.active else utterance.scheduler.finish()
            if frame.shape is not MouthShape.NEUTRAL:  # pragma: no cover - defensive
                frame = utterance.scheduler.finish()
            self._emit(self._event("mouth_neutral", request, {"explanation": frame.explanation}))
            if utterance.measurement is not None:
                utterance.measurement.neutral_at = self.clock.monotonic()
            utterance.release()
            self._spoken += 1

    # ----------------------------------------------------------------- #

    def _synthesise_and_play(self, utterance: Utterance, decision: VoiceDecision) -> bool:
        """The full path: our samples, our backend, measured mouth timing."""
        request = utterance.request
        provider = utterance.provider
        assert provider is not None

        utterance.workspace = PrivateWorkspace()
        synthesis = provider.synthesize(
            request, utterance.workspace, cancellation=utterance.cancellation
        )
        utterance.synthesis = synthesis
        if utterance.measurement is not None:
            utterance.measurement.synthesis_finished_at = self.clock.monotonic()

        if utterance.cancellation.cancelled:
            self._finish_cancelled(utterance)
            return True
        if not synthesis.succeeded:
            self._degrade(
                utterance, "provider-failure", "synthesis", synthesis.detail,
                provider_id=synthesis.provider_id,
            )
            utterance.detail = synthesis.detail
            return False

        probe, reason = inspect_audio(synthesis.audio_path)
        if probe is None:
            self._degrade(
                utterance, "unsupported-audio-format", "synthesis", reason,
                provider_id=synthesis.provider_id,
            )
            utterance.detail = reason
            return False

        try:
            envelope = amplitude_envelope(probe)
        except Exception:  # noqa: BLE001 - a viseme is never worth losing speech over
            envelope = []
        utterance.timeline = (
            from_amplitude(
                request.request_id, envelope,
                total_ms=int(probe.duration_seconds * 1000), sample_rate=probe.sample_rate,
            )
            if envelope
            else from_text(
                request.request_id, request.speech_text,
                total_ms=int(probe.duration_seconds * 1000), rate=request.speaking_rate,
            )
        )

        backend, device, why = self.router.select(probe=probe)
        if backend is None or device is None:
            self._degrade(
                utterance, "no-audio-device-at-startup", "playback",
                "; ".join(why) or "no audio backend is reachable",
            )
            utterance.detail = "; ".join(why) or "no audio backend is reachable"
            # No point trying the streaming path: it needs the same devices.
            self._settle(
                utterance, SpeechDisposition.DEGRADED_TO_CAPTIONS,
                "no audio output is reachable; the caption is the whole of the output",
            )
            return True

        handle = backend.play(
            request.request_id, synthesis.audio_path,
            device_id=device.device_id, volume=request.volume, probe=probe,
        )
        utterance.handle = handle
        if not handle.started:
            self.router.penalise(
                backend.backend_id,
                kind="playback-backend-crash",
                detail=handle.start_error,
                request_id=request.request_id,
            )
            self._degrade(
                utterance, "playback-backend-crash", "playback", handle.start_error,
            )
            utterance.detail = handle.start_error
            return False

        started = self.clock.monotonic()
        if utterance.measurement is not None:
            utterance.measurement.audio_started_at = started
            utterance.measurement.viseme_source = utterance.timeline.source
        self._emit(self._event("audio_started", request, {
            "backendId": backend.backend_id,
            "deviceId": device.device_id,
            "audioSeconds": round(probe.duration_seconds, 4),
            "visemeSource": utterance.timeline.source,
            "visemeConfidence": utterance.timeline.confidence,
        }))

        frame = utterance.scheduler.start(utterance.timeline)
        if utterance.measurement is not None:
            utterance.measurement.first_viseme_at = self.clock.monotonic()
        # Emitted, not merely computed. The opening frame is the one that tells
        # a renderer the timeline exists, which source it came from and how much
        # to trust it — and for an utterance short enough that the loop below
        # never turns, it is the only frame there would otherwise be.
        self._emit_viseme(request, frame)

        # Drive the mouth in this thread while the player runs. No timer, no
        # second thread: the worker is already awake and has nothing else to do,
        # and a callback-driven mouth would be a resource nothing owns.
        while handle.poll() is None:
            if utterance.cancellation.cancelled:
                break
            position_ms = int(handle.position_seconds * 1000)
            frame = utterance.scheduler.advance(
                position_ms, audio_clock_ms=position_ms
            )
            self._emit_viseme(request, frame)
            time.sleep(self.tick_seconds)

        outcome = handle.wait(cancellation=utterance.cancellation, poll_interval=self.tick_seconds)
        utterance.playback = outcome
        if utterance.measurement is not None:
            utterance.measurement.audio_finished_at = self.clock.monotonic()

        if outcome.cancelled or utterance.cancellation.cancelled:
            self.router.succeed(backend.backend_id)
            self._finish_cancelled(utterance)
            return True
        if not outcome.succeeded:
            self.router.penalise(
                backend.backend_id,
                kind="device-removed-during-playback",
                detail=outcome.detail,
                request_id=request.request_id,
            )
            self._degrade(
                utterance, "device-removed-during-playback", "playback", outcome.detail,
            )
            utterance.detail = outcome.detail
            return False

        self.router.succeed(backend.backend_id)
        self._settle(utterance, SpeechDisposition.PLAYED, "played")
        return True

    # ----------------------------------------------------------------- #

    def _stream(self, utterance: Utterance, decision: VoiceDecision, *, fallback: bool) -> bool:
        """The lighter path: the provider keeps the audio, we estimate the mouth."""
        request = utterance.request
        exclude: list[str] = []
        if fallback and utterance.selection is not None and utterance.selection.provider is not None:
            exclude.append(utterance.selection.provider.declaration.provider_id)

        selection = self.registry.select(
            request, monotonic=self.clock.monotonic(),
            exclude=exclude, require_streaming=True,
        )
        if not selection.selected or selection.provider is None:
            if fallback:
                self._degrade(
                    utterance, "streaming-unavailable", "playback",
                    selection.detail,
                )
            utterance.detail = selection.detail
            return False
        provider = selection.provider
        utterance.provider = provider
        utterance.selection = selection

        duration_ms = estimated_duration_ms(request.speech_text, rate=request.speaking_rate)
        utterance.timeline = from_text(
            request.request_id, request.speech_text, rate=request.speaking_rate
        )

        started = self.clock.monotonic()
        if utterance.measurement is not None:
            utterance.measurement.audio_started_at = started
            utterance.measurement.viseme_source = utterance.timeline.source
        self._emit(self._event("audio_started", request, {
            "providerId": provider.declaration.provider_id,
            "providerOwnedPlayback": True,
            "estimatedMs": duration_ms,
            "visemeSource": utterance.timeline.source,
            "visemeConfidence": utterance.timeline.confidence,
        }))

        frame = utterance.scheduler.start(utterance.timeline)
        if utterance.measurement is not None:
            utterance.measurement.first_viseme_at = self.clock.monotonic()
        self._emit_viseme(request, frame)

        # The provider blocks holding its own audio, so the mouth is driven from
        # a ticker this worker creates, owns and joins. On the estimated clock:
        # there is no audio clock to compare against, which is exactly why this
        # timeline's confidence is 0.35 and not higher.
        stop = threading.Event()
        utterance.ticker_stop = stop

        def _tick() -> None:
            origin = self.clock.monotonic()
            while not stop.is_set() and not utterance.cancellation.cancelled:
                position_ms = int((self.clock.monotonic() - origin) * 1000)
                self._emit_viseme(request, utterance.scheduler.advance(position_ms))
                if not utterance.scheduler.active:
                    return
                stop.wait(self.tick_seconds)

        ticker = threading.Thread(target=_tick, name="companion-voice-mouth", daemon=True)
        utterance.ticker = ticker
        ticker.start()

        outcome = provider.stream(request, cancellation=utterance.cancellation)
        stop.set()
        ticker.join(timeout=2.0)
        utterance.ticker = None

        if utterance.measurement is not None:
            utterance.measurement.audio_finished_at = self.clock.monotonic()

        if outcome.cancelled or utterance.cancellation.cancelled:
            self._finish_cancelled(utterance)
            return True
        if not outcome.succeeded:
            self._degrade(
                utterance, "provider-failure", "playback", outcome.detail,
                provider_id=outcome.provider_id,
            )
            utterance.detail = outcome.detail
            return False
        self._settle(utterance, SpeechDisposition.PLAYED, "played by the provider")
        return True

    # ----------------------------------------------------------------- #

    def _finish_cancelled(self, utterance: Utterance) -> None:
        interrupted = bool(utterance.interrupted_by)
        disposition = SpeechDisposition.INTERRUPTED if interrupted else SpeechDisposition.CANCELLED
        detail = (
            f"interrupted by {utterance.interrupted_by}" if interrupted
            else utterance.cancellation.reason or "cancelled"
        )
        self._settle(utterance, disposition, detail)

    def _settle(self, utterance: Utterance, disposition: str, detail: str) -> None:
        """Record the outcome once, everywhere it has to be recorded."""
        request = utterance.request
        utterance.disposition = disposition
        utterance.detail = detail
        if self.journal is not None:
            self.journal.record_settle(request, disposition, monotonic=self.clock.monotonic())
        self.queue.record(request, disposition, detail)
        self.ledger.record_disposition(request.caption_reference, request.request_id, disposition)
        self.ledger.release(request.request_id)
        kind = {
            SpeechDisposition.PLAYED: "speech_finished",
            SpeechDisposition.INTERRUPTED: "speech_interrupted",
            SpeechDisposition.CANCELLED: "speech_cancelled",
            SpeechDisposition.SUPERSEDED: "speech_cancelled",
            SpeechDisposition.FAILED: "speech_failed",
        }.get(disposition, "speech_degraded")
        measurement = utterance.measurement
        self._emit(self._event(kind, request, {
            "disposition": disposition,
            "detail": detail,
            "providerId": (
                utterance.selection.provider.declaration.provider_id
                if utterance.selection and utterance.selection.provider else ""
            ),
            "synthesis": utterance.synthesis.to_json() if utterance.synthesis else None,
            "playback": utterance.playback.to_json() if utterance.playback else None,
            "visemes": utterance.timeline.to_json() if utterance.timeline else None,
            "synchronisation": measurement.to_json() if measurement else None,
            "captionsRetained": True,
            "taskAffected": False,
        }))

    def _degrade(
        self,
        utterance: Utterance,
        kind: str,
        stage: str,
        detail: str,
        *,
        provider_id: str = "",
    ) -> DegradationRecord:
        record = self.router.record(DegradationRecord(
            kind=kind,
            stage=stage,
            detail=detail,
            provider_id=provider_id,
            request_id=utterance.request.request_id,
            at_monotonic=self.clock.monotonic(),
        ))
        utterance.degradations.append(record)
        self._emit(self._event("speech_degraded", utterance.request, record.to_json()))
        return record

    # ----------------------------------------------------------------- #

    def _emit_viseme(self, request: VoiceRequest, frame: Any) -> None:
        self._emit(self._event("viseme", request, frame.to_json()))

    def _event(self, kind: str, request: VoiceRequest, payload: Mapping[str, Any]) -> VoiceEvent:
        return VoiceEvent(
            kind=kind,
            request_id=request.request_id,
            session_id=request.session_id,
            task_id=request.task_id,
            caption_reference=request.caption_reference,
            at_monotonic=self.clock.monotonic(),
            payload=dict(payload),
        )

    def _emit(self, event: VoiceEvent) -> None:
        with self._guard:
            # Visemes are not retained. Forty a second for the length of every
            # utterance would swamp a bounded ring and push out the events a
            # person actually wants to read, and a subscriber that wants them is
            # already receiving them live.
            if event.kind != "viseme":
                self._events.append(event)
                if len(self._events) > 256:
                    del self._events[:-256]
            observers = list(self._observers)
        for observer in observers:
            try:
                observer(event)
            except Exception:  # noqa: BLE001 - a broken subscriber must not stop speech
                continue

    # ----------------------------------------------------------------- #

    def events(self, *, limit: int = 64) -> tuple[VoiceEvent, ...]:
        with self._guard:
            return tuple(self._events[-max(1, limit):])

    def status(self) -> dict[str, Any]:
        """Everything §17's ``voice_status`` answers, and what §22 counts."""
        with self._guard:
            current = self._current
            thread = self._thread
        utterance: dict[str, Any] | None = None
        if current is not None:
            handle = current.handle
            utterance = {
                "requestId": current.request.request_id,
                "taskId": current.request.task_id,
                "sessionId": current.request.session_id,
                "captionReference": current.request.caption_reference,
                "priority": current.request.priority.wire,
                "textDigest": current.request.text_digest,
                "providerId": (
                    current.selection.provider.declaration.provider_id
                    if current.selection and current.selection.provider else ""
                ),
                "paused": bool(handle is not None and handle.paused),
                "positionSeconds": round(handle.position_seconds, 3) if handle else 0.0,
                "cancelled": current.cancellation.cancelled,
                "mouthShape": current.scheduler.shape.value,
                "visemeSource": current.timeline.source if current.timeline else "",
                "temporaryFiles": len(current.workspace.files) if current.workspace else 0,
            }
        return {
            "running": self.running,
            "threadAlive": bool(thread is not None and thread.is_alive()),
            "activeRequests": 1 if current is not None else 0,
            "queueDepth": len(self.queue),
            "spoken": self._spoken,
            "uptimeSeconds": round(self.clock.monotonic() - self._started_at, 3) if self._started_at else 0.0,
            "current": utterance,
            "decision": self.policy.decision.to_json(),
            "dispositions": self.queue.counts(),
            "captionsAuthoritative": True,
            "mayMutateTaskState": False,
            "remoteTransmission": False,
            "voiceCloning": False,
        }
