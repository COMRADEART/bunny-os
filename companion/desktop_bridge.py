# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The one seam between task authority and desktop effects.

This module lives *outside* ``companion/desktop/`` for the same reason
:mod:`companion.capability_bridge` lives outside ``capability/`` and
:mod:`companion.agent_bridge` lives outside ``companion/agents/``: it is the only
file that imports both sides, so "the desktop package holds no task authority"
stays checkable by reading one directory.

What it does is small and load-bearing:

**It registers the nine actions as tools.** §15's list, in order, and each step
happens somewhere a reader can point at:

1. *validate action availability* — :meth:`DesktopSupport.requirement_for`
   refuses before a question is asked, so a user is never asked to approve
   something the machine cannot do;
2. *validate task permission* — the classification ceiling, checked by
   :func:`companion.desktop.parameters.normalise`;
3. *validate structured parameters* — the closed schema, same place;
4. *recheck lifecycle epoch* — carried on the request, compared in the binding;
5. *derive approval requirements* — :meth:`requirement_for` produces an
   :class:`~companion.approvals.ApprovalRequirement` whose ``action`` is the
   descriptor's approval class and whose ``reason`` is §18's exact sentence;
6. *bind exact target and data disclosure* — the requirement's
   ``destination_declaration`` **is** the §8 binding material, so the existing
   :class:`companion.approvals.ApprovalGate` already refuses a changed act. No
   second approval system;
7. *obtain or validate approval* — the canonical gate does it, unchanged;
8. *invoke the desktop broker* — :meth:`DesktopSupport.context_for` hands the
   worker the very same :class:`~companion.desktop.broker.PreparedAction` the
   question was built from;
9. *record the result* — the runtime's own ``operation_completed`` event;
10. *return a sanitized result* — :meth:`companion.desktop.result.DesktopActionResult.to_tool_json`,
    which has no backend object, file descriptor, socket or portal handle in it
    because the type has nowhere to put one.

**The approved act and the executed act are the same object.** A prepared action
is built once, cached under the plan and operation it belongs to, and read back
by the worker. Building it twice would mean the prompt described one
normalisation and the adapter received another — and normalisation changes
something on nearly every action, so "twice" would mean "differently" more often
than not. The cache is keyed by the plan *fingerprint*, so a replan that
produces an identical plan reuses the answer and a replan that produces a
different one asks again, which is the supersession rule §12 of the runtime
brief already states.

**A provider never reaches any of this.** An executor proposes a
:class:`~companion.executor.PlannedOperation` naming a tool and arguments. It has
no channel to ``context``, cannot construct a
:class:`~companion.desktop.request.DesktopActionRequest`, cannot reach an
adapter, and cannot see this module — ``companion/agents/`` is forbidden from
importing it by the same AST test that forbids it importing the runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import threading
from typing import Any, Callable, Mapping, Sequence

from .approvals import ApprovalRequirement
from .clock import Clock, SystemClock
from .desktop.binding import ApprovalBinding
from .desktop.broker import BrokerOptions, DesktopActionBroker, PreparedAction
from .desktop.catalogue import ACTION_IDS, DESCRIPTORS
from .desktop.errors import DesktopActionError, DesktopUnavailable
from .desktop.paths import PathContext
from .desktop.result import DesktopActionResult
from .errors import CompanionError
from .executor import PlannedOperation
from .ids import IdSource, RandomIds
from .privacy import rank
from .task import CompanionTask
from .tools import ToolBroker, ToolDeclaration, ToolOutcome

__all__ = [
    "DESKTOP_TOOL_IDS",
    "DesktopSupport",
    "DesktopToolContext",
    "desktop_tool_declarations",
    "register_desktop_tools",
]

#: The tool identifier for each action. The action id *is* the tool id: a second
#: naming scheme would be a second thing to keep in step, and the one place a
#: user sees both is a record where they had better match.
DESKTOP_TOOL_IDS: tuple[str, ...] = ACTION_IDS


