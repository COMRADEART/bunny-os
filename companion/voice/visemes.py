# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Moving the character's mouth in time with speech, and saying how well.

The mouth shapes are the renderer's own — :class:`companion.character.lipsync.MouthShape`
— and this module does not add to them. What it adds is *timing*, and the whole
design turns on one sentence from §13: **no claim of phoneme accuracy unless
measured.**

Four generators, in descending order of how much they know:

:func:`from_provider_timing`
    Provider-native visemes. **No provider in this build produces them**, so the
    function exists as the place a future one would land and raises rather than
    fabricating. Confidence would be 0.95.

:func:`from_phoneme_timing`
    Phoneme boundaries with the audio. **Not produced by any provider here.**
    eSpeak NG can print phoneme *names* with ``-x``; it does not print
    boundaries alongside the samples, and turning names into times would be an
    estimate wearing a measurement's label.

:func:`from_amplitude`
    Root-mean-square level of the samples that will actually be played, from
    :func:`companion.voice.pcm.amplitude_envelope`. This is a *measurement* —
    the only one in this module — and it is why the eSpeak NG synthesis path is
    preferred over the streaming one. It knows how loud each 40 ms is and
    nothing about which sound it is, so it cannot produce ``rounded``, and
    confidence is 0.6.

:func:`from_text`
    Arithmetic over the characters, distributed across a known or estimated
    duration. Used when the provider owns playback and there are no samples to
    measure. It knows which *letters* are being spoken and only guesses when,
    so it can produce ``rounded`` where amplitude cannot — and its confidence is
    0.35 because the alignment is an assumption about even pacing that no
    synthesiser actually honours.

:func:`speaking_state`
    The floor: open while speaking, neutral when not. Confidence 0.15. §14's
    answer to "synchronisation cannot be maintained" is to fall back to this
    rather than to keep showing timing that has drifted.

**Neutral is the terminal state on every path.** Completion, cancellation,
drift beyond tolerance, a renderer restart mid-timeline, and the worker being
torn down all end with the mouth closed and still. A character left mid-syllable
is the most visible possible symptom of a runtime that lost track of itself, and
it is the one thing a user notices instantly.

``smile`` is deliberately never generated here. It is an expression, not a mouth
position for a sound, and the canonical presentation phase already drives the
character's expression through :mod:`companion.character.mapper`. A viseme
generator that emitted it would be forming an opinion about how the task was
going, which is §1's boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from ..character.lipsync import LipSyncEvent, LipSyncStatus, MouthShape, amplitude_to_shape
from .request import VoiceRequest

__all__ = [
    "MAX_VISEME_EVENTS",
    "SOURCE_CONFIDENCE",
    "VisemeEvent",
    "VisemeScheduler",
    "VisemeTimeline",
    "from_amplitude",
    "from_phoneme_timing",
    "from_provider_timing",
    "from_text",
    "speaking_state",
]

#: The bound §13 requires. At the 40 ms analysis window a four-minute utterance
#: produces 6000 events, so this is generous for anything a caption can be and
#: is a hard ceiling rather than a target: a generator that would exceed it
#: widens its own window instead of emitting more.
MAX_VISEME_EVENTS = 8192

#: How much each source method is worth, stated once. These are not tuned
#: parameters; they are an ordering, and the only property that matters is that
#: a measurement outranks an estimate outranks a guess.
SOURCE_CONFIDENCE: Mapping[str, float] = {
    "viseme": 0.95,
    "phoneme": 0.9,
    "amplitude": 0.6,
    "text-estimate": 0.35,
    "speaking-state": 0.15,
}

#: Letters that close the mouth. Bilabials: the sound cannot be made with the
#: lips apart, so this is the one text-derived mapping that is a fact about
#: speech rather than a convention.
_CLOSED = frozenset("mbp")

#: Letters made with rounded lips. Also physical rather than conventional.
_ROUNDED = frozenset("ouwq")

#: Open vowels, by how far the jaw drops.
_WIDE = frozenset("a")
_MEDIUM = frozenset("eiy")


