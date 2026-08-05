# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The runtime: the only thing here that is allowed to make anything happen.

Everything else in this package is a value, a contract or a store. This module
is the one that moves a task through its lifecycle, and it is therefore the one
that holds every decision the other modules exist to make checkable:

* it asks :mod:`companion.capability_bridge` where the task may run, and blocks
  it with the router's own reasons when the answer is nowhere;
* it takes an executor's plan and decides, from the tool *declarations* rather
  than from the executor's opinion, what needs a person's consent;
* it performs operations through :class:`companion.tools.ToolBroker`, never
  letting the executor near it;
* it builds one frozen review context per round and hands the same value to
  every reviewer, so reviewers cannot influence each other;
* it writes an event before and after everything, so that a process killed at
  any point leaves a record :mod:`companion.recovery` can reason about.

The order of two of those matters enough to state. **Consent is checked against
the plan that is about to run**, not the plan that was current when the question
was asked — so a revision produced in response to review invalidates the
approval for the previous revision, and the runtime asks again. And **the state
machine gates operations**, not a flag: new work is possible only in
``executing``, so cancellation stops new operations by leaving that state rather
than by every call site remembering to check.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import re
import threading
from typing import Any, Mapping, Sequence

from capability.router import RemoteProvider
from capability.runtime import Assessment

from .approvals import (
    USER_REFUSAL_STATES,
    ApprovalGate,
    CompanionApprovalStore,
    ConsentSource,
    RefusingConsent,
    requirements_for,
    terminal_record,
)
from .capability_bridge import CapabilityDecision, evaluate_task
from .clock import Clock, SystemClock, iso8601
from .coordination import (
    CoordinationPolicy,
    ExecutorLeases,
    ReviewRound,
    reviewer_context,
    run_review_round,
)
from .errors import (
    ApprovalError,
    ApprovalInvalidated,
    CapabilityRefused,
    CompanionError,
    CoordinationLimitExceeded,
    ExecutorUnavailable,
    IntegrityError,
    MalformedOutput,
    StoreError,
)
from .events import TaskEvent, build_event, classification_for
from .executor import Executor, TaskPlan, TaskResult, context_for
from .ids import IdSource, RandomIds, operation_key
from .privacy import display_summary
from .reviewer import Reviewer
from .session import CompanionSession, CostPolicy, PrivacyPolicy
from .states import TERMINAL_STATES, require_transition
from .store import CompanionStore
from .task import (
    ApprovalReference,
    CompanionTask,
    ErrorReference,
    OperationReference,
    OutputReference,
)
from .tools import ToolBroker

__all__ = ["CompanionRuntime", "RuntimeOptions", "classify_request"]

#: How many times an append may lose the race for the stream tip before the
#: runtime gives up. Small: contention here means two writers on one session,
#: which is a cancel arriving mid-run — one retry almost always settles it.
_EMIT_ATTEMPTS = 8


#: Words that place a request in a task type, checked in this order. Crude and
#: deterministic. A real classifier belongs to a later phase and will be a model;
#: what this phase needs is a classification that is *reproducible*, so that the
#: vertical slice produces the same event stream twice and the tests can assert
#: on a type rather than on whatever a model felt like today.
_CLASSIFIERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("summarise", re.compile(r"(?i)\b(summari[sz]e|summary|abstract|tl;?dr)\b")),
    ("compute", re.compile(r"(?i)\b(count|calculate|compute|sum|total|measure|validate)\b")),
    ("transform", re.compile(r"(?i)\b(convert|translate|rewrite|reformat|transform)\b")),
    ("retrieve", re.compile(r"(?i)\b(find|search|look up|retrieve|fetch)\b")),
    ("local_action", re.compile(r"(?i)\b(open|launch|start|install|delete|move|rename)\b")),
    ("question", re.compile(r"(?i)(\?|^\s*(what|why|how|when|where|who|which)\b)")),
)

#: Which capabilities each task type needs, in the router's vocabulary.
_REQUIRED_CAPABILITIES: Mapping[str, tuple[str, ...]] = {
    "summarise": ("inference",),
    "question": ("inference",),
    "transform": ("inference",),
    "retrieve": ("inference",),
    "compute": (),
    "local_action": (),
    "unclassified": ("inference",),
}


def classify_request(request: str) -> tuple[str, tuple[str, ...]]:
    """Decide what kind of task this is. Pure and deterministic."""
    for task_type, pattern in _CLASSIFIERS:
        if pattern.search(request):
            return task_type, _REQUIRED_CAPABILITIES[task_type]
    return "unclassified", _REQUIRED_CAPABILITIES["unclassified"]


@dataclass
class RuntimeOptions:
    """How this runtime is wired. Every dependency is injectable.

    Not for the sake of testability alone: the installed system passes a real
    clock and random ids, and the vertical slice passes a frozen clock and
    sequential ids, and those two runs must exercise the *same* code. A runtime
    that reached for ``time.time()`` internally would make the reproducible run a
    different program from the one that ships.
    """

    store: CompanionStore
    assessment: Assessment
    executors: tuple[Executor, ...] = ()
    reviewers: tuple[Reviewer, ...] = ()
    broker: ToolBroker = field(default_factory=ToolBroker)
    approvals: CompanionApprovalStore | None = None
    #: Whatever stands in for the person who answers approval questions. The
    #: default refuses everything, which is what a Bunny OS with no Approval
    #: Centre connected must do.
    consent: ConsentSource = field(default_factory=RefusingConsent)
    providers: tuple[RemoteProvider, ...] = ()
    policy: CoordinationPolicy = field(default_factory=CoordinationPolicy)
    clock: Clock = field(default_factory=SystemClock)
    ids: IdSource = field(default_factory=RandomIds)


