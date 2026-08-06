# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Deciding when somebody is speaking, from the samples and nothing else.

§15 asks for bounded speech and silence detection, and the word that matters is
*bounded* — in both directions. A capture with no speech in it must end at the
initial-silence timeout rather than holding the microphone open; a capture with
speech in it must end shortly after the speech does; and neither decision may
depend on wall time, because the samples themselves carry the only clock that
cannot drift against them. Every position here is **audio time**: bytes seen,
divided by the request's own byte rate. A test that feeds this detector the
same PCM twice gets the same answer twice, which is what makes §16's race tests
deterministic rather than timing-dependent.

The detection itself is deliberately unsophisticated: a root-mean-square energy
gate with a calibrated noise floor. That is enough to tell "somebody spoke"
from "the room hummed", which is all §15 asks, and it is *all* this module may
ever do — the docstring on :class:`SpeechActivityDetector` states the §15
prohibition out loud: no biometric capability, no speaker identity, no
vocabulary. Energy in, boundaries out.

Calibration is "where safe" (§15): the floor adapts only upward from its
configured minimum, only during the initial-silence window, and only within a
fixed multiple — so a noisy room raises the bar for what counts as speech, and
nothing a microphone hears can *lower* it to the point where silence starts
counting as speech and the capture never ends.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = [
    "ActivityState",
    "SpeechActivityDetector",
]

#: The RMS level, on 16-bit samples, below which a frame is silence whatever
#: the calibration says. Roughly -42 dBFS: quiet-room noise on a normal
#: microphone sits under it, ordinary speech sits well over it.
DEFAULT_NOISE_FLOOR = 250.0

#: The most calibration may raise the floor, as a multiple of the configured
#: one. The bound on "where safe": past this, the room is too loud for energy
#: gating to mean anything and the detector says so rather than guessing.
MAX_CALIBRATION_MULTIPLE = 8.0

#: How far above the floor a frame must be to count as speech. A gap between
#: the silence threshold and the speech threshold is what stops a level right
#: at the boundary from toggling the state machine every frame.
SPEECH_RATIO = 2.5

#: How much continuous speech-level audio starts an utterance, in seconds.
#: A door slam is louder than speech and shorter than this.
SPEECH_START_SECONDS = 0.12

#: The analysis frame. 30 ms is small enough that endpoint latency is dominated
#: by the endpoint timeout, and large enough that RMS means something.
FRAME_SECONDS = 0.03


@dataclass(frozen=True)
class ActivityState:
    """What the detector currently believes, and when it started believing it."""

    #: ``calibrating``, ``waiting-for-speech``, ``speech``, ``trailing-silence``
    #: or ``ended``.
    phase: str
    #: Audio position, in seconds from the start of the capture.
    position_seconds: float
    #: When speech was first detected, or 0.0 if it never was.
    speech_started_at: float = 0.0
    #: Why the detector considers the utterance over, when it does.
    #: ``initial-silence``, ``endpoint-silence``, ``maximum-duration`` or "".
    end_reason: str = ""
    #: The calibrated noise floor in force.
    noise_floor: float = 0.0
    #: Whether calibration hit its ceiling — the room was too loud to measure.
    calibration_saturated: bool = False

    @property
    def speech_detected(self) -> bool:
        return bool(self.speech_started_at)

    @property
    def ended(self) -> bool:
        return self.phase == "ended"

    def to_json(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "positionSeconds": round(self.position_seconds, 4),
            "speechStartedAt": round(self.speech_started_at, 4),
            "speechDetected": self.speech_detected,
            "endReason": self.end_reason,
            "noiseFloor": round(self.noise_floor, 2),
            "calibrationSaturated": self.calibration_saturated,
        }


