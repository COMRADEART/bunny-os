# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Provider-neutral AI, voice, and speech-input contracts.

No commercial or remote provider adapter is implemented here.  Descriptors
contain authentication *state* but never credentials.  A provider is selected
only after the capability/privacy router has supplied a permitted identity.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import shutil
import subprocess
import threading
from typing import Any, Callable, Mapping, Sequence

from .model import Locality, PrivacyClass, bounded_text, redact_text, safe_identifier


@dataclass(frozen=True)
class UsageReport:
    input_units: int = 0
    output_units: int = 0
    cost_minor_units: int = 0
    currency: str = "USD"

    def __post_init__(self) -> None:
        if min(self.input_units, self.output_units, self.cost_minor_units) < 0:
            raise ValueError("usage values cannot be negative")

    def to_json(self) -> dict[str, Any]:
        return {
            "inputUnits": self.input_units,
            "outputUnits": self.output_units,
            "costMinorUnits": self.cost_minor_units,
            "currency": self.currency,
        }


@dataclass(frozen=True)
class AgentProviderDescriptor:
    provider_id: str
    model_id: str
    capabilities: tuple[str, ...]
    context_window_limit: int
    tool_support: bool
    streaming_support: bool
    structured_output_support: bool
    image_support: bool
    audio_support: bool
    locality: Locality
    cost_class: str
    privacy_classification: PrivacyClass
    authentication_state: str
    availability: str
    health: str

    def __post_init__(self) -> None:
        safe_identifier(self.provider_id, "provider id")
        safe_identifier(self.model_id, "model id")
        if self.context_window_limit < 0:
            raise ValueError("context window limit cannot be negative")
        if self.cost_class not in {"free", "metered", "paid", "unknown"}:
            raise ValueError("provider cost class is invalid")
        if self.authentication_state not in {"not_required", "configured", "missing", "invalid", "unknown"}:
            raise ValueError("provider authentication state is invalid")
        if self.availability not in {"available", "unavailable", "degraded", "unknown"}:
            raise ValueError("provider availability is invalid")
        if self.health not in {"healthy", "degraded", "unhealthy", "unknown"}:
            raise ValueError("provider health is invalid")

    def to_json(self) -> dict[str, Any]:
        return {
            "providerId": self.provider_id,
            "modelId": self.model_id,
            "capabilities": list(self.capabilities),
            "contextWindowLimit": self.context_window_limit,
            "toolSupport": self.tool_support,
            "streamingSupport": self.streaming_support,
            "structuredOutputSupport": self.structured_output_support,
            "imageSupport": self.image_support,
            "audioSupport": self.audio_support,
            "locality": self.locality.value,
            "costClass": self.cost_class,
            "privacyClassification": self.privacy_classification.value,
            "authenticationState": self.authentication_state,
            "availability": self.availability,
            "health": self.health,
        }


@dataclass(frozen=True)
class AgentProviderRequest:
    request_id: str
    task_id: str
    display_prompt: str
    permitted_tools: tuple[str, ...] = ()
    structured_output_schema: Mapping[str, Any] | None = None
    maximum_output_units: int = 0

    def __post_init__(self) -> None:
        safe_identifier(self.request_id, "provider request id")
        safe_identifier(self.task_id, "provider task id")
        bounded_text(self.display_prompt, "provider display prompt", 8192)


@dataclass(frozen=True)
class AgentProviderResponse:
    request_id: str
    display_text: str
    structured_output: Mapping[str, Any] | None = None
    usage: UsageReport = field(default_factory=UsageReport)
    finish_reason: str = "complete"

    def __post_init__(self) -> None:
        safe_identifier(self.request_id, "provider response request id")
        bounded_text(self.display_text, "provider display text", 32768)


