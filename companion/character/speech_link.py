# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The one door between voice-produced visemes and the character's mouth.

Before this existed the two halves were both finished and never joined. The
voice worker measured amplitude envelopes and emitted an ordered viseme stream;
the renderer had a :class:`~companion.character.lipsync.LipSyncController` and a
mouth-shape map; and the only thing that had ever driven the second from the
first was a *fabricated* timeline in a test. "Visemes work" and "the mouth
moves" were two separate claims with nothing between them.

What this module is, precisely:

* it subscribes to :class:`companion.voice.worker.VoiceWorker` events and drives
  a :class:`companion.character.surface.CharacterPresenter`. Nothing flows the
  other way. The renderer cannot cancel speech, cannot change a task and cannot
  reach the voice runtime — it receives frames and draws them;
* the timeline it feeds the controller is the worker's own, carried by the
  ``viseme_timeline`` event. Rebuilding it here would be a second interpretation
  of the audio, which is the mistake the integration phase spent itself
  removing one layer up;
* **captions are not its business.** §8: the caption is authoritative and speech
  is an optional second rendering, so the mouth is an optional third. Every
  rejection below drops a *frame* and nothing else, and there is no path from
  here to a caption, a task or an approval.

**Two threads meet here.** The worker calls :meth:`on_voice_event` from its own
thread; GTK may only be touched from the main loop. So this class does the
deciding — ordering, staleness, bounds — on the calling thread and hands the
survivor to ``dispatch``, which is ``GLib.idle_add`` under a compositor and
direct invocation in a test. Nothing is scheduled with a timer: a mouth driven
by a timer is a resource that outlives whatever created it, and §5 asks that
none survive teardown.

**Every rejection has a name.** A frame that is dropped is counted under a
reason, and the reasons are a closed set, because "the mouth did not move" and
"the mouth did not move because a viseme arrived after the utterance was
cancelled" are different facts and only the second one is useful.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import threading
from typing import Any, Callable, Mapping, Sequence

from .lipsync import LipSyncEvent, LipSyncStatus, MouthShape

__all__ = [
    "MAX_FRAMES_PER_REQUEST",
    "REJECTION_REASONS",
    "MouthFrame",
    "VisemeLink",
    "VisemeLinkReport",
]

#: The most mouth frames one utterance may draw. Forty a second for a minute is
#: 2400; this is comfortably above any real utterance and far below anything
#: that could hold a main loop. A stream past it is not a long utterance, it is
#: a runaway producer, and the mouth stops moving rather than the loop stopping
#: running.
MAX_FRAMES_PER_REQUEST = 4096

#: Why a frame was not drawn. Closed, because a surface reporting "some frames
#: were dropped" tells nobody anything.
REJECTION_REASONS = (
    "no-active-request",
    "stale-request",
    "out-of-order",
    "duplicate",
    "after-cancellation",
    "after-completion",
    "stale-revision",
    "count-exceeded",
    "unsupported-shape",
    "renderer-absent",
    "renderer-failed",
    "link-closed",
)


@dataclass(frozen=True)
class MouthFrame:
    """One mouth shape, at one moment, for one request. What the renderer draws."""

    request_id: str
    sequence: int
    shape: str
    source: str
    position_ms: int
    drift_ms: int
    #: The presentation revision in force when this frame was accepted. A
    #: renderer that redrew from a newer projection and then applied an older
    #: frame would be showing two answers at once.
    revision: int
    at_monotonic: float
    #: ``timeline``, ``neutral-on-completion``, ``neutral-on-cancellation``,
    #: ``neutral-on-teardown`` or ``neutral-on-restart``.
    origin: str = "timeline"

    @property
    def neutral(self) -> bool:
        return self.shape == MouthShape.NEUTRAL.value

    def to_json(self) -> dict[str, Any]:
        return {
            "requestId": self.request_id,
            "sequence": self.sequence,
            "mouthShape": self.shape,
            "sourceMethod": self.source,
            "positionMs": self.position_ms,
            "driftMs": self.drift_ms,
            "revision": self.revision,
            "atMonotonic": self.at_monotonic,
            "origin": self.origin,
        }


@dataclass
class VisemeLinkReport:
    """What the link did, in a shape a gate can assert on."""

    accepted: int = 0
    drawn: int = 0
    rejected: dict[str, int] = field(default_factory=dict)
    distinct_shapes: set[str] = field(default_factory=set)
    requests: list[str] = field(default_factory=list)
    neutral_returns: int = 0
    maximum_drift_ms: int = 0
    renderer_failures: int = 0

    def to_json(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "drawn": self.drawn,
            "rejected": dict(sorted(self.rejected.items())),
            "rejectedTotal": sum(self.rejected.values()),
            "distinctShapes": sorted(self.distinct_shapes),
            "distinctNonNeutralShapes": sorted(
                self.distinct_shapes - {MouthShape.NEUTRAL.value}
            ),
            "requests": list(self.requests),
            "neutralReturns": self.neutral_returns,
            "maximumDriftMs": self.maximum_drift_ms,
            "rendererFailures": self.renderer_failures,
        }


