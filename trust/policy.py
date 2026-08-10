# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The decision procedure, written so that every exit is a denial or a question.

:func:`resolve` is the only function in Bunny OS that may conclude an application
is allowed to do something. It is deliberately short, deliberately ordered, and
deliberately has no branch that reaches ``allow`` without either a stored grant a
person made or a catalogue default whose risk is low enough that §19 permits one.

The order of the checks is the design, and it is checked by tests that assert on
the *reason code* rather than only on the verdict — because "denied because you
said no" and "denied because the store was corrupt" are the same verdict and
completely different facts.

1. **Malformed.** An unknown category, a resource of the wrong kind, a request
   whose fields do not typecheck. Denied, ``malformed-request``. Nothing else is
   consulted; a request nobody can read is not a request anybody can answer.
2. **Store unreadable.** Denied, ``store-unreadable``, with ``failure`` set.
   §22: if the policy system cannot determine whether an operation is allowed,
   deny it safely.
3. **Not declared.** The application is asking for something its catalogue entry
   never listed, or there is no entry. Denied, ``not-declared``. This is the
   strong reading of deny-by-default and it means no surface is ever asked to
   render the prompt.
4. **Beyond the declared network ceiling.** Denied, ``beyond-ceiling``. An entry
   that declared "reaches api.example.com" cannot ask for the internet.
5. **A standing denial.** Denied, ``user-denied``. Denials sort ahead of allows
   in :meth:`~trust.store.TrustStore.matching`, so a later deny on one file beats
   an earlier allow on the folder containing it.
6. **A standing allow.** Allowed, ``granted-previously``, carrying the grant so
   the audit can name which decision authorised this.
7. **A catalogue default.** Allowed, ``catalog-default``, only when the category
   is required, its risk is at most medium, and the user gave the install-time
   consent. Three conditions, all necessary.
8. **Otherwise, ask.** ``prompt``, with the scopes the category permits — and,
   for a high-risk category, never a scope wider than the category's own table
   allows regardless of what a caller asked for.

There is no ninth case. A request that falls off the end cannot happen, and the
function ends in a denial rather than an assertion so that if one ever did, the
consequence is a refusal rather than a traceback in a permission check.

**The policy never asks anybody anything.** It returns ``prompt``. Turning a
prompt into a decision requires a person and lives in :mod:`trust.gate`, which
also enforces that a decision arriving from a surface actually corresponds to the
resolution that authorised the prompt — the check that stops a compromised or
buggy surface from answering a question that was never asked.
"""

from __future__ import annotations

from .categories import descriptor
from .decision import Grant, Resolution
from .declaration import PermissionDeclaration
from .errors import TrustError, TrustStoreUnreadable
from .request import PermissionRequest
from .resources import network_covers
from .store import TrustStore

__all__ = [
    "REASON_CODES",
    "network_within_ceiling",
    "resolve",
]

#: Every reason a resolution can carry. Enumerated so a surface can be exhaustive
#: about the sentences it knows how to render, and a test can assert that no code
#: is produced that nothing can explain.
REASON_CODES = (
    "malformed-request",
    "store-unreadable",
    "not-declared",
    "unknown-application",
    "beyond-ceiling",
    "user-denied",
    "granted-previously",
    "catalog-default",
    "needs-user",
)


def network_within_ceiling(requested: str, ceiling: str) -> bool:
    """Whether a requested network class sits inside the declared ceiling.

    Reuses the lattice in :mod:`trust.resources` rather than restating it: the
    ceiling covers the request exactly when a grant of the ceiling would cover a
    request for it, and having two implementations of "which network class
    subsumes which" is how they come to disagree.
    """
    return network_covers(ceiling, requested)


def resolve(
    request: PermissionRequest,
    *,
    store: TrustStore,
    declaration: PermissionDeclaration,
    install_consent: bool = False,
) -> Resolution:
    """Decide, ask, or refuse. See the module docstring for the order."""
    # 1. Malformed. PermissionRequest validates at construction, so reaching here
    #    with a bad one means the category table changed underneath a serialised
    #    request. Re-checked rather than assumed.
    try:
        category = descriptor(request.category)
    except TrustError:
        return Resolution(verdict="deny", reason_code="malformed-request", failure="malformed-request")

    # 2. Store unreadable. Every read below could raise; doing it once here means
    #    there is exactly one place where a damaged store becomes a denial.
    try:
        matches = store.matching(request)
    except TrustStoreUnreadable as exc:
        return Resolution(verdict="deny", reason_code="store-unreadable", failure=str(exc) or "store-unreadable")

    # 3. Not declared.
    if not declaration.known:
        return Resolution(verdict="deny", reason_code="unknown-application")
    if declaration.application_id != request.application_id:
        return Resolution(verdict="deny", reason_code="malformed-request", failure="declaration-mismatch")
    if not declaration.declares(request.category):
        return Resolution(verdict="deny", reason_code="not-declared")

    # 4. Beyond the declared ceiling. Only network has one today; the check is
    #    written per resource kind so adding a second ceiling is a new branch
    #    rather than a change to this one.
    if request.resource.kind == "network":
        if not network_within_ceiling(request.resource.identifier, declaration.ceiling_identifier()):
            return Resolution(verdict="deny", reason_code="beyond-ceiling")

    # 5 and 6. Standing decisions, denials first.
    for grant in matches:
        if grant.verdict == "deny":
            return Resolution(verdict="deny", reason_code="user-denied", grant=grant)
        return Resolution(verdict="allow", reason_code="granted-previously", grant=grant)

    # 7. A catalogue default: required, low or medium risk, and consented to at
    #    install. All three, and the risk test is on the table rather than on the
    #    entry so an entry cannot promote itself.
    if install_consent and request.category in declaration.required and category.catalog_grantable:
        return Resolution(verdict="allow", reason_code="catalog-default")

    # 8. Ask. The offered scopes come from the category table, never from the
    #    caller: a request that asked to be granted "always" for the microphone
    #    is offered what the microphone offers.
    return Resolution(verdict="prompt", reason_code="needs-user", offered_scopes=category.allow_scopes)