@dataclass(frozen=True)
class DesktopToolContext:
    """The authority facts one invocation runs under.

    Constructed by :meth:`DesktopSupport.context_for` from the task the runtime
    is currently executing. There is no path from a provider to this type: an
    executor returns plans, and a plan has no field that reaches
    :meth:`companion.tools.ToolBroker.invoke`'s ``context`` parameter.
    """

    session_id: str
    task_id: str
    lifecycle_epoch: int
    plan_id: str
    plan_fingerprint: str
    operation_id: str
    classification: str
    #: The approval reference the canonical gate resolved for this operation.
    approval_reference: str = ""
    #: The act the user approved, as §8 compares acts.
    approved_binding: ApprovalBinding | None = None
    #: The paths this task may reveal. Built by the runtime from what the user
    #: named; a provider contributes nothing to it.
    path_context: PathContext | None = None
    #: Re-read at every checkpoint. A callable rather than a flag because a stop
    #: can arrive from another process while this one is between two lines.
    cancelled: Callable[[], bool] | None = None
    audit_reference: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "sessionId": self.session_id,
            "taskId": self.task_id,
            "lifecycleEpoch": self.lifecycle_epoch,
            "planId": self.plan_id,
            "operationId": self.operation_id,
            "classification": self.classification,
            "approvalReference": self.approval_reference,
            "hasApprovedBinding": self.approved_binding is not None,
            "pathReferences": list(self.path_context.identifiers()) if self.path_context else [],
        }


def desktop_tool_declarations() -> tuple[ToolDeclaration, ...]:
    """One :class:`~companion.tools.ToolDeclaration` per declared action.

    Derived from the descriptors so the two cannot disagree. The three flags the
    approval machinery reads are set from what the action *is*:

    ``interrupts_user``
        true for everything here. Every action in this catalogue is user-visible
        by design — §18 requires the expected visible effect to be shown — and a
        desktop effect that did not interrupt would be one happening behind
        somebody's back.
    ``destructive``
        false throughout, and correctly: nothing in this catalogue destroys user
        work. A clipboard write displaces what was there, which is why it is
        classified *compensatable* rather than harmless, but the tool
        declaration's ``destructive`` means "discards unsaved state" and none of
        these does.
    ``external_destination``
        false. Everything happens on this machine. Opening a URI hands an address
        to a local handler; whether that handler then reaches the network is the
        handler's business and the user's browser policy, not a claim this tool
        can make. Declaring it external would ask for ``remote_dispatch``
        approval on top of the precise one, which would make the prompt vaguer
        rather than stricter.
    """
    return tuple(
        ToolDeclaration(
            tool_id=action_id,
            summary=DESCRIPTORS[action_id].summary,
            destructive=False,
            external_destination=False,
            interrupts_user=True,
            maximum_classification=DESCRIPTORS[action_id].privacy_ceiling,
            requires_context=True,
        )
        for action_id in ACTION_IDS
    )


