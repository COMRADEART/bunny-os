# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The caption is the output. Speech is a second rendering of it.

§8's rule is short and everything here follows from it: **captions remain the
authoritative accessible output.** Speech consumes a caption or a sanitized
derivative of one, carries a reference back to it, and cannot alter it. There is
no path in this package by which the voice runtime composes a sentence the user
has not already been shown.

That inverts the usual arrangement, and the inversion is the point. A companion
that generated speech and captioned it afterwards would have two renderings that
can disagree, and the one a deaf user reads would be the derived one. Here the
caption comes from :class:`companion.presentation.PresentationState` — the
canonical projection, already bounded, already redacted at the ``ui`` ceiling —
and the utterance is derived from *it*. A machine with no synthesiser, a broken
speaker or a muted session loses the sound and nothing else.

**A task never fails because speech failed.** Nothing in this module raises at a
caller that has a task to keep alive, and :class:`SpeechDisposition` has no
value that means "the task did not complete".

**Replay does not re-speak.** :meth:`CaptionLedger.speak_once` refuses a second
utterance for a caption that has already been spoken, and §20 relies on it: a
GTK client that restarts and re-reads the presentation stream would otherwise
narrate the whole task again from the beginning, which is the single most
alarming thing a companion can do to somebody who just restarted it.

**This ledger is not a second caption store.** It holds a copy of the text so a
request can be derived from it, the timings §14 measures, and what has already
been spoken. It is never read by a surface, and no protocol operation returns
its text. The projection remains the only thing anything displays.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import threading
from typing import Any, Mapping, Sequence

from ..clock import Clock, SystemClock
from ..ids import IdSource, RandomIds
from ..presentation import PresentationState
from ..privacy import display_summary
from .request import (
    InterruptionPolicy,
    Priority,
    VoiceRequest,
    VoiceRequestError,
    coalescing_key,
    priority_for_phase,
    sanitized_speech_text,
)

__all__ = [
    "Caption",
    "CaptionLedger",
    "SpeechDisposition",
    "SyncMeasurement",
    "TOLERANCES",
    "caption_from_state",
]


class SpeechDisposition:
    """Every way one utterance can end. §7's list, and nothing outside it.

    A closed vocabulary because §7 requires the outcome to be *recorded* and a
    record with free-text outcomes cannot be counted across a hundred runs. Note
    what is absent: there is no ``failed_task``, no ``blocked`` and no
    ``denied``. Speech has no vocabulary for affecting a task because it has no
    ability to.
    """

    QUEUED = "queued"
    PLAYED = "played"
    INTERRUPTED = "interrupted"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"
    DROPPED = "dropped_by_policy"
    COALESCED = "coalesced"
    FAILED = "failed"
    DEGRADED_TO_CAPTIONS = "degraded_to_captions"
    EXPIRED = "expired"

    ALL = (
        QUEUED, PLAYED, INTERRUPTED, CANCELLED, SUPERSEDED, DROPPED,
        COALESCED, FAILED, DEGRADED_TO_CAPTIONS, EXPIRED,
    )

    #: Dispositions in which the user heard at least part of the utterance.
    #: Used by §20: a completed utterance is not replayed after a restart, and
    #: an interrupted one is not either — it is *marked* interrupted, and
    #: repeating it would be the runtime deciding the user wants to hear it
    #: again.
    HEARD = (PLAYED, INTERRUPTED)

    #: Dispositions where the caption was the whole of the output. Every one of
    #: them is a success from the task's point of view.
    SILENT = (DROPPED, COALESCED, FAILED, DEGRADED_TO_CAPTIONS, EXPIRED, CANCELLED, SUPERSEDED)


