# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The long-lived half: one runtime, one store, and a socket onto it.

This is what the systemd user unit starts and what outlives every window. It
owns exactly one :class:`companion.runtime.CompanionRuntime`, runs tasks on its
own worker, and exposes the operations in :mod:`companion.protocol` — and
nothing else — to whatever connects.

The division of labour is the point of the whole integration:

* the **runtime** decides. Which executor, whether the capability allows it,
  whether consent covers this act, what the record says happened.
* the **service** schedules and serves. It puts a submitted task on a worker,
  answers questions about the record, and carries a person's approval decision
  back to the runtime *as a claim to be checked* rather than as an instruction.
* the **client** draws. It has no store, no executor, no broker and no way to
  reach one.

Two mechanisms make that hold rather than merely describe it.

:class:`InteractiveConsent` is a :class:`companion.approvals.ConsentSource` that
blocks. It is the seam through which a person's answer reaches the runtime, and
it is a *narrow* one: it returns ``"granted"``, ``"denied"`` or ``None``, which
is the entire vocabulary. There is no path by which the Approval Centre can hand
the runtime anything else — not a plan, not a destination, not a provider. The
binding fields the UI sends back are checked in
:meth:`CompanionGateway.resolve_approval` against the request the runtime
recorded, and then thrown away; only the yes or no travels onward, and
:meth:`companion.approvals.ApprovalGate.resolve` checks the whole binding again
against the plan that is about to run.

**A connection owns nothing.** Each request is served and the connection closed.
Closing the GTK window therefore cannot stop a task, cancel an approval or lose
a result, because none of those were ever attached to a socket.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import os
from pathlib import Path
import queue
import re
import threading
from typing import Any, Mapping, Sequence

from capability.apply.approval import ApprovalRequest

from .approvals import CompanionApprovalStore, ConsentSource
from .cancellation import cancel_task
from .clock import Clock, SystemClock, iso8601
from .errors import CompanionError, StoreError
from .events import TaskEvent
from .presentation import (
    AccessibilityPreferences,
    PresentationProjector,
    PresentationState,
    select_presentation,
    signals_from_capability_event,
)
from .protocol import CompanionServer, MAX_EVENT_PAGE, PROTOCOL_SCHEMA_VERSION
from .recovery import recover
from .runtime import CompanionRuntime
# The *preferences* type only. The service reaches the voice runtime through
# :meth:`CompanionService._build_voice`, which imports it inside the function —
# so a build with no voice package still imports this module, and the dependency
# runs one way: the companion knows about voice, voice knows nothing about the
# companion's runtime.
from .voice.policy import VoicePreferences

__all__ = [
    "CompanionGateway",
    "CompanionService",
    "InteractiveConsent",
    "PRESENTATION_AUDIENCE",
]

#: The audience every client is served at, and the only one.
#:
#: Not a parameter. A protocol that let the caller name its own audience would
#: let a client ask for the ``executor`` ceiling and be given a ``secret``
#: task's contents — privilege escalation by keyword argument. The UI ceiling is
#: ``sensitive`` (:data:`companion.privacy.AUDIENCE_CEILING`), and a client that
#: needs more than that is not a client.
PRESENTATION_AUDIENCE = "ui"

#: How long a task will wait for a person before the safe default applies. The
#: approval request carries its own expiry and the shorter of the two wins; this
#: exists so a runtime with nothing attached to answer does not hold a worker
#: for the whole approval TTL.
DEFAULT_CONSENT_WAIT_SECONDS = 300.0


# --------------------------------------------------------------------------- #
# Consent
# --------------------------------------------------------------------------- #


#: The longest a fault message may be. A fault log is a diagnostic, and an
#: exception carrying a megabyte of context is a way to put that context
#: somewhere it was never reviewed for.
MAX_FAULT_MESSAGE = 400

#: Anything shaped like a secret or a private path is replaced rather than
#: truncated, because truncation keeps the prefix and the prefix is the
#: interesting part of a token.
_FAULT_REDACTIONS: tuple[tuple["re.Pattern[str]", str], ...] = (
    # Windows and POSIX user directories. The fault is identifiable from the
    # basename; the path to somebody's home directory is not needed to fix it.
    (re.compile(r"(?i)[a-z]:\\+users\\+[^\\\s]+"), "<user-path>"),
    (re.compile(r"/(?:home|Users)/[^/\s]+"), "<user-path>"),
    (re.compile(r"(?i)\b/tmp/[^\s]+"), "<temp-path>"),
    # Anything self-describing as a secret, with its value.
    (re.compile(r"(?i)\b(token|secret|password|passphrase|api[_-]?key|bearer)"
                r"\s*[:=]?\s*\S+"), r"\1=<redacted>"),
    # Long hex or base64-ish runs: request tokens, keys, digests of content.
    (re.compile(r"\b[A-Fa-f0-9]{32,}\b"), "<hex>"),
)


def _sanitise_fault_message(error: BaseException) -> str:
    """An exception's text, with what must not be logged taken out.

    Applied to every swallowed fault. The exceptions raised here are written by
    this project and do not deliberately carry secrets, but they do interpolate
    paths and identifiers, and a third-party executor's exception carries
    whatever that executor put in it. Redacting on the way *in* is the only
    point at which that is still under this module's control.
    """
    message = f"{error}"
    for pattern, replacement in _FAULT_REDACTIONS:
        message = pattern.sub(replacement, message)
    message = " ".join(message.split())
    if len(message) > MAX_FAULT_MESSAGE:
        message = message[: MAX_FAULT_MESSAGE - 1] + "…"
    return message


@dataclass
class _Waiter:
    request: ApprovalRequest
    gate: threading.Event = field(default_factory=threading.Event)
    decision: str = ""


@dataclass(frozen=True)
class _HeldAnswer:
    """A decision given before the task asked for it.

    It carries the question's expiry and owner so that it can be discarded on
    exactly the same terms as a waiting task would have been: when the request
    lapses, when the task is cancelled or paused, and when the service stops.
    """

    decision: str
    expires_at_monotonic: float
    service_id: str


