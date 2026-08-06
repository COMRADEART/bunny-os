# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What the speech-input runtime may be asked, and what it may never be told.

A :class:`SpeechInputRequest` is the whole of the capture worker's input.
Everything downstream — the activation gate, the capture backend, the activity
detector, the recogniser — reads this object and nothing else about the world.
The absent fields are the specification: there is no field for an executable, a
model path, a recording destination, a wake word, or a remote endpoint, and
adding one would need a new field and a new line in
:meth:`SpeechInputRequest.to_json`, which is exactly the review this boundary
exists to force.

Three properties are load-bearing and each is enforced at construction rather
than at use:

**The activation source is a closed set of explicit interactions.** §3 limits
activation to a push-to-talk button, a keyboard shortcut, an explicit protocol
request and an accessibility control. There is no ``wake-word`` member, no
``service-startup`` member and no ``timer`` member, and a request naming one is
refused at construction — which is what makes §22's silent-activation test an
assertion about a type rather than about the discipline of every caller.

**Every capture bound is a ceiling the request cannot raise.** Maximum duration,
byte count, silence timeouts, sample rate, channel count: each is validated
against a module constant, and a request over any of them is *refused* — never
clamped. A clamped bound is a caller that believes it asked for ten minutes and
got thirty seconds, and the difference between those is a truncated sentence the
user does not know was truncated.

**Expiry is monotonic.** ``expires_at_monotonic`` is compared against
:meth:`companion.clock.Clock.monotonic` and never wall time, for the reason
every other deadline in the companion is: an activation whose validity could be
extended by changing the timezone is an activation that can be replayed. A
request whose deadline cannot be evaluated after a restart is expired, which is
the safe direction for a microphone even more than for speech output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Mapping

from capability.apply.identity import digest

from ..ids import valid_id
from ..privacy import DATA_CLASSES

__all__ = [
    "ACTIVATION_SOURCES",
    "CAPTURE_FORMATS",
    "CHANNEL_BOUNDS",
    "MAX_CAPTURE_BYTES",
    "MAX_CAPTURE_SECONDS",
    "MAX_TRANSCRIPT_BYTES",
    "MAX_TRANSCRIPT_CHARACTERS",
    "SAMPLE_RATES",
    "SPEECH_INPUT_REQUEST_SCHEMA_VERSION",
    "SpeechInputRequest",
    "SpeechInputRequestError",
    "transcript_digest",
]

#: Bumped when a field is added, removed or reinterpreted. A worker that reads a
#: version it does not know refuses the request rather than guessing which
#: fields it can still trust.
SPEECH_INPUT_REQUEST_SCHEMA_VERSION = 1

#: §3's allowed activation sources, and deliberately nothing passive. Each names
#: an act a person performed *now*: a button held, a key chord pressed, a
#: protocol call a surface made on the user's explicit behalf, an assistive
#: switch. ``wake-word``, ``always-listening`` and ``scheduled`` are not here and
#: may not be added in this phase — §26.9 is the completion criterion that this
#: tuple is the enforcement of.
ACTIVATION_SOURCES = (
    "push-to-talk-button",
    "keyboard-shortcut",
    "explicit-protocol-request",
    "accessibility-control",
)

#: The one sample format capture accepts: signed 16-bit little-endian PCM, raw.
#: One format on purpose. Every capture program in the allowlist can produce it,
#: every recogniser adapter consumes it, and a second format would be a decoder
#: parsing microphone bytes in the companion's own address space.
CAPTURE_FORMATS = ("raw-pcm-s16le",)

#: Rates a request may ask the microphone for. 16 kHz first because it is what
#: local recognisers are trained on; the rest are what real capture servers
#: natively run at. Nothing here resamples — a backend that cannot capture the
#: requested rate says so, and the policy layer degrades rather than compensates.
SAMPLE_RATES = (16_000, 22_050, 44_100, 48_000)

#: How many channels a capture may open. One is the correct answer for speech;
#: two is permitted because some devices only present stereo. More than two is a
#: soundcard being enumerated, not a person being listened to.
CHANNEL_BOUNDS = (1, 2)