@dataclass(frozen=True)
class VisemeEvent:
    """One mouth shape, when it starts and how long it holds.

    Every field §13 names is here and none is optional. ``offset_ms`` is
    measured from the start of *this utterance's audio*, not from any clock:
    a renderer that restarts mid-utterance re-derives its position from the
    playback handle and re-enters the timeline, which only works if the timeline
    itself has no absolute time in it.
    """

    request_id: str
    sequence: int
    offset_ms: int
    duration_ms: int
    shape: MouthShape
    confidence: float
    source: str

    def __post_init__(self) -> None:
        if self.offset_ms < 0:
            raise ValueError("a viseme offset cannot be negative")
        if self.duration_ms < 0:
            raise ValueError("a viseme duration cannot be negative")
        if self.sequence < 0:
            raise ValueError("a viseme sequence cannot be negative")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("viseme confidence must be between 0 and 1")
        if self.source not in SOURCE_CONFIDENCE:
            raise ValueError(f"unknown viseme source method: {self.source!r}")
        if self.shape is MouthShape.SMILE:
            raise ValueError(
                "a smile is an expression rather than a mouth position for a sound; "
                "the character's expression comes from the canonical presentation phase"
            )

    @property
    def end_ms(self) -> int:
        return self.offset_ms + self.duration_ms

    def to_lipsync(self) -> LipSyncEvent:
        return LipSyncEvent(timestamp_ms=self.offset_ms, shape=self.shape, source=self.source)

    def to_json(self) -> dict[str, Any]:
        return {
            "requestId": self.request_id,
            "sequence": self.sequence,
            "offsetMs": self.offset_ms,
            "durationMs": self.duration_ms,
            "mouthShape": self.shape.value,
            "confidence": self.confidence,
            "sourceMethod": self.source,
        }


@dataclass(frozen=True)
class VisemeTimeline:
    """An ordered, bounded run of shapes for one utterance, ending neutral."""

    request_id: str
    events: tuple[VisemeEvent, ...]
    source: str
    total_ms: int
    #: What the timing was derived from, in words a person can check — "22050 Hz
    #: samples, 40 ms windows" or "58 characters across an estimated 2100 ms".
    derivation: str = ""
    truncated: bool = False

    def __post_init__(self) -> None:
        previous = -1
        for event in self.events:
            if event.offset_ms < previous:
                raise ValueError("viseme offsets must be ordered")
            previous = event.offset_ms
        if len(self.events) > MAX_VISEME_EVENTS:
            raise ValueError(f"a viseme timeline may hold at most {MAX_VISEME_EVENTS} events")
        if self.events and self.events[-1].shape is not MouthShape.NEUTRAL:
            raise ValueError("a viseme timeline must end with the mouth neutral")

    @property
    def confidence(self) -> float:
        return SOURCE_CONFIDENCE.get(self.source, 0.0)

    def lipsync_events(self) -> tuple[LipSyncEvent, ...]:
        """The renderer's own event type, so it needs no knowledge of this module."""
        return tuple(event.to_lipsync() for event in self.events)

    def shape_at(self, offset_ms: int) -> MouthShape:
        current = MouthShape.NEUTRAL
        for event in self.events:
            if event.offset_ms > offset_ms:
                break
            current = event.shape
        return current

    def to_json(self, *, include_events: bool = False) -> dict[str, Any]:
        document: dict[str, Any] = {
            "requestId": self.request_id,
            "sourceMethod": self.source,
            "confidence": self.confidence,
            "eventCount": len(self.events),
            "totalMs": self.total_ms,
            "derivation": self.derivation,
            "truncated": self.truncated,
            "endsNeutral": bool(self.events) and self.events[-1].shape is MouthShape.NEUTRAL,
        }
        if include_events:
            document["events"] = [event.to_json() for event in self.events]
        return document


def _build(
    request_id: str,
    shapes: Sequence[tuple[int, MouthShape]],
    *,
    source: str,
    total_ms: int,
    derivation: str,
) -> VisemeTimeline:
    """Turn ``(offset, shape)`` pairs into a bounded timeline that ends neutral.

    Consecutive identical shapes are merged. Not an optimisation: a renderer
    told to change to the shape it is already in re-runs its transition, and a
    mouth that restarts the same animation forty times a second looks like a
    stutter rather than a hold.
    """
    confidence = SOURCE_CONFIDENCE[source]
    merged: list[tuple[int, MouthShape]] = []
    for offset, shape in shapes:
        if merged and merged[-1][1] is shape:
            continue
        merged.append((max(0, int(offset)), shape))

    truncated = False
    if len(merged) > MAX_VISEME_EVENTS - 1:
        # Room is kept for the closing neutral, which must not be the event that
        # falls off the end.
        merged = merged[: MAX_VISEME_EVENTS - 1]
        truncated = True

    events: list[VisemeEvent] = []
    for index, (offset, shape) in enumerate(merged):
        following = merged[index + 1][0] if index + 1 < len(merged) else max(offset, total_ms)
        events.append(VisemeEvent(
            request_id=request_id,
            sequence=index,
            offset_ms=offset,
            duration_ms=max(0, following - offset),
            shape=shape,
            confidence=confidence,
            source=source,
        ))
    events.append(VisemeEvent(
        request_id=request_id,
        sequence=len(events),
        offset_ms=max(total_ms, events[-1].end_ms if events else 0),
        duration_ms=0,
        shape=MouthShape.NEUTRAL,
        confidence=confidence,
        source=source,
    ))
    return VisemeTimeline(
        request_id=request_id,
        events=tuple(events),
        source=source,
        total_ms=total_ms,
        derivation=derivation,
        truncated=truncated,
    )


