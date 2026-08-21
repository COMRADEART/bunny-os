# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The one seam between task authority and capsule execution.

This module exists because :mod:`companion.capsule_bridge` had no production
caller. The security architecture worked, the Companion worked, and nothing
joined them — so every property the qualification measured was a property of a
path the product never took. That is the defect this file closes, and the
route-existence test beside it is what stops it reopening.

It is deliberately the same shape as :mod:`companion.desktop_bridge`, which
solved the same problem for desktop actions. Both live outside the package they
bridge to, both are the only file that imports both sides, and both express the
integration as a *tool* rather than as a new pathway:

**A capsule task is a tool invocation.** The Companion already has exactly one
place where a task can cause something to happen — :meth:`ToolBroker.invoke` —
and exactly one place where a person is asked first. Adding a second would mean
two approval systems, two audit trails and two things to keep right. So an
operation from :data:`companion.capsule_tasks.OPERATIONS` is registered as a
tool whose declaration says it interrupts the user, and everything else follows
from machinery that already exists.

**The Companion's approval is the Trust answer.** :class:`trust.gate.TrustGate`
needs a :class:`~trust.gate.ConsentSurface`; the Companion has already put a
precise question to the person and recorded a binding. :class:`ApprovedActSurface`
converts that one recorded decision, and only for the act it was bound to. It
cannot be asked a second question, cannot be reused for another application,
another category or another file, and has no code path that produces ``allow``
without a decision. One question reaches the person; one authority records the
grant.

**Nothing here decides.** The resolver picks from the catalogue, the gate asks,
Trust grants, the capsule runtime confines, systemd owns the lifecycle. This
file carries values between them and refuses when they disagree.

Layering, which §12 states and this module keeps::

    UI  →  Companion protocol  →  CompanionRuntime  →  CapsuleSupport  →  CapsuleTaskCoordinator

The UI is never handed a reference to anything below the protocol. In
particular it cannot reach the trust store: a renderer that could write grants
would be a renderer that could mint them, which is §27 and is also why the
window unit is not given ``ReadWritePaths=`` for the state roots.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
import threading
from typing import Any, Callable, Mapping, Sequence

import trust
from capsules.backends import available_backends
from capsules.errors import CapsuleError, CapsuleUnavailable
from capsules.exchange import user_destinations
from capsules.runtime import CapsuleRuntime, SubprocessExecutor
from catalog.registry import CatalogRegistry
from trust.audit import TrustAudit
from trust.gate import TrustGate, UserAnswer
from trust.resources import path_resource
from trust.store import TrustStore

from .approvals import ApprovalRequirement
from .capsule_bridge import CapsuleProcessTool, CapsuleTaskCoordinator, CapsuleTaskResult
from .capsule_status import capsule_status
from .capsule_tasks import (
    ApplicationTaskRequest,
    CapsuleTaskFailure,
    OPERATIONS,
    OperationDescriptor,
    operation as operation_descriptor,
    output_name_for,
)
from .clock import Clock, SystemClock
from .errors import CompanionError
from .executor import PlannedOperation
from .ids import IdSource, RandomIds
from .task import CompanionTask
from .tools import ToolBroker, ToolDeclaration, ToolOutcome

__all__ = [
    "CAPSULE_TOOL_IDS",
    "ApprovedActSurface",
    "CapsuleSupport",
    "CapsuleToolContext",
    "PreparedCapsuleTask",
    "capsule_tool_declarations",
    "register_capsule_tools",
]

#: One tool per operation, so the broker's allowlist stays meaningful. A plan
#: naming an operation this build does not have fails at the allowlist, which is
#: the same refusal a plan naming ``shell.run`` gets and for the same reason.
CAPSULE_TOOL_IDS: tuple[str, ...] = tuple(sorted(OPERATIONS))


# --------------------------------------------------------------------------- #
# The consent surface
# --------------------------------------------------------------------------- #