class CompanionRuntime:
    """One process's view of the companion."""

    def __init__(self, options: RuntimeOptions) -> None:
        self.options = options
        self.store = options.store
        self.policy = options.policy
        self.clock = options.clock
        self.ids = options.ids
        self.broker = options.broker
        self.leases = ExecutorLeases()
        self.approvals = options.approvals or CompanionApprovalStore()
        self.gate = ApprovalGate(self.approvals, consent=options.consent)
        self._executors = {item.declaration.executor_id: item for item in options.executors}
        self._reviewers = {getattr(item, "reviewer_id", ""): item for item in options.reviewers}
        self._sessions: dict[str, CompanionSession] = {}
        self._started = False
        #: Serialises the operations that change where a task is in its life —
        #: pausing, resuming and cancelling.
        #:
        #: Not a lock over running a task. A task spends most of its wall-clock
        #: time blocked inside a consent call, and holding a lock across that
        #: would make pausing wait for the answer it exists to stop waiting for.
        #: What this protects is the *transition*: each of these has to
        #: enumerate outstanding approvals, withdraw them, release their
        #: waiters and persist a new state, and two of them interleaving leaves
        #: a task that is half paused with live approval authority. Reentrant
        #: because cancellation calls through the runtime's own helpers.
        self._lifecycle_guard = threading.RLock()

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> "CompanionRuntime":
        self.store.initialise()
        self._started = True
        return self

    def stop(self) -> None:
        """Release in-process state. Nothing on disk changes.

        Deliberately not a checkpoint: everything durable was made durable when
        it was written. A ``stop`` that flushed would imply that a runtime which
        did not get to stop had lost something, and the whole point of the store
        is that it has not.
        """
        for task_id in list(self.leases.leases):
            self.leases.release(task_id)
        self._sessions.clear()
        self._started = False

    def __enter__(self) -> "CompanionRuntime":
        return self.start()

    def __exit__(self, *_exc: object) -> None:
        self.stop()

    def executor(self, executor_id: str) -> Executor | None:
        return self._executors.get(executor_id)

    def reviewer_ids(self) -> tuple[str, ...]:
        return tuple(sorted(name for name in self._reviewers if name))

    # -- event plumbing ----------------------------------------------------

    def _emit(
        self,
        session_id: str,
        task_id: str,
        event_type: str,
        payload: Mapping[str, Any],
        *,
        producer: str = "runtime",
        classification: str = "internal",
        audit_reference: str = "",
        internal_fields: Sequence[str] = (),
    ) -> TaskEvent:
        """Append one event. The only way anything reaches the record."""
        # The tip is read here and the append happens below; the session lock is
        # taken inside `append_many`, so another writer can land in between and
        # the append is refused. That refusal is the store working correctly —
        # it is the defence against replays and stale tips — but from here it is
        # simply a lost race, so it is retried against the new tip. Bounded,
        # because a caller that cannot win in a few attempts is contending with
        # something that needs a person, not another loop.
        last: IntegrityError | None = None
        for _ in range(_EMIT_ATTEMPTS):
            try:
                return self._emit_once(
                    session_id, task_id, event_type, payload,
                    producer=producer, classification=classification,
                    audit_reference=audit_reference, internal_fields=internal_fields,
                )
            except IntegrityError as exc:
                last = exc
        raise StoreError(
            f"could not append a {event_type!r} event to session {session_id} after "
            f"{_EMIT_ATTEMPTS} attempts; another writer holds the stream"
        ) from last

    def _emit_once(
        self,
        session_id: str,
        task_id: str,
        event_type: str,
        payload: Mapping[str, Any],
        *,
        producer: str = "runtime",
        classification: str = "internal",
        audit_reference: str = "",
        internal_fields: Sequence[str] = (),
    ) -> TaskEvent:
        sequence, previous = self.store.tip(session_id)
        # The caller passes the *task's* class; the event carries the class its
        # own payload warrants. Doing this here rather than at each call site is
        # what keeps the two from drifting apart as event types are added.
        #
        # The event id comes from the sequence and not from the id source. An
        # event id has to be unique within its stream, and a stream position is
        # unique within its stream by construction — whereas a minted id is only
        # unique if whatever mints it never repeats itself, which a counter
        # reset by a restart certainly does. Deriving it also makes two runs of
        # the same session produce the same ids, which is what lets the vertical
        # slice compare a replay against the original by value.
        event = build_event(
            event_id=f"ev-{sequence + 1:08d}",
            session_id=session_id,
            task_id=task_id,
            sequence=sequence + 1,
            event_type=event_type,
            timestamp=_iso(self.clock),
            producer=producer,
            payload=payload,
            classification=classification_for(event_type, classification),
            previous_hash=previous,
            audit_reference=audit_reference,
            internal_fields=internal_fields,
        )
        self.store.append(event)
        session = self._sessions.get(session_id)
        if session is not None:
            self._sessions[session_id] = session.touch(self.clock.wall(), revision=event.sequence)
        return event

    def _transition(
        self,
        task: CompanionTask,
        target: str,
        payload: Mapping[str, Any] | None = None,
        *,
        producer: str = "runtime",
        audit_reference: str = "",
        paused_from: str = "",
    ) -> CompanionTask:
        """Move a task, refusing the move if the table does not contain it."""
        event_type = require_transition(task.state, target)
        body = _fill_required(event_type, task, target, dict(payload or {}))
        self._emit(
            task.session_id, task.task_id, event_type, body,
            producer=producer, classification=task.classification, audit_reference=audit_reference,
        )
        return task.with_state(target, paused_from=paused_from)

    def _checkpoint(
        self,
        session: CompanionSession,
        task: CompanionTask | None = None,
        *,
        authoritative: bool = False,
    ) -> CompanionSession:
        """Write the projections so they agree with the stream at rest.

        A crash between the append and this call leaves the projection behind,
        which is what :mod:`companion.recovery` is for. Narrowing the window
        further would need a transaction across two files; making the window
        harmless was the cheaper and more honest fix.
        """
        tip, _ = self.store.tip(session.session_id)
        current = session.touch(self.clock.wall(), revision=tip)
        self.store.save_session(current)
        self._sessions[current.session_id] = current
        if task is not None:
            if authoritative:
                # The caller *is* the authority for this task's state —
                # cancellation recording its own final `cancelled`/`complete`.
                # A protective write here would refuse, because the task it is
                # about to write is exactly the terminal one it checks for.
                self.store.save_task(task)
            else:
                # The run path. Protective, so a phase that finished a moment
                # after somebody cancelled cannot put its stale `executing` back
                # over the cancellation — which is how a cancel landing during
                # review or result used to be erased on its way to `completed`.
                self._save_running_task(task)
        return current

    # -- sessions ----------------------------------------------------------

    def create_session(
        self,
        title: str,
        *,
        privacy_policy: PrivacyPolicy | None = None,
        cost_policy: CostPolicy | None = None,
        locality_preference: str = "device-only",
    ) -> CompanionSession:
        session = CompanionSession.create(
            session_id=self.ids.next("ses"),
            title=title,
            now=self.clock.wall(),
            privacy_policy=privacy_policy,
            cost_policy=cost_policy,
            locality_preference=locality_preference,
        )
        self._sessions[session.session_id] = session
        self.store.save_session(session)
        self._emit(
            session.session_id, "", "session_created",
            {
                "title": session.title,
                "privacyPolicy": session.privacy_policy.to_json(),
                "costPolicy": session.cost_policy.to_json(),
                "localityPreference": session.locality_preference,
            },
            producer="user",
            # The session's own default class, not "internal": the title is the
            # user's words, and an export for a remote or audit audience must
            # withhold it like any other thing the user typed. The policy
            # blocks beside it are declared runtime fact, because they are what
            # an auditor reads to check "nothing was permitted to leave this
            # device" — pinning the whole event at the title's class withheld
            # those too.
            classification=session.privacy_policy.default_classification,
            internal_fields=("privacyPolicy", "costPolicy", "localityPreference"),
        )
        return self._checkpoint(self._sessions[session.session_id])

    def session(self, session_id: str) -> CompanionSession:
        cached = self._sessions.get(session_id)
        if cached is not None:
            return cached
        loaded = self.store.load_session(session_id)
        if loaded is None:
            raise CompanionError(f"no session {session_id!r} exists in this store")
        self._sessions[session_id] = loaded
        return loaded

    def sessions(self) -> tuple[CompanionSession, ...]:
        found = []
        for session_id in self.store.session_ids():
            loaded = self.store.load_session(session_id)
            if loaded is not None:
                found.append(loaded)
        return tuple(found)

    def pause_session(self, session_id: str) -> CompanionSession:
        session = self.session(session_id).paused(self.clock.wall())
        return self._checkpoint(session)

    def resume_session(self, session_id: str) -> CompanionSession:
        session = self.session(session_id).resumed(self.clock.wall())
        return self._checkpoint(session)

    def close_session(self, session_id: str) -> CompanionSession:
        session = self.session(session_id).closed(self.clock.wall())
        return self._checkpoint(session)

    # -- tasks -------------------------------------------------------------

    def submit_task(
        self,
        session_id: str,
        request: str,
        *,
        classification: str | None = None,
        data_locality: str | None = None,
        requires_offline: bool = False,
        cost_limit_units: int | None = None,
        execution_deadline_seconds: float | None = None,
    ) -> CompanionTask:
        """Record a request. Nothing is planned or run here.

        Submission is separate from execution so that a task exists — with an
        id, in the record — before anything is decided about it. A submission
        that only became visible once an executor accepted it would be invisible
        during exactly the window in which it might be refused.
        """
        session = self.session(session_id)
        if session.status == "closed":
            raise CompanionError(f"session {session_id} is closed and accepts no new tasks")
        task_id = self.ids.next("task")
        if self.store.load_task(session_id, task_id) is not None:
            # A task id that already exists would silently overwrite somebody
            # else's task document. Refused rather than deduplicated: the id
            # source has repeated itself, and continuing would hide that.
            raise CompanionError(
                f"a task with id {task_id!r} already exists in session {session_id}; "
                "the identifier source has repeated itself and nothing was written"
            )
        task = CompanionTask.create(
            task_id=task_id,
            session_id=session_id,
            request=request,
            now=self.clock.wall(),
            classification=classification or session.privacy_policy.default_classification,
            data_locality=data_locality or session.locality_preference,
            requires_offline=requires_offline,
            cost_limit_units=(
                cost_limit_units if cost_limit_units is not None else session.cost_policy.task_limit_units
            ),
            execution_deadline_seconds=(
                execution_deadline_seconds
                if execution_deadline_seconds is not None
                else self.policy.execution_deadline_seconds
            ),
        )
        self._emit(
            session_id, task.task_id, "task_created",
            {
                "summary": task.display_summary,
                "classification": task.classification,
                "dataLocality": task.data_locality,
                "requiresOffline": task.requires_offline,
                "costLimitUnits": task.cost_limit_units,
                "executionDeadlineSeconds": task.execution_deadline_seconds,
            },
            producer="user",
            classification=task.classification,
            # The summary is the user's words and carries the task's class. The
            # rest is declared runtime fact, and pinning the whole event at the
            # summary's class withheld it — so a `secret` task's own privacy
            # indicator arrived at the surface as "[withheld: secret]", which is
            # the one field that exists to say a task is secret. Same reasoning
            # and same fix as `session_created`'s policy blocks above.
            internal_fields=(
                "classification", "dataLocality", "requiresOffline",
                "costLimitUnits", "executionDeadlineSeconds",
            ),
        )
        session = session.with_task(task.task_id, self.clock.wall())
        self._sessions[session_id] = session
        self._checkpoint(session, task)
        return task

    def task(self, session_id: str, task_id: str) -> CompanionTask:
        loaded = self.store.load_task(session_id, task_id)
        if loaded is None:
            raise CompanionError(f"no task {task_id!r} exists in session {session_id!r}")
        return loaded

    def find_task(self, task_id: str) -> tuple[str, CompanionTask]:
        """Locate a task by id alone, for the CLI. Linear, and small on purpose."""
        for session_id in self.store.session_ids():
            loaded = self.store.load_task(session_id, task_id)
            if loaded is not None:
                return session_id, loaded
        raise CompanionError(f"no task {task_id!r} exists in this store")

    def events(self, session_id: str, *, task_id: str | None = None) -> tuple[TaskEvent, ...]:
        return self.store.read_events(session_id, task_id=task_id)

    # -- the pipeline ------------------------------------------------------

    def run_task(self, session_id: str, task_id: str) -> CompanionTask:
        """Carry one task from ``created`` to a terminal or parked state.

        Synchronous by design for this phase. Concurrency across *tasks* works
        already — each task has its own lease and its own events — and the
        scheduler that would run several at once belongs with the UX shell,
        which is the thing that will have opinions about how many at a time.
        """
        session = self.session(session_id)
        task = self.task(session_id, task_id)
        if task.terminal:
            return task
        try:
            # Entered at whichever phase the task is actually in. Recovery parks
            # a resumable task at `classifying` or `planning`, and this is what
            # makes those parks resumable rather than decorative: the pipeline
            # picks it up there instead of insisting on a fresh `created`.
            if task.state == "created":
                task = self._transition(task, "classifying")
            if task.state == "classifying":
                task = self._classify(session, task)
            if task.state == "waiting_for_capability":
                decision, task = self._check_capability(session, task)
            else:
                decision = self._capability_decision(session, task)
            if task.state == "waiting_for_executor":
                task = self._select_executor(session, task, decision)
            else:
                task = self._reattach_executor(task, decision)
            task = self._plan_and_execute(session, task, decision)
        # Each handler re-reads the task and then checks whether somebody has
        # already stopped it. Without that check the runner's own verdict
        # overwrote theirs: a task paused while its question was on screen
        # raised ApprovalError a moment later — because the question had been
        # withdrawn, which is exactly what pausing does — and the handler wrote
        # `blocked` over the `paused` that had just been persisted. The user
        # pressed pause and the task reported itself blocked.
        #
        # The check belongs here rather than inside `_block`, because failing
        # is not the same as being stopped: a task that genuinely faulted
        # should record that even if it was also cancelled, whereas a refusal
        # caused *by* the stop should not.
        except CapabilityRefused as exc:
            task = self._block_unless_stopped(
                session, session_id, task, str(exc), exc.reasons
            )
        except CoordinationLimitExceeded as exc:
            task = self._fail(session, self._latest(session_id, task), "coordination_limit", str(exc))
        except ApprovalError as exc:
            task = self._block_unless_stopped(
                session, session_id, task, str(exc), (str(exc),)
            )
        except (MalformedOutput, ExecutorUnavailable) as exc:
            task = self._fail(session, self._latest(session_id, task), "executor_fault", str(exc))
        finally:
            self.leases.release(task_id)
        return task

    def _block_unless_stopped(
        self,
        session: CompanionSession,
        session_id: str,
        task: CompanionTask,
        summary: str,
        reasons: Sequence[str],
    ) -> CompanionTask:
        """Block the task, unless somebody has already stopped it.

        A pause or a cancellation withdraws the task's outstanding questions,
        and withdrawing them is what makes the runner's next approval check
        raise. Blocking on that refusal would be recording the *consequence* of
        the user's action as a fault of the task's own, over the top of the
        state they asked for.

        Under the lifecycle lock, because reading the state and writing over it
        have to be one step. Checking first and blocking afterwards was still
        wrong, just less often: the pause landed in between, the check saw a
        task that was not yet stopped, and `blocked` went over the `paused` that
        arrived a moment later. The event order showed the block first and the
        store disagreed, which is what two writers on one document look like.
        """
        with self._lifecycle_guard:
            current = self._latest(session_id, task)
            stopped = self._stopped(current)
            if stopped is not None:
                return stopped
            return self._block(session, current, summary, reasons)

    def _register_waiter(self, request) -> bool:
        """Take a consent waiter before the question becomes durable.

        Optional on the consent source. A blocking source — the Approval Centre
        — needs it, because it is the one with a window to lose an answer in. A
        non-blocking source answers inside the same call that asks, so there is
        no window and nothing to register; ``RefusingConsent`` and
        ``ScriptedConsent`` implement neither method and are handled here rather
        than made to grow a pair of no-ops each.
        """
        register = getattr(self.gate.consent, "register", None)
        if register is None:
            return True
        return bool(register(request))

    def _unregister_waiter(self, request_id: str) -> None:
        unregister = getattr(self.gate.consent, "unregister", None)
        if unregister is not None:
            unregister(request_id)

    def _stopped(self, task: CompanionTask) -> CompanionTask | None:
        """The persisted task, if something has stopped it; otherwise ``None``.

        Read from the store rather than from the in-memory copy. Cancellation is
        written by whoever asked for it — possibly another process — and the
        runner's own copy will still say the task is running. Checking at each
        phase boundary is what stops a cancelled task being carried through
        review, result and completion by a loop that never looked again.

        ``paused`` counts, and did not always. ``pause_task`` writes the pause
        from another caller exactly as ``cancel`` writes a cancellation, and the
        runner used to carry straight on and put its own ``executing`` back over
        it at the next save — so a pause issued through the Approval Centre or
        the CLI appeared to work and then silently undid itself. Pausing is not
        cancelling and needs its own entry rather than a shared flag, but it
        needs the same protection.
        """
        persisted = self.store.load_task(task.session_id, task.task_id)
        if persisted is None:
            return None
        if persisted.terminal or persisted.cancellation_state != "none" or persisted.state == "paused":
            return persisted
        return None

    def _save_running_task(self, task: CompanionTask) -> CompanionTask:
        """Write a task the runtime is driving, without erasing a cancellation.

        Cancellation is owned by whoever asked for it, not by whoever is
        running. ``bunny-os companion task cancel`` writes the request from
        another process; the runner's next ``save_task`` would put its own
        in-memory copy — which still says ``none`` — straight over the top, and
        the cancellation would vanish between two operations. So the persisted
        cancellation fields are read back and merged in before every write from
        the run path. The canceller itself writes directly; it is the source.
        """
        # Under the lifecycle lock, because reading the persisted task and
        # writing over it is a check followed by an act, and pausing is exactly
        # the thing that happens in between. Traced: a pause and the runner's
        # block both observed `waiting_for_approval` and both proceeded, so the
        # block's write landed after the pause's and the user's pause was lost.
        # Holding the lock across the pair is what makes the guard mean
        # anything. Reentrant, so the callers that already hold it — the
        # lifecycle transitions themselves — are unaffected.
        with self._lifecycle_guard:
            return self._save_running_task_locked(task)

    def _save_running_task_locked(self, task: CompanionTask) -> CompanionTask:
        persisted = self.store.load_task(task.session_id, task.task_id)
        if persisted is not None and (
            persisted.terminal
            or persisted.cancellation_state != "none"
            or persisted.state == "paused"
        ):
            # Somebody else has taken this task terminal, begun stopping it, or
            # paused it.
            # The runner has lost authority over the document and writes
            # nothing — not even a merge, because its `state` field is stale too
            # and writing it back would resurrect a cancelled task as
            # `executing`. Whatever the runner still has to say goes into the
            # event stream, which is authoritative anyway and from which
            # recovery rebuilds the ledger.
            return persisted
        if persisted is not None and persisted.lifecycle_epoch > task.lifecycle_epoch:
            # The task was paused and resumed while this phase was in flight, so
            # the copy about to be written is from the previous attempt and
            # carries the previous epoch. Writing it would reset the epoch, and
            # the epoch is the only thing separating this attempt's approval
            # outcomes from the last one's — an outcome from before the resume
            # would start matching again.
            #
            # Merged rather than refused, for the same reason the cancellation
            # fields are merged: the runner still has legitimate progress to
            # record, and only this one field is stale. Monotonic, so taking the
            # larger value is always the newer one.
            task = replace(task, lifecycle_epoch=persisted.lifecycle_epoch)
        self.store.save_task(task)
        return task

    def _latest(self, session_id: str, fallback: CompanionTask) -> CompanionTask:
        """The most recently written projection of a task.

        An exception unwinds past every local the phases had built up, so the
        handlers would otherwise park a task using a value from before the phase
        that failed — losing, among other things, the approval reference that
        records what was asked. The store has the later version, because each
        phase writes as it goes.
        """
        try:
            stored = self.store.load_task(session_id, fallback.task_id)
        except CompanionError:
            return fallback
        return stored if stored is not None else fallback

    # -- phases ------------------------------------------------------------

    def _classify(self, session: CompanionSession, task: CompanionTask) -> CompanionTask:
        task_type, capabilities = classify_request(task.original_request)
        task = replace(task, task_type=task_type, required_capabilities=capabilities)
        task = self._transition(task, "waiting_for_capability", {
            "taskType": task_type,
            "classification": task.classification,
            "requiredCapabilities": list(capabilities),
        })
        self._checkpoint(session, task)
        return task

    def _capability_decision(self, session: CompanionSession, task: CompanionTask) -> CapabilityDecision:
        """Ask the capability runtime, without moving the task.

        Used when the pipeline is re-entered at a later phase. The question is
        asked again rather than the previous answer reused: the machine may have
        changed while the runtime was not running, and a resumed task must not
        act on a capability decision taken before a reboot.
        """
        decision = evaluate_task(
            task, session, tuple(self._executors.values()), self.options.assessment,
            providers=self.options.providers,
        )
        if not decision.eligible:
            raise CapabilityRefused(
                "no executor is eligible for this task on this machine under this policy",
                reasons=decision.blocked_reasons,
            )
        return decision

    def _reattach_executor(self, task: CompanionTask, decision: CapabilityDecision) -> CompanionTask:
        """Take the lease again for a task the pipeline re-entered mid-flight."""
        executor_id = task.executor_id or decision.selected_executor
        if executor_id not in self._executors:
            raise ExecutorUnavailable(
                f"executor {executor_id!r} held this task and is not configured in this runtime"
            )
        if self.leases.holder(task.task_id) != executor_id:
            self.leases.acquire(task.task_id, executor_id, now=self.clock.monotonic())
        return replace(task, executor_id=executor_id)

    def _check_capability(
        self, session: CompanionSession, task: CompanionTask
    ) -> tuple[CapabilityDecision, CompanionTask]:
        decision = evaluate_task(
            task, session, tuple(self._executors.values()), self.options.assessment,
            providers=self.options.providers,
        )
        target = "waiting_for_executor" if decision.eligible else "blocked"
        task = self._transition(task, target, {
            "planId": decision.plan_id,
            "planFingerprint": decision.plan_fingerprint,
            "eligible": decision.eligible,
            "reasons": list(decision.blocked_reasons),
            "signals": dict(decision.signals),
            "executors": [item.to_json() for item in decision.eligibility],
        }, audit_reference=decision.plan_id)
        task = replace(task, capability_plan_reference=decision.plan_fingerprint)
        self._checkpoint(session, task)
        if not decision.eligible:
            raise CapabilityRefused(
                "no executor is eligible for this task on this machine under this policy",
                reasons=decision.blocked_reasons,
            )
        return decision, task

    def _select_executor(
        self, session: CompanionSession, task: CompanionTask, decision: CapabilityDecision
    ) -> CompanionTask:
        executor = self.executor(decision.selected_executor)
        if executor is None:
            raise ExecutorUnavailable(f"executor {decision.selected_executor!r} is not configured")
        health = executor.health()
        if not health.ready:
            raise ExecutorUnavailable(
                f"executor {decision.selected_executor!r} is not ready: {health.detail or 'no detail given'}"
            )
        self.leases.acquire(task.task_id, decision.selected_executor, now=self.clock.monotonic())
        self._emit(
            task.session_id, task.task_id, "executor_selected",
            {
                "executorId": decision.selected_executor,
                "local": executor.declaration.local,
                "declaration": executor.declaration.to_json(),
                "health": health.to_json(),
                "planId": decision.plan_id,
            },
            classification=task.classification,
            audit_reference=decision.plan_id,
        )
        reviewers = self.reviewer_ids()
        self.policy.check_reviewers(len(reviewers))
        self._emit(
            task.session_id, task.task_id, "reviewer_selected",
            {"reviewerIds": list(reviewers), "contextCeiling": self.policy.reviewer_context_ceiling},
            classification=task.classification,
        )
        task = replace(task, executor_id=decision.selected_executor, reviewer_ids=reviewers)
        session = session.with_selection(
            executor=decision.selected_executor,
            reviewers=reviewers,
            plan_reference=decision.plan_fingerprint,
        )
        self._sessions[session.session_id] = session
        self._checkpoint(session, task)
        return task

    def _plan_and_execute(
        self, session: CompanionSession, task: CompanionTask, decision: CapabilityDecision
    ) -> CompanionTask:
        executor = self._executors[task.executor_id]
        observations: tuple[Mapping[str, Any], ...] = ()
        operation_results: list[Mapping[str, Any]] = []
        result: TaskResult | None = None

        while True:
            stopped = self._stopped(task)
            if stopped is not None:
                return stopped
            revision = task.plan_revision + 1
            task = replace(task, plan_revision=revision)

            # Planning happens before the transition, so that the single
            # `planning_started` event carries the plan it is about. Planning is
            # a proposal and has no side effects, so nothing has happened by the
            # time the state catches up.
            plan = executor.plan(context_for(
                task, plan_revision=revision, observations=observations,
                operation_results=operation_results,
                remaining_cost_units=max(0, task.cost_limit_units - task.spent_cost_units),
            ))
            if not isinstance(plan, TaskPlan):
                raise MalformedOutput(
                    f"executor {task.executor_id!r} returned {type(plan).__name__} where a TaskPlan was required"
                )
            if task.state == "planning":
                # Re-entered here by recovery. The task is already in the phase,
                # so the event is emitted directly rather than by a transition
                # the table would rightly refuse.
                self._emit(
                    task.session_id, task.task_id, "planning_started",
                    {"planRevision": revision, "plan": plan.to_json()},
                    producer=f"executor:{task.executor_id}",
                    classification=task.classification,
                )
            else:
                task = self._transition(
                    task, "planning",
                    {"planRevision": revision, "plan": plan.to_json()},
                    producer=f"executor:{task.executor_id}",
                )

            task = self._settle_approvals(session, task, plan, executor, decision)
            stopped = self._stopped(task)
            if stopped is not None:
                # Approvals are where a task spends most of its wall-clock time
                # with a person looking at it, so this is where a stop lands.
                # `_settle_approvals` already returns the stopped task, but
                # returning it was not enough: `_execute_plan` would still be
                # called with it and, for a pause, would run the plan anyway —
                # its own guard only looked at the cancellation fields.
                return stopped
            task, results = self._execute_plan(session, task, plan)
            operation_results = list(results)

            stopped = self._stopped(task)
            if stopped is not None:
                # Cancellation landed while the plan was running. The loop ends
                # here: no review, no result, no completion. Without this the
                # runtime would carry a cancelled task through to `completed`
                # and write `task_completed` after `task_cancelled` — which is
                # not merely untidy, it is the record asserting that a task the
                # user stopped finished normally.
                return stopped

            task, observations, revise = self._review(session, task, plan)

            stopped = self._stopped(task)
            if stopped is not None:
                # Review can take `maximum_reviewers × reviewer_timeout_seconds`
                # — twenty seconds by default — and a cancel landing inside that
                # window used to sail past here into a result and a completion.
                return stopped

            if not revise:
                result = executor.result(context_for(
                    task, plan_revision=revision, observations=observations,
                    operation_results=operation_results,
                ))
                # And again after the executor produced the result, which is
                # unbounded: it is third-party code and may take as long as it
                # likes. Every phase boundary asks, because "the loop checks"
                # was exactly the assumption that left two of them open.
                stopped = self._stopped(task)
                if stopped is not None:
                    return stopped
                break
            # Round the loop. The next revision supersedes this plan, which
            # invalidates every approval granted against it — done explicitly
            # rather than left to expiry, so a superseded consent cannot be
            # spent inside its remaining time. The next revision asks again.
            withdrawn = self.gate.invalidate_for_task(
                task,
                detail=(
                    f"plan {plan.plan_id} revision {plan.revision} was superseded in response to "
                    "review; consent given for it does not carry over"
                ),
                terminal_state="superseded",
            )
            if withdrawn:
                self._emit(
                    task.session_id, task.task_id, "approval_resolved",
                    {
                        "requestId": withdrawn[0],
                        "decision": "expired",
                        "supersededPlanId": plan.plan_id,
                        "supersededRevision": plan.revision,
                        "withdrawn": list(withdrawn),
                    },
                    producer="policy",
                    classification=task.classification,
                )

        if not isinstance(result, TaskResult):
            raise MalformedOutput(
                f"executor {task.executor_id!r} returned {type(result).__name__} where a TaskResult was required"
            )
        return self._present(session, task, result)

    def _settle_approvals(
        self,
        session: CompanionSession,
        task: CompanionTask,
        plan: TaskPlan,
        executor: Executor,
        decision: CapabilityDecision,
    ) -> CompanionTask:
        """Ask about everything that needs asking, and act on nothing until answered."""
        selection = decision.selection()
        requirements = requirements_for(
            task, session, plan,
            executor_is_local=executor.declaration.local,
            executor_provider_id=executor.declaration.provider_id if not executor.declaration.local else "",
            executor_cost_class=executor.declaration.cost_class,
            broker=self.broker,
            provider_declaration={"routeTarget": decision.route.target, "providerId": decision.route.provider_id}
            if selection is not None and selection.destination != "local" else None,
        )
        if not requirements:
            return task

        # Transition ids are derived from the plan, so the id of the first
        # request is known before it is raised. The transition event can
        # therefore name the actual request rather than a placeholder, which
        # matters because a reader following the stream should be able to get
        # from "this task started waiting" to "for this question" in one hop.
        transition_ids = [
            self.gate.transition_id(plan, index, requirement)
            for index, requirement in enumerate(requirements)
        ]
        task = self._transition(task, "waiting_for_approval", {
            "requestId": f"approval:{task.task_id}:{transition_ids[0]}",
            "action": requirements[0].action,
            "destination": requirements[0].destination,
            "planId": plan.plan_id,
            "requirementCount": len(requirements),
            # Marks this as the *transition* into waiting, not one of the
            # individual questions that follow. Both are `approval_requested`;
            # a consumer that could not tell them apart would count the first
            # question twice.
            "batch": True,
        })

        last_request_id = ""
        for index, requirement in enumerate(requirements):
            transition_id = transition_ids[index]
            # Prepared and *written down* before anybody is asked. With an
            # Approval Centre attached the ask blocks for as long as a person
            # takes; emitting afterwards left the stream silent for exactly that
            # window, so a client reconnecting while the user was being asked
            # something replayed a task that looked like it was quietly working.
            # See companion.approvals.ApprovalGate.prepare.
            # §4's order, and the order matters at every step.
            #
            # 1. Build the identity. Nothing is visible yet: no store, no
            #    stream, no task document.
            request, reference = self.gate.build(
                task, requirement, plan, transition_id=transition_id, now=self.clock.monotonic(),
            )
            # 2. Register the waiter, *before* the question is persisted. The
            #    durable write is what makes a question displayable, so
            #    registering after it left a window in which a person could see
            #    a question and answer it with nothing listening.
            registered = self._register_waiter(request)
            if not registered:
                # Nothing was persisted, nothing was emitted, nothing can be
                # displayed and nothing is authorised. A question nobody can
                # answer must not exist at all.
                raise ApprovalInvalidated(
                    f"a consent waiter for {request.request_id!r} could not be taken; "
                    "the question was not raised"
                )
            # 3. Persist. From here the question is real and answerable.
            try:
                response = self.gate.persist(request)
            except Exception:
                # Roll the registration back. A waiter for a question that does
                # not exist would hold a worker on something nobody can see.
                self._unregister_waiter(request.request_id)
                raise
            reference = replace(reference, decision=response.decision)
            task = task.with_approval(reference)
            self._emit(
                task.session_id, task.task_id, "approval_requested",
                {
                    "requestId": request.request_id,
                    "action": request.action,
                    "destination": request.destination,
                    "planId": plan.plan_id,
                    "planRevision": plan.revision,
                    "request": request.to_json(),
                    "requirement": requirement.to_json(),
                },
                classification=task.classification,
                audit_reference=plan.plan_id,
            )
            # Protective, like every other write on the run path. This was the
            # last unprotected one, and it was the worst: a real Approval Centre
            # blocks here, so this is where a task spends most of its wall-clock
            # time and precisely the moment a user is looking at a dialog and
            # most likely to press stop. An unprotected write here erased the
            # cancellation and the plan ran on — including the operations that
            # had needed consent in the first place.
            task = self._save_running_task(task)

            stopped = self._stopped(task)
            if stopped is not None:
                return stopped

            # The blocking half. An interactive consent source parks here until
            # somebody answers or the request expires; the refusing default
            # returns immediately. Either way the question is already in the
            # stream above, so a client that connects during the wait sees it.
            self.gate.seek_consent(
                request, plan, transition_id=transition_id, now=self.clock.monotonic(),
            )

            stopped = self._stopped(task)
            if stopped is not None:
                # Somebody pressed stop while the question was on screen. This
                # is the most likely moment for it and the check has to be
                # after the wait, not only before it.
                return stopped

            try:
                resolved = self.gate.resolve(
                    task, request.request_id,
                    plan=plan, requirement=requirement, transition_id=transition_id,
                    now=self.clock.monotonic(),
                )
            except ApprovalError as exc:
                # The terminal state comes from the exception, not from a
                # constant. This line used to say "denied" for every failure
                # here, which meant a question withdrawn because somebody
                # pressed pause was written into the record as a refusal by the
                # person. It was not: `ApprovalGate.invalidate_for_task` had
                # already recorded it as withdrawn, and this overwrote that with
                # a denial — which then outranked the pause in the presentation
                # fold and made a paused task project as blocked. Only
                # ApprovalDenied means somebody said no.
                state = getattr(exc, "terminal_state", "invalidated")
                previous = self.approvals.decision_for(request.request_id)
                # The reference records what happened too, and it also used to
                # say "denied" for everything. It is read back by
                # `_fill_required` when the task transitions to blocked, so a
                # wrong value here reappears as a second wrong event.
                task = task.with_approval(replace(
                    reference,
                    decision="denied" if state in USER_REFUSAL_STATES else "expired",
                ))
                self._emit(
                    task.session_id, task.task_id, "approval_resolved",
                    terminal_record(
                        request_id=request.request_id,
                        task_id=task.task_id,
                        plan_id=plan.plan_id,
                        transition_id=transition_id,
                        state=state,
                        previous_state=(
                            previous.decision if previous is not None else "pending"
                        ),
                        reason=str(exc),
                        actor="user" if state in USER_REFUSAL_STATES else "system",
                        at=iso8601(self.clock.wall()),
                        binding_digest=reference.destination_fingerprint,
                        lifecycle_epoch=task.lifecycle_epoch,
                    ),
                    classification=task.classification,
                )
                self._checkpoint(session, task)
                raise
            task = task.with_approval(resolved)
            last_request_id = request.request_id
            answer = self.approvals.decision_for(request.request_id)
            self._emit(
                task.session_id, task.task_id, "approval_resolved",
                {
                    **terminal_record(
                        request_id=request.request_id,
                        task_id=task.task_id,
                        plan_id=plan.plan_id,
                        transition_id=transition_id,
                        state="approved",
                        previous_state="pending",
                        reason="the user approved this step",
                        actor=answer.responder if answer is not None else "user",
                        at=iso8601(self.clock.wall()),
                        binding_digest=reference.destination_fingerprint,
                        lifecycle_epoch=task.lifecycle_epoch,
                    ),
                    "planRevision": plan.revision,
                    "responder": answer.responder if answer is not None else "user",
                },
                producer="user",
                classification=task.classification,
                audit_reference=plan.plan_id,
            )
        self._checkpoint(session, task)
        stopped = self._stopped(task)
        if stopped is not None:
            return stopped
        return self._transition(task, "executing", {
            "requestId": last_request_id,
            "decision": "granted",
            "planRevision": plan.revision,
        })

    def _execute_plan(
        self, session: CompanionSession, task: CompanionTask, plan: TaskPlan
    ) -> tuple[CompanionTask, tuple[Mapping[str, Any], ...]]:
        if task.state == "planning":
            task = self._transition(task, "executing", {"planRevision": plan.revision})

        results: list[Mapping[str, Any]] = []
        started_at_monotonic = self.clock.monotonic()
        keys = plan.keys_for(task.task_id)
        completed = task.completed_operation_keys()
        unknown = task.unknown_operation_keys()
        # What each already-completed operation produced, read out of the stream
        # rather than remembered. After a restart the runtime has no memory, and
        # the stream is the only thing that does.
        previous_values = {
            str(event.payload.get("operationKey", "")): event.payload.get("value")
            for event in self.events(task.session_id, task_id=task.task_id)
            if event.event_type == "operation_completed"
        }

        for index, operation in enumerate(plan.operations):
            # Re-read rather than trust the in-memory copy. Cancellation can
            # arrive from another process — `bunny-os companion task cancel`
            # while this one is running — and the executor lease is in-memory,
            # so it does not stop that. This read is what *notices*; the refusal
            # in `_save_running_task` to write over a cancelled task is what
            # keeps there being something to notice, since the runner would
            # otherwise put its own stale copy back before the next iteration.
            # Both are needed, and removing either fails a different test.
            persisted = self.store.load_task(task.session_id, task.task_id)
            if persisted is not None and persisted.cancellation_state != "none":
                task = replace(
                    task,
                    cancellation_state=persisted.cancellation_state,
                    cancellation_cause=persisted.cancellation_cause,
                )
            if task.cancellation_state != "none":
                break
            if persisted is not None and persisted.state == "paused":
                # A pause landed between two operations. Stopping here rather
                # than at the end of the plan is the difference between pausing
                # and asking politely.
                task = persisted
                break
            key = keys[index]
            if key in completed:
                # The record proves this act already happened. It is not done
                # again, and the value it produced is carried forward out of the
                # stream so the result is built from what actually occurred
                # rather than from a hole where the operation used to be.
                results.append({
                    "name": operation.name,
                    "value": previous_values.get(key),
                    "skipped": "already completed",
                    "operationKey": key,
                })
                self._emit(
                    task.session_id, task.task_id, "operation_progress",
                    {
                        "operationKey": key, "progress": round((index + 1) / max(1, len(plan.operations)), 3),
                        "skipped": True,
                        "reason": "this operation is already recorded as completed and was not repeated",
                    },
                    classification=task.classification,
                )
                continue
            if key in unknown:
                # The load-bearing refusal. This operation was started and
                # nothing settled it; whether it happened is not known, and
                # §15's rule is that an operation is not repeated merely because
                # its completion event was missing. So it is skipped, said so,
                # and handed back to the executor as unknown — which is a fact it
                # can plan around, unlike a silent retry.
                results.append({
                    "name": operation.name,
                    "value": None,
                    "unknown": True,
                    "operationKey": key,
                })
                self._emit(
                    task.session_id, task.task_id, "operation_progress",
                    {
                        "operationKey": key, "progress": round((index + 1) / max(1, len(plan.operations)), 3),
                        "skipped": True,
                        "reason": (
                            "this operation began before the runtime stopped and nothing settled it; "
                            "whether it happened is not known, so it was not repeated"
                        ),
                    },
                    classification=task.classification,
                )
                continue

            self.policy.check_tool_calls(task.tool_call_count)
            self.policy.check_events(len(self.events(task.session_id, task_id=task.task_id)))
            # The deadline, actually enforced. `check_deadline` had no callers
            # and `deadlineConsumedSeconds` was never written, so a ceiling the
            # policy advertised and the schema documented did nothing at all.
            # Checked between operations rather than during one: the runtime can
            # decline to start the next act, and cannot interrupt the current.
            consumed = self.clock.monotonic() - started_at_monotonic + task.deadline_consumed_seconds
            self.policy.check_deadline(consumed, task_deadline=task.execution_deadline_seconds)
            self.policy.check_cost(
                task.spent_cost_units, operation.estimated_cost_units, task_limit=task.cost_limit_units
            )

            self._emit(
                task.session_id, task.task_id, "operation_started",
                {
                    "operationKey": key, "name": operation.name, "tool": operation.tool,
                    "destination": operation.destination, "planRevision": plan.revision,
                },
                classification=task.classification,
            )
            task = task.with_operation(OperationReference(
                key=key, name=operation.name, status="started",
                started_sequence=self.store.tip(task.session_id)[0],
            ))
            task = replace(task, tool_call_count=task.tool_call_count + 1)
            task = self._save_running_task(task)

            outcome = self.broker.invoke(
                operation.tool, operation.arguments,
                caller="runtime", classification=task.classification,
            )
            self._emit(
                task.session_id, task.task_id, "operation_progress",
                {"operationKey": key, "progress": round((index + 1) / max(1, len(plan.operations)), 3)},
                classification=task.classification,
            )
            if outcome.ok:
                self._emit(
                    task.session_id, task.task_id, "operation_completed",
                    {"operationKey": key, "name": operation.name, "value": outcome.value},
                    classification=task.classification,
                )
                task = task.with_operation(OperationReference(
                    key=key, name=operation.name, status="completed",
                    started_sequence=(task.operation(key) or OperationReference(key=key, name=operation.name)).started_sequence,
                    settled_sequence=self.store.tip(task.session_id)[0],
                ))
                results.append({"name": operation.name, "value": outcome.value, "detail": outcome.detail})
            else:
                self._emit(
                    task.session_id, task.task_id, "operation_failed",
                    {"operationKey": key, "name": operation.name, "error": outcome.detail},
                    classification=task.classification,
                )
                task = task.with_operation(OperationReference(
                    key=key, name=operation.name, status="failed",
                    started_sequence=(task.operation(key) or OperationReference(key=key, name=operation.name)).started_sequence,
                    settled_sequence=self.store.tip(task.session_id)[0],
                ))
                task = task.with_error(ErrorReference(
                    code="operation_failed", summary=display_summary(outcome.detail),
                    producer="runtime", sequence=self.store.tip(task.session_id)[0],
                ))
                results.append({"name": operation.name, "value": None, "error": outcome.detail})
            task = task.with_progress((index + 1) / max(1, len(plan.operations)) * 0.8)
            task = replace(
                task,
                spent_cost_units=task.spent_cost_units + operation.estimated_cost_units,
            )
            task = self._save_running_task(task)

        task = replace(
            task,
            deadline_consumed_seconds=(
                task.deadline_consumed_seconds + max(0.0, self.clock.monotonic() - started_at_monotonic)
            ),
        )
        self._checkpoint(session, task)
        return task, tuple(results)

    def _review(
        self, session: CompanionSession, task: CompanionTask, plan: TaskPlan
    ) -> tuple[CompanionTask, tuple[Mapping[str, Any], ...], bool]:
        """Run one review round and decide whether the executor gets another go."""
        if not self._reviewers:
            return task, (), False

        task = self._transition(task, "reviewing")
        round_number = task.review_rounds + 1
        context = reviewer_context(
            task_view=task.view("reviewer"),
            plan_view=plan.to_review_json(),
            event_views=[event.view("reviewer") for event in self.events(task.session_id, task_id=task.task_id)],
            classification=task.classification,
            policy=self.policy,
            round_number=round_number,
        )
        outcome: ReviewRound = run_review_round(
            tuple(self._reviewers.values()), context, self.policy, round_number=round_number
        )
        task = replace(task, review_rounds=round_number)

        for observation in outcome.observations:
            self._emit(
                task.session_id, task.task_id, "reviewer_observation",
                {**observation.to_json(), "roundNumber": round_number},
                producer=f"reviewer:{observation.reviewer_id}",
                classification=task.classification,
            )
        for observation in outcome.disagreements:
            # Recorded separately and never retracted. §10 requires material
            # disagreement to remain visible even after the executor revises,
            # so this event stands in the stream next to whatever came after it.
            self._emit(
                task.session_id, task.task_id, "reviewer_disagreement",
                {**observation.to_json(), "roundNumber": round_number},
                producer=f"reviewer:{observation.reviewer_id}",
                classification=task.classification,
            )
        for reviewer_id, detail in outcome.absent:
            self._emit(
                task.session_id, task.task_id, "reviewer_observation",
                {
                    "reviewerId": reviewer_id, "severity": "info", "category": "policy",
                    "summary": f"This reviewer produced no observation: {display_summary(detail)}",
                    "suggestedAction": "", "evidenceEventIds": [], "absent": True,
                    "roundNumber": round_number,
                },
                classification=task.classification,
            )

        observations = tuple(item.to_json() for item in outcome.observations)
        revise = bool(outcome.disagreements)
        if revise:
            try:
                self.policy.check_review_rounds(task.review_rounds)
            except CoordinationLimitExceeded:
                # The ceiling stops the loop; it does not erase the objection.
                revise = False
        self._checkpoint(session, task)
        return task, observations, revise

    def _present(self, session: CompanionSession, task: CompanionTask, result: TaskResult) -> CompanionTask:
        task = self._transition(task, "presenting", {
            "resultId": result.result_id,
            "result": result.to_json(),
        })
        for output in result.outputs:
            task = task.with_output(OutputReference(
                output_id=output.output_id, kind=output.kind, digest=output.digest,
                byte_size=output.byte_size, classification=output.classification,
                summary=display_summary(output.content), created_sequence=self.store.tip(task.session_id)[0],
            ))
        task = self._transition(task, "completed", {"resultId": result.result_id})
        task = task.finished(self.clock.wall())
        session = self.session(task.session_id).task_finished(task.task_id, self.clock.wall())
        self._sessions[session.session_id] = session
        self._checkpoint(session, task)
        return task

    # -- parking -----------------------------------------------------------

    def _block(
        self, session: CompanionSession, task: CompanionTask, summary: str, reasons: Sequence[str]
    ) -> CompanionTask:
        if task.terminal:
            # Something took this task terminal while the run path was raising —
            # a cancel, almost always. Parking it would be an illegal
            # transition, and letting that propagate would replace the real
            # diagnostic (why it was blocked) with a confusing one about the
            # state machine. The persisted task is returned unchanged.
            return task
        if task.state == "blocked":
            current = task
        else:
            current = self._transition(task, "blocked", {"reasons": list(reasons)})
        # The reasons travel with the error, not only in the event payload. A
        # user running `companion task inspect` on a blocked task should be told
        # what to do about it without having to read the whole stream.
        detail = summary
        if reasons:
            detail = f"{summary} — " + "; ".join(reasons[:3])
        current = current.with_error(ErrorReference(
            # A longer bound than an ordinary summary: this is the field that
            # has to answer "why can this not run", and three reasons cut off
            # mid-sentence answers it worse than no reasons at all.
            code="blocked", summary=display_summary(detail, limit=600), producer="runtime",
            sequence=self.store.tip(task.session_id)[0],
        ))
        session = self.session(task.session_id)
        self._checkpoint(session, current)
        return current

    def _fail(self, session: CompanionSession, task: CompanionTask, code: str, summary: str) -> CompanionTask:
        if task.terminal:
            # As in `_block`: already finished by somebody else, so there is
            # nothing to fail and no transition that would be legal.
            return task
        current = self._transition(task, "failed", {"error": display_summary(summary), "code": code})
        current = current.with_error(ErrorReference(
            code=code, summary=display_summary(summary), producer="runtime",
            sequence=self.store.tip(task.session_id)[0],
        )).finished(self.clock.wall())
        session = self.session(task.session_id).task_finished(task.task_id, self.clock.wall())
        self._sessions[session.session_id] = session
        self._checkpoint(session, current)
        return current

    def pause_task(self, session_id: str, task_id: str) -> CompanionTask:
        """Set a task aside, and take its outstanding questions off the screen.

        The withdrawal is the part that is easy to leave out. A paused task is
        not being run, so a question about it authorises nothing — and leaving
        it pending would keep an Approve button in front of somebody for work
        that has stopped, ticking towards an expiry they cannot see. It is the
        same rule cancellation applies in :mod:`companion.cancellation`, for the
        same reason, and resuming asks again rather than spending consent given
        before the pause.

        The order below is the whole of it, and it is the order rather than the
        steps that was wrong before. ``task_paused`` used to be emitted *first*,
        while the questions were still pending and their waiters still live — so
        a client that saw the pause and immediately re-read the projection could
        be shown an Approve button for a task that had already stopped. The
        questions are withdrawn and their waiters released before anything says
        the task is paused.
        """
        with self._lifecycle_guard:
            # 1-2. Under the lock, and only from a state that can pause.
            task = self.task(session_id, task_id)
            if task.state in TERMINAL_STATES:
                raise CompanionError(
                    f"task {task_id} is {task.state!r} and has already finished; "
                    "a finished task cannot be paused"
                )
            if task.state == "paused":
                # Idempotent rather than an error: two clients pressing pause is
                # not a fault, and the second must not withdraw a second time or
                # emit a second task_paused.
                return task

            paused_from = task.state

            # 3-4. Enumerate from the durable approval authority. The task
            # document is not enough on its own: a question is durable the
            # moment it is raised and reaches the task document only at the next
            # save, and that gap is exactly when somebody is looking at the
            # question and most likely to press pause.
            withdrawn = self.gate.invalidate_for_task(
                task,
                detail=(
                    f"task {task_id} was paused; this question no longer authorises anything "
                    "and will be asked again if the task resumes"
                ),
                terminal_state="cancelled-with-pause",
            )

            # 5-6. Release every waiter for those questions, including any the
            # worker has registered but not yet reached. Released with no
            # decision: pausing authorises nothing.
            self._release_waiters(task_id, withdrawn)

            # 7. The plan's authority is gone with the approvals, and the lease
            # is released so nothing may be started on this task's behalf.
            self.leases.release(task_id)

            # 8. Tell the executor, once, and do not wait on its answer. An
            # executor that hangs in `cancel` must not hold the pause open —
            # the same rule cancellation applies, for the same reason. Only
            # executors that declare support are called; the rest have nothing
            # to stop.
            self._signal_executor_paused(task)

            task = replace(task, approvals=tuple(
                replace(reference, decision="expired")
                if reference.request_id in withdrawn else reference
                for reference in task.approvals
            ))
            if withdrawn:
                # Before task_paused, so that no reader can observe a paused
                # task with a question still pending.
                self._emit(
                    session_id, task_id, "approval_resolved",
                    {
                        "requestId": withdrawn[0],
                        "decision": "cancelled-with-pause",
                        "withdrawn": list(withdrawn),
                        "pausedFrom": paused_from,
                        "lifecycleEpoch": task.lifecycle_epoch,
                        "reason": "the task was paused; the question was withdrawn, not answered",
                        "detail": "the task was paused; the question was withdrawn, not answered",
                    },
                    producer="policy",
                    classification=task.classification,
                )

            # 9-11. Now the state, the event and the projection.
            paused = self._transition(
                task, "paused", {"pausedFrom": paused_from}, paused_from=paused_from
            )
            # Authoritative, because this *is* the authority for pausing — the
            # same reason `resume_task` is authoritative for un-pausing, and
            # cancellation for cancelling.
            #
            # A protective write declines when it sees a task somebody else
            # has taken — and the runner, working from a phase that began before
            # the pause, is somebody else. Traced on Linux at about one run in
            # three: the runner read `waiting_for_approval`, reached its own
            # verdict, and the pause did not end up persisted. The exact
            # interleaving is not reconstructed here and is not claimed; what is
            # claimed is the rule, which is that whoever the user asked wins.
            # Everything the runner writes afterwards is protective and declines
            # against the pause, which is the half that already worked.
            self._checkpoint(self.session(session_id), paused, authoritative=True)
            return paused

    def _signal_executor_paused(self, task: CompanionTask) -> None:
        """Tell the executor the task is being set aside. Best effort, by design.

        Its answer is not waited on and its faults are swallowed rather than
        raised: an executor that throws on the way out does not get to stop a
        pause, because the steps that matter to the user have already happened
        by the time this runs.
        """
        if not task.executor_id:
            return
        executor = self.executor(task.executor_id)
        if executor is None or not executor.declaration.supports_cancellation:
            return
        try:
            executor.cancel(
                context_for(task, plan_revision=task.plan_revision), "paused"
            )
        except Exception:  # noqa: BLE001 - third-party code; its faults are not fatal
            pass

    def _release_waiters(self, task_id: str, request_ids: Sequence[str]) -> None:
        """Wake anything parked on a question that has just been withdrawn.

        Tolerant of a consent source with no waiters to release — the refusing
        and scripted sources answer inside the call that asks, so there is never
        anything parked on them.
        """
        consent = self.gate.consent
        abandon = getattr(consent, "abandon", None)
        if abandon is not None:
            abandon(task_id)
        unregister = getattr(consent, "unregister", None)
        if unregister is not None:
            for request_id in request_ids:
                unregister(request_id)

    def resume_task(self, session_id: str, task_id: str) -> CompanionTask:
        # Under the lifecycle lock, like pausing and cancelling. Every defect
        # this phase found had the same shape — two writers on one task
        # document, separated by a check that had gone stale by the time the
        # write happened — and resuming is a lifecycle transition with exactly
        # that structure. Locked before a gate had to find it.
        with self._lifecycle_guard:
            return self._resume_task_locked(session_id, task_id)

    def _resume_task_locked(self, session_id: str, task_id: str) -> CompanionTask:
        task = self.task(session_id, task_id)
        if task.state != "paused":
            raise CompanionError(f"task {task_id} is {task.state!r} and is not paused")
        target = task.paused_from or "classifying"
        # A new attempt, and it says so. §8: the questions this attempt asks are
        # new questions, and the outcomes recorded against the previous attempt
        # must not be able to authorise or display anything here. An unchanged
        # plan produces the same plan and transition ids on purpose — that is how
        # an answer which still applies is kept — so the epoch is the only field
        # that separates the two attempts, and the projection filters on it.
        epoch = task.lifecycle_epoch + 1
        resumed = self._transition(
            task, target, {"resumedTo": target, "lifecycleEpoch": epoch}
        )
        resumed = replace(resumed, paused_from="", lifecycle_epoch=epoch)
        # Authoritative, because this *is* the authority for un-pausing. The
        # protective write refuses when the persisted task is paused — which is
        # exactly what it is here, by definition — so a protective resume
        # emitted its event and then declined to write the document, leaving a
        # task whose stream said "resumed" and whose projection said "paused".
        self._checkpoint(self.session(session_id), resumed, authoritative=True)
        return resumed


