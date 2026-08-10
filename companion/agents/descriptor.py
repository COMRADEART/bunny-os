# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What a text-generation provider *is*, stated once, with nowhere to put a key.

The descriptor is the §3 schema: a versioned, strictly bounded record of one
provider as configured on this machine. Everything above this module — the
registry, the selection explanation, the protocol operations, the GTK status
surface — reads descriptors; nothing reads an adapter's private state.

**There is no credential field.** Not an optional one, not a redacted one, not
a "reference that is usually safe". A descriptor records *which kind* of
authentication is available (:data:`AUTHENTICATION_KINDS`) and whether a
credential is *present* — never its value, never its file path beyond the
approved-location label, never a header it would appear in. The way to keep a
secret out of every event, log, task record and protocol response is for the
type they all serialize to have nowhere to put it.

**The ladder is six words and each one is earned separately:**

``configured``
    The provider appears in the configuration with ``enabled: true``. Says
    nothing about whether it can be reached.
``authenticated``
    Its declared credential requirement is met — a credential is *present* at
    the declared source. Local providers that need none are authenticated by
    vacuity.
``available``
    The most recent probe reached the endpoint (or resolved the program) and
    the declared model was offered.
``healthy``
    Available, and the circuit breaker is closed: recent generations have not
    been failing.
``eligible``
    Healthy, and permitted for one *specific* request under privacy, locality,
    cost and capability policy. Eligibility is a property of a
    (provider, request) pair and lives in
    :class:`companion.agents.registry.SelectionExplanation`, not here.
``selected``
    Eligible, and first in the deterministic order. Exactly one provider per
    generation.

A configured provider is not necessarily eligible, and every step of the
ladder a provider fails to climb is recorded with a reason — an absent local
runtime must be distinguishable from an unsupported request, because the first
is fixed with ``dnf install`` and the second with a policy change.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping

from ..ids import valid_id
from ..privacy import DATA_CLASSES
from .errors import AgentSchemaError

__all__ = [
    "AUTHENTICATION_KINDS",
    "COST_CLASSES",
    "DESCRIPTOR_SCHEMA_VERSION",
    "ENDPOINT_KINDS",
    "EndpointIdentity",
    "MODALITIES",
    "PROVIDER_TYPES",
    "ProviderDescriptor",
    "ProviderStanding",
    "ResourceEstimate",
    "SUPPORTED_TASK_CLASSES",
]

DESCRIPTOR_SCHEMA_VERSION = 1

#: The only provider type this build implements. A future embedding or vision
#: provider is a new value here, not a new boolean on the descriptor.
PROVIDER_TYPES = ("text-generation",)

#: Mirrors ``companion.executor.COST_CLASSES``; a test asserts the two tuples
#: are identical, because this package may not import that module.
COST_CLASSES = ("free", "metered", "paid")

#: Mirrors ``companion.task.TASK_TYPES`` minus ``unclassified`` (no provider
#: declares support for "we do not know yet"); a test asserts the relationship.
SUPPORTED_TASK_CLASSES = (
    "question",
    "summarise",
    "transform",
    "retrieve",
    "compute",
    "local_action",
)

MODALITIES = ("text", "image", "audio")

#: How a credential *could* be supplied. Presence of a kind here says the
#: mechanism exists on this machine, never that a secret was seen.
AUTHENTICATION_KINDS = (
    "none",
    "secret-service",
    "credential-file",
    "environment",
    "hardware-backed",
)

#: Where a provider lives. ``loopback-http`` is pinned to loopback addresses at
#: request time — a "local" provider whose endpoint resolves elsewhere is a
#: refusal, not a slower kind of local (§20's SSRF case). ``subprocess`` names
#: an allowlisted program resolved from trusted directories only.
ENDPOINT_KINDS = ("loopback-http", "remote-https", "subprocess")

_MAX_TEXT = 512
_MAX_LIST = 64


def _require_text(name: str, value: str, *, limit: int = _MAX_TEXT) -> None:
    if not isinstance(value, str):
        raise AgentSchemaError(f"{name} must be a string, not {type(value).__name__}")
    if len(value) > limit:
        raise AgentSchemaError(f"{name} exceeds {limit} characters")