@dataclass(frozen=True)
class Tolerances:
    """§14's acceptable offsets for this environment, stated as numbers.

    Development-environment figures, and labelled as such: they were chosen
    against the reference target (Fedora 44 under WSL, audio through the WSLg
    bridge) where playback start is dominated by an RDP hop that a physical
    sound card would not have. A build validated on real hardware would tighten
    them; a build that stated no numbers at all could not be tested against.
    """

    #: The caption must be shown *before* audio starts, or at worst with it.
    #: Negative would mean audio led the caption, which §8 forbids outright —
    #: somebody reading rather than listening would be behind.
    caption_lead_minimum_ms: int = 0
    #: How far ahead the caption may be before it stops being "with" the speech.
    #: Two seconds is long enough to cover a cold synthesiser start and short
    #: enough that the caption has not scrolled away.
    caption_lead_maximum_ms: int = 2000
    #: Mouth against sound. Matches
    #: :attr:`companion.voice.visemes.VisemeScheduler.DEFAULT_DRIFT_LIMIT_MS`
    #: so the measurement and the runtime behaviour agree about what is in sync.
    viseme_offset_maximum_ms: int = 120
    #: How long after the audio ends the mouth may still be moving.
    neutral_reset_maximum_ms: int = 250
    #: How long a caption may remain non-final after the audio finished.
    caption_finalisation_maximum_ms: int = 1000

    def to_json(self) -> dict[str, Any]:
        return {
            "captionLeadMinimumMs": self.caption_lead_minimum_ms,
            "captionLeadMaximumMs": self.caption_lead_maximum_ms,
            "visemeOffsetMaximumMs": self.viseme_offset_maximum_ms,
            "neutralResetMaximumMs": self.neutral_reset_maximum_ms,
            "captionFinalisationMaximumMs": self.caption_finalisation_maximum_ms,
            "environment": "development; audio via the WSLg bridge, no physical speaker validated",
        }


TOLERANCES = Tolerances()


@dataclass(frozen=True)
class Caption:
    """One thing the companion said, as the canonical runtime produced it.

    ``final`` distinguishes a caption that may still be revised — a status line
    during ``working`` — from the one that stands. §8 wants both: partial
    updates while a task runs, and a final caption that is what remains
    afterwards. Speech is normally derived from a final caption; a partial one
    can be spoken when it is urgent, and the reference in the request records
    which revision was read.
    """

    caption_id: str
    session_id: str
    task_id: str
    text: str
    revision: int = 0
    final: bool = False
    phase: str = "idle"
    classification: str = "internal"
    approval_pending: bool = False
    created_at_wall: float = 0.0
    created_at_monotonic: float = 0.0
    #: When the surface reported the caption on screen. Zero until a client says
    #: so; §14's caption-to-audio offset is measured from this, and measuring it
    #: from when the caption was *produced* would flatter the number by the
    #: whole of the render path.
    shown_at_monotonic: float = 0.0

    @property
    def speakable(self) -> bool:
        return bool(self.text.strip())

    def to_json(self, *, include_text: bool = False) -> dict[str, Any]:
        document = {
            "captionId": self.caption_id,
            "sessionId": self.session_id,
            "taskId": self.task_id,
            "revision": self.revision,
            "final": self.final,
            "phase": self.phase,
            "classification": self.classification,
            "approvalPending": self.approval_pending,
            "characters": len(self.text),
            "createdAtWall": self.created_at_wall,
            "shownAtMonotonic": self.shown_at_monotonic,
        }
        if include_text:
            document["text"] = self.text
        return document


def caption_from_state(
    state: PresentationState,
    *,
    caption_id: str,
    clock: Clock | None = None,
) -> Caption:
    """Read the caption out of the canonical projection. Composes nothing.

    Which of the projection's sentences is *the* caption follows
    :func:`companion.character.integration.bubble_request_for` exactly — the
    speech bubble and the voice must say the same thing, and the way to
    guarantee that is for both to apply one priority order. Duplicating it here
    rather than importing it would be the second interpretation this whole
    architecture exists to avoid, so the order is stated once, in a comment, and
    matched: approval, then error, then result, then status.
    """
    clock = clock or SystemClock()
    if state.approval_state == "pending" or state.approvals or state.phase == "waiting_for_approval":
        approval = state.approvals[0] if state.approvals else None
        text = (approval.reason if approval is not None and approval.reason else "") or state.status_text
        final = False
    elif state.phase in ("error", "blocked"):
        text = state.error_summary or state.status_text
        final = True
    elif state.error_summary and state.phase not in ("success", "presenting_result"):
        text = state.error_summary
        final = False
    elif state.phase in ("success", "presenting_result") and state.result_summary:
        text = state.result_summary
        final = True
    else:
        text = state.status_text
        final = state.phase in ("cancelled", "success")

    return Caption(
        caption_id=caption_id,
        session_id=state.session_id,
        task_id=state.task_id,
        # Bounded with the projection's own summariser so the spoken and the
        # displayed text are cut at the same place by the same code.
        text=display_summary(text or ""),
        revision=state.revision,
        final=final,
        phase=state.phase,
        classification=state.privacy_classification,
        approval_pending=state.approval_state == "pending" or bool(state.approvals),
        created_at_wall=clock.wall(),
        created_at_monotonic=clock.monotonic(),
    )


