# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Speaking out loud: the runtime, and the boundary around listening.

This package was a single module — :mod:`companion.voice.system`, which still
holds it unchanged — that could read a caption aloud through a local
synthesiser. It stayed deliberately small because speech is optional and a
caption is not, and everything it did is still true: argument arrays and never a
command string, text bounded before it is spoken, failure returned as data
rather than raised at a caller with a task to finish.

What this package adds is everything that "read a caption aloud" leaves out once
the companion has a character with a mouth, a machine that may be too hot to
narrate, and a user who may cancel mid-sentence:

:mod:`~companion.voice.request`
    The versioned, bounded schema that is the whole of the runtime's input, and
    §7's priority ladder.
:mod:`~companion.voice.execution`
    Allowlisted, argv-only subprocess execution with deterministic resolution,
    bounded environments, private workspaces, escalating termination and
    guaranteed reaping.
:mod:`~companion.voice.provider` / :mod:`~companion.voice.providers`
    The provider-neutral contract, and the two real local adapters — eSpeak NG
    and Speech Dispatcher. No commercial adapter and no placeholder shaped like
    one.
:mod:`~companion.voice.audio` / :mod:`~companion.voice.pcm`
    Device discovery, playback with pause and resume, loss handling with
    backoff and hysteresis, and the WAV inspection that decides whether a
    synthesiser actually produced sound.
:mod:`~companion.voice.captions`
    The rule the rest of it serves: the caption is the output, speech is a
    second rendering of it, and a replay does not re-speak.
:mod:`~companion.voice.visemes`
    Generic mouth shapes on the renderer's own vocabulary, labelled with how
    their timing was arrived at and never claiming more.
:mod:`~companion.voice.policy` / :mod:`~companion.voice.queue`
    §11's four outcomes from the existing capability plan, §12's deterministic
    descent, and the bounded priority queue that makes an unbounded narration
    loop impossible.
:mod:`~companion.voice.worker` / :mod:`~companion.voice.recovery`
    One speaking thread that owns every resource an utterance touches, and the
    journal that lets the next process tell "finished" from "stopped
    mid-sentence".
:mod:`~companion.voice.service`
    The eight operations a client may call, and the §18 decision to run inside
    the canonical companion service rather than beside it.

