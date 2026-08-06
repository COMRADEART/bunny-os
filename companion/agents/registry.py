# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Eligibility and selection: deterministic, exhaustive, and always explained.

§9's rule is that selection is a *derivation*, not a ranking. There is no
score, no weight vector, no tie-break a reader cannot reproduce with the
configuration file and this docstring. The order is:

1. **Local before remote**, categorically. Not a large weight — a category.
   A remote provider is never merely "better"; it is a different act with an
   approval attached (§8), and no amount of latency preference promotes it
   past an eligible local one.
2. **User preference** within a category: the ``userPreferred`` configuration
   flag, then a request's explicit ``preferred_provider_id``.
3. **Configuration file order.** The user's file, read top to bottom, is the
   final tie-break, so "which one wins" is answerable by looking at it.

Eligibility gathers **all** reasons, never the first — the same discipline as
:func:`companion.capability_bridge._declaration_reasons` and for the same
reason: "ineligible: 4 reasons" with the list is a configuration session;
"ineligible: the first thing we noticed" is four configuration sessions.

The §10 ladder falls out of the same order: the ``fallback_order`` in every
explanation is the eligible list beyond the selected provider, and it is
*local-only unless the requirement already permits remote* — a local failure
re-selects among locals and then **blocks with the explanation**, because
"local failed" is a capability statement, not a consent. Remote never enters
a fallback chain it was not approved into.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..privacy import DATA_CLASSES, rank
from .adapter import ProbeResult, ProviderAdapter, unavailable_probe
from .config import AgentConfiguration, ProviderConfiguration
from .credentials import CredentialStatus, Secret, credential_status, resolve_credential
from .descriptor import ProviderDescriptor, ProviderStanding, ResourceEstimate
from .errors import AgentSchemaError
from .health import ProviderHealthMonitor
from .request import LOCALITY_REQUIREMENTS

__all__ = [
    "AgentProviderRegistry",
    "PROBE_TTL_SECONDS",
    "SelectionExplanation",
    "SelectionRequirement",
]

PROBE_TTL_SECONDS = 30.0


@dataclass(frozen=True)
class SelectionRequirement:
    """What one generation needs. Selection reads this and the descriptors."""

    task_class: str
    classification: str = "internal"
    locality: str = "device-only"
    requires_offline: bool = False
    needs_structured_output: bool = False
    needs_tool_proposals: bool = False
    needs_streaming: bool = True
    needs_image_input: bool = False
    needs_audio_input: bool = False
    estimated_context_tokens: int = 0
    estimated_output_tokens: int = 0
    cost_limit_units: int = 0
    preferred_provider_id: str = ""
    language: str = ""

    def __post_init__(self) -> None:
        if self.classification not in DATA_CLASSES:
            raise AgentSchemaError(f"classification {self.classification!r} is unknown")
        if self.locality not in LOCALITY_REQUIREMENTS:
            raise AgentSchemaError(f"locality {self.locality!r} is unknown")
        if self.estimated_context_tokens < 0 or self.estimated_output_tokens < 0:
            raise AgentSchemaError("token estimates must be non-negative")
        if self.cost_limit_units < 0:
            raise AgentSchemaError("cost limit must be non-negative")

    def to_json(self) -> dict[str, Any]:
        return {
            "taskClass": self.task_class,
            "classification": self.classification,
            "locality": self.locality,
            "requiresOffline": self.requires_offline,
            "needsStructuredOutput": self.needs_structured_output,
            "needsToolProposals": self.needs_tool_proposals,
            "needsStreaming": self.needs_streaming,
            "needsImageInput": self.needs_image_input,
            "needsAudioInput": self.needs_audio_input,
            "estimatedContextTokens": self.estimated_context_tokens,
            "estimatedOutputTokens": self.estimated_output_tokens,
            "costLimitUnits": self.cost_limit_units,
            "preferredProviderId": self.preferred_provider_id,
            "language": self.language,
        }


@dataclass(frozen=True)
class SelectionExplanation:
    """The complete answer to "why this provider", kept even on success."""

    requirement: Mapping[str, Any]
    eligible: tuple[str, ...]
    ineligible: tuple[tuple[str, tuple[str, ...]], ...]
    selected: str = ""
    selected_local: bool = True
    decisive_factors: tuple[str, ...] = ()
    fallback_order: tuple[str, ...] = ()
    requires_approval: bool = False
    approval_actions: tuple[str, ...] = ()
    detail: str = ""

    @property
    def found(self) -> bool:
        return bool(self.selected)

    def to_json(self) -> dict[str, Any]:
        return {
            "requirement": dict(self.requirement),
            "eligible": list(self.eligible),
            "ineligible": [
                {"providerId": provider_id, "reasons": list(reasons)}
                for provider_id, reasons in self.ineligible
            ],
            "selected": self.selected,
            "selectedLocal": self.selected_local,
            "decisiveFactors": list(self.decisive_factors),
            "fallbackOrder": list(self.fallback_order),
            "requiresApproval": self.requires_approval,
            "approvalActions": list(self.approval_actions),
            "detail": self.detail,
        }


