# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What a speech recogniser has to be, stated once so nothing has to guess.

The contract is provider-neutral in the strict sense: nothing in it names a
model file, a framework, or a capability only one implementation has. A
recogniser *declares* what it can do (:class:`RecognizerDeclaration`), *reports*
whether it can do it right now (:class:`RecognizerHealth`), and *does* it
through a :class:`RecognitionSession` the worker feeds frames to. Everything
above this module reads declarations and health, never the recogniser's
identity.

**An unavailable recogniser reports unavailable.** It does not raise on
construction, and it does not return an empty transcript that looks like a
person who said nothing — the position
:class:`companion.voice.system.AbsentSpeechRecognition` staked out before any
recogniser existed, kept now that real ones do. A registry with nothing ready
selects nothing, the policy layer degrades to typed input, and the reason
travels the whole way to the surface.

**Local is a gate, not a description.** :meth:`RecognizerDeclaration.serves`
refuses a declaration whose ``local`` is ``False``, because §9 forbids remote
commercial recognition and §10 forbids local incapability from authorising it.
There is no remote adapter in this build, no placeholder shaped like one, and
the refusal is in the contract so that a future one cannot be reached by
registering it.

**Sessions are owned.** A :class:`RecognitionSession` is created by the worker,
fed by the worker, finished or cancelled by the worker, and closed in the
worker's ``finally``. §23 counts recogniser instances across a hundred runs;
a session that outlives its capture is the leak that count exists to catch.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Protocol, Sequence, runtime_checkable

from ..privacy import rank
from .request import SpeechInputRequest
from .transcript import FinalTranscript, PartialTranscript

__all__ = [
    "RecognitionSession",
    "RecognizerDeclaration",
    "RecognizerHealth",
    "RecognizerRegistry",
    "RecognizerResourceEstimate",
    "RecognizerSelection",
    "SpeechRecognizer",
]


@dataclass(frozen=True)
class RecognizerDeclaration:
    """Everything a recogniser promises, checked before it is handed audio.

    Undeclared is unavailable, exactly as
    :class:`companion.voice.provider.ProviderDeclaration` has it: a recogniser
    whose declaration does not cover a request is not tried and then failed —
    it is not selected, and the reason is carried so "why is it not listening
    to me in French" has an answer.
    """

    provider_id: str
    #: Which build of the recogniser this is — a library version and a model
    #: revision. Recorded on every transcript so a measurement or a complaint
    #: can be attributed to the thing that produced it.
    implementation_id: str = ""
    #: ``True`` for a recogniser that runs entirely on this machine. There is
    #: no ``False`` recogniser in this build and :meth:`serves` refuses one, so
    #: the field is a gate rather than a description.
    local: bool = True
    languages: tuple[str, ...] = ()
    locales: tuple[str, ...] = ()
    #: Whether frames may be submitted as they arrive. A batch-only recogniser
    #: is fed the same frames and produces no partials.
    supports_streaming: bool = False
    supports_partial_transcripts: bool = False
    provides_word_timestamps: bool = False
    provides_confidence: bool = False
    supports_cancellation: bool = True
    audio_formats: tuple[str, ...] = ("raw-pcm-s16le",)
    sample_rates: tuple[int, ...] = ()
    #: What one recognition is expected to cost, before it is started. §10
    #: reads the model memory requirement from here.
    resource_estimate: "RecognizerResourceEstimate | None" = None
    #: The highest privacy classification this recogniser may be handed. A
    #: local model may hold anything the executor may.
    maximum_privacy_class: str = "secret"
    cost_class: str = "free"
    requires_authentication: bool = False
    #: Where the model was found — an installed path, a user cache — carried
    #: for the report, never writable through any protocol operation.
    model_origin: str = ""

    @property
    def fully_declared(self) -> bool:
        """Whether this declaration is complete enough to be trusted.

        Fails closed: a recogniser that did not say what it does cannot be
        checked against what it is asked for.
        """
        return bool(
            self.provider_id
            and self.implementation_id
            and self.languages
            and self.sample_rates
            and self.cost_class in ("free", "metered", "paid")
        )

    def handles_language(self, language: str, locale: str = "") -> bool:
        """The language is the requirement; the locale is a preference.

        Deliberately looser than the voice provider's rule, because the
        directions differ: a synthesiser with no en-GB voice would *speak* the
        wrong accent, which the user hears every time, while a recogniser
        trained on en-US still transcribes British English — less accurately,
        which §13's confirmation step exists to catch. Refusing an en model
        over the region would cost the user the entire capture (measured: the
        installed slice's first Linux run refused every capture because the
        only installed model declared ``en-US`` against a default preference
        of ``en-GB``) to satisfy an accent. When more than one recogniser is
        installed, selection order still prefers the earlier registration; a
        locale-aware preference between eligible models is future work, noted
        in the report.
        """
        del locale
        return language in self.languages

    def serves(self, request: SpeechInputRequest) -> tuple[bool, tuple[str, ...]]:
        """Whether this recogniser may take this capture, and every reason not.

        All the reasons, not the first — the same answer-shape every
        eligibility check in the companion gives, because a user told "it
        cannot transcribe this" deserves the whole answer.
        """
        reasons: list[str] = []
        if not self.fully_declared:
            reasons.append(
                f"{self.provider_id!r} has not fully declared itself; an undeclared "
                "recogniser fails closed"
            )
        if not self.local:
            # The one refusal that is policy rather than capability. §9: no
            # remote commercial recognition; §10: local incapability does not
            # authorise it. The contract refuses so nobody has to remember to.
            reasons.append(
                f"{self.provider_id!r} is not local; this build has no remote recognition "
                "path and captured audio does not leave the machine"
            )
        if not self.handles_language(request.language, request.locale):
            reasons.append(
                f"{self.provider_id!r} has no model for {request.locale or request.language!r}"
            )
        if request.audio_format not in self.audio_formats:
            reasons.append(f"{self.provider_id!r} does not accept {request.audio_format}")
        if request.sample_rate not in self.sample_rates:
            reasons.append(
                f"{self.provider_id!r} does not accept audio at {request.sample_rate} Hz"
            )
        if rank(request.privacy_classification) > rank(self.maximum_privacy_class):
            reasons.append(
                f"the capture is classified {request.privacy_classification} and "
                f"{self.provider_id!r} may hold data up to {self.maximum_privacy_class}"
            )
        if self.cost_class != "free":
            reasons.append(
                f"{self.provider_id!r} bills for use and speech input permits no spend"
            )
        if self.requires_authentication:
            reasons.append(
                f"{self.provider_id!r} requires authentication and none is configured"
            )
        return (not reasons), tuple(reasons)

    def to_json(self) -> dict[str, Any]:
        return {
            "providerId": self.provider_id,
            "implementationId": self.implementation_id,
            "local": self.local,
            "languages": list(self.languages),
            "locales": list(self.locales),
            "supportsStreaming": self.supports_streaming,
            "supportsPartialTranscripts": self.supports_partial_transcripts,
            "providesWordTimestamps": self.provides_word_timestamps,
            "providesConfidence": self.provides_confidence,
            "supportsCancellation": self.supports_cancellation,
            "audioFormats": list(self.audio_formats),
            "sampleRates": list(self.sample_rates),
            "resourceEstimate": (
                self.resource_estimate.to_json() if self.resource_estimate else None
            ),
            "maximumPrivacyClass": self.maximum_privacy_class,
            "costClass": self.cost_class,
            "requiresAuthentication": self.requires_authentication,
            "modelOrigin": self.model_origin,
            "fullyDeclared": self.fully_declared,
            "remoteTransmission": not self.local,
            "speakerIdentification": False,
            "voiceBiometrics": False,
        }


