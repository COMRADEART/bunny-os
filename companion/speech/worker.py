# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The one thing that listens, and the one thing that owns everything listening uses.

§2 asks for a restartable capture worker, and the ownership rule is the voice
worker's, applied to input: everything one capture touches is a field of
:class:`CaptureSession`, one exists at a time, and it is released in a
``finally``. If it is not on that object it is not owned, and if it is on that
object it is released — which is what makes §23's per-iteration deltas a
question about one dataclass.

**At most one capture.** Not a performance choice: two open microphones is two
listening indicators or one lie, and §4's conflicting-session rule is enforced
by a single slot under a lock rather than by counting.

**The ordering is the security property.** ``_serve`` runs §4's sequence in
§4's order — validate, reserve, quiesce output (§19), start the recogniser,
**raise the indicator**, open the microphone, capture — and the two clauses
with teeth are branches, not comments: a failed indicator raise returns before
any device call exists, and the indicator clear passes the capture handle's
own ``closed`` fact, which :class:`companion.speech.indicator.ListeningIndicator`
refuses without.

**The worker cannot touch a task.** It holds no store, no runtime, no session
object and no approval. Its imports are the proof, as §1 asks: nothing from
:mod:`companion.runtime`, :mod:`companion.store`, :mod:`companion.task` or
:mod:`companion.approvals` appears in this file. A final transcript's whole
journey out of here is into the :class:`~companion.speech.confirmation.ConfirmationLedger`,
where it waits for a person.

**Threads.** No persistent thread: a capture owns one, created at start and
joined at release, so a worker with no capture running holds nothing §23
could count. The reader threads inside the capture child are owned by the
handle, which is owned by the session, which is released in the ``finally``.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
import threading
from typing import Any, Callable, Mapping

from ..clock import Clock, SystemClock
from ..voice.execution import CancellationSignal
from .activity import SpeechActivityDetector
from .capture import CaptureDegradation, CaptureHandle, CaptureRouter
from .confirmation import ConfirmationLedger
from .coordination import CoordinationRecord, VoiceOutputCoordinator
from .events import SpeechInputEvent
from .execution import SpeechWorkspace
from .indicator import ListeningIndicator
from .policy import SpeechInputPolicy
from .recognizer import RecognitionSession, RecognizerRegistry
from .recovery import SpeechJournal
from .request import SpeechInputRequest
from .transcript import FinalTranscript, TranscriptError

__all__ = [
    "CaptureMeasurement",
    "CaptureOutcome",
    "CaptureSession",
    "CaptureWorker",
    "MAX_PARTIALS_PER_CAPTURE",
]

#: The most partial-transcript events one capture may emit. Ten a second for
#: twenty-five seconds; past it the partials are suppressed with a typed
#: degradation and final recognition is untouched (§12).
MAX_PARTIALS_PER_CAPTURE = 256

#: How long the worker waits for frames before treating the transport as
#: stalled. Distinct from silence: a silent room still delivers zero-valued
#: frames on schedule, and a recorder delivering *nothing* is a device that
#: has gone away without saying so.
STALL_SECONDS = 3.0


@dataclass(frozen=True)
class CaptureOutcome:
    """What one start request decided, immediately and synchronously."""

    accepted: bool
    request_id: str = ""
    detail: str = ""
    cancellation_token: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "requestId": self.request_id,
            "detail": self.detail,
            "cancellationToken": self.cancellation_token,
            "typedInputPreserved": True,
            "taskAffected": False,
        }


@dataclass
class CaptureMeasurement:
    """Every §25 latency for one capture, monotonic, measured where it happens."""

    requested_at: float = 0.0
    output_quiesced_at: float = 0.0
    recognizer_ready_at: float = 0.0
    indicator_raised_at: float = 0.0
    microphone_opened_at: float = 0.0
    first_frame_at: float = 0.0
    speech_detected_at: float = 0.0
    first_partial_at: float = 0.0
    capture_stopped_at: float = 0.0
    microphone_closed_at: float = 0.0
    indicator_cleared_at: float = 0.0
    final_transcript_at: float = 0.0
    cancelled_at: float = 0.0
    settled_at: float = 0.0
    peak_buffered_bytes: int = 0
    bytes_captured: int = 0

    def to_json(self) -> dict[str, Any]:
        def gap(later: float, earlier: float) -> float | None:
            if not later or not earlier or later < earlier:
                return None
            return round(later - earlier, 6)

        return {
            "indicatorLatencySeconds": gap(self.indicator_raised_at, self.requested_at),
            "microphoneOpenLatencySeconds": gap(self.microphone_opened_at, self.requested_at),
            "firstFrameLatencySeconds": gap(self.first_frame_at, self.requested_at),
            "speechDetectLatencySeconds": gap(self.speech_detected_at, self.first_frame_at),
            "firstPartialLatencySeconds": gap(self.first_partial_at, self.speech_detected_at),
            "finalTranscriptLatencySeconds": gap(self.final_transcript_at, self.capture_stopped_at),
            "cancellationLatencySeconds": gap(self.settled_at, self.cancelled_at),
            "deviceCloseLatencySeconds": gap(self.microphone_closed_at, self.capture_stopped_at),
            "indicatorBeforeOpen": bool(
                self.indicator_raised_at
                and self.microphone_opened_at
                and self.indicator_raised_at <= self.microphone_opened_at
            ),
            "indicatorClearedAfterClose": bool(
                self.indicator_cleared_at
                and self.microphone_closed_at
                and self.indicator_cleared_at >= self.microphone_closed_at
            ),
            "peakBufferedBytes": self.peak_buffered_bytes,
            "bytesCaptured": self.bytes_captured,
        }


