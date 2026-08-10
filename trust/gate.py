# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Turning a question into an answer, and the four ways an answer stops counting.

:mod:`trust.policy` can say *ask*. Only this module can turn an ask into an
allow, and it can only do so by way of an answer that a surface produced against
a ticket this gate issued. That is the whole security property, and it exists
because the permission surface is the part of Bunny OS most exposed to the rest
of the desktop: it draws, it takes input, it runs in the user's session, and it
is exactly the component an attacker would rather talk to than the policy engine.

**A ticket binds an answer to a question.** :class:`PromptTicket` carries a
digest of the request it was issued for. An answer naming a ticket id that was
never issued, or issued for a different request, is refused — so a surface cannot
answer a question that was not asked, and an answer captured from one prompt
cannot authorise another.

**A ticket is consumed exactly once.** The second presentation of an answer is
:class:`~trust.errors.TrustReplayed`, denied, and audited as a replay rather than
as an ordinary denial, because a replay is evidence about the system rather than
about the user.

**Silence is denial, and so is a broken surface.** §22 is explicit: if the visual
permission UI crashes, the privileged operation must not proceed. So a surface
that raises, returns ``None``, or takes longer than the ticket's life produces a
denial carrying ``failure`` — and the denial is distinguishable in the audit from
a person saying no, which matters because the two want different follow-up.

**The gate cannot widen an answer.** The scope in the answer must be one the
resolution offered, and the resolution's offered scopes come from the category
table. A surface that returned ``always`` for the microphone is refused, and that
refusal is a bug report about the surface.

Time is measured on a monotonic clock supplied by the caller. A ticket's life is
short — long enough for a person to read a sentence and press a button, short
enough that a prompt left on a locked screen for an hour is not still live when
somebody walks past. Wall-clock time is not used, so a clock that jumps cannot
extend a ticket.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import secrets
import time
from typing import Any, Callable, Mapping, Protocol

from .audit import TrustAudit
from .categories import DENY_SCOPE, descriptor
from .decision import Decision, Grant, Resolution
from .declaration import PermissionDeclaration
from .errors import TrustError, TrustSchemaError
from .explain import TrustPrompt, build_prompt
from .policy import resolve
from .request import PermissionRequest
from .store import TrustStore, utc_now

__all__ = [
    "DEFAULT_PROMPT_TTL_SECONDS",
    "ConsentSurface",
    "DenyingSurface",
    "PromptTicket",
    "ScriptedSurface",
    "TrustGate",
    "UserAnswer",
]

#: How long a prompt stands. Two minutes: long enough to read a sentence and
#: think, short enough that a question left on screen while somebody walks away
#: is dead before anybody else reaches the keyboard.
DEFAULT_PROMPT_TTL_SECONDS = 120.0