@dataclass(frozen=True)
class RecognizerResourceEstimate:
    """What one recognition is expected to cost. Estimates, named as such."""

    model_memory_bytes: int = 0
    working_memory_bytes: int = 0
    cpu_share: float = 0.0
    expected_first_partial_seconds: float = 0.0

    def to_json(self) -> dict[str, Any]:
        return {
            "modelMemoryBytes": self.model_memory_bytes,
            "workingMemoryBytes": self.working_memory_bytes,
            "cpuShare": self.cpu_share,
            "expectedFirstPartialSeconds": self.expected_first_partial_seconds,
        }


@dataclass(frozen=True)
class RecognizerHealth:
    """Whether a recogniser can be used *now*, and why not when it cannot."""

    provider_id: str
    available: bool = False
    healthy: bool = True
    detail: str = ""
    status_code: str = ""
    checked_at_monotonic: float = 0.0
    consecutive_failures: int = 0

    @property
    def ready(self) -> bool:
        return self.available and self.healthy

    def to_json(self) -> dict[str, Any]:
        return {
            "providerId": self.provider_id,
            "available": self.available,
            "healthy": self.healthy,
            "ready": self.ready,
            "detail": self.detail,
            "statusCode": self.status_code,
            "checkedAtMonotonic": self.checked_at_monotonic,
            "consecutiveFailures": self.consecutive_failures,
        }


@runtime_checkable
class RecognitionSession(Protocol):
    """One recognition in flight. Created, fed, finished and closed by one owner."""

    def accept(self, frames: bytes, *, position_seconds: float = 0.0) -> PartialTranscript | None:
        """Take captured frames; return a new partial when there is one.

        A batch recogniser buffers and returns ``None`` every time. A streaming
        one returns a partial only when the reading *changed* — the worker does
        not deduplicate, because only the recogniser knows what changed.
        """

    def finish(self) -> FinalTranscript:
        """The complete answer for everything accepted. Ends the session."""

    def cancel(self) -> None:
        """Abandon the recognition. Nothing may be returned after this."""

    def close(self) -> None:
        """Release everything. Safe to call twice and after a fault."""


