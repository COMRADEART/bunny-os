# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""One generation thread, and every resource a generation touches owned by it.

The shape is :class:`companion.voice.worker.VoiceWorker`'s, restated for
generations: a single daemon thread (``companion-agents``) serves a bounded
queue; each job owns its assembler, its cancellation signal and its journal
entries; and the worker's ``finally`` releases what the job's cannot. A fault
in a provider must not end the provider runtime, and must certainly not reach
the task — the executor sees a structured outcome, always.

**The caller blocks; the worker does not care.** ``generate`` is called on
the task worker thread and waits on the job's own latch with a bounded
timeout. That blocking is the §2 pipeline's honest shape — a task *is*
waiting on its generation — and cancellation crosses threads by latching the
job's signal and closing the adapter's connection, so the wait ends the
moment the stream does.

**Backpressure is structural.** Adapters emit through the assembler on the
worker thread; they can produce no faster than events are validated and
accumulated. The queue bound refuses new jobs rather than growing; a refused
job is a failed outcome with the reason, not an exception.

Restart (:meth:`restart`) is the §23 step-22 operation: stop the thread,
cancel the current job, fail the queued ones honestly, start a new thread —
without touching the task runtime, which this object cannot reach (it holds
no reference to one; the import-boundary test makes that structural).
"""

from __future__ import annotations

import queue
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from .adapter import (
    CancellationSignal,
    GenerationOutcome,
    ProviderAdapter,
    StreamEventFactory,
)
from .credentials import Secret
from .errors import CredentialRefused, StreamViolation
from .journal import GenerationJournal
from .registry import AgentProviderRegistry
from .request import GenerationRequest
from .stream import StreamAssembler, StreamEvent
from .usage import UsageLedger

__all__ = ["AgentWorker", "MAX_QUEUE_DEPTH", "WORKER_THREAD_NAME"]

WORKER_THREAD_NAME = "companion-agents"
MAX_QUEUE_DEPTH = 8
_JOIN_TIMEOUT = 10.0
_EVENT_RING = 256
#: Slack over the token bound when converting to the byte bound the assembler
#: enforces: generous, because the token estimate is the provider's business
#: and the byte bound exists to stop pathology, not to meter.
_OUTPUT_BYTES_PER_TOKEN = 16


@dataclass
class _Job:
    request: GenerationRequest
    settled: threading.Event = field(default_factory=threading.Event)
    cancellation: CancellationSignal = field(default_factory=CancellationSignal)
    outcome: GenerationOutcome | None = None
    provisional: str = ""
    #: When the adapter was handed the request, and when its first output
    #: delta arrived — the two stamps §25's time-to-first-token is the
    #: difference of. Zero means it never happened.
    dispatched_monotonic: float = 0.0
    first_delta_monotonic: float = 0.0


class AgentWorker:
    """Runs generations against the registry's adapters, one at a time."""

    def __init__(
        self,
        *,
        registry: AgentProviderRegistry,
        journal: GenerationJournal,
        ledger: UsageLedger,
        monotonic: Callable[[], float],
        queue_depth: int = MAX_QUEUE_DEPTH,
    ) -> None:
        self._registry = registry
        self._journal = journal
        self._ledger = ledger
        self._monotonic = monotonic
        self._queue: "queue.Queue[_Job | None]" = queue.Queue(maxsize=queue_depth)
        self._guard = threading.RLock()
        self._thread: threading.Thread | None = None
        self._running = threading.Event()
        self._current: _Job | None = None
        self._events: deque[dict[str, Any]] = deque(maxlen=_EVENT_RING)
        self._jobs: dict[str, _Job] = {}
        self._generations = 0
        #: The last settlement's timing note, so §25 can read time to first
        #: token without the ring having to be scanned for it.
        self._last_timing: dict[str, Any] = {}

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        with self._guard:
            if self._thread is not None and self._thread.is_alive():
                return
            self._running.set()
            # The counter belongs to the thread's lifetime: after a restart it
            # reads zero until somebody explicitly asks for a generation,
            # which is how §19's "nothing interrupted is repeated" becomes a
            # number a gate can assert on.
            self._generations = 0
            self._thread = threading.Thread(
                target=self._serve, name=WORKER_THREAD_NAME, daemon=True
            )
            self._thread.start()
            self._note("worker_started", {})

    def stop(self, *, timeout: float = _JOIN_TIMEOUT) -> None:
        with self._guard:
            thread = self._thread
            self._running.clear()
            current = self._current
        if current is not None:
            self.cancel(current.request.request_id, reason="worker stopping")
        if thread is not None:
            self._queue.put(None)
            thread.join(timeout=timeout)
        # Fail whatever is still queued, honestly, after the thread is gone.
        while True:
            try:
                job = self._queue.get_nowait()
            except queue.Empty:
                break
            if job is None:
                continue
            self._settle(job, GenerationOutcome(
                request_id=job.request.request_id,
                provider_id=job.request.provider_id,
                ok=False, cancelled=True, detail="worker stopped before dispatch",
            ), journal_disposition="cancelled")
        with self._guard:
            self._thread = None
            self._note("worker_stopped", {})

    def restart(self, *, timeout: float = _JOIN_TIMEOUT) -> None:
        self.stop(timeout=timeout)
        self.start()

    @property
    def running(self) -> bool:
        thread = self._thread
        return bool(thread is not None and thread.is_alive() and self._running.is_set())

    # -- submission ----------------------------------------------------------

    def generate(self, request: GenerationRequest) -> GenerationOutcome:
        """Dispatch one generation and wait for its outcome. Thread-safe."""
        if not self.running:
            return GenerationOutcome(
                request_id=request.request_id, provider_id=request.provider_id,
                ok=False, failure_kind="connection", detail="the provider worker is not running",
            )
        job = _Job(request=request)
        with self._guard:
            self._jobs[request.request_id] = job
        try:
            self._queue.put_nowait(job)
        except queue.Full:
            with self._guard:
                self._jobs.pop(request.request_id, None)
            return GenerationOutcome(
                request_id=request.request_id, provider_id=request.provider_id,
                ok=False, failure_kind="rate-limit",
                detail=f"the provider queue holds {self._queue.maxsize} jobs and is full",
            )
        # Deadline plus margin: the adapter's own timeouts are the enforcement;
        # this wait is the backstop that keeps a wedged adapter from wedging
        # the task worker forever.
        settled = job.settled.wait(timeout=request.deadline_seconds + 30.0)
        if not settled:
            self.cancel(request.request_id, reason="deadline backstop")
            job.settled.wait(timeout=15.0)
        with self._guard:
            self._jobs.pop(request.request_id, None)
        if job.outcome is not None:
            return job.outcome
        return GenerationOutcome(  # pragma: no cover - only a wedged adapter reaches this
            request_id=request.request_id, provider_id=request.provider_id,
            ok=False, failure_kind="timeout",
            detail="the generation did not settle inside its deadline backstop",
        )

    def cancel(self, request_id: str, *, reason: str = "cancelled") -> bool:
        """Latch the signal and close the stream under it. Idempotent."""
        with self._guard:
            job = self._jobs.get(request_id)
        if job is None:
            return False
        latched = job.cancellation.cancel(reason)
        adapter = self._registry.adapter_for(job.request.provider_id)
        if adapter is not None:
            adapter.cancel(request_id)
        return latched

    def cancel_task(self, task_id: str, *, reason: str) -> int:
        """Cancel every generation belonging to one task."""
        with self._guard:
            matching = [
                job.request.request_id for job in self._jobs.values()
                if job.request.task_id == task_id
            ]
        return sum(1 for request_id in matching if self.cancel(request_id, reason=reason))

    # -- the loop ------------------------------------------------------------

    def _serve(self) -> None:
        while self._running.is_set():
            job = self._queue.get()
            if job is None or not self._running.is_set():
                if job is not None:
                    self._settle(job, GenerationOutcome(
                        request_id=job.request.request_id,
                        provider_id=job.request.provider_id,
                        ok=False, cancelled=True, detail="worker stopping",
                    ), journal_disposition="cancelled")
                break
            with self._guard:
                self._current = job
            try:
                outcome = self._run(job)
            except Exception as error:  # noqa: BLE001 - the worker survives its jobs
                outcome = GenerationOutcome(
                    request_id=job.request.request_id,
                    provider_id=job.request.provider_id,
                    ok=False, failure_kind="invalid-response",
                    detail=f"worker fault: {type(error).__name__}: {error}",
                )
            finally:
                with self._guard:
                    self._current = None
            self._settle(job, outcome)

    def _run(self, job: _Job) -> GenerationOutcome:
        request = job.request
        registry = self._registry
        config = registry.configuration_for(request.provider_id)
        adapter = registry.adapter_for(request.provider_id)
        if config is None or adapter is None:
            return GenerationOutcome(
                request_id=request.request_id, provider_id=request.provider_id,
                ok=False, failure_kind="model-unavailable",
                detail=f"provider {request.provider_id!r} is not configured in this runtime",
            )
        if job.cancellation.cancelled:
            return GenerationOutcome(
                request_id=request.request_id, provider_id=request.provider_id,
                ok=False, cancelled=True, detail=job.cancellation.reason,
            )
        now = self._monotonic()
        allowed, why = registry.monitor.allows(request.provider_id, now)
        if not allowed:
            return GenerationOutcome(
                request_id=request.request_id, provider_id=request.provider_id,
                ok=False, failure_kind="connection", detail=why,
            )
        # Remote dispatch is double-checked here, below every policy layer:
        # a remote provider with no approval reference on the request is a
        # refusal even if every layer above misbehaved.
        if config.remote and not request.remote_approval_reference:
            return GenerationOutcome(
                request_id=request.request_id, provider_id=request.provider_id,
                ok=False, failure_kind="authentication",
                detail="remote dispatch without an approval reference is refused at the last layer",
            )
        secret: Secret | None = None
        if config.credential.kind != "none":
            try:
                secret = registry.resolve_secret(request.provider_id)
            except CredentialRefused as refusal:
                registry.monitor.record_failure(
                    request.provider_id, "authentication", now, detail=str(refusal)
                )
                return GenerationOutcome(
                    request_id=request.request_id, provider_id=request.provider_id,
                    ok=False, failure_kind="authentication", detail=str(refusal),
                )
        assembler = StreamAssembler(
            request_id=request.request_id,
            provider_id=request.provider_id,
            maximum_output_bytes=request.maximum_output_tokens * _OUTPUT_BYTES_PER_TOKEN,
        )
        factory = StreamEventFactory(
            request_id=request.request_id,
            provider_id=request.provider_id,
            monotonic=self._monotonic,
        )

        def emit(event: StreamEvent) -> None:
            assembler.accept(event)
            if event.kind == "output_delta":
                job.provisional = (job.provisional + str(event.payload["text"]))[-2048:]
                if job.first_delta_monotonic == 0.0:
                    job.first_delta_monotonic = event.monotonic
            self._note("stream", {
                "kind": event.kind, "requestId": event.request_id,
                "providerId": event.provider_id, "sequence": event.sequence,
                # The event's own stamp, carried through so §25 can measure
                # time to first token without the measurement inventing a
                # clock the runtime does not otherwise consult.
                "monotonic": event.monotonic,
            })

        self._journal.record_start(
            request_id=request.request_id, provider_id=request.provider_id,
            session_id=request.session_id, task_id=request.task_id,
            purpose=request.purpose, remote=config.remote,
            paid=config.cost_class == "paid",
        )
        started = self._monotonic()
        job.dispatched_monotonic = started
        try:
            outcome = adapter.generate(
                request, config,
                secret=secret,
                emit=emit,
                events=factory,
                cancellation=job.cancellation,
            )
        except StreamViolation as violation:
            adapter.cancel(request.request_id)
            outcome = GenerationOutcome(
                request_id=request.request_id, provider_id=request.provider_id,
                ok=False, failure_kind="malformed-output", detail=str(violation),
            )
        finally:
            secret = None  # one dispatch, no residue
        elapsed = self._monotonic() - started
        if outcome.ok and assembler.terminal is not None:
            try:
                assembled = assembler.finalize()
            except StreamViolation as violation:  # pragma: no cover - terminal implies finalizable
                outcome = GenerationOutcome(
                    request_id=request.request_id, provider_id=request.provider_id,
                    ok=False, failure_kind="malformed-output", detail=str(violation),
                )
            else:
                outcome = GenerationOutcome(
                    request_id=outcome.request_id, provider_id=outcome.provider_id,
                    ok=outcome.ok, detail=outcome.detail, assembled=assembled,
                    usage=outcome.usage, retry_hint_seconds=outcome.retry_hint_seconds,
                )
        # Health accounting, one place.
        if outcome.ok:
            registry.monitor.record_success(request.provider_id)
        elif not outcome.cancelled:
            registry.monitor.record_failure(
                request.provider_id, outcome.failure_kind or "invalid-response",
                self._monotonic(), detail=outcome.detail,
                retry_hint_seconds=outcome.retry_hint_seconds,
            )
        if outcome.usage is not None and request.task_id:
            self._ledger.record(request.session_id, request.task_id, outcome.usage)
        self._generations += 1
        note: dict[str, Any] = {
            "requestId": request.request_id,
            "providerId": request.provider_id,
            "ok": outcome.ok,
            "cancelled": outcome.cancelled,
            "failureKind": outcome.failure_kind,
            "seconds": round(elapsed, 3),
        }
        if job.first_delta_monotonic:
            note["firstTokenSeconds"] = round(
                job.first_delta_monotonic - job.dispatched_monotonic, 4
            )
        self._note("generation_settled", note)
        with self._guard:
            self._last_timing = dict(note)
        return outcome

    def _settle(self, job: _Job, outcome: GenerationOutcome, *,
                journal_disposition: str = "") -> None:
        job.outcome = outcome
        disposition = journal_disposition or (
            "completed" if outcome.ok
            else "cancelled" if outcome.cancelled
            else f"failed:{outcome.failure_kind or 'unknown'}"
        )
        self._journal.record_settled(outcome.request_id, disposition, outcome.detail)
        job.settled.set()

    # -- observation ---------------------------------------------------------

    def _note(self, kind: str, payload: Mapping[str, Any]) -> None:
        self._events.append({"kind": kind, **dict(payload)})

    def events(self, *, limit: int = 64) -> tuple[Mapping[str, Any], ...]:
        with self._guard:
            items = tuple(self._events)
        return items[-limit:]

    def provisional_text(self, request_id: str) -> str:
        with self._guard:
            job = self._jobs.get(request_id)
        return job.provisional if job is not None else ""

    def last_timing(self) -> dict[str, Any]:
        """The most recent generation's own timings. Measurement, not state."""
        with self._guard:
            return dict(self._last_timing)

    def active_for_task(self, task_id: str) -> tuple[str, str]:
        """(request_id, provider_id) of this task's live generation, or ("", "")."""
        with self._guard:
            for job in self._jobs.values():
                if job.request.task_id == task_id and not job.settled.is_set():
                    return job.request.request_id, job.request.provider_id
        return "", ""

    def status(self) -> dict[str, Any]:
        with self._guard:
            current = self._current
            return {
                "running": self.running,
                "threadName": WORKER_THREAD_NAME,
                "queueDepth": self._queue.qsize(),
                "activeRequestId": current.request.request_id if current is not None else "",
                "activeProviderId": current.request.provider_id if current is not None else "",
                "generationsServed": self._generations,
                "trackedJobs": len(self._jobs),
            }
