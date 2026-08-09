# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The speech-input runtime assembled, and the eight things a client may ask it.

The §18-shaped decision the voice runtime already argued applies with more
force here, because the resource at stake is a microphone: speech input runs
**inside the canonical companion service, as an isolated subsystem with no
persistent thread**. A separate user service would put a socket between "the
user pressed stop" and the ``SIGTERM`` that releases the device, and would be
one accidental operation away from a second thing that can open a microphone.
Inside the service, the object graph is the boundary: this class holds no
runtime, no store, no session and no approval object, and the one place a
confirmed transcript crosses into task authority is the gateway, which calls
:meth:`confirm_transcript` and performs the submission itself with the runtime
only it holds.

The operations are §20's eight and are validated against
:data:`companion.protocol.SPEECH_OPERATIONS` — the same objects the protocol
validates a client against, so the two cannot drift. Note what none of them
takes: no executable, no model path, no recording destination, no raw-audio
retrieval, no URL, no arbitrary device command. ``speech_input_start`` does
not even take free text — every string it accepts is validated against a
closed set or a bounded identifier shape in
:class:`companion.speech.request.SpeechInputRequest`.

§4's "no microphone initialisation during service startup" is a property of
construction: building this service builds a router, a registry, a policy, an
indicator, a ledger and a *constructed* worker — objects, no threads, no
devices, no model load. The §21 recovery pass runs here, before any capture
can exist, so a workspace left by a crash is swept while nothing could be
using one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import threading
from typing import Any, Callable, Mapping

from ..clock import Clock, SystemClock
from ..ids import IdSource, RandomIds
from ..protocol import SPEECH_OPERATIONS, ProtocolError
from .capture import CaptureRouter
from .confirmation import ConfirmationLedger, ConfirmedSubmission
from .coordination import VoiceOutputCoordinator
from .events import SpeechInputEvent
from .indicator import IndicatorSink, ListeningIndicator
from .policy import (
    SpeechInputPolicy,
    SpeechInputPreferences,
    signals_from_capability,
)
from .recognizer import RecognizerRegistry
from .recognizers import local_recognizers
from .recovery import SpeechJournal, SpeechRecoveryReport, recover
from .request import (
    ACTIVATION_SOURCES,
    SpeechInputRequest,
    SpeechInputRequestError,
)
from .worker import CaptureWorker

__all__ = [
    "ACTIVATION_LIFETIME_SECONDS",
    "SpeechInputService",
    "SpeechInputServiceOptions",
]

#: How long an explicit activation remains valid before the capture must have
#: begun. An activation is a moment; ten seconds is generous for a loaded
#: machine and far too short for a stored one to be replayed usefully.
ACTIVATION_LIFETIME_SECONDS = 10.0


@dataclass
class SpeechInputServiceOptions:
    """How one speech-input runtime is put together."""

    runtime_directory: Path | None = None
    preferences: SpeechInputPreferences = field(default_factory=SpeechInputPreferences)
    clock: Clock = field(default_factory=SystemClock)
    ids: IdSource = field(default_factory=RandomIds)
    #: Injected so tests present backends and recognisers that are missing,
    #: hostile or slow without installing any. Production passes nothing.
    router: CaptureRouter | None = None
    registry: RecognizerRegistry | None = None
    indicator: ListeningIndicator | None = None
    #: The voice worker to coordinate output speech with, or ``None`` for a
    #: service running without voice. Only the coordinator ever holds it.
    voice_worker: Any = None


