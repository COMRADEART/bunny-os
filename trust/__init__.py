# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Bunny Trust: the layer that turns a Linux capability into a question.

Bunny OS does not invent a security boundary. The boundaries are the ones Linux
already has — namespaces, seccomp, cgroups, bind mounts, portals, Polkit, the
existing ``bunny-system-broker``. What this package adds is the part those
primitives do not have: a model of *who is asking*, *for what*, *why, according
to whom*, and *what a person decided about it* — and a way to say all of that in
a sentence somebody who does not know what a portal is can act on.

The division of labour is fixed and is the whole design::

    the policy engine decides which capability is being requested
    Bunny Trust states it in ordinary language
    the person decides
    a Linux primitive enforces it

Nothing in this package enforces anything. It stores decisions and produces
sentences. Enforcement is :mod:`capsules.isolation`, which reads the grants and
builds a sandbox from them, and the portal and broker calls that sit behind
individual categories. Keeping those apart is what makes §22 achievable: if this
package crashes, no permission has been widened, because it was never the thing
holding the permission closed.

Module map, in the order a request travels:

:mod:`~trust.categories`
    The seventeen categories, their scopes, their risk, the Linux mechanism that
    enforces each and whether this build actually applies it.
:mod:`~trust.resources`
    What a permission is *about*, canonicalised so that two spellings of one file
    cannot become two grants.
:mod:`~trust.request`
    One question, with the provenance of every claim in it. There is no reason
    source meaning "the model inferred it".
:mod:`~trust.declaration`
    What the application said it would need. An application cannot ask for what
    it never declared.
:mod:`~trust.policy`
    Allow, deny, or ask — deny-by-default, fail-closed, eight ordered checks.
:mod:`~trust.explain`
    The sentence, the options, the attribution, and the honest note when a
    permission is not enforced by this build.
:mod:`~trust.gate`
    The only path from a question to a permission, with ticket binding, single
    consumption, and denial for silence and for a broken surface.
:mod:`~trust.store`
    Where standing grants live, and every way one stops standing.
:mod:`~trust.audit`
    What happened, with resource digests rather than resource contents.
:mod:`~trust.persistence`
    Durable, private, atomic files — one implementation for the three packages
    added in this phase.

A note on what is *not* here. There is no "trust score", no reputation, no
heuristic that decides an application is probably fine. Trust in this package
means a record of decisions a person made, plus the metadata a curated catalogue
publishes. Both are things that can be pointed at afterwards, which is the
property that matters when somebody asks why their microphone turned on.
"""

from __future__ import annotations

from .audit import ActivityEntry, TrustAudit, default_audit_path
from .categories import CATEGORIES, CATEGORY_IDS, SCOPES, CategoryDescriptor, descriptor
from .decision import DECISION_REASONS, Decision, Grant, Resolution
from .declaration import UNDECLARED, PermissionDeclaration
from .errors import (
    TrustError,
    TrustExpired,
    TrustNotDeclared,
    TrustRefused,
    TrustReplayed,
    TrustSchemaError,
    TrustStoreUnreadable,
    TrustSurfaceUnavailable,
)
from .explain import TrustPrompt, build_prompt, decision_sentence, revoke_sentence
from .gate import ConsentSurface, DenyingSurface, PromptTicket, ScriptedSurface, TrustGate, UserAnswer
from .policy import resolve
from .request import PermissionRequest, Reason
from .resources import (
    NETWORK_CLASSES,
    Resource,
    device_resource,
    network_resource,
    no_resource,
    path_resource,
    peer_resource,
)
from .store import TrustStore, default_store_path

#: The document version this package reads and writes. Bumped together with the
#: schema in ``schemas/trust-permission.schema.json``.
TRUST_SCHEMA_VERSION = 1

__all__ = [
    "CATEGORIES",
    "CATEGORY_IDS",
    "DECISION_REASONS",
    "NETWORK_CLASSES",
    "SCOPES",
    "TRUST_SCHEMA_VERSION",
    "UNDECLARED",
    "ActivityEntry",
    "CategoryDescriptor",
    "ConsentSurface",
    "Decision",
    "DenyingSurface",
    "Grant",
    "PermissionDeclaration",
    "PermissionRequest",
    "PromptTicket",
    "Reason",
    "Resolution",
    "Resource",
    "ScriptedSurface",
    "TrustAudit",
    "TrustError",
    "TrustExpired",
    "TrustGate",
    "TrustNotDeclared",
    "TrustPrompt",
    "TrustRefused",
    "TrustReplayed",
    "TrustSchemaError",
    "TrustStore",
    "TrustStoreUnreadable",
    "TrustSurfaceUnavailable",
    "UserAnswer",
    "build_prompt",
    "decision_sentence",
    "default_audit_path",
    "default_store_path",
    "descriptor",
    "device_resource",
    "network_resource",
    "no_resource",
    "path_resource",
    "peer_resource",
    "resolve",
    "revoke_sentence",
]