@dataclass(frozen=True)
class EndpointIdentity:
    """Where a provider is reached, precisely enough to bind an approval to.

    ``locator`` is host:port plus base path for HTTP endpoints and the program
    name for subprocess ones. It never carries a scheme userinfo section, a
    query string or a fragment — the places URLs hide credentials.
    """

    kind: str
    locator: str

    def __post_init__(self) -> None:
        if self.kind not in ENDPOINT_KINDS:
            raise AgentSchemaError(f"endpoint kind {self.kind!r} is not one of {ENDPOINT_KINDS}")
        _require_text("endpoint locator", self.locator, limit=256)
        if not self.locator:
            raise AgentSchemaError("endpoint locator must not be empty")
        lowered = self.locator.lower()
        if "@" in self.locator or "?" in self.locator or "#" in self.locator:
            raise AgentSchemaError("endpoint locator must not carry userinfo, query or fragment")
        if lowered.startswith(("http://", "https://")):
            raise AgentSchemaError("endpoint locator is host:port/path, not a URL; the scheme is the kind")

    @property
    def fingerprint(self) -> str:
        canonical = json.dumps({"kind": self.kind, "locator": self.locator}, sort_keys=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]

    def to_json(self) -> dict[str, Any]:
        return {"kind": self.kind, "locator": self.locator, "fingerprint": self.fingerprint}


@dataclass(frozen=True)
class ResourceEstimate:
    """What running this provider is expected to cost this machine.

    Estimates, labelled as such. The §25 measurements replace them with figures
    for the reference target; the descriptor keeps estimates so selection can
    weigh a provider that has not run yet.
    """

    memory_bytes: int = 0
    startup_seconds: float = 0.0
    expected_first_token_seconds: float = 0.0

    def __post_init__(self) -> None:
        if self.memory_bytes < 0 or self.startup_seconds < 0 or self.expected_first_token_seconds < 0:
            raise AgentSchemaError("resource estimates must be non-negative")

    def to_json(self) -> dict[str, Any]:
        return {
            "memoryBytes": self.memory_bytes,
            "startupSeconds": self.startup_seconds,
            "expectedFirstTokenSeconds": self.expected_first_token_seconds,
        }


