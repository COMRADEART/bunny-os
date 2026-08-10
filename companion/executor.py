# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What an executor is, and — more importantly — what it is not.

An executor is the thing that decides *what should be done*. It is not the thing
that does it. That separation is the single most important line in this module:
an executor returns a **plan**, and the runtime decides whether each planned
operation is permitted, whether it needs a person's consent, and whether it has
already happened. The executor never touches a file, a socket or a process.

This is why :class:`Executor` has no ``run`` method and is handed no broker. An
interface that let an executor perform its own operations would put the
allowlist, the approval check and the idempotency ledger inside whatever code
somebody plugs in later, which is exactly where they must not be. Here, a
malicious or merely careless executor can at worst propose something; proposing
it is not doing it.

The declaration block exists for the same reason it exists in
:class:`capability.router.ProviderDeclaration`: an executor that will not state
its cost class, its privacy ceiling or whether it runs locally cannot be
selected, because none of the decisions in :mod:`companion.capability_bridge`
can be made about it. Undeclared fails closed.

Only one implementation ships here: :class:`DeterministicLocalExecutor`, which
is pure, local, free and reproducible. There is deliberately no adapter for any
commercial provider, not even a stub. A stub adapter is a place for credentials
to appear and a shape for a real integration to be poured into without anybody
reviewing the decision to have one.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
import re
from typing import Any, Mapping, Protocol, Sequence

from .errors import MalformedOutput
from .ids import operation_key
from .privacy import DATA_CLASSES, display_summary, rank
from .task import TASK_TYPES, CompanionTask

__all__ = [
    "COST_CLASSES",
    "DeterministicLocalExecutor",
    "Executor",
    "ExecutorDeclaration",
    "ExecutorHealth",
    "PlannedOperation",
    "ProducedOutput",
    "TaskContext",
    "TaskPlan",
    "TaskResult",
    "plan_fingerprint",
]

#: What using an executor costs. ``metered`` means free of money but not of a
#: metered connection, which is a cost a user on a phone tether cares about and
#: which the router already knows how to refuse.
COST_CLASSES = ("free", "metered", "paid")

#: Requests that ask to be told the answer rather than merely to have it.
_WANTS_NOTICE = re.compile(r"(?i)\b(notify|notice|let me know|tell me when)\b")


@dataclass(frozen=True)
class ExecutorDeclaration:
    """Everything an executor must state about itself to be selectable."""

    executor_id: str
    provider_id: str
    implementation_id: str
    #: ``True`` when the work happens on this machine and nothing leaves it.
    local: bool = True
    supported_task_types: tuple[str, ...] = ()
    supports_tools: bool = False
    supports_structured_output: bool = False
    supports_streaming: bool = False
    supports_cancellation: bool = False
    #: Whether a task interrupted by a restart can be handed back to this
    #: executor rather than restarted. Almost always ``False``, and honestly so:
    #: an executor that cannot prove it resumed where it stopped should say it
    #: cannot resume, and :mod:`companion.recovery` will replan instead.
    supports_resume: bool = False
    context_limit_tokens: int = 0
    cost_class: str = "free"
    #: The most sensitive data this executor may be given. A local pure-function
    #: executor can hold anything; anything that leaves the device cannot.
    maximum_privacy_class: str = "internal"
    requires_authentication: bool = False

    def __post_init__(self) -> None:
        if self.cost_class not in COST_CLASSES:
            raise MalformedOutput(f"costClass must be one of {list(COST_CLASSES)}")
        if self.maximum_privacy_class not in DATA_CLASSES:
            raise MalformedOutput(f"maximumPrivacyClass must be one of {list(DATA_CLASSES)}")
        unknown = set(self.supported_task_types) - set(TASK_TYPES)
        if unknown:
            raise MalformedOutput(f"unknown task types declared: {', '.join(sorted(unknown))}")
        if not self.local and rank(self.maximum_privacy_class) > rank("sensitive"):
            raise MalformedOutput(
                "a non-local executor cannot declare a privacy ceiling of 'secret'; "
                "secret data never leaves the device"
            )

    @property
    def fully_declared(self) -> bool:
        """Whether enough is stated to select this executor at all."""
        return bool(
            self.executor_id
            and self.provider_id
            and self.implementation_id
            and self.supported_task_types
        )

    def handles(self, task_type: str) -> bool:
        return task_type in self.supported_task_types

    def to_json(self) -> dict[str, Any]:
        return {
            "executorId": self.executor_id,
            "providerId": self.provider_id,
            "implementationId": self.implementation_id,
            "local": self.local,
            "supportedTaskTypes": list(self.supported_task_types),
            "supportsTools": self.supports_tools,
            "supportsStructuredOutput": self.supports_structured_output,
            "supportsStreaming": self.supports_streaming,
            "supportsCancellation": self.supports_cancellation,
            "supportsResume": self.supports_resume,
            "contextLimitTokens": self.context_limit_tokens,
            "costClass": self.cost_class,
            "maximumPrivacyClass": self.maximum_privacy_class,
            "requiresAuthentication": self.requires_authentication,
            "fullyDeclared": self.fully_declared,
        }


