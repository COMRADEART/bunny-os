# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What the voice runtime is allowed to be asked, and what it may never be told.

A :class:`VoiceRequest` is the whole of the voice runtime's input. Everything
downstream — the provider, the worker, the audio backend, the viseme scheduler —
reads this object and nothing else about the task. That is the point: the
absent fields are the specification. There is no place here for an API key, a
credential, a model's reasoning, a raw tool result, a filesystem destination or
a command line, and adding one would need a new field and a new line in
:meth:`VoiceRequest.to_json`, which is exactly the review this boundary is for.

Three properties are load-bearing and each is enforced at construction rather
than at use:

**The text is bounded in both units.** Characters bound what a person would call
the length; bytes bound what the pipe to a synthesiser actually carries, and the
two differ by a factor of four for text that is mostly non-Latin. Bounding only
characters would let a caller hand a 16 KiB payload to a subprocess through a
field documented as 4000 long. Over either bound is *refused* — never shortened.
A caption that was cut in half and spoken is the companion saying something
other than what is on the screen beside it, and the user has no way to tell.

**The text is a derivative of a caption, not a replacement for it.**
``caption_reference`` is required and names the canonical caption this utterance
speaks. The voice runtime never invents user-visible content; it reads out
something the canonical runtime already produced and already showed. §8.

**Expiry is monotonic.** ``expires_at_monotonic`` is compared against
:meth:`companion.clock.Clock.monotonic` and never against wall time. An
utterance whose expiry could be extended by changing the timezone is an
utterance that can be replayed an hour later into a different task's context.
Monotonic time also does not survive a restart, and :mod:`companion.voice.recovery`
relies on that: a request whose deadline cannot be evaluated is expired, which
is the safe direction for speech as much as for consent.

The priority ladder is §7's, in order, and it is compared by rank and never by
string. The names are for people; the integer is the meaning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Any, Mapping

from capability.apply.identity import digest

from ..ids import valid_id
from ..privacy import DATA_CLASSES, MAX_SUMMARY_LENGTH, rank, scrub_text

__all__ = [
    "AUDIO_FORMATS",
    "InterruptionPolicy",
    "MAX_SPEECH_BYTES",
    "MAX_SPEECH_CHARACTERS",
    "Priority",
    "SAMPLE_RATES",
    "VOICE_REQUEST_SCHEMA_VERSION",
    "VoiceRequest",
    "VoiceRequestError",
    "speech_digest",
]

#: Bumped when a field is added, removed or reinterpreted. A worker that read a
#: version it does not know refuses the request rather than guessing which
#: fields it can still trust.
VOICE_REQUEST_SCHEMA_VERSION = 1

#: The character bound, matching :data:`companion.voice.system.MAX_SPEECH_CHARACTERS`
#: so that the two ways into a synthesiser agree. A caption is bounded at
#: :data:`companion.privacy.MAX_SUMMARY_LENGTH` long before it reaches here; this
#: is the bound at the process boundary, where it protects against a *caller*
#: rather than against a payload.
MAX_SPEECH_CHARACTERS = 4000

#: The byte bound, on the UTF-8 encoding that actually crosses the pipe.
#:
#: **Three** times the character bound, not four, and the difference is the
#: whole point of having a second bound at all. UTF-8 encodes at most four bytes
#: per character, so a byte limit at ``4 × MAX_SPEECH_CHARACTERS`` can never be
#: reached — the character check would always fire first, and the byte check
#: would be decoration that a reader could mistake for protection. At three
#: times, every script that encodes in three bytes or fewer (which is Latin,
#: Greek, Cyrillic, Hebrew, Arabic, Devanagari, Han, Hiragana, Katakana and
#: Hangul — that is, all of prose) gets the full character allowance, while text
#: that is mostly four-byte characters is refused. Four-byte UTF-8 is emoji and
#: historic scripts; 4000 emoji is not a caption, and a synthesiser handed one
#: would produce four thousand descriptions of pictures.
MAX_SPEECH_BYTES = 3 * MAX_SPEECH_CHARACTERS