class InteractiveConsent(ConsentSource):
    """A consent source that waits for a person, and gives up safely.

    Every exit from :meth:`answer` other than an explicit ``"granted"`` returns
    something that means *no*: an explicit denial, or ``None`` for "nobody
    answered", which :mod:`companion.approvals` turns into a denial with the
    safe default. There is no timeout branch that grants, and there is no
    configuration that would create one.
    """

    def __init__(self, *, maximum_wait_seconds: float = DEFAULT_CONSENT_WAIT_SECONDS) -> None:
        if maximum_wait_seconds <= 0:
            raise ValueError("the consent wait must be positive")
        self.maximum_wait_seconds = maximum_wait_seconds
        self._guard = threading.Lock()
        self._waiting: dict[str, _Waiter] = {}
        #: Answers that arrived before anything was waiting for them.
        #:
        #: With :meth:`register` called before the question is persisted, this
        #: should now be unreachable through the runtime's own path — the waiter
        #: exists before the Approval Centre can see anything to answer. It is
        #: kept because it costs nothing and because "should be unreachable" is
        #: a claim about every caller, present and future, rather than about
        #: this class; a consent source that silently discarded a real answer
        #: would fail in the one direction that matters.
        #:
        #: Keyed by request id. Bounded by the number of questions that are
        #: live and unanswered, because nothing reaches it that has not already
        #: been checked against a live, unexpired, unanswered request.
        self._answered_early: dict[str, _HeldAnswer] = {}
        #: Questions belonging to a task that was cancelled or paused before any
        #: worker asked them. Refused on arrival rather than waited on. Valued
        #: by the question's expiry for the same reason as the held answers: a
        #: long-running service must not accumulate one entry per cancellation
        #: for the rest of its life.
        self._refuse_on_arrival: dict[str, float] = {}
        #: Questions that have already been answered once, and when they lapse.
        #:
        #: Replay protection cannot wait for the durable store. The gateway used
        #: to detect a second answer by asking the approval store whether a
        #: decision existed — but the decision is written by the *worker*, after
        #: it wakes from the consent call, and a second answer arriving before
        #: that was found to be still "pending" and accepted. Measured at about
        #: one run in thirty. An approval authorises one act; the moment an
        #: answer is taken is the moment a second one becomes a replay, and that
        #: moment is here.
        self._answered: dict[str, float] = {}

    # -- registration, before the question exists anywhere else ------------

    def register(self, request: ApprovalRequest) -> bool:
        """Take a waiter for a question that has not been persisted yet.

        This is the fix for the visible-but-unanswerable window, and it fixes it
        at the source. Previously the first thing that existed was the durable
        request, which is also what makes the question displayable — so between
        the store write and the worker reaching :meth:`answer` there was a
        period in which a person could see a question and answer it, and the
        answer had nowhere to go.

        Registering first inverts that. When the Approval Centre can see the
        question, something is already waiting for the answer, and there is no
        window left to lose one in.

        Returns whether a waiter was taken. ``False`` means one already exists
        for this request id, which the caller must treat as a failure to
        register rather than as success: two waiters for one question would let
        an answer release only one of them.
        """
        with self._guard:
            if request.request_id in self._waiting:
                return False
            self._waiting[request.request_id] = _Waiter(request=request)
            return True

    def unregister(self, request_id: str) -> None:
        """Drop a waiter for a question that never became durable.

        The rollback half of :meth:`register`. If persistence fails after
        registration, nothing may be left behind that could receive an answer:
        the question does not exist, so an answer to it must not either.
        """
        with self._guard:
            waiter = self._waiting.pop(request_id, None)
            self._answered_early.pop(request_id, None)
        if waiter is not None:
            # Released with no decision, in case anything is already parked on
            # it. Nothing is authorised by a question being withdrawn.
            waiter.gate.set()

    # -- the ConsentSource interface --------------------------------------

    def answer(self, request: ApprovalRequest, *, now: float) -> str | None:
        with self._guard:
            # Claiming an early answer and taking the waiter happen under one
            # acquisition of the lock. Split across two, a decision landing
            # between them would be recorded as early, found by nobody, and
            # dropped — the original defect, reintroduced one level down.
            self._discard_lapsed(now)
            if request.request_id in self._refuse_on_arrival:
                # The task was cancelled while this question was outstanding.
                # Refusing here rather than waiting is what keeps a cancelled
                # task from holding a worker.
                self._refuse_on_arrival.pop(request.request_id, None)
                self._answered_early.pop(request.request_id, None)
                self._waiting.pop(request.request_id, None)
                return None
            early = self._answered_early.pop(request.request_id, None)
            # The waiter is normally already here, taken by `register` before
            # the question was persisted. Creating one is the fallback for a
            # consent source used without registration — the composed
            # `raise_request` path, which every test and the headless
            # demonstration still use.
            waiter = self._waiting.get(request.request_id)
            if early is None and waiter is None:
                waiter = _Waiter(request=request)
                self._waiting[request.request_id] = waiter
        if early is not None:
            # An answer held here is still subject to the question's own expiry,
            # exactly as a waiting one is. Granting past it would honour consent
            # given for a question that had already lapsed.
            if early.expires_at_monotonic > 0 and now >= early.expires_at_monotonic:
                return None
            return early.decision
        try:
            remaining = self.maximum_wait_seconds
            if request.expires_at_monotonic > 0:
                # Never wait past the moment the request itself expires. Waiting
                # longer and then granting would honour consent given for a
                # question that had already lapsed.
                remaining = min(remaining, max(0.0, request.expires_at_monotonic - now))
            if remaining <= 0:
                return None
            waiter.gate.wait(remaining)
            return waiter.decision or None
        finally:
            with self._guard:
                self._waiting.pop(request.request_id, None)

    # -- the Approval Centre side -----------------------------------------

    def resolve(
        self,
        request_id: str,
        decision: str,
        *,
        expires_at_monotonic: float = 0.0,
        service_id: str = "",
        hold_for_pending_ask: bool = False,
    ) -> str:
        """Deliver an answer, and say what became of it.

        Returns ``"released"`` when a waiting task was woken, ``"held"`` when
        nobody was waiting yet and the answer has been kept for the task that is
        about to ask, ``"unclaimed"`` when nobody was waiting and the answer was
        not kept, and ``"replayed"`` when this question has already been
        answered once.

        ``hold_for_pending_ask`` is what separates the second case from the
        third, and only a caller that has already established the question is
        live may set it. :meth:`CompanionGateway.resolve_approval` does exactly
        that before it calls here: the request exists, every binding field
        matches what the person was shown, it has not expired, and it has not
        already been answered. Holding a decision that has passed those checks
        cannot authorise anything that answering a moment later would not have
        authorised anyway; holding one that had not would be a way to pre-approve
        a question nobody has asked yet.
        """
        if decision not in ("granted", "denied"):
            raise ValueError("an approval decision is 'granted' or 'denied'")
        with self._guard:
            if request_id in self._answered:
                # Answered once already. Whether the worker has got round to
                # writing that down is not this question's business.
                return "replayed"
            self._answered[request_id] = expires_at_monotonic
            waiter = self._waiting.get(request_id)
            if waiter is None:
                if not hold_for_pending_ask:
                    return "unclaimed"
                self._answered_early[request_id] = _HeldAnswer(
                    decision=decision,
                    expires_at_monotonic=expires_at_monotonic,
                    service_id=service_id,
                )
                return "held"
            waiter.decision = decision
        waiter.gate.set()
        return "released"

    def abandon(
        self,
        task_id: str,
        *,
        request_ids: Sequence[str] | Sequence[tuple[str, float]] = (),
    ) -> tuple[str, ...]:
        """Stop waiting on every question belonging to one task.

        Used by cancellation and by pausing. The waiters are released with *no*
        decision, so the safe default applies and nothing is authorised by a
        task ending or being set aside.

        ``request_ids`` names questions that are outstanding but that no worker
        has reached yet, and it closes the mirror image of the early-answer
        window. A task becomes visibly "waiting for approval" when its request
        is written to the store, which is before the worker calls :meth:`answer`.
        Cancelling in that window released nothing, and the worker then parked on
        a question belonging to a task that had already been cancelled — held for
        the whole consent budget, which is precisely what cancelling is supposed
        to prevent. Naming the outstanding requests here refuses them on arrival
        instead.

        Passing request ids rather than remembering the task is deliberate. A
        paused task resumes and asks again, and it asks with *new* request ids;
        refusing by task would refuse those too, and a resumed task would be
        unable to obtain consent for the rest of the service's life.
        """
        service_id = f"companion.task.{task_id}"
        # Accepts bare ids as well as (id, expiry) pairs, so a caller that has
        # no expiry to hand is not forced to invent one.
        refusals = {
            (item[0], item[1]) if isinstance(item, tuple) else (item, 0.0)
            for item in request_ids
        }
        with self._guard:
            self._refuse_on_arrival.update(refusals)
        released = self._release(
            lambda waiter: waiter.request.service_id == service_id,
            held=lambda answer: answer.service_id == service_id,
        )
        # Both halves are reported: a question whose waiter was woken and one
        # that will be refused the moment it is asked have the same consequence
        # for the person who cancelled, and a caller that saw only the first
        # would think nothing had been stopped.
        return tuple(sorted(set(released) | {request_id for request_id, _expiry in refusals}))

    def abandon_all(self) -> tuple[str, ...]:
        """Release every waiter. Used when the service itself is stopping.

        Without this a service told to stop would wait for whatever remained of
        the consent timeout — up to five minutes by default — because a worker
        parked on an unanswered question is a worker that cannot be joined. It
        releases with no decision, so stopping the service authorises nothing.
        """
        with self._guard:
            self._refuse_on_arrival.clear()
        return self._release(lambda _waiter: True, held=lambda _answer: True)

    def _release(self, matches, *, held) -> tuple[str, ...]:
        """Release matching waiters, and drop the held answers alongside them.

        Both halves matter. A waiter that is not released holds a worker; a held
        answer that is not dropped would be handed to a question asked after the
        task it belonged to was cancelled, which is consent surviving the thing
        it was given for.
        """
        with self._guard:
            waiters = [
                (request_id, waiter)
                for request_id, waiter in self._waiting.items()
                if matches(waiter)
            ]
            for request_id in [
                request_id
                for request_id, answer in self._answered_early.items()
                if held(answer)
            ]:
                self._answered_early.pop(request_id, None)
        for _request_id, waiter in waiters:
            waiter.gate.set()
        return tuple(request_id for request_id, _waiter in waiters)

    def _discard_lapsed(self, now: float) -> None:
        """Drop anything whose question has expired. Caller holds the lock.

        Both maps are swept together: an expired question cannot be answered and
        cannot be refused, because there is nothing left to answer or refuse.
        """
        for request_id in [
            request_id
            for request_id, answer in self._answered_early.items()
            if answer.expires_at_monotonic > 0 and now >= answer.expires_at_monotonic
        ]:
            self._answered_early.pop(request_id, None)
        for request_id in [
            request_id
            for request_id, expires_at in self._refuse_on_arrival.items()
            if expires_at > 0 and now >= expires_at
        ]:
            self._refuse_on_arrival.pop(request_id, None)
        for request_id in [
            request_id
            for request_id, expires_at in self._answered.items()
            if expires_at > 0 and now >= expires_at
        ]:
            # Safe to forget: a lapsed question cannot be replayed, because the
            # approval store refuses it on its own expiry.
            self._answered.pop(request_id, None)

    def waiting_for(self) -> tuple[ApprovalRequest, ...]:
        with self._guard:
            return tuple(self._waiting[key].request for key in sorted(self._waiting))

    def held_answers(self) -> tuple[str, ...]:
        """Request ids with an answer waiting for the question. For diagnostics."""
        with self._guard:
            return tuple(sorted(self._answered_early))


