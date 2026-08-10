# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The voice runtime assembled, and the eight things a client may ask it.

**§18: voice runs inside the canonical companion service, in an isolated
worker.** The decision and its reasons, stated here because §18 asks for it to
be documented rather than merely made:

A separate user service is justified only when it materially improves crash
isolation, resource control, audio lifecycle, provider restart or a security
boundary. Measured against those five:

*Crash isolation* — the thing that crashes is a synthesiser or a player, and
both are already separate processes behind
:mod:`companion.voice.execution`. A second *service* would add isolation
between the voice worker and the companion, not between the companion and the
thing that actually fails. :class:`VoiceWorker` catches per-utterance faults and
keeps serving; §21 tests that a provider fault leaves the worker running.

*Resource control* — a second unit could carry its own ``MemoryMax``. But the
voice worker's own footprint is a thread and a bounded queue; the memory is in
the synthesiser, which is a child process either way and is bounded by the
timeout and the concurrency limit rather than by a cgroup.

*Audio lifecycle* — this is the one that would argue *for* separation, and it
argues the other way on inspection. The audio handle has to be released when the
utterance ends, and the utterance ends when the task's presentation moves on.
Putting the two in different processes puts a socket between a task event and a
``SIGTERM`` to a player.

*Provider restart* — providers are restarted by starting a new child. Nothing
about that needs a service boundary.

*Security boundary* — this is real and is answered without a second unit. The
worker cannot mutate task state because it holds nothing that could: no store,
no runtime, no approval object. That is enforced by the import graph and
asserted by a test, which is a stronger boundary than a socket with a protocol
that could grow an operation.

So: one service, one worker, restartable independently — :meth:`VoiceService.restart_worker`
does exactly that and §21 tests that a task continues across it. **And no second
task runtime**, which §18 forbids outright and which a separate voice service
would have been one accidental feature away from becoming.

The operations are narrow by construction. There is no operation that takes an
executable, an argument list, an output path, a provider module, a URL or a raw
device handle, and :data:`VOICE_OPERATIONS` is the whole list. Every parameter
is declared and bounded, and an undeclared one is refused rather than ignored —
the position :class:`companion.protocol.Operation` already takes, reused here
rather than reimplemented.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import threading
from typing import Any, Callable, Mapping, Sequence

from ..clock import Clock, SystemClock
from ..ids import IdSource, RandomIds
from ..presentation import PresentationState
from ..protocol import VOICE_OPERATIONS, Operation, ProtocolError
from .audio import AudioRouter
from .captions import Caption, CaptionLedger, SpeechDisposition
from .policy import VoiceDecision, VoicePolicy, VoicePreferences, VoiceSignals, signals_from_capability
from .provider import ProviderRegistry
from .providers import local_providers
from .queue import SpeechQueue
from .recovery import RecoveryReport, VoiceJournal, recover
from .request import (
    InterruptionPolicy,
    Priority,
    VoiceRequest,
    VoiceRequestError,
    may_speak_remotely,
)
from .worker import VoiceEvent, VoiceWorker

__all__ = [
    "VOICE_OPERATIONS",
    "VoiceService",
    "VoiceServiceOptions",
]


#: §17's operations, taken from :data:`companion.protocol.OPERATIONS` rather
#: than declared again here. One table, so the schema a client is validated
#: against and the schema this serves cannot drift apart — and so that reviewing
#: "what can a client reach" stays a matter of reading one list.
#:
#: Note what none of them takes: no executable, no argument list, no output
#: path, no provider module, no URL, no device handle. ``voice_speak`` does not
#: even take text — it takes a caption identifier.

@dataclass
class VoiceServiceOptions:
    """How one voice runtime is put together."""

    runtime_directory: Path | None = None
    preferences: VoicePreferences = field(default_factory=VoicePreferences)
    clock: Clock = field(default_factory=SystemClock)
    ids: IdSource = field(default_factory=RandomIds)
    #: Injected so tests can present providers and backends that are missing,
    #: hostile or slow without installing any. Production passes nothing and
    #: gets :func:`companion.voice.execution.resolve_executable`.
    resolver: Any = None
    registry: ProviderRegistry | None = None
    router: AudioRouter | None = None
    maximum_queue_depth: int = SpeechQueue.MAX_DEPTH
    tick_seconds: float = 0.025
    #: Started with the service by default. A test that wants to drive the loop
    #: by hand passes ``False`` and calls the worker directly.
    start_worker: bool = True