**Listening is still not implemented and this package still says so.**
:class:`MicrophoneBoundary` is the activation rule and
:class:`AbsentSpeechRecognition` refuses rather than returning an empty
transcript. Nothing in the voice *runtime* touches a microphone; it is an output
subsystem, and the boundary is re-exported here so that the one place somebody
looks for "how does Bunny OS listen" still answers honestly.
"""

from __future__ import annotations

from .audio import (
    AlsaBackend,
    AudioDevice,
    AudioRouter,
    BackendHealth,
    DEGRADATION_KINDS,
    DegradationRecord,
    PipeWireBackend,
    PlaybackHandle,
    PlaybackOutcome,
    PulseAudioBackend,
    local_backends,
)
from .captions import (
    Caption,
    CaptionLedger,
    SpeechDisposition,
    SyncMeasurement,
    TOLERANCES,
    caption_from_state,
)
from .execution import (
    ALLOWED_EXECUTABLES,
    CancellationSignal,
    CommandOutcome,
    CommandSpec,
    ExecutableRefused,
    PrivateWorkspace,
    TRUSTED_DIRECTORIES,
    redacted_argv,
    resolve_executable,
)
from .pcm import AudioProbe, PcmError, amplitude_envelope, probe_wav
from .policy import (
    VOICE_OUTCOMES,
    VoiceDecision,
    VoicePolicy,
    VoicePreferences,
    VoiceSignals,
    signals_from_capability,
)
from .provider import (
    ProviderDeclaration,
    ProviderHealth,
    ProviderRegistry,
    ResourceEstimate,
    StreamOutcome,
    SynthesisResult,
    VoiceDescriptor,
    VoiceProvider,
)
from .neural import DEFAULT_TTS_PROVIDER, KittenTTSProvider, PocketTTSProvider
from .providers import EspeakNgProvider, SpeechDispatcherProvider, local_providers
from .queue import QueueOutcome, SpeechQueue
from .recovery import RecoveryReport, VoiceJournal, recover, sweep_workspaces
from .request import (
    InterruptionPolicy,
    MAX_SPEECH_BYTES,
    Priority,
    VoiceRequest,
    VoiceRequestError,
    may_speak_locally,
    may_speak_remotely,
    priority_for_phase,
    sanitized_speech_text,
)
from .service import VOICE_OPERATIONS, VoiceService, VoiceServiceOptions
from .system import (
    AbsentSpeechRecognition,
    MAX_SPEECH_CHARACTERS,
    MicrophoneBoundary,
    SpeechOutcome,
    SpeechRecognition,
    SystemVoice,
    VOICE_CANDIDATES,
    local_voice_available,
    speak_caption,
)
from .visemes import (
    MAX_VISEME_EVENTS,
    SOURCE_CONFIDENCE,
    VisemeEvent,
    VisemeScheduler,
    VisemeTimeline,
    from_amplitude,
    from_text,
    speaking_state,
)
from .worker import EVENT_KINDS, Utterance, VoiceEvent, VoiceWorker

__all__ = [
    # The original surface, unchanged. Every existing importer keeps working.
    "AbsentSpeechRecognition",
    "MAX_SPEECH_CHARACTERS",
    "MicrophoneBoundary",
    "SpeechOutcome",
    "SpeechRecognition",
    "SystemVoice",
    "VOICE_CANDIDATES",
    "local_voice_available",
    "speak_caption",
    # Requests and policy
    "InterruptionPolicy",
    "MAX_SPEECH_BYTES",
    "Priority",
    "VOICE_OUTCOMES",
    "VoiceDecision",
    "VoicePolicy",
    "VoicePreferences",
    "VoiceRequest",
    "VoiceRequestError",
    "VoiceSignals",
    "may_speak_locally",
    "may_speak_remotely",
    "priority_for_phase",
    "sanitized_speech_text",
    "signals_from_capability",
    # Execution
    "ALLOWED_EXECUTABLES",
    "CancellationSignal",
    "CommandOutcome",
    "CommandSpec",
    "ExecutableRefused",
    "PrivateWorkspace",
    "TRUSTED_DIRECTORIES",
    "redacted_argv",
    "resolve_executable",
    # Providers
    "DEFAULT_TTS_PROVIDER",
    "EspeakNgProvider",
    "KittenTTSProvider",
    "PocketTTSProvider",
    "ProviderDeclaration",
    "ProviderHealth",
    "ProviderRegistry",
    "ResourceEstimate",
    "SpeechDispatcherProvider",
    "StreamOutcome",
    "SynthesisResult",
    "VoiceDescriptor",
    "VoiceProvider",
    "local_providers",
    # Audio
    "AlsaBackend",
    "AudioDevice",
    "AudioProbe",
    "AudioRouter",
    "BackendHealth",
    "DEGRADATION_KINDS",
    "DegradationRecord",
    "PcmError",
    "PipeWireBackend",
    "PlaybackHandle",
    "PlaybackOutcome",
    "PulseAudioBackend",
    "amplitude_envelope",
    "local_backends",
    "probe_wav",
    # Captions and visemes
    "Caption",
    "CaptionLedger",
    "MAX_VISEME_EVENTS",
    "SOURCE_CONFIDENCE",
    "SpeechDisposition",
    "SyncMeasurement",
    "TOLERANCES",
    "VisemeEvent",
    "VisemeScheduler",
    "VisemeTimeline",
    "caption_from_state",
    "from_amplitude",
    "from_text",
    "speaking_state",
    # Queue, worker, recovery, service
    "EVENT_KINDS",
    "QueueOutcome",
    "RecoveryReport",
    "SpeechQueue",
    "Utterance",
    "VOICE_OPERATIONS",
    "VoiceEvent",
    "VoiceJournal",
    "VoiceService",
    "VoiceServiceOptions",
    "VoiceWorker",
    "recover",
    "sweep_workspaces",
]
