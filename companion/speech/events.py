# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What the speech-input runtime says happened, in a shape a gate can count.

§11's event list, as a closed set. Closed for the reason every event
vocabulary in the companion is: a surface subscribing needs to know what it
can receive, a gate counting needs the names stable, and a free-text event
kind is a fact nothing can aggregate.

Every event carries §11's required fields — request id, per-request sequence,
both clocks, producer, locality, privacy classification, presentation revision
— and a payload that has been through :func:`companion.privacy.sanitize`
before construction ever completes. The one thing a payload can never carry is
audio: the field check below refuses byte strings outright, and the privacy
module's forbidden-field rule catches the names raw audio travels under. §22's
"raw audio appears in task events" test is an assertion about this
constructor, which is a smaller thing to trust than every call site.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from ..privacy import DATA_CLASSES, sanitize

__all__ = [
    "SPEECH_EVENT_KINDS",
    "SpeechInputEvent",
]

#: Every event this runtime emits. §11's list, plus the two closure events —
#: ``microphone_closed`` and ``indicator_cleared`` — that make §5's ordering
#: (open before capture, clear only after close) measurable by a gate rather
#: than asserted by a reading of the worker.
SPEECH_EVENT_KINDS = (
    "speech_input_requested",
    "microphone_indicator_raised",
    "microphone_opened",
    "capture_started",
    "speech_detected",
    "partial_transcript",
    "silence_detected",
    "capture_stopped",
    "microphone_closed",
    "indicator_cleared",
    "recognition_finalizing",
    "final_transcript",
    "transcript_confirmation_requested",
    "transcript_confirmed",
    "transcript_rejected",
    "speech_input_cancelled",
    "device_lost",
    "recognition_failed",
    "speech_input_degraded",
    "capture_worker_started",
    "capture_worker_stopped",
)


@dataclass(frozen=True)
class SpeechInputEvent:
    """One thing that happened, with everything §11 requires attached to it."""

    kind: str
    request_id: str = ""
    session_id: str = ""
    #: Strictly monotonic per request, assigned by the worker. What lets a
    #: surface — and §16's stale-event tests — order and refuse
    #: deterministically.
    sequence: int = 0
    at_wall: float = 0.0
    at_monotonic: float = 0.0
    #: Which component produced this: ``capture-worker``, ``speech-service``,
    #: ``confirmation``.
    producer: str = "capture-worker"
    #: ``local`` is the only value this build produces; carried so the claim
    #: is on every record rather than implied by the absence of another.
    locality: str = "local"
    privacy_classification: str = "personal"
    presentation_revision: int = 0
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in SPEECH_EVENT_KINDS:
            raise ValueError(f"unknown speech-input event kind: {self.kind!r}")
        if self.privacy_classification not in DATA_CLASSES:
            raise ValueError(
                f"unknown privacy classification: {self.privacy_classification!r}"
            )
        for key, value in dict(self.payload).items():
            if isinstance(value, (bytes, bytearray, memoryview)):
                # The one shape raw audio arrives in. Refused by type before
                # the name-based rule gets a say, because a byte payload in an
                # event is wrong whatever it is called.
                raise ValueError(
                    f"event payload field {key!r} holds raw bytes; audio and other "
                    "binary content never travel in events"
                )
        # Sanitised at construction: forbidden field names are removed and the
        # removal recorded, bounds are enforced, and an oversized payload is a
        # refusal here rather than a surprise in the store.
        cleaned = sanitize(dict(self.payload))
        document = dict(cleaned.value)
        if cleaned.removed:
            document["removedFields"] = list(cleaned.removed)
        object.__setattr__(self, "payload", document)

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "requestId": self.request_id,
            "sessionId": self.session_id,
            "sequence": self.sequence,
            "atWall": self.at_wall,
            "atMonotonic": self.at_monotonic,
            "producer": self.producer,
            "locality": self.locality,
            "privacyClassification": self.privacy_classification,
            "presentationRevision": self.presentation_revision,
            **{key: value for key, value in dict(self.payload).items()},
        }
