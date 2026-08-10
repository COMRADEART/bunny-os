# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What a speech provider has to be, stated once so nothing has to guess.

The contract here is provider-neutral in the strict sense: nothing in it names a
program, a format a particular synthesiser happens to emit, or a capability only
one implementation has. A provider *declares* what it can do
(:class:`ProviderDeclaration`), *reports* whether it can do it right now
(:class:`ProviderHealth`), and *does* it (:meth:`VoiceProvider.synthesize` and
:meth:`VoiceProvider.stream`). Everything above this module — the worker, the
queue, the degradation ladder — reads declarations and health, never the
provider's identity.

**An unavailable provider reports unavailable.** It does not raise on
construction, it does not return silence that looks like speech, and it does not
succeed with no audio. This matters more than it sounds: a provider that
"succeeded" with an empty result would make :mod:`companion.voice.worker` record
an utterance as *played*, which would make §20's recovery believe there is
nothing to reconcile, which would make a user who heard nothing unable to tell
the difference between a broken synthesiser and a silent one. So health is a
first-class return value and every caller branches on it.

**Two ways to produce speech, and the difference is load-bearing.**

:meth:`VoiceProvider.synthesize`
    Produces an audio artifact in a private workspace. The worker then plays it
    through :mod:`companion.voice.audio`. This is the path that supports
    amplitude-derived visemes, measured caption-to-audio offsets, pause and
    resume, and a device change between synthesis and playback — because *we*
    hold the audio.

:meth:`VoiceProvider.stream`
    Hands the utterance to a provider that owns its own playback, and gets back
    only "it finished" or "it did not". Speech Dispatcher works this way by
    design: it is a *server* with its own queue and its own audio connection,
    and a client that also wanted the samples would be fighting it. The cost is
    real and is recorded rather than hidden — visemes fall back to text-derived
    timing and pause/resume is not available — and §12's ladder has
    "non-streaming local voice" as a rung precisely so this trade-off is a
    policy decision rather than an accident.

Both are optional. A provider declares which it has, and
:meth:`ProviderDeclaration.serves` refuses a request the provider could not
honour rather than letting the worker discover it at the subprocess.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence, runtime_checkable

from ..privacy import rank
from .execution import CancellationSignal, CommandOutcome, PrivateWorkspace
from .request import VoiceRequest

__all__ = [
    "ProviderDeclaration",
    "ProviderHealth",
    "ProviderRegistry",
    "ResourceEstimate",
    "SelectionResult",
    "StreamOutcome",
    "SynthesisResult",
    "VoiceDescriptor",
    "VoiceProvider",
]


@dataclass(frozen=True)
class VoiceDescriptor:
    """One voice a provider has installed.

    Note what is *not* here: no sample, no embedding, no model reference, no
    path to a recording. §16 forbids a voice that came from anywhere but the
    provider's own installation, and the way to forbid it structurally is for
    the type that names a voice to have nowhere to put one.
    """

    voice_id: str
    provider_id: str
    name: str = ""
    language: str = "en"
    locale: str = ""
    #: The provider's own quality or priority hint, normalised to 0..1 where the
    #: provider offers one. Used only to order otherwise-equal candidates.
    preference: float = 0.5
    #: ``True`` when this is the provider's default for its language. A request
    #: that names no voice gets a default rather than the alphabetically first.
    default: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "voiceId": self.voice_id,
            "providerId": self.provider_id,
            "name": self.name,
            "language": self.language,
            "locale": self.locale,
            "preference": self.preference,
            "default": self.default,
        }