#: Formats a request may ask for. Deliberately short and deliberately all
#: uncompressed or losslessly framed: every one of these can be produced by a
#: local synthesiser and played by a local backend with no codec in between, and
#: a format that needed a decoder would be a decoder parsing attacker-influenced
#: bytes in the companion's own address space.
AUDIO_FORMATS = ("wav-pcm-s16le", "raw-pcm-s16le")

#: Rates a request may ask for. A provider that cannot produce the requested
#: rate says so; nothing here resamples, because a resampler is a second audio
#: implementation and §12's answer to "the provider cannot do this" is to
#: degrade rather than to compensate.
SAMPLE_RATES = (16_000, 22_050, 24_000, 44_100, 48_000)

#: BCP-47-ish, bounded and restricted. Not a full parser: these end up as
#: subprocess arguments and in file names, and the useful property is "contains
#: nothing that changes meaning at a boundary", not "is grammatical".
_LANGUAGE = re.compile(r"^[a-z]{2,3}\Z")
_LOCALE = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8}){0,2}\Z")

#: A voice identifier is a provider's own name for one of its installed voices.
#: Restricted to the same shape as every other identifier in the runtime because
#: it reaches an argv, and a voice id containing a path separator is a directory
#: traversal looking for somewhere to happen.
_VOICE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}\Z")

#: Control characters that must not survive into an argv or a caption. ``\n`` is
#: included: a synthesiser given a newline is fine, but a *log line* given one is
#: a log line an attacker can forge a second record into.
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


class VoiceRequestError(ValueError):
    """A request that may not be served, with the reason a person needs.

    A ``ValueError`` rather than a :class:`companion.errors.CompanionError`:
    this is a malformed *input*, not a runtime fault, and the distinction
    matters at the protocol boundary where one is a client's bug and the other
    is ours.
    """


class Priority(Enum):
    """§7's ladder. Lower value is more urgent; compared by value, never by name.

    The order is the whole of the meaning and it encodes two separate judgements
    that happen to coincide here: how much the user needs to hear this, and how
    freely it may be thrown away when the machine is under pressure.
    ``DECORATIVE`` is last on both counts, which is why §12 may drop it without
    consulting anything else.
    """

    CRITICAL_WARNING = 0
    APPROVAL_REQUIRED = 1
    TASK_ERROR = 2
    DIRECT_USER_RESPONSE = 3
    TASK_RESULT = 4
    PROGRESS_UPDATE = 5
    DECORATIVE = 6

    @property
    def wire(self) -> str:
        return self.name.lower()

    @classmethod
    def parse(cls, value: Any) -> "Priority":
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            try:
                return cls[value.replace("-", "_").upper()]
            except KeyError:
                pass
        raise VoiceRequestError(f"unknown speech priority: {value!r}")

    @property
    def essential(self) -> bool:
        """Whether §12 must keep this utterance under resource pressure.

        Everything at or above a task result is essential. A progress update is
        narration and a decorative line is atmosphere; neither carries
        information the captions do not already hold, so dropping them costs the
        user nothing but the sound.
        """
        return self.value <= Priority.TASK_RESULT.value


class InterruptionPolicy(Enum):
    """What this utterance does to what is already speaking, and vice versa.

    Separated from :class:`Priority` because they answer different questions.
    Priority says which of two utterances matters more; this says whether the
    more important one *waits*. A task result outranks a progress update and
    still, usually, lets it finish its sentence — cutting a companion off
    mid-word to say something less urgent is how a surface feels broken.
    """

    #: Take the floor now. The current utterance is stopped and recorded
    #: ``interrupted``. Only honoured when this request outranks the current one.
    INTERRUPT = "interrupt"
    #: Wait for the floor. The default, and the only policy that never loses an
    #: utterance to a busy worker.
    QUEUE = "queue"
    #: Speak only if the floor is free right now; otherwise recorded ``dropped``.
    #: For narration whose moment has passed by the time it could be spoken.
    DROP_IF_BUSY = "drop_if_busy"

    @classmethod
    def parse(cls, value: Any) -> "InterruptionPolicy":
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            for item in cls:
                if item.value == value.replace("-", "_"):
                    return item
        raise VoiceRequestError(f"unknown interruption policy: {value!r}")