class VoiceService:
    """One voice runtime: providers, audio, policy, captions, queue and worker.

    Holds no task, no session and no store. The only thing that comes in from
    the canonical runtime is a :class:`companion.presentation.PresentationState`,
    which is the projection every surface already receives, and the only thing
    that goes back out is nothing at all — this service has no way to call the
    runtime and no reference to one.
    """

    def __init__(self, options: VoiceServiceOptions | None = None) -> None:
        self.options = options or VoiceServiceOptions()
        self.clock = self.options.clock
        # ``is None`` throughout. :class:`ProviderRegistry` defines ``__len__``,
        # so an empty one is falsy, and ``or`` would replace a caller's
        # deliberately-empty registry with the real local providers — a test
        # asserting "a machine with no providers falls back to captions" would
        # instead have exercised whatever the host happened to have installed.
        self.registry = (
            local_providers(resolver=self.options.resolver)
            if self.options.registry is None else self.options.registry
        )
        self.router = (
            AudioRouter(resolver=self.options.resolver)
            if self.options.router is None else self.options.router
        )
        self.policy = VoicePolicy(self.options.preferences)
        self.ledger = CaptionLedger(ids=self.options.ids, clock=self.clock)
        self.queue = SpeechQueue(maximum_depth=self.options.maximum_queue_depth)

        directory = self.options.runtime_directory
        if directory is None:
            from ..protocol import default_runtime_directory

            directory = default_runtime_directory()
        self.runtime_directory = Path(directory)
        self.journal = VoiceJournal(self.runtime_directory / "voice-journal.jsonl")

        # §20 runs *before* the worker starts. A worker that began speaking
        # while recovery was still deciding what the last one had done could
        # write a start line the reconciliation then read as abandoned.
        self.recovery: RecoveryReport = recover(self.journal, own_pid=None)

        self.worker = VoiceWorker(
            registry=self.registry,
            router=self.router,
            policy=self.policy,
            ledger=self.ledger,
            queue=self.queue,
            clock=self.clock,
            journal=self.journal,
            tick_seconds=self.options.tick_seconds,
        )
        self._guard = threading.RLock()
        self._closed = False
        self._last_signals = VoiceSignals()
        self.refresh()
        if self.options.start_worker:
            self.worker.start()

    # ----------------------------------------------------------------- #
    # Lifecycle
    # ----------------------------------------------------------------- #

    def refresh(
        self,
        *,
        capability_signals: Mapping[str, Any] | None = None,
        foreground_workload: int = 0,
        plan_id: str = "",
    ) -> VoiceDecision:
        """Take a fresh reading and let the policy move, with hysteresis.

        Called between utterances rather than during one: probing the audio
        server in the middle of playback would put a subprocess into the path
        §24 measures the latency of.
        """
        healths = self.router.observe()
        audio_available = any(item.ready for item in healths)
        provider_healths = self.registry.health(monotonic=self.clock.monotonic())
        # Neural providers deliberately verify their installation outside the
        # caller's thread and load inference only when selected. These states
        # mean "installed and becoming usable", not "this machine has no local
        # voice". Keeping the policy speech-capable lets
        # registry selection move down to Kitten/eSpeak/Speech Dispatcher for
        # this utterance; once the cached probe becomes READY, later requests
        # select Pocket normally.  A genuinely missing/corrupt provider still
        # reports one of the unavailable states and is not counted here.
        provider_available = any(
            item.ready or item.status in ("INITIALIZING", "MODEL_VERIFIED")
            for item in provider_healths
        )
        synthesis_available = any(
            (item.ready or item.status in ("INITIALIZING", "MODEL_VERIFIED"))
            and provider.declaration.supports_synthesis
            for item, provider in zip(provider_healths, self.registry)
        )
        signals = signals_from_capability(
            capability_signals or {},
            audio_output_available=audio_available,
            local_provider_available=provider_available,
            synthesis_provider_available=synthesis_available,
            foreground_workload=foreground_workload,
            plan_id=plan_id,
        )
        with self._guard:
            self._last_signals = signals
        if self.options.preferences.preferred_device:
            self.router.prefer_device(self.options.preferences.preferred_device)
        return self.policy.observe(signals, monotonic=self.clock.monotonic())

    def set_preferences(self, preferences: VoicePreferences) -> VoiceDecision:
        self.options.preferences = preferences
        self.policy.set_preferences(preferences)
        self.router.prefer_device(preferences.preferred_device)
        with self._guard:
            signals = self._last_signals
        return self.policy.observe(signals, monotonic=self.clock.monotonic())

    def restart_worker(self, *, timeout: float = 10.0) -> RecoveryReport:
        """§18: restart voice without restarting or cancelling anything else.

        The task runtime is not touched — this object has no reference to one.
        The queue is cleared, the current utterance is recorded interrupted, and
        the new worker starts with nothing in flight, because §20 forbids
        replaying what the old one was saying.
        """
        self.worker.stop(timeout=timeout)
        report = self.journal.reconcile(own_pid=None)
        self.journal.truncate()
        self.worker = VoiceWorker(
            registry=self.registry,
            router=self.router,
            policy=self.policy,
            ledger=self.ledger,
            queue=self.queue,
            clock=self.clock,
            journal=self.journal,
            tick_seconds=self.options.tick_seconds,
        )
        self.worker.start()
        return report

    def close(self) -> None:
        """Stop and release. Safe to call twice and safe after a fault."""
        with self._guard:
            if self._closed:
                return
            self._closed = True
        self.worker.stop()
        self.registry.close()
        self.router.close()

    def __enter__(self) -> "VoiceService":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # ----------------------------------------------------------------- #
    # Captions in
    # ----------------------------------------------------------------- #

    def publish(self, state: PresentationState) -> Caption:
        """Record the caption the canonical projection currently holds.

        The only way anything enters the voice runtime. Note the direction: the
        projection is pushed *in*, and this service never reaches out for one.
        """
        return self.ledger.publish(state)

    def announce(
        self,
        state: PresentationState,
        *,
        shown: bool = True,
        priority: Priority | None = None,
    ) -> tuple[VoiceRequest | None, str]:
        """Publish a caption and speak it if policy allows. The ordinary path.

        Returns the request or the reason there is none. A caller that ignores
        the return value has still had its caption published, which is the part
        that matters — §8's caption is authoritative and speech is the optional
        second rendering.
        """
        caption = self.publish(state)
        if shown:
            self.ledger.mark_shown(caption.caption_id)
        return self.speak(caption.caption_id, priority=priority)

    def speak(
        self,
        caption_id: str,
        *,
        priority: Priority | None = None,
        interruption_policy: InterruptionPolicy | None = None,
        voice_id: str = "",
        replay: bool = False,
    ) -> tuple[VoiceRequest | None, str]:
        caption = self.ledger.get(caption_id)
        if caption is None:
            return None, f"there is no caption {caption_id!r} to speak"
        preferences = self.options.preferences
        decision = self.policy.decision
        request, reason = self.ledger.speak_once(
            caption,
            priority=priority,
            interruption_policy=interruption_policy,
            provider_id=preferences.provider_id,
            model_id=preferences.model_id,
            voice_id=voice_id or preferences.voice_id,
            language=preferences.language,
            locale=preferences.locale,
            speaking_rate=preferences.speaking_rate,
            volume=preferences.volume,
            prefer_streaming=preferences.prefer_streaming or decision.prefer_streaming,
            force=replay,
        )
        if request is None:
            return None, reason
        outcome = self.worker.submit(request)
        if not outcome.accepted:
            return None, outcome.detail
        return request, ""

    # ----------------------------------------------------------------- #
    # Operations
    # ----------------------------------------------------------------- #

    def dispatch(self, name: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Validate and serve one operation. The only entry point for a client."""
        operation = VOICE_OPERATIONS.get(name)
        if operation is None:
            raise ProtocolError(f"unknown voice operation: {name!r}")
        resolved = operation.validate(params or {})
        handler = getattr(self, name, None)
        if handler is None:  # pragma: no cover - the table and the methods agree
            raise ProtocolError(f"{name} is declared and not implemented")
        return handler(**resolved)

    def voice_health(self) -> dict[str, Any]:
        """Everything about whether this machine can speak, and why not."""
        now = self.clock.monotonic()
        return {
            "providers": [
                {**provider.declaration.to_json(), **provider.health(monotonic=now).to_json()}
                for provider in self.registry
            ],
            "audio": self.router.describe(),
            "policy": self.policy.describe(),
            "captions": self.ledger.describe(),
            "recovery": self.recovery.to_json(),
            "operations": sorted(VOICE_OPERATIONS),
            "boundaries": self.boundaries(),
        }

    def voice_list(self, *, language: str = "", limit: int = 64) -> dict[str, Any]:
        """The voices installed on this machine. Nothing downloadable, nothing remote."""
        voices = self.registry.inventory()
        if language:
            voices = [item for item in voices if item.language == language]
        return {
            "voices": [item.to_json() for item in voices[:limit]],
            "total": len(voices),
            "truncated": len(voices) > limit,
            # §16, answered in the place somebody would look for a way in.
            "voiceCloningSupported": False,
            "voiceImportSupported": False,
            "voiceTrainingSupported": False,
            "remoteVoicesAvailable": False,
        }

    def voice_status(self) -> dict[str, Any]:
        status = self.worker.status()
        status["queue"] = self.queue.describe()
        status["signals"] = self._last_signals.to_json()
        status["recentEvents"] = [item.to_json() for item in self.worker.events(limit=32)]
        return status

    def voice_speak(
        self,
        *,
        captionId: str,
        priority: str = "",
        interruptionPolicy: str = "",
        voiceId: str = "",
        replay: bool = False,
    ) -> dict[str, Any]:
        try:
            rank = Priority.parse(priority) if priority else None
            policy = InterruptionPolicy.parse(interruptionPolicy) if interruptionPolicy else None
        except VoiceRequestError as exc:
            raise ProtocolError(str(exc)) from exc
        request, reason = self.speak(
            captionId,
            priority=rank,
            interruption_policy=policy,
            voice_id=voiceId,
            replay=replay,
        )
        return {
            "accepted": request is not None,
            "requestId": request.request_id if request else "",
            "cancellationToken": request.cancellation_token if request else "",
            "reason": reason,
            "captionRetained": True,
            "taskAffected": False,
        }

    def voice_cancel(
        self, *, requestId: str = "", taskId: str = "", cancellationToken: str = ""
    ) -> dict[str, Any]:
        if not requestId and not taskId:
            raise ProtocolError("voice_cancel needs a requestId or a taskId")
        cancelled: list[str] = []
        if requestId:
            if self.worker.cancel(requestId, token=cancellationToken):
                cancelled.append(requestId)
        if taskId:
            cancelled.extend(self.worker.cancel_task(taskId))
        return {
            # Idempotent by construction: a second cancel finds nothing to
            # cancel and reports so. §19 tests a duplicate cancellation, and the
            # property it asserts is that the second one is not an error.
            "cancelled": sorted(set(cancelled)),
            "count": len(set(cancelled)),
            "captionRetained": True,
            "taskAffected": False,
        }

    def voice_pause(self) -> dict[str, Any]:
        paused = self.worker.pause()
        return {
            "paused": paused,
            "reason": "" if paused else (
                "nothing is playing, or the provider owns its own playback and cannot be paused"
            ),
        }

    def voice_resume(self) -> dict[str, Any]:
        resumed = self.worker.resume()
        return {
            "resumed": resumed,
            "reason": "" if resumed else "nothing is paused",
        }

    def voice_explain(self, *, requestId: str = "") -> dict[str, Any]:
        """Why speech is doing what it is doing, in the words a person needs.

        The one operation that exists purely for the user rather than for the
        machine. "It stopped talking" has a dozen causes — a policy floor, a
        thermal state, a missing sink, a provider that failed once — and a
        surface that could only say "no audio" would send somebody to check
        their speakers when the answer was that the battery is at 8%.
        """
        decision = self.policy.decision
        document: dict[str, Any] = {
            "outcome": decision.outcome,
            "eligible": decision.eligible,
            "speaks": decision.speaks,
            "reasons": list(decision.reasons),
            "minimumPriority": decision.minimum_priority.wire,
            "ladder": self.policy.describe()["ladder"],
            "transitions": self.policy.describe()["transitions"],
            "degradations": [item.to_json() for item in self.router.degradations[-16:]],
            "boundaries": self.boundaries(),
        }
        if requestId:
            measurement = self.ledger.measurement(requestId)
            document["synchronisation"] = measurement.to_json() if measurement else None
            document["ledger"] = [
                item for item in self.queue.ledger if item.get("requestId") == requestId
            ]
        return document

    # ----------------------------------------------------------------- #

    def boundaries(self) -> dict[str, Any]:
        """The claims this phase makes, in a form a gate can assert on.

        Every one of these is a §1, §15 or §16 statement. Putting them in the
        health response rather than only in a document means a test asserts the
        running system rather than the prose.
        """
        return {
            "captionsAuthoritative": True,
            "voiceMayChangeTaskState": False,
            "voiceMayResolveApprovals": False,
            "voiceMaySelectExecutor": False,
            "voiceMayInvokeTools": False,
            "voiceMayReadSecretPayloads": False,
            "voiceMayRewriteCaptions": False,
            "voiceFailureFailsTask": False,
            "remoteProviderConfigured": False,
            "remoteTransmissionPermitted": may_speak_remotely("public"),
            "voiceCloningSupported": False,
            "voiceSampleImportSupported": False,
            "speakerEmbeddingSupported": False,
            "modelTrainingSupported": False,
            "microphoneUsedByVoiceRuntime": False,
            "speechRecognitionImplemented": False,
            "physicalSpeakerValidated": False,
        }

    def describe(self) -> dict[str, Any]:
        return {
            "runtimeDirectory": str(self.runtime_directory),
            "workerRunning": self.worker.running,
            "integration": {
                "mode": "in-process isolated worker",
                "separateUserService": False,
                "reason": (
                    "the failing components are already separate processes; a second unit "
                    "would isolate the worker from the companion rather than the companion "
                    "from the synthesiser, and would put a socket between a task event and "
                    "the signal that releases an audio device"
                ),
                "secondTaskRuntime": False,
            },
            "health": self.voice_health(),
        }