def from_provider_timing(request_id: str, timing: Iterable[Any]) -> VisemeTimeline:
    """Provider-native viseme timing. Nothing in this build produces it.

    Raises rather than returning an empty timeline, for the reason
    :class:`companion.voice.system.AbsentSpeechRecognition` raises: an empty
    result is indistinguishable from a provider that produced no visemes for a
    silent utterance, and every consumer downstream would treat it as real.
    """
    del timing
    raise NotImplementedError(
        f"no provider in this build returns native viseme timing for {request_id}; "
        "claiming it would put an unmeasured accuracy into the record"
    )


def from_phoneme_timing(request_id: str, phonemes: Iterable[Any]) -> VisemeTimeline:
    """Phoneme boundaries alongside the audio. Nothing in this build produces them.

    eSpeak NG prints phoneme names with ``-x`` and does not print the times they
    occur at. Deriving times from names would produce a timeline labelled
    ``phoneme`` — the second-highest confidence in :data:`SOURCE_CONFIDENCE` —
    from an estimate no better than :func:`from_text`. §13 forbids exactly that.
    """
    del phonemes
    raise NotImplementedError(
        f"no provider in this build returns phoneme boundaries for {request_id}; "
        "eSpeak NG emits phoneme names without times, which is not timing"
    )


def from_amplitude(
    request_id: str,
    envelope: Sequence[tuple[int, float]],
    *,
    total_ms: int = 0,
    sample_rate: int = 0,
    window_ms: int = 40,
) -> VisemeTimeline:
    """Mouth shapes from the measured level of the samples that will be played.

    Delegates the level-to-shape decision to
    :func:`companion.character.lipsync.amplitude_to_shape`, which the renderer
    already owns. Two implementations of "how open is this" would eventually
    disagree, and the one drawing the mouth should win.
    """
    if not envelope:
        return _build(
            request_id, [], source="amplitude", total_ms=total_ms,
            derivation="no samples were available to measure",
        )
    shapes = [(offset, amplitude_to_shape(max(0.0, min(1.0, level)))) for offset, level in envelope]
    end = total_ms or (envelope[-1][0] + window_ms)
    return _build(
        request_id, shapes, source="amplitude", total_ms=end,
        derivation=(
            f"root-mean-square level of {len(envelope)} windows of {window_ms} ms"
            + (f" at {sample_rate} Hz" if sample_rate else "")
        ),
    )


def _shape_for_character(character: str) -> MouthShape | None:
    lowered = character.lower()
    if not lowered.isalpha():
        # Punctuation and spaces close the mouth. A pause with the mouth open is
        # the single most common way lip-sync looks wrong.
        return MouthShape.CLOSED if lowered.strip() == "" or lowered in ".,;:!?" else None
    if lowered in _CLOSED:
        return MouthShape.CLOSED
    if lowered in _ROUNDED:
        return MouthShape.ROUNDED
    if lowered in _WIDE:
        return MouthShape.OPEN_WIDE
    if lowered in _MEDIUM:
        return MouthShape.OPEN_MEDIUM
    return MouthShape.OPEN_SMALL


def estimated_duration_ms(text: str, *, words_per_minute: float = 175.0, rate: float = 1.0) -> int:
    """How long an utterance will take, when nobody has measured it.

    175 words per minute is eSpeak NG's own default and is what the streaming
    path actually runs at, so this is the synthesiser's stated pace rather than
    a general figure about speech. Floored at 300 ms: a one-word utterance still
    needs a mouth that opens.
    """
    words = max(1, len(text.split()))
    pace = max(20.0, words_per_minute * max(0.05, rate))
    return max(300, int(words / pace * 60_000))


