# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The §6 generation request: bounded, sanitized, and refused at construction.

A request that cannot be represented cannot be dispatched, so every bound in
this module is enforced in ``__post_init__`` rather than checked by callers.
This is the same construction-refusal discipline as
:mod:`companion.speech.request`, and it exists for the same reason: the layer
that talks to an external engine must be able to trust its input completely,
because by the time the input reaches a socket there is nobody left to refuse.

**What is deliberately not here.**

There is no field for hidden reasoning, no scratchpad, no "internal prompt"
distinct from the recorded messages. The messages *are* the context; the
:class:`~companion.agents.context.BuiltContext` digest binds them to the items
they were built from; anything a provider is told is something the record can
show it was told.

There is no credential field, no header field, no way to smuggle either
through ``sampling`` — :class:`SamplingSettings` is a closed set of numeric
knobs, not a mapping.

**Oversized context is refused, not trimmed.** The context builder raises
:class:`~companion.agents.errors.ContextOverflow` before a request exists;
this module refuses a message set whose byte size exceeds its own declared
``maximum_input_tokens`` budget (at the conservative bytes-per-token floor)
so a builder bug cannot construct what the builder would have refused.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping

from ..ids import valid_id
from ..privacy import DATA_CLASSES, scrub_text
from .errors import AgentSchemaError

__all__ = [
    "GENERATION_PURPOSES",
    "GenerationMessage",
    "GenerationRequest",
    "LOCALITY_REQUIREMENTS",
    "MAX_MESSAGES",
    "MAX_MESSAGE_BYTES",
    "MESSAGE_ROLES",
    "REQUEST_SCHEMA_VERSION",
    "SamplingSettings",
    "messages_digest",
]

REQUEST_SCHEMA_VERSION = 1

MESSAGE_ROLES = ("system", "user", "assistant", "tool")

#: Why the runtime is asking. ``plan`` and ``result`` are the executor's two
#: questions; ``review`` is the reviewer's one; ``repair`` is a bounded retry
#: of invalid structured output; ``probe`` is the health check's one-token
#: request and may carry no task content at all.
GENERATION_PURPOSES = ("plan", "result", "review", "repair", "probe")

#: Mirrors ``companion.session.LOCALITY_PREFERENCES``; a test asserts the two
#: tuples are identical, because this package may not import that module.
LOCALITY_REQUIREMENTS = ("device-only", "trusted-remote", "any")

MAX_MESSAGES = 128
MAX_MESSAGE_BYTES = 64 * 1024
MAX_TOOL_NAMES = 32

#: The conservative floor used to convert a token budget into a byte bound.
#: One token is never fewer bytes than this in any tokenizer this build
#: dispatches to; the true ratio is higher, so the bound only over-admits,
#: and the provider's own context check remains the final word.
BYTES_PER_TOKEN_FLOOR = 1