class SpeechActivityDetector:
    """An energy gate over PCM, clocked by the samples themselves.

    **This is not a recogniser and must never grow toward one.** §15: no
    biometric capability, no speaker identity, no phrase spotting. The whole of
    what it computes is per-frame RMS against a calibrated floor, and the whole
    of what it emits is boundaries: speech started, silence fell, the capture
    should end and why.

    Feed it with :meth:`feed` as chunks arrive; read :meth:`state` at any
    point. Both are cheap and neither blocks. ``manual stop overrides
    automatic stop`` (§15) is not implemented here because it cannot be: this
    object only ever *recommends* an end, and the worker that owns the capture
    takes a user's stop whatever this recommends.
    """

    def __init__(
        self,
        *,
        sample_rate: int,
        channels: int,
        initial_silence_seconds: float,
        endpoint_silence_seconds: float,
        maximum_seconds: float,
        noise_floor: float = DEFAULT_NOISE_FLOOR,
        calibration_seconds: float = 0.24,
    ) -> None:
        self.sample_rate = int(sample_rate)
        self.channels = int(channels)
        self.initial_silence_seconds = float(initial_silence_seconds)
        self.endpoint_silence_seconds = float(endpoint_silence_seconds)
        self.maximum_seconds = float(maximum_seconds)
        self.configured_floor = float(noise_floor)
        self.calibration_seconds = max(0.0, float(calibration_seconds))

        self._bytes_per_second = self.sample_rate * self.channels * 2
        self._frame_bytes = max(2, int(FRAME_SECONDS * self._bytes_per_second)) & ~1
        self._pending = bytearray()
        self._position = 0.0
        self._floor = self.configured_floor
        self._calibration_energies: list[float] = []
        self._calibrated = self.calibration_seconds == 0.0
        self._saturated = False
        self._speech_started_at = 0.0
        self._speech_run_seconds = 0.0
        self._last_speech_at = 0.0
        self._end_reason = ""

    # ----------------------------------------------------------------- #

    @staticmethod
    def _rms(frame: bytes) -> float:
        """Root-mean-square of one 16-bit little-endian frame.

        ``audioop`` was removed in Python 3.13, so this is spelled out. The
        loop is over at most a few hundred samples per frame and runs forty
        times a second; correctness beats cleverness at that scale.
        """
        count = len(frame) // 2
        if not count:
            return 0.0
        total = 0
        for index in range(0, count * 2, 2):
            sample = int.from_bytes(frame[index:index + 2], "little", signed=True)
            total += sample * sample
        return (total / count) ** 0.5

    def feed(self, chunk: bytes) -> ActivityState:
        """Advance the detector over one arriving chunk. Returns the new state."""
        if chunk and not self._end_reason:
            self._pending.extend(chunk)
            while len(self._pending) >= self._frame_bytes and not self._end_reason:
                frame = bytes(self._pending[: self._frame_bytes])
                del self._pending[: self._frame_bytes]
                self._advance(frame)
        return self.state()

    def _advance(self, frame: bytes) -> None:
        self._position += len(frame) / self._bytes_per_second
        energy = self._rms(frame)

        if not self._calibrated:
            self._calibration_energies.append(energy)
            if self._position >= self.calibration_seconds:
                measured = sorted(self._calibration_energies)[len(self._calibration_energies) // 2]
                ceiling = self.configured_floor * MAX_CALIBRATION_MULTIPLE
                # Only upward from the configured floor, and only to the
                # ceiling. Downward calibration would let a silent room lower
                # the bar until noise reads as speech and the capture never
                # ends on silence — the unsafe direction §15's "where safe"
                # exists to name.
                candidate = max(self.configured_floor, measured * 1.5)
                self._saturated = candidate > ceiling
                self._floor = min(candidate, ceiling)
                self._calibrated = True
            return

        speaking = energy >= self._floor * SPEECH_RATIO

        if speaking:
            self._speech_run_seconds += len(frame) / self._bytes_per_second
            if not self._speech_started_at and self._speech_run_seconds >= SPEECH_START_SECONDS:
                self._speech_started_at = self._position
            if self._speech_started_at:
                self._last_speech_at = self._position
        else:
            self._speech_run_seconds = 0.0

        if self._position >= self.maximum_seconds:
            self._end_reason = "maximum-duration"
            return
        if not self._speech_started_at:
            if self._position >= self.calibration_seconds + self.initial_silence_seconds:
                self._end_reason = "initial-silence"
            return
        if self._position - self._last_speech_at >= self.endpoint_silence_seconds:
            self._end_reason = "endpoint-silence"

    # ----------------------------------------------------------------- #

    def state(self) -> ActivityState:
        if self._end_reason:
            phase = "ended"
        elif not self._calibrated:
            phase = "calibrating"
        elif not self._speech_started_at:
            phase = "waiting-for-speech"
        elif self._position - self._last_speech_at > FRAME_SECONDS * 2:
            phase = "trailing-silence"
        else:
            phase = "speech"
        return ActivityState(
            phase=phase,
            position_seconds=self._position,
            speech_started_at=self._speech_started_at,
            end_reason=self._end_reason,
            noise_floor=self._floor,
            calibration_saturated=self._saturated,
        )

    def describe(self) -> dict[str, Any]:
        return {
            **self.state().to_json(),
            "sampleRate": self.sample_rate,
            "channels": self.channels,
            "initialSilenceSeconds": self.initial_silence_seconds,
            "endpointSilenceSeconds": self.endpoint_silence_seconds,
            "maximumSeconds": self.maximum_seconds,
            "configuredFloor": self.configured_floor,
            "speakerIdentification": False,
            "biometricCapability": False,
        }