def _ticket_binding(request: PermissionRequest, offered: tuple[str, ...]) -> str:
    """A digest of everything the answer is an answer *to*.

    Includes the resource identifier, not merely its digest, and the offered
    scopes, so that a ticket cannot be reused after the question widened.
    """
    material = "\x00".join(
        (
            request.request_id,
            request.application_id,
            request.category,
            request.purpose,
            request.resource.kind,
            request.resource.identifier,
            request.session_id,
            request.task_id or "",
            ",".join(offered),
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PromptTicket:
    """One live question. Issued by the gate, consumed once, never reissued."""

    ticket_id: str
    binding: str
    issued_at: float
    expires_at: float

    def live_at(self, now: float) -> bool:
        return self.issued_at <= now < self.expires_at


@dataclass(frozen=True)
class UserAnswer:
    """What a surface reports a person chose.

    ``scope`` is meaningful only when ``verdict`` is ``allow``; a denial is always
    stored at :data:`~trust.categories.DENY_SCOPE` so that "no" persists and is
    not asked again on the next launch.
    """

    ticket_id: str
    verdict: str
    scope: str = "once"

    def __post_init__(self) -> None:
        if self.verdict not in ("allow", "deny"):
            raise TrustSchemaError(f"unknown answer verdict: {self.verdict!r}")


class ConsentSurface(Protocol):
    """Whatever puts the question in front of a person.

    Returning ``None`` means *nobody answered*, and the gate treats it as a
    denial. Raising means the surface is broken, and the gate treats that as a
    denial too. There is no third outcome and no way for a surface to defer.
    """

    def ask(self, prompt: TrustPrompt, ticket: PromptTicket) -> UserAnswer | None:
        ...


class DenyingSurface:
    """A surface that answers nothing. The default, and the safe one.

    Used wherever a consent surface has not been wired up — a headless test, a
    service starting before the session, a recovery shell. A component with no
    way to ask must not be able to proceed, and getting that by construction is
    better than by remembering to check.
    """

    def ask(self, prompt: TrustPrompt, ticket: PromptTicket) -> UserAnswer | None:
        return None


@dataclass
class ScriptedSurface:
    """A surface that answers from a list, for tests and the vertical slice.

    Answers are matched by category and consumed in order. An exhausted script
    answers nothing, which denies — so a test that forgets to script an answer
    fails closed rather than passing on a default.
    """

    answers: list[tuple[str, str, str]] = field(default_factory=list)
    asked: list[TrustPrompt] = field(default_factory=list)

    def ask(self, prompt: TrustPrompt, ticket: PromptTicket) -> UserAnswer | None:
        self.asked.append(prompt)
        for index, (category, verdict, scope) in enumerate(self.answers):
            if category == prompt.category:
                del self.answers[index]
                return UserAnswer(ticket_id=ticket.ticket_id, verdict=verdict, scope=scope)
        return None


@dataclass
class TrustGate:
    """The only path from a permission request to a permission.

    Holds the store, the audit and the surface. Every public method returns a
    :class:`~trust.decision.Decision` — never a bare boolean — because the caller
    needs the reason as much as the verdict, and a boolean is how a denial for
    "the store is corrupt" comes to be reported as "you said no".
    """

    store: TrustStore
    audit: TrustAudit
    surface: ConsentSurface = field(default_factory=DenyingSurface)
    #: Application id to display name. Supplied by the caller from the catalogue;
    #: an id with no name is shown as itself, which reads worse and is better than
    #: a prompt naming an application Bunny has invented a title for.
    names: Mapping[str, str] = field(default_factory=dict)
    clock: Callable[[], float] = time.monotonic
    prompt_ttl: float = DEFAULT_PROMPT_TTL_SECONDS
    _tickets: dict[str, PromptTicket] = field(default_factory=dict)
    _consumed: set[str] = field(default_factory=set)

    # -- the one entry point ---------------------------------------------

    def check(
        self,
        request: PermissionRequest,
        *,
        declaration: PermissionDeclaration,
        install_consent: bool = False,
    ) -> Decision:
        """Resolve, ask if necessary, persist, audit, and return the decision."""
        resolution = resolve(
            request,
            store=self.store,
            declaration=declaration,
            install_consent=install_consent,
        )
        if resolution.verdict == "allow":
            return self._settle(
                request, resolution, verdict="allow",
                scope=_scope_of(resolution), source=_source_of(resolution),
                existing=resolution.grant,
            )
        if resolution.verdict == "deny":
            return self._settle(
                request, resolution, verdict="deny", scope=DENY_SCOPE,
                source=_source_of(resolution), existing=resolution.grant,
            )
        return self._ask(request, resolution, declaration)

    # -- prompting -------------------------------------------------------

    def _ask(
        self,
        request: PermissionRequest,
        resolution: Resolution,
        declaration: PermissionDeclaration,
    ) -> Decision:
        now = self.clock()
        ticket = PromptTicket(
            ticket_id=secrets.token_urlsafe(18),
            binding=_ticket_binding(request, resolution.offered_scopes),
            issued_at=now,
            expires_at=now + self.prompt_ttl,
        )
        self._tickets[ticket.ticket_id] = ticket
        prompt = build_prompt(
            request, resolution, declaration,
            application_name=self.names.get(request.application_id),
        )
        try:
            answer = self.surface.ask(prompt, ticket)
        except Exception as exc:  # noqa: BLE001 - a broken surface must deny, not propagate
            self._tickets.pop(ticket.ticket_id, None)
            return self._settle(
                request, resolution, verdict="deny", scope=DENY_SCOPE, source="policy",
                reason_code="surface-failed", failure=f"{type(exc).__name__}: {exc}",
            )
        if answer is None:
            self._tickets.pop(ticket.ticket_id, None)
            return self._settle(
                request, resolution, verdict="deny", scope=DENY_SCOPE, source="policy",
                reason_code="unanswered", failure="nobody answered",
            )
        return self._accept(request, resolution, ticket, answer)

    def _accept(
        self,
        request: PermissionRequest,
        resolution: Resolution,
        ticket: PromptTicket,
        answer: UserAnswer,
    ) -> Decision:
        if answer.ticket_id in self._consumed:
            return self._settle(
                request, resolution, verdict="deny", scope=DENY_SCOPE, source="policy",
                reason_code="replayed", failure="that answer was already used",
            )
        held = self._tickets.pop(answer.ticket_id, None)
        if held is None or held.ticket_id != ticket.ticket_id:
            return self._settle(
                request, resolution, verdict="deny", scope=DENY_SCOPE, source="policy",
                reason_code="answer-mismatch", failure="that answer belongs to a different question",
            )
        self._consumed.add(held.ticket_id)
        if held.binding != _ticket_binding(request, resolution.offered_scopes):
            return self._settle(
                request, resolution, verdict="deny", scope=DENY_SCOPE, source="policy",
                reason_code="answer-mismatch", failure="the question changed after it was asked",
            )
        if not held.live_at(self.clock()):
            return self._settle(
                request, resolution, verdict="deny", scope=DENY_SCOPE, source="policy",
                reason_code="expired", failure="the question timed out",
            )
        if answer.verdict == "deny":
            return self._settle(request, resolution, verdict="deny", scope=DENY_SCOPE, source="user", reason_code="user-denied")
        if answer.scope not in resolution.offered_scopes:
            return self._settle(
                request, resolution, verdict="deny", scope=DENY_SCOPE, source="policy",
                reason_code="scope-not-offered", failure=f"{answer.scope} was not offered",
            )
        return self._settle(request, resolution, verdict="allow", scope=answer.scope, source="user", reason_code="user-allowed")

    # -- settling --------------------------------------------------------

    def _settle(
        self,
        request: PermissionRequest,
        resolution: Resolution,
        *,
        verdict: str,
        scope: str,
        source: str,
        reason_code: str | None = None,
        failure: str | None = None,
        existing: Grant | None = None,
    ) -> Decision:
        """Write the grant if this decision creates one, audit, and return.

        Exactly three things produce a durable grant, and the predicate below is
        the whole rule:

        * the scope is not ``once`` — a once decision leaves nothing behind, which
          is the entire meaning of once;
        * no grant already authorised this — an allow that came from a standing
          grant references that grant rather than writing a second copy of it,
          so re-launching an application does not grow the database once per use;
        * the source is a person or an install-time catalogue consent. A denial
          produced because a surface broke, a store was corrupt or a category was
          undeclared writes **nothing**. Storing those as "the user said no" would
          silently make the next launch refuse without asking, and would put a
          decision in Settings that nobody made.
        """
        grant: Grant | None = existing
        if existing is None and scope != "once" and source in ("user", "catalog"):
            grant = Grant(
                grant_id=secrets.token_urlsafe(12),
                application_id=request.application_id,
                category=request.category,
                resource=request.resource,
                purpose=request.purpose,
                scope=scope,
                verdict=verdict,
                source=source,
                decided_at=utc_now(),
                session_id=request.session_id if scope == "session" else None,
            )
            try:
                self.store.put(grant)
            except TrustError as exc:
                # The decision cannot be recorded, so it does not stand. Denial,
                # and the reason says the storage failed rather than the person.
                grant = None
                verdict, scope, source = "deny", DENY_SCOPE, "policy"
                reason_code, failure = "store-unwritable", str(exc)

        decision = Decision(
            request_id=request.request_id,
            application_id=request.application_id,
            category=request.category,
            resource=request.resource,
            purpose=request.purpose,
            verdict=verdict,
            scope=scope,
            source=source,
            reason_code=reason_code or resolution.reason_code,
            decided_at=utc_now(),
            session_id=request.session_id,
            task_id=request.task_id,
            grant_id=grant.grant_id if grant is not None else None,
        )
        self.audit.record_decision(decision, failure=failure or resolution.failure)
        return decision

    # -- revocation ------------------------------------------------------

    def revoke(self, grant_id: str, *, application_id: str) -> bool:
        """Withdraw one standing permission and say how soon it stops mattering."""
        grants = {grant.grant_id: grant for grant in self.store.for_application(application_id)}
        grant = grants.get(grant_id)
        removed = self.store.revoke(grant_id) if grant is not None else False
        if removed and grant is not None:
            self.audit.record_revocation(
                application_id=application_id,
                category=grant.category,
                resource=grant.resource,
                revocation=descriptor(grant.category).revocation,
                at=utc_now(),
            )
        return removed


def _scope_of(resolution: Resolution) -> str:
    """The scope an automatic allow stands at.

    A catalogue default is a ``session`` grant rather than an ``always`` one even
    though the consent was given at install: it means the application may use the
    capability while it is running, and the next launch re-derives it from the
    same consent. That keeps the durable record of what a person actually agreed
    to in one place — the install consent — instead of scattering derived
    ``always`` grants that outlive it.
    """
    if resolution.grant is not None:
        return resolution.grant.scope
    return "session"


def _source_of(resolution: Resolution) -> str:
    if resolution.grant is not None:
        return resolution.grant.source
    if resolution.reason_code == "catalog-default":
        return "catalog"
    return "policy"