class AgentProvider(ABC):
    @property
    @abstractmethod
    def descriptor(self) -> AgentProviderDescriptor:
        raise NotImplementedError

    @abstractmethod
    def generate(self, request: AgentProviderRequest) -> AgentProviderResponse:
        raise NotImplementedError

    @abstractmethod
    def cancel(self, request_id: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def usage(self, request_id: str) -> UsageReport | None:
        raise NotImplementedError


@dataclass(frozen=True)
class VoiceDescriptor:
    provider_id: str
    voice_id: str
    languages: tuple[str, ...]
    styles: tuple[str, ...]
    streaming: bool
    cancellation: bool
    audio_formats: tuple[str, ...]
    locality: Locality
    cost_class: str
    privacy_classification: PrivacyClass
    health: str
    fallback_provider_id: str | None = None

    def __post_init__(self) -> None:
        safe_identifier(self.provider_id, "voice provider id")
        safe_identifier(self.voice_id, "voice id")
        if self.fallback_provider_id is not None:
            safe_identifier(self.fallback_provider_id, "fallback voice provider id")
        if self.health not in {"healthy", "degraded", "unavailable", "unknown"}:
            raise ValueError("voice health is invalid")
        if self.cost_class not in {"free", "metered", "paid", "unknown"}:
            raise ValueError("voice cost class is invalid")

    def to_json(self) -> dict[str, Any]:
        return {
            "providerId": self.provider_id,
            "voiceId": self.voice_id,
            "languages": list(self.languages),
            "styles": list(self.styles),
            "streaming": self.streaming,
            "cancellation": self.cancellation,
            "audioFormats": list(self.audio_formats),
            "locality": self.locality.value,
            "costClass": self.cost_class,
            "privacyClassification": self.privacy_classification.value,
            "health": self.health,
            "fallbackProviderId": self.fallback_provider_id,
        }


@dataclass(frozen=True)
class SpeechRequest:
    speech_id: str
    text: str
    language: str = "en"
    style: str = "neutral"
    speed: float = 1.0
    audio_format: str = "system-device"

    def __post_init__(self) -> None:
        safe_identifier(self.speech_id, "speech id")
        bounded_text(self.text, "speech text", 4000)
        if not 0.5 <= self.speed <= 2.0:
            raise ValueError("speech speed is outside the supported range")


@dataclass(frozen=True)
class SpeechResult:
    speech_id: str
    completed: bool
    cancelled: bool = False
    detail: str = ""
    usage: UsageReport = field(default_factory=UsageReport)


class VoiceProvider(ABC):
    @property
    @abstractmethod
    def descriptor(self) -> VoiceDescriptor:
        raise NotImplementedError

    @abstractmethod
    def speak(self, request: SpeechRequest) -> SpeechResult:
        raise NotImplementedError

    @abstractmethod
    def cancel(self, speech_id: str) -> bool:
        raise NotImplementedError


class VoiceRouter:
    """Select an available voice without silently crossing policy boundaries.

    The ordering is intentional: callers provide their preferred provider and
    explicit fallbacks.  Remote or paid providers are skipped unless the
    corresponding decision was already approved by policy.  The router does
    not itself ask for approval and never treats an unavailable provider as a
    successful speech operation.
    """

    def __init__(self, providers: Sequence[VoiceProvider]) -> None:
        if not providers:
            raise ValueError("at least one voice provider is required")
        self.providers = tuple(providers)
        identities = [item.descriptor.provider_id for item in self.providers]
        if len(identities) != len(set(identities)):
            raise ValueError("voice provider identities must be unique")

    def select(
        self,
        *,
        remote_approved: bool = False,
        paid_approved: bool = False,
    ) -> VoiceProvider | None:
        for provider in self.providers:
            descriptor = provider.descriptor
            if descriptor.health != "healthy":
                continue
            if descriptor.locality == Locality.REMOTE and not remote_approved:
                continue
            if descriptor.cost_class in {"metered", "paid"} and not paid_approved:
                continue
            return provider
        return None


class CaptionsOnlyVoiceProvider(VoiceProvider):
    """Explicit no-audio endpoint used when policy permits no voice provider."""

    @property
    def descriptor(self) -> VoiceDescriptor:
        return VoiceDescriptor(
            provider_id="captions-only",
            voice_id="no-audio",
            languages=(),
            styles=(),
            streaming=False,
            cancellation=False,
            audio_formats=(),
            locality=Locality.LOCAL,
            cost_class="free",
            privacy_classification=PrivacyClass.INTERNAL,
            health="unavailable",
        )

    def speak(self, request: SpeechRequest) -> SpeechResult:
        return SpeechResult(
            speech_id=request.speech_id,
            completed=False,
            detail="audio is disabled; captions remain available",
        )

    def cancel(self, speech_id: str) -> bool:
        return False


class SystemVoiceProvider(VoiceProvider):
    """A real local system speech adapter, available only when a binary exists."""

    def __init__(self) -> None:
        candidates = (
            ("spd-say", "speech-dispatcher"),
            ("espeak-ng", "espeak-ng"),
            ("say", "macos-system-voice"),
        )
        self._command: str | None = None
        self._voice_id = "system-default"
        for executable, voice_id in candidates:
            resolved = shutil.which(executable)
            if resolved:
                self._command = resolved
                self._voice_id = voice_id
                break
        self._processes: dict[str, subprocess.Popen[Any]] = {}
        self._lock = threading.RLock()

    @property
    def descriptor(self) -> VoiceDescriptor:
        available = self._command is not None
        return VoiceDescriptor(
            provider_id="os-system-voice",
            voice_id=self._voice_id,
            languages=("system-default",),
            styles=("neutral",),
            streaming=False,
            cancellation=True,
            audio_formats=("system-device",),
            locality=Locality.LOCAL,
            cost_class="free",
            privacy_classification=PrivacyClass.INTERNAL,
            health="healthy" if available else "unavailable",
        )

    def _argv(self, request: SpeechRequest) -> list[str]:
        assert self._command is not None
        name = self._voice_id
        if name == "speech-dispatcher":
            rate = int(max(-100, min(100, (request.speed - 1.0) * 100)))
            return [self._command, "--wait", "--rate", str(rate), "--", request.text]
        if name == "espeak-ng":
            words_per_minute = int(175 * request.speed)
            return [self._command, "-s", str(words_per_minute), request.text]
        words_per_minute = int(180 * request.speed)
        return [self._command, "-r", str(words_per_minute), request.text]

    def speak(self, request: SpeechRequest) -> SpeechResult:
        if self._command is None:
            return SpeechResult(request.speech_id, completed=False, detail="no local system voice is available")
        process = subprocess.Popen(
            self._argv(request),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        with self._lock:
            self._processes[request.speech_id] = process
        return_code = process.wait()
        with self._lock:
            self._processes.pop(request.speech_id, None)
        cancelled = return_code < 0
        return SpeechResult(
            request.speech_id,
            completed=return_code == 0,
            cancelled=cancelled,
            detail="local system voice completed" if return_code == 0 else f"local system voice exited {return_code}",
        )

    def cancel(self, speech_id: str) -> bool:
        with self._lock:
            process = self._processes.get(speech_id)
            if process is None or process.poll() is not None:
                return False
            process.terminate()
            return True


@dataclass(frozen=True)
class SpeechInputDescriptor:
    provider_id: str
    languages: tuple[str, ...]
    partial_transcription: bool
    cancellation: bool
    locality: Locality
    privacy_classification: PrivacyClass
    health: str

    def __post_init__(self) -> None:
        safe_identifier(self.provider_id, "speech input provider id")
        if self.health not in {"healthy", "degraded", "unavailable", "unknown"}:
            raise ValueError("speech input health is invalid")


@dataclass(frozen=True)
class SpeechInputRequest:
    interaction_id: str
    language: str = "en"
    mode: str = "push_to_talk"
    silence_timeout_seconds: float = 5.0
    explicit_user_activation: bool = False
    continuous_conversation_enabled: bool = False
    remote_transmission_approved: bool = False

    def __post_init__(self) -> None:
        safe_identifier(self.interaction_id, "speech interaction id")
        if self.mode not in {"push_to_talk", "wake_interaction", "continuous"}:
            raise ValueError("speech input mode is invalid")
        if not 0.5 <= self.silence_timeout_seconds <= 120.0:
            raise ValueError("silence timeout is outside the supported range")


@dataclass(frozen=True)
class Transcript:
    interaction_id: str
    text: str
    final: bool

    def __post_init__(self) -> None:
        safe_identifier(self.interaction_id, "transcript interaction id")
        bounded_text(self.text, "transcript", 8192, allow_empty=True)


class SpeechInputProvider(ABC):
    @property
    @abstractmethod
    def descriptor(self) -> SpeechInputDescriptor:
        raise NotImplementedError

    @abstractmethod
    def start(self, request: SpeechInputRequest, on_transcript: Callable[[Transcript], None]) -> None:
        raise NotImplementedError

    @abstractmethod
    def cancel(self, interaction_id: str) -> bool:
        raise NotImplementedError


IndicatorCallback = Callable[[bool, bool], None]


class MicrophoneController:
    """The only supported activation path for a speech-input provider."""

    def __init__(self, *, microphone_available: bool, indicator: IndicatorCallback) -> None:
        self.microphone_available = microphone_available
        self.indicator = indicator
        self._active: tuple[SpeechInputProvider, str] | None = None

    def start(
        self,
        provider: SpeechInputProvider,
        request: SpeechInputRequest,
        on_transcript: Callable[[Transcript], None],
    ) -> None:
        if not self.microphone_available:
            raise PermissionError("the microphone is unavailable or disabled")
        if not request.explicit_user_activation:
            raise PermissionError("microphone activation requires an explicit user interaction")
        if request.mode == "continuous" and not request.continuous_conversation_enabled:
            raise PermissionError("continuous conversation was not explicitly enabled")
        remote = provider.descriptor.locality == Locality.REMOTE
        if remote and not request.remote_transmission_approved:
            raise PermissionError("remote audio transmission was not approved")
        if self._active is not None:
            raise RuntimeError("a microphone interaction is already active")

        # The persistent indicator is raised before the provider can touch the
        # device or network.  A provider failure then clears it in finally.
        self.indicator(True, remote)
        self._active = (provider, request.interaction_id)
        try:
            provider.start(request, on_transcript)
        except BaseException:
            self._active = None
            self.indicator(False, False)
            raise

    def stop(self) -> bool:
        active = self._active
        if active is None:
            return False
        provider, interaction_id = active
        try:
            return provider.cancel(interaction_id)
        finally:
            self._active = None
            self.indicator(False, False)