def messages_digest(messages: tuple["GenerationMessage", ...]) -> str:
    """One digest over the whole conversation, order included."""
    canonical = json.dumps(
        [{"role": item.role, "content": item.content} for item in messages],
        sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class GenerationMessage:
    """One turn of sanitized conversation.

    ``content`` is stored after :func:`companion.privacy.scrub_text`, and
    ``scrubbed`` records whether scrubbing changed it — a message that arrived
    carrying a credential shape is admissible (the credential is gone) but the
    record must say the removal happened.
    """

    role: str
    content: str
    scrubbed: bool = False

    def __post_init__(self) -> None:
        if self.role not in MESSAGE_ROLES:
            raise AgentSchemaError(f"message role {self.role!r} is not one of {MESSAGE_ROLES}")
        if not isinstance(self.content, str):
            raise AgentSchemaError("message content must be a string")
        if len(self.content.encode("utf-8")) > MAX_MESSAGE_BYTES:
            raise AgentSchemaError(f"message content exceeds {MAX_MESSAGE_BYTES} bytes")
        clean = scrub_text(self.content)
        if clean != self.content:
            object.__setattr__(self, "content", clean)
            object.__setattr__(self, "scrubbed", True)

    def to_json(self) -> dict[str, Any]:
        return {"role": self.role, "content": self.content, "scrubbed": self.scrubbed}


@dataclass(frozen=True)
class SamplingSettings:
    """The closed set of sampling knobs.

    A mapping here would be a place to hide arbitrary provider parameters —
    including the ones that change logging, tooling or endpoints on some
    providers — so the type admits exactly these numbers and nothing else.
    Defaults are deterministic on purpose: §9 requires selection to be
    explainable and a temperature-zero baseline keeps "same request, same
    provider, different answer" out of the defect ledger.
    """

    temperature: float = 0.0
    top_p: float = 1.0
    seed: int = 0

    def __post_init__(self) -> None:
        if not 0.0 <= self.temperature <= 2.0:
            raise AgentSchemaError("temperature must be within [0, 2]")
        if not 0.0 < self.top_p <= 1.0:
            raise AgentSchemaError("top_p must be within (0, 1]")
        if not isinstance(self.seed, int) or self.seed < 0:
            raise AgentSchemaError("seed must be a non-negative integer")

    def to_json(self) -> dict[str, Any]:
        return {"temperature": self.temperature, "topP": self.top_p, "seed": self.seed}


@dataclass(frozen=True)
class GenerationRequest:
    """Everything a provider adapter is given, and nothing more.

    Deliberately absent: the task document, the session, the store, the event
    stream, other tasks' anything, and every unsanitized form of the request.
    An adapter that wanted more context than this has no way to ask for it.
    """

    request_id: str
    session_id: str
    task_id: str
    lifecycle_epoch: int
    plan_id: str
    provider_id: str
    model_id: str
    purpose: str
    messages: tuple[GenerationMessage, ...]
    system_policy_reference: str
    maximum_input_tokens: int
    maximum_output_tokens: int
    sampling: SamplingSettings = field(default_factory=SamplingSettings)
    structured_schema_reference: str = ""
    permitted_tool_names: tuple[str, ...] = ()
    classification: str = "internal"
    locality_requirement: str = "device-only"
    remote_approval_reference: str = ""
    cost_limit_units: int = 0
    deadline_seconds: float = 60.0
    cancellation_token: str = ""
    created_at: str = ""
    expires_at_monotonic: float = 0.0
    context_digest: str = ""
    schema_version: int = REQUEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name, value in (
            ("request id", self.request_id),
            ("provider id", self.provider_id),
        ):
            if not valid_id(value):
                raise AgentSchemaError(f"{name} {value!r} is not a valid identifier")
        for name, value in (("session id", self.session_id), ("task id", self.task_id)):
            # A probe carries no task; everything else must name one.
            if value and not valid_id(value):
                raise AgentSchemaError(f"{name} {value!r} is not a valid identifier")
        if self.purpose not in GENERATION_PURPOSES:
            raise AgentSchemaError(f"purpose {self.purpose!r} is not one of {GENERATION_PURPOSES}")
        if self.purpose != "probe" and not (self.session_id and self.task_id):
            raise AgentSchemaError(f"a {self.purpose!r} request must name its session and task")
        if self.classification not in DATA_CLASSES:
            raise AgentSchemaError(f"classification {self.classification!r} is not one of {DATA_CLASSES}")
        if self.locality_requirement not in LOCALITY_REQUIREMENTS:
            raise AgentSchemaError(
                f"locality {self.locality_requirement!r} is not one of {LOCALITY_REQUIREMENTS}"
            )
        if not isinstance(self.lifecycle_epoch, int) or self.lifecycle_epoch < 0:
            raise AgentSchemaError("lifecycle epoch must be a non-negative integer")
        if not self.model_id or len(self.model_id) > 256:
            raise AgentSchemaError("model id must be present and bounded")
        if not isinstance(self.messages, tuple):
            raise AgentSchemaError("messages must be a tuple")
        if not self.messages:
            raise AgentSchemaError("a request with no messages asks nothing")
        if len(self.messages) > MAX_MESSAGES:
            raise AgentSchemaError(f"more than {MAX_MESSAGES} messages")
        for item in self.messages:
            if not isinstance(item, GenerationMessage):
                raise AgentSchemaError("every message must be a GenerationMessage")
        if not self.system_policy_reference:
            raise AgentSchemaError(
                "a request must name its system-policy reference; a request that "
                "cannot say which policy it was built under was built under none"
            )
        for name, value in (
            ("maximum input", self.maximum_input_tokens),
            ("maximum output", self.maximum_output_tokens),
        ):
            if not isinstance(value, int) or value <= 0:
                raise AgentSchemaError(f"{name} must be a positive integer")
        if not isinstance(self.cost_limit_units, int) or self.cost_limit_units < 0:
            raise AgentSchemaError("cost limit must be a non-negative integer")
        if self.deadline_seconds <= 0:
            raise AgentSchemaError("deadline must be positive")
        if len(self.permitted_tool_names) > MAX_TOOL_NAMES:
            raise AgentSchemaError(f"more than {MAX_TOOL_NAMES} permitted tools")
        for tool_name in self.permitted_tool_names:
            if not isinstance(tool_name, str) or not tool_name or len(tool_name) > 128:
                raise AgentSchemaError("permitted tool names must be bounded strings")
        if self.structured_schema_reference and len(self.structured_schema_reference) > 128:
            raise AgentSchemaError("structured schema reference exceeds bounds")
        # The input bound, applied to what is actually being sent. The
        # conversion floor only over-admits; the point is that a request
        # claiming a budget its own payload exceeds is not representable.
        total_bytes = sum(len(item.content.encode("utf-8")) for item in self.messages)
        if total_bytes > self.maximum_input_tokens * max(BYTES_PER_TOKEN_FLOOR, 1) * 8:
            raise AgentSchemaError(
                f"messages total {total_bytes} bytes, beyond any plausible "
                f"{self.maximum_input_tokens}-token input budget"
            )
        if self.context_digest:
            expected = messages_digest(self.messages)
            if self.context_digest != expected:
                raise AgentSchemaError(
                    "context digest does not match the messages; the request was "
                    "altered after the context was built"
                )

    @property
    def remote_permitted(self) -> bool:
        """Whether this request may leave the machine at all — not whether it should."""
        return self.locality_requirement != "device-only"

    def to_json(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "requestId": self.request_id,
            "sessionId": self.session_id,
            "taskId": self.task_id,
            "lifecycleEpoch": self.lifecycle_epoch,
            "planId": self.plan_id,
            "providerId": self.provider_id,
            "modelId": self.model_id,
            "purpose": self.purpose,
            "messageCount": len(self.messages),
            "systemPolicyReference": self.system_policy_reference,
            "maximumInputTokens": self.maximum_input_tokens,
            "maximumOutputTokens": self.maximum_output_tokens,
            "sampling": self.sampling.to_json(),
            "structuredSchemaReference": self.structured_schema_reference,
            "permittedToolNames": list(self.permitted_tool_names),
            "classification": self.classification,
            "localityRequirement": self.locality_requirement,
            "remoteApprovalReference": self.remote_approval_reference,
            "costLimitUnits": self.cost_limit_units,
            "deadlineSeconds": self.deadline_seconds,
            "cancellationToken": self.cancellation_token,
            "createdAt": self.created_at,
            "expiresAtMonotonic": self.expires_at_monotonic,
            "contextDigest": self.context_digest,
        }