def speech_digest(text: str) -> str:
    """The identity of an utterance's *content*, independent of its request id.

    Used for three things that all need "is this the same words": refusing a
    duplicate request id that carries different text (§6), coalescing repeated
    progress narration (§7), and writing a diagnostic record that identifies an
    utterance without quoting it (§15).
    """
    return digest({"speechText": text})


def _bounded_text(value: Any) -> str:
    """The one place speech text is validated. Refuses; never truncates."""
    if not isinstance(value, str):
        raise VoiceRequestError("speech text must be a string")
    # Collapsed first, so that the bound is measured against what will actually
    # be spoken rather than against the whitespace a caller happened to send.
    body = " ".join(value.split())
    if not body:
        raise VoiceRequestError("there is no speech text; an empty utterance is not a request")
    if _CONTROL.search(body):
        raise VoiceRequestError("speech text contains control characters and was refused")
    if len(body) > MAX_SPEECH_CHARACTERS:
        raise VoiceRequestError(
            f"speech text is {len(body)} characters against a limit of {MAX_SPEECH_CHARACTERS}; "
            "it was refused rather than shortened, and the caption is unaffected"
        )
    encoded = len(body.encode("utf-8"))
    if encoded > MAX_SPEECH_BYTES:
        raise VoiceRequestError(
            f"speech text is {encoded} bytes against a limit of {MAX_SPEECH_BYTES}; "
            "it was refused rather than shortened, and the caption is unaffected"
        )
    return body


def _identifier(name: str, value: Any, *, required: bool = True) -> str:
    if value in (None, "") and not required:
        return ""
    if not isinstance(value, str) or not valid_id(value):
        raise VoiceRequestError(f"{name} is not a usable identifier")
    return value


