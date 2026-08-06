# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The one door between speech-input events and the character's posture.

The mirror of :mod:`companion.character.speech_link`, for the other direction
of audio — and the first rule is the asymmetry §18 states: **microphone input
never drives the mouth.** Speaking visemes mean "the companion is talking";
lighting them while the *user* talks would be the character mouthing along
with somebody else's words. So this link never touches
:meth:`~companion.character.surface.CharacterPresenter.start_lip_sync` — the
method is not called anywhere in this file, and the §18 test asserts exactly
that — and what it produces instead is a :class:`ListeningPosture`: the three
flags the presenter's own mapper already models as first-class character
states (``listening``, ``transcribing``, ``waiting_for_user``), with their
fallback chains and their accessibility descriptions.

The second rule is §18's last sentence: **renderer failure must not stop
capture.** Everything here runs on the capture worker's thread up to the
deciding, and hands the survivor to ``dispatch`` — ``GLib.idle_add`` under a
compositor, direct invocation in a test. A draw that raises is counted and
swallowed; the worker never learns. The persistent text indicator
(:mod:`companion.speech.indicator`) is authoritative throughout, which is why
this link may be absent, broken or restarted without §5 noticing.

Ordering and staleness follow the viseme link's discipline: per-request
sequences are monotonic, a posture for a request that has settled is dropped
under a named reason, and the closed set of reasons is what turns "the
character did not react" into a diagnosable fact.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import threading
import time
from typing import Any, Callable

__all__ = [
    "LISTENING_REJECTION_REASONS",
    "ListeningLink",
    "ListeningLinkReport",
    "ListeningPosture",
]

#: Why a posture change was not applied. Closed, for the same reason every
#: rejection vocabulary here is.
LISTENING_REJECTION_REASONS = (
    "stale-request",
    "out-of-order",
    "after-settled",
    "renderer-absent",
    "renderer-failed",
    "link-closed",
    "unknown-event",
)

#: Which event kinds move the posture, and where to. Anything not named here
#: is not the renderer's business — a partial transcript changes the *text*
#: surface, not the character's pose.
_POSTURES: dict[str, str] = {
    "microphone_indicator_raised": "listening",
    "microphone_opened": "listening",
    "capture_started": "listening",
    "speech_detected": "listening",
    "capture_stopped": "transcribing",
    "recognition_finalizing": "transcribing",
    "final_transcript": "waiting-for-user",
    "transcript_confirmation_requested": "waiting-for-user",
    "transcript_confirmed": "neutral",
    "transcript_rejected": "neutral",
    "speech_input_cancelled": "neutral",
    "device_lost": "neutral",
    "recognition_failed": "neutral",
    "indicator_cleared": None,  # type: ignore[dict-item]  # keeps current posture
}

#: Postures that end a request's story. A posture event for a request in this
#: state arrived late and is refused as such.
_TERMINAL = ("neutral",)


@dataclass(frozen=True)
class ListeningPosture:
    """What the character should look like about the microphone, right now."""

    posture: str
    request_id: str
    sequence: int
    at_monotonic: float

    @property
    def listening(self) -> bool:
        return self.posture == "listening"

    @property
    def transcribing(self) -> bool:
        return self.posture == "transcribing"

    @property
    def waiting_for_user(self) -> bool:
        return self.posture == "waiting-for-user"

    def to_json(self) -> dict[str, Any]:
        return {
            "posture": self.posture,
            "requestId": self.request_id,
            "sequence": self.sequence,
            "atMonotonic": self.at_monotonic,
            "listening": self.listening,
            "transcribing": self.transcribing,
            "waitingForUser": self.waiting_for_user,
        }


@dataclass
class ListeningLinkReport:
    """What the link did, in a shape a gate can assert on."""

    applied: int = 0
    held: int = 0
    rejected: dict[str, int] = field(default_factory=dict)
    postures_seen: set[str] = field(default_factory=set)
    neutral_returns: int = 0
    renderer_failures: int = 0

    def to_json(self) -> dict[str, Any]:
        return {
            "applied": self.applied,
            "held": self.held,
            "rejected": dict(sorted(self.rejected.items())),
            "rejectedTotal": sum(self.rejected.values()),
            "posturesSeen": sorted(self.postures_seen),
            "neutralReturns": self.neutral_returns,
            "rendererFailures": self.renderer_failures,
            "lipSyncDriven": False,
        }