@dataclass(frozen=True)
class ExecutorHealth:
    """The executor's answer to "can you take work right now".

    Availability, authentication and health are separate because they fail
    separately and a user is owed the difference: "the model is not installed",
    "you are signed out" and "it is installed and answering with nonsense" call
    for three different actions.
    """

    available: bool = True
    authenticated: bool = True
    healthy: bool = True
    detail: str = ""

    @property
    def ready(self) -> bool:
        return self.available and self.authenticated and self.healthy

    def to_json(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "authenticated": self.authenticated,
            "healthy": self.healthy,
            "ready": self.ready,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class PlannedOperation:
    """One thing the executor would like the runtime to do.

    ``destination`` is ``"local"`` or a provider id, and it is part of what an
    approval is granted against — §12 requires an approval whose destination
    changed to be refused, and that comparison needs the destination to be a
    field rather than something inferred from the tool name.
    """

    name: str
    tool: str
    arguments: Mapping[str, Any] = field(default_factory=dict)
    destination: str = "local"
    estimated_cost_units: int = 0
    #: Set by the executor when it knows consent is needed. The runtime decides
    #: independently and may require an approval the executor did not ask for;
    #: it never skips one because the executor said it was unnecessary.
    requires_approval: bool = False
    approval_action: str = ""

    def __post_init__(self) -> None:
        if not self.name or not self.tool:
            raise MalformedOutput("a planned operation needs a name and a tool")
        if self.estimated_cost_units < 0:
            raise MalformedOutput("an operation cannot have a negative estimated cost")
        if not isinstance(self.arguments, Mapping):
            raise MalformedOutput("operation arguments must be an object")

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "tool": self.tool,
            "arguments": dict(self.arguments),
            "destination": self.destination,
            "estimatedCostUnits": self.estimated_cost_units,
            "requiresApproval": self.requires_approval,
            "approvalAction": self.approval_action,
        }

    def to_review_json(self) -> dict[str, Any]:
        """The operation as a reviewer may see it: what it does, not what to.

        The arguments are where the user's material ends up — the text to
        summarise, the file to act on, the recipients. A reviewer needs none of
        it to do its job: "this plan omits the validation step" and "this step
        sends data to a provider" are both answerable from the names, the tools
        and the destinations. So the argument *keys* survive, because their
        presence is sometimes the finding, and the values do not.
        """
        from .privacy import REDACTION_MARKER

        value = self.to_json()
        value["arguments"] = {key: REDACTION_MARKER for key in sorted(self.arguments)}
        return value


def plan_fingerprint(operations: Sequence[PlannedOperation], summary: str) -> str:
    """What makes a plan *this* plan.

    Used to notice supersession. Two plans with the same operations in the same
    order against the same destinations are the same plan and an approval
    granted for one is good for the other; change any of that and the approval
    is not transferable, which is what :mod:`companion.approvals` checks.
    """
    from capability.apply.identity import canonical_json

    material = canonical_json({
        "summary": summary,
        "operations": [item.to_json() for item in operations],
    })
    return hashlib.sha256(material.encode("ascii")).hexdigest()[:32]