@dataclass
class DesktopSupport:
    """Holds the desktop broker, and speaks the runtime's language to it.

    One per runtime. Thread-safe because a runtime may execute two tasks at
    once, and the prepared-action cache is shared state between the moment a
    question is asked and the moment the answer is spent.
    """

    broker: DesktopActionBroker
    clock: Clock = field(default_factory=SystemClock)
    ids: IdSource = field(default_factory=RandomIds)
    #: Per-task path contexts, set by whatever built the task. Absent means the
    #: task may reveal nothing, which is the correct default: §4.9 requires the
    #: path to already exist in canonical task context, and a task with no
    #: context has none.
    path_contexts: dict[str, PathContext] = field(default_factory=dict)
    #: (task, plan fingerprint, operation name) -> the prepared action. The
    #: object the question was built from and the object the worker executes.
    _prepared: dict[tuple[str, str, str], PreparedAction] = field(default_factory=dict, repr=False)
    _guard: threading.RLock = field(default_factory=threading.RLock, repr=False)

    # -- construction ------------------------------------------------------

    @classmethod
    def create(
        cls,
        *,
        ledger_path: Path | None = None,
        clock: Clock | None = None,
        ids: IdSource | None = None,
        headless_uri_policy: bool = False,
        accessibility: Any = None,
        capability_signals: Mapping[str, Any] | None = None,
        adapters: Any = None,
    ) -> "DesktopSupport":
        the_clock = clock or SystemClock()
        broker = DesktopActionBroker(BrokerOptions(
            ledger_path=ledger_path,
            adapters=adapters,
            clock=the_clock,
            headless_uri_policy=headless_uri_policy,
            accessibility=accessibility,
            capability_signals=dict(capability_signals or {}),
        ))
        return cls(broker=broker, clock=the_clock, ids=ids or RandomIds())

    def start(self) -> "DesktopSupport":
        self.broker.start()
        return self

    def stop(self) -> dict[str, int]:
        with self._guard:
            self._prepared.clear()
        return self.broker.stop()

    def handles(self, tool_id: str) -> bool:
        return tool_id in DESKTOP_TOOL_IDS

    # -- §15 steps 1-6: the approval requirement ---------------------------

    def requirement_for(
        self, task: CompanionTask, plan: Any, operation: PlannedOperation
    ) -> ApprovalRequirement | None:
        """The precise question to put about one desktop operation.

        Returns ``None`` for an operation that is not a desktop action, so the
        caller falls back to the generic tool-declaration requirements.

        An operation the environment cannot perform raises rather than returning
        ``None``. Asking a person to approve something that will then report
        ``unsupported`` wastes their attention and teaches them the prompts are
        noise; refusing at planning time puts the reason in the task's record
        where the executor can replan around it.
        """
        if operation.tool not in DESKTOP_TOOL_IDS:
            return None
        prepared = self._prepare(task, plan, operation)
        descriptor = DESCRIPTORS[operation.tool]
        return ApprovalRequirement(
            action=descriptor.approval_class,
            # §18's sentence, not a category. "Open Firefox", not "Allow task
            # action". The rest of the fields are what a person needs to weigh
            # it, in the order they would ask.
            reason=(
                f"{prepared.request.presentation}. "
                f"{prepared.request.expected_effect} "
                f"Discloses: {prepared.request.disclosure}. "
                + (
                    f"Can be undone: {prepared.undo_preview}."
                    if prepared.undo_preview
                    else f"This cannot be undone ({descriptor.reversibility})."
                )
            ),
            # The exact target: the application id, the normalised address, the
            # resolved path, the audio sink, the settings page.
            destination=prepared.request.target,
            provider_id=None,
            estimated_cost_units=None,
            data_affected=prepared.request.classification,
            alternatives=_alternatives(operation.tool),
            operation_name=operation.name,
            # The whole §8 binding, feeding the destination fingerprint the
            # canonical gate already compares. This is the integration: a
            # changed target, URI, path, clipboard digest, volume, parameter,
            # classification, plan, epoch or action type changes this digest,
            # and ApprovalGate.resolve refuses on it without knowing what a
            # desktop action is.
            destination_declaration=prepared.binding.material,
        )

    def prompt_for(
        self, task: CompanionTask, plan: Any, operation: PlannedOperation
    ) -> dict[str, Any] | None:
        """§18's fields for one operation, for an approval centre to render."""
        if operation.tool not in DESKTOP_TOOL_IDS:
            return None
        with self._guard:
            prepared = self._prepared.get(self._key(task, plan, operation))
        if prepared is None:
            try:
                prepared = self._prepare(task, plan, operation)
            except CompanionError:
                return None
        return prepared.to_prompt_json()

    # -- §15 step 8: the invocation context --------------------------------

    def context_for(
        self,
        task: CompanionTask,
        plan: Any,
        operation: PlannedOperation,
        *,
        cancelled: Callable[[], bool] | None = None,
        audit_reference: str = "",
    ) -> DesktopToolContext:
        """The authority facts for one invocation, with the approved act attached.

        The binding is read from the *prepared* action rather than rebuilt, so
        the comparison in the broker is against the object the user's answer was
        bound to. Rebuilding it here would compare a normalisation against
        itself and prove nothing.
        """
        prepared = None
        with self._guard:
            prepared = self._prepared.get(self._key(task, plan, operation))
        reference = ""
        binding: ApprovalBinding | None = None
        if prepared is not None:
            binding = prepared.binding
            reference = _approval_reference(task, prepared)
        return DesktopToolContext(
            session_id=task.session_id,
            task_id=task.task_id,
            lifecycle_epoch=task.lifecycle_epoch,
            plan_id=getattr(plan, "plan_id", ""),
            plan_fingerprint=getattr(plan, "fingerprint", ""),
            operation_id=operation.name,
            classification=task.classification,
            approval_reference=reference,
            approved_binding=binding,
            path_context=self.path_contexts.get(task.task_id),
            cancelled=cancelled,
            audit_reference=audit_reference or getattr(plan, "plan_id", ""),
        )

    def forget_plan(self, task_id: str) -> None:
        """Drop cached preparations for a task whose plan was superseded."""
        with self._guard:
            for key in [item for item in self._prepared if item[0] == task_id]:
                self._prepared.pop(key, None)

    # -- internals ---------------------------------------------------------

    def _key(self, task: CompanionTask, plan: Any, operation: PlannedOperation) -> tuple[str, str, str]:
        return (task.task_id, getattr(plan, "fingerprint", ""), operation.name)

    def _prepare(
        self, task: CompanionTask, plan: Any, operation: PlannedOperation
    ) -> PreparedAction:
        key = self._key(task, plan, operation)
        with self._guard:
            existing = self._prepared.get(key)
            if existing is not None:
                return existing
        prepared = self.broker.prepare(
            operation.tool,
            operation.arguments,
            request_id=self.ids.next("dreq"),
            session_id=task.session_id,
            task_id=task.task_id,
            lifecycle_epoch=task.lifecycle_epoch,
            plan_id=getattr(plan, "plan_id", ""),
            operation_id=operation.name,
            cancellation_token=self.ids.next("dcancel"),
            classification=task.classification,
            path_context=self.path_contexts.get(task.task_id),
            audit_reference=getattr(plan, "plan_id", ""),
        )
        with self._guard:
            self._prepared.setdefault(key, prepared)
            return self._prepared[key]

    # -- §15 steps 8-10: the tool implementation ---------------------------

    def invoke(self, tool_id: str, arguments: Mapping[str, Any], context: Any) -> ToolOutcome:
        """The callable registered in the :class:`~companion.tools.ToolBroker`.

        Everything that can go wrong becomes a failed :class:`ToolOutcome` with
        a sentence, rather than an exception. An exception here would abort the
        task; a desktop action that could not be performed should leave the task
        able to replan around it, and the executor is handed the reason.
        """
        if not isinstance(context, DesktopToolContext):
            return ToolOutcome(
                tool_id, False,
                detail=(
                    "a desktop action may only be performed with the task's authority facts, "
                    "and what was supplied is not a desktop invocation context"
                ),
            )
        with self._guard:
            prepared = next(
                (
                    item for key, item in self._prepared.items()
                    if key[0] == context.task_id and key[2] == context.operation_id
                    and item.request.action_id == tool_id
                ),
                None,
            )
        if prepared is None:
            return ToolOutcome(
                tool_id, False,
                detail=(
                    "no approved desktop action was prepared for this operation; an action is "
                    "prepared when the question is asked and executed from that preparation, "
                    "so an operation that reached here without one was not approved"
                ),
            )
        if not context.approval_reference or context.approved_binding is None:
            return ToolOutcome(
                tool_id, False,
                detail=f"{tool_id} was not approved; no response means no action",
            )

        request = prepared.request.with_approval(context.approval_reference)
        try:
            result = self.broker.execute(
                request,
                approved_binding=context.approved_binding,
                path_context=context.path_context,
                cancelled=context.cancelled,
            )
        except DesktopActionError as exc:
            return ToolOutcome(tool_id, False, detail=str(exc))
        return ToolOutcome(
            tool_id,
            result.succeeded,
            # §15: never a backend object, a descriptor, a socket or a portal
            # handle. `to_tool_json` is the whole of what a provider sees, and
            # the type it comes from has nowhere to put any of those.
            value=result.to_tool_json(),
            detail=result.explanation,
        )

    # -- reporting ---------------------------------------------------------

    def status(self) -> dict[str, Any]:
        return self.broker.status()


