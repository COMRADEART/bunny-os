# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Provider-backed executors and reviewers: the one seam, on the runtime's side.

This module is to :mod:`companion.agents` what
:mod:`companion.capability_bridge` is to the capability runtime — the only
place both sides are imported, living *outside* the subsystem package so the
import-boundary test can keep the subsystem itself runtime-free.

Three classes, three different relationships to authority:

:class:`ProviderBackedExecutor`
    Fronts the **local** providers only. Plans are generated as structured
    output, validated locally, and become ordinary
    :class:`~companion.executor.PlannedOperation` tuples — which is the whole
    §13 story: a "tool proposal" is a plan entry, and it meets the same
    broker, the same approvals and the same lifecycle checks the deterministic
    executor's entries meet. The executor holds no broker, no store and no
    task; it turns a :class:`~companion.executor.TaskContext` into text and
    proposals, and the runtime decides.

:class:`RemoteProviderExecutor`
    Fronts exactly one configured remote provider, and resolves the §8
    chicken-and-egg honestly: *planning* would already transmit context, so
    its plan is produced deterministically on-device (zero operations, no
    generation), the approval binds to that plan and this destination, and
    the first byte leaves the machine in :meth:`result` — after
    ``_settle_approvals`` has granted ``remote_dispatch`` against the
    fingerprint of :meth:`destination_declaration`. No tool proposals, ever,
    from remote providers in this build. A remote failure falls back to
    nothing: a different destination is a different approval.

:class:`ProviderBackedReviewer`
    Observation-only, local-only, and fed the reviewer-projected context the
    coordination layer already builds. Its output passes through
    :func:`companion.reviewer.observation_from_json`, which refuses
    attribution to anyone else; a reviewer that cannot produce valid
    observations produces none.

§14's loop limits live here because this is where proposals are born: a plan
whose operation matches an operation the task has already failed twice is
stopped with :class:`~companion.errors.CoordinationLimitExceeded` before the
runtime spends anything on it.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

from .agents.context import SYSTEM_POLICY_REFERENCE
from .agents.errors import (
    AgentProviderError,
    ContextOverflow,
    GenerationBudgetExceeded,
    StructuredOutputInvalid,
)
from .agents.registry import SelectionExplanation, SelectionRequirement
from .agents.request import GenerationMessage, GenerationRequest
from .agents.service import AgentProviderService
from .agents.structured import (
    OBSERVATIONS_SCHEMA_REFERENCE,
    PLAN_SCHEMA_REFERENCE,
    parse_structured,
    repair_instruction,
)
from .clock import iso8601
from .errors import (
    ApprovalInvalidated,
    CapabilityRefused,
    CoordinationLimitExceeded,
    ExecutorUnavailable,
    MalformedOutput,
)
from .executor import (
    ExecutorDeclaration,
    ExecutorHealth,
    PlannedOperation,
    ProducedOutput,
    TaskContext,
    TaskPlan,
    TaskResult,
)
from .privacy import display_summary
from .reviewer import ReviewContext, ReviewObservation, observation_from_json
from .tools import ToolDeclaration

__all__ = [
    "ProviderBackedExecutor",
    "ProviderBackedReviewer",
    "RemoteProviderExecutor",
]

_PLAN_OUTPUT_TOKENS = 1024
_RESULT_OUTPUT_TOKENS = 768
_REVIEW_OUTPUT_TOKENS = 512
_GENERATION_DEADLINE_SECONDS = 120.0
#: §14: an operation that has already failed this many times may not be
#: proposed again for the same task.
_MAX_IDENTICAL_FAILED_PROPOSALS = 2


def _plan_identifier(task_id: str, revision: int) -> str:
    # The deterministic executor's exact derivation, kept so approvals and
    # transition ids behave identically across executor kinds.
    return "plan-" + hashlib.sha256(f"{task_id}\x1f{revision}".encode("utf-8")).hexdigest()[:16]