@runtime_checkable
class SpeechRecognizer(Protocol):
    """The whole of what the worker may ask of a recogniser."""

    @property
    def declaration(self) -> RecognizerDeclaration: ...

    def health(self, *, monotonic: float = 0.0, refresh: bool = False) -> RecognizerHealth:
        """Never raises; unavailability is a return value."""

    def start(self, request: SpeechInputRequest) -> RecognitionSession:
        """Begin one recognition. The caller owns the session's lifecycle."""

    def close(self) -> None:
        """Release the model and everything else. Safe to call twice."""


@dataclass(frozen=True)
class RecognizerSelection:
    """Which recogniser will listen, and the whole reason every other will not."""

    recognizer: SpeechRecognizer | None
    rejected: tuple[tuple[str, tuple[str, ...]], ...] = ()
    detail: str = ""

    @property
    def selected(self) -> bool:
        return self.recognizer is not None

    def to_json(self) -> dict[str, Any]:
        return {
            "selected": self.selected,
            "providerId": (
                self.recognizer.declaration.provider_id if self.recognizer else ""
            ),
            "rejected": [
                {"providerId": name, "reasons": list(reasons)}
                for name, reasons in self.rejected
            ],
            "detail": self.detail,
        }


class RecognizerRegistry:
    """The recognisers this runtime knows, in preference order.

    Order is the caller's, exactly as the voice provider registry's is: the
    preference lives in one readable tuple in
    :func:`companion.speech.recognizers.local_recognizers`, and selection walks
    down it deterministically.
    """

    def __init__(self, recognizers: Iterable[SpeechRecognizer] = ()) -> None:
        self._recognizers: list[SpeechRecognizer] = list(recognizers)

    def __len__(self) -> int:
        return len(self._recognizers)

    def __iter__(self):
        return iter(self._recognizers)

    def add(self, recognizer: SpeechRecognizer) -> None:
        self._recognizers.append(recognizer)

    def get(self, provider_id: str) -> SpeechRecognizer | None:
        for recognizer in self._recognizers:
            if recognizer.declaration.provider_id == provider_id:
                return recognizer
        return None

    def declarations(self) -> list[dict[str, Any]]:
        return [item.declaration.to_json() for item in self._recognizers]

    def health(self, *, monotonic: float = 0.0, refresh: bool = False) -> list[RecognizerHealth]:
        return [
            item.health(monotonic=monotonic, refresh=refresh) for item in self._recognizers
        ]

    def select(
        self,
        request: SpeechInputRequest,
        *,
        monotonic: float = 0.0,
        exclude: Iterable[str] = (),
        require_streaming: bool = False,
    ) -> RecognizerSelection:
        """The first recogniser in order that may and can serve this capture.

        A named preference is honoured when that recogniser is eligible and
        *refused with the reason* when it is not — never silently substituted,
        because a user who chose a recogniser and got a different one has had
        their audio handed to something they did not pick.
        """
        skipped = set(exclude)
        rejected: list[tuple[str, tuple[str, ...]]] = []
        preferred = request.provider_preference

        candidates = list(self._recognizers)
        if preferred:
            named = self.get(preferred)
            if named is None:
                return RecognizerSelection(
                    recognizer=None,
                    rejected=((preferred, ("no recogniser with this identifier is registered",)),),
                    detail=(
                        f"the requested recogniser {preferred!r} is not installed; "
                        "typed input remains available"
                    ),
                )
            candidates = [named]

        for recognizer in candidates:
            declaration = recognizer.declaration
            name = declaration.provider_id
            if name in skipped:
                rejected.append((name, ("excluded after an earlier failure on this capture",)))
                continue
            permitted, reasons = declaration.serves(request)
            problems = list(reasons)
            if require_streaming and not declaration.supports_streaming:
                problems.append(f"{name!r} cannot stream and streaming was required")
            if permitted and not problems:
                health = recognizer.health(monotonic=monotonic)
                if not health.ready:
                    problems.append(
                        f"{name!r} is not ready" + (f": {health.detail}" if health.detail else "")
                    )
            if problems:
                rejected.append((name, tuple(problems)))
                continue
            return RecognizerSelection(
                recognizer=recognizer,
                rejected=tuple(rejected),
                detail=f"{name} selected",
            )
        return RecognizerSelection(
            recognizer=None,
            rejected=tuple(rejected),
            detail=(
                "no eligible local recogniser; capture may proceed only where policy "
                "permits, and typed input remains available"
            ),
        )

    def close(self) -> None:
        for recognizer in self._recognizers:
            try:
                recognizer.close()
            except Exception:  # noqa: BLE001 - closing must not stop at the first failure
                continue