@dataclass
class ApprovedActSurface:
    """Answers one Trust question, from one decision a person already made.

    The Companion asked "may Bunny Image Tool open holiday.png?" through its own
    approval gate, which bound the answer to the application, the operation, the
    file and the plan. This surface hands that answer to :class:`TrustGate` for
    the matching prompt and denies everything else.

    Why not simply grant? Because the grant, its scope, its expiry, its audit
    record and its revocation are Trust's job, and short-circuiting them would
    mean a capsule ran against a permission with no record and no way to take it
    back. The surface is the narrow adapter that lets one authority answer a
    question the other authority is asking.

    Three properties, each of which is a test:

    * **it is single-use.** ``ask`` consumes the answer. A second prompt — from a
      retry, a replan, or an application asking twice — finds nothing and is
      denied.
    * **it is bound.** The application id, the category and the resource display
      must all match what the person was shown. A prompt for a different file is
      a different question.
    * **it cannot invent.** There is no branch that returns ``allow`` when
      ``self.answer`` is not ``allow``. A surface constructed from a denial
      denies; a surface constructed from nothing denies.
    """

    application_id: str
    category: str
    resource_display: str
    #: What the person chose, as the Companion recorded it.
    verdict: str = "deny"
    scope: str = "once"
    #: Every prompt this surface was shown, for the audit and for tests that
    #: assert a second question was refused rather than silently answered.
    seen: list[Mapping[str, Any]] = field(default_factory=list)
    _spent: bool = False

    def ask(self, prompt: Any, ticket: Any) -> UserAnswer | None:
        matched = (
            prompt.application_id == self.application_id
            and prompt.category == self.category
            and prompt.resource_display == self.resource_display
        )
        self.seen.append({
            "applicationId": prompt.application_id,
            "category": prompt.category,
            "resource": prompt.resource_display,
            "matched": matched,
            "spent": self._spent,
        })
        if self._spent or not matched or self.verdict != "allow":
            return None
        self._spent = True
        return UserAnswer(ticket_id=ticket.ticket_id, verdict="allow", scope=self.scope)


# --------------------------------------------------------------------------- #
# What one operation was prepared as
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class PreparedCapsuleTask:
    """The act the question was built from, and the act that gets executed.

    Built once per (task, plan fingerprint, operation) and read back at
    execution. Building it twice would mean the prompt described one
    normalisation and the launcher received another — and normalisation changes
    something on nearly every request, because the input path is resolved and
    the output name is derived.
    """

    request: ApplicationTaskRequest
    descriptor: OperationDescriptor
    entry_id: str
    application_id: str
    application_name: str
    #: The one file, as the person will see it named: "Pictures/holiday.png".
    resource_display: str
    #: The identity digest Trust keys grants on: a hash of *kind and path*, not
    #: of content. Kept because it is what the grant is stored under.
    resource_digest: str
    #: A hash of the exact bytes at approval time. §11's substitution check
    #: compares this immediately before launch, so a file swapped between the
    #: question and the answer is a different act — which
    #: :attr:`resource_digest` cannot detect, because two different files at one
    #: path share it. Finding that out is what this field is: the first version
    #: compared the identity digest and would have let a swapped file through.
    content_digest: str
    output_name: str
    parameters: Mapping[str, Any]

    @property
    def material(self) -> Mapping[str, Any]:
        """The §8 binding material, which becomes the destination fingerprint.

        Everything that would make this a different act is in here. The
        canonical :class:`companion.approvals.ApprovalGate` compares the
        fingerprint without knowing what a capsule is, so a changed application,
        operation, file, file *content*, width or output name is refused by
        machinery that predates this module.
        """
        return {
            "kind": "capsule-task",
            "operationId": self.descriptor.operation_id,
            "applicationId": self.application_id,
            "entryId": self.entry_id,
            "resource": self.resource_display,
            "resourceDigest": self.resource_digest,
            "contentDigest": self.content_digest,
            "outputName": self.output_name,
            "parameters": dict(self.parameters),
            "network": self.descriptor.network,
            "modifiesInput": self.descriptor.modifies_input,
        }

    def to_prompt_json(self) -> dict[str, Any]:
        """What an approval centre renders. §32's plain view, and no more.

        The technical panel is not built here — it comes from the effective plan
        once there is one, so that the two cannot disagree. Before a launch there
        is no plan, and a "protected space" panel drawn from a guess would be a
        second display policy of exactly the kind §17 forbids.
        """
        return {
            "kind": "capsule-task",
            "operationId": self.descriptor.operation_id,
            "applicationName": self.application_name,
            "applicationId": self.application_id,
            "presentation": f"{self.application_name} wants to open {self.resource_display}",
            "expectedEffect": (
                f"It will save a copy as {self.output_name}. "
                f"Your original file will not be changed."
                if not self.descriptor.modifies_input
                else f"It will change {self.resource_display}."
            ),
            "disclosure": self.resource_display,
            "fileAccess": f"{self.resource_display} only",
            "network": "Off" if self.descriptor.network == "none" else "On",
            "privateAppData": "Isolated",
        }