#: The longest any single capture may run, whatever the request says. §7's
#: maximum-duration bound at its widest: five minutes of held push-to-talk is a
#: stuck key, not an utterance.
MAX_CAPTURE_SECONDS = 300.0

#: The most captured audio one request may buffer or write, in bytes. Sized for
#: the ceiling: 300 s × 48 kHz × 2 ch × 2 bytes ≈ 55 MiB, rounded up. A capture
#: that reaches it is stopped and the recogniser is given what exists.
MAX_CAPTURE_BYTES = 64 * 1024 * 1024

#: The longest transcript this runtime will hold or hand onward, in characters.
#: 4000, matching :data:`companion.voice.request.MAX_SPEECH_CHARACTERS` — the
#: two directions of speech carry the same bound — and deliberately *under*
#: two ceilings it must fit inside: :data:`companion.privacy.MAX_STRING_LENGTH`
#: (4096), because a final transcript travels in a sanitized event payload and
#: a transcript the event layer would refuse is a transcript that reaches the
#: user nowhere; and :data:`companion.privacy.MAX_REQUEST_LENGTH` (8192),
#: because a confirmed transcript becomes a task request. Four thousand
#: characters is several minutes of continuous dictation; past it, the honest
#: answer is typed input.
MAX_TRANSCRIPT_CHARACTERS = 4000

#: The byte bound on the UTF-8 encoding, three times the character bound for the
#: reason :data:`companion.voice.request.MAX_SPEECH_BYTES` is: at four times the
#: check could never fire and would be decoration.
MAX_TRANSCRIPT_BYTES = 3 * MAX_TRANSCRIPT_CHARACTERS

#: Bounds on the silence timeouts, in seconds. The floor stops a request from
#: making silence detection a busy loop; the ceiling stops one from disabling it
#: — §15 requires that capture cannot run indefinitely when nobody speaks.
SILENCE_TIMEOUT_BOUNDS = (0.2, 30.0)

#: BCP-47-ish, bounded and restricted, exactly as the voice runtime's. These end
#: up in file names and recogniser configuration; the useful property is
#: "contains nothing that changes meaning at a boundary".
_LANGUAGE = re.compile(r"^[a-z]{2,3}\Z")
_LOCALE = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8}){0,2}\Z")

#: What a capture device identifier may look like. Wider than
#: :data:`companion.ids.ID_PATTERN` because real device names carry colons and
#: commas — ``hw:0,0``, ``alsa_input.pci-0000_00_1f.3.analog-stereo`` — and
#: narrower than free text because a device name reaches an argv. No spaces, no
#: separators that mean anything to a shell this runtime never invokes anyway,
#: no leading dash that an option parser could eat.
_DEVICE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:,+-]{0,127}\Z")

#: A recogniser identifier is the provider's registry name and follows the same
#: shape every other identifier does.
_PROVIDER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}\Z")


class SpeechInputRequestError(ValueError):
    """A request that may not be served, with the reason a person needs.

    A ``ValueError`` rather than a :class:`companion.errors.CompanionError` for
    the same reason :class:`companion.voice.request.VoiceRequestError` is: this
    is a malformed *input*, a client's bug rather than a runtime fault, and the
    protocol boundary reports the two differently.
    """


def transcript_digest(text: str) -> str:
    """The identity of a transcript's *content*, independent of its request.

    Used to bind a confirmation to the exact words the user reviewed (§13), to
    detect a stale transcript replayed against a newer capture (§22), and to
    write diagnostic records that identify a transcript without quoting it.
    """
    return digest({"transcriptText": text})


def _identifier(name: str, value: Any, *, required: bool = True) -> str:
    if value in (None, "") and not required:
        return ""
    if not isinstance(value, str) or not valid_id(value):
        raise SpeechInputRequestError(f"{name} is not a usable identifier")
    return value