@dataclass(frozen=True)
class VoiceRequest:
    """One thing to say, once, with every constraint on saying it.

    Frozen, so that a request cannot be edited after the policy layer has
    approved it. A worker that needed a changed field builds a new request,
    which gets a new id and a fresh trip through validation.
    """

    request_id: str
    session_id: str
    task_id: str
    caption_reference: str
    speech_text: str
    #: The presentation revision the caption was read from. Carried so a client
    #: can tell that an utterance belongs to the state it is looking at, and so
    #: a replayed request against a moved-on presentation is recognisable.
    presentation_revision: int = 0
    language: str = "en"
    locale: str = "en-GB"
    voice_id: str = ""
    speaking_rate: float = 1.0
    #: ``None`` means "the provider's own". A provider that cannot change pitch
    #: reports so through its contract and a request that asked for one is
    #: served at the default with the discrepancy recorded, rather than refused:
    #: pitch is a preference, and refusing speech over it would cost the user
    #: the utterance to satisfy a decoration.
    pitch: float | None = None
    volume: float = 1.0
    audio_format: str = "wav-pcm-s16le"
    sample_rate: int = 22_050
    #: A *preference*. A provider with no streaming path serves it
    #: non-streaming and the degradation is recorded; §12's ladder has
    #: "non-streaming local voice" as a rung for exactly this.
    prefer_streaming: bool = False
    privacy_classification: str = "internal"
    #: The strictest locality this utterance may be served under. ``device-only``
    #: is the only value this build can honour, because this build has no remote
    #: provider; the field exists so that a future one cannot be reached by
    #: *omission*.
    locality_requirement: str = "device-only"
    #: Units this utterance may spend. Zero for every local provider, and the
    #: field is here so that a paid provider could never be selected by a
    #: request that never considered cost.
    cost_ceiling_units: int = 0
    created_at_wall: float = 0.0
    created_at_monotonic: float = 0.0
    #: Monotonic deadline. Zero means "no expiry", which is only correct for a
    #: request built by a test; :func:`companion.voice.captions.speech_request_for`
    #: always sets one.
    expires_at_monotonic: float = 0.0
    #: An opaque token a canceller must present. Not a secret — a local client
    #: already holds the request id — but a value that binds a cancellation to
    #: *this* request rather than to a reused id, so a late cancel for a
    #: completed utterance cannot silence the one that replaced it.
    cancellation_token: str = ""
    priority: Priority = Priority.PROGRESS_UPDATE
    interruption_policy: InterruptionPolicy = InterruptionPolicy.QUEUE
    schema_version: int = VOICE_REQUEST_SCHEMA_VERSION
    #: The content identity. Derived in ``__post_init__``; never supplied.
    text_digest: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_id", _identifier("requestId", self.request_id))
        object.__setattr__(self, "session_id", _identifier("sessionId", self.session_id))
        object.__setattr__(self, "task_id", _identifier("taskId", self.task_id))
        object.__setattr__(
            self, "caption_reference", _identifier("captionReference", self.caption_reference)
        )
        object.__setattr__(self, "speech_text", _bounded_text(self.speech_text))

        if self.schema_version != VOICE_REQUEST_SCHEMA_VERSION:
            raise VoiceRequestError(
                f"this runtime serves voice request schema {VOICE_REQUEST_SCHEMA_VERSION} and the "
                f"request declared {self.schema_version!r}; there is no downgrade path"
            )
        if not isinstance(self.presentation_revision, int) or isinstance(self.presentation_revision, bool):
            raise VoiceRequestError("presentationRevision must be an integer")
        if self.presentation_revision < 0:
            raise VoiceRequestError("presentationRevision cannot be negative")
        if not _LANGUAGE.match(self.language or ""):
            raise VoiceRequestError(f"unsupported language tag: {self.language!r}")
        if not _LOCALE.match(self.locale or ""):
            raise VoiceRequestError(f"unsupported locale tag: {self.locale!r}")
        if not self.locale.lower().startswith(self.language.lower()):
            # A locale that disagrees with its language is the sort of mismatch a
            # provider resolves silently and differently from every other
            # provider. Caught here so the answer is the same everywhere.
            raise VoiceRequestError(
                f"locale {self.locale!r} does not belong to language {self.language!r}"
            )
        if self.voice_id and not _VOICE_ID.match(self.voice_id):
            raise VoiceRequestError(f"voiceId is not a usable voice identifier: {self.voice_id!r}")
        if not 0.25 <= self.speaking_rate <= 4.0:
            raise VoiceRequestError("speakingRate is outside the supported range (0.25 to 4.0)")
        if self.pitch is not None and not 0.5 <= self.pitch <= 2.0:
            raise VoiceRequestError("pitch is outside the supported range (0.5 to 2.0)")
        if not 0.0 <= self.volume <= 1.0:
            raise VoiceRequestError("volume must be between 0 and 1")
        if self.audio_format not in AUDIO_FORMATS:
            raise VoiceRequestError(
                f"unsupported audio format {self.audio_format!r}; this runtime serves "
                f"{', '.join(AUDIO_FORMATS)}"
            )
        if self.sample_rate not in SAMPLE_RATES:
            raise VoiceRequestError(
                f"unsupported sample rate {self.sample_rate!r}; this runtime serves "
                f"{', '.join(str(item) for item in SAMPLE_RATES)}"
            )
        if self.privacy_classification not in DATA_CLASSES:
            raise VoiceRequestError(
                f"unknown privacy classification: {self.privacy_classification!r}"
            )
        if self.locality_requirement not in ("device-only", "trusted-remote", "any"):
            raise VoiceRequestError(f"unknown locality requirement: {self.locality_requirement!r}")
        if not isinstance(self.cost_ceiling_units, int) or isinstance(self.cost_ceiling_units, bool):
            raise VoiceRequestError("costCeilingUnits must be an integer")
        if self.cost_ceiling_units < 0:
            raise VoiceRequestError("costCeilingUnits cannot be negative")
        if self.cancellation_token and not valid_id(self.cancellation_token):
            raise VoiceRequestError("cancellationToken is not a usable identifier")

        object.__setattr__(self, "priority", Priority.parse(self.priority))
        object.__setattr__(
            self, "interruption_policy", InterruptionPolicy.parse(self.interruption_policy)
        )
        object.__setattr__(self, "text_digest", speech_digest(self.speech_text))

    # ----------------------------------------------------------------- #

    @property
    def byte_length(self) -> int:
        return len(self.speech_text.encode("utf-8"))

    def expired(self, monotonic_now: float) -> bool:
        """Whether this may no longer be spoken. Monotonic only, by construction."""
        return bool(self.expires_at_monotonic) and monotonic_now >= self.expires_at_monotonic

    def outranks(self, other: "VoiceRequest") -> bool:
        return self.priority.value < other.priority.value

    def may_interrupt(self, current: "VoiceRequest") -> bool:
        """Whether this request takes the floor from ``current``.

        Both conditions, not either: the policy must ask for it *and* the
        priority must earn it. A request that declared ``INTERRUPT`` and did not
        outrank what is speaking is queued, which is why a decorative line
        cannot cut off an approval prompt by setting a field.
        """
        return self.interruption_policy is InterruptionPolicy.INTERRUPT and self.outranks(current)

    def conflicts_with(self, other: "VoiceRequest") -> bool:
        """Same id, different utterance. §6's duplicate rule, as a predicate.

        Two requests with one id and one text are a retry and are idempotent.
        Two with one id and different text are a bug or an attack, and serving
        the second under the first's identity would mean the record of what was
        said no longer matches what was said.
        """
        return self.request_id == other.request_id and self.text_digest != other.text_digest

    def redacted(self) -> dict[str, Any]:
        """What a diagnostic log may hold: identity and shape, never the words.

        §15. The digest is here so two records can be compared, and the lengths
        are here so a "refused, too long" can be understood without the payload
        being quoted into a file that outlives the task.
        """
        return {
            "requestId": self.request_id,
            "sessionId": self.session_id,
            "taskId": self.task_id,
            "captionReference": self.caption_reference,
            "textDigest": self.text_digest,
            "textCharacters": len(self.speech_text),
            "textBytes": self.byte_length,
            "privacyClassification": self.privacy_classification,
            "priority": self.priority.wire,
            "voiceId": self.voice_id,
            "language": self.language,
        }

    def to_json(self, *, include_text: bool = True) -> dict[str, Any]:
        """The wire form.

        ``include_text=False`` is how this object crosses into anything that
        persists. The default is ``True`` because the worker genuinely needs the
        words; every caller that writes a record passes ``False`` and gets a
        document that is complete except for the one field that must not be in
        it.
        """
        document: dict[str, Any] = {
            "schemaVersion": self.schema_version,
            "requestId": self.request_id,
            "sessionId": self.session_id,
            "taskId": self.task_id,
            "captionReference": self.caption_reference,
            "presentationRevision": self.presentation_revision,
            "textDigest": self.text_digest,
            "textCharacters": len(self.speech_text),
            "textBytes": self.byte_length,
            "language": self.language,
            "locale": self.locale,
            "voiceId": self.voice_id,
            "speakingRate": self.speaking_rate,
            "pitch": self.pitch,
            "volume": self.volume,
            "audioFormat": self.audio_format,
            "sampleRate": self.sample_rate,
            "preferStreaming": self.prefer_streaming,
            "privacyClassification": self.privacy_classification,
            "localityRequirement": self.locality_requirement,
            "costCeilingUnits": self.cost_ceiling_units,
            "createdAtWall": self.created_at_wall,
            "createdAtMonotonic": self.created_at_monotonic,
            "expiresAtMonotonic": self.expires_at_monotonic,
            "cancellationToken": self.cancellation_token,
            "priority": self.priority.wire,
            "interruptionPolicy": self.interruption_policy.value,
        }
        if include_text:
            document["speechText"] = self.speech_text
        return document

    # ----------------------------------------------------------------- #

    @classmethod
    def from_json(cls, document: Mapping[str, Any]) -> "VoiceRequest":
        """Rebuild a request from the wire, refusing anything undeclared.

        Undeclared keys are rejected rather than ignored, for the reason
        :class:`companion.protocol.Operation` gives: an ignored parameter is a
        parameter a caller believes took effect, and the first time one of them
        means "and skip the privacy check" the silence becomes the vulnerability.
        """
        if not isinstance(document, Mapping):
            raise VoiceRequestError("a voice request must be a JSON object")
        known = set(_WIRE_FIELDS) | {"speechText", "textDigest", "textCharacters", "textBytes"}
        unknown = sorted(set(document) - known)
        if unknown:
            raise VoiceRequestError(f"a voice request does not accept: {', '.join(unknown)}")

        def take(key: str, default: Any) -> Any:
            value = document.get(key, default)
            return default if value is None and default is not None else value

        request = cls(
            request_id=str(document.get("requestId", "")),
            session_id=str(document.get("sessionId", "")),
            task_id=str(document.get("taskId", "")),
            caption_reference=str(document.get("captionReference", "")),
            speech_text=document.get("speechText", ""),
            presentation_revision=int(take("presentationRevision", 0)),
            language=str(take("language", "en")),
            locale=str(take("locale", "en-GB")),
            voice_id=str(take("voiceId", "")),
            speaking_rate=float(take("speakingRate", 1.0)),
            pitch=None if document.get("pitch") is None else float(document["pitch"]),
            volume=float(take("volume", 1.0)),
            audio_format=str(take("audioFormat", "wav-pcm-s16le")),
            sample_rate=int(take("sampleRate", 22_050)),
            prefer_streaming=bool(take("preferStreaming", False)),
            privacy_classification=str(take("privacyClassification", "internal")),
            locality_requirement=str(take("localityRequirement", "device-only")),
            cost_ceiling_units=int(take("costCeilingUnits", 0)),
            created_at_wall=float(take("createdAtWall", 0.0)),
            created_at_monotonic=float(take("createdAtMonotonic", 0.0)),
            expires_at_monotonic=float(take("expiresAtMonotonic", 0.0)),
            cancellation_token=str(take("cancellationToken", "")),
            priority=take("priority", Priority.PROGRESS_UPDATE),
            interruption_policy=take("interruptionPolicy", InterruptionPolicy.QUEUE),
            schema_version=int(take("schemaVersion", VOICE_REQUEST_SCHEMA_VERSION)),
        )
        supplied = document.get("textDigest")
        if isinstance(supplied, str) and supplied and supplied != request.text_digest:
            # The digest is derived, so a supplied one that disagrees means the
            # text was changed in transit or the sender computed it over
            # something else. Either way the record and the words have parted.
            raise VoiceRequestError(
                "the supplied textDigest does not match the speech text it accompanies"
            )
        return request