@dataclass
class CaptureSession:
    """Everything one capture owns. §2's list, as fields, released in one place."""

    request: SpeechInputRequest
    cancellation: CancellationSignal
    measurement: CaptureMeasurement
    stop_requested: threading.Event = field(default_factory=threading.Event)
    stop_reason: str = ""
    handle: CaptureHandle | None = None
    recognition: RecognitionSession | None = None
    workspace: SpeechWorkspace | None = None
    coordination: CoordinationRecord | None = None
    thread: threading.Thread | None = None
    phase: str = "validating"
    disposition: str = ""
    detail: str = ""
    partials_emitted: int = 0
    partials_suppressed: bool = False
    #: The newest partial, kept for the poll-based client: partial events are
    #: delivered live and not retained, and a window that polls twice a second
    #: still deserves the current provisional reading.
    last_partial: Any = None
    hasher: Any = None
    batch_path: Any = None

    def release(self) -> None:
        """Give back every resource, in the order that cannot strand one.

        The handle before the workspace — a recorder still writing when its
        directory is removed is the orphan §6 forbids — and the recognition
        session after both, because closing it is memory work that cannot
        block on a device.
        """
        handle = self.handle
        if handle is not None:
            handle.close()
        self.handle = None
        workspace = self.workspace
        if workspace is not None:
            workspace.close()
        self.workspace = None
        recognition = self.recognition
        if recognition is not None:
            try:
                recognition.close()
            except Exception:  # noqa: BLE001 - release never raises
                pass
        self.recognition = None


