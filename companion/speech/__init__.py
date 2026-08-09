# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Listening, at last — behind the boundary that was built before the ears.

:class:`companion.voice.system.MicrophoneBoundary` has said, since before this
package existed, what listening would have to be: explicit interaction, a
visible indicator raised before anything touches the device, nothing at
service start, nothing remote. This package is that promise implemented, and
the boundary's rules appear here as *types* rather than as discipline:

:mod:`~companion.speech.request`
    The versioned, bounded schema that is the whole of the runtime's input.
    Activation sources are a closed set of explicit interactions; there is no
    wake-word member and no field that could carry a model path.
:mod:`~companion.speech.execution` / :mod:`~companion.speech.capture`
    Allowlisted, argv-only recorders — ``parec``, ``pw-record``, ``arecord`` —
    with multi-call contracts checked before anything runs, a bounded frame
    buffer that counts what it drops, and loss handling with backoff and
    hysteresis.
:mod:`~companion.speech.activity`
    Speech and silence boundaries from the samples themselves. An energy gate,
    deliberately, and never a biometric.
:mod:`~companion.speech.recognizer` / :mod:`~companion.speech.recognizers`
    The provider-neutral contract and the one genuine local adapter (Vosk).
    No remote adapter and no placeholder shaped like one.
:mod:`~companion.speech.transcript` / :mod:`~companion.speech.confirmation`
    Partials that are provisional by type, finals with provenance, and the
    ledger where a transcript waits for the user's yes — which is the only
    path toward a task, and it runs through the gateway, not through here.
:mod:`~companion.speech.policy`
    §10's four outcomes from the existing capability plan, with hysteresis,
    and no rung that leaves the machine.
:mod:`~companion.speech.indicator`
    The listening indicator, raised before the device opens and cleared only
    after the handle closes — refusals, not conventions.
:mod:`~companion.speech.worker` / :mod:`~companion.speech.recovery`
    One capture at a time, owning everything it touches, and the journal that
    lets the next process tell "finished" from "stopped mid-capture" without
    ever resuming a capture on its own.
:mod:`~companion.speech.coordination`
    Output speech quiesced before the microphone opens, recorded, and never
    replayed automatically after a task is submitted.
:mod:`~companion.speech.service`
    The eight operations a client may call, validated against the same table
    the protocol validates the client against.
"""

from __future__ import annotations

from .activity import ActivityState, SpeechActivityDetector
from .capture import (
    AlsaCaptureBackend,
    BoundedFrameBuffer,
    CAPTURE_DEGRADATION_KINDS,
    CaptureBackendHealth,
    CaptureDegradation,
    CaptureDevice,
    CaptureHandle,
    CaptureRouter,
    PipeWireCaptureBackend,
    PulseAudioCaptureBackend,
    RecorderContract,
    local_capture_backends,
)
from .confirmation import ConfirmationLedger, ConfirmedSubmission, PendingTranscript
from .coordination import CoordinationRecord, VoiceOutputCoordinator
from .events import SPEECH_EVENT_KINDS, SpeechInputEvent
from .execution import CAPTURE_EXECUTABLES, CaptureChild, SpeechWorkspace, resolve_capture_executable
from .indicator import IndicatorSink, IndicatorState, ListeningIndicator
from .policy import (
    SPEECH_INPUT_OUTCOMES,
    SpeechInputDecision,
    SpeechInputPolicy,
    SpeechInputPreferences,
    SpeechInputSignals,
    signals_from_capability,
)
from .recognizer import (
    RecognitionSession,
    RecognizerDeclaration,
    RecognizerHealth,
    RecognizerRegistry,
    RecognizerResourceEstimate,
    RecognizerSelection,
    SpeechRecognizer,
)
from .recognizers import MODEL_DIRECTORIES, VoskRecognizer, local_recognizers
from .recovery import (
    CAPTURE_DISPOSITIONS,
    SpeechJournal,
    SpeechRecoveryReport,
    recover,
    sweep_workspaces,
)
from .request import (
    ACTIVATION_SOURCES,
    MAX_CAPTURE_SECONDS,
    MAX_TRANSCRIPT_CHARACTERS,
    SpeechInputRequest,
    SpeechInputRequestError,
    transcript_digest,
)
from .service import (
    ACTIVATION_LIFETIME_SECONDS,
    SpeechInputService,
    SpeechInputServiceOptions,
)
from .transcript import (
    FinalTranscript,
    PartialTranscript,
    TranscriptError,
    bounded_transcript_text,
    pango_escaped,
)
from .worker import (
    CaptureMeasurement,
    CaptureOutcome,
    CaptureSession,
    CaptureWorker,
    MAX_PARTIALS_PER_CAPTURE,
)
from .wakeword import WakeWordService, WakeWordState

__all__ = [
    # Request and transcripts
    "ACTIVATION_SOURCES",
    "MAX_CAPTURE_SECONDS",
    "MAX_TRANSCRIPT_CHARACTERS",
    "SpeechInputRequest",
    "SpeechInputRequestError",
    "transcript_digest",
    "FinalTranscript",
    "PartialTranscript",
    "TranscriptError",
    "bounded_transcript_text",
    "pango_escaped",
    # Capture
    "AlsaCaptureBackend",
    "BoundedFrameBuffer",
    "CAPTURE_DEGRADATION_KINDS",
    "CAPTURE_EXECUTABLES",
    "CaptureBackendHealth",
    "CaptureChild",
    "CaptureDegradation",
    "CaptureDevice",
    "CaptureHandle",
    "CaptureRouter",
    "PipeWireCaptureBackend",
    "PulseAudioCaptureBackend",
    "RecorderContract",
    "SpeechWorkspace",
    "local_capture_backends",
    "resolve_capture_executable",
    # Activity
    "ActivityState",
    "SpeechActivityDetector",
    # Recognition
    "MODEL_DIRECTORIES",
    "RecognitionSession",
    "RecognizerDeclaration",
    "RecognizerHealth",
    "RecognizerRegistry",
    "RecognizerResourceEstimate",
    "RecognizerSelection",
    "SpeechRecognizer",
    "VoskRecognizer",
    "WakeWordService",
    "WakeWordState",
    "local_recognizers",
    # Policy, indicator, events
    "SPEECH_EVENT_KINDS",
    "SPEECH_INPUT_OUTCOMES",
    "SpeechInputDecision",
    "SpeechInputEvent",
    "SpeechInputPolicy",
    "SpeechInputPreferences",
    "SpeechInputSignals",
    "signals_from_capability",
    "IndicatorSink",
    "IndicatorState",
    "ListeningIndicator",
    # Confirmation and coordination
    "ConfirmationLedger",
    "ConfirmedSubmission",
    "PendingTranscript",
    "CoordinationRecord",
    "VoiceOutputCoordinator",
    # Worker, recovery, service
    "CAPTURE_DISPOSITIONS",
    "CaptureMeasurement",
    "CaptureOutcome",
    "CaptureSession",
    "CaptureWorker",
    "MAX_PARTIALS_PER_CAPTURE",
    "SpeechJournal",
    "SpeechRecoveryReport",
    "recover",
    "sweep_workspaces",
    "ACTIVATION_LIFETIME_SECONDS",
    "SpeechInputService",
    "SpeechInputServiceOptions",
]