#: Kept beside :meth:`VoiceRequest.to_json` deliberately: the two are the same
#: list read in opposite directions, and a field added to one and not the other
#: is a field that survives a round trip in only one direction.
_WIRE_FIELDS = (
    "schemaVersion", "requestId", "sessionId", "taskId", "captionReference",
    "presentationRevision", "language", "locale", "voiceId", "speakingRate", "pitch",
    "volume", "audioFormat", "sampleRate", "preferStreaming", "privacyClassification",
    "localityRequirement", "costCeilingUnits", "createdAtWall", "createdAtMonotonic",
    "expiresAtMonotonic", "cancellationToken", "priority", "interruptionPolicy",
)


def sanitized_speech_text(caption: str, *, limit: int = MAX_SUMMARY_LENGTH) -> str:
    """A caption reduced to something a synthesiser may be handed.

    Three narrowings, and none of them changes what the sentence says:

    * :func:`companion.privacy.scrub_text` removes anything that reads as a
      credential, which a caption should never contain and which a spoken
      credential would broadcast to a room;
    * markup and control characters are collapsed to spaces, because a caption
      may carry Pango markup for the bubble and a synthesiser would read the
      angle brackets aloud;
    * the result is bounded at the caption's own summary limit.

    Bounded here and *refused* in :class:`VoiceRequest`. The difference is
    deliberate: this function's job is to derive an utterance from a caption the
    runtime already truncated for display, so the two agree; the request's job
    is to refuse a caller who bypassed this and handed over a megabyte.
    """
    body = scrub_text(str(caption))
    body = re.sub(r"<[^>]{0,200}>", " ", body)
    body = _CONTROL.sub(" ", body)
    body = " ".join(body.split())
    if len(body) > limit:
        # A display summary is already truncated and says so; matching it keeps
        # the spoken and the shown text the same sentence.
        body = body[: max(0, limit - 1)].rstrip() + "…"
    return body