def _bounded_seconds(name: str, value: Any, *, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SpeechInputRequestError(f"{name} must be a number of seconds")
    number = float(value)
    if not low <= number <= high:
        raise SpeechInputRequestError(
            f"{name} is {number}s and must be between {low}s and {high}s; "
            "it was refused rather than clamped"
        )
    return number


@dataclass(frozen=True)
class SpeechInputRequest:
    """One bounded act of listening, with every constraint on performing it.

    Frozen, so a request cannot be edited after the activation gate has
    examined it. A worker that needs a changed field builds a new request,
    which gets a new id, a new explicit activation and a fresh trip through
    validation — §21's "a new capture needs a new user action", enforced by
    immutability rather than by discipline.
    """

    request_id: str
    session_id: str
    #: Which explicit interaction produced this request. Validated against
    #: :data:`ACTIVATION_SOURCES`; there is no default, because a default
    #: activation source would be an activation nobody performed.
    activation_source: str
    created_at_wall: float = 0.0
    created_at_monotonic: float = 0.0
    #: Monotonic deadline for *starting* the capture. An activation is a moment,
    #: not a standing permission; a start that cannot happen promptly should not
    #: happen at all. Zero means "no expiry" and is only correct in a test.
    expires_at_monotonic: float = 0.0
    language: str = "en"
    locale: str = "en-GB"
    #: A preference, not a command. The registry may select another provider
    #: when the named one is unavailable — and refuses rather than substitutes
    #: when the name is unknown, exactly as voice selection refuses an
    #: uninstalled voice.
    provider_preference: str = ""
    #: The capture device the user chose, or "" for the backend's default.
    device_preference: str = ""
    maximum_capture_seconds: float = 30.0
    #: How long the microphone stays open with no speech at all before the
    #: capture ends on its own. §15's initial-silence rule.
    initial_silence_seconds: float = 6.0
    #: How much trailing silence ends an utterance that did contain speech.
    endpoint_silence_seconds: float = 1.2
    #: Whether the client wants provisional transcripts as recognition runs.
    #: A preference: policy may suppress them under pressure (§12) without
    #: invalidating final recognition.
    partial_transcripts: bool = True
    #: Whether the final transcript must be confirmed by the user before it may
    #: become a task. ``True`` by default and turning it off requires the user
    #: preference *and* the per-request flag — §13's two-key arrangement.
    confirmation_required: bool = True
    privacy_classification: str = "personal"
    #: The strictest locality this capture may be served under. ``device-only``
    #: is the only value this build can honour; the field exists so a future
    #: remote recogniser cannot be reached by omission.
    locality_requirement: str = "device-only"
    audio_format: str = "raw-pcm-s16le"
    sample_rate: int = 16_000
    channels: int = 1
    #: An opaque token a canceller or confirmer must present. Not a secret — a
    #: local client already holds the request id — but a binding that stops a
    #: late cancel or a replayed confirmation from acting on the request that
    #: reused the id.
    cancellation_token: str = ""
    #: The presentation revision the client was showing when the user activated.
    #: Carried into every event so a surface can tell an event belongs to the
    #: state it is looking at.
    presentation_revision: int = 0
    schema_version: int = SPEECH_INPUT_REQUEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_id", _identifier("requestId", self.request_id))
        object.__setattr__(self, "session_id", _identifier("sessionId", self.session_id))

        if self.schema_version != SPEECH_INPUT_REQUEST_SCHEMA_VERSION:
            raise SpeechInputRequestError(
                f"this runtime serves speech-input request schema "
                f"{SPEECH_INPUT_REQUEST_SCHEMA_VERSION} and the request declared "
                f"{self.schema_version!r}; there is no downgrade path"
            )
        if self.activation_source not in ACTIVATION_SOURCES:
            raise SpeechInputRequestError(
                f"activation source {self.activation_source!r} is not an explicit user "
                f"interaction this runtime accepts; the microphone is turned on by a person "
                f"performing one of: {', '.join(ACTIVATION_SOURCES)}"
            )
        if not _LANGUAGE.match(self.language or ""):
            raise SpeechInputRequestError(f"unsupported language tag: {self.language!r}")
        if not _LOCALE.match(self.locale or ""):
            raise SpeechInputRequestError(f"unsupported locale tag: {self.locale!r}")
        if not self.locale.lower().startswith(self.language.lower()):
            raise SpeechInputRequestError(
                f"locale {self.locale!r} does not belong to language {self.language!r}"
            )
        if self.provider_preference and not _PROVIDER_ID.match(self.provider_preference):
            raise SpeechInputRequestError(
                f"providerPreference is not a usable provider identifier: "
                f"{self.provider_preference!r}"
            )
        if self.device_preference and not _DEVICE_ID.match(self.device_preference):
            # The refusal §22's device-name-injection test asserts. A device
            # name with a space, a slash or a leading dash is not a device this
            # runtime discovered; it is an argv waiting to be misparsed.
            raise SpeechInputRequestError(
                f"devicePreference is not a usable capture device identifier: "
                f"{self.device_preference!r}"
            )
        object.__setattr__(
            self,
            "maximum_capture_seconds",
            _bounded_seconds(
                "maximumCaptureSeconds", self.maximum_capture_seconds,
                low=1.0, high=MAX_CAPTURE_SECONDS,
            ),
        )
        object.__setattr__(
            self,
            "initial_silence_seconds",
            _bounded_seconds(
                "initialSilenceSeconds", self.initial_silence_seconds,
                low=SILENCE_TIMEOUT_BOUNDS[0], high=SILENCE_TIMEOUT_BOUNDS[1],
            ),
        )
        object.__setattr__(
            self,
            "endpoint_silence_seconds",
            _bounded_seconds(
                "endpointSilenceSeconds", self.endpoint_silence_seconds,
                low=SILENCE_TIMEOUT_BOUNDS[0], high=SILENCE_TIMEOUT_BOUNDS[1],
            ),
        )
        if self.privacy_classification not in DATA_CLASSES:
            raise SpeechInputRequestError(
                f"unknown privacy classification: {self.privacy_classification!r}"
            )
        if self.locality_requirement != "device-only":
            # Stricter than the voice runtime, which admits the *names* of wider
            # localities. Captured audio is the user's voice; §1 forbids sending
            # it anywhere, and the way to forbid it structurally is for the type
            # to refuse the name of the path that would.
            raise SpeechInputRequestError(
                f"locality requirement {self.locality_requirement!r} was refused; "
                "captured audio is served on this device only, and local incapability "
                "does not authorise a remote recogniser"
            )
        if self.audio_format not in CAPTURE_FORMATS:
            raise SpeechInputRequestError(
                f"unsupported capture format {self.audio_format!r}; this runtime captures "
                f"{', '.join(CAPTURE_FORMATS)}"
            )
        if self.sample_rate not in SAMPLE_RATES:
            raise SpeechInputRequestError(
                f"unsupported sample rate {self.sample_rate!r}; this runtime captures at "
                f"{', '.join(str(item) for item in SAMPLE_RATES)}"
            )
        if self.channels not in CHANNEL_BOUNDS:
            raise SpeechInputRequestError(
                f"unsupported channel count {self.channels!r}; this runtime captures "
                f"{' or '.join(str(item) for item in CHANNEL_BOUNDS)} channel(s)"
            )
        if self.cancellation_token and not valid_id(self.cancellation_token):
            raise SpeechInputRequestError("cancellationToken is not a usable identifier")
        if not isinstance(self.presentation_revision, int) or isinstance(self.presentation_revision, bool):
            raise SpeechInputRequestError("presentationRevision must be an integer")
        if self.presentation_revision < 0:
            raise SpeechInputRequestError("presentationRevision cannot be negative")
        if not isinstance(self.partial_transcripts, bool):
            raise SpeechInputRequestError("partialTranscripts must be true or false")
        if not isinstance(self.confirmation_required, bool):
            raise SpeechInputRequestError("confirmationRequired must be true or false")

    # ----------------------------------------------------------------- #

    @property
    def bytes_per_second(self) -> int:
        return self.sample_rate * self.channels * 2

    @property
    def maximum_capture_bytes(self) -> int:
        """The byte ceiling for this capture: its own duration at its own rate.

        Bounded twice — by the request's duration and by the module ceiling —
        so a request cannot buy more memory by asking for a higher rate.
        """
        return min(
            MAX_CAPTURE_BYTES,
            int(self.maximum_capture_seconds * self.bytes_per_second) + self.bytes_per_second,
        )

    def expired(self, monotonic_now: float) -> bool:
        """Whether this activation may no longer open a microphone."""
        return bool(self.expires_at_monotonic) and monotonic_now >= self.expires_at_monotonic

    def to_json(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "requestId": self.request_id,
            "sessionId": self.session_id,
            "activationSource": self.activation_source,
            "createdAtWall": self.created_at_wall,
            "createdAtMonotonic": self.created_at_monotonic,
            "expiresAtMonotonic": self.expires_at_monotonic,
            "language": self.language,
            "locale": self.locale,
            "providerPreference": self.provider_preference,
            "devicePreference": self.device_preference,
            "maximumCaptureSeconds": self.maximum_capture_seconds,
            "initialSilenceSeconds": self.initial_silence_seconds,
            "endpointSilenceSeconds": self.endpoint_silence_seconds,
            "partialTranscripts": self.partial_transcripts,
            "confirmationRequired": self.confirmation_required,
            "privacyClassification": self.privacy_classification,
            "localityRequirement": self.locality_requirement,
            "audioFormat": self.audio_format,
            "sampleRate": self.sample_rate,
            "channels": self.channels,
            "cancellationToken": self.cancellation_token,
            "presentationRevision": self.presentation_revision,
        }

    # ----------------------------------------------------------------- #

    @classmethod
    def from_json(cls, document: Mapping[str, Any]) -> "SpeechInputRequest":
        """Rebuild a request from the wire, refusing anything undeclared.

        Undeclared keys are rejected rather than ignored, for the reason
        :class:`companion.protocol.Operation` gives: an ignored parameter is a
        parameter a caller believes took effect, and the first time one of them
        means "and skip the confirmation" the silence becomes the vulnerability.
        """
        if not isinstance(document, Mapping):
            raise SpeechInputRequestError("a speech-input request must be a JSON object")
        unknown = sorted(set(document) - set(_WIRE_FIELDS))
        if unknown:
            raise SpeechInputRequestError(
                f"a speech-input request does not accept: {', '.join(unknown)}"
            )

        def take(key: str, default: Any) -> Any:
            value = document.get(key, default)
            return default if value is None and default is not None else value

        return cls(
            request_id=str(document.get("requestId", "")),
            session_id=str(document.get("sessionId", "")),
            activation_source=str(document.get("activationSource", "")),
            created_at_wall=float(take("createdAtWall", 0.0)),
            created_at_monotonic=float(take("createdAtMonotonic", 0.0)),
            expires_at_monotonic=float(take("expiresAtMonotonic", 0.0)),
            language=str(take("language", "en")),
            locale=str(take("locale", "en-GB")),
            provider_preference=str(take("providerPreference", "")),
            device_preference=str(take("devicePreference", "")),
            maximum_capture_seconds=take("maximumCaptureSeconds", 30.0),
            initial_silence_seconds=take("initialSilenceSeconds", 6.0),
            endpoint_silence_seconds=take("endpointSilenceSeconds", 1.2),
            partial_transcripts=bool(take("partialTranscripts", True)),
            confirmation_required=bool(take("confirmationRequired", True)),
            privacy_classification=str(take("privacyClassification", "personal")),
            locality_requirement=str(take("localityRequirement", "device-only")),
            audio_format=str(take("audioFormat", "raw-pcm-s16le")),
            sample_rate=int(take("sampleRate", 16_000)),
            channels=int(take("channels", 1)),
            cancellation_token=str(take("cancellationToken", "")),
            presentation_revision=int(take("presentationRevision", 0)),
            schema_version=int(take("schemaVersion", SPEECH_INPUT_REQUEST_SCHEMA_VERSION)),
        )


#: Kept beside :meth:`SpeechInputRequest.to_json` deliberately: the two are the
#: same list read in opposite directions, and a field added to one and not the
#: other survives a round trip in only one direction.
_WIRE_FIELDS = (
    "schemaVersion", "requestId", "sessionId", "activationSource",
    "createdAtWall", "createdAtMonotonic", "expiresAtMonotonic",
    "language", "locale", "providerPreference", "devicePreference",
    "maximumCaptureSeconds", "initialSilenceSeconds", "endpointSilenceSeconds",
    "partialTranscripts", "confirmationRequired", "privacyClassification",
    "localityRequirement", "audioFormat", "sampleRate", "channels",
    "cancellationToken", "presentationRevision",
)