@dataclass(frozen=True)
class ProviderStanding:
    """The first four rungs of the ladder, each with its reason.

    ``eligible`` and ``selected`` are deliberately absent: they exist only
    against a concrete request and are recorded in the selection explanation.
    A status display that showed "eligible" with no request in hand would be
    inventing the request.
    """

    configured: bool = False
    authenticated: bool = False
    available: bool = False
    healthy: bool = False
    detail: str = ""

    def __post_init__(self) -> None:
        _require_text("standing detail", self.detail)
        # The ladder is ordered: a rung cannot be held without the one below.
        if self.authenticated and not self.configured:
            raise AgentSchemaError("authenticated requires configured")
        if self.available and not self.authenticated:
            raise AgentSchemaError("available requires authenticated")
        if self.healthy and not self.available:
            raise AgentSchemaError("healthy requires available")

    @property
    def rung(self) -> str:
        if self.healthy:
            return "healthy"
        if self.available:
            return "available"
        if self.authenticated:
            return "authenticated"
        if self.configured:
            return "configured"
        return "unconfigured"

    def to_json(self) -> dict[str, Any]:
        return {
            "configured": self.configured,
            "authenticated": self.authenticated,
            "available": self.available,
            "healthy": self.healthy,
            "rung": self.rung,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ProviderDescriptor:
    """One provider as configured on this machine — the §3 record.

    Assembled by the registry from configuration, the latest probe and the
    health monitor; nothing in it is asserted by the provider itself except
    what the probe observed it offer. ``model_revision`` is whatever the
    runtime reports for the loaded model (a digest, a tag, a build string) so
    a result can be attributed to *which* weights produced it.
    """

    provider_id: str
    adapter_id: str
    provider_type: str = "text-generation"
    local: bool = True
    model_id: str = ""
    model_revision: str = ""
    endpoint: EndpointIdentity | None = None
    supported_task_classes: tuple[str, ...] = ()
    input_modalities: tuple[str, ...] = ("text",)
    output_modalities: tuple[str, ...] = ("text",)
    context_limit_tokens: int = 0
    maximum_output_tokens: int = 0
    supports_streaming: bool = False
    supports_structured_output: bool = False
    supports_tool_proposals: bool = False
    supports_image_input: bool = False
    supports_audio_input: bool = False
    supports_cancellation: bool = False
    available_authentication: tuple[str, ...] = ("none",)
    standing: ProviderStanding = field(default_factory=ProviderStanding)
    cost_class: str = "free"
    #: The highest :mod:`companion.privacy` class this provider may be handed.
    #: A remote provider above ``internal`` is refused at construction — the
    #: same ceiling :class:`companion.tools.ToolDeclaration` applies to an
    #: external destination, for the same reason.
    maximum_privacy_class: str = "secret"
    resource_estimate: ResourceEstimate = field(default_factory=ResourceEstimate)
    supported_languages: tuple[str, ...] = ("en",)
    license_reference: str = ""
    availability_detail: str = ""
    schema_version: int = DESCRIPTOR_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not valid_id(self.provider_id):
            raise AgentSchemaError(f"provider id {self.provider_id!r} is not a valid identifier")
        if not valid_id(self.adapter_id):
            raise AgentSchemaError(f"adapter id {self.adapter_id!r} is not a valid identifier")
        if self.provider_type not in PROVIDER_TYPES:
            raise AgentSchemaError(f"provider type {self.provider_type!r} is not one of {PROVIDER_TYPES}")
        if self.cost_class not in COST_CLASSES:
            raise AgentSchemaError(f"cost class {self.cost_class!r} is not one of {COST_CLASSES}")
        if self.maximum_privacy_class not in DATA_CLASSES:
            raise AgentSchemaError(
                f"privacy class {self.maximum_privacy_class!r} is not one of {DATA_CLASSES}"
            )
        if not self.local and DATA_CLASSES.index(self.maximum_privacy_class) > DATA_CLASSES.index("internal"):
            raise AgentSchemaError(
                "a remote provider may not declare a privacy ceiling above internal; "
                "the ceiling is a promise about where data may travel, not a preference"
            )
        for name, values, universe in (
            ("task class", self.supported_task_classes, SUPPORTED_TASK_CLASSES),
            ("input modality", self.input_modalities, MODALITIES),
            ("output modality", self.output_modalities, MODALITIES),
            ("authentication kind", self.available_authentication, AUTHENTICATION_KINDS),
        ):
            if len(values) > _MAX_LIST:
                raise AgentSchemaError(f"too many {name} entries")
            for value in values:
                if value not in universe:
                    raise AgentSchemaError(f"{name} {value!r} is not one of {universe}")
        if len(self.supported_languages) > _MAX_LIST:
            raise AgentSchemaError("too many language entries")
        for language in self.supported_languages:
            _require_text("language", language, limit=16)
        for name, value in (
            ("model id", self.model_id),
            ("model revision", self.model_revision),
            ("license reference", self.license_reference),
            ("availability detail", self.availability_detail),
        ):
            _require_text(name, value)
        for name, value in (
            ("context limit", self.context_limit_tokens),
            ("maximum output", self.maximum_output_tokens),
        ):
            if not isinstance(value, int) or value < 0:
                raise AgentSchemaError(f"{name} must be a non-negative integer")
        if self.schema_version != DESCRIPTOR_SCHEMA_VERSION:
            raise AgentSchemaError(
                f"descriptor schema version {self.schema_version!r} is not {DESCRIPTOR_SCHEMA_VERSION}"
            )
        # Declared support must be structurally coherent: an image-input
        # provider that does not list the modality would make the two fields
        # disagree about the same fact.
        if self.supports_image_input != ("image" in self.input_modalities):
            raise AgentSchemaError("image-input support and input modalities disagree")
        if self.supports_audio_input != ("audio" in self.input_modalities):
            raise AgentSchemaError("audio-input support and input modalities disagree")

    @property
    def fully_declared(self) -> bool:
        """Whether selection may consider this provider at all."""
        return bool(
            self.model_id
            and self.supported_task_classes
            and self.context_limit_tokens > 0
            and self.maximum_output_tokens > 0
            and self.endpoint is not None
        )

    def handles(self, task_class: str) -> bool:
        return task_class in self.supported_task_classes

    def to_json(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "providerId": self.provider_id,
            "adapterId": self.adapter_id,
            "providerType": self.provider_type,
            "local": self.local,
            "remoteTransmission": not self.local,
            "modelId": self.model_id,
            "modelRevision": self.model_revision,
            "endpoint": self.endpoint.to_json() if self.endpoint is not None else None,
            "supportedTaskClasses": list(self.supported_task_classes),
            "inputModalities": list(self.input_modalities),
            "outputModalities": list(self.output_modalities),
            "contextLimitTokens": self.context_limit_tokens,
            "maximumOutputTokens": self.maximum_output_tokens,
            "supportsStreaming": self.supports_streaming,
            "supportsStructuredOutput": self.supports_structured_output,
            "supportsToolProposals": self.supports_tool_proposals,
            "supportsImageInput": self.supports_image_input,
            "supportsAudioInput": self.supports_audio_input,
            "supportsCancellation": self.supports_cancellation,
            "availableAuthentication": list(self.available_authentication),
            "standing": self.standing.to_json(),
            "costClass": self.cost_class,
            "maximumPrivacyClass": self.maximum_privacy_class,
            "resourceEstimate": self.resource_estimate.to_json(),
            "supportedLanguages": list(self.supported_languages),
            "licenseReference": self.license_reference,
            "availabilityDetail": self.availability_detail,
            "fullyDeclared": self.fully_declared,
        }