def priority_for_phase(phase: str, *, approval_pending: bool = False) -> Priority:
    """The §7 rank a canonical presentation phase earns.

    A table rather than a heuristic. A voice runtime that guessed urgency from
    the wording of a caption would be forming its own opinion about the task,
    which is the one thing §1 forbids it. Every phase here is one the canonical
    projection produces; anything else is narration.
    """
    if approval_pending or phase == "waiting_for_approval":
        return Priority.APPROVAL_REQUIRED
    return _PHASE_PRIORITY.get(phase, Priority.PROGRESS_UPDATE)


_PHASE_PRIORITY: Mapping[str, Priority] = {
    "error": Priority.TASK_ERROR,
    "blocked": Priority.TASK_ERROR,
    "cancelled": Priority.PROGRESS_UPDATE,
    "success": Priority.TASK_RESULT,
    "presenting_result": Priority.TASK_RESULT,
    "speaking": Priority.DIRECT_USER_RESPONSE,
    "planning": Priority.PROGRESS_UPDATE,
    "working": Priority.PROGRESS_UPDATE,
    "reviewing": Priority.PROGRESS_UPDATE,
    "understanding": Priority.PROGRESS_UPDATE,
    "recovering": Priority.PROGRESS_UPDATE,
    "idle": Priority.DECORATIVE,
    "starting": Priority.DECORATIVE,
}