@dataclass(frozen=True)
class TaskPlan:
    """What the executor proposes, at one revision."""

    plan_id: str
    revision: int
    summary: str
    operations: tuple[PlannedOperation, ...] = ()
    #: The executor's reply to the reviewers, when it revised. Free text, and
    #: sanitized like everything else. This is the *response*, not the private
    #: reasoning behind it: there is no field for the latter anywhere here.
    response_to_review: str = ""

    def __post_init__(self) -> None:
        if self.revision < 1:
            raise MalformedOutput("plan revisions begin at 1")
        if not self.plan_id:
            raise MalformedOutput("a plan needs an identifier")

    @property
    def fingerprint(self) -> str:
        return plan_fingerprint(self.operations, self.summary)

    @property
    def estimated_cost_units(self) -> int:
        return sum(item.estimated_cost_units for item in self.operations)

    def keys_for(self, task_id: str) -> tuple[str, ...]:
        """The idempotency key of every operation in this plan, in order.

        Keyed on the act, not on the position — so a revised plan that still
        contains an operation performed under the previous revision produces the
        same key for it, and the runtime skips it instead of doing it again.
        """
        return tuple(
            operation_key(
                task_id=task_id,
                name=item.name,
                tool=item.tool,
                arguments=item.arguments,
                destination=item.destination,
            )
            for item in self.operations
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "planId": self.plan_id,
            "revision": self.revision,
            "summary": self.summary,
            "fingerprint": self.fingerprint,
            "estimatedCostUnits": self.estimated_cost_units,
            "responseToReview": self.response_to_review,
            "operations": [item.to_json() for item in self.operations],
        }

    def to_review_json(self) -> dict[str, Any]:
        """The plan as a reviewer may see it. Structure kept, contents removed."""
        value = self.to_json()
        value["operations"] = [item.to_review_json() for item in self.operations]
        return value


@dataclass(frozen=True)
class ProducedOutput:
    """One thing the task made."""

    output_id: str
    kind: str = "text"
    content: str = ""
    classification: str = "internal"

    def __post_init__(self) -> None:
        if self.classification not in DATA_CLASSES:
            raise MalformedOutput(f"unknown output classification: {self.classification!r}")

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()[:32]

    @property
    def byte_size(self) -> int:
        return len(self.content.encode("utf-8"))

    def to_json(self) -> dict[str, Any]:
        return {
            "outputId": self.output_id,
            "kind": self.kind,
            "content": self.content,
            "classification": self.classification,
            "digest": self.digest,
            "byteSize": self.byte_size,
        }


@dataclass(frozen=True)
class TaskResult:
    """What the task produced, and how it should be summarised."""

    result_id: str
    summary: str
    outputs: tuple[ProducedOutput, ...] = ()
    classification: str = "internal"

    def __post_init__(self) -> None:
        if not self.result_id:
            raise MalformedOutput("a result needs an identifier")
        if self.classification not in DATA_CLASSES:
            raise MalformedOutput(f"unknown result classification: {self.classification!r}")

    def to_json(self) -> dict[str, Any]:
        return {
            "resultId": self.result_id,
            "summary": self.summary,
            "classification": self.classification,
            "outputs": [item.to_json() for item in self.outputs],
        }


@dataclass(frozen=True)
class TaskContext:
    """Everything an executor is given, and nothing more.

    Note what is absent: the store, the runtime, the tool broker, the approval
    store, the other tasks in the session. An executor that wanted to read
    another task's events or perform an operation directly has nothing to reach
    for. This is the same argument as :class:`companion.reviewer.ReviewContext`,
    applied one privilege level up.
    """

    task: Mapping[str, Any]
    #: The task's classification, so an executor can refuse work it should not
    #: hold rather than relying on the runtime to have checked.
    classification: str
    plan_revision: int
    #: Operations this task has already completed, by idempotency key. Present
    #: so that a replan after a crash can leave them alone. An executor that
    #: ignores this and replans them anyway is caught by the runtime, which
    #: checks the same set before performing anything.
    completed_operation_keys: frozenset[str] = frozenset()
    #: Operations that were started and never settled — the runtime stopped
    #: between the two events and whether they happened is not known. The
    #: runtime will refuse to perform an operation whose key is in here, so an
    #: executor that needs the work done must plan a *different* act (different
    #: arguments, or a step that first establishes what the state actually is)
    #: rather than the same one again.
    unknown_operation_keys: frozenset[str] = frozenset()
    #: Reviewer observations from the previous round, redacted to what a
    #: reviewer was allowed to see in the first place.
    observations: tuple[Mapping[str, Any], ...] = ()
    #: Results of the operations performed under the previous plan revision.
    operation_results: tuple[Mapping[str, Any], ...] = ()
    remaining_cost_units: int = 0
    remaining_seconds: float = float("inf")

    def to_json(self) -> dict[str, Any]:
        return {
            "task": dict(self.task),
            "classification": self.classification,
            "planRevision": self.plan_revision,
            "completedOperationKeys": sorted(self.completed_operation_keys),
            "unknownOperationKeys": sorted(self.unknown_operation_keys),
            "observations": [dict(item) for item in self.observations],
            "operationResults": [dict(item) for item in self.operation_results],
            "remainingCostUnits": self.remaining_cost_units,
            "remainingSeconds": self.remaining_seconds,
        }