def _iso(clock: Clock) -> str:
    from .clock import iso8601

    return iso8601(clock.wall())


#: How a recorded approval reference reads as a terminal state in the event
#: stream. The reference uses the durable store's vocabulary; the event uses the
#: companion's, and only one of them can say "a person refused".
_REFERENCE_TERMINAL_STATE = {
    "granted": "approved",
    "denied": "denied-by-user",
    "expired": "invalidated",
}


def _reference_terminal_state(reference: ApprovalReference | None, target: str) -> str:
    """What actually happened to the last approval, in the event's vocabulary.

    Falls back on the target only when there is no reference to read, which is a
    transition into ``blocked`` for a reason that was never about an approval at
    all — and ``invalidated`` is the honest word for that, because nobody
    answered anything.
    """
    if reference is not None and reference.decision in _REFERENCE_TERMINAL_STATE:
        return _REFERENCE_TERMINAL_STATE[reference.decision]
    return "approved" if target != "blocked" else "invalidated"


def _fill_required(event_type: str, task: CompanionTask, target: str, body: dict[str, Any]) -> dict[str, Any]:
    """Supply the payload fields a transition's event type must carry.

    Several transitions are reachable from generic paths — anything active can
    fail, be paused or be cancelled — and those paths do not know which event
    type the table will pick. Rather than have every caller enumerate the
    possibilities, the defaults live here, next to the table that chose them.
    Anything not defaulted is still required from the caller, and the schema
    check in :func:`companion.events.build_event` is what catches an omission.
    """
    if event_type == "task_state_changed":
        body.setdefault("from", task.state)
        body.setdefault("to", target)
    elif event_type == "approval_resolved":
        last = task.approvals[-1] if task.approvals else None
        body.setdefault("requestId", last.request_id if last is not None else "")
        # From the approval that was actually recorded, not from the target.
        #
        # This defaulted to "denied" whenever the target was `blocked`, which is
        # every transition out of `waiting_for_approval` that did not proceed —
        # including one caused by the user pausing. The runtime has already
        # emitted an accurate `approval_resolved` by the time this fires, so the
        # transition event was a second record of the same fact carrying a worse
        # value, and it is the one the projection folded last. A paused task
        # showed as blocked because of this line.
        body.setdefault("decision", _reference_terminal_state(last, target))
    elif event_type == "task_failed":
        body.setdefault("error", "the task failed")
    elif event_type == "task_cancelled":
        body.setdefault("reason", task.cancellation_cause or "user")
    elif event_type == "task_paused":
        body.setdefault("pausedFrom", task.state)
    elif event_type == "task_resumed":
        body.setdefault("resumedTo", target)
    elif event_type == "recovery_started":
        body.setdefault("detectedState", task.state)
    elif event_type == "recovery_completed":
        body.setdefault("decision", target)
    elif event_type == "planning_started":
        body.setdefault("planRevision", task.plan_revision)
    elif event_type == "execution_started":
        body.setdefault("planRevision", task.plan_revision)
    return body
