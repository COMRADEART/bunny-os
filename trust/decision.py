# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What a person decided, what it covers, and when it stops counting.

Three values live here and the distinctions between them matter.

:class:`Decision` is the *answer* — an event, produced once, by a person or by a
policy rule, about one request. It is what the audit records.

:class:`Grant` is the *standing consequence* of an allow decision whose scope
outlives the request. A ``once`` decision produces no grant at all, which is the
whole meaning of ``once``: nothing is written down, so nothing can be reused.

:class:`Resolution` is what :mod:`trust.policy` returns: allow, deny, or "a
person has to be asked", together with the reason code and, when a person has to
be asked, the scopes the prompt may offer. Keeping the resolution separate from
the decision is what stops a policy engine from being able to answer on the
user's behalf: it can say ``prompt``, and only a decision carrying
``source="user"`` can say allow at a scope a person chose.

**Purpose widens in one direction only.** A grant for ``write`` covers a ``read``
of the same resource, because a person who allowed an application to change a
file has necessarily allowed it to look at the file. The converse is false and is
the case §15 turns on — "open this image" must not authorise overwriting it.

**Grants match on digests, never on display strings.** The display string is for
people and may be shortened, localised or reworded; two resources with the same
display can be different files.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .categories import SCOPES, descriptor
from .errors import TrustSchemaError
from .request import PURPOSES, PermissionRequest
from .resources import Resource

__all__ = [
    "DECISION_REASONS",
    "DECISION_SOURCES",
    "RESOLUTION_VERDICTS",
    "VERDICTS",
    "Decision",
    "Grant",
    "Resolution",
    "purpose_covers",
]

VERDICTS = ("allow", "deny")

RESOLUTION_VERDICTS = ("allow", "deny", "prompt")

#: Every reason a decision may carry, from both halves of the layer: the codes
#: :mod:`trust.policy` produces before anyone is asked, and the codes
#: :mod:`trust.gate` produces about the asking itself.
#:
#: Closed, and validated on construction, so that a surface can be exhaustive
#: about the sentences it knows how to render and a test can assert that no
#: decision is produced that nothing can explain. The five codes about the
#: *asking* — a broken surface, silence, a replay, a mismatched answer, a scope
#: that was never offered — are the ones that must never be conflated with
#: ``user-denied``: each is a statement about the system, and only ``user-denied``
#: is a statement about the person.
DECISION_REASONS = (
    # from trust.policy, before anybody is asked
    "malformed-request",
    "store-unreadable",
    "not-declared",
    "unknown-application",
    "beyond-ceiling",
    "user-denied",
    "granted-previously",
    "catalog-default",
    "needs-user",
    # from trust.gate, about the asking
    "user-allowed",
    "surface-failed",
    "unanswered",
    "replayed",
    "answer-mismatch",
    "expired",
    "scope-not-offered",
    "store-unwritable",
)

#: Who produced a decision. ``user`` is the only source that may allow at a scope
#: wider than ``once`` for a high-risk category; :mod:`trust.policy` enforces
#: that, and this tuple is what makes the rule expressible.
DECISION_SOURCES = ("user", "catalog", "policy", "system")

_PURPOSE_COVERS: Mapping[str, frozenset[str]] = {
    "write": frozenset({"write", "read"}),
    "read": frozenset({"read"}),
    "use": frozenset({"use"}),
}


def purpose_covers(held: str, wanted: str) -> bool:
    """Whether a grant for ``held`` authorises a request for ``wanted``."""
    if held not in PURPOSES or wanted not in PURPOSES:
        return False
    return wanted in _PURPOSE_COVERS[held]


