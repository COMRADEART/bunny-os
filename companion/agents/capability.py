# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Configured remote providers, restated for the capability router.

The router decides *whether work may leave this device* and needs a provider
declaration to decide against — retention, training use, locality,
jurisdiction, cost. Those are facts about a service, not about an adapter, so
they live in the provider configuration and are translated here into the
router's own :class:`capability.router.ProviderDeclaration`.

**Undeclared fails closed, and this build declares conservatively.** Where a
configuration does not state retention or training use, the values here are
``unspecified`` and ``None`` — which makes
:attr:`~capability.router.ProviderDeclaration.fully_declared` false and the
router refuse the destination. That is the correct outcome: a provider nobody
has said anything about is not a provider a user can be asked to consent to.

This module is the reason ``companion/agents`` may not import the runtime and
this file still can: it imports *capability*, not the task side, and the
service passes its output into ``RuntimeOptions.providers`` exactly as any
other provider list would arrive.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from capability.router import ProviderDeclaration as RouterDeclaration

from .config import AgentConfiguration, ProviderConfiguration

__all__ = ["ConfiguredRemoteProvider", "router_providers"]

#: What the companion asks a provider for. Mirrors
#: ``companion.capability_bridge.task_request_for``'s ``capability="inference"``.
_CAPABILITY = "inference"


@dataclass(frozen=True)
class ConfiguredRemoteProvider:
    """One configured remote provider, as the router sees it.

    ``available`` is deliberately *not* a network probe: §8 forbids touching a
    remote endpoint before an approval exists, and the router calls this while
    deciding whether to *offer* the destination. Availability here means
    "configured, enabled, and holding a resolvable credential" — the same
    ladder rung :class:`companion.agents.descriptor.ProviderStanding` calls
    ``authenticated``.
    """

    declaration: RouterDeclaration
    configured_and_authenticated: bool = False

    def available(self) -> bool:
        return self.configured_and_authenticated


def _declaration_for(config: ProviderConfiguration) -> RouterDeclaration:
    return RouterDeclaration(
        id=config.provider_id,
        title=f"{config.adapter_id} — {config.model_id or 'unspecified model'}",
        locality="hosted",
        # Retention and training use are facts the operator states about the
        # service; this build has no channel that carries them, so they stay
        # undeclared and the router fails the destination closed until one
        # exists. Stated here rather than guessed as "ephemeral/False", which
        # would be a promise nobody made.
        retention=config.retention,
        trains_on_input=config.trains_on_input,
        costs_money=config.cost_class != "free",
        capabilities=(_CAPABILITY,),
        jurisdiction=config.jurisdiction or "unspecified",
    )


def router_providers(
    configuration: AgentConfiguration,
    *,
    authenticated_ids: Sequence[str] = (),
) -> tuple[ConfiguredRemoteProvider, ...]:
    """Every enabled remote provider, as router destinations.

    ``authenticated_ids`` names the providers whose credential the registry
    could resolve. A provider without one is still listed — so the reason a
    destination is unavailable is "no credential", not silence — but reports
    itself unavailable, which is what keeps the router from offering it.
    """
    authenticated = set(authenticated_ids)
    return tuple(
        ConfiguredRemoteProvider(
            declaration=_declaration_for(config),
            configured_and_authenticated=config.provider_id in authenticated,
        )
        for config in configuration.providers
        if config.remote and config.enabled
    )