@dataclass
class SyncMeasurement:
    """§14's offsets for one utterance, and whether each is inside tolerance.

    Every field is a monotonic reading or a derived difference. A measurement
    with no reading is ``None`` rather than zero, because zero is a legitimate
    offset and "we did not measure this" must not average in as a perfect score.
    """

    request_id: str
    caption_id: str
    tolerances: Tolerances = field(default_factory=lambda: TOLERANCES)
    caption_shown_at: float | None = None
    speech_requested_at: float | None = None
    synthesis_started_at: float | None = None
    synthesis_finished_at: float | None = None
    audio_started_at: float | None = None
    audio_finished_at: float | None = None
    first_viseme_at: float | None = None
    neutral_at: float | None = None
    caption_finalised_at: float | None = None
    viseme_source: str = ""

    @staticmethod
    def _ms(later: float | None, earlier: float | None) -> int | None:
        if later is None or earlier is None:
            return None
        return int(round((later - earlier) * 1000))

    @property
    def caption_to_audio_ms(self) -> int | None:
        """Positive means the caption led the audio, which is the correct sign."""
        return self._ms(self.audio_started_at, self.caption_shown_at)

    @property
    def viseme_to_audio_ms(self) -> int | None:
        """Positive means the mouth started after the sound."""
        return self._ms(self.first_viseme_at, self.audio_started_at)

    @property
    def synthesis_latency_ms(self) -> int | None:
        return self._ms(self.synthesis_finished_at, self.synthesis_started_at)

    @property
    def time_to_first_audio_ms(self) -> int | None:
        return self._ms(self.audio_started_at, self.speech_requested_at)

    @property
    def neutral_reset_ms(self) -> int | None:
        return self._ms(self.neutral_at, self.audio_finished_at)

    @property
    def caption_finalisation_ms(self) -> int | None:
        return self._ms(self.caption_finalised_at, self.audio_finished_at)

    def violations(self) -> tuple[str, ...]:
        """Every tolerance this utterance broke. Unmeasured is never a violation."""
        problems: list[str] = []
        lead = self.caption_to_audio_ms
        if lead is not None:
            if lead < self.tolerances.caption_lead_minimum_ms:
                problems.append(
                    f"audio started {-lead} ms before the caption was shown; "
                    "the caption must never trail the speech"
                )
            elif lead > self.tolerances.caption_lead_maximum_ms:
                problems.append(
                    f"the caption led the audio by {lead} ms, beyond the "
                    f"{self.tolerances.caption_lead_maximum_ms} ms tolerance"
                )
        offset = self.viseme_to_audio_ms
        if offset is not None and abs(offset) > self.tolerances.viseme_offset_maximum_ms:
            problems.append(
                f"the mouth started {offset} ms from the audio, beyond the "
                f"{self.tolerances.viseme_offset_maximum_ms} ms tolerance"
            )
        reset = self.neutral_reset_ms
        if reset is not None and reset > self.tolerances.neutral_reset_maximum_ms:
            problems.append(
                f"the mouth took {reset} ms to return to neutral, beyond the "
                f"{self.tolerances.neutral_reset_maximum_ms} ms tolerance"
            )
        finalisation = self.caption_finalisation_ms
        if finalisation is not None and finalisation > self.tolerances.caption_finalisation_maximum_ms:
            problems.append(
                f"the caption was finalised {finalisation} ms after the audio ended"
            )
        return tuple(problems)

    @property
    def within_tolerance(self) -> bool:
        return not self.violations()

    def to_json(self) -> dict[str, Any]:
        return {
            "requestId": self.request_id,
            "captionId": self.caption_id,
            "captionToAudioMs": self.caption_to_audio_ms,
            "visemeToAudioMs": self.viseme_to_audio_ms,
            "synthesisLatencyMs": self.synthesis_latency_ms,
            "timeToFirstAudioMs": self.time_to_first_audio_ms,
            "neutralResetMs": self.neutral_reset_ms,
            "captionFinalisationMs": self.caption_finalisation_ms,
            "visemeSource": self.viseme_source,
            "withinTolerance": self.within_tolerance,
            "violations": list(self.violations()),
            "tolerances": self.tolerances.to_json(),
        }