class ListeningLink:
    """Carries speech-input events to one renderer's posture.

    ``draw`` receives every applied :class:`ListeningPosture` on the dispatch
    thread; under GTK it calls
    :meth:`companion.character.surface.CharacterPresenter.update` with the
    current canonical projection and the posture's flags. ``draw`` is optional,
    exactly as the viseme link's presenter is: with none attached the link
    still validates, orders and counts, which is what makes "renderer absent"
    a tested case rather than a crash.
    """

    def __init__(
        self,
        *,
        draw: Callable[[ListeningPosture], None] | None = None,
        dispatch: Callable[[Callable[[], None]], Any] | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self._draw = draw
        self._dispatch = dispatch or (lambda action: action())
        self._now = monotonic or time.monotonic
        self._guard = threading.RLock()
        self._closed = False
        self._request_id = ""
        self._sequence = -1
        self._settled: set[str] = set()
        self._posture = "neutral"
        self.report = ListeningLinkReport()
        self.last_posture: ListeningPosture | None = None

    # ----------------------------------------------------------------- #

    def on_speech_event(self, event: Any) -> None:
        """Called from the capture worker's thread. Never raises at the worker."""
        try:
            self._handle(event)
        except Exception:  # noqa: BLE001 - a broken renderer must not stop capture
            with self._guard:
                self.report.renderer_failures += 1
            self._reject("renderer-failed")

    def _handle(self, event: Any) -> None:
        kind = str(getattr(event, "kind", ""))
        if kind not in _POSTURES:
            # Not the renderer's business; not an error either. Partial
            # transcripts, degradations and the rest change other surfaces.
            return
        posture = _POSTURES[kind]
        request_id = str(getattr(event, "request_id", ""))
        sequence = int(getattr(event, "sequence", 0))

        with self._guard:
            if self._closed:
                self._reject("link-closed", locked=True)
                return
            if request_id in self._settled and posture not in (None, *_TERMINAL):
                self._reject("after-settled", locked=True)
                return
            if request_id != self._request_id:
                if posture in _TERMINAL or posture is None:
                    # A late terminal event for a request that is no longer
                    # current changes nothing on screen.
                    self._reject("stale-request", locked=True)
                    return
                # A new capture takes the link over; the old request is done
                # whether or not its terminal event was seen.
                if self._request_id:
                    self._settled.add(self._request_id)
                    if len(self._settled) > 256:
                        self._settled = set(list(self._settled)[-128:])
                self._request_id = request_id
                self._sequence = -1
            if sequence <= self._sequence:
                self._reject("out-of-order", locked=True)
                return
            self._sequence = sequence
            if posture is None:
                self.report.held += 1
                return
            if posture == self._posture:
                self.report.held += 1
                return
            self._posture = posture
            if posture in _TERMINAL:
                self._settled.add(request_id)
                self.report.neutral_returns += 1
            self.report.applied += 1
            self.report.postures_seen.add(posture)
            applied = ListeningPosture(
                posture=posture,
                request_id=request_id,
                sequence=sequence,
                at_monotonic=self._now(),
            )
            self.last_posture = applied
            draw = self._draw

        if draw is None:
            self._reject("renderer-absent")
            return

        def _paint() -> None:
            try:
                draw(applied)
            except Exception:  # noqa: BLE001 - a renderer fault is not a capture fault
                self._reject("renderer-failed")
                with self._guard:
                    self.report.renderer_failures += 1

        self._dispatch(_paint)

    # ----------------------------------------------------------------- #

    def restart_renderer(self, draw: Callable[[ListeningPosture], None] | None) -> str:
        """Point the link at a new renderer. The posture resets to neutral.

        A renderer that restarted mid-capture does not know what the character
        was doing; neutral is the honest starting point, and the next event
        moves it. The *capture* is unaffected — §18's renderer-failure rule,
        exercised by the §16 GTK-restart race test.
        """
        with self._guard:
            self._draw = draw
            self._posture = "neutral"
            request_id = self._request_id
        posture = ListeningPosture(
            posture="neutral", request_id=request_id, sequence=self._sequence,
            at_monotonic=self._now(),
        )
        with self._guard:
            self.last_posture = posture
        if draw is not None:
            try:
                self._dispatch(lambda: draw(posture))
            except Exception:  # noqa: BLE001
                pass
        return "reset-to-neutral"

    def close(self) -> None:
        """Neutral, then nothing. Safe twice and safe after a fault."""
        with self._guard:
            if self._closed:
                return
            self._closed = True
            draw = self._draw
            self._draw = None
            request_id = self._request_id
            was_neutral = self._posture == "neutral"
            self._posture = "neutral"
        if draw is not None and not was_neutral:
            posture = ListeningPosture(
                posture="neutral", request_id=request_id, sequence=self._sequence,
                at_monotonic=self._now(),
            )
            try:
                draw(posture)
            except Exception:  # noqa: BLE001 - teardown never raises
                pass

    def _reject(self, reason: str, *, locked: bool = False) -> None:
        if reason not in LISTENING_REJECTION_REASONS:  # pragma: no cover - closed set
            reason = "renderer-failed"
        if locked:
            self.report.rejected[reason] = self.report.rejected.get(reason, 0) + 1
            return
        with self._guard:
            self.report.rejected[reason] = self.report.rejected.get(reason, 0) + 1

    def describe(self) -> dict[str, Any]:
        with self._guard:
            return {
                "requestId": self._request_id,
                "posture": self._posture,
                "closed": self._closed,
                "rendererAttached": self._draw is not None,
                "lastPosture": self.last_posture.to_json() if self.last_posture else None,
                "report": self.report.to_json(),
                "drivesLipSync": False,
                "textIndicatorAuthoritative": True,
                "rendererFailureStopsCapture": False,
            }