# --------------------------------------------------------------------------- #
# The invocation context
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CapsuleToolContext:
    """The authority facts one capsule invocation runs under.

    Constructed by :meth:`CapsuleSupport.context_for` from the task the runtime
    is executing. There is no path from an executor or a provider to this type:
    a plan has no field that reaches ``ToolBroker.invoke``'s ``context``.
    """

    session_id: str
    task_id: str
    lifecycle_epoch: int
    plan_id: str
    plan_fingerprint: str
    operation_id: str
    classification: str
    approval_reference: str = ""
    approved_binding: Any = None
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
        }


def capsule_tool_declarations() -> tuple[ToolDeclaration, ...]:
    """One declaration per operation, derived from the operation table.

    ``interrupts_user`` is true for all of them: launching an application and
    writing a file into the user's folders is not something that should happen
    behind somebody's back, and it is the flag that makes the runtime ask.
    ``destructive`` is false because no operation here modifies the user's
    original — an operation that did would set ``modifies_input`` and this would
    follow it. ``external_destination`` is false because every operation runs
    with ``network="none"``; an operation that wanted the network would have to
    change that field, in a review, and would then be asking for
    ``remote_dispatch`` on top of the precise question.
    """
    return tuple(
        ToolDeclaration(
            tool_id=descriptor.operation_id,
            summary=descriptor.summary,
            destructive=descriptor.modifies_input,
            external_destination=descriptor.network != "none",
            interrupts_user=True,
            # The task's own data does not flow into the sandbox: what crosses
            # is a file the user named and a validated integer. The classifier
            # ceiling that matters is on the *file*, and Trust applies it when
            # the grant is asked for.
            maximum_classification="secret",
            requires_context=True,
        )
        for descriptor in (OPERATIONS[key] for key in CAPSULE_TOOL_IDS)
    )


# --------------------------------------------------------------------------- #
# The support object
# --------------------------------------------------------------------------- #