class CaptionLedger:
    """What has been captioned, what has been spoken, and what may be spoken next.

    The "may" is the part that matters. :meth:`speak_once` is the only way a
    caption becomes an utterance, and it refuses in four cases, each of which is
    a §8 or §20 requirement rather than a policy knob:

    * the caption has already been spoken — §20's no-automatic-replay;
    * the same words are already queued for the same task at the same rank —
      §7's coalescing;
    * the caption has no speakable text;
    * the text cannot be reduced to a valid request.

    Refusals are returned, never raised. A projection arriving with nothing to
    say is the ordinary case, not an error.
    """

    #: The most captions remembered. A task's whole history of status lines is
    #: not needed — only enough to recognise a replay and to coalesce a repeat —
    #: and an unbounded ledger in a service that runs for days is a leak with a
    #: dictionary in front of it.
    MAX_CAPTIONS = 512

    def __init__(
        self,
        *,
        ids: IdSource | None = None,
        clock: Clock | None = None,
        tolerances: Tolerances = TOLERANCES,
    ) -> None:
        self.ids = ids or RandomIds()
        self.clock = clock or SystemClock()
        self.tolerances = tolerances
        self._captions: dict[str, Caption] = {}
        self._order: list[str] = []
        self._spoken: dict[str, str] = {}
        self._coalescing: dict[tuple[str, str, int], str] = {}
        self._measurements: dict[str, SyncMeasurement] = {}
        self._guard = threading.RLock()

    # ----------------------------------------------------------------- #

    def publish(self, state: PresentationState) -> Caption:
        """Record the caption the canonical projection currently holds.

        Idempotent per ``(task, revision, text)``: a client polling the
        projection re-publishes the same caption repeatedly and must not create
        a new one each time, or the replay guard would never match.
        """
        with self._guard:
            provisional = caption_from_state(state, caption_id="c-0", clock=self.clock)
            for existing in reversed(self._order[-32:]):
                candidate = self._captions[existing]
                if (
                    candidate.task_id == provisional.task_id
                    and candidate.revision == provisional.revision
                    and candidate.text == provisional.text
                ):
                    return candidate
            caption = caption_from_state(
                state, caption_id=self.ids.next("cap"), clock=self.clock
            )
            self._captions[caption.caption_id] = caption
            self._order.append(caption.caption_id)
            self._evict()
            return caption

    def _evict(self) -> None:
        while len(self._order) > self.MAX_CAPTIONS:
            oldest = self._order.pop(0)
            self._captions.pop(oldest, None)
            self._measurements.pop(oldest, None)

    def get(self, caption_id: str) -> Caption | None:
        with self._guard:
            return self._captions.get(caption_id)

    def mark_shown(self, caption_id: str, *, monotonic: float | None = None) -> Caption | None:
        """A surface reported this caption on screen. §14's zero point.

        Called by the client, not inferred here. A caption the runtime produced
        is not a caption anybody has seen, and inferring the display time from
        the production time would build the whole render path's latency into
        every measurement as if it were zero.
        """
        with self._guard:
            caption = self._captions.get(caption_id)
            if caption is None:
                return None
            shown = self.clock.monotonic() if monotonic is None else monotonic
            updated = Caption(**{**caption.__dict__, "shown_at_monotonic": shown})
            self._captions[caption_id] = updated
            measurement = self._measurements.get(caption_id)
            if measurement is not None and measurement.caption_shown_at is None:
                measurement.caption_shown_at = shown
            return updated

    # ----------------------------------------------------------------- #

    def already_spoken(self, caption_id: str) -> str:
        """The request id that spoke this caption, or ``""``."""
        with self._guard:
            return self._spoken.get(caption_id, "")

    def record_disposition(self, caption_id: str, request_id: str, disposition: str) -> None:
        """Remember whether a caption was heard, so a replay does not repeat it.

        Only :data:`SpeechDisposition.HEARD` marks a caption spoken. A cancelled
        or dropped utterance leaves the caption speakable, which is what makes
        an explicit "read that again" work after a failure while an automatic
        replay after a restart still does not.
        """
        if disposition not in SpeechDisposition.ALL:
            raise ValueError(f"unknown speech disposition: {disposition!r}")
        with self._guard:
            if disposition in SpeechDisposition.HEARD:
                self._spoken[caption_id] = request_id
                if len(self._spoken) > self.MAX_CAPTIONS:
                    for key in list(self._spoken)[: len(self._spoken) - self.MAX_CAPTIONS]:
                        self._spoken.pop(key, None)
            for key, value in list(self._coalescing.items()):
                if value == request_id:
                    self._coalescing.pop(key, None)

    def speak_once(
        self,
        caption: Caption,
        *,
        priority: Priority | None = None,
        interruption_policy: InterruptionPolicy | None = None,
        voice_id: str = "",
        language: str = "en",
        locale: str = "en-GB",
        speaking_rate: float = 1.0,
        volume: float = 1.0,
        prefer_streaming: bool = False,
        expires_in_seconds: float = 120.0,
        force: bool = False,
    ) -> tuple[VoiceRequest | None, str]:
        """Derive an utterance from a caption, or say why there will not be one.

        ``force`` is the *explicit* replay §20 permits: a user pressing "read
        that again" is a new request, and it goes through the same construction
        with the same bounds. Nothing in the runtime sets it; only a deliberate
        protocol call does.
        """
        if not caption.speakable:
            return None, "the caption has no text to speak"
        with self._guard:
            if not force and caption.caption_id in self._spoken:
                return None, (
                    "this caption has already been spoken; a replay is an explicit request "
                    "rather than something a restart does on its own"
                )

        text = sanitized_speech_text(caption.text)
        if not text:
            return None, "nothing survived sanitising the caption into speech"

        rank = priority or priority_for_phase(caption.phase, approval_pending=caption.approval_pending)
        policy = interruption_policy or (
            InterruptionPolicy.INTERRUPT
            if rank.value <= Priority.APPROVAL_REQUIRED.value
            else InterruptionPolicy.QUEUE
        )
        now_wall = self.clock.wall()
        now_monotonic = self.clock.monotonic()
        try:
            request = VoiceRequest(
                request_id=self.ids.next("speech"),
                session_id=caption.session_id,
                task_id=caption.task_id,
                caption_reference=caption.caption_id,
                speech_text=text,
                presentation_revision=caption.revision,
                language=language,
                locale=locale,
                voice_id=voice_id,
                speaking_rate=speaking_rate,
                volume=volume,
                prefer_streaming=prefer_streaming,
                privacy_classification=caption.classification,
                locality_requirement="device-only",
                cost_ceiling_units=0,
                created_at_wall=now_wall,
                created_at_monotonic=now_monotonic,
                expires_at_monotonic=now_monotonic + max(1.0, expires_in_seconds),
                cancellation_token=self.ids.next("cancel"),
                priority=rank,
                interruption_policy=policy,
            )
        except VoiceRequestError as exc:
            # Returned rather than raised: a caption that cannot become speech is
            # a caption that stays on the screen, and the caller has a task to
            # finish either way.
            return None, str(exc)

        key = coalescing_key(request)
        with self._guard:
            if not force and key in self._coalescing:
                return None, (
                    f"the same words are already queued for this task at "
                    f"{request.priority.wire}; the repeat was coalesced"
                )
            self._coalescing[key] = request.request_id
            self._measurements[request.request_id] = SyncMeasurement(
                request_id=request.request_id,
                caption_id=caption.caption_id,
                tolerances=self.tolerances,
                caption_shown_at=caption.shown_at_monotonic or None,
                speech_requested_at=now_monotonic,
            )
        return request, ""

    # ----------------------------------------------------------------- #

    def measurement(self, request_id: str) -> SyncMeasurement | None:
        with self._guard:
            return self._measurements.get(request_id)

    def measurements(self) -> tuple[SyncMeasurement, ...]:
        with self._guard:
            return tuple(self._measurements.values())

    def release(self, request_id: str) -> None:
        """Forget the coalescing entry for a request that will never be spoken."""
        with self._guard:
            for key, value in list(self._coalescing.items()):
                if value == request_id:
                    self._coalescing.pop(key, None)

    def describe(self) -> dict[str, Any]:
        with self._guard:
            measured = [item for item in self._measurements.values() if item.audio_started_at]
            return {
                "captions": len(self._captions),
                "spoken": len(self._spoken),
                "queuedContent": len(self._coalescing),
                "measured": len(measured),
                "withinTolerance": sum(1 for item in measured if item.within_tolerance),
                "tolerances": self.tolerances.to_json(),
                "captionsAuthoritative": True,
                "voiceMayComposeText": False,
            }