@dataclass(frozen=True)
class Grant:
    """A standing permission: durable, revocable, and never wider than asked.

    ``session_id`` is set exactly when ``scope`` is ``session``. A session grant
    whose session is gone is not merely expired, it is *unevaluable* — the login
    it belonged to no longer exists — and :class:`~trust.store.TrustStore` drops
    those on load rather than carrying them forward.
    """

    grant_id: str
    application_id: str
    category: str
    resource: Resource
    purpose: str
    scope: str
    verdict: str
    source: str
    #: ISO-8601 UTC, for display in Settings and in the activity view only.
    #: Nothing decides anything from this field; see :mod:`trust.store` for why
    #: expiry is measured elsewhere.
    decided_at: str
    session_id: str | None = None

    def __post_init__(self) -> None:
        if self.verdict not in VERDICTS:
            raise TrustSchemaError(f"unknown verdict: {self.verdict!r}")
        if self.scope not in SCOPES:
            raise TrustSchemaError(f"unknown scope: {self.scope!r}")
        if self.scope == "once":
            raise TrustSchemaError("a once decision produces no grant")
        if self.purpose not in PURPOSES:
            raise TrustSchemaError(f"unknown purpose: {self.purpose!r}")
        if self.source not in DECISION_SOURCES:
            raise TrustSchemaError(f"unknown decision source: {self.source!r}")
        descriptor(self.category)
        if (self.scope == "session") != (self.session_id is not None):
            raise TrustSchemaError("a session grant carries a session id and no other scope does")

    def matches(self, request: PermissionRequest, *, session_id: str) -> bool:
        """Whether this grant answers ``request`` in the session ``session_id``."""
        if self.application_id != request.application_id:
            return False
        if self.category != request.category:
            return False
        if self.scope == "session" and self.session_id != session_id:
            return False
        if not purpose_covers(self.purpose, request.purpose):
            return False
        return self.resource.covers(request.resource)

    def as_record(self) -> Mapping[str, Any]:
        record: dict[str, Any] = {
            "grantId": self.grant_id,
            "applicationId": self.application_id,
            "category": self.category,
            "resource": dict(self.resource.as_record()),
            "resourceIdentifier": self.resource.identifier,
            "purpose": self.purpose,
            "scope": self.scope,
            "verdict": self.verdict,
            "source": self.source,
            "decidedAt": self.decided_at,
        }
        if self.session_id is not None:
            record["sessionId"] = self.session_id
        return record

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "Grant":
        """Rebuild from a stored record, refusing anything that is not one.

        Strict on purpose. A grant read back from a file that has been edited by
        hand, corrupted, or written by a different version is not a grant this
        build understands, and the safe reading of "I do not understand this
        permission record" is that nobody granted anything.
        """
        try:
            resource = Resource(
                kind=str(record["resource"]["kind"]),
                identifier=str(record["resourceIdentifier"]),
                display=str(record["resource"]["display"]),
                digest=str(record["resource"]["digest"]),
            )
            return cls(
                grant_id=str(record["grantId"]),
                application_id=str(record["applicationId"]),
                category=str(record["category"]),
                resource=resource,
                purpose=str(record["purpose"]),
                scope=str(record["scope"]),
                verdict=str(record["verdict"]),
                source=str(record["source"]),
                decided_at=str(record["decidedAt"]),
                session_id=str(record["sessionId"]) if record.get("sessionId") is not None else None,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise TrustSchemaError(f"not a permission grant: {error}") from error


@dataclass(frozen=True)
class Decision:
    """One answer to one request.

    Every decision is audited, including the ones nobody was asked about: a
    catalogue default and a fail-closed denial are both decisions, and a record
    that only held the ones with a prompt behind them would understate what the
    system did on the user's behalf.
    """

    request_id: str
    application_id: str
    category: str
    resource: Resource
    purpose: str
    verdict: str
    scope: str
    source: str
    reason_code: str
    decided_at: str
    session_id: str
    task_id: str | None = None
    grant_id: str | None = None

    def __post_init__(self) -> None:
        if self.verdict not in VERDICTS:
            raise TrustSchemaError(f"unknown verdict: {self.verdict!r}")
        if self.scope not in SCOPES:
            raise TrustSchemaError(f"unknown scope: {self.scope!r}")
        if self.source not in DECISION_SOURCES:
            raise TrustSchemaError(f"unknown decision source: {self.source!r}")
        if self.purpose not in PURPOSES:
            raise TrustSchemaError(f"unknown purpose: {self.purpose!r}")
        if self.reason_code not in DECISION_REASONS:
            raise TrustSchemaError(f"unknown decision reason: {self.reason_code!r}")

    @property
    def allowed(self) -> bool:
        return self.verdict == "allow"

    def as_record(self) -> Mapping[str, Any]:
        return {
            "requestId": self.request_id,
            "applicationId": self.application_id,
            "category": self.category,
            "resource": dict(self.resource.as_record()),
            "purpose": self.purpose,
            "verdict": self.verdict,
            "scope": self.scope,
            "source": self.source,
            "reasonCode": self.reason_code,
            "decidedAt": self.decided_at,
            "sessionId": self.session_id,
            "taskId": self.task_id,
            "grantId": self.grant_id,
        }


@dataclass(frozen=True)
class Resolution:
    """What policy concluded, before anybody was asked.

    ``verdict`` of ``prompt`` is the only outcome that may become an allow at a
    scope the user picked, and ``offered_scopes`` is the closed set the prompt
    may show. A surface that offered a scope outside this tuple would be offering
    a permission the policy never authorised putting on screen.
    """

    verdict: str
    reason_code: str
    offered_scopes: tuple[str, ...] = ()
    grant: Grant | None = None
    #: Set when the resolution is fail-closed because something went wrong rather
    #: than because a rule said no. Surfaces render these differently: "Bunny
    #: could not check this, so it said no" is a different sentence from "you
    #: said no", and conflating them teaches people to distrust the second.
    failure: str | None = None

    def __post_init__(self) -> None:
        if self.verdict not in RESOLUTION_VERDICTS:
            raise TrustSchemaError(f"unknown resolution verdict: {self.verdict!r}")
        if self.verdict != "prompt" and self.offered_scopes:
            raise TrustSchemaError("only a prompt offers scopes")
        for scope in self.offered_scopes:
            if scope not in SCOPES:
                raise TrustSchemaError(f"unknown scope: {scope!r}")

    @property
    def needs_user(self) -> bool:
        return self.verdict == "prompt"