class CaptureWorker:
    """The speech-input runtime's only capturing component.

    Constructed with the pieces it drives and owning none of their policy: the
    router decides which backends exist, the registry which recognisers, the
    policy whether to capture at all, the indicator whether listening is
    visible, the coordinator what happens to output speech, and the ledger
    where a transcript waits. This class decides *order and lifecycle*, which
    is why it is the one place a leak could come from and the one place §23
    points its counters at.
    """

    def __init__(
        self,
        *,
        router: CaptureRouter,
        registry: RecognizerRegistry,
        policy: SpeechInputPolicy,
        indicator: ListeningIndicator,
        ledger: ConfirmationLedger,
        coordinator: VoiceOutputCoordinator | None = None,
        journal: SpeechJournal | None = None,
        clock: Clock | None = None,
        observer: Callable[[SpeechInputEvent], None] | None = None,
    ) -> None:
        self.router = router
        self.registry = registry
        self.policy = policy
        self.indicator = indicator
        self.ledger = ledger
        self.coordinator = coordinator or VoiceOutputCoordinator(None)
        self.journal = journal
        self.clock = clock or SystemClock()

        self._observers: list[Callable[[SpeechInputEvent], None]] = (
            [observer] if observer else []
        )
        self._events: list[SpeechInputEvent] = []
        self._current: CaptureSession | None = None
        self._seen: dict[str, str] = {}
        self._sequences: dict[str, int] = {}
        self._records: list[dict[str, Any]] = []
        self._measurements: dict[str, CaptureMeasurement] = {}
        self._guard = threading.RLock()
        self._closed = False
        self._captures = 0

    # ----------------------------------------------------------------- #
    # Submission
    # ----------------------------------------------------------------- #

    def start_capture(self, request: SpeechInputRequest) -> CaptureOutcome:
        """§4's gate, then a session thread. Never raises; the outcome says why not.

        Every cheap refusal happens here, synchronously, before anything owns
        a thread: the caller learns "no" in the reply rather than in an event
        stream, and a refused start costs nothing to unwind because nothing
        was wound.
        """
        now = self.clock.monotonic()
        with self._guard:
            if self._closed:
                return CaptureOutcome(
                    accepted=False, request_id=request.request_id,
                    detail="the capture worker is stopped",
                )
            previous = self._seen.get(request.request_id)
            if previous is not None:
                # §16's duplicate activation: one id is one capture, and the
                # second start is refused rather than made a second microphone.
                return CaptureOutcome(
                    accepted=False, request_id=request.request_id,
                    detail="this request id has already been used for a capture; "
                           "a new capture is a new explicit activation with a new id",
                )
            if self._current is not None:
                return CaptureOutcome(
                    accepted=False, request_id=request.request_id,
                    detail=(
                        f"a capture is already running for {self._current.request.request_id!r}; "
                        "one microphone, one capture at a time"
                    ),
                )

        if request.expired(now):
            self._record(request.request_id, "expired", "the activation lapsed before capture began")
            return CaptureOutcome(
                accepted=False, request_id=request.request_id,
                detail="the activation lapsed before the capture could begin; press again",
            )

        decision = self.policy.decision
        if not decision.may_capture:
            self._record(request.request_id, "refused", "; ".join(decision.reasons) or decision.outcome)
            return CaptureOutcome(
                accepted=False, request_id=request.request_id,
                detail=(
                    f"speech input is {decision.outcome}: "
                    + ("; ".join(decision.reasons) or "capture is not available")
                ),
            )
        preferences = self.policy.preferences
        if not request.confirmation_required and not preferences.allow_immediate_submission:
            # §13: immediate submission exists only as an explicit user
            # preference. A request asking for it without the preference is
            # refused outright rather than quietly served with confirmation —
            # a caller that believes confirmation is off must not be running
            # under a different contract than it thinks.
            return CaptureOutcome(
                accepted=False, request_id=request.request_id,
                detail=(
                    "this capture asked to skip transcript confirmation and the user "
                    "has not enabled immediate submission; the request was refused"
                ),
            )

        selection = self.registry.select(request, monotonic=now)
        if not selection.selected:
            self._record(request.request_id, "refused", selection.detail)
            return CaptureOutcome(
                accepted=False, request_id=request.request_id,
                detail=selection.detail,
            )

        measurement = CaptureMeasurement(requested_at=now)
        session = CaptureSession(
            request=request,
            cancellation=CancellationSignal(name=request.request_id),
            measurement=measurement,
            hasher=hashlib.sha256(),
        )
        with self._guard:
            if self._current is not None:
                return CaptureOutcome(
                    accepted=False, request_id=request.request_id,
                    detail="a capture began while this one was being validated; one at a time",
                )
            self._current = session
            self._seen[request.request_id] = request.activation_source
            if len(self._seen) > 4096:
                for key in list(self._seen)[:1024]:
                    self._seen.pop(key, None)
            self._measurements[request.request_id] = measurement
            if len(self._measurements) > 64:
                for key in list(self._measurements)[:16]:
                    self._measurements.pop(key, None)

        thread = threading.Thread(
            target=self._serve,
            args=(session, selection.recognizer, decision),
            name="companion-speech-capture",
            daemon=True,
        )
        session.thread = thread
        thread.start()
        return CaptureOutcome(
            accepted=True,
            request_id=request.request_id,
            cancellation_token=request.cancellation_token,
            detail="capture starting",
        )

    def stop_capture(self, request_id: str) -> tuple[bool, str]:
        """§15: a person's stop overrides every automatic one. Ends capture,
        keeps the audio, proceeds to recognition."""
        with self._guard:
            session = self._current
        if session is None or session.request.request_id != request_id:
            return False, f"no capture is running as {request_id!r}"
        session.stop_reason = "manual-stop"
        session.stop_requested.set()
        return True, ""

    def cancel(self, request_id: str, *, token: str = "") -> tuple[bool, str]:
        """Abandon a capture: no transcript, no task, everything released."""
        with self._guard:
            session = self._current
        if session is None or session.request.request_id != request_id:
            return False, f"no capture is running as {request_id!r}"
        expected = session.request.cancellation_token
        if expected and token != expected:
            return False, "the cancellation does not carry this capture's token"
        session.measurement.cancelled_at = self.clock.monotonic()
        cancelled = session.cancellation.cancel("cancelled by request")
        return cancelled, "" if cancelled else "already cancelled"

    # ----------------------------------------------------------------- #
    # The capture, from validation to settlement
    # ----------------------------------------------------------------- #

    def _serve(
        self,
        session: CaptureSession,
        recognizer: Any,
        decision: Any,
    ) -> None:
        request = session.request
        measurement = session.measurement
        try:
            self._emit(session, "speech_input_requested", {
                "activationSource": request.activation_source,
                "outcome": decision.outcome,
                "providerId": recognizer.declaration.provider_id,
            })
            if self.journal is not None:
                self.journal.record_start(request, monotonic=self.clock.monotonic())

            # §19 before §5: output speech is quiesced before the indicator
            # rises, so the first captured frame cannot carry the companion's
            # own narration.
            session.coordination = self.coordinator.quiesce(
                capture_request_id=request.request_id
            )
            measurement.output_quiesced_at = self.clock.monotonic()

            streaming = bool(
                decision.streaming and recognizer.declaration.supports_streaming
            )
            session.phase = "starting-recognizer"
            if streaming:
                # Before the microphone: a model that takes seconds to load
                # must spend them with the device shut, not open.
                try:
                    session.recognition = recognizer.start(request)
                except Exception as exc:  # noqa: BLE001 - refusal, not crash
                    self._fail_before_open(
                        session, "recognizer-unavailable",
                        f"the recogniser could not start: {exc}",
                    )
                    return
            measurement.recognizer_ready_at = self.clock.monotonic()

            if session.cancellation.cancelled:
                # §16: cancel before the microphone opens. Nothing was opened,
                # so there is nothing to close — the refusal is a settle and a
                # released recogniser, and no device call ever happens.
                self._finish_cancelled(session)
                return

            session.phase = "raising-indicator"
            raised, reason = self.indicator.raise_for(
                request_id=request.request_id,
                session_id=request.session_id,
                device_id=request.device_preference,
                backend_id="",
                provider_id=recognizer.declaration.provider_id,
            )
            if not raised:
                # §4's sentence as a branch: no indicator, no microphone.
                self._fail_before_open(session, "indicator-unavailable", reason)
                return
            measurement.indicator_raised_at = self.clock.monotonic()
            self._emit(session, "microphone_indicator_raised", {
                "indicator": self.indicator.state.to_json(
                    monotonic_now=self.clock.monotonic()
                ),
            })

            if session.cancellation.cancelled:
                # §16: the indicator went up and the cancel arrived before the
                # device call. Clear it — nothing opened, so "closed" is true —
                # and settle without a microphone ever having existed.
                self._clear_indicator(session, capture_closed=True)
                self._finish_cancelled(session)
                return

            session.phase = "opening-microphone"
            backend, device, why = self.router.select(request)
            if backend is None or device is None:
                self._clear_indicator(session, capture_closed=True)
                self._fail_before_open(
                    session, "no-capture-device-at-startup",
                    "; ".join(why) or "no capture device is reachable",
                    indicator_cleared=True,
                )
                return
            handle = backend.open(request, device_id=device.device_id)
            session.handle = handle
            if not handle.started:
                self.router.penalise(
                    backend.backend_id,
                    kind="capture-backend-crash",
                    detail=handle.start_error,
                    request_id=request.request_id,
                )
                handle.close()
                measurement.microphone_closed_at = self.clock.monotonic()
                self._clear_indicator(session, capture_closed=True)
                self._fail_before_open(
                    session, "capture-backend-crash", handle.start_error,
                    indicator_cleared=True,
                )
                return
            measurement.microphone_opened_at = self.clock.monotonic()
            self._emit(session, "microphone_opened", {
                "backendId": backend.backend_id,
                "deviceId": device.device_id,
                "sampleRate": request.sample_rate,
                "channels": request.channels,
                "openLatencySeconds": round(handle.open_latency_seconds, 6),
            })

            session.phase = "capturing"
            self._emit(session, "capture_started", {
                "maximumSeconds": request.maximum_capture_seconds,
                "streaming": streaming,
                "partialTranscripts": bool(
                    streaming
                    and request.partial_transcripts
                    and decision.partial_transcripts_permitted
                ),
            })
            ending = self._capture_loop(session, streaming=streaming, decision=decision)

            # Stop and close before anything else: §17's order, and §5's
            # precondition for the indicator clear below.
            handle.stop()
            self._drain(session, streaming=streaming)
            measurement.capture_stopped_at = self.clock.monotonic()
            handle.close()
            measurement.microphone_closed_at = self.clock.monotonic()
            measurement.bytes_captured = handle.bytes_captured
            self._emit(session, "capture_stopped", {
                "reason": ending,
                "bytesCaptured": handle.bytes_captured,
                "droppedBytes": handle.buffer.dropped_bytes,
            })
            self._emit(session, "microphone_closed", {
                "exitCode": handle.exit_code(),
            })
            self._clear_indicator(session, capture_closed=handle.closed)

            if ending == "cancelled":
                self._finish_cancelled(session)
                return
            if ending == "device-lost":
                self._finish_device_lost(session, streaming=streaming)
                return
            # Every other ending — endpoint silence, initial silence, the
            # duration or byte ceilings, a manual stop — goes through
            # finalisation, and the *recogniser* decides whether speech
            # occurred. The energy gate bounds how long the microphone stays
            # open (§15); it is a heuristic, and it was measured wrong in
            # exactly the way that matters: a capture whose speech began in
            # the calibration window ran to its initial-silence timeout with
            # the recogniser holding the whole correct sentence, and a
            # discard here threw the user's words away because a heuristic
            # had not noticed them. An empty final transcript still settles
            # as no-speech, in one place, in ``_finalize``.
            self._finalize(session, streaming=streaming, ending=ending)
        except Exception as exc:  # noqa: BLE001 - a fault must not skip release
            # A fault in the speech runtime must not reach a task and must not
            # leave a device open. Recorded, released below, indicator cleared
            # after the handle has actually closed.
            if session.handle is not None:
                session.handle.close()
                session.measurement.microphone_closed_at = self.clock.monotonic()
            self._clear_indicator(session, capture_closed=True)
            self._settle(
                session, "failed",
                f"the capture worker faulted: {type(exc).__name__}",
            )
        finally:
            session.release()
            with self._guard:
                self._current = None
                self._captures += 1

    # ----------------------------------------------------------------- #

    def _capture_loop(self, session: CaptureSession, *, streaming: bool, decision: Any) -> str:
        """Frames in, boundaries out. Returns why the capture ended."""
        request = session.request
        handle = session.handle
        assert handle is not None
        detector = SpeechActivityDetector(
            sample_rate=request.sample_rate,
            channels=request.channels,
            initial_silence_seconds=request.initial_silence_seconds,
            endpoint_silence_seconds=request.endpoint_silence_seconds,
            maximum_seconds=request.maximum_capture_seconds,
        )
        if not streaming:
            session.workspace = SpeechWorkspace()
            session.batch_path = session.workspace.file("capture", suffix=".pcm")

        speech_announced = False
        silence_announced = False
        overrun_announced = False
        last_frame_at = self.clock.monotonic()

        while True:
            if session.cancellation.cancelled:
                return "cancelled"
            if session.stop_requested.is_set():
                return session.stop_reason or "manual-stop"

            chunk = handle.read(timeout=0.05)
            now = self.clock.monotonic()
            if chunk:
                last_frame_at = now
                if not session.measurement.first_frame_at:
                    session.measurement.first_frame_at = now
                session.hasher.update(chunk)
                state = detector.feed(chunk)
                session.measurement.peak_buffered_bytes = max(
                    session.measurement.peak_buffered_bytes,
                    handle.buffer.buffered_bytes,
                )
                if state.speech_detected and not speech_announced:
                    speech_announced = True
                    session.measurement.speech_detected_at = now
                    self._emit(session, "speech_detected", {
                        "positionSeconds": state.to_json()["positionSeconds"],
                        "noiseFloor": state.to_json()["noiseFloor"],
                    })
                if streaming and session.recognition is not None:
                    self._feed_streaming(session, chunk, state, decision)
                elif session.batch_path is not None:
                    with open(session.batch_path, "ab") as sink:
                        sink.write(chunk)
                if handle.buffer.overran and not overrun_announced:
                    overrun_announced = True
                    self._degrade(
                        session, "input-overrun", "capture",
                        f"{handle.buffer.dropped_bytes} bytes arrived faster than "
                        "recognition consumed them and were dropped; partial "
                        "transcripts may lag, final recognition covers what was kept",
                    )
                if state.ended:
                    if not silence_announced and state.end_reason in (
                        "initial-silence", "endpoint-silence",
                    ):
                        silence_announced = True
                        self._emit(session, "silence_detected", {
                            "endReason": state.end_reason,
                            "positionSeconds": state.to_json()["positionSeconds"],
                        })
                    return state.end_reason
            else:
                if not handle.running():
                    if handle.buffer.exhausted:
                        return "maximum-duration"
                    return "device-lost"
                if now - last_frame_at > STALL_SECONDS:
                    # Alive and delivering nothing: the transport stalled. A
                    # silent room still delivers zeros on schedule; this is
                    # §17's device loss wearing a quieter face.
                    return "device-lost"

    def _feed_streaming(
        self, session: CaptureSession, chunk: bytes, state: Any, decision: Any
    ) -> None:
        recognition = session.recognition
        if recognition is None:
            return
        try:
            partial = recognition.accept(
                chunk, position_seconds=state.position_seconds
            )
        except Exception as exc:  # noqa: BLE001 - a recogniser fault mid-stream
            self._degrade(
                session, "recognizer-failure", "recognition",
                f"the recogniser faulted on submitted frames: {type(exc).__name__}",
            )
            return
        if partial is None:
            return
        request = session.request
        wanted = (
            request.partial_transcripts
            and decision.partial_transcripts_permitted
            and not session.partials_suppressed
        )
        if not wanted:
            return
        if session.partials_emitted >= MAX_PARTIALS_PER_CAPTURE:
            session.partials_suppressed = True
            self._degrade(
                session, "partial-transcripts-suppressed", "recognition",
                f"{MAX_PARTIALS_PER_CAPTURE} partial transcripts were emitted; the "
                "rest are suppressed and final recognition is unaffected",
            )
            return
        session.partials_emitted += 1
        session.last_partial = partial
        if not session.measurement.first_partial_at:
            session.measurement.first_partial_at = self.clock.monotonic()
        self._emit(session, "partial_transcript", partial.to_json())

    def _drain(self, session: CaptureSession, *, streaming: bool) -> None:
        """Everything still buffered when capture stopped, into its consumer."""
        handle = session.handle
        if handle is None:
            return
        while True:
            chunk = handle.read(timeout=0.0)
            if not chunk:
                return
            session.hasher.update(chunk)
            if streaming and session.recognition is not None:
                try:
                    session.recognition.accept(chunk)
                except Exception:  # noqa: BLE001 - the final flush decides
                    return
            elif session.batch_path is not None:
                with open(session.batch_path, "ab") as sink:
                    sink.write(chunk)

    # ----------------------------------------------------------------- #

    def _finalize(self, session: CaptureSession, *, streaming: bool, ending: str) -> None:
        request = session.request
        self._emit(session, "recognition_finalizing", {"captureEnding": ending})
        session.phase = "finalizing"
        recognition = session.recognition
        try:
            if not streaming:
                recognition = self._recognize_batch(session)
            assert recognition is not None
            final = recognition.finish()
        except Exception as exc:  # noqa: BLE001 - recognition failure is an ending
            self._emit(session, "recognition_failed", {
                "detail": f"{type(exc).__name__}: recognition did not produce a transcript",
                "retryAvailable": True,
                "typedInputPreserved": True,
            })
            self._settle(session, "failed", "recognition failed; retry or type instead")
            return
        finally:
            # §8: the audio exists for active recognition and no longer.
            if session.workspace is not None:
                session.workspace.close()
                session.workspace = None
                session.batch_path = None

        if session.cancellation.cancelled:
            # §16: the recogniser finished while the cancellation arrived. The
            # answer exists and is discarded: a person who said "never mind"
            # while the machine was still thinking did not ask for a
            # transcript, and offering one anyway would be the machine
            # overriding the newer instruction with the older one.
            self._finish_cancelled(session)
            return

        if not final.text.strip():
            self._settle(session, "no-speech", "recognition heard nothing it could transcribe")
            return

        digest = f"sha256:{session.hasher.hexdigest()}" if session.hasher else ""
        try:
            final = replace(
                final,
                audio_digest=digest,
                recognition_mode="streaming" if streaming else "batch",
                text_digest="",
            )
        except TranscriptError:
            self._settle(session, "failed", "the transcript could not be held; retry or type instead")
            return
        session.measurement.final_transcript_at = self.clock.monotonic()

        preferences = self.policy.preferences
        immediate = (
            not request.confirmation_required
            and preferences.allow_immediate_submission
        )
        held, refusal = self.ledger.hold(
            final,
            cancellation_token=request.cancellation_token,
            immediate=immediate,
        )
        if held is None:
            self._settle(session, "failed", refusal)
            return
        self._emit(session, "final_transcript", {
            **final.to_json(),
            "immediateSubmission": immediate,
        })
        if not immediate:
            self._emit(session, "transcript_confirmation_requested", {
                "requestId": request.request_id,
                "textDigest": final.text_digest,
                "expiresAtMonotonic": held.expires_at_monotonic,
                "editable": True,
                "retryAvailable": True,
            })
        self._settle(session, "completed", "a final transcript is waiting for the user")

    def _recognize_batch(self, session: CaptureSession) -> RecognitionSession:
        """The batch path: recognise the private capture file, then delete it."""
        request = session.request
        selection = self.registry.select(request, monotonic=self.clock.monotonic())
        if not selection.selected:
            raise RuntimeError(selection.detail)
        recognition = selection.recognizer.start(request)
        session.recognition = recognition
        path = session.batch_path
        if path is not None:
            position = 0.0
            bytes_per_second = request.bytes_per_second
            with open(path, "rb") as source:
                while True:
                    chunk = source.read(65536)
                    if not chunk:
                        break
                    position += len(chunk) / bytes_per_second
                    recognition.accept(chunk, position_seconds=position)
        return recognition

    # ----------------------------------------------------------------- #

    def _finish_cancelled(self, session: CaptureSession) -> None:
        recognition = session.recognition
        if recognition is not None:
            try:
                recognition.cancel()
            except Exception:  # noqa: BLE001
                pass
        self._emit(session, "speech_input_cancelled", {
            "reason": session.cancellation.reason or "cancelled",
            "audioDiscarded": True,
            "taskCreated": False,
        })
        # §19: resuming paused narration is explicitly safe here — no task was
        # created and the user's last act was "never mind".
        record = self.coordinator.release(resume_paused=True)
        self._settle(
            session, "cancelled",
            session.cancellation.reason or "cancelled",
            coordination=record,
        )

    def _finish_device_lost(self, session: CaptureSession, *, streaming: bool) -> None:
        """§17, in §17's order. The device is already closed by the caller."""
        request = session.request
        handle = session.handle
        self._degrade(
            session, "device-removed-during-capture", "capture",
            "the capture device stopped delivering frames mid-capture",
        )
        self._emit(session, "device_lost", {
            "backendId": handle.backend_id if handle else "",
            "deviceId": handle.device_id if handle else "",
            "typedInputPreserved": True,
            "retryAvailable": True,
        })
        if handle is not None:
            self.router.penalise(
                handle.backend_id,
                kind="device-removed-during-capture",
                detail="the recorder exited while capture was wanted",
                request_id=request.request_id,
            )

        # A safe provisional transcript, preserved as explicitly incomplete
        # (§17.6) — and only from the streaming path, where the recogniser
        # already holds the frames. The batch file is removed unrecognised:
        # running a model over a truncated recording nobody asked to keep is
        # not preservation, it is guessing.
        preserved = False
        recognition = session.recognition
        if streaming and recognition is not None:
            try:
                final = recognition.finish()
                if final.text.strip():
                    final = replace(final, incomplete=True, text_digest="")
                    held, _refusal = self.ledger.hold(
                        final, cancellation_token=request.cancellation_token,
                    )
                    if held is not None:
                        preserved = True
                        self._emit(session, "final_transcript", {
                            **final.to_json(),
                            "immediateSubmission": False,
                        })
                        self._emit(session, "transcript_confirmation_requested", {
                            "requestId": request.request_id,
                            "textDigest": final.text_digest,
                            "incomplete": True,
                            "editable": True,
                            "retryAvailable": True,
                        })
            except Exception:  # noqa: BLE001 - preservation is best-effort
                preserved = False
        self._settle(
            session, "device-lost",
            "the input device was lost; "
            + ("a partial transcript is held as incomplete" if preserved
               else "no transcript could be preserved")
            + "; typed input remains available and no task was created",
        )

    def _fail_before_open(
        self,
        session: CaptureSession,
        kind: str,
        detail: str,
        *,
        indicator_cleared: bool = False,
    ) -> None:
        """A refusal after the thread started and before the device opened."""
        del indicator_cleared
        self._degrade(session, kind, "activation", detail)
        self._settle(session, "refused", detail)

    def _clear_indicator(self, session: CaptureSession, *, capture_closed: bool) -> None:
        cleared, reason = self.indicator.clear(
            session.request.request_id, capture_closed=capture_closed
        )
        if cleared:
            session.measurement.indicator_cleared_at = self.clock.monotonic()
            self._emit(session, "indicator_cleared", {})
        elif reason != "the indicator was not raised":
            self._degrade(session, "indicator-unavailable", "teardown", reason)

    def _settle(
        self,
        session: CaptureSession,
        disposition: str,
        detail: str,
        *,
        coordination: CoordinationRecord | None = None,
    ) -> None:
        """Record the outcome once, everywhere it has to be recorded."""
        session.disposition = disposition
        session.detail = detail
        session.phase = "settled"
        session.measurement.settled_at = self.clock.monotonic()
        if coordination is None and disposition != "cancelled":
            # §19: never resumed on the paths that may have created a task.
            coordination = self.coordinator.release(resume_paused=False)
        if self.journal is not None:
            self.journal.record_settle(
                session.request.request_id, disposition,
                monotonic=self.clock.monotonic(),
            )
        self._record(session.request.request_id, disposition, detail)
        if disposition in ("refused", "failed", "expired"):
            self._emit(session, "recognition_failed" if disposition == "failed"
                       else "speech_input_cancelled", {
                "disposition": disposition,
                "detail": detail,
                "typedInputPreserved": True,
                "taskCreated": False,
            })

    def _degrade(self, session: CaptureSession, kind: str, stage: str, detail: str) -> None:
        record = self.router.record(CaptureDegradation(
            kind=kind,
            stage=stage,
            detail=detail,
            request_id=session.request.request_id,
            at_monotonic=self.clock.monotonic(),
        ))
        self._emit(session, "speech_input_degraded", record.to_json())

    def _record(self, request_id: str, disposition: str, detail: str) -> None:
        with self._guard:
            self._records.append({
                "requestId": request_id,
                "disposition": disposition,
                "detail": detail,
                "atMonotonic": self.clock.monotonic(),
            })
            if len(self._records) > 128:
                del self._records[:-128]

    # ----------------------------------------------------------------- #
    # Events
    # ----------------------------------------------------------------- #

    def _emit(self, session: CaptureSession, kind: str, payload: Mapping[str, Any]) -> None:
        request = session.request
        self.emit_external(
            kind,
            request_id=request.request_id,
            session_id=request.session_id,
            payload=payload,
            privacy_classification=request.privacy_classification,
            presentation_revision=request.presentation_revision,
            producer="capture-worker",
        )

    def emit_external(
        self,
        kind: str,
        *,
        request_id: str,
        session_id: str,
        payload: Mapping[str, Any],
        privacy_classification: str = "personal",
        presentation_revision: int = 0,
        producer: str = "speech-service",
    ) -> None:
        """One event into this worker's stream from outside a capture.

        Confirmation and rejection happen after the capture thread has ended,
        and their events belong in the same ordered, per-request stream the
        capture's own events used — same sequence counter, same ring, same
        subscribers — or a client replaying the stream would see a confirmation
        it cannot order against the transcript it confirms.
        """
        with self._guard:
            sequence = self._sequences.get(request_id, 0) + 1
            self._sequences[request_id] = sequence
            if len(self._sequences) > 512:
                for key in list(self._sequences)[:128]:
                    self._sequences.pop(key, None)
        event = SpeechInputEvent(
            kind=kind,
            request_id=request_id,
            session_id=session_id,
            sequence=sequence,
            at_wall=self.clock.wall(),
            at_monotonic=self.clock.monotonic(),
            producer=producer,
            privacy_classification=privacy_classification,
            presentation_revision=presentation_revision,
            payload=dict(payload),
        )
        with self._guard:
            # Partials are delivered live and not retained: a bounded ring
            # full of provisional text would push out the events a person
            # wants to read, and a subscriber that wants them already has them.
            if kind != "partial_transcript":
                self._events.append(event)
                if len(self._events) > 256:
                    del self._events[:-256]
            observers = list(self._observers)
        for observer in observers:
            try:
                observer(event)
            except Exception:  # noqa: BLE001 - a broken subscriber must not stop capture
                continue

    def subscribe(self, observer: Callable[[SpeechInputEvent], None]) -> None:
        with self._guard:
            self._observers.append(observer)

    def events(self, *, limit: int = 64) -> tuple[SpeechInputEvent, ...]:
        with self._guard:
            return tuple(self._events[-max(1, limit):])

    def measurement(self, request_id: str) -> CaptureMeasurement | None:
        with self._guard:
            return self._measurements.get(request_id)

    # ----------------------------------------------------------------- #
    # Lifecycle
    # ----------------------------------------------------------------- #

    def drain(self, *, timeout: float = 30.0) -> bool:
        """Wait until no capture is running. A barrier for slices and tests."""
        import time as _time

        deadline = _time.monotonic() + timeout
        while _time.monotonic() < deadline:
            with self._guard:
                session = self._current
            if session is None:
                return True
            thread = session.thread
            if thread is not None:
                thread.join(timeout=0.05)
            else:  # pragma: no cover - a session always has its thread
                _time.sleep(0.02)
        with self._guard:
            return self._current is None

    def close(self, *, timeout: float = 10.0) -> bool:
        """Stop listening and release everything. §2's restartability's other half."""
        with self._guard:
            self._closed = True
            session = self._current
        if session is not None:
            session.cancellation.cancel("the capture worker is stopping")
            thread = session.thread
            if thread is not None:
                thread.join(timeout=timeout)
        with self._guard:
            leftover = self._current
            self._current = None
        if leftover is not None:
            # The thread did not reach its own ``finally``. Releasing here is
            # the difference between a bounded stop and a stranded recorder.
            leftover.release()
        return True

    @property
    def active(self) -> bool:
        with self._guard:
            return self._current is not None

    def status(self) -> dict[str, Any]:
        """Everything §20's ``speech_input_status`` answers and §23 counts."""
        with self._guard:
            session = self._current
            records = list(self._records[-16:])
            captures = self._captures
        current: dict[str, Any] | None = None
        if session is not None:
            handle = session.handle
            current = {
                "requestId": session.request.request_id,
                "sessionId": session.request.session_id,
                "activationSource": session.request.activation_source,
                "phase": session.phase,
                "cancelled": session.cancellation.cancelled,
                "bytesCaptured": handle.bytes_captured if handle else 0,
                "bufferedBytes": handle.buffer.buffered_bytes if handle else 0,
                "partialsEmitted": session.partials_emitted,
                "partialText": (
                    session.last_partial.text if session.last_partial is not None else ""
                ),
                "partialRevision": (
                    session.last_partial.revision if session.last_partial is not None else 0
                ),
                "deviceId": handle.device_id if handle else "",
                "backendId": handle.backend_id if handle else "",
            }
        return {
            "capturing": current is not None,
            "current": current,
            "capturesServed": captures,
            "indicator": self.indicator.describe(),
            "recentDispositions": records,
            "decision": self.policy.decision.to_json(),
            "boundaries": {
                "microphoneOpensOnExplicitActionOnly": True,
                "indicatorBeforeOpen": True,
                "indicatorClearedAfterClose": True,
                "mayCreateTask": False,
                "mayResolveApprovals": False,
                "mayExecuteTools": False,
                "mayChangeTaskState": False,
                "remoteTransmission": False,
                "wakeWordSupported": False,
                "continuousListeningSupported": False,
                "voiceBiometricsSupported": False,
                "speakerIdentificationSupported": False,
                "rawAudioRetainedByDefault": False,
            },
        }