class Executor(Protocol):
    """A provider-neutral executor."""

    declaration: ExecutorDeclaration

    def health(self) -> ExecutorHealth:
        """Whether this executor can take work right now."""

    def plan(self, context: TaskContext) -> TaskPlan:
        """Propose what should be done. Must not do any of it."""

    def result(self, context: TaskContext) -> TaskResult:
        """Produce the task's outputs from the operations that were performed."""

    def cancel(self, context: TaskContext, reason: str) -> None:
        """Stop. Called at most once, and after the runtime has already refused
        every further operation, so an executor that ignores this cannot cause
        anything to happen — it only fails to release its own resources."""


# --------------------------------------------------------------------------- #
# The one shipped implementation.
# --------------------------------------------------------------------------- #


@dataclass
class DeterministicLocalExecutor:
    """A pure, local, free executor that always produces the same answer.

    It exists so the whole runtime can be exercised — planning, approval,
    operations, review, revision, result, restart, replay — with no model, no
    network and no provider. Because it is deterministic, "the completed result
    is unchanged after restart" is a real comparison rather than a hope, and the
    vertical slice is a test rather than a demonstration.

    It plans word counting and then validation, in that order, because the local
    test reviewer is written to notice when the validation step is missing. The
    two together are the smallest honest exercise of the review-and-revise loop:
    the first plan omits validation, the reviewer says so, and the second plan
    includes it.
    """

    declaration: ExecutorDeclaration = field(default_factory=lambda: ExecutorDeclaration(
        executor_id="local.deterministic",
        provider_id="local",
        implementation_id="bunny-companion-deterministic-1",
        local=True,
        supported_task_types=("unclassified", "question", "summarise", "transform", "compute", "local_action"),
        supports_tools=True,
        supports_structured_output=True,
        supports_streaming=False,
        supports_cancellation=True,
        supports_resume=False,
        context_limit_tokens=4096,
        cost_class="free",
        # Local and pure: nothing it is given can leave, so it can hold anything.
        maximum_privacy_class="secret",
        requires_authentication=False,
    ))
    #: Set by a test to model an executor that has gone away.
    reported_health: ExecutorHealth = field(default_factory=ExecutorHealth)
    cancelled_with: str = ""
    #: Set by a test to model an executor that returns something that is not its
    #: contract. Never set in production; the field exists so the runtime's
    #: refusal of malformed output can be exercised without a mock that would
    #: also have to reimplement everything else.
    malformed: bool = False

    def health(self) -> ExecutorHealth:
        return self.reported_health

    # -- the desktop-intent path -------------------------------------------
    #
    # A request that names one of the assistant's bounded acts — "Open Files",
    # "what is in my Downloads folder" — is planned as that act, through
    # :mod:`companion.local_intent`. Everything else keeps the word-counting
    # plan below, unchanged.
    #
    # Delegated to rather than placed beside. Capability selection picks exactly
    # one local executor and the first eligible one wins, so a second executor
    # in front of this one took *every* task away from it — which the
    # integration slice caught by asserting that this executor is selected and
    # that its plan raises an approval. Neither remained true. Routing through
    # one executor keeps selection, the audit record and the slice exactly as
    # they were, and adds the acts.
    #
    # The import is deferred because local_intent imports this module.

    def _intent(self, request: str):
        from .intents import recognise

        return recognise(request)

    @staticmethod
    def _intent_executor():
        from .local_intent import LocalIntentExecutor

        return LocalIntentExecutor()

    def plan(self, context: TaskContext) -> TaskPlan:
        if self.malformed:
            return "this is not a plan"  # type: ignore[return-value]
        request = str(context.task.get("originalRequest", ""))
        if self._intent(request) is not None:
            return self._intent_executor().plan(context)
        revision = max(1, context.plan_revision)
        plan_id = "plan-" + hashlib.sha256(
            f"{context.task.get('taskId', '')}\x1f{revision}".encode("utf-8")
        ).hexdigest()[:16]

        operations = [
            PlannedOperation(
                name="count-words",
                tool="text.count_words",
                arguments={"text": request},
            ),
        ]
        # Revision 2 exists only in response to review. The first plan is
        # deliberately incomplete so that the reviewer has something true to say.
        asked_for_validation = any(
            "validat" in str(item.get("summary", "")).lower() for item in context.observations
        )
        if revision > 1 or asked_for_validation:
            operations.append(
                PlannedOperation(
                    name="validate-count",
                    tool="text.validate_count",
                    arguments={"text": request},
                )
            )
        # A request that asks to be told the answer plans a notice, and a notice
        # interrupts the user — so this is the branch that makes the runtime ask
        # for consent. The executor marks it, but the runtime decides
        # independently from the tool's declaration; see
        # companion.approvals.requirements_for.
        if _WANTS_NOTICE.search(request):
            operations.append(
                PlannedOperation(
                    name="publish-notice",
                    tool="notice.publish",
                    arguments={"text": "The word count is ready."},
                    requires_approval=True,
                    approval_action="interrupt_user_work",
                )
            )
        return TaskPlan(
            plan_id=plan_id,
            revision=revision,
            summary=(
                "Count the words in the request"
                + (", then validate the count" if len(operations) > 1 else "")
            ),
            operations=tuple(operations),
            response_to_review=(
                "The validation step the reviewer asked for has been added to this revision."
                if revision > 1 else ""
            ),
        )

    def result(self, context: TaskContext) -> TaskResult:
        request = str(context.task.get("originalRequest", ""))
        if self._intent(request) is not None:
            return self._intent_executor().result(context)
        counted = ""
        validated = ""
        for outcome in context.operation_results:
            if outcome.get("name") == "count-words":
                counted = str(outcome.get("value", ""))
            elif outcome.get("name") == "validate-count":
                validated = str(outcome.get("value", ""))
        body = f"words={counted}"
        if validated:
            body += f"; validation={validated}"
        # What the record keeps and what the user is told are different things.
        #
        # The body stays `words=N`: it is the audit record, the determinism
        # comparison across a restart is written against it, and the recovery
        # tests use its shape. The *summary* is what reaches a speech bubble on
        # a desktop, and "words=6; validation=consistent" is not an answer to
        # "write me a poem" — it is the executor describing its own internals to
        # somebody who asked a question. So the summary says what this assistant
        # can actually do, which is the true and useful answer to a request it
        # did not understand.
        from .intents import capability_sentence

        summary = capability_sentence()
        return TaskResult(
            result_id="result-" + hashlib.sha256(
                f"{context.task.get('taskId', '')}\x1f{body}".encode("utf-8")
            ).hexdigest()[:16],
            summary=display_summary(summary),
            outputs=(
                ProducedOutput(
                    output_id="output-1",
                    kind="text",
                    content=body,
                    classification=str(context.classification),
                ),
            ),
            classification=str(context.classification),
        )

    def cancel(self, context: TaskContext, reason: str) -> None:
        self.cancelled_with = reason

    # Convenience for tests that need an executor in a particular condition.
    def unavailable(self, detail: str) -> "DeterministicLocalExecutor":
        return replace(
            self,
            reported_health=ExecutorHealth(available=False, healthy=False, detail=detail),
        )


def context_for(
    task: CompanionTask,
    *,
    plan_revision: int,
    observations: Sequence[Mapping[str, Any]] = (),
    operation_results: Sequence[Mapping[str, Any]] = (),
    remaining_cost_units: int = 0,
) -> TaskContext:
    """Build the executor's view of a task.

    Uses the ``executor`` audience, which is the on-device ceiling. A remote
    executor is never handed one of these directly; :mod:`companion.runtime`
    builds a ``remote``-audience context for that case, and the difference is
    the point.
    """
    return TaskContext(
        task=task.view("executor"),
        classification=task.classification,
        plan_revision=plan_revision,
        completed_operation_keys=task.completed_operation_keys(),
        unknown_operation_keys=task.unknown_operation_keys(),
        observations=tuple(dict(item) for item in observations),
        operation_results=tuple(dict(item) for item in operation_results),
        remaining_cost_units=remaining_cost_units,
        remaining_seconds=task.deadline_remaining_seconds,
    )
