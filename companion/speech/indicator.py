# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The indicator that makes listening visible, and the ordering that makes it true.

§4's required ordering puts the indicator *before* the microphone: validate,
reserve, **raise the indicator**, open, capture. §5 puts it after too: on any
ending, the indicator clears only once the capture handle has closed. Between
those two rules, there is no instant at which audio is being collected and the
screen says it is not — provided the rules are enforced rather than followed,
which is what this module is for.

Both rules are properties of this type:

* :meth:`ListeningIndicator.raise_for` returns whether the indicator is
  *actually showing* — either an attached in-process sink accepted it, or the
  out-of-process Bunny Shell supplied the positive presentation revision of
  the persistent MIC surface it raised before the request. A surface that
  cannot establish either fact makes the raise fail, and the worker reads a
  failed raise as "do not open the microphone", which is §4's sentence as a
  branch. Revision zero is never a surface attestation.
* :meth:`ListeningIndicator.clear` refuses to clear while the capture handle
  reports itself open. The worker passes the handle's own ``closed`` fact; a
  clear attempted early is refused and *counted*, because an ordering
  violation that is merely avoided is one test away from coming back.

What the indicator shows is §5's list, carried as data so every surface —
GTK, the CLI, a test — renders the same facts: listening state, device,
locality, provider, elapsed time, and whether audio is being retained (in
this build: never). The stop and cancel controls belong to the surface; the
indicator carries the request id they act on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import threading
from typing import Any, Callable, Protocol

from ..clock import Clock, SystemClock

__all__ = [
    "IndicatorSink",
    "IndicatorState",
    "ListeningIndicator",
]


@dataclass(frozen=True)
class IndicatorState:
    """Everything §5 requires the user to be shown, as one value."""

    listening: bool
    request_id: str = ""
    session_id: str = ""
    device_id: str = ""
    backend_id: str = ""
    #: ``local`` is the only value this build can produce. The field exists so
    #: a surface renders locality from data rather than assumption — and so
    #: the day a remote path existed, the indicator could not fail to say so.
    locality: str = "local"
    provider_id: str = ""
    #: A positive revision is an attestation from an out-of-process Bunny
    #: surface that it made the persistent listening indicator visible before
    #: requesting capture. In-process surfaces instead attach an
    #: :class:`IndicatorSink` and may leave this at zero.
    presentation_revision: int = 0
    started_at_monotonic: float = 0.0
    #: Always ``False`` in this build: audio is retained only for active
    #: recognition and deleted after (§8). Shown, not implied.
    audio_retained: bool = False

    def elapsed_seconds(self, monotonic_now: float) -> float:
        if not self.listening or not self.started_at_monotonic:
            return 0.0
        return max(0.0, monotonic_now - self.started_at_monotonic)

    def to_json(self, *, monotonic_now: float = 0.0) -> dict[str, Any]:
        return {
            "listening": self.listening,
            "requestId": self.request_id,
            "sessionId": self.session_id,
            "deviceId": self.device_id,
            "backendId": self.backend_id,
            "locality": self.locality,
            "providerId": self.provider_id,
            "presentationRevision": self.presentation_revision,
            "elapsedSeconds": round(self.elapsed_seconds(monotonic_now), 3),
            "audioRetained": self.audio_retained,
            "stopControl": "speech_input_stop",
            "cancelControl": "speech_input_cancel",
        }


class IndicatorSink(Protocol):
    """One place the indicator is displayed. GTK attaches one; tests attach one.

    ``show`` returns whether the sink is actually presenting the state. A sink
    that cannot — its window is gone, its widget failed — answers ``False``,
    and if every sink answers ``False`` the raise fails and the microphone
    stays shut.
    """

    def show(self, state: IndicatorState) -> bool: ...
    def clear(self, state: IndicatorState) -> bool: ...


