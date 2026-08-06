# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Holding a final transcript between the recogniser and the user's yes.

§13's default flow ends with "submit only confirmed text", and this ledger is
where a transcript waits for that confirmation — and where every §16 and §22
attack on the waiting is refused:

* **replay** — a transcript is confirmed once. The second confirmation is
  refused with the fact, exactly as an approval is (§9's rule, borrowed with
  its reasoning);
* **cross-session confirmation** — the confirming client repeats the session
  id, and a mismatch is a refusal, because a transcript dictated into one
  session must not become a task in another;
* **staleness** — a confirmation names the transcript digest it reviewed.
  After a retry has superseded the transcript, the old digest no longer
  matches and the confirmation is refused: the user cannot submit words that
  are no longer on their screen;
* **expiry** — a pending transcript lapses on the monotonic clock, because
  dictated text waiting forever for a yes is a recording with extra steps.

What this ledger conspicuously cannot do is submit. :meth:`confirm` returns
the confirmed transcript to its caller and the caller — the gateway, which
holds the runtime — creates the task. The speech subsystem keeps no runtime,
no store and no session object, so "speech input cannot create a task" stays
a fact about the object graph (§1), with the one seam where text crosses into
task authority sitting in the gateway where every other authority crossing
already lives.
"""

from __future__ import annotations

from dataclasses import dataclass
import threading
from typing import Any

from ..clock import Clock, SystemClock
from .transcript import FinalTranscript, TranscriptError, bounded_transcript_text

__all__ = [
    "ConfirmationLedger",
    "ConfirmedSubmission",
    "PendingTranscript",
]

#: How long a final transcript waits for its confirmation before it lapses.
DEFAULT_CONFIRMATION_SECONDS = 300.0

#: The most transcripts that may wait at once, across all sessions. A user has
#: one microphone; a ledger holding dozens of pending transcripts is a client
#: looping, and the bound turns that into a refusal rather than growth.
MAX_PENDING = 8


@dataclass
class PendingTranscript:
    """One transcript waiting for a person, and what has happened to it."""

    transcript: FinalTranscript
    expires_at_monotonic: float
    cancellation_token: str = ""
    #: ``pending``, ``confirmed``, ``rejected``, ``superseded`` or ``expired``.
    state: str = "pending"
    #: Set when the immediate-submission preference applied to this capture;
    #: the service confirms on the user's standing instruction and records
    #: that it did.
    immediate: bool = False
    detail: str = ""

    def to_json(self, *, include_text: bool = True) -> dict[str, Any]:
        return {
            "transcript": self.transcript.to_json(include_text=include_text),
            "expiresAtMonotonic": self.expires_at_monotonic,
            "state": self.state,
            "immediate": self.immediate,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ConfirmedSubmission:
    """What the gateway may turn into a task: confirmed text and its provenance."""

    transcript: FinalTranscript
    confirmed_at_monotonic: float
    #: ``user`` for an explicit confirmation, ``immediate-preference`` for the
    #: §13 exception. Recorded on the submission so the task's origin says
    #: which kind of yes it was.
    confirmed_by: str = "user"

    @property
    def text(self) -> str:
        return self.transcript.text

    def to_json(self) -> dict[str, Any]:
        return {
            "transcript": self.transcript.to_json(),
            "confirmedAtMonotonic": self.confirmed_at_monotonic,
            "confirmedBy": self.confirmed_by,
        }


class ConfirmationLedger:
    """Every transcript between recognition and decision, and nothing after."""

    def __init__(self, *, clock: Clock | None = None) -> None:
        self.clock = clock or SystemClock()
        self._pending: dict[str, PendingTranscript] = {}
        self._guard = threading.RLock()

    # ----------------------------------------------------------------- #

    def hold(
        self,
        transcript: FinalTranscript,
        *,
        cancellation_token: str = "",
        immediate: bool = False,
        lifetime_seconds: float = DEFAULT_CONFIRMATION_SECONDS,
    ) -> tuple[PendingTranscript | None, str]:
        """Take a final transcript into the waiting state.

        A second final for the same request supersedes the first — that is the
        retry path — and the ledger is bounded: at :data:`MAX_PENDING` waiting
        transcripts the oldest lapsed entries are swept and, if the ledger is
        still full, the hold is refused.
        """
        now = self.clock.monotonic()
        with self._guard:
            self._sweep(now)
            existing = self._pending.get(transcript.request_id)
            if existing is not None and existing.state == "pending":
                existing.state = "superseded"
                existing.detail = "replaced by a newer recognition of the same request"
            live = sum(1 for item in self._pending.values() if item.state == "pending")
            if live >= MAX_PENDING:
                return None, (
                    f"{live} transcripts are already waiting for confirmation; "
                    "this one was refused rather than queued without bound"
                )
            entry = PendingTranscript(
                transcript=transcript,
                expires_at_monotonic=now + max(1.0, lifetime_seconds),
                cancellation_token=cancellation_token,
                immediate=immediate,
            )
            self._pending[transcript.request_id] = entry
            return entry, ""

    def get(self, request_id: str) -> PendingTranscript | None:
        with self._guard:
            self._sweep(self.clock.monotonic())
            return self._pending.get(request_id)

    # ----------------------------------------------------------------- #

    def confirm(
        self,
        request_id: str,
        *,
        session_id: str,
        text: str | None = None,
        reviewed_digest: str = "",
        cancellation_token: str = "",
        confirmed_by: str = "user",
    ) -> tuple[ConfirmedSubmission | None, str]:
        """One confirmation, checked against everything it must be about.

        ``text`` present means the user edited; the submission carries their
        words marked as theirs. ``reviewed_digest``, when supplied, must match
        the pending transcript's — the staleness check that makes "confirm
        what you are looking at" a comparison rather than a hope.
        """
        now = self.clock.monotonic()
        with self._guard:
            self._sweep(now)
            entry = self._pending.get(request_id)
            if entry is None:
                return None, f"there is no transcript waiting for confirmation as {request_id!r}"
            if entry.transcript.session_id != session_id:
                return None, (
                    "this transcript belongs to a different session; a transcript is "
                    "confirmed in the session it was dictated into"
                )
            if entry.state == "confirmed":
                return None, (
                    "this transcript has already been confirmed; a transcript becomes "
                    "a task once"
                )
            if entry.state == "superseded":
                return None, (
                    "this transcript was superseded by a retry; confirm the one that is "
                    "on the screen"
                )
            if entry.state == "rejected":
                return None, "this transcript was rejected and cannot be confirmed afterwards"
            if entry.state == "expired" or now >= entry.expires_at_monotonic:
                entry.state = "expired"
                return None, "this transcript lapsed before it was confirmed"
            if entry.cancellation_token and cancellation_token != entry.cancellation_token:
                return None, "the confirmation does not carry this capture's token"
            if reviewed_digest and reviewed_digest != entry.transcript.text_digest:
                return None, (
                    "the confirmation names a different transcript than the one waiting; "
                    "the text has changed since it was reviewed"
                )
            transcript = entry.transcript
            if text is not None:
                try:
                    candidate = bounded_transcript_text(text, allow_empty=False)
                except TranscriptError as exc:
                    return None, str(exc)
                if candidate != transcript.text:
                    transcript = transcript.edited(candidate)
            entry.state = "confirmed"
            entry.detail = f"confirmed by {confirmed_by}"
            entry.transcript = transcript
            return ConfirmedSubmission(
                transcript=transcript,
                confirmed_at_monotonic=now,
                confirmed_by=confirmed_by,
            ), ""

    def reject(
        self,
        request_id: str,
        *,
        session_id: str = "",
        cancellation_token: str = "",
        reason: str = "rejected by the user",
    ) -> tuple[bool, str]:
        """The user said no. Idempotent: a second rejection reports itself."""
        with self._guard:
            entry = self._pending.get(request_id)
            if entry is None:
                return False, f"there is no transcript waiting as {request_id!r}"
            if session_id and entry.transcript.session_id != session_id:
                return False, "this transcript belongs to a different session"
            if entry.cancellation_token and cancellation_token and \
                    cancellation_token != entry.cancellation_token:
                return False, "the rejection does not carry this capture's token"
            if entry.state == "confirmed":
                return False, "this transcript was already confirmed and cannot be rejected"
            already = entry.state == "rejected"
            entry.state = "rejected"
            entry.detail = reason
            return not already, "" if not already else "already rejected"

    def supersede(self, request_id: str, *, reason: str = "a retry replaced it") -> bool:
        """A retry is underway; the waiting transcript may no longer be confirmed."""
        with self._guard:
            entry = self._pending.get(request_id)
            if entry is None or entry.state != "pending":
                return False
            entry.state = "superseded"
            entry.detail = reason
            return True

    # ----------------------------------------------------------------- #

    def _sweep(self, now: float) -> None:
        """Lapse what expired; drop what nothing can ask about any more.

        Terminal entries are kept briefly — their state *is* the answer to a
        late confirm — and dropped once the ledger grows past twice its bound.
        """
        for entry in self._pending.values():
            if entry.state == "pending" and now >= entry.expires_at_monotonic:
                entry.state = "expired"
                entry.detail = "lapsed before it was confirmed"
        if len(self._pending) > MAX_PENDING * 2:
            terminal = [
                request_id for request_id, entry in self._pending.items()
                if entry.state != "pending"
            ]
            for request_id in terminal[: len(self._pending) - MAX_PENDING]:
                self._pending.pop(request_id, None)

    def describe(self) -> dict[str, Any]:
        with self._guard:
            self._sweep(self.clock.monotonic())
            return {
                "pending": sum(
                    1 for item in self._pending.values() if item.state == "pending"
                ),
                "held": {
                    request_id: entry.to_json(include_text=False)
                    for request_id, entry in self._pending.items()
                },
                "maximumPending": MAX_PENDING,
                "submitsDirectly": False,
                "confirmationDefault": True,
            }