class VisemeLink:
    """Carries the worker's viseme stream to one presenter's mouth.

    ``draw`` receives every accepted :class:`MouthFrame` on the dispatch thread
    and is where a GTK widget is actually touched. ``presenter`` is optional:
    with none, the link still validates, orders and counts, which is what makes
    "renderer absent" a case that is *tested* rather than a crash.
    """

    def __init__(
        self,
        *,
        presenter: Any = None,
        draw: Callable[[MouthFrame], None] | None = None,
        dispatch: Callable[[Callable[[], None]], Any] | None = None,
        monotonic: Callable[[], float] | None = None,
        maximum_frames: int = MAX_FRAMES_PER_REQUEST,
    ) -> None:
        self.presenter = presenter
        self._draw = draw
        # Direct invocation by default. Under a compositor the caller passes
        # ``GLib.idle_add``; the choice belongs to whoever owns the main loop,
        # not to this module, which must stay importable with no GTK present.
        self._dispatch = dispatch or (lambda action: action())
        self._now = monotonic or __import__("time").monotonic
        self._maximum = maximum_frames

        self._guard = threading.RLock()
        self._closed = False
        self._request_id = ""
        self._sequence = -1
        self._count = 0
        self._active = False
        self._completed: set[str] = set()
        self._cancelled: set[str] = set()
        self._revision = 0
        self._frame_revision = 0
        self.report = VisemeLinkReport()
        self.last_frame: MouthFrame | None = None
        self.frames: list[MouthFrame] = []
        #: Bounded: a long-running service must not grow a frame log.
        self.history_limit = 4096

    # ----------------------------------------------------------------- #
    # Presentation revision
    # ----------------------------------------------------------------- #

    @property
    def revision(self) -> int:
        with self._guard:
            return self._revision

    def publish(self, revision: int) -> None:
        """Tell the link which projection the renderer is currently showing.

        A frame accepted under an older revision is dropped rather than drawn.
        The renderer redraws the whole character when the projection moves — a
        new phase, a new animation, a new expression — and a mouth shape
        computed against what it was showing a moment ago would be composited on
        top of a picture that has already moved on.
        """
        with self._guard:
            self._revision = int(revision)

    # ----------------------------------------------------------------- #
    # The worker's side
    # ----------------------------------------------------------------- #

    def on_voice_event(self, event: Any) -> None:
        """Called from the voice worker's thread. Never raises at the worker."""
        try:
            handler = getattr(self, "_on_" + str(event.kind), None)
            if handler is not None:
                handler(event)
        except Exception:  # noqa: BLE001 - a broken renderer must not stop speech
            self._reject("renderer-failed")
            with self._guard:
                self.report.renderer_failures += 1

    def _on_viseme_timeline(self, event: Any) -> None:
        payload: Mapping[str, Any] = event.payload
        events = self._lipsync_events(payload.get("events", ()))
        with self._guard:
            if self._closed:
                self._reject("link-closed", locked=True)
                return
            self._request_id = str(payload.get("requestId") or event.request_id)
            self._sequence = -1
            self._count = 0
            self._active = True
            self._frame_revision = self._revision
            self._cancelled.discard(self._request_id)
            self._completed.discard(self._request_id)
            if self._request_id not in self.report.requests:
                self.report.requests.append(self._request_id)
            presenter = self.presenter
        if presenter is not None:
            # The controller's own start. Its drift arithmetic and its shape
            # fallback are what this timeline is being handed to; recomputing
            # either here would be a second answer to a question that already
            # has one.
            presenter.start_lip_sync(events)

    def _on_viseme(self, event: Any) -> None:
        payload: Mapping[str, Any] = event.payload
        request_id = str(payload.get("requestId") or event.request_id)
        sequence = int(payload.get("sequence", 0))
        position_ms = int(payload.get("positionMs", 0))
        drift_ms = int(payload.get("driftMs", 0))
        shape = str(payload.get("mouthShape", MouthShape.NEUTRAL.value))
        source = str(payload.get("sourceMethod", ""))

        with self._guard:
            reason = self._admit(request_id, sequence)
            if reason:
                self._reject(reason, locked=True)
                return
            self._sequence = sequence
            self._count += 1
            revision = self._frame_revision
            self.report.accepted += 1
            self.report.maximum_drift_ms = max(self.report.maximum_drift_ms, abs(drift_ms))
            presenter = self.presenter

        status: LipSyncStatus | None = None
        if presenter is not None:
            if not self._package_supports(presenter, shape):
                # Recorded before the controller substitutes, because after it
                # has there is nothing left to see. Not a rejection of the
                # frame: the mouth still moves, to the nearest shape this
                # character has an asset for, which is what §6 asks of a
                # character package that lacks one.
                self._reject("unsupported-shape")
            # The controller decides the shape actually drawn: it substitutes a
            # supported one for a shape this character package has no asset for,
            # and it holds neutral under reduced motion. Its answer is the one
            # drawn, because deriving a second shape here from the same timeline
            # would be two answers to one question.
            status = presenter.advance_lip_sync(position_ms, audio_clock_ms=position_ms + drift_ms)
            drawn_shape = status.shape.value
        else:
            drawn_shape = shape

        self._emit(MouthFrame(
            request_id=request_id, sequence=sequence, shape=drawn_shape, source=source,
            position_ms=position_ms, drift_ms=drift_ms, revision=revision,
            at_monotonic=self._now(), origin="timeline",
        ))

    def _on_mouth_neutral(self, event: Any) -> None:
        self._settle(event, "neutral-on-completion")

    def _on_speech_cancelled(self, event: Any) -> None:
        self._settle(event, "neutral-on-cancellation", cancelled=True)

    _on_speech_interrupted = _on_speech_cancelled

    def _on_speech_finished(self, event: Any) -> None:
        self._settle(event, "neutral-on-completion")

    _on_speech_failed = _on_speech_finished
    _on_speech_degraded = _on_speech_finished

    def _on_worker_stopped(self, event: Any) -> None:
        """A voice-worker restart returns the mouth to neutral, always.

        The worker that was speaking is gone; whatever it was mid-way through
        will never be finished, and a mouth left in the shape of half a syllable
        is the most visible symptom of a runtime that lost track of itself.
        """
        self._settle(event, "neutral-on-restart", cancelled=True)

    # ----------------------------------------------------------------- #

    def _settle(self, event: Any, origin: str, *, cancelled: bool = False) -> None:
        request_id = str(getattr(event, "request_id", "") or self._request_id)
        with self._guard:
            if cancelled and request_id:
                self._cancelled.add(request_id)
            elif request_id:
                self._completed.add(request_id)
            was_active = self._active
            self._active = False
            revision = self._frame_revision
            presenter = self.presenter
            if was_active or self.last_frame is None or not self.last_frame.neutral:
                self.report.neutral_returns += 1
            else:
                # Already neutral and already settled. Emitting again would be
                # harmless and would also make "did the mouth return to neutral"
                # a count nobody could interpret.
                return
        if presenter is not None:
            if cancelled:
                presenter.cancel_lip_sync("speech was interrupted")
            else:
                presenter.finish_lip_sync()
        self._emit(MouthFrame(
            request_id=request_id, sequence=-1, shape=MouthShape.NEUTRAL.value,
            source="", position_ms=0, drift_ms=0, revision=revision,
            at_monotonic=self._now(), origin=origin,
        ))

    def _admit(self, request_id: str, sequence: int) -> str:
        """Why this frame must not be drawn, or ``""``. Called under the guard."""
        if self._closed:
            return "link-closed"
        if request_id in self._cancelled:
            return "after-cancellation"
        if request_id in self._completed:
            return "after-completion"
        if not self._request_id:
            return "no-active-request"
        if request_id != self._request_id:
            return "stale-request"
        if not self._active:
            return "after-completion"
        if sequence == self._sequence:
            return "duplicate"
        if sequence < self._sequence:
            return "out-of-order"
        if self._count >= self._maximum:
            return "count-exceeded"
        if self._frame_revision != self._revision:
            return "stale-revision"
        return ""

    def _reject(self, reason: str, *, locked: bool = False) -> None:
        if reason not in REJECTION_REASONS:  # pragma: no cover - closed set
            reason = "renderer-failed"
        if locked:
            self.report.rejected[reason] = self.report.rejected.get(reason, 0) + 1
            return
        with self._guard:
            self.report.rejected[reason] = self.report.rejected.get(reason, 0) + 1

    def _emit(self, frame: MouthFrame) -> None:
        with self._guard:
            self.last_frame = frame
            self.frames.append(frame)
            if len(self.frames) > self.history_limit:
                del self.frames[: -self.history_limit]
            self.report.drawn += 1
            self.report.distinct_shapes.add(frame.shape)
            draw = self._draw

        if draw is None:
            self._reject("renderer-absent")
            return

        def _paint() -> None:
            try:
                draw(frame)
            except Exception:  # noqa: BLE001 - a renderer fault is not a speech fault
                self._reject("renderer-failed")
                with self._guard:
                    self.report.renderer_failures += 1

        self._dispatch(_paint)

    # ----------------------------------------------------------------- #

    def restart_renderer(self, presenter: Any, *, resume: bool = False) -> str:
        """Point the link at a new presenter. Returns what it decided.

        A renderer that restarts mid-utterance can either resume the timeline it
        was drawing or say plainly that it will not. This resumes only when the
        new presenter is handed the same timeline — which it is not, because the
        timeline arrived in an event that has already been consumed — so the
        honest answer is ``degraded-to-neutral``: the mouth goes neutral and
        stays there until the next utterance, and the caption is unaffected.

        ``resume=True`` is accepted and still degrades, so a caller asking for
        the behaviour this build does not have is told rather than silently
        given something else.
        """
        with self._guard:
            self.presenter = presenter
            self._active = False
            request_id = self._request_id
            revision = self._frame_revision
        self._emit(MouthFrame(
            request_id=request_id, sequence=-1, shape=MouthShape.NEUTRAL.value,
            source="", position_ms=0, drift_ms=0, revision=revision,
            at_monotonic=self._now(), origin="neutral-on-restart",
        ))
        return "degraded-to-neutral" if not resume else (
            "degraded-to-neutral: this build does not carry a timeline across a "
            "renderer restart, and resuming from an unknown position would be a "
            "mouth moving to timing nobody measured"
        )

    def close(self) -> None:
        """Neutral, then nothing. Safe twice and safe after a fault."""
        with self._guard:
            if self._closed:
                return
            already_neutral = self.last_frame is not None and self.last_frame.neutral
            self._closed = True
            self._active = False
            revision = self._frame_revision
            request_id = self._request_id
            presenter = self.presenter
        if presenter is not None:
            try:
                presenter.cancel_lip_sync("the link was closed")
            except Exception:  # noqa: BLE001 - teardown never raises
                pass
        if not already_neutral:
            frame = MouthFrame(
                request_id=request_id, sequence=-1, shape=MouthShape.NEUTRAL.value,
                source="", position_ms=0, drift_ms=0, revision=revision,
                at_monotonic=self._now(), origin="neutral-on-teardown",
            )
            with self._guard:
                self.last_frame = frame
                self.frames.append(frame)
                self.report.drawn += 1
                self.report.neutral_returns += 1
                draw = self._draw
            if draw is not None:
                try:
                    draw(frame)
                except Exception:  # noqa: BLE001 - teardown never raises
                    pass
        with self._guard:
            self._draw = None
            self.presenter = None

    # ----------------------------------------------------------------- #

    @staticmethod
    def _package_supports(presenter: Any, shape: str) -> bool:
        """Whether this character has an asset for this mouth shape.

        Asked of the controller's own supported set rather than inferred from
        what it drew. Comparing the requested shape with the drawn one *looks*
        like the same question and is not: the controller is at a playback
        position, the frame carries the worker's own idea of the shape at that
        position, and the two differ at the opening frame of every utterance
        without anything being unsupported at all.
        """
        controller = getattr(presenter, "controller", None)
        lip_sync = getattr(controller, "lip_sync", None)
        supported = getattr(lip_sync, "supported_shapes", None)
        if not supported:
            return True
        return shape in supported

    @staticmethod
    def _lipsync_events(events: Sequence[Mapping[str, Any]]) -> list[LipSyncEvent]:
        """The worker's wire form, back into the renderer's own event type.

        A shape the renderer does not know is dropped rather than guessed at:
        the controller substitutes a supported shape for an unsupported one, but
        it cannot do that for a name that is not a mouth shape at all.
        """
        result: list[LipSyncEvent] = []
        for item in events:
            try:
                shape = MouthShape(str(item.get("mouthShape")))
            except ValueError:
                continue
            source = str(item.get("sourceMethod", "amplitude"))
            try:
                result.append(LipSyncEvent(
                    timestamp_ms=max(0, int(item.get("offsetMs", 0))),
                    shape=shape,
                    source=source,
                ))
            except ValueError:
                continue
        return result

    def describe(self) -> dict[str, Any]:
        with self._guard:
            return {
                "requestId": self._request_id,
                "active": self._active,
                "closed": self._closed,
                "revision": self._revision,
                "frameRevision": self._frame_revision,
                "sequence": self._sequence,
                "count": self._count,
                "maximumFrames": self._maximum,
                "rendererAttached": self.presenter is not None,
                "lastFrame": self.last_frame.to_json() if self.last_frame else None,
                "report": self.report.to_json(),
                "captionsAuthoritative": True,
                "mouthMayChangeCaption": False,
                "mouthMayChangeTask": False,
            }