def _result_identifier(task_id: str, body: str) -> str:
    return "result-" + hashlib.sha256(f"{task_id}\x1f{body}".encode("utf-8")).hexdigest()[:16]


def _printable(text: str) -> str:
    """Strip ESC and C0 control bytes (newline and tab excepted) from provider text.

    The structured path *refuses* control bytes because structured output is a
    contract; plain text is prose, and prose is cleaned rather than refused —
    but it is cleaned *here*, before it becomes a ``ProducedOutput`` or a
    summary, because the next reader of the durable record may be a terminal.
    Found by the §20 security suite: ``display_summary`` scrubs credential
    shapes, not escape bytes.
    """
    return "".join(
        character for character in text
        if ord(character) >= 0x20 or character in ("\n", "\t")
    )


def _tool_lines(declarations: Sequence[ToolDeclaration]) -> str:
    lines = []
    for item in declarations:
        lines.append(f"- {item.tool_id}: {item.summary} (arguments: {{\"text\": string}})")
    return "\n".join(lines)


class ProviderBackedExecutor:
    """The local-provider executor. See the module docstring for the contract."""

    def __init__(
        self,
        service: AgentProviderService,
        *,
        executor_id: str = "agents.local-provider",
        tool_declarations: Sequence[ToolDeclaration] = (),
    ) -> None:
        self._service = service
        self._executor_id = executor_id
        self._tools = tuple(tool_declarations)
        self._permitted = tuple(item.tool_id for item in self._tools)
        local = [
            config for config in service.registry.configuration.providers
            if config.local and config.enabled
        ]
        supported: set[str] = set()
        context_limit = 0
        for config in local:
            supported.update(config.supported_task_classes)
            context_limit = max(context_limit, config.context_limit_tokens)
        self.declaration = ExecutorDeclaration(
            executor_id=executor_id,
            provider_id="agents.local",
            implementation_id="agents-runtime/1",
            local=True,
            supported_task_types=tuple(sorted(supported)) or ("question",),
            supports_tools=bool(self._permitted),
            supports_structured_output=True,
            supports_streaming=True,
            supports_cancellation=True,
            supports_resume=False,
            context_limit_tokens=context_limit or 4096,
            cost_class="free",
            maximum_privacy_class="secret",
            requires_authentication=False,
        )

    # -- health --------------------------------------------------------------

    def health(self) -> ExecutorHealth:
        now = self._service.clock.monotonic()
        details: list[str] = []
        for descriptor in self._service.registry.descriptors(monotonic=now):
            if not descriptor.local:
                continue
            if descriptor.standing.available and descriptor.fully_declared:
                healthy = descriptor.standing.healthy
                return ExecutorHealth(
                    available=True, authenticated=True, healthy=healthy,
                    detail=f"{descriptor.provider_id} ({descriptor.model_id})"
                           + ("" if healthy else "; circuit not closed"),
                )
            details.append(f"{descriptor.provider_id}: {descriptor.availability_detail}")
        return ExecutorHealth(
            available=False, authenticated=True, healthy=False,
            detail="no local provider is available: " + ("; ".join(details) or "none configured"),
        )

    # -- selection -----------------------------------------------------------

    def _requirement(self, context: TaskContext, *, purpose: str) -> SelectionRequirement:
        view = context.task
        task_class = str(view.get("taskType", "question"))
        if task_class not in self.declaration.supported_task_types:
            task_class = "question"
        request_bytes = len(str(view.get("originalRequest", "")).encode("utf-8"))
        estimated_context = max(256, request_bytes // 4 + 512)
        return SelectionRequirement(
            task_class=task_class,
            classification=str(context.classification),
            locality="device-only",
            requires_offline=bool(view.get("requiresOffline", False)),
            needs_structured_output=(purpose == "plan"),
            needs_tool_proposals=(purpose == "plan" and bool(self._permitted)),
            estimated_context_tokens=estimated_context,
            estimated_output_tokens=_PLAN_OUTPUT_TOKENS if purpose == "plan" else _RESULT_OUTPUT_TOKENS,
            cost_limit_units=int(context.remaining_cost_units),
            preferred_provider_id=self._sticky_provider(str(view.get("taskId", ""))),
        )

    def _sticky_provider(self, task_id: str) -> str:
        """One provider controls a task at a time; re-selection prefers it."""
        recorded = self._service.task_selection(task_id)
        if recorded is None:
            return ""
        return str(recorded.get("selected", ""))

    def _select(self, context: TaskContext, *, purpose: str) -> SelectionExplanation:
        requirement = self._requirement(context, purpose=purpose)
        explanation = self._service.registry.select(
            requirement, monotonic=self._service.clock.monotonic()
        )
        task_id = str(context.task.get("taskId", ""))
        if task_id:
            self._service.record_task_selection(task_id, explanation.to_json())
        if not explanation.found:
            reasons = tuple(
                f"{provider_id}: {'; '.join(reasons)}"
                for provider_id, reasons in explanation.ineligible
            ) or ("no providers are configured",)
            raise CapabilityRefused(
                "no agent provider is eligible for this task under current policy",
                reasons=reasons,
            )
        return explanation

    # -- generation plumbing -------------------------------------------------

    def _generate(
        self,
        context: TaskContext,
        explanation: SelectionExplanation,
        *,
        purpose: str,
        instruction: str,
        schema_reference: str,
        extra_messages: tuple[GenerationMessage, ...] = (),
    ) -> tuple[str, str]:
        """Run the ladder: selected provider, then eligible local alternates.

        Returns ``(text, provider_id)`` where text is the structured payload
        when a schema was requested. Raises only runtime-catchable types.
        """
        view = context.task
        service = self._service
        task_id = str(view.get("taskId", ""))
        session_id = str(view.get("sessionId", ""))
        failures: list[str] = []
        candidates = (explanation.selected,) + tuple(
            provider_id for provider_id in explanation.fallback_order
            if self._is_local(provider_id)
        )
        for provider_id in candidates:
            descriptor = service.registry.descriptor(
                provider_id, monotonic=service.clock.monotonic()
            )
            if schema_reference and not descriptor.supports_structured_output:
                failures.append(f"{provider_id}: no structured output")
                continue
            try:
                built = service.builder.build(
                    audience="executor",
                    classification=str(context.classification),
                    request_text=str(view.get("originalRequest", "")),
                    task_history=self._history_text(context),
                    observations_text=self._observations_text(context),
                    tool_results_text=self._tool_results_text(context),
                    context_limit_tokens=max(1, descriptor.context_limit_tokens),
                    maximum_input_tokens=max(1, descriptor.context_limit_tokens),
                    instruction=instruction,
                )
            except ContextOverflow as overflow:
                # No provider with a smaller window will fare better later in
                # the ladder than a bigger one did; refuse the task honestly.
                raise CapabilityRefused(
                    "the task context exceeds the provider's window and is "
                    "refused rather than trimmed",
                    reasons=(str(overflow),),
                ) from None
            messages = built.messages + extra_messages
            try:
                service.ledger.check_budget(
                    session_id=session_id, task_id=task_id,
                    task_limit_units=int(view.get("costLimitUnits", 0)),
                    session_limit_units=int(view.get("costLimitUnits", 0)),
                    next_generation_estimate_units=service.registry.estimate_cost_units(
                        provider_id, self._requirement(context, purpose=purpose)
                    ),
                )
            except GenerationBudgetExceeded as exceeded:
                raise CoordinationLimitExceeded(
                    str(exceeded), limit=exceeded.limit,
                    measured=exceeded.measured, allowed=exceeded.allowed,
                ) from None
            deadline = min(
                _GENERATION_DEADLINE_SECONDS,
                context.remaining_seconds if context.remaining_seconds > 0 else _GENERATION_DEADLINE_SECONDS,
            )
            request = GenerationRequest(
                request_id=service.ids.next("gen"),
                session_id=session_id,
                task_id=task_id,
                lifecycle_epoch=int(view.get("lifecycleEpoch", 0)),
                plan_id=_plan_identifier(task_id, max(1, context.plan_revision)),
                provider_id=provider_id,
                model_id=descriptor.model_id,
                purpose=purpose,
                messages=messages,
                system_policy_reference=SYSTEM_POLICY_REFERENCE,
                maximum_input_tokens=max(1, descriptor.context_limit_tokens),
                maximum_output_tokens=min(
                    descriptor.maximum_output_tokens or _PLAN_OUTPUT_TOKENS,
                    _PLAN_OUTPUT_TOKENS if purpose in ("plan", "repair") else _RESULT_OUTPUT_TOKENS,
                ),
                structured_schema_reference=schema_reference,
                permitted_tool_names=self._permitted if schema_reference == PLAN_SCHEMA_REFERENCE else (),
                classification=str(context.classification),
                locality_requirement="device-only",
                cost_limit_units=int(context.remaining_cost_units),
                deadline_seconds=deadline,
                created_at=iso8601(service.clock.wall()),
            )
            outcome = service.worker.generate(request)
            if outcome.cancelled:
                raise ExecutorUnavailable(
                    f"generation on {provider_id!r} was cancelled: {outcome.detail}"
                )
            if outcome.ok and outcome.assembled is not None:
                text = outcome.assembled.structured_text or outcome.assembled.text
                if text.strip():
                    return text, provider_id
                failures.append(f"{provider_id}: empty output")
                continue
            failures.append(f"{provider_id}: {outcome.failure_kind or 'failed'}: {outcome.detail}")
        # §10: the ladder ends in a blocked task with the explanation — never
        # in a quiet promotion to remote.
        raise CapabilityRefused(
            "every eligible local provider failed this generation",
            reasons=tuple(failures) or ("no candidates",),
        )

    def _is_local(self, provider_id: str) -> bool:
        config = self._service.registry.configuration_for(provider_id)
        return bool(config is not None and config.local)

    @staticmethod
    def _history_text(context: TaskContext) -> str:
        operations = tuple(context.task.get("operations", ()))
        if not operations:
            return ""
        lines = [
            f"{item.get('name', '?')}: {item.get('status', '?')}"
            for item in operations if isinstance(item, Mapping)
        ]
        return "Prior operations:\n" + "\n".join(lines) if lines else ""

    @staticmethod
    def _observations_text(context: TaskContext) -> str:
        if not context.observations:
            return ""
        lines = []
        for item in context.observations:
            if isinstance(item, Mapping):
                lines.append(
                    f"[{item.get('severity', 'info')}/{item.get('category', '?')}] "
                    f"{item.get('summary', '')} — {item.get('suggestedAction', '')}"
                )
        return "Reviewer observations to address:\n" + "\n".join(lines) if lines else ""

    @staticmethod
    def _tool_results_text(context: TaskContext) -> str:
        if not context.operation_results:
            return ""
        lines = []
        for item in context.operation_results:
            if isinstance(item, Mapping):
                lines.append(json.dumps(
                    {"name": item.get("name"), "value": item.get("value"),
                     "detail": item.get("detail")},
                    ensure_ascii=False, default=str,
                )[:1024])
        return "Executed tool results:\n" + "\n".join(lines) if lines else ""

    # -- §14: repeated-failure guard ----------------------------------------

    def _failed_operation_names(self, context: TaskContext) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in context.task.get("operations", ()):
            if isinstance(item, Mapping) and item.get("status") == "failed":
                name = str(item.get("name", ""))
                counts[name] = counts.get(name, 0) + 1
        return counts

    # -- Executor protocol ---------------------------------------------------

    def plan(self, context: TaskContext) -> TaskPlan:
        explanation = self._select(context, purpose="plan")
        instruction = (
            "Produce a plan as JSON matching exactly: "
            '{"summary": string, "operations": [{"name": identifier, "tool": string, '
            '"arguments": object, "rationale": string, "expectedEffect": string}]}. '
            "Propose at most 3 operations, only from these permitted tools:\n"
            + (_tool_lines(self._tools) or "- none: propose no operations")
            + "\nWhen no tool is needed, use an empty operations array. "
            "Respond with the JSON only."
        )
        text, provider_id = self._generate(
            context, explanation,
            purpose="plan", instruction=instruction,
            schema_reference=PLAN_SCHEMA_REFERENCE,
        )
        try:
            value, digest = parse_structured(text, PLAN_SCHEMA_REFERENCE)
        except StructuredOutputInvalid as invalid:
            value, digest = self._repair(context, explanation, text, invalid)
        return self._plan_from(context, value, provider_id)

    def _repair(
        self,
        context: TaskContext,
        explanation: SelectionExplanation,
        original: str,
        invalid: StructuredOutputInvalid,
    ) -> tuple[Any, str]:
        """One bounded repair round. The original survives as a digest."""
        extra = (
            GenerationMessage(role="assistant", content=original[:4096]),
            GenerationMessage(
                role="user",
                content=repair_instruction(PLAN_SCHEMA_REFERENCE, invalid.reason or str(invalid)),
            ),
        )
        text, _ = self._generate(
            context, explanation,
            purpose="repair",
            instruction="Correct the previous JSON so it validates. JSON only.",
            schema_reference=PLAN_SCHEMA_REFERENCE,
            extra_messages=extra,
        )
        try:
            return parse_structured(text, PLAN_SCHEMA_REFERENCE)
        except StructuredOutputInvalid as still_invalid:
            raise MalformedOutput(
                "structured plan output failed validation twice "
                f"(original digest {invalid.digest[:16]}, repair digest {still_invalid.digest[:16]}): "
                f"{still_invalid.reason}"
            ) from None

    def _plan_from(self, context: TaskContext, value: Mapping[str, Any], provider_id: str) -> TaskPlan:
        view = context.task
        task_id = str(view.get("taskId", ""))
        revision = max(1, context.plan_revision)
        failed_counts = self._failed_operation_names(context)
        operations: list[PlannedOperation] = []
        for entry in value.get("operations", ()):
            tool = str(entry.get("tool", ""))
            name = str(entry.get("name", ""))
            if tool not in self._permitted:
                raise MalformedOutput(
                    f"the provider proposed tool {tool!r}, which is not in the permitted set "
                    f"{self._permitted}; proposals outside the set are refused, not filtered"
                )
            if failed_counts.get(name, 0) >= _MAX_IDENTICAL_FAILED_PROPOSALS:
                raise CoordinationLimitExceeded(
                    f"operation {name!r} has already failed "
                    f"{failed_counts[name]} times and was proposed again; the loop stops here",
                    limit="repeated-failed-proposal",
                    measured=failed_counts[name],
                    allowed=_MAX_IDENTICAL_FAILED_PROPOSALS,
                )
            arguments = entry.get("arguments", {})
            operations.append(PlannedOperation(
                name=name or f"operation-{len(operations) + 1}",
                tool=tool,
                arguments=dict(arguments) if isinstance(arguments, Mapping) else {},
            ))
        summary = display_summary(str(value.get("summary", "")) or "Provider-generated plan")
        return TaskPlan(
            plan_id=_plan_identifier(task_id, revision),
            revision=revision,
            summary=summary,
            operations=tuple(operations),
            response_to_review=(
                f"Revision {revision} generated by {provider_id} addressing reviewer observations."
                if revision > 1 else ""
            ),
        )

    def result(self, context: TaskContext) -> TaskResult:
        explanation = self._select(context, purpose="result")
        instruction = (
            "Write the final answer for the user. Use the executed tool results "
            "verbatim where they answer the request. Plain text, at most one "
            "short paragraph. No JSON, no markup."
        )
        text, provider_id = self._generate(
            context, explanation,
            purpose="result", instruction=instruction,
            schema_reference="",
        )
        body = _printable(text).strip()
        view = context.task
        return TaskResult(
            result_id=_result_identifier(str(view.get("taskId", "")), body),
            summary=display_summary(body),
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
        task_id = str(context.task.get("taskId", ""))
        if task_id:
            self._service.worker.cancel_task(task_id, reason=reason or "cancelled")


class RemoteProviderExecutor(ProviderBackedExecutor):
    """One remote provider, approval-bound, text results only."""

    def __init__(
        self,
        service: AgentProviderService,
        remote_provider_id: str,
        *,
        executor_id: str = "",
    ) -> None:
        config = service.registry.configuration_for(remote_provider_id)
        if config is None or not config.remote:
            raise ExecutorUnavailable(
                f"{remote_provider_id!r} is not a configured remote provider"
            )
        super().__init__(
            service,
            executor_id=executor_id or f"agents.remote.{remote_provider_id}",
            tool_declarations=(),  # no remote tool proposals in this build
        )
        self._remote_id = remote_provider_id
        self._config = config
        self.declaration = ExecutorDeclaration(
            executor_id=self._executor_id,
            provider_id=remote_provider_id,
            implementation_id=f"agents-remote/{config.adapter_id}",
            local=False,
            supported_task_types=config.supported_task_classes,
            supports_tools=False,
            supports_structured_output=False,
            supports_streaming=True,
            supports_cancellation=True,
            supports_resume=False,
            context_limit_tokens=config.context_limit_tokens,
            cost_class=config.cost_class,
            maximum_privacy_class=config.maximum_privacy_class,
            requires_authentication=True,
        )

    def health(self) -> ExecutorHealth:
        descriptor = self._service.registry.descriptor(
            self._remote_id, monotonic=self._service.clock.monotonic()
        )
        standing = descriptor.standing
        return ExecutorHealth(
            available=standing.available,
            authenticated=standing.authenticated,
            healthy=standing.healthy or standing.available,
            detail=descriptor.availability_detail,
        )

    def destination_declaration(self, task: Any) -> Mapping[str, Any]:
        """The §8 binding material: what, where, how much — fingerprinted.

        Consumed by ``requirements_for`` via ``destination_fingerprint``; any
        change — provider, model, endpoint, data class, context bucket, cost
        ceiling, tool set, policy — changes the fingerprint, and the gate
        refuses the stale approval.
        """
        classification = getattr(task, "classification", "internal")
        cost_limit = getattr(task, "cost_limit_units", 0)
        request_length = len(getattr(task, "original_request", "") or "")
        context_bucket = -(-max(1, request_length) // 4096)
        return {
            "providerId": self._remote_id,
            "adapterId": self._config.adapter_id,
            "modelId": self._config.model_id,
            "endpoint": self._config.endpoint.to_json(),
            "dataClasses": [classification],
            "approximateContextBucket": context_bucket,
            "costCeilingUnits": cost_limit,
            "toolNames": [],
            "policyReference": SYSTEM_POLICY_REFERENCE,
        }

    def plan(self, context: TaskContext) -> TaskPlan:
        """Deterministic and on-device: nothing is transmitted to plan."""
        view = context.task
        task_id = str(view.get("taskId", ""))
        revision = max(1, context.plan_revision)
        task_selection = {
            "selected": self._remote_id,
            "selectedLocal": False,
            "requirement": {"taskClass": str(view.get("taskType", "question"))},
            "eligible": [self._remote_id],
            "ineligible": [],
            "decisiveFactors": ["no local provider is eligible; remote requires approval"],
            "fallbackOrder": [],
            "requiresApproval": True,
            "approvalActions": ["remote_dispatch"],
            "detail": "remote plan is deterministic; generation follows approval",
        }
        self._service.record_task_selection(task_id, task_selection)
        # The revision is *in the summary*, and therefore in the plan
        # fingerprint, on purpose. A remote plan has no operations, so two
        # attempts would otherwise fingerprint identically and the approval
        # gate would refuse the second as a replay — which is the gate working
        # correctly on a plan that lied about being the same act. Attempt two
        # is a second dispatch to somebody else's computer; §8 says that needs
        # its own approval, and this is how it gets one.
        return TaskPlan(
            plan_id=_plan_identifier(task_id, revision),
            revision=revision,
            summary=display_summary(
                f"Answer the request using the remote provider {self._remote_id}"
                + (f" (attempt {revision})" if revision > 1 else "")
            ),
            operations=(),
            response_to_review="" if revision == 1 else
            f"Revision {revision}: the remote plan is unchanged; only the answer is regenerated.",
        )

    def result(self, context: TaskContext) -> TaskResult:
        view = context.task
        task_id = str(view.get("taskId", ""))
        session_id = str(view.get("sessionId", ""))
        revision = max(1, context.plan_revision)
        plan_id = _plan_identifier(task_id, revision)
        approval_reference = ""
        for item in view.get("approvals", ()):
            if not isinstance(item, Mapping):
                continue
            if (
                item.get("action") == "remote_dispatch"
                and item.get("decision") == "granted"
                and item.get("planId") == plan_id
            ):
                approval_reference = str(item.get("requestId", ""))
        if not approval_reference:
            raise ApprovalInvalidated(
                "remote generation requires a granted remote_dispatch approval "
                "for this exact plan; none is on the task",
            )
        descriptor = self._service.registry.descriptor(
            self._remote_id, monotonic=self._service.clock.monotonic()
        )
        if not descriptor.fully_declared:
            raise ExecutorUnavailable(
                f"remote provider {self._remote_id!r} is not fully declared: "
                f"{descriptor.availability_detail}"
            )
        built = self._service.builder.build(
            audience="executor",
            classification=str(context.classification),
            request_text=str(view.get("originalRequest", "")),
            tool_results_text=self._tool_results_text(context),
            context_limit_tokens=max(1, descriptor.context_limit_tokens),
            maximum_input_tokens=max(1, descriptor.context_limit_tokens),
            instruction="Write the final answer for the user. Plain text, one short paragraph.",
        )
        request = GenerationRequest(
            request_id=self._service.ids.next("gen"),
            session_id=session_id,
            task_id=task_id,
            lifecycle_epoch=int(view.get("lifecycleEpoch", 0)),
            plan_id=plan_id,
            provider_id=self._remote_id,
            model_id=descriptor.model_id or self._config.model_id,
            purpose="result",
            messages=built.messages,
            system_policy_reference=SYSTEM_POLICY_REFERENCE,
            maximum_input_tokens=max(1, descriptor.context_limit_tokens),
            maximum_output_tokens=min(
                self._config.maximum_output_tokens, _RESULT_OUTPUT_TOKENS
            ),
            classification=str(context.classification),
            locality_requirement="trusted-remote",
            remote_approval_reference=approval_reference,
            cost_limit_units=int(context.remaining_cost_units),
            deadline_seconds=_GENERATION_DEADLINE_SECONDS,
            created_at=iso8601(self._service.clock.wall()),
        )
        outcome = self._service.worker.generate(request)
        if not outcome.ok or outcome.assembled is None:
            # §10: a failed remote does not authorise a different remote, and
            # a local fallback here would misattribute the destination the
            # user approved. The task fails with the reason.
            raise ExecutorUnavailable(
                f"the approved remote provider failed: "
                f"{outcome.failure_kind or 'cancelled'}: {outcome.detail}"
            )
        body = _printable(outcome.assembled.text or outcome.assembled.structured_text).strip()
        return TaskResult(
            result_id=_result_identifier(task_id, body),
            summary=display_summary(body),
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


class ProviderBackedReviewer:
    """Observation-only, local-only, attribution-enforced."""

    def __init__(
        self,
        service: AgentProviderService,
        *,
        reviewer_id: str = "agents.provider-reviewer",
        provider_id: str = "",
    ) -> None:
        self._service = service
        self.reviewer_id = reviewer_id
        self._provider_id = provider_id

    def observe(self, context: ReviewContext) -> Sequence[ReviewObservation]:
        service = self._service
        try:
            requirement = SelectionRequirement(
                task_class="question",
                classification=str(context.classification),
                locality="device-only",
                needs_structured_output=True,
                estimated_output_tokens=_REVIEW_OUTPUT_TOKENS,
                preferred_provider_id=self._provider_id,
            )
            explanation = service.registry.select(
                requirement, monotonic=service.clock.monotonic()
            )
            if not explanation.found:
                return ()
            selected = explanation.selected
            config = service.registry.configuration_for(selected)
            if config is None or not config.local:
                # Reviewers never dispatch remotely; a remote-only world
                # reviews with nobody rather than transmitting to review.
                return ()
            descriptor = service.registry.descriptor(
                selected, monotonic=service.clock.monotonic()
            )
            plan_text = json.dumps(dict(context.plan), ensure_ascii=False, default=str)[:8192]
            built = service.builder.build(
                audience="reviewer",
                classification=str(context.classification),
                request_text=str(context.task.get("displaySummary", ""))
                             or str(context.task.get("originalRequest", "")) or "(withheld)",
                plan_text=plan_text,
                context_limit_tokens=max(1, descriptor.context_limit_tokens),
                maximum_input_tokens=max(1, descriptor.context_limit_tokens),
                instruction=(
                    "You are an observation-only reviewer. Assess the plan for "
                    "correctness, security, privacy and policy concerns. Produce JSON "
                    'matching exactly: {"observations": [{"severity": one of '
                    '["info","low","medium","high","blocking"], "category": one of '
                    '["correctness","security","privacy","improvement","policy"], '
                    '"summary": string, "suggestedAction": string}]}. At most 3 '
                    "observations. You cannot execute anything, approve anything, or "
                    "change the plan. JSON only."
                ),
            )
            request = GenerationRequest(
                request_id=service.ids.next("gen"),
                session_id=str(context.task.get("sessionId", "")) or "review",
                task_id=str(context.task.get("taskId", "")) or "review",
                lifecycle_epoch=int(context.task.get("lifecycleEpoch", 0)),
                plan_id=str(context.plan.get("planId", "")),
                provider_id=selected,
                model_id=descriptor.model_id,
                purpose="review",
                messages=built.messages,
                system_policy_reference=SYSTEM_POLICY_REFERENCE,
                maximum_input_tokens=max(1, descriptor.context_limit_tokens),
                maximum_output_tokens=_REVIEW_OUTPUT_TOKENS,
                structured_schema_reference=OBSERVATIONS_SCHEMA_REFERENCE,
                classification=str(context.classification),
                locality_requirement="device-only",
                deadline_seconds=60.0,
                created_at=iso8601(service.clock.wall()),
            )
            outcome = service.worker.generate(request)
            if not outcome.ok or outcome.assembled is None:
                return ()
            text = outcome.assembled.structured_text or outcome.assembled.text
            value, _ = parse_structured(text, OBSERVATIONS_SCHEMA_REFERENCE)
            observations: list[ReviewObservation] = []
            for entry in value.get("observations", ())[:3]:
                document = {
                    "reviewerId": self.reviewer_id,
                    "severity": entry.get("severity", "info"),
                    "category": entry.get("category", "correctness"),
                    "summary": entry.get("summary", ""),
                    "suggestedAction": entry.get("suggestedAction", ""),
                }
                observations.append(
                    observation_from_json(document, reviewer_id=self.reviewer_id)
                )
            return tuple(observations)
        except (AgentProviderError, StructuredOutputInvalid, ValueError):
            # A reviewer that cannot review reviews nothing. Never fatal.
            return ()