@dataclass(frozen=True)
class ProviderDeclaration:
    """Everything a provider promises, checked before it is asked for anything.

    Undeclared is unavailable. A provider whose declaration does not cover a
    request is not tried and then failed; it is not selected, and the reason is
    carried into :class:`SelectionResult` so a user asking "why did it not
    speak" gets the answer rather than a shrug.
    """

    provider_id: str
    display_name: str = ""
    #: Which *build* of the provider this is — a version, a data revision, the
    #: thing that changes when the same provider id starts sounding different.
    #: Recorded on every utterance so a measurement can be attributed.
    implementation_id: str = ""
    languages: tuple[str, ...] = ()
    locales: tuple[str, ...] = ()
    audio_formats: tuple[str, ...] = ()
    sample_rates: tuple[int, ...] = ()
    supports_synthesis: bool = False
    supports_streaming: bool = False
    supports_cancellation: bool = False
    rate_control: bool = False
    pitch_control: bool = False
    volume_control: bool = False
    #: ``True`` for a provider that runs entirely on this machine. There is no
    #: ``False`` provider in this build and :meth:`serves` refuses one, so the
    #: field is a gate rather than a description.
    local: bool = True
    #: ``free``, ``metered`` or ``paid``. Only ``free`` is reachable here.
    cost_class: str = "free"
    #: The highest :mod:`companion.privacy` classification this provider may be
    #: handed. A local synthesiser may hold anything the executor may; a remote
    #: one could not, and this is where that would be stated.
    maximum_privacy_class: str = "secret"
    requires_authentication: bool = False
    #: Whether the provider returns phoneme boundaries with the audio. Declared
    #: ``False`` by everything in this build: §13 forbids claiming phoneme
    #: accuracy that has not been measured, and none has been.
    provides_phoneme_timing: bool = False
    provides_native_visemes: bool = False
    #: Installed model ids exposed to settings.  Empty for engines whose model
    #: is part of the system package rather than a user choice.
    models: tuple[str, ...] = ()
    default_model_id: str = ""
    #: How the provider was resolved. ``False`` means it was found outside
    #: :data:`companion.voice.execution.TRUSTED_DIRECTORIES`, which the installed
    #: system never does; carried so a report can say which platform it is about.
    trusted_resolution: bool = True

    @property
    def fully_declared(self) -> bool:
        """Whether this declaration is complete enough to be trusted.

        An undeclared provider fails closed, exactly as
        :class:`companion.executor.ExecutorDeclaration` does. The two subsystems
        take the same position for the same reason: a component that did not say
        what it does cannot be checked against what it was asked for.
        """
        return bool(
            self.provider_id
            and self.implementation_id
            and self.languages
            and (self.supports_synthesis or self.supports_streaming)
            and self.cost_class in ("free", "metered", "paid")
        )

    def handles_language(self, language: str, locale: str = "") -> bool:
        if language not in self.languages:
            return False
        # A locale is honoured when declared and *ignored* when not: a provider
        # with an ``en`` voice and no ``en-GB`` still speaks English, and
        # refusing over the region would cost the user the utterance to satisfy
        # an accent.
        return not (locale and self.locales and locale not in self.locales)

    def serves(self, request: VoiceRequest) -> tuple[bool, tuple[str, ...]]:
        """Whether this provider may take this request, and every reason it may not.

        All the reasons, not the first. A user told "it cannot speak this"
        deserves the whole answer — the same position
        :func:`companion.capability_bridge._declaration_reasons` takes about
        executors, for the same reason.
        """
        reasons: list[str] = []
        if not self.fully_declared:
            reasons.append(
                f"{self.provider_id!r} has not fully declared itself; an undeclared provider fails closed"
            )
        if not self.local:
            # The one refusal in this module that is a policy statement rather
            # than a capability check. §15: no remote provider exists in this
            # phase, and the way to keep it that way is to refuse one here
            # rather than to rely on nobody writing it.
            reasons.append(
                f"{self.provider_id!r} is not local; this build has no remote speech path "
                "and local incapability does not authorise one"
            )
        if request.locality_requirement == "device-only" and not self.local:
            reasons.append("this utterance is device-only and the provider is not")
        if not self.handles_language(request.language, request.locale):
            reasons.append(
                f"{self.provider_id!r} has no voice for {request.locale or request.language!r}"
            )
        if rank(request.privacy_classification) > rank(self.maximum_privacy_class):
            reasons.append(
                f"the utterance is classified {request.privacy_classification} and "
                f"{self.provider_id!r} may hold data up to {self.maximum_privacy_class}"
            )
        if self.cost_class != "free" and request.cost_ceiling_units <= 0:
            reasons.append(
                f"{self.provider_id!r} bills for use and this utterance permits no spend"
            )
        if self.requires_authentication:
            reasons.append(f"{self.provider_id!r} requires authentication and none is configured")
        # Format and rate are checked only against the synthesis path. A
        # streaming provider never hands us samples, so what container it would
        # have used is not a fact about whether it can speak.
        if self.supports_synthesis:
            if request.audio_format not in self.audio_formats and not self.supports_streaming:
                reasons.append(
                    f"{self.provider_id!r} does not produce {request.audio_format}"
                )
            if request.sample_rate not in self.sample_rates and not self.supports_streaming:
                reasons.append(
                    f"{self.provider_id!r} does not produce audio at {request.sample_rate} Hz"
                )
        elif not self.supports_streaming:
            reasons.append(f"{self.provider_id!r} can neither synthesise nor stream")
        return (not reasons), tuple(reasons)

    def to_json(self) -> dict[str, Any]:
        return {
            "providerId": self.provider_id,
            "displayName": self.display_name or self.provider_id,
            "implementationId": self.implementation_id,
            "languages": list(self.languages),
            "locales": list(self.locales),
            "audioFormats": list(self.audio_formats),
            "sampleRates": list(self.sample_rates),
            "supportsSynthesis": self.supports_synthesis,
            "supportsStreaming": self.supports_streaming,
            "supportsCancellation": self.supports_cancellation,
            "rateControl": self.rate_control,
            "pitchControl": self.pitch_control,
            "volumeControl": self.volume_control,
            "local": self.local,
            "costClass": self.cost_class,
            "maximumPrivacyClass": self.maximum_privacy_class,
            "requiresAuthentication": self.requires_authentication,
            "providesPhonemeTiming": self.provides_phoneme_timing,
            "providesNativeVisemes": self.provides_native_visemes,
            "models": list(self.models),
            "defaultModelId": self.default_model_id,
            "trustedResolution": self.trusted_resolution,
            "fullyDeclared": self.fully_declared,
            "remoteTransmission": not self.local,
            "voiceCloning": False,
        }