# --------------------------------------------------------------------------- #
# The gateway
# --------------------------------------------------------------------------- #


class CompanionGateway:
    """Everything a connected client may ask the runtime to do.

    One method per protocol operation and no generic accessor. Reviewing the
    client's reach means reading this class, which is the reason it exists as
    a class rather than as a handful of closures over the runtime.
    """

    def __init__(
        self,
        runtime: CompanionRuntime,
        *,
        consent: InteractiveConsent,
        preferences: AccessibilityPreferences | None = None,
        audio_output_available: bool = False,
        display_available: bool = True,
        endpoint_description: Mapping[str, Any] | None = None,
        clock: Clock | None = None,
        voice: "VoiceService | None" = None,
    ) -> None:
        self.runtime = runtime
        self.consent = consent
        self.preferences = preferences or AccessibilityPreferences()
        self.audio_output_available = audio_output_available
        self.display_available = display_available
        self.endpoint_description = dict(endpoint_description or {})
        self.clock = clock or SystemClock()
        #: Optional. A gateway with no voice runtime answers every ``voice_*``
        #: operation with a refusal that says so, rather than raising: a client
        #: asking a machine with speech disabled why it is not talking should be
        #: told, and §8 means the answer costs the task nothing either way.
        self.voice = voice
        self._work: "queue.Queue[str | None]" = queue.Queue()
        self._running: set[str] = set()
        self._queued: set[str] = set()
        #: The last few faults the worker swallowed. See :meth:`_record_fault`.
        self._faults: "deque[dict[str, Any]]" = deque(maxlen=32)
        self._guard = threading.Lock()
        self._worker: threading.Thread | None = None
        self._stopping = threading.Event()

    # -- the worker --------------------------------------------------------

    def start_worker(self) -> threading.Thread:
        """Start the single thread that carries tasks through the runtime.

        One thread, deliberately. A task parked on an approval holds it, which
        is a real limitation and is written down as one — but two threads
        driving one :class:`CompanionRuntime` would share its in-memory session
        cache and its executor leases, and "probably fine under the GIL" is not
        a property worth resting the record on. Cancelling or answering a parked
        task frees the worker, and neither of those goes through it.
        """
        if self._worker is not None:
            raise RuntimeError("the companion worker is already running")
        self._worker = threading.Thread(
            target=self._serve_work, name="bunny-companion-worker", daemon=True
        )
        self._worker.start()
        return self._worker

    def stop_worker(self) -> None:
        self._stopping.set()
        self._work.put(None)
        if self._worker is not None:
            self._worker.join(timeout=10.0)
            self._worker = None

    def _serve_work(self) -> None:
        while not self._stopping.is_set():
            item = self._work.get()
            if item is None:
                return
            with self._guard:
                self._queued.discard(item)
                self._running.add(item)
            state_before = self._task_state(item)
            try:
                session_id, task = self.runtime.find_task(item)
                self.runtime.run_task(session_id, task.task_id)
            except CompanionError as exc:
                # The refusal is already in the event stream — the runtime
                # writes one before it raises. Swallowed here because a worker
                # that died on a blocked task would take every later task with
                # it, and the record already says what happened.
                self._record_fault(item, exc, classified=True, state_before=state_before)
            except Exception as exc:  # noqa: BLE001 - the fault is data
                # Third-party code — an executor, a reviewer, a tool — faulted
                # in a way the runtime did not classify. The worker survives;
                # the task's own record carries whatever the runtime managed to
                # write before it unwound.
                self._record_fault(item, exc, classified=False, state_before=state_before)
            finally:
                with self._guard:
                    self._running.discard(item)

    def _task_state(self, task_id: str) -> str:
        """The task's current state, or ``""`` if it cannot be read.

        Read before the run so that a fault can say whether the run moved the
        task anywhere. A fault that left the task exactly where it was needs a
        human; one that moved it to ``blocked`` has already told the user
        something.
        """
        try:
            _session_id, task = self.runtime.find_task(task_id)
        except Exception:  # noqa: BLE001 - reading state must never fault
            return ""
        return task.state

    def _record_fault(
        self,
        task_id: str,
        error: BaseException,
        *,
        classified: bool,
        state_before: str = "",
    ) -> None:
        """Keep what the worker swallowed, so that it can be asked about later.

        The worker must survive a task that faults, or one bad task would take
        every later one with it. But surviving silently is how a task comes to
        sit in ``waiting_for_executor`` with nothing running, nothing queued and
        no explanation anywhere — which is exactly the shape the intermittent
        suite failure presented, and the reason it went two phases without a
        diagnosis. Swallowing the exception and discarding the evidence are
        separable, and only the first one is necessary.

        The record is structured rather than a sentence, because the questions
        asked of it are structured: which fault, on which task, in which phase,
        did anything change, does somebody need to do something. A message
        alone answers none of those without being parsed.

        **Nothing sensitive reaches it.** The message is sanitized, and the
        fields are chosen so that the fault is identifiable without the task's
        contents: no request text, no credentials, no tokens, no unrestricted
        paths. A fault log is read by whoever is debugging, which is not
        necessarily whoever owns the data.

        Bounded, because an unbounded fault log on a long-running service is a
        memory leak with a helpful name.
        """
        state_after = self._task_state(task_id)
        with self._guard:
            self._faults.append({
                "faultType": type(error).__name__,
                "taskId": task_id,
                "operation": "run_task",
                "lifecyclePhase": state_before or "unknown",
                "at": iso8601(self.clock.wall()),
                "message": _sanitise_fault_message(error),
                # The runtime does not retry a task; the store retries a
                # replacement beneath it. Said explicitly so that a reader does
                # not have to infer which layer gave up.
                "retryAttempted": False,
                "taskStateChanged": bool(state_after) and state_after != state_before,
                "stateAfter": state_after or "unknown",
                # An unclassified fault is third-party code failing in a way the
                # runtime never described, and nothing has told the user.
                "classified": classified,
                "userVisibleRecoveryRequired": (
                    not classified or state_after == state_before
                ),
            })

    def recent_faults(self) -> list[dict[str, Any]]:
        with self._guard:
            return list(self._faults)

    def _schedule(self, task_id: str) -> str:
        with self._guard:
            if task_id in self._running:
                return "running"
            if task_id in self._queued:
                return "queued"
            self._queued.add(task_id)
        self._work.put(task_id)
        return "queued"

    def is_running(self, task_id: str) -> bool:
        with self._guard:
            return task_id in self._running

    def drain(self, timeout: float = 30.0) -> bool:
        """Wait for the queue to empty. For the vertical slice and the tests."""
        deadline = threading.Event()
        waited = 0.0
        step = 0.02
        while waited < timeout:
            with self._guard:
                idle = not self._running and not self._queued
            if idle:
                return True
            deadline.wait(step)
            waited += step
        return False

    # -- operations --------------------------------------------------------

    def health(self) -> dict[str, Any]:
        try:
            sessions = len(self.runtime.store.session_ids())
            store_ok = True
            store_detail = ""
        except StoreError as exc:
            sessions = 0
            store_ok = False
            store_detail = str(exc)
        with self._guard:
            running = sorted(self._running)
            queued = sorted(self._queued)
        return {
            "ok": store_ok,
            "protocolSchemaVersion": PROTOCOL_SCHEMA_VERSION,
            "endpoint": self.endpoint_description,
            "storeRoot": str(self.runtime.store.root),
            "storeReadable": store_ok,
            "storeDetail": store_detail,
            "sessions": sessions,
            "executors": sorted(self.runtime._executors),
            "reviewers": list(self.runtime.reviewer_ids()),
            "runningTasks": running,
            "queuedTasks": queued,
            "awaitingApproval": [item.request_id for item in self.consent.waiting_for()],
            # A task that stopped without reaching a terminal state left its
            # reason here, and nowhere else.
            "recentWorkerFaults": self.recent_faults(),
            "audioOutputAvailable": self.audio_output_available,
            "displayAvailable": self.display_available,
            # Stated rather than implied. A reader should not have to infer from
            # an absence that no microphone is running and no provider is
            # configured; §16 and §11 both turn on that being said out loud.
            "microphoneActive": False,
            "microphonePolicy": "explicit activation only; never at service start",
            "remoteProviders": [],
            "paidProviderConfigured": False,
            "accessibility": self.preferences.to_json(),
        }

    def create_session(
        self,
        *,
        title: str,
        locality: str,
        allowRemote: bool,
        taskLimitUnits: int,
        sessionLimitUnits: int,
    ) -> dict[str, Any]:
        from .session import CostPolicy, LOCALITY_PREFERENCES, PrivacyPolicy

        if locality not in LOCALITY_PREFERENCES:
            raise CompanionError(f"locality must be one of {list(LOCALITY_PREFERENCES)}")
        session = self.runtime.create_session(
            title,
            privacy_policy=PrivacyPolicy(allow_remote=bool(allowRemote)),
            cost_policy=CostPolicy(
                task_limit_units=int(taskLimitUnits),
                session_limit_units=int(sessionLimitUnits),
            ),
            locality_preference=locality,
        )
        return {"session": session.to_json()}

    def list_sessions(self) -> dict[str, Any]:
        return {"sessions": [item.to_json() for item in self.runtime.sessions()]}

    def get_session(self, *, sessionId: str) -> dict[str, Any]:
        session = self.runtime.session(sessionId)
        return {
            "session": session.to_json(),
            "tasks": [task.view(PRESENTATION_AUDIENCE) for task in self.runtime.store.tasks(sessionId)],
        }

    def submit_task(
        self,
        *,
        sessionId: str,
        request: str,
        classification: str | None,
        costLimitUnits: int | None,
        run: bool,
    ) -> dict[str, Any]:
        task = self.runtime.submit_task(
            sessionId, request, classification=classification, cost_limit_units=costLimitUnits
        )
        scheduled = self._schedule(task.task_id) if run else "not-scheduled"
        return {
            "task": task.view(PRESENTATION_AUDIENCE),
            "sessionId": sessionId,
            "scheduled": scheduled,
        }

    def list_tasks(self, *, sessionId: str | None) -> dict[str, Any]:
        session_ids = [sessionId] if sessionId else list(self.runtime.store.session_ids())
        tasks = []
        for identifier in session_ids:
            for task in self.runtime.store.tasks(identifier):
                tasks.append(task.view(PRESENTATION_AUDIENCE))
        return {"tasks": tasks}

    def get_task(self, *, taskId: str, sessionId: str | None) -> dict[str, Any]:
        session_id, task = self._locate(taskId, sessionId)
        return {"sessionId": session_id, "task": task.view(PRESENTATION_AUDIENCE)}

    def get_events(
        self, *, taskId: str | None, sessionId: str | None, afterSequence: int, limit: int
    ) -> dict[str, Any]:
        session_id, events = self._events(taskId, sessionId)
        later = [event for event in events if event.sequence > afterSequence]
        page = later[: min(limit, MAX_EVENT_PAGE)]
        return {
            "sessionId": session_id,
            "taskId": taskId or "",
            "events": [event.view(PRESENTATION_AUDIENCE) for event in page],
            "afterSequence": afterSequence,
            "revision": page[-1].sequence if page else afterSequence,
            "hasMore": len(later) > len(page),
            "audience": PRESENTATION_AUDIENCE,
        }

    def get_presentation_state(
        self, *, taskId: str | None, sessionId: str | None, afterSequence: int, limit: int
    ) -> dict[str, Any]:
        session_id, events = self._events(taskId, sessionId)
        state, projector = self._project(events)
        later = [event for event in events if event.sequence > afterSequence]
        page = later[: min(limit, MAX_EVENT_PAGE)]
        # The caption is published to the voice runtime here, at the one place
        # the canonical projection is produced for a client. Publishing is not
        # speaking: it records what the authoritative caption currently is and
        # returns an identifier a client may later pass to ``voice_speak``.
        # Doing it anywhere else would mean the voice runtime reading the event
        # stream itself, which is the second interpretation §1 forbids.
        caption_id = ""
        if self.voice is not None and state.task_id:
            try:
                caption = self.voice.publish(state)
                caption_id = caption.caption_id
                self.voice.refresh(
                    capability_signals=projector.capability_signals,
                    foreground_workload=len(self._running),
                )
            except Exception:  # noqa: BLE001 - presentation must survive a voice fault
                caption_id = ""
        return {
            "sessionId": session_id,
            "taskId": taskId or state.task_id,
            "state": state.to_json(),
            #: What ``voice_speak`` takes. Empty when there is no voice runtime
            #: or nothing speakable, which a client treats as "no speech
            #: available" — never as a reason not to show the caption.
            "captionId": caption_id,
            # The events since the client's revision, so it can fold them itself
            # and arrive at the same value. Not required — the state above is
            # complete — but §7 asks the client to be able to rebuild by replay
            # and it cannot do that if it is never given the events.
            "events": [event.view(PRESENTATION_AUDIENCE) for event in page],
            "hasMore": len(later) > len(page),
            "revision": state.revision,
            "audience": PRESENTATION_AUDIENCE,
            "capabilitySignals": dict(projector.capability_signals),
        }

    def resolve_approval(
        self,
        *,
        requestId: str,
        sessionId: str,
        taskId: str,
        planId: str,
        transitionId: str,
        action: str,
        destination: str,
        providerId: str,
        dataClassification: str,
        estimatedCostUnits: int | None,
        destinationFingerprint: str,
        decision: str,
    ) -> dict[str, Any]:
        """Take a person's answer, having first checked it is about what they saw.

        Every §9 rejection lives here or one layer below. This one compares the
        *claim* — what the Approval Centre says it displayed — against the
        request the runtime recorded, and refuses if any binding field differs.
        :meth:`companion.approvals.ApprovalGate.resolve` then compares the
        recorded reference against the plan that is actually about to run. Both
        are needed: this catches a client that altered what it showed, and that
        catches a plan that changed after the person answered.
        """
        if decision not in ("granted", "denied"):
            raise CompanionError("an approval decision is 'granted' or 'denied'")
        request = self.runtime.approvals.requests.get(requestId)
        if request is None:
            raise KeyError(f"no approval request with id {requestId!r} was raised")

        expected_service = f"companion.task.{taskId}"
        mismatches: list[str] = []
        if request.service_id != expected_service:
            mismatches.append(
                f"the request belongs to {request.service_id!r} and was answered for task {taskId!r}"
            )
        if request.plan_id != planId:
            mismatches.append(
                f"the plan was {request.plan_id!r} when the question was asked and the answer names {planId!r}"
            )
        if request.transition_id != transitionId:
            mismatches.append("the answer names a different step of the plan")
        if request.action != action:
            mismatches.append(
                f"the question was about {request.action!r} and the answer is about {action!r}"
            )
        if request.destination != destination:
            mismatches.append(
                f"the destination was {request.destination!r} and the answer names {destination!r}"
            )
        if (request.provider_id or "") != (providerId or ""):
            mismatches.append("the provider changed between the question and the answer")
        if request.data_affected != dataClassification:
            mismatches.append("the data classification changed between the question and the answer")
        if request.estimated_cost_units != estimatedCostUnits:
            mismatches.append(
                f"the cost was {request.estimated_cost_units!r} and the answer names {estimatedCostUnits!r}"
            )
        if destinationFingerprint:
            reference = self._approval_reference(sessionId, taskId, requestId)
            if reference is not None and reference.destination_fingerprint != destinationFingerprint:
                mismatches.append("the destination fingerprint does not match the recorded request")
        if mismatches:
            from .errors import ApprovalMismatch

            raise ApprovalMismatch(
                "this answer is not about the question that was asked: " + "; ".join(mismatches)
            )

        now = self.clock.monotonic()
        if request.expired(now):
            from .errors import ApprovalExpired

            self.runtime.approvals.expire(now)
            raise ApprovalExpired(
                f"{requestId!r} expired before it was answered; the safe default applied "
                "and nothing was done"
            )
        existing = self.runtime.approvals.decision_for(requestId)
        if existing is not None and existing.decision not in ("pending",):
            from .errors import ApprovalReplayed

            raise ApprovalReplayed(
                f"{requestId!r} was already {existing.decision}; an approval is answered once"
            )

        # Every check above has established that this question is live: it
        # exists, it is about what the person was shown, it has not expired and
        # it has not been answered. That is precisely the licence the consent
        # source needs to hold the answer for a task that is about to ask for
        # it rather than discard it.
        outcome = self.consent.resolve(
            requestId,
            decision,
            expires_at_monotonic=request.expires_at_monotonic,
            service_id=request.service_id,
            hold_for_pending_ask=True,
        )
        if outcome == "replayed":
            from .errors import ApprovalReplayed

            # The check above asks the durable store, and the store learns the
            # decision from the *worker*, after it wakes. A second answer that
            # arrives before that found "pending" and was accepted — measured at
            # about one run in thirty. The consent source knows immediately.
            raise ApprovalReplayed(
                f"{requestId!r} has already been answered; an approval is answered once"
            )
        if outcome == "unclaimed":
            # Nobody is waiting and nobody will. The decision is recorded anyway
            # — it is the user's answer and belongs in the record — but the task
            # it was about has already moved on, and saying so is better than
            # letting the user believe they unblocked something.
            if decision == "granted":
                self.runtime.approvals.grant(
                    requestId, plan_id=planId, now=now, responder="user",
                    detail="answered after the task had stopped waiting",
                )
            else:
                self.runtime.approvals.deny(
                    requestId, plan_id=planId, responder="user",
                    detail="answered after the task had stopped waiting",
                )
        return {
            "requestId": requestId,
            "decision": decision,
            # "held" is a delivery. The answer reaches the task that asks for
            # it, and the only difference the person could observe is that it
            # arrived before the question rather than after.
            "delivered": outcome in ("released", "held"),
            "outcome": outcome,
            "detail": {
                "released": "the waiting task was released with your answer",
                "held": "your answer is recorded and the task will take it as soon as it asks",
                "unclaimed": "your answer was recorded; the task was no longer waiting for it",
            }[outcome],
        }

    def cancel_task(self, *, taskId: str, sessionId: str | None, cause: str, detail: str) -> dict[str, Any]:
        session_id, task = self._locate(taskId, sessionId)
        # Released first. A task parked on an approval is inside a blocking
        # consent call; cancelling without waking it would leave the worker held
        # until the request expired, and the user watching a "cancelled" task
        # that had not stopped.
        released = self.consent.abandon(taskId, request_ids=self._outstanding_requests(taskId))
        outcome = cancel_task(self.runtime, session_id, task.task_id, cause=cause, detail=detail)
        # §7: cancelling a task stops that task's speech, queued and current.
        # After the cancellation, not before: the task's own outcome does not
        # depend on speech stopping, and stopping speech first would leave a
        # window where a cancellation that then failed had already silenced a
        # task that carried on running.
        silenced: tuple[str, ...] = ()
        if self.voice is not None:
            try:
                silenced = self.voice.worker.cancel_task(
                    task.task_id, reason="the task was cancelled"
                )
            except Exception:  # noqa: BLE001 - a voice fault must not fail a cancellation
                silenced = ()
        return {
            "sessionId": session_id,
            "cancellation": outcome.to_json(),
            "task": outcome.task.view(PRESENTATION_AUDIENCE),
            "releasedApprovals": list(released),
            "silencedUtterances": list(silenced),
        }

    def pause_task(self, *, taskId: str, sessionId: str | None) -> dict[str, Any]:
        session_id, _task = self._locate(taskId, sessionId)
        # One call, because pausing is one transaction and it belongs to the
        # runtime. It used to be split: the runtime wrote the pause and this
        # method released the waiters afterwards, which left a window between
        # "the task says paused" and "nothing is waiting on its questions" — and
        # ordering the two halves correctly from out here was never possible,
        # because whichever went first the other was observable on its own.
        # CompanionRuntime.pause_task now enumerates the outstanding questions
        # from the durable approval authority, withdraws them, releases their
        # waiters and only then emits task_paused, under the lifecycle lock.
        before = set(self.runtime.approvals.requests)
        task = self.runtime.pause_task(session_id, taskId)
        owner = f"companion.task.{taskId}"
        released = sorted(
            request_id
            for request_id in before
            if self.runtime.approvals.requests[request_id].service_id == owner
            and (self.runtime.approvals.decision_for(request_id) or None) is not None
            and self.runtime.approvals.decision_for(request_id).decision != "pending"
        )
        return {
            "sessionId": session_id,
            "task": task.view(PRESENTATION_AUDIENCE),
            "releasedApprovals": released,
        }

    def resume_task(self, *, taskId: str, sessionId: str | None) -> dict[str, Any]:
        session_id, _task = self._locate(taskId, sessionId)
        task = self.runtime.resume_task(session_id, taskId)
        self._schedule(task.task_id)
        return {"sessionId": session_id, "task": task.view(PRESENTATION_AUDIENCE), "scheduled": "queued"}

    # -- internals ---------------------------------------------------------

    # -- speech ------------------------------------------------------------
    #
    # Eight methods, each one line of delegation to
    # :class:`companion.voice.service.VoiceService`. Deliberately thin: this
    # gateway holds the runtime, and any logic living here would be logic with a
    # runtime in reach. The voice service has no runtime, no store and no
    # session, which is what makes "voice cannot change task state" a fact about
    # the object graph rather than a rule somebody has to keep.

    def _voice_unavailable(self, operation: str) -> dict[str, Any]:
        return {
            "available": False,
            "operation": operation,
            "reason": (
                "this companion service is running without a voice runtime; the captions "
                "are the whole of the output and the task is unaffected"
            ),
            "captionRetained": True,
            "taskAffected": False,
        }

    def voice_health(self) -> dict[str, Any]:
        if self.voice is None:
            return self._voice_unavailable("voice_health")
        return {"available": True, **self.voice.voice_health()}

    def voice_list(self, *, language: str, limit: int) -> dict[str, Any]:
        if self.voice is None:
            return self._voice_unavailable("voice_list")
        return {"available": True, **self.voice.voice_list(language=language, limit=limit)}

    def voice_status(self) -> dict[str, Any]:
        if self.voice is None:
            return self._voice_unavailable("voice_status")
        return {"available": True, **self.voice.voice_status()}

    def voice_speak(
        self,
        *,
        captionId: str,
        priority: str,
        interruptionPolicy: str,
        voiceId: str,
        replay: bool,
    ) -> dict[str, Any]:
        if self.voice is None:
            return self._voice_unavailable("voice_speak")
        return {"available": True, **self.voice.voice_speak(
            captionId=captionId,
            priority=priority,
            interruptionPolicy=interruptionPolicy,
            voiceId=voiceId,
            replay=replay,
        )}

    def voice_cancel(
        self, *, requestId: str, taskId: str, cancellationToken: str
    ) -> dict[str, Any]:
        if self.voice is None:
            return self._voice_unavailable("voice_cancel")
        return {"available": True, **self.voice.voice_cancel(
            requestId=requestId, taskId=taskId, cancellationToken=cancellationToken
        )}

    def voice_pause(self) -> dict[str, Any]:
        if self.voice is None:
            return self._voice_unavailable("voice_pause")
        return {"available": True, **self.voice.voice_pause()}

    def voice_resume(self) -> dict[str, Any]:
        if self.voice is None:
            return self._voice_unavailable("voice_resume")
        return {"available": True, **self.voice.voice_resume()}

    def voice_explain(self, *, requestId: str) -> dict[str, Any]:
        if self.voice is None:
            return self._voice_unavailable("voice_explain")
        return {"available": True, **self.voice.voice_explain(requestId=requestId)}

    def _outstanding_requests(self, task_id: str) -> tuple[tuple[str, float], ...]:
        """Unanswered questions belonging to one task, whether or not asked yet.

        Taken from the approval store rather than from the consent source: the
        store is where a request appears the moment it exists, which is the whole
        point — the ones that matter here are exactly those that are visible to
        the person and not yet reached by a worker.
        """
        service_id = f"companion.task.{task_id}"
        return tuple(
            (request.request_id, request.expires_at_monotonic)
            for request in self.runtime.approvals.pending()
            if request.service_id == service_id
        )

    def _locate(self, task_id: str, session_id: str | None):
        if session_id:
            return session_id, self.runtime.task(session_id, task_id)
        return self.runtime.find_task(task_id)

    def _approval_reference(self, session_id: str, task_id: str, request_id: str):
        try:
            _session, task = self._locate(task_id, session_id or None)
        except CompanionError:
            return None
        return task.approval(request_id)

    def _events(self, task_id: str | None, session_id: str | None) -> tuple[str, tuple[TaskEvent, ...]]:
        if task_id:
            resolved, _task = self._locate(task_id, session_id)
            return resolved, self.runtime.events(resolved, task_id=task_id)
        if session_id:
            return session_id, self.runtime.events(session_id)
        identifiers = self.runtime.store.session_ids()
        if not identifiers:
            return "", ()
        latest = identifiers[-1]
        return latest, self.runtime.events(latest)

    def _project(self, events: tuple[TaskEvent, ...]) -> tuple[PresentationState, PresentationProjector]:
        projector = PresentationProjector(audience=PRESENTATION_AUDIENCE)
        for event in events:
            projector.apply(event)
        # Overlay what the durable approval store says now. The stream records
        # what was asked; the store records what has since been answered, and a
        # decision recorded out of band — from the CLI, say — must not leave the
        # surface showing a question the runtime no longer considers open.
        for approval in projector.state.approvals:
            response = self.runtime.approvals.decision_for(approval.request_id)
            if response is not None and response.decision != "pending":
                projector.settle(approval.request_id, response.decision)
        state = projector.refresh()
        signals = projector.capability_signals
        recommendation = select_presentation(
            signals_from_capability_event(
                signals,
                display_available=self.display_available,
                audio_output_available=self.audio_output_available,
                headless=not self.display_available,
            ),
            self.preferences,
            phase=state.phase,
            plan_id=state.explanation_reference,
        )
        return projector.with_recommendation(recommendation), projector


