# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Provider-neutral generic mouth-shape timeline with drift handling."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Sequence


class MouthShape(str, Enum):
    CLOSED = "closed"
    OPEN_SMALL = "open-small"
    OPEN_MEDIUM = "open-medium"
    OPEN_WIDE = "open-wide"
    ROUNDED = "rounded"
    SMILE = "smile"
    NEUTRAL = "neutral"


#: How a mouth shape's timing was arrived at, in descending order of how much
#: it knows about the sound. Carried on every event so a surface — and a report
#: — can say which, because the five are not interchangeable: ``amplitude`` is a
#: measurement of the samples that will be played, ``text-estimate`` is
#: arithmetic over the characters, and ``speaking-state`` knows only that
#: something is being said.
#:
#: ``text-estimate`` was added when the voice runtime landed. A provider that
#: owns its own playback (Speech Dispatcher) never hands over samples, so
#: amplitude is unavailable and the honest label for what remains is not
#: ``viseme`` — that would claim provider-native timing this build has never
#: received.
LIP_SYNC_SOURCES = frozenset({"phoneme", "viseme", "amplitude", "text-estimate", "speaking-state"})


@dataclass(frozen=True)
class LipSyncEvent:
    timestamp_ms: int
    shape: MouthShape
    source: str = "viseme"

    def __post_init__(self) -> None:
        if self.timestamp_ms < 0:
            raise ValueError("lip-sync timestamps cannot be negative")
        if self.source not in LIP_SYNC_SOURCES:
            raise ValueError("lip-sync source is unsupported")

    def to_json(self) -> dict[str, Any]:
        return {"timestampMs": self.timestamp_ms, "shape": self.shape.value, "source": self.source}


@dataclass(frozen=True)
class LipSyncStatus:
    active: bool
    shape: MouthShape
    sequence: int
    drift_ms: int
    drift_detected: bool
    cancelled: bool
    explanation: str

    def to_json(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "mouthShape": self.shape.value,
            "sequence": self.sequence,
            "driftMs": self.drift_ms,
            "driftDetected": self.drift_detected,
            "cancelled": self.cancelled,
            "explanation": self.explanation,
        }


def validate_lip_sync_events(events: Iterable[LipSyncEvent]) -> tuple[LipSyncEvent, ...]:
    result = tuple(events)
    if len(result) > 10_000:
        raise ValueError("lip-sync event sequence exceeds its bound")
    previous = -1
    for event in result:
        if event.timestamp_ms < previous:
            raise ValueError("lip-sync timestamps must be monotonic")
        previous = event.timestamp_ms
    return result


def amplitude_to_shape(amplitude: float) -> MouthShape:
    if not 0 <= amplitude <= 1:
        raise ValueError("audio amplitude must be normalized")
    if amplitude < 0.08:
        return MouthShape.CLOSED
    if amplitude < 0.30:
        return MouthShape.OPEN_SMALL
    if amplitude < 0.65:
        return MouthShape.OPEN_MEDIUM
    return MouthShape.OPEN_WIDE


class LipSyncController:
    def __init__(self, supported_shapes: Iterable[str], *, drift_limit_ms: int = 120) -> None:
        self.supported_shapes = frozenset(supported_shapes)
        self.drift_limit_ms = drift_limit_ms
        self.events: tuple[LipSyncEvent, ...] = ()
        self.index = 0
        self.sequence = 0
        self.active = False
        self.cancelled = False
        self.reduced_motion = False
        self.shape = MouthShape.NEUTRAL

    def start(self, events: Iterable[LipSyncEvent], *, reduced_motion: bool = False) -> LipSyncStatus:
        self.events = validate_lip_sync_events(events)
        self.index = 0
        self.sequence += 1
        self.active = True
        self.cancelled = False
        self.reduced_motion = reduced_motion
        self.shape = MouthShape.NEUTRAL
        return self.status(0, "lip-sync timeline started")

    def _supported(self, requested: MouthShape) -> MouthShape:
        if self.reduced_motion:
            return MouthShape.NEUTRAL
        if requested.value in self.supported_shapes:
            return requested
        for fallback in (MouthShape.NEUTRAL, MouthShape.CLOSED):
            if fallback.value in self.supported_shapes:
                return fallback
        return MouthShape.NEUTRAL

    def advance(self, playback_ms: int, *, audio_clock_ms: int | None = None) -> LipSyncStatus:
        if playback_ms < 0:
            raise ValueError("lip-sync playback time cannot be negative")
        if not self.active:
            return self.status(0, "lip-sync timeline is inactive")
        while self.index < len(self.events) and self.events[self.index].timestamp_ms <= playback_ms:
            self.shape = self._supported(self.events[self.index].shape)
            self.index += 1
        drift = 0 if audio_clock_ms is None else int(audio_clock_ms - playback_ms)
        detected = abs(drift) > self.drift_limit_ms
        if self.index >= len(self.events):
            self.finish()
            return self.status(drift, "lip-sync timeline completed and returned to neutral", detected)
        explanation = "audio drift exceeded the diagnostic threshold" if detected else "lip-sync timeline advanced monotonically"
        return self.status(drift, explanation, detected)

    def finish(self) -> LipSyncStatus:
        self.active = False
        self.shape = MouthShape.NEUTRAL
        return self.status(0, "speech ended; mouth returned to neutral")

    def cancel(self, reason: str = "audio interrupted") -> LipSyncStatus:
        self.active = False
        self.cancelled = True
        self.shape = MouthShape.NEUTRAL
        return self.status(0, reason)

    def status(self, drift_ms: int, explanation: str, detected: bool | None = None) -> LipSyncStatus:
        return LipSyncStatus(
            self.active, self.shape, self.sequence, drift_ms,
            abs(drift_ms) > self.drift_limit_ms if detected is None else detected,
            self.cancelled, explanation,
        )