@dataclass(frozen=True)
class ProviderHealth:
    """Whether a provider can be used *now*, and why not when it cannot."""

    provider_id: str
    available: bool = False
    authenticated: bool = True
    healthy: bool = True
    detail: str = ""
    #: Stable machine-readable readiness state.  Settings renders ``detail``;
    #: diagnostics and tests use this value without parsing prose.
    status: str = ""
    #: The monotonic reading this was taken at. Health is cached — probing a
    #: binary's existence on every utterance is a stat call per word — and a
    #: cached answer with no timestamp is an answer nobody can age out.
    checked_at_monotonic: float = 0.0
    #: How many consecutive failures this provider has had. The fixed local
    #: ladder uses it for diagnostics; one utterance never retries the same
    #: failed provider.
    consecutive_failures: int = 0

    @property
    def ready(self) -> bool:
        return self.available and self.authenticated and self.healthy

    def to_json(self) -> dict[str, Any]:
        return {
            "providerId": self.provider_id,
            "available": self.available,
            "authenticated": self.authenticated,
            "healthy": self.healthy,
            "ready": self.ready,
            "detail": self.detail,
            "status": self.status or ("READY" if self.ready else "UNAVAILABLE"),
            "checkedAtMonotonic": self.checked_at_monotonic,
            "consecutiveFailures": self.consecutive_failures,
        }


@dataclass(frozen=True)
class ResourceEstimate:
    """What one utterance is expected to cost, before it is started.

    Estimates, and named as such. They exist so §11 can refuse an utterance on a
    machine with no headroom *before* forking a synthesiser, which is the only
    point at which refusing is cheaper than the thing being refused. Measured
    values for this build are in ``COMPANION_VOICE_REPORT.md``; these constants
    are the provider's own conservative claim and are deliberately round.
    """

    memory_bytes: int = 0
    temporary_bytes: int = 0
    #: Fraction of one core, for the duration.
    cpu_share: float = 0.0
    expected_latency_seconds: float = 0.0

    def to_json(self) -> dict[str, Any]:
        return {
            "memoryBytes": self.memory_bytes,
            "temporaryBytes": self.temporary_bytes,
            "cpuShare": self.cpu_share,
            "expectedLatencySeconds": self.expected_latency_seconds,
        }