def register_desktop_tools(broker: ToolBroker, support: DesktopSupport) -> tuple[str, ...]:
    """Add the nine desktop actions to a tool broker. Returns what was added.

    The registration is explicit and per-runtime. A build with no desktop
    support has no desktop tools at all, so a plan naming one fails at the
    allowlist — which is the same refusal a plan naming ``shell.run`` gets, and
    for the same reason.
    """
    added: list[str] = []
    registry = dict(broker.tools)
    for declaration in desktop_tool_declarations():
        tool_id = declaration.tool_id

        def implementation(
            arguments: Mapping[str, Any], context: Any, _tool_id: str = tool_id
        ) -> ToolOutcome:
            return support.invoke(_tool_id, arguments, context)

        registry[tool_id] = (declaration, implementation)
        added.append(tool_id)
    broker.tools = registry
    return tuple(added)


def _alternatives(tool_id: str) -> tuple[str, ...]:
    """What the user gets if they decline. Never empty; §12 refuses one that is.

    Written per action rather than generically, because "Skip this step" is a
    true but useless sentence next to "Copy this to the clipboard" — the useful
    alternative is the one that says what they can do instead.
    """
    common = ("Skip this step.", "Cancel the task.")
    if tool_id == "desktop.clipboard.copy-text":
        return ("Leave the clipboard as it is.", *common)
    if tool_id == "desktop.uri.open":
        return ("Have the address shown to you instead of opened.", *common)
    if tool_id == "desktop.application.launch":
        return ("Open the application yourself.", *common)
    if tool_id == "desktop.audio.set-volume":
        return ("Change the volume yourself.", *common)
    if tool_id == "desktop.file.reveal":
        return ("Have the location shown to you instead of opened.", *common)
    return common


def _approval_reference(task: CompanionTask, prepared: PreparedAction) -> str:
    """The canonical approval id the gate resolved for **this exact act**.

    Matched by destination fingerprint rather than by action class or by
    position. The fingerprint is
    :func:`companion.approvals.destination_fingerprint` over the target and the
    §8 binding material — the same value the gate compared when it resolved the
    answer — so a match here means the reference was granted against precisely
    this normalisation and nothing else.

    Matching by approval class was the obvious wrong version and is worth
    naming: two clipboard writes in one plan share a class, and the first
    granted reference would have authorised the second act.

    Only ``granted`` references are considered. A pending or withdrawn one is
    not consent, and returning it would let :meth:`DesktopSupport.invoke`
    believe it had an approval — which the broker would then refuse for a
    different reason than the true one, and the user would read the wrong
    sentence.
    """
    from .approvals import destination_fingerprint

    wanted = destination_fingerprint(
        destination=prepared.request.target,
        provider_declaration=prepared.binding.material,
    )
    for reference in task.approvals:
        if reference.decision == "granted" and reference.destination_fingerprint == wanted:
            return reference.request_id
    return ""