class AgentProviderRegistry:
    """Holds configurations, adapters, probes, credentials and health — and
    answers every "which provider" question the subsystem asks.

    Probes are cached for :data:`PROBE_TTL_SECONDS` on the caller's monotonic
    clock, refreshed on demand; nothing here reads time itself.
    """

    def __init__(
        self,
        configuration: AgentConfiguration,
        adapters: Mapping[str, ProviderAdapter],
        *,
        monitor: ProviderHealthMonitor | None = None,
    ) -> None:
        self._configuration = configuration
        self._adapters = dict(adapters)
        self._monitor = monitor if monitor is not None else ProviderHealthMonitor()
        self._guard = threading.Lock()
        self._probes: dict[str, tuple[float, ProbeResult]] = {}

    @property
    def monitor(self) -> ProviderHealthMonitor:
        return self._monitor

    @property
    def configuration(self) -> AgentConfiguration:
        return self._configuration

    def provider_ids(self) -> tuple[str, ...]:
        return tuple(item.provider_id for item in self._configuration.providers)

    def configuration_for(self, provider_id: str) -> ProviderConfiguration | None:
        return self._configuration.provider(provider_id)

    def adapter_for(self, provider_id: str) -> ProviderAdapter | None:
        config = self.configuration_for(provider_id)
        if config is None:
            return None
        return self._adapters.get(config.adapter_id)

    def _approved_directories(self) -> tuple[Path, ...]:
        return tuple(Path(item) for item in self._configuration.approved_credential_directories)

    def credential_status_for(self, provider_id: str) -> CredentialStatus:
        config = self.configuration_for(provider_id)
        if config is None:
            return CredentialStatus(kind="none", present=False, detail="provider is not configured")
        return credential_status(config.credential, approved_directories=self._approved_directories())

    def resolve_secret(self, provider_id: str) -> Secret | None:
        """Resolved at dispatch, held by the caller for one call, never cached."""
        config = self.configuration_for(provider_id)
        if config is None or config.credential.kind == "none":
            return None
        return resolve_credential(config.credential, approved_directories=self._approved_directories())

    # -- probing -------------------------------------------------------------

    def probe(self, provider_id: str, *, monotonic: float, refresh: bool = False) -> ProbeResult:
        config = self.configuration_for(provider_id)
        if config is None:
            return unavailable_probe("unknown", f"provider {provider_id!r} is not configured")
        adapter = self._adapters.get(config.adapter_id)
        if adapter is None:
            return unavailable_probe(
                config.adapter_id, f"adapter {config.adapter_id!r} is not present in this build"
            )
        with self._guard:
            cached = self._probes.get(provider_id)
            if cached is not None and not refresh and monotonic - cached[0] < PROBE_TTL_SECONDS:
                return cached[1]
        result = adapter.probe(config)
        with self._guard:
            self._probes[provider_id] = (monotonic, result)
        return result

    # -- descriptors ---------------------------------------------------------

    def _resolved_model(self, config: ProviderConfiguration, probe: ProbeResult) -> tuple[str, str, int]:
        """(model_id, revision, context_limit) — configured first, else discovered."""
        context = config.context_limit_tokens
        for listing in probe.models:
            if listing.context_limit_tokens > 0:
                context = min(context, listing.context_limit_tokens) if config.model_id else listing.context_limit_tokens
                break
        if config.model_id:
            revision = config.model_revision
            for listing in probe.models:
                if listing.model_id == config.model_id and listing.revision:
                    revision = listing.revision
            return config.model_id, revision, context
        offered = sorted(item.model_id for item in probe.models)
        if offered:
            chosen = offered[0]
            for listing in probe.models:
                if listing.model_id == chosen:
                    return chosen, listing.revision, context
        return "", "", context

    def descriptor(self, provider_id: str, *, monotonic: float, refresh: bool = False) -> ProviderDescriptor:
        config = self.configuration_for(provider_id)
        if config is None:
            raise AgentSchemaError(f"provider {provider_id!r} is not configured")
        adapter = self._adapters.get(config.adapter_id)
        credential = self.credential_status_for(provider_id)
        configured = bool(config.enabled and adapter is not None)
        authenticated = bool(configured and credential.present)
        availability_detail = ""
        available = False
        model_id, model_revision, context_limit = config.model_id, config.model_revision, config.context_limit_tokens
        implementation = ""
        if not config.enabled:
            availability_detail = "not enabled in configuration"
        elif adapter is None:
            availability_detail = f"adapter {config.adapter_id!r} is not present in this build"
        elif not credential.present:
            availability_detail = f"credential absent: {credential.detail}"
        elif config.remote:
            # Remote availability is configuration + credential; the first
            # network contact is an approved generation, never a probe.
            available = True
            availability_detail = "configured; network is contacted only under an approval"
        else:
            probe = self.probe(provider_id, monotonic=monotonic, refresh=refresh)
            available = probe.available
            availability_detail = probe.detail
            implementation = probe.implementation
            model_id, model_revision, context_limit = self._resolved_model(config, probe)
        healthy = bool(available and self._monitor.healthy(provider_id))
        if available and not healthy:
            circuit = self._monitor.report(provider_id)["circuit"]
            availability_detail = (
                f"{availability_detail}; circuit {circuit['state']}"
                + (" (requires intervention)" if circuit["requiresIntervention"] else "")
            )
        standing = ProviderStanding(
            configured=configured,
            authenticated=authenticated,
            available=available,
            healthy=healthy,
            detail=availability_detail[:512],
        )
        # The adapter declares it; the registry reads it. A list of adapter
        # ids here was a real coupling a test double tripped over — an
        # adapter that exists but is not named would have been silently
        # denied a capability it implements.
        supports_structured = bool(getattr(adapter, "supports_structured_output", False))
        return ProviderDescriptor(
            provider_id=config.provider_id,
            adapter_id=config.adapter_id,
            local=config.local,
            model_id=model_id,
            model_revision=(model_revision or implementation)[:512],
            endpoint=config.endpoint,
            supported_task_classes=config.supported_task_classes,
            context_limit_tokens=max(0, context_limit),
            maximum_output_tokens=config.maximum_output_tokens,
            supports_streaming=True,
            supports_structured_output=supports_structured,
            supports_tool_proposals=supports_structured,
            supports_cancellation=True,
            available_authentication=(config.credential.kind,) if config.credential.kind != "none" else ("none",),
            standing=standing,
            cost_class=config.cost_class,
            maximum_privacy_class=config.maximum_privacy_class,
            resource_estimate=ResourceEstimate(),
            supported_languages=config.supported_languages,
            license_reference=config.license_reference,
            availability_detail=availability_detail[:512],
        )

    def descriptors(self, *, monotonic: float, refresh: bool = False) -> tuple[ProviderDescriptor, ...]:
        return tuple(
            self.descriptor(provider_id, monotonic=monotonic, refresh=refresh)
            for provider_id in self.provider_ids()
        )

    # -- selection -----------------------------------------------------------

    def _reasons(self, descriptor: ProviderDescriptor, requirement: SelectionRequirement) -> tuple[str, ...]:
        """Every reason, not the first one. Empty means eligible."""
        reasons: list[str] = []
        standing = descriptor.standing
        if not standing.configured:
            reasons.append(f"not configured: {standing.detail or 'not enabled'}")
        elif not standing.authenticated:
            reasons.append(f"not authenticated: {standing.detail}")
        elif not standing.available:
            reasons.append(f"not available: {standing.detail}")
        elif not standing.healthy:
            reasons.append(f"not healthy: {standing.detail}")
        if not descriptor.fully_declared:
            reasons.append("not fully declared: no model is configured or discovered")
        if not descriptor.handles(requirement.task_class):
            reasons.append(
                f"task class {requirement.task_class!r} is not in "
                f"{descriptor.supported_task_classes}"
            )
        if requirement.needs_structured_output and not descriptor.supports_structured_output:
            reasons.append("structured output is required and not supported")
        if requirement.needs_tool_proposals and not descriptor.supports_tool_proposals:
            reasons.append("tool proposals are required and not supported")
        if requirement.needs_streaming and not descriptor.supports_streaming:
            reasons.append("streaming is required and not supported")
        if requirement.needs_image_input and not descriptor.supports_image_input:
            reasons.append("image input is required and not supported")
        if requirement.needs_audio_input and not descriptor.supports_audio_input:
            reasons.append("audio input is required and not supported")
        if rank(requirement.classification) > rank(descriptor.maximum_privacy_class):
            reasons.append(
                f"classification {requirement.classification!r} exceeds the provider "
                f"ceiling {descriptor.maximum_privacy_class!r}"
            )
        if not descriptor.local:
            if requirement.locality == "device-only":
                reasons.append("the request is device-only and the provider is remote")
            if requirement.requires_offline:
                reasons.append("the request requires offline operation and the provider is remote")
        if requirement.estimated_context_tokens and descriptor.context_limit_tokens:
            if requirement.estimated_context_tokens > descriptor.context_limit_tokens:
                reasons.append(
                    f"context of ~{requirement.estimated_context_tokens} tokens exceeds the "
                    f"{descriptor.context_limit_tokens}-token window"
                )
        if requirement.estimated_output_tokens > descriptor.maximum_output_tokens > 0:
            reasons.append(
                f"requested output of ~{requirement.estimated_output_tokens} tokens exceeds "
                f"the {descriptor.maximum_output_tokens}-token maximum"
            )
        if descriptor.cost_class != "free" and requirement.cost_limit_units <= 0:
            reasons.append(
                f"cost class {descriptor.cost_class!r} against a zero cost ceiling; "
                "nothing may be spent"
            )
        if requirement.language and requirement.language not in descriptor.supported_languages:
            reasons.append(f"language {requirement.language!r} is not declared")
        return tuple(reasons)

    def select(self, requirement: SelectionRequirement, *, monotonic: float) -> SelectionExplanation:
        eligible: list[tuple[ProviderDescriptor, ProviderConfiguration]] = []
        ineligible: list[tuple[str, tuple[str, ...]]] = []
        for index, config in enumerate(self._configuration.providers):
            descriptor = self.descriptor(config.provider_id, monotonic=monotonic)
            reasons = self._reasons(descriptor, requirement)
            if reasons:
                ineligible.append((config.provider_id, reasons))
            else:
                eligible.append((descriptor, config))

        def order_key(item: tuple[ProviderDescriptor, ProviderConfiguration]) -> tuple[int, int, int, int]:
            descriptor, config = item
            position = self.provider_ids().index(config.provider_id)
            return (
                0 if descriptor.local else 1,
                0 if config.provider_id == requirement.preferred_provider_id else 1,
                0 if config.user_preferred else 1,
                position,
            )

        eligible.sort(key=order_key)
        ordered_ids = tuple(config.provider_id for _, config in eligible)
        if not eligible:
            return SelectionExplanation(
                requirement=requirement.to_json(),
                eligible=(),
                ineligible=tuple(ineligible),
                detail="no provider is eligible; every reason is listed",
            )
        selected_descriptor, selected_config = eligible[0]
        factors: list[str] = []
        factors.append(
            "local before remote" if selected_descriptor.local
            else "no local provider is eligible; remote requires approval"
        )
        if selected_config.provider_id == requirement.preferred_provider_id:
            factors.append("explicitly preferred by the request")
        if selected_config.user_preferred:
            factors.append("marked userPreferred in configuration")
        factors.append("configuration order breaks remaining ties")
        approval_actions: list[str] = []
        if not selected_descriptor.local:
            approval_actions.append("remote_dispatch")
            if rank(requirement.classification) >= rank("personal"):
                approval_actions.append("send_sensitive_data")
        if selected_descriptor.cost_class == "paid":
            approval_actions.append("paid_provider")
        return SelectionExplanation(
            requirement=requirement.to_json(),
            eligible=ordered_ids,
            ineligible=tuple(ineligible),
            selected=selected_config.provider_id,
            selected_local=selected_descriptor.local,
            decisive_factors=tuple(factors),
            fallback_order=ordered_ids[1:],
            requires_approval=bool(approval_actions),
            approval_actions=tuple(approval_actions),
            detail=f"selected {selected_config.provider_id!r} of {len(ordered_ids)} eligible",
        )

    def estimate_cost_units(self, provider_id: str, requirement: SelectionRequirement) -> int:
        config = self.configuration_for(provider_id)
        if config is None or not config.estimated_units_per_kilotoken:
            return 0
        tokens = requirement.estimated_context_tokens + requirement.estimated_output_tokens
        return -(-max(1, tokens) // 1000) * config.estimated_units_per_kilotoken

    def close(self) -> None:
        for adapter in self._adapters.values():
            adapter.close()

    def status(self, *, monotonic: float) -> dict[str, Any]:
        return {
            "providers": [item.to_json() for item in self.descriptors(monotonic=monotonic)],
            "health": self._monitor.reports(),
        }