@dataclass(frozen=True)
class SynthesisResult:
    """Audio a provider produced, and everything true about producing it.

    ``audio_path`` lives inside the :class:`PrivateWorkspace` the worker owns
    and is removed with it. Nothing here holds the utterance's text: a result
    that carried the words would put them in every diagnostic that logs a
    result, which is exactly §15's objection.
    """

    request_id: str
    provider_id: str
    implementation_id: str
    voice_id: str
    succeeded: bool
    audio_path: str = ""
    audio_format: str = ""
    sample_rate: int = 0
    channels: int = 1
    frame_count: int = 0
    duration_seconds: float = 0.0
    synthesis_seconds: float = 0.0
    #: Degradations accepted to produce this at all — a rate the provider could
    #: not honour, a pitch it ignored. Recorded rather than silently applied:
    #: §12 requires degradation to be visible, and a provider that quietly
    #: substituted its default would make the record wrong rather than partial.
    degradations: tuple[str, ...] = ()
    detail: str = ""
    outcome: CommandOutcome | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "requestId": self.request_id,
            "providerId": self.provider_id,
            "implementationId": self.implementation_id,
            "voiceId": self.voice_id,
            "succeeded": self.succeeded,
            "audioFormat": self.audio_format,
            "sampleRate": self.sample_rate,
            "channels": self.channels,
            "frameCount": self.frame_count,
            "durationSeconds": round(self.duration_seconds, 6),
            "synthesisSeconds": round(self.synthesis_seconds, 6),
            "degradations": list(self.degradations),
            "detail": self.detail,
            "command": self.outcome.to_json() if self.outcome is not None else None,
        }


@dataclass(frozen=True)
class StreamOutcome:
    """What a provider-owned playback did.

    Deliberately thinner than :class:`SynthesisResult`: when the provider owns
    the audio there is genuinely less that is knowable, and inventing a duration
    we did not measure would put a fabricated number into §24's table.
    """

    request_id: str
    provider_id: str
    implementation_id: str
    voice_id: str
    succeeded: bool
    cancelled: bool = False
    elapsed_seconds: float = 0.0
    degradations: tuple[str, ...] = ()
    detail: str = ""
    outcome: CommandOutcome | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "requestId": self.request_id,
            "providerId": self.provider_id,
            "implementationId": self.implementation_id,
            "voiceId": self.voice_id,
            "succeeded": self.succeeded,
            "cancelled": self.cancelled,
            "elapsedSeconds": round(self.elapsed_seconds, 6),
            "degradations": list(self.degradations),
            "detail": self.detail,
            "command": self.outcome.to_json() if self.outcome is not None else None,
        }


@runtime_checkable
class VoiceProvider(Protocol):
    """The whole of what the worker may call on a provider.

    One method per thing, and nothing that takes a command, a path or a URL. A
    provider cannot be asked to run something; it can be asked to speak, and
    what it runs to do that is its own business behind
    :mod:`companion.voice.execution`'s allowlist.
    """

    @property
    def declaration(self) -> ProviderDeclaration: ...

    def inventory(self) -> Sequence[VoiceDescriptor]:
        """The voices this provider has installed, right now."""

    def health(self, *, monotonic: float = 0.0, refresh: bool = False) -> ProviderHealth:
        """Whether it can be used. Never raises; unavailability is a return value."""

    def estimate(self, request: VoiceRequest) -> ResourceEstimate:
        """What serving this request is expected to cost."""

    def synthesize(
        self,
        request: VoiceRequest,
        workspace: PrivateWorkspace,
        *,
        cancellation: CancellationSignal | None = None,
    ) -> SynthesisResult:
        """Produce audio into ``workspace``. Never plays it."""

    def stream(
        self,
        request: VoiceRequest,
        *,
        cancellation: CancellationSignal | None = None,
        on_started: Callable[[], None] | None = None,
    ) -> StreamOutcome:
        """Speak directly, with the provider owning playback."""

    def cancel(self, request_id: str) -> bool:
        """Stop one in-flight utterance. Returns whether there was one."""

    def close(self) -> None:
        """Release everything. Must be safe to call twice and after a fault."""