@dataclass
class CapsuleSupport:
    """Holds the capsule runtime, and speaks the Companion's language to it.

    One per runtime, thread-safe because a runtime may execute two tasks at
    once and the prepared-task cache is shared between the moment a question is
    asked and the moment the answer is spent.
    """

    runtime: CapsuleRuntime
    registry: CatalogRegistry
    store: TrustStore
    audit: TrustAudit
    gate: TrustGate
    clock: Clock = field(default_factory=SystemClock)
    ids: IdSource = field(default_factory=RandomIds)
    #: Where results are written. The user's Pictures directory by default; a
    #: task never chooses this and an application never sees it.
    destination: Path | None = None
    #: (task, plan fingerprint, operation) -> the prepared task.
    _prepared: dict[tuple[str, str, str], PreparedCapsuleTask] = field(default_factory=dict, repr=False)
    #: task -> the coordinator currently running it, so a cancel can reach it.
    _running: dict[str, CapsuleTaskResult | None] = field(default_factory=dict, repr=False)
    #: task -> the input files the user named. Set by whatever built the task;
    #: absent means the task may open nothing, which is the correct default.
    inputs: dict[str, tuple[Path, ...]] = field(default_factory=dict)
    _guard: threading.RLock = field(default_factory=threading.RLock, repr=False)

    # -- construction ------------------------------------------------------

    @classmethod
    def create(
        cls,
        *,
        session_id: str,
        catalog_directory: Path | None = None,
        clock: Clock | None = None,
        ids: IdSource | None = None,
        destination: Path | None = None,
        executor: Any = None,
    ) -> "CapsuleSupport":
        """Build the real thing: real store, real audit, real subprocess executor.

        There is no ``mock=True``. A build that cannot construct this raises, and
        :meth:`CompanionService._build_capsules` turns that into "no capsule
        tools are registered", so a plan naming one fails at the allowlist. What
        must never happen is a support object that looks registered and runs
        nothing confined, because that is indistinguishable from working right
        up until somebody checks.
        """
        import catalog
        from capsules.backends import MachineProbe
        import capsules as capsules_package

        store = TrustStore(trust.default_store_path(), session_id=session_id).load()
        audit = TrustAudit(trust.default_audit_path(), names={})
        gate = TrustGate(store=store, audit=audit, surface=None, names={})
        runtime = CapsuleRuntime(
            store=store,
            audit=audit,
            gate=gate,
            session_id=session_id,
            root=capsules_package.default_capsule_root(),
            probe=MachineProbe.measure(),
            executor=executor if executor is not None else SubprocessExecutor(),
        )
        registry = CatalogRegistry.load(catalog_directory or catalog.default_catalog_directory())
        return cls(
            runtime=runtime,
            registry=registry,
            store=store,
            audit=audit,
            gate=gate,
            clock=clock or SystemClock(),
            ids=ids or RandomIds(),
            destination=destination,
        )

    def start(self) -> "CapsuleSupport":
        return self

    def stop(self) -> dict[str, int]:
        """Stop every capsule this login started, then drop the caches.

        Not just bookkeeping. A task running an application task is blocked
        inside a wait on a transient unit; stopping the unit is what ends that
        wait, which is why ``capsules`` is released before ``task-worker``. A
        capsule left running past shutdown would also be an application holding
        a granted file after the session that authorised it had gone.

        Persistent capsule data is untouched: ``stop`` ends a *process*, and the
        application's private storage, config and cache are the capsule's
        identity rather than the task's — §16.
        """
        stopped = 0
        failed = 0
        for capsule in self.runtime.list():
            try:
                if self.runtime.stop(capsule):
                    stopped += 1
            except Exception:  # noqa: BLE001 - one that will not stop must not
                failed += 1     # prevent the others being asked
        with self._guard:
            prepared = len(self._prepared)
            self._prepared.clear()
            self.inputs.clear()
        return {"preparedDropped": prepared, "capsulesStopped": stopped, "stopFailed": failed}

    def handles(self, tool_id: str) -> bool:
        return tool_id in CAPSULE_TOOL_IDS

    def bind_inputs(self, task_id: str, paths: Sequence[Path]) -> None:
        """Attach the files the *user* named, before the task can be scheduled.

        Once an operation has been prepared its prompt is bound to the exact
        file, so replacing the inputs afterwards would create two competing
        authorities for one task. Refuse that state rather than guess.
        """
        with self._guard:
            if any(key[0] == task_id for key in self._prepared):
                raise CompanionError("the input cannot change after a capsule task was prepared")
            self.inputs[task_id] = tuple(Path(item) for item in paths)

    def release_task_context(self, task_id: str) -> None:
        with self._guard:
            self.inputs.pop(task_id, None)
            for key in [item for item in self._prepared if item[0] == task_id]:
                self._prepared.pop(key, None)

    def forget_plan(self, task_id: str) -> None:
        with self._guard:
            for key in [item for item in self._prepared if item[0] == task_id]:
                self._prepared.pop(key, None)

    # -- the approval requirement ------------------------------------------

    def requirement_for(
        self, task: CompanionTask, plan: Any, operation: PlannedOperation
    ) -> ApprovalRequirement | None:
        """The precise question to put about one capsule operation.

        ``None`` for an operation that is not one of ours, so the caller falls
        back to the generic tool-declaration requirement.

        An operation that cannot be performed *raises* rather than returning
        ``None``: asking somebody to approve something that will then report
        "no app" wastes their attention and teaches them the prompts are noise.
        """
        if operation.tool not in CAPSULE_TOOL_IDS:
            return None
        prepared = self._prepare(task, plan, operation)
        return ApprovalRequirement(
            action="launch_application",
            # §49: what it is, what will happen, what is disclosed. No mechanism.
            reason=(
                f"{prepared.to_prompt_json()['presentation']}. "
                f"{prepared.to_prompt_json()['expectedEffect']} "
                f"It runs in its protected space with no network access."
            ),
            destination=prepared.application_id,
            provider_id=None,
            estimated_cost_units=None,
            data_affected=task.classification,
            alternatives=(
                "Choose a different file.",
                "Cancel the task.",
            ),
            operation_name=operation.name,
            off_device=False,
            destination_declaration=prepared.material,
            # The same facts, structured, for a surface that can lay them out.
            # `reason` above stays exactly as it was: it is what a text-only
            # surface reads aloud and what the recovery shell prints, and a
            # graphical surface gaining a better layout must not cost a console
            # its sentence.
            prompt=prepared.to_prompt_json(),
        )

    def prompt_for(
        self, task: CompanionTask, plan: Any, operation: PlannedOperation
    ) -> dict[str, Any] | None:
        if operation.tool not in CAPSULE_TOOL_IDS:
            return None
        with self._guard:
            prepared = self._prepared.get(self._key(task, plan, operation))
        if prepared is None:
            try:
                prepared = self._prepare(task, plan, operation)
            except (CompanionError, CapsuleTaskFailure):
                return None
        return prepared.to_prompt_json()

    # -- the invocation context --------------------------------------------

    def context_for(
        self,
        task: CompanionTask,
        plan: Any,
        operation: PlannedOperation,
        *,
        cancelled: Callable[[], bool] | None = None,
        audit_reference: str = "",
    ) -> CapsuleToolContext:
        prepared = None
        with self._guard:
            prepared = self._prepared.get(self._key(task, plan, operation))
        reference = ""
        binding = None
        if prepared is not None:
            binding = prepared.material
            reference = _approval_reference(task, prepared)
        return CapsuleToolContext(
            session_id=task.session_id,
            task_id=task.task_id,
            lifecycle_epoch=task.lifecycle_epoch,
            plan_id=getattr(plan, "plan_id", ""),
            plan_fingerprint=getattr(plan, "fingerprint", ""),
            operation_id=operation.name,
            classification=task.classification,
            approval_reference=reference,
            approved_binding=binding,
            cancelled=cancelled,
            audit_reference=audit_reference or getattr(plan, "plan_id", ""),
        )

    # -- internals ---------------------------------------------------------

    def _key(self, task: CompanionTask, plan: Any, operation: PlannedOperation) -> tuple[str, str, str]:
        return (task.task_id, getattr(plan, "fingerprint", ""), operation.name)

    def _prepare(
        self, task: CompanionTask, plan: Any, operation: PlannedOperation
    ) -> PreparedCapsuleTask:
        key = self._key(task, plan, operation)
        with self._guard:
            existing = self._prepared.get(key)
            if existing is not None:
                return existing
            inputs = self.inputs.get(task.task_id, ())

        descriptor = operation_descriptor(operation.tool)
        if not inputs:
            raise CapsuleTaskFailure(
                "SECURITY_POLICY_BLOCKED",
                "this task has no file to work on; a capsule task's input is named by the user",
            )
        if len(inputs) != 1:
            raise CapsuleTaskFailure(
                "SECURITY_POLICY_BLOCKED", "the first capsule operation takes exactly one file"
            )
        source = inputs[0]
        if descriptor.input_extensions and source.suffix.lower() not in descriptor.input_extensions:
            raise CapsuleTaskFailure(
                "APP_UNAVAILABLE", f"{descriptor.operation_id} does not work on {source.suffix!r} files"
            )
        request = ApplicationTaskRequest(
            task_id=task.task_id,
            user_intent=str(task.original_request or ""),
            operation_id=descriptor.operation_id,
            parameters=dict(operation.arguments),
            inputs=(source,),
            destination=self._destination(),
        )
        parameters = request.validated_parameters()
        entry = self._resolve(descriptor)
        resource = path_resource(source, roots=user_destinations())
        prepared = PreparedCapsuleTask(
            request=replace(request, application_id=entry.application_id),
            descriptor=descriptor,
            entry_id=entry.entry_id,
            application_id=entry.application_id,
            application_name=entry.name,
            resource_display=resource.display,
            resource_digest=resource.digest,
            content_digest=_content_digest(source),
            output_name=output_name_for(descriptor, source),
            parameters=parameters,
        )
        with self._guard:
            self._prepared.setdefault(key, prepared)
            return self._prepared[key]

    def _destination(self) -> Path:
        if self.destination is not None:
            return self.destination
        roots = user_destinations()
        return Path(roots.get("Pictures") or roots.get("Documents") or Path.home())

    def _resolve(self, descriptor: OperationDescriptor):
        """§7. The catalogue chooses; the model never names an executable.

        Preference order is: installed first, then first-party, then whatever
        else declares the capability and can be sandboxed. A web option is never
        selected for an operation — it is not a thing that can run in a capsule,
        and offering one here would be offering something that cannot be done.
        """
        candidates = [
            entry for entry in self.registry.providing(descriptor.capability)
            if entry.delivery == "capsule" and entry.installable
        ]
        if not candidates:
            raise CapsuleTaskFailure(
                "APP_UNAVAILABLE",
                f"no installable sandboxable application declares {descriptor.capability!r}",
            )
        installed = {capsule.identity.application_id for capsule in self.runtime.list()}
        candidates.sort(
            key=lambda entry: (
                entry.application_id not in installed,
                entry.package_source != "bunny-system",
                entry.name,
            )
        )
        return candidates[0]

    # -- the tool implementation -------------------------------------------

    def invoke(self, tool_id: str, arguments: Mapping[str, Any], context: Any) -> ToolOutcome:
        """The callable registered in the tool broker. Everything below happens here.

        Every failure becomes a failed :class:`ToolOutcome` carrying a typed
        code, rather than an exception. An exception would abort the task; a
        capsule task that could not run should leave the task able to explain
        itself, and the code is what the audit keeps.
        """
        if not isinstance(context, CapsuleToolContext):
            return _failed(
                tool_id,
                CapsuleTaskFailure(
                    "SECURITY_POLICY_BLOCKED",
                    "a capsule task may only run with the task's authority facts",
                ),
            )
        with self._guard:
            prepared = next(
                (
                    item for key, item in self._prepared.items()
                    if key[0] == context.task_id and key[2] == context.operation_id
                    and item.descriptor.operation_id == tool_id
                ),
                None,
            )
        if prepared is None:
            return _failed(
                tool_id,
                CapsuleTaskFailure(
                    "SECURITY_POLICY_BLOCKED",
                    "no approved capsule task was prepared for this operation, so it was "
                    "never approved",
                ),
            )
        if not context.approval_reference or context.approved_binding is None:
            return _failed(
                tool_id,
                CapsuleTaskFailure("PERMISSION_DENIED", f"{tool_id} was not approved"),
            )
        try:
            self._revalidate(prepared, context)
        except CapsuleTaskFailure as failure:
            return _failed(tool_id, failure)

        if context.cancelled is not None and context.cancelled():
            return _failed(tool_id, CapsuleTaskFailure("TASK_CANCELLED", "cancelled before launch"))

        tool = CapsuleProcessTool(
            parameters=prepared.parameters,
            output_name=prepared.output_name,
            timeout_seconds=prepared.descriptor.timeout_seconds,
        )
        surface = ApprovedActSurface(
            application_id=prepared.application_id,
            category="files",
            resource_display=prepared.resource_display,
            verdict="allow",
            # `session`, and this is the one place in the integration where the
            # obvious answer is wrong.
            #
            # "Allow once" is what the person is offered and what they get. It
            # is not what the *grant* can say, because Trust deliberately never
            # persists an allow-once decision — and the isolation plan is built
            # from persisted grants, so a once grant produces no bind at all and
            # the application is handed a path to nothing. Measured, on the
            # first real end-to-end run: the capsule started and the program
            # reported "the input is not a file this app can see".
            #
            # A session grant is persisted, so the bind exists, and the runtime
            # drops every session grant when the capsule stops. The coordinator
            # stops the capsule as soon as the operation finishes, so the grant
            # outlives the person's answer by exactly one launch. That is what
            # "once" means to them, expressed in the lifetime the store has.
            scope="session",
        )
        self.gate.surface = surface
        coordinator = CapsuleTaskCoordinator(
            runtime=self.runtime, registry=self.registry, tool=tool
        )
        try:
            result = coordinator.run(
                task_id=context.task_id,
                capability=prepared.descriptor.capability,
                entry_id=prepared.entry_id,
                inputs=prepared.request.inputs,
                destination=prepared.request.destination,
                request_text=None,
                overwrite_inputs=prepared.descriptor.modifies_input,
                parameters=prepared.parameters,
            )
        except CapsuleUnavailable as error:
            return _failed(
                tool_id,
                CapsuleTaskFailure("CAPSULE_BACKEND_UNAVAILABLE", str(error)),
            )
        except CapsuleError as error:
            return _failed(tool_id, CapsuleTaskFailure("CAPSULE_LAUNCH_FAILED", str(error)))
        finally:
            self.gate.surface = None

        return self._outcome(tool_id, prepared, result, tool, surface)

    def _revalidate(self, prepared: PreparedCapsuleTask, context: CapsuleToolContext) -> None:
        """§11. Immediately before the launch, not at planning time.

        The window between a person answering and a process starting is where
        substitution lives: the file can be replaced, the application can be
        uninstalled, the backend can go away. Each of these is a separate code
        because each is a different thing to tell somebody.
        """
        if context.approved_binding != prepared.material:
            raise CapsuleTaskFailure(
                "SECURITY_POLICY_BLOCKED",
                "the act being executed is not the act that was approved",
            )
        source = prepared.request.inputs[0]
        if not source.is_file():
            raise CapsuleTaskFailure(
                "OUTPUT_MISSING", "the file that was approved is no longer there"
            )
        current = path_resource(source, roots=user_destinations())
        if current.digest != prepared.resource_digest:
            raise CapsuleTaskFailure(
                "SECURITY_POLICY_BLOCKED",
                "the file that was approved is not the file at that path",
            )
        if _content_digest(source) != prepared.content_digest:
            raise CapsuleTaskFailure(
                "SECURITY_POLICY_BLOCKED",
                "the file changed between the question and the answer",
            )
        try:
            self.store.load()
        except Exception as error:  # noqa: BLE001 - an unreadable store is fail-closed
            raise CapsuleTaskFailure("TRUST_UNAVAILABLE", str(error)) from error
        # The weakest backend is excluded by name: `systemd-scope` carries the
        # cgroup and confines nothing, so a machine on which it is the only
        # option is a machine with no confinement — which is a refusal, never a
        # quieter launch.
        confining = [
            name for name in available_backends(self.runtime.probe) if name != "systemd-scope"
        ]
        if not confining:
            raise CapsuleTaskFailure(
                "CAPSULE_BACKEND_UNAVAILABLE",
                "no confining backend is available on this machine",
            )

    def _outcome(
        self,
        tool_id: str,
        prepared: PreparedCapsuleTask,
        result: CapsuleTaskResult,
        tool: CapsuleProcessTool,
        surface: ApprovedActSurface,
    ) -> ToolOutcome:
        """Turn the coordinator's result into what the runtime records.

        A refusal that never reached a launch and a launch that failed are
        different codes, and the coordinator distinguishes them by whether a
        decision was recorded and whether a launch happened. "Completed" is
        never reported for a result that is not ``completed`` — §57's "failure
        does not produce completed" is this branch.
        """
        if result.succeeded:
            status = capsule_status(
                self.runtime.open(prepared.application_id), result.launch.plan
            ) if result.launch is not None else None
            return ToolOutcome(
                tool_id,
                True,
                value={
                    "taskId": result.task_id,
                    "applicationId": result.application_id,
                    "outputs": [dict(item.as_record()) for item in result.exports],
                    "workspace": dict(result.workspace.as_record()),
                    "protectedSpace": dict(status.as_record()) if status is not None else None,
                    "exitStatus": tool.exit_code,
                    "surfaceQuestions": list(surface.seen),
                },
                detail=result.workspace.summary,
            )
        code = "CAPSULE_LAUNCH_FAILED"
        if result.decisions and not result.decisions[-1].allowed:
            code = (
                "PERMISSION_EXPIRED"
                if result.decisions[-1].reason_code == "expired"
                else "PERMISSION_DENIED"
            )
        elif result.launch is not None and tool.exit_code not in (None, 0):
            code = "CAPSULE_EXITED"
        elif result.launch is not None and tool.exit_code == 0:
            code = "OUTPUT_MISSING"
        failure = CapsuleTaskFailure(code, result.failure or "")
        return ToolOutcome(
            tool_id,
            False,
            value={
                "taskId": result.task_id,
                "failure": dict(failure.as_record()),
                "workspace": dict(result.workspace.as_record()),
                "surfaceQuestions": list(surface.seen),
            },
            detail=failure.sentence,
        )

    def status(self) -> dict[str, Any]:
        with self._guard:
            return {
                "operations": list(CAPSULE_TOOL_IDS),
                "prepared": len(self._prepared),
                "capsules": len(self.runtime.list()),
            }


