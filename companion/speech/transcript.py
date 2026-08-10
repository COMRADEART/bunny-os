# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What a recogniser said the user said, held to what a transcript may be.

Two types, and the distance between them is the whole of §12 and §13.

A :class:`PartialTranscript` is **provisional** and everything about the type
says so: it carries a monotonic revision so a surface can apply replacements
deterministically, it is bounded so a runaway recogniser cannot grow a label
without limit, and there is no path from it to a task — nothing in this package
accepts a partial where a submission is being formed, and the field that would
carry one does not exist.

A :class:`FinalTranscript` is the recogniser's *complete* answer, with the
provenance §13 requires: which provider, which implementation, what language,
what confidence it claims, when the audio started and ended, whether the path
was streaming or batch, and — after the user touches it — whether the text was
edited before submission. The edited flag matters because the canonical task
must receive what the *user* confirmed, and a record that could not distinguish
"the recogniser said this" from "the user corrected it to this" would attribute
the user's words to a model or the model's to the user.

Text hygiene happens here, once, at construction: control characters are
refused, length is bounded in characters and bytes, and whitespace is
collapsed. :func:`pango_escaped` is the one way transcript text may reach a
GTK label — §22's markup-injection test asserts that a transcript containing
``<b>`` arrives on screen as five characters rather than as bold.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import re
from typing import Any, Mapping

from .request import (
    MAX_TRANSCRIPT_BYTES,
    MAX_TRANSCRIPT_CHARACTERS,
    SpeechInputRequestError,
    transcript_digest,
)

__all__ = [
    "FinalTranscript",
    "PartialTranscript",
    "TranscriptError",
    "bounded_transcript_text",
    "pango_escaped",
]

#: Control characters that must not survive into a label, a log or a task
#: request. Newlines and tabs are absent because they are *whitespace* and the
#: collapse in :func:`bounded_transcript_text` has already turned them into
#: single spaces before this pattern runs; what this refuses is the rest —
#: NULs, escapes, the characters that rewrite a terminal or truncate a C
#: string — for which no normalisation is honest.
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


class TranscriptError(SpeechInputRequestError):
    """Transcript content this runtime refuses to hold."""


def bounded_transcript_text(value: Any, *, allow_empty: bool = True) -> str:
    """The one place transcript text is validated. Refuses; never truncates.

    A truncated transcript submitted as a task would be the companion doing
    half of what the user said and recording that it did all of it. Over the
    bound is refused, and the refusal reaches the user as "too long, use typed
    input", which is at least true.
    """
    if not isinstance(value, str):
        raise TranscriptError("transcript text must be a string")
    body = " ".join(value.split())
    if _CONTROL.search(body):
        raise TranscriptError("transcript text contains control characters and was refused")
    if not body and not allow_empty:
        raise TranscriptError("the transcript is empty; there is nothing to submit")
    if len(body) > MAX_TRANSCRIPT_CHARACTERS:
        raise TranscriptError(
            f"the transcript is {len(body)} characters against a limit of "
            f"{MAX_TRANSCRIPT_CHARACTERS}; it was refused rather than shortened"
        )
    encoded = len(body.encode("utf-8"))
    if encoded > MAX_TRANSCRIPT_BYTES:
        raise TranscriptError(
            f"the transcript is {encoded} bytes against a limit of {MAX_TRANSCRIPT_BYTES}; "
            "it was refused rather than shortened"
        )
    return body


def pango_escaped(text: str) -> str:
    """Transcript text as GTK markup may carry it: five entities, nothing clever.

    The order matters — ampersand first, or the escapes themselves would be
    re-escaped. This is deliberately not a general sanitiser: transcript text
    has already been through :func:`bounded_transcript_text`, and the only
    remaining hazard on the way to a label is markup interpretation.
    """
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


@dataclass(frozen=True)
class PartialTranscript:
    """A provisional reading, replaceable by the next one. Never submittable.

    ``revision`` is per-request and strictly monotonic: a surface holding
    revision 7 that receives revision 5 drops it, which is how an old partial
    arriving after a cancellation or a retry is prevented from repainting text
    the user already watched disappear (§16). ``stable_prefix`` is the number
    of leading characters the recogniser does not expect to change; a surface
    may render the rest differently, and a recogniser that does not know sends
    zero rather than a guess.
    """

    request_id: str
    revision: int
    text: str
    provider_id: str
    implementation_id: str = ""
    confidence: float | None = None
    stable_prefix: int = 0
    #: Audio position when this partial was produced, in seconds.
    position_seconds: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "text", bounded_transcript_text(self.text))
        if not isinstance(self.revision, int) or isinstance(self.revision, bool) or self.revision < 0:
            raise TranscriptError("a partial transcript revision is a non-negative integer")
        if self.confidence is not None and not 0.0 <= float(self.confidence) <= 1.0:
            raise TranscriptError("confidence is a fraction between 0 and 1")
        if not 0 <= int(self.stable_prefix) <= len(self.text):
            raise TranscriptError("stablePrefix must lie within the text")

    @property
    def provisional(self) -> bool:
        """Always ``True``. Present so the claim is on the wire, not implied."""
        return True

    def to_json(self) -> dict[str, Any]:
        return {
            "requestId": self.request_id,
            "revision": self.revision,
            "text": self.text,
            "provisional": True,
            "providerId": self.provider_id,
            "implementationId": self.implementation_id,
            "confidence": self.confidence,
            "stablePrefix": self.stable_prefix,
            "positionSeconds": round(self.position_seconds, 4),
        }