# --------------------------------------------------------------------------- #
# Selection
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SelectionResult:
    """Which provider will speak, and the whole reason every other one will not.

    ``rejected`` is kept even on success. "Why did it pick eSpeak when Speech
    Dispatcher is installed" is a question somebody will ask, and an answer that
    only exists when nothing was selected is an answer that is never there when
    it is wanted.
    """

    provider: VoiceProvider | None
    voice: VoiceDescriptor | None
    rejected: tuple[tuple[str, tuple[str, ...]], ...] = ()
    detail: str = ""

    @property
    def selected(self) -> bool:
        return self.provider is not None

    def to_json(self) -> dict[str, Any]:
        return {
            "selected": self.selected,
            "providerId": self.provider.declaration.provider_id if self.provider else "",
            "voice": self.voice.to_json() if self.voice else None,
            "rejected": [
                {"providerId": name, "reasons": list(reasons)} for name, reasons in self.rejected
            ],
            "detail": self.detail,
        }


class ProviderRegistry:
    """The providers this runtime knows, in preference order.

    Order is the caller's, not a score computed here. A registry that ranked
    providers by a quality heuristic would be making a judgement the user cannot
    see or change; the order comes from :func:`companion.voice.providers.local_providers`
    where it is one readable tuple, and the degradation ladder in
    :mod:`companion.voice.policy` moves *down* it deterministically.
    """

    def __init__(self, providers: Iterable[VoiceProvider] = ()) -> None:
        self._providers: list[VoiceProvider] = list(providers)

    def __len__(self) -> int:
        return len(self._providers)

    def __iter__(self):
        return iter(self._providers)

    def add(self, provider: VoiceProvider) -> None:
        self._providers.append(provider)

    def get(self, provider_id: str) -> VoiceProvider | None:
        for provider in self._providers:
            if provider.declaration.provider_id == provider_id:
                return provider
        return None

    def declarations(self) -> list[dict[str, Any]]:
        return [provider.declaration.to_json() for provider in self._providers]

    def inventory(self) -> list[VoiceDescriptor]:
        """Every installed voice across every available provider.

        A provider that is not available contributes nothing rather than raising
        — the voice list is something a settings surface asks for, and a settings
        surface that failed to open because a synthesiser was uninstalled would
        be a worse answer than a shorter list.
        """
        voices: list[VoiceDescriptor] = []
        for provider in self._providers:
            try:
                health = provider.health()
                if not health.available and health.status not in ("INITIALIZING", "MODEL_VERIFIED"):
                    continue
                voices.extend(provider.inventory())
            except Exception:  # noqa: BLE001 - an inventory must never break a list
                continue
        return voices

    def health(self, *, monotonic: float = 0.0, refresh: bool = False) -> list[ProviderHealth]:
        return [provider.health(monotonic=monotonic, refresh=refresh) for provider in self._providers]

    def select(
        self,
        request: VoiceRequest,
        *,
        monotonic: float = 0.0,
        exclude: Iterable[str] = (),
        require_synthesis: bool = False,
        require_streaming: bool = False,
        preferred_provider_id: str = "",
    ) -> SelectionResult:
        """The first provider in order that may and can serve this request.

        ``exclude`` carries providers already tried on this utterance. The
        worker retries with failed providers excluded. It may descend the
        complete fixed local ladder, but after the last eligible provider the
        visible caption is the whole output.
        """
        skipped = set(exclude)
        rejected: list[tuple[str, tuple[str, ...]]] = []
        preference_known = any(
            provider.declaration.provider_id == preferred_provider_id
            for provider in self._providers
        ) if preferred_provider_id else False
        providers = self._ordered_from(preferred_provider_id)
        for provider in providers:
            declaration = provider.declaration
            name = declaration.provider_id
            if name in skipped:
                rejected.append((name, ("excluded after an earlier failure on this utterance",)))
                continue
            permitted, reasons = declaration.serves(request)
            problems = list(reasons)
            if require_synthesis and not declaration.supports_synthesis:
                problems.append(f"{name!r} cannot produce an audio artifact")
            if require_streaming and not declaration.supports_streaming:
                problems.append(f"{name!r} cannot stream")
            if permitted and not problems:
                health = provider.health(monotonic=monotonic)
                # Neural providers verify their pinned assets asynchronously so
                # companion startup never waits for model I/O, then load only
                # the provider selected for the utterance. Selection runs on
                # the dedicated voice worker, where waiting is safe and keeps
                # the first response from skipping Pocket during cold startup.
                if not health.ready and health.status in ("INITIALIZING", "MODEL_VERIFIED"):
                    try:
                        health = provider.health(monotonic=monotonic, refresh=True)
                    except Exception as exc:  # noqa: BLE001 - selection falls down safely
                        health = ProviderHealth(
                            provider_id=name,
                            available=False,
                            healthy=False,
                            detail=f"readiness refresh failed: {type(exc).__name__}",
                            status="WORKER_FAILED",
                            checked_at_monotonic=monotonic,
                        )
                if not health.ready:
                    problems.append(
                        f"{name!r} is not ready" + (f": {health.detail}" if health.detail else "")
                    )
            if problems:
                rejected.append((name, tuple(problems)))
                continue
            voice = _choose_voice(
                provider,
                request,
                honour_named_voice=(
                    not preference_known or name == preferred_provider_id
                ),
            )
            if voice is None:
                rejected.append((name, (f"{name!r} has no installed voice matching the request",)))
                continue
            return SelectionResult(
                provider=provider,
                voice=voice,
                rejected=tuple(rejected),
                detail=f"{name} selected",
            )
        return SelectionResult(
            provider=None,
            voice=None,
            rejected=tuple(rejected),
            detail="no eligible local voice provider; the caption is the whole of the output",
        )

    def _ordered_from(self, preferred_provider_id: str) -> list[VoiceProvider]:
        """The fixed degradation ladder beginning at the user's preference.

        A preference may move the starting point down the declared order; it
        cannot smuggle in an unregistered provider and it never climbs back to a
        heavier provider after failure.  Thus low-resource Kitten degrades to
        eSpeak and Speech Dispatcher, not back to Pocket.
        """
        if not preferred_provider_id:
            return list(self._providers)
        for index, provider in enumerate(self._providers):
            if provider.declaration.provider_id == preferred_provider_id:
                return list(self._providers[index:])
        return list(self._providers)

    def close(self) -> None:
        for provider in self._providers:
            try:
                provider.close()
            except Exception:  # noqa: BLE001 - closing must not raise past the first failure
                continue


def _choose_voice(
    provider: VoiceProvider,
    request: VoiceRequest,
    *,
    honour_named_voice: bool = True,
) -> VoiceDescriptor | None:
    """The voice a request names, or the provider's default for its language.

    A named voice that is not installed returns ``None`` rather than quietly
    substituting: a user who chose a voice and got a different one has been
    ignored, and §21 tests the refusal.
    """
    try:
        voices = list(provider.inventory())
    except Exception:  # noqa: BLE001
        return None
    if not voices:
        return None
    if request.voice_id and honour_named_voice:
        for voice in voices:
            if voice.voice_id == request.voice_id:
                return voice
        return None
    locale = request.locale.lower()
    language = request.language.lower()
    exact = [item for item in voices if item.locale.lower() == locale]
    same_language = [item for item in voices if item.language.lower() == language]
    for pool in (exact, same_language):
        if not pool:
            continue
        default = [item for item in pool if item.default]
        chosen = default or pool
        return max(chosen, key=lambda item: (item.preference, item.voice_id))
    return None