# --------------------------------------------------------------------------- #
# The service
# --------------------------------------------------------------------------- #


@dataclass
class ServiceOptions:
    """How the long-lived half is wired."""

    root: Path
    endpoint: Path | None = None
    machine: str | None = None
    consent_wait_seconds: float = DEFAULT_CONSENT_WAIT_SECONDS
    preferences: AccessibilityPreferences = field(default_factory=AccessibilityPreferences)
    audio_output_available: bool | None = None
    display_available: bool | None = None
    require_unix: bool | None = None
    #: Force the developer TCP transport on a platform that has AF_UNIX.
    #: A diagnostic for comparing the two transports under one workload; see
    #: companion.protocol.CompanionServer. Never set in production.
    prefer_loopback: bool = False
    #: Run a recovery pass at start-up. On by default: a runtime that starts
    #: without deciding about the tasks it was in the middle of is a runtime
    #: that will make the decision later, implicitly, by running one of them.
    recover_on_start: bool = True
    #: Build a voice runtime inside this service. §18's decision: one service,
    #: one isolated worker, no second unit and no second task runtime. Turning
    #: it off leaves every ``voice_*`` operation answering "no voice runtime"
    #: and changes nothing else — which is the property §8 asks for, expressed
    #: as a configuration flag that a deployment can actually set.
    voice_enabled: bool = True
    voice_preferences: "VoicePreferences | None" = None