def from_text(
    request_id: str,
    text: str,
    *,
    total_ms: int = 0,
    rate: float = 1.0,
    words_per_minute: float = 175.0,
    maximum_events: int = 1200,
) -> VisemeTimeline:
    """Mouth shapes from the characters, spread evenly across the duration.

    Even spacing is the assumption, and it is wrong in a knowable direction: no
    synthesiser gives every character the same time, so a long utterance drifts
    against its own audio. That is why the confidence is 0.35 and why §14
    measures drift and falls back to :func:`speaking_state` when it exceeds
    tolerance — rather than this module pretending to a precision it has not got.

    ``maximum_events`` widens the per-character step for a long caption instead
    of emitting one event per letter. At 1200 events a four-second utterance
    changes shape every three milliseconds, which no renderer can draw and no
    eye can see.
    """
    body = " ".join(str(text).split())
    duration = total_ms or estimated_duration_ms(body, words_per_minute=words_per_minute, rate=rate)
    if not body:
        return _build(
            request_id, [], source="text-estimate", total_ms=duration,
            derivation="there were no characters to derive timing from",
        )
    step = max(1, len(body) // max(1, maximum_events) + 1)
    per_character = duration / len(body)
    shapes: list[tuple[int, MouthShape]] = []
    for index in range(0, len(body), step):
        shape = _shape_for_character(body[index])
        if shape is None:
            continue
        shapes.append((int(index * per_character), shape))
    return _build(
        request_id, shapes, source="text-estimate", total_ms=duration,
        derivation=(
            f"{len(body)} characters sampled every {step} across "
            f"{'an estimated ' if not total_ms else 'a measured '}{duration} ms utterance"
        ),
    )


def speaking_state(request_id: str, *, total_ms: int) -> VisemeTimeline:
    """Open while speaking, neutral when it stops. The floor of the ladder.

    Two events. It is not a degraded version of lip-sync; it is a different and
    honest statement — "this character is talking" — and it is what §14 requires
    when timing cannot be maintained, because a mouth moving to *wrong* timing
    reads as broken in a way a mouth simply being open does not.
    """
    return _build(
        request_id,
        [(0, MouthShape.OPEN_MEDIUM)],
        source="speaking-state",
        total_ms=max(0, int(total_ms)),
        derivation="speaking state only; no timing was available",
    )


def timeline_for(
    request: VoiceRequest,
    *,
    envelope: Sequence[tuple[int, float]] | None = None,
    audio_seconds: float = 0.0,
    sample_rate: int = 0,
) -> VisemeTimeline:
    """The best timeline the available evidence supports, and no better.

    The order is the §13 ladder read downwards, and each rung is taken only when
    the evidence for it exists. There is no configuration that promotes a
    timeline to a source method it was not derived from.
    """
    total_ms = int(audio_seconds * 1000) if audio_seconds else 0
    if envelope:
        return from_amplitude(
            request.request_id, envelope, total_ms=total_ms, sample_rate=sample_rate
        )
    return from_text(request.request_id, request.speech_text, total_ms=total_ms, rate=request.speaking_rate)


# --------------------------------------------------------------------------- #
# Scheduling
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class VisemeFrame:
    """What the renderer should be showing at one instant, and how sure we are."""

    request_id: str
    sequence: int
    shape: MouthShape
    confidence: float
    source: str
    position_ms: int
    drift_ms: int
    drift_detected: bool
    active: bool
    cancelled: bool
    explanation: str

    def to_json(self) -> dict[str, Any]:
        return {
            "requestId": self.request_id,
            "sequence": self.sequence,
            "mouthShape": self.shape.value,
            "confidence": self.confidence,
            "sourceMethod": self.source,
            "positionMs": self.position_ms,
            "driftMs": self.drift_ms,
            "driftDetected": self.drift_detected,
            "active": self.active,
            "cancelled": self.cancelled,
            "explanation": self.explanation,
        }


class VisemeScheduler:
    """Drives one timeline against a playback position, and degrades honestly.

    Owned by the voice worker, one at a time, and reset on every utterance.

    Drift is the difference between where the timeline thinks the audio is and
    where the playback handle says it is. Beyond :attr:`drift_limit_ms` for
    :attr:`drift_tolerance_frames` consecutive readings the scheduler *switches
    source* — down to speaking-state — rather than continuing to show timing it
    knows is wrong. One reading over the limit is a scheduling hiccup; several
    in a row is a timeline that has come apart from its audio.
    """

    #: §14's tolerance for this environment. 120 ms is roughly the point at
    #: which a viewer starts to perceive lips and sound as separate; it matches
    #: :class:`companion.character.lipsync.LipSyncController`'s own default so
    #: the two layers do not disagree about what "in sync" means.
    DEFAULT_DRIFT_LIMIT_MS = 120

    def __init__(
        self,
        *,
        drift_limit_ms: int = DEFAULT_DRIFT_LIMIT_MS,
        drift_tolerance_frames: int = 3,
    ) -> None:
        self.drift_limit_ms = drift_limit_ms
        self.drift_tolerance_frames = drift_tolerance_frames
        self.timeline: VisemeTimeline | None = None
        self.index = 0
        self.shape = MouthShape.NEUTRAL
        self.active = False
        self.cancelled = False
        self.degraded = False
        self._over_limit = 0
        self._emitted = 0

    @property
    def emitted(self) -> int:
        return self._emitted

    def start(self, timeline: VisemeTimeline) -> VisemeFrame:
        self.timeline = timeline
        self.index = 0
        self.shape = MouthShape.NEUTRAL
        self.active = True
        self.cancelled = False
        self.degraded = False
        self._over_limit = 0
        self._emitted = 0
        return self._frame(0, 0, False, "viseme timeline started")

    def advance(self, position_ms: int, *, audio_clock_ms: int | None = None) -> VisemeFrame:
        """Move to ``position_ms``, reporting the shape and the drift.

        ``position_ms`` is the renderer's own idea of where it is;
        ``audio_clock_ms`` is the playback handle's. Passing both is what makes
        drift observable at all — a scheduler driven by one clock cannot know it
        has lost the other.
        """
        if position_ms < 0:
            raise ValueError("a viseme position cannot be negative")
        timeline = self.timeline
        if timeline is None or not self.active:
            return self._frame(position_ms, 0, False, "no viseme timeline is running")

        while self.index < len(timeline.events) and timeline.events[self.index].offset_ms <= position_ms:
            self.shape = timeline.events[self.index].shape
            self.index += 1
            self._emitted += 1

        drift = 0 if audio_clock_ms is None else int(audio_clock_ms - position_ms)
        detected = abs(drift) > self.drift_limit_ms
        self._over_limit = self._over_limit + 1 if detected else 0

        if self._over_limit >= self.drift_tolerance_frames and not self.degraded:
            return self.degrade(
                f"the timeline drifted {drift} ms from the audio for "
                f"{self._over_limit} consecutive readings"
            )
        if self.index >= len(timeline.events):
            return self.finish("the utterance ended and the mouth returned to neutral")
        return self._frame(
            position_ms, drift, detected,
            "viseme timeline advanced" if not detected else "drift exceeded the tolerance",
        )

    def degrade(self, reason: str) -> VisemeFrame:
        """Drop to speaking-state timing, keeping the mouth moving but honest."""
        timeline = self.timeline
        total = timeline.total_ms if timeline is not None else 0
        request_id = timeline.request_id if timeline is not None else ""
        self.timeline = speaking_state(request_id, total_ms=total)
        self.index = 0
        self.degraded = True
        self._over_limit = 0
        self.shape = MouthShape.OPEN_MEDIUM
        return self._frame(0, 0, True, f"degraded to speaking-state timing: {reason}")

    def finish(self, explanation: str = "speech ended; the mouth returned to neutral") -> VisemeFrame:
        self.active = False
        self.shape = MouthShape.NEUTRAL
        return self._frame(0, 0, False, explanation)

    def cancel(self, reason: str = "speech was interrupted") -> VisemeFrame:
        self.active = False
        self.cancelled = True
        self.shape = MouthShape.NEUTRAL
        return self._frame(0, 0, False, reason)

    def reset_for_renderer_restart(self) -> VisemeFrame:
        """A renderer came back and does not know what it was showing.

        The mouth is put to neutral and the timeline is re-entered from the
        current index rather than from the start: replaying from zero would run
        the whole utterance's mouth movement against audio that is most of the
        way through, which looks far worse than a mouth that simply catches up.
        """
        self.shape = MouthShape.NEUTRAL
        return self._frame(0, 0, False, "the renderer restarted; the mouth was reset to neutral")

    def _frame(self, position_ms: int, drift: int, detected: bool, explanation: str) -> VisemeFrame:
        timeline = self.timeline
        return VisemeFrame(
            request_id=timeline.request_id if timeline is not None else "",
            sequence=self.index,
            shape=self.shape,
            confidence=timeline.confidence if timeline is not None else 0.0,
            source=timeline.source if timeline is not None else "speaking-state",
            position_ms=position_ms,
            drift_ms=drift,
            drift_detected=detected,
            active=self.active,
            cancelled=self.cancelled,
            explanation=explanation,
        )

    def status(self) -> LipSyncStatus:
        """The renderer's own status type, so the GTK client needs nothing new."""
        return LipSyncStatus(
            active=self.active,
            shape=self.shape,
            sequence=self.index,
            drift_ms=0,
            drift_detected=self.degraded,
            cancelled=self.cancelled,
            explanation="degraded to speaking-state timing" if self.degraded else "viseme timeline",
        )