class ListeningIndicator:
    """The one authority on whether the screen says "listening".

    The *text-side* authority, precisely: §18 makes the renderer's animation
    decorative and this indicator authoritative, so a renderer failure changes
    nothing here. In-process surfaces attach sinks; Bunny Shell attests the
    positive revision it rendered before crossing IPC. The worker raises and
    clears; everything else reads.
    """

    def __init__(self, *, clock: Clock | None = None) -> None:
        self.clock = clock or SystemClock()
        self._sinks: list[IndicatorSink] = []
        self._state = IndicatorState(listening=False)
        self._observers: list[Callable[[IndicatorState], None]] = []
        self._early_clears = 0
        self._raise_failures = 0
        self._attested_raises = 0
        self._guard = threading.RLock()

    # ----------------------------------------------------------------- #

    def attach(self, sink: IndicatorSink) -> None:
        with self._guard:
            self._sinks.append(sink)

    def detach(self, sink: IndicatorSink) -> None:
        with self._guard:
            self._sinks = [item for item in self._sinks if item is not sink]

    def subscribe(self, observer: Callable[[IndicatorState], None]) -> None:
        """State-change notifications for anything that is not a display.

        Observers are informational and cannot veto; only sinks decide whether
        the indicator is showing.
        """
        with self._guard:
            self._observers.append(observer)

    @property
    def state(self) -> IndicatorState:
        with self._guard:
            return self._state

    @property
    def listening(self) -> bool:
        with self._guard:
            return self._state.listening

    # ----------------------------------------------------------------- #

    def raise_for(
        self,
        *,
        request_id: str,
        session_id: str,
        device_id: str,
        backend_id: str,
        provider_id: str,
        presentation_revision: int = 0,
    ) -> tuple[bool, str]:
        """Show the indicator, before anything touches a device.

        Returns ``(raised, reason)``. ``raised`` is ``True`` only when at
        least one sink reported the state displayed or a positive revision
        attests the already-rendered Bunny Shell surface; ``reason`` is what
        the caller tells the user when it is not. A worker that opened the
        microphone after a ``False`` here would be violating §4 knowingly —
        which is why the worker's own test asserts the branch, not this
        module's.
        """
        with self._guard:
            if self._state.listening:
                return False, (
                    f"the indicator is already raised for {self._state.request_id!r}; "
                    "one capture at a time"
                )
            sinks = list(self._sinks)
            state = IndicatorState(
                listening=True,
                request_id=request_id,
                session_id=session_id,
                device_id=device_id,
                backend_id=backend_id,
                provider_id=provider_id,
                presentation_revision=presentation_revision,
                started_at_monotonic=self.clock.monotonic(),
            )
        externally_presented = presentation_revision > 0
        if not sinks and not externally_presented:
            with self._guard:
                self._raise_failures += 1
            return False, (
                "no surface is attached to display the listening indicator; the "
                "microphone is not opened without one"
            )
        shown = externally_presented
        for sink in sinks:
            try:
                shown = bool(sink.show(state)) or shown
            except Exception:  # noqa: BLE001 - a broken sink is a False, not a crash
                continue
        if not shown:
            with self._guard:
                self._raise_failures += 1
            return False, (
                "no attached surface could display the listening indicator; the "
                "microphone is not opened while listening would be invisible"
            )
        with self._guard:
            if externally_presented:
                self._attested_raises += 1
            self._state = state
            observers = list(self._observers)
        for observer in observers:
            try:
                observer(state)
            except Exception:  # noqa: BLE001 - observation must not stop the raise
                continue
        return True, ""

    def clear(self, request_id: str, *, capture_closed: bool) -> tuple[bool, str]:
        """Take the indicator down — only once the capture handle has closed.

        ``capture_closed`` is the handle's own fact, passed by the worker. A
        clear attempted while the handle is open is refused and counted: §5
        says the indicator outlives the capture interval completely, and an
        indicator that could be cleared early would show "not listening" over
        an open device — the exact lie the indicator exists to make impossible.
        """
        with self._guard:
            state = self._state
            if not state.listening:
                return True, "the indicator was not raised"
            if state.request_id != request_id:
                return False, (
                    f"the indicator belongs to {state.request_id!r} and the clear names "
                    f"{request_id!r}; refused"
                )
            if not capture_closed:
                self._early_clears += 1
                return False, (
                    "the capture handle has not closed; the indicator stays up until "
                    "the microphone is actually released"
                )
            cleared = IndicatorState(listening=False)
            self._state = cleared
            sinks = list(self._sinks)
            observers = list(self._observers)
        for sink in sinks:
            try:
                sink.clear(state)
            except Exception:  # noqa: BLE001 - teardown never raises
                continue
        for observer in observers:
            try:
                observer(cleared)
            except Exception:  # noqa: BLE001
                continue
        return True, ""

    # ----------------------------------------------------------------- #

    def describe(self) -> dict[str, Any]:
        with self._guard:
            return {
                "state": self._state.to_json(monotonic_now=self.clock.monotonic()),
                "sinksAttached": len(self._sinks),
                "earlyClearAttempts": self._early_clears,
                "raiseFailures": self._raise_failures,
                "attestedRaises": self._attested_raises,
                "indicatorBeforeOpen": True,
                "clearedOnlyAfterClose": True,
            }