@dataclass(frozen=True)
class FinalTranscript:
    """The recogniser's complete answer, with everything §13 requires of one."""

    request_id: str
    session_id: str
    text: str
    provider_id: str
    implementation_id: str = ""
    language: str = "en"
    confidence: float | None = None
    #: Audio boundaries, in seconds from capture start.
    audio_started_at: float = 0.0
    audio_ended_at: float = 0.0
    #: SHA-256-derived digest of the captured audio, where policy permits one.
    #: The digest is what §8 allows the record to keep; the audio is not.
    audio_digest: str = ""
    #: ``streaming`` or ``batch`` — which recognition path produced this.
    recognition_mode: str = "streaming"
    #: ``True`` once the user has changed the text. Set through
    #: :meth:`edited`, never at construction from a recogniser.
    user_edited: bool = False
    #: ``True`` when capture ended abnormally — device loss, cancellation
    #: mid-recognition — and this text covers only part of what was said. §17:
    #: preserved, marked, and never silently treated as complete.
    incomplete: bool = False
    #: Digest of :attr:`text`, derived; the identity a confirmation binds to.
    text_digest: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "text", bounded_transcript_text(self.text))
        if self.confidence is not None and not 0.0 <= float(self.confidence) <= 1.0:
            raise TranscriptError("confidence is a fraction between 0 and 1")
        if self.recognition_mode not in ("streaming", "batch"):
            raise TranscriptError(
                f"unknown recognition mode: {self.recognition_mode!r}"
            )
        if self.audio_ended_at and self.audio_ended_at < self.audio_started_at:
            raise TranscriptError("the audio cannot end before it starts")
        object.__setattr__(self, "text_digest", transcript_digest(self.text))

    def edited(self, text: str) -> "FinalTranscript":
        """The user's correction, as a new transcript marked as theirs.

        A new frozen value rather than a mutation, so the recogniser's answer
        and the user's answer both exist and the record can carry which was
        submitted. An edit to the same text is still an edit — the user
        reviewed it and touched it — but produces the same digest, which is
        what confirmation binds to.
        """
        return replace(
            self,
            text=bounded_transcript_text(text, allow_empty=False),
            user_edited=True,
            text_digest="",  # rederived in __post_init__
        )

    def redacted(self) -> dict[str, Any]:
        """What a diagnostic record may hold: identity and shape, never the words."""
        return {
            "requestId": self.request_id,
            "sessionId": self.session_id,
            "textDigest": self.text_digest,
            "textCharacters": len(self.text),
            "providerId": self.provider_id,
            "implementationId": self.implementation_id,
            "language": self.language,
            "confidence": self.confidence,
            "recognitionMode": self.recognition_mode,
            "userEdited": self.user_edited,
            "incomplete": self.incomplete,
        }

    def to_json(self, *, include_text: bool = True) -> dict[str, Any]:
        document: dict[str, Any] = {
            "requestId": self.request_id,
            "sessionId": self.session_id,
            "providerId": self.provider_id,
            "implementationId": self.implementation_id,
            "language": self.language,
            "confidence": self.confidence,
            "audioStartedAt": round(self.audio_started_at, 4),
            "audioEndedAt": round(self.audio_ended_at, 4),
            "audioDigest": self.audio_digest,
            "recognitionMode": self.recognition_mode,
            "userEdited": self.user_edited,
            "incomplete": self.incomplete,
            "textDigest": self.text_digest,
            "textCharacters": len(self.text),
            "provisional": False,
        }
        if include_text:
            document["text"] = self.text
        return document

    @classmethod
    def from_json(cls, document: Mapping[str, Any]) -> "FinalTranscript":
        if not isinstance(document, Mapping):
            raise TranscriptError("a final transcript must be a JSON object")
        return cls(
            request_id=str(document.get("requestId", "")),
            session_id=str(document.get("sessionId", "")),
            text=str(document.get("text", "")),
            provider_id=str(document.get("providerId", "")),
            implementation_id=str(document.get("implementationId", "")),
            language=str(document.get("language", "en")),
            confidence=(
                None if document.get("confidence") is None
                else float(document["confidence"])
            ),
            audio_started_at=float(document.get("audioStartedAt", 0.0)),
            audio_ended_at=float(document.get("audioEndedAt", 0.0)),
            audio_digest=str(document.get("audioDigest", "")),
            recognition_mode=str(document.get("recognitionMode", "streaming")),
            user_edited=bool(document.get("userEdited", False)),
            incomplete=bool(document.get("incomplete", False)),
        )