class CompanionService:
    """One runtime, one worker, one socket. Started by the user unit."""

    def __init__(self, options: ServiceOptions) -> None:
        self.options = options
        self.root = Path(options.root)
        # Built before the runtime and handed to it, rather than substituted
        # afterwards. A runtime that was constructed with the refusing default
        # and then had its consent source replaced would refuse everything for
        # however long the substitution was missing, and the failure mode of a
        # forgotten line would be an approval nobody could answer.
        self.consent = InteractiveConsent(maximum_wait_seconds=options.consent_wait_seconds)
        self.runtime = self._build_runtime(self.consent)
        self.recovery: dict[str, Any] = {}
        self._stop = threading.Event()
        audio = options.audio_output_available
        if audio is None:
            from .voice import local_voice_available

            audio = local_voice_available()
        display = options.display_available
        if display is None:
            display = bool(os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"))
        self.voice = self._build_voice() if options.voice_enabled else None
        # Everything after the voice runtime is built runs inside this, because
        # the voice runtime has a *started thread* in it and construction can
        # still fail: `CompanionServer` raises `DuplicateRuntime` when a second
        # service is pointed at a live endpoint, which is a supported and tested
        # refusal. Before there was a voice runtime a half-built service leaked
        # nothing; now it would strand a worker thread that nobody holds a
        # reference to and nothing can ever stop.
        #
        # Found by §22's thread-delta column: fifty complete suite runs
        # accumulated a hundred `companion-voice` threads, two per run, and the
        # tests themselves all passed.
        try:
            self.gateway = CompanionGateway(
                self.runtime,
                consent=self.consent,
                preferences=options.preferences,
                audio_output_available=bool(audio),
                display_available=bool(display),
                clock=self.runtime.clock,
                voice=self.voice,
            )
            self.server = CompanionServer(
                self.gateway, options.endpoint,
                require_unix=options.require_unix,
                prefer_loopback=options.prefer_loopback,
            )
            self.gateway.endpoint_description = self.server.describe()
        except BaseException:
            if self.voice is not None:
                self.voice.close()
                self.voice = None
            raise

    def _build_voice(self) -> "VoiceService | None":
        """Construct the voice runtime, or carry on without one.

        A failure here is swallowed on purpose and is the clearest statement of
        §8 in the codebase: a companion whose *service* would not start because
        a synthesiser was misconfigured would have made speech load-bearing for
        tasks, which is exactly the arrangement this phase exists to prevent.
        The captions are unaffected and every ``voice_*`` operation reports the
        absence.
        """
        from .voice.service import VoiceService, VoiceServiceOptions

        try:
            return VoiceService(VoiceServiceOptions(
                runtime_directory=self.root / "voice",
                preferences=self.options.voice_preferences or VoicePreferences(),
                clock=self.runtime.clock,
            ))
        except Exception:  # noqa: BLE001 - speech is never a reason not to start
            return None

    def _build_runtime(self, consent: ConsentSource) -> CompanionRuntime:
        from capability.runtime import assess, assess_current_machine
        from capability.simulate import simulate

        from .coordination import CoordinationPolicy
        from .executor import DeterministicLocalExecutor
        from .ids import RandomIds
        from .reviewer import DeterministicLocalReviewer
        from .runtime import RuntimeOptions
        from .store import CompanionStore
        from .tools import ToolBroker

        assessment = (
            assess(simulate(self.options.machine))
            if self.options.machine
            else assess_current_machine()
        )
        return CompanionRuntime(RuntimeOptions(
            store=CompanionStore(self.root / "store"),
            assessment=assessment,
            executors=(DeterministicLocalExecutor(),),
            reviewers=(DeterministicLocalReviewer(),),
            broker=ToolBroker(),
            approvals=CompanionApprovalStore.load(self.root / "approvals.json"),
            consent=consent,
            providers=(),
            policy=CoordinationPolicy(),
            clock=SystemClock(),
            ids=RandomIds(),
        ))

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> "CompanionService":
        self.runtime.start()
        if self.options.recover_on_start:
            self.recovery = recover(self.runtime).to_json()
        self.gateway.start_worker()
        self.server.start()
        return self

    def close(self) -> None:
        self._stop.set()
        self.server.close()
        # Before the worker is joined, not after. A task parked on an
        # unanswered question holds the worker for the rest of the consent
        # timeout, and a service that took five minutes to stop would be killed
        # by `TimeoutStopSec` mid-append every time somebody left a dialog open.
        # Releasing grants nothing: the waiters return with no decision and the
        # safe default applies.
        self.consent.abandon_all()
        # Before the task worker is joined. A voice worker still playing holds a
        # child process and an audio device, and stopping it first means the
        # service's own shutdown is bounded by the player's termination
        # escalation rather than by whatever the task worker is doing.
        if self.voice is not None:
            self.voice.close()
        self.gateway.stop_worker()
        self.runtime.stop()

    def describe(self) -> dict[str, Any]:
        return {
            "storeRoot": str(self.root),
            "endpoint": self.server.describe(),
            "recovery": self.recovery,
            "voice": self.voice.describe() if self.voice is not None else {
                "workerRunning": False,
                "reason": "voice is disabled for this service",
            },
        }

    def serve_forever(self) -> None:
        """Block until :meth:`close` or an interrupt. What the user unit runs."""
        try:
            self._stop.wait()
        except KeyboardInterrupt:  # pragma: no cover - operator interrupt
            return

    def __enter__(self) -> "CompanionService":
        return self.start()

    def __exit__(self, *_exc: object) -> None:
        self.close()