class SpeechInputService:
    """One speech-input runtime: capture, recognition, policy, indicator, ledger.

    Restartable without the companion runtime noticing:
    :meth:`restart_worker` closes the capture worker and builds a new one over
    the same policy, router and ledger, which is §2's requirement expressed as
    a method.
    """

    def __init__(self, options: SpeechInputServiceOptions | None = None) -> None:
        self.options = options or SpeechInputServiceOptions()
        self.clock = self.options.clock
        self.ids = self.options.ids
        # ``is None`` throughout, for the reason every companion service spells
        # it: these classes define ``__len__``, and ``or`` would replace a
        # deliberately-empty test registry with the host's real one.
        self.router = (
            CaptureRouter() if self.options.router is None else self.options.router
        )
        self.registry = (
            local_recognizers(preferred_model_id=self.options.preferences.model_id)
            if self.options.registry is None else self.options.registry
        )
        self.indicator = (
            ListeningIndicator(clock=self.clock)
            if self.options.indicator is None else self.options.indicator
        )
        self.policy = SpeechInputPolicy(self.options.preferences)
        self.ledger = ConfirmationLedger(clock=self.clock)
        self.coordinator = VoiceOutputCoordinator(self.options.voice_worker)

        directory = self.options.runtime_directory
        if directory is None:
            from ..protocol import default_runtime_directory

            directory = default_runtime_directory()
        self.runtime_directory = Path(directory)
        self.journal = SpeechJournal(self.runtime_directory / "speech-journal.jsonl")

        # §21 runs before any worker exists. A capture that began while
        # recovery was deciding what the last one had done could write a start
        # line the reconciliation then reads as abandoned.
        self.recovery: SpeechRecoveryReport = recover(self.journal, own_pid=None)

        self.worker = self._build_worker()
        self._guard = threading.RLock()
        self._closed = False
        self._requests: dict[str, SpeechInputRequest] = {}
        self._submission_hook: Callable[[ConfirmedSubmission], str] | None = None
        self.refresh()
        self.worker.subscribe(self._on_worker_event)

    def _build_worker(self) -> CaptureWorker:
        return CaptureWorker(
            router=self.router,
            registry=self.registry,
            policy=self.policy,
            indicator=self.indicator,
            ledger=self.ledger,
            coordinator=self.coordinator,
            journal=self.journal,
            clock=self.clock,
        )

    # ----------------------------------------------------------------- #
    # Lifecycle
    # ----------------------------------------------------------------- #

    def refresh(
        self,
        *,
        capability_signals: Mapping[str, Any] | None = None,
        foreground_workload: int = 0,
        plan_id: str = "",
    ) -> None:
        """Take a fresh reading and let the policy move, with hysteresis.

        Called between captures, never during one: probing an audio server
        mid-capture would put a subprocess into the path §25 measures.
        """
        now = self.clock.monotonic()
        healths = self.router.observe()
        capture_available = any(item.ready for item in healths)
        recognizer_healths = self.registry.health(monotonic=now)
        recognizer_available = any(item.ready for item in recognizer_healths)
        streaming_available = any(
            health.ready and recognizer.declaration.supports_streaming
            for health, recognizer in zip(recognizer_healths, self.registry)
        )
        model_memory = 0
        for health, recognizer in zip(recognizer_healths, self.registry):
            if health.ready and recognizer.declaration.resource_estimate is not None:
                model_memory = recognizer.declaration.resource_estimate.model_memory_bytes
                break
        signals = signals_from_capability(
            capability_signals or {},
            capture_device_available=capture_available,
            recognizer_available=recognizer_available,
            streaming_recognizer_available=streaming_available,
            model_memory_bytes=model_memory,
            foreground_workload=foreground_workload,
            plan_id=plan_id,
        )
        if self.options.preferences.input_device:
            self.router.prefer_device(self.options.preferences.input_device)
        self.policy.observe(signals, monotonic=now)

    def set_preferences(self, preferences: SpeechInputPreferences) -> None:
        # Turning Voice Input off is an immediate privacy boundary, not a
        # preference for the next capture. Release an active microphone before
        # publishing the disabled policy.
        if not preferences.enabled:
            current = self.worker.status().get("current")
            if isinstance(current, Mapping):
                request_id = str(current.get("requestId") or "")
                request = self._requests.get(request_id)
                self.worker.cancel(
                    request_id,
                    token=request.cancellation_token if request is not None else "",
                )
        self.options.preferences = preferences
        self.policy.set_preferences(preferences)
        self.router.prefer_device(preferences.input_device)
        self.refresh()

    def set_submission_hook(self, hook: Callable[[ConfirmedSubmission], str]) -> None:
        """How an immediate-mode transcript becomes a task: through the gateway.

        The hook is set by the gateway at construction and receives a
        :class:`ConfirmedSubmission`; it returns the created task id. The
        speech service never sees a runtime — it sees one callable whose whole
        contract is "submit this confirmed text".
        """
        with self._guard:
            self._submission_hook = hook

    def attach_indicator_sink(self, sink: IndicatorSink) -> None:
        self.indicator.attach(sink)

    def restart_worker(self, *, timeout: float = 10.0) -> SpeechRecoveryReport:
        """§2: restart capture without restarting or cancelling anything else.

        The companion runtime is not touched — this object has no reference to
        one. An in-flight capture is cancelled and recorded; the new worker
        starts with nothing in flight, because §21 forbids resuming it.
        """
        self.worker.close(timeout=timeout)
        report = self.journal.reconcile(own_pid=None)
        self.journal.truncate()
        self.worker = self._build_worker()
        self.worker.subscribe(self._on_worker_event)
        return report

    def close(self) -> None:
        """Stop and release. Safe to call twice and safe after a fault."""
        with self._guard:
            if self._closed:
                return
            self._closed = True
        self.worker.close()
        self.registry.close()
        self.router.close()

    def __enter__(self) -> "SpeechInputService":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # ----------------------------------------------------------------- #
    # Immediate submission, through the gateway's hook
    # ----------------------------------------------------------------- #

    def _on_worker_event(self, event: SpeechInputEvent) -> None:
        if event.kind != "final_transcript":
            return
        if not dict(event.payload).get("immediateSubmission"):
            return
        with self._guard:
            hook = self._submission_hook
        if hook is None:
            # No gateway attached: the transcript stays in the ledger waiting
            # for an explicit confirmation, which is the safe direction.
            return
        submission, reason = self.ledger.confirm(
            event.request_id,
            session_id=event.session_id,
            cancellation_token=self._token_for(event.request_id),
            confirmed_by="immediate-preference",
        )
        if submission is None:
            self.worker.emit_external(
                "transcript_rejected",
                request_id=event.request_id,
                session_id=event.session_id,
                payload={"detail": reason, "taskCreated": False},
            )
            return
        try:
            task_id = hook(submission)
        except Exception as exc:  # noqa: BLE001 - a submission fault is reported, not raised
            self.worker.emit_external(
                "transcript_rejected",
                request_id=event.request_id,
                session_id=event.session_id,
                payload={
                    "detail": f"the submission failed: {type(exc).__name__}",
                    "taskCreated": False,
                },
            )
            return
        self.record_submitted(
            event.request_id, event.session_id, task_id,
            confirmed_by="immediate-preference",
        )

    def _token_for(self, request_id: str) -> str:
        with self._guard:
            request = self._requests.get(request_id)
        return request.cancellation_token if request is not None else ""

    # ----------------------------------------------------------------- #
    # The confirmation seam the gateway drives
    # ----------------------------------------------------------------- #

    def confirm_transcript(
        self,
        request_id: str,
        *,
        session_id: str,
        text: str | None = None,
        reviewed_digest: str = "",
        cancellation_token: str = "",
    ) -> tuple[ConfirmedSubmission | None, str]:
        """Validate one confirmation and hand back what may be submitted.

        The gateway calls this, then performs the task submission itself, then
        calls :meth:`record_submitted`. Nothing here can submit — the method's
        return type is the entire path from a transcript to a task.
        """
        return self.ledger.confirm(
            request_id,
            session_id=session_id,
            text=text,
            reviewed_digest=reviewed_digest,
            cancellation_token=cancellation_token,
            confirmed_by="user",
        )

    def record_submitted(
        self,
        request_id: str,
        session_id: str,
        task_id: str,
        *,
        confirmed_by: str = "user",
    ) -> None:
        entry = self.ledger.get(request_id)
        self.worker.emit_external(
            "transcript_confirmed",
            request_id=request_id,
            session_id=session_id,
            payload={
                "taskId": task_id,
                "confirmedBy": confirmed_by,
                "userEdited": bool(
                    entry is not None and entry.transcript.user_edited
                ),
                "taskCreated": bool(task_id),
            },
        )

    def reject_transcript(
        self,
        request_id: str,
        *,
        session_id: str = "",
        cancellation_token: str = "",
        reason: str = "rejected by the user",
    ) -> tuple[bool, str]:
        rejected, detail = self.ledger.reject(
            request_id,
            session_id=session_id,
            cancellation_token=cancellation_token,
            reason=reason,
        )
        if rejected:
            self.worker.emit_external(
                "transcript_rejected",
                request_id=request_id,
                session_id=session_id,
                payload={"detail": reason, "taskCreated": False},
            )
        return rejected, detail

    # ----------------------------------------------------------------- #
    # Operations
    # ----------------------------------------------------------------- #

    def dispatch(self, name: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Validate and serve one operation. The only generic entry point."""
        operation = SPEECH_OPERATIONS.get(name)
        if operation is None:
            raise ProtocolError(f"unknown speech-input operation: {name!r}")
        resolved = operation.validate(params or {})
        handler = getattr(self, name, None)
        if handler is None:  # pragma: no cover - the table and the methods agree
            raise ProtocolError(f"{name} is declared and not implemented")
        return handler(**resolved)

    def speech_input_health(self) -> dict[str, Any]:
        """Everything about whether this machine can listen, and why not."""
        now = self.clock.monotonic()
        return {
            "recognizers": [
                {
                    **recognizer.declaration.to_json(),
                    **recognizer.health(monotonic=now).to_json(),
                }
                for recognizer in self.registry
            ],
            "capture": self.router.describe(),
            "policy": self.policy.describe(),
            "indicator": self.indicator.describe(),
            "confirmation": self.ledger.describe(),
            "coordination": self.coordinator.describe(),
            "recovery": self.recovery.to_json(),
            "operations": sorted(SPEECH_OPERATIONS),
            "activationSources": list(ACTIVATION_SOURCES),
            "boundaries": self.boundaries(),
        }

    def speech_input_devices(self) -> dict[str, Any]:
        """The capture devices this machine presents, labelled as what they are."""
        devices: list[dict[str, Any]] = []
        for backend in self.router.backends:
            try:
                if not backend.health(monotonic=self.clock.monotonic()).ready:
                    continue
                for device in backend.discover():
                    devices.append(device.to_json())
            except Exception:  # noqa: BLE001 - an inventory must never break a list
                continue
        return {
            "devices": devices[:64],
            "total": len(devices),
            "preferredDevice": self.router.preferred_device,
            "monitorSourcesSelectable": False,
            "physicalMicrophoneValidated": False,
        }

    def speech_input_start(
        self,
        *,
        sessionId: str,
        activationSource: str,
        language: str = "",
        locale: str = "",
        deviceId: str = "",
        providerId: str = "",
        maxCaptureMs: int = 30_000,
        initialSilenceMs: int = 6_000,
        endpointSilenceMs: int = 1_200,
        partialTranscripts: bool = True,
        confirmationRequired: bool = True,
        presentationRevision: int = 0,
    ) -> dict[str, Any]:
        preferences = self.options.preferences
        now = self.clock.monotonic()
        try:
            request = SpeechInputRequest(
                request_id=self.ids.next("speechreq"),
                session_id=sessionId,
                activation_source=activationSource,
                created_at_wall=self.clock.wall(),
                created_at_monotonic=now,
                expires_at_monotonic=now + ACTIVATION_LIFETIME_SECONDS,
                language=language or preferences.language,
                locale=locale or preferences.locale,
                provider_preference=providerId or preferences.provider_preference,
                device_preference=deviceId or preferences.input_device,
                maximum_capture_seconds=maxCaptureMs / 1000.0,
                initial_silence_seconds=initialSilenceMs / 1000.0,
                endpoint_silence_seconds=endpointSilenceMs / 1000.0,
                partial_transcripts=bool(partialTranscripts and preferences.partial_transcripts),
                confirmation_required=confirmationRequired,
                cancellation_token=self.ids.next("speechtok"),
                presentation_revision=presentationRevision,
            )
        except SpeechInputRequestError as exc:
            raise ProtocolError(str(exc)) from exc
        with self._guard:
            self._requests[request.request_id] = request
            if len(self._requests) > 32:
                for key in list(self._requests)[:8]:
                    self._requests.pop(key, None)
        outcome = self.worker.start_capture(request)
        return outcome.to_json()

    def speech_input_status(self) -> dict[str, Any]:
        status = self.worker.status()
        status["confirmation"] = self.ledger.describe()
        status["recentEvents"] = [item.to_json() for item in self.worker.events(limit=32)]
        return status

    def speech_input_stop(self, *, requestId: str) -> dict[str, Any]:
        stopped, reason = self.worker.stop_capture(requestId)
        return {
            "stopped": stopped,
            "reason": reason,
            "recognitionContinues": stopped,
            "taskAffected": False,
        }

    def speech_input_cancel(
        self, *, requestId: str, cancellationToken: str = ""
    ) -> dict[str, Any]:
        cancelled, reason = self.worker.cancel(requestId, token=cancellationToken)
        if cancelled:
            return {
                "cancelled": True,
                "stage": "capture",
                "reason": "",
                "taskCreated": False,
            }
        # §16: cancel after the final transcript and before confirmation. The
        # capture is gone; what remains cancellable is the waiting transcript.
        entry = self.ledger.get(requestId)
        if entry is not None and entry.state == "pending":
            rejected, detail = self.reject_transcript(
                requestId,
                session_id=entry.transcript.session_id,
                cancellation_token=cancellationToken,
                reason="cancelled before confirmation",
            )
            return {
                "cancelled": rejected,
                "stage": "confirmation",
                "reason": detail,
                "taskCreated": False,
            }
        return {
            # Idempotent by construction: a second cancel finds nothing and
            # reports so, which §16's duplicate-cancellation test asserts is
            # not an error.
            "cancelled": False,
            "stage": "none",
            "reason": reason,
            "taskCreated": False,
        }

    def speech_input_retry(
        self, *, requestId: str, activationSource: str
    ) -> dict[str, Any]:
        """Discard what is waiting and capture again. An explicit act (§21).

        The retry names the activation the user just performed — pressing
        "retry" *is* push-to-talk with a different label — and the superseded
        transcript can no longer be confirmed, which is §16's stale-final
        refusal built into the flow.
        """
        with self._guard:
            original = self._requests.get(requestId)
        if original is None:
            raise ProtocolError(
                f"no capture is known as {requestId!r}; a retry continues a "
                "capture this service performed"
            )
        self.ledger.supersede(requestId, reason="the user asked for another take")
        return self.speech_input_start(
            sessionId=original.session_id,
            activationSource=activationSource,
            language=original.language,
            locale=original.locale,
            deviceId=original.device_preference,
            providerId=original.provider_preference,
            maxCaptureMs=int(original.maximum_capture_seconds * 1000),
            initialSilenceMs=int(original.initial_silence_seconds * 1000),
            endpointSilenceMs=int(original.endpoint_silence_seconds * 1000),
            partialTranscripts=original.partial_transcripts,
            confirmationRequired=original.confirmation_required,
            presentationRevision=original.presentation_revision,
        )

    # ----------------------------------------------------------------- #

    def boundaries(self) -> dict[str, Any]:
        """The claims this phase makes, in a form a gate can assert on."""
        return {
            "explicitActivationOnly": True,
            "microphoneAtServiceStartup": False,
            "indicatorBeforeOpen": True,
            "indicatorClearedAfterClose": True,
            "wakeWordSupported": False,
            "continuousListeningSupported": False,
            "backgroundRecordingSupported": False,
            "remoteRecognitionConfigured": False,
            "remoteTransmissionPermitted": False,
            "voiceBiometricsSupported": False,
            "speakerIdentificationSupported": False,
            "voiceCloningSupported": False,
            "rawAudioRetainedByDefault": False,
            "rawAudioInTaskHistory": False,
            "confirmationRequiredByDefault": True,
            "immediateSubmissionDefault": False,
            "speechInputMayCreateTask": False,
            "speechInputMayResolveApprovals": False,
            "speechInputMayExecuteTools": False,
            "speechInputMaySelectExecutor": False,
            "speechInputMayChangeTaskState": False,
            "localIncapabilityAuthorisesRemote": False,
            "captureResumesAfterRestart": False,
        }

    def describe(self) -> dict[str, Any]:
        return {
            "runtimeDirectory": str(self.runtime_directory),
            "capturing": self.worker.active,
            "integration": {
                "mode": "in-process subsystem, no persistent thread",
                "separateUserService": False,
                "microphoneInitialisedAtStartup": False,
            },
            "health": self.speech_input_health(),
        }