def _content_digest(path: Path) -> str:
    """A hash of what is actually in the file, right now.

    Trust's :func:`~trust.resources.resource_digest` hashes the *identity* — the
    kind and the path — because that is what a grant is keyed on and a grant is
    about a location. It therefore cannot notice that the bytes at that location
    changed, which is exactly the substitution §11 asks about: the person was
    shown one image and a different one is on disk when the launch happens.

    Read in blocks and bounded by nothing: an image the user chose is a file the
    machine is about to open anyway. An unreadable file returns a sentinel that
    matches no real digest, so it fails the comparison rather than passing it.
    """
    import hashlib

    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()
    except OSError:
        return "unreadable"


def _failed(tool_id: str, failure: CapsuleTaskFailure) -> ToolOutcome:
    return ToolOutcome(tool_id, False, value={"failure": dict(failure.as_record())},
                       detail=failure.sentence)


def _approval_reference(task: CompanionTask, prepared: PreparedCapsuleTask) -> str:
    return f"{task.task_id}:{prepared.descriptor.operation_id}:{prepared.output_name}"


def register_capsule_tools(broker: ToolBroker, support: CapsuleSupport) -> tuple[str, ...]:
    """Add the capsule operations to a tool broker. Returns what was added.

    Explicit and per-runtime, like the desktop registration. A build with no
    capsule support registers nothing, so a plan naming an operation fails at
    the allowlist rather than reaching a support object that is not there.
    """
    added: list[str] = []
    registry = dict(broker.tools)
    for declaration in capsule_tool_declarations():
        tool_id = declaration.tool_id

        def implementation(
            arguments: Mapping[str, Any], context: Any, _tool_id: str = tool_id
        ) -> ToolOutcome:
            return support.invoke(_tool_id, arguments, context)

        registry[tool_id] = (declaration, implementation)
        added.append(tool_id)
    broker.tools = registry
    return tuple(added)