def may_speak_locally(classification: str) -> bool:
    """Whether a local synthesiser may be handed text of this classification.

    Every classification may, and the function exists to say so explicitly at
    the one place a future remote provider would have to change. A local
    synthesiser is a process on this machine with no network path, which is the
    same trust boundary the executor already runs inside; the question §15 cares
    about is *remote* transmission, and :func:`may_speak_remotely` is where the
    answer is no.
    """
    return classification in DATA_CLASSES


def may_speak_remotely(classification: str) -> bool:
    """Always ``False`` in this build, and the reason it is a function.

    A constant would be deleted by whoever adds the first remote provider. A
    function with this docstring is a place where the decision has to be
    argued: secret text may never leave the machine to be *read aloud*, and no
    remote provider exists here to leave for. §15, §16.
    """
    del classification  # every classification, for the same reason
    return False


def coalescing_key(request: VoiceRequest) -> tuple[str, str, int]:
    """What makes two utterances "the same progress update said twice".

    Task, content and rank. Deliberately not the request id — coalescing exists
    precisely because a runtime emits a fresh id for each repetition — and
    deliberately including the rank, so a progress line that is later reissued
    as an error is not swallowed by the earlier harmless one.
    """
    return (request.task_id, request.text_digest, request.priority.value)


def stricter_locality(left: str, right: str) -> str:
    order = ("device-only", "trusted-remote", "any")
    return min((left, right), key=order.index)


def classification_ceiling(left: str, right: str) -> str:
    """The higher of two classifications, by rank rather than by string."""
    return left if rank(left) >= rank(right) else right
