# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Turning a capability into a sentence, without inventing anything.

This is the module the Companion speaks through, and it is deliberately not
where the Companion gets to be clever. §10 divides the work three ways: the
policy engine decides *what capability is being requested*, this module states it
in ordinary language, and the person decides. The Companion narrates; it does not
author. So there is no free text here that is generated at runtime — every
sentence is a template from :mod:`trust.categories` filled with two values whose
provenance is known, plus a reason that either came from somewhere citable or is
reported as absent.

**Absence is stated, not filled in.** The single most important behaviour is what
happens when nobody said why the application wants a permission:
:attr:`TrustPrompt.reason` is ``None`` and :attr:`TrustPrompt.reason_note` reads
*It didn't say why.* That sentence is more useful to a person than a plausible
invention, and it is the only honest thing available.

**A reason is attributed to whoever said it.** A catalogue reason is prefixed
*Bunny's catalogue says*; an application's own reason is prefixed *The app says*
and quoted, because an application's claim about itself is evidence of what it
claims, not of what is true. A task reason is the user's own request echoed back.

**An unenforced permission says so.** Where
:attr:`~trust.categories.CategoryDescriptor.enforced_by_default` is ``False``,
the prompt carries an enforcement note in plain words. Presenting a permission
prompt for something the sandbox does not actually restrict, without saying so,
would be the most damaging kind of security theatre: it teaches a person that
denying works.

**Nothing here escapes to markup.** The values are returned as data;
:func:`escape` exists for the two surfaces that render Pango markup, and it is
applied by them rather than here, so a caller that renders to a terminal or to a
screen reader is not handed entity references to read out loud.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .categories import CategoryDescriptor, descriptor
from .decision import Decision, Resolution
from .declaration import PermissionDeclaration
from .request import PermissionRequest, Reason
from .resources import Resource

__all__ = [
    "DENY_LABEL",
    "SCOPE_LABELS",
    "TrustPrompt",
    "build_prompt",
    "decision_sentence",
    "escape",
    "headline",
    "revoke_sentence",
]

#: What each scope is called in front of a person. "Allow while using" rather
#: than "session", because "session" is a word about the machine.
SCOPE_LABELS: Mapping[str, str] = {
    "once": "Allow once",
    "session": "Allow while using",
    "always": "Always allow",
}

DENY_LABEL = "Don't allow"

#: How a reason is attributed, by source. ``unknown`` has no prefix because it
#: has no text; see :attr:`TrustPrompt.reason_note`.
_ATTRIBUTION: Mapping[str, str] = {
    "catalog": "Bunny's catalogue says",
    "application": "The app says",
    "task": "You asked Bunny to",
}

#: Said when nobody supplied a reason. Short, and does not editorialise: it is a
#: fact about the request, not a hint that the request is suspicious.
UNKNOWN_REASON_NOTE = "It didn't say why."

_ENFORCEMENT_NOTE = (
    "Bunny can record this decision but cannot yet stop {app} doing it. "
    "The restriction is not enforced in this build."
)

#: Where the generic capability note is not specific enough because the *purpose*
#: changes what is at stake. A read of a file and a write to it are one category
#: and two different consents, and §15's "the original is preserved unless
#: modification was explicitly requested" is only meaningful if the person could
#: tell which one they were agreeing to.
_PURPOSE_NOTES: Mapping[tuple[str, str], str] = {
    ("files", "read"): "Read that one file. Your copy is not changed.",
    ("files", "write"): "Change that file. What is there now is replaced.",
    ("folders", "read"): "Read anything in that folder, now and later.",
    ("folders", "write"): "Read, add, change and delete anything in that folder, now and later.",
}

_MARKUP = {"&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"}


def escape(text: str) -> str:
    """Escape for Pango/HTML. Applied by surfaces that need it, never here."""
    return "".join(_MARKUP.get(character, character) for character in text)


def headline(application_name: str, category: str, resource: Resource) -> str:
    """The one sentence at the top of a prompt.

    The template comes from the category table and is filled with exactly two
    values. A category whose ``resource_kind`` is ``none`` has no ``{resource}``
    field, and passing one is a programming error rather than a formatting one —
    which is why the check is on the descriptor rather than on whether the
    resource happens to be empty.
    """
    entry = descriptor(category)
    if entry.resource_kind == "none":
        return entry.sentence.format(app=application_name)
    return entry.sentence.format(app=application_name, resource=resource.display)


@dataclass(frozen=True)
class TrustPrompt:
    """Everything a surface needs to ask one question, and nothing else.

    A surface renders this and returns a :class:`~trust.gate.UserAnswer`. It is
    given no store, no policy and no way to reach either: a compromised surface
    can lie about what a person answered — which the gate's ticket binding
    limits — but it cannot grant anything by itself, and it cannot read the
    permissions of applications it was not asked about.
    """

    request_id: str
    application_id: str
    application_name: str
    category: str
    category_title: str
    risk: str
    purpose: str
    headline: str
    capability_note: str
    resource_display: str
    reason: str | None
    reason_note: str | None
    enforcement_note: str | None
    revocation: str
    options: tuple[tuple[str, str], ...]
    deny_option: tuple[str, str] = ("deny", DENY_LABEL)
    #: A short, screen-reader-first rendering of the whole question. Built here
    #: rather than by each surface so the spoken form and the drawn form cannot
    #: drift apart, and so a text-only companion has a complete sentence to say.
    spoken: str = ""

    def as_record(self) -> Mapping[str, Any]:
        return {
            "requestId": self.request_id,
            "applicationId": self.application_id,
            "applicationName": self.application_name,
            "category": self.category,
            "categoryTitle": self.category_title,
            "risk": self.risk,
            "purpose": self.purpose,
            "headline": self.headline,
            "capabilityNote": self.capability_note,
            "resource": self.resource_display,
            "reason": self.reason,
            "reasonNote": self.reason_note,
            "enforcementNote": self.enforcement_note,
            "revocation": self.revocation,
            "options": [{"scope": scope, "label": label} for scope, label in self.options],
            "denyOption": {"verdict": "deny", "label": self.deny_option[1]},
            "spoken": self.spoken,
        }


def _attributed(reason: Reason) -> tuple[str | None, str | None]:
    """The reason text as it should appear, and the note when there is none."""
    if reason.source == "unknown" or not reason.text:
        return None, UNKNOWN_REASON_NOTE
    prefix = _ATTRIBUTION[reason.source]
    if reason.source == "application":
        return f'{prefix}: "{reason.text}"', None
    return f"{prefix}: {reason.text}", None


def build_prompt(
    request: PermissionRequest,
    resolution: Resolution,
    declaration: PermissionDeclaration,
    *,
    application_name: str | None = None,
) -> TrustPrompt:
    """Assemble the prompt for a resolution that concluded ``prompt``.

    The reason is taken from the request when the request carries one, and
    otherwise from the catalogue declaration. Both are citable. Neither is
    generated. If the request carries an ``unknown`` reason and the catalogue is
    silent for this category, the prompt says so.
    """
    entry: CategoryDescriptor = descriptor(request.category)
    name = application_name or request.application_id
    reason = request.reason
    if reason.source == "unknown":
        reason = declaration.reason_for(request.category)
    reason_text, reason_note = _attributed(reason)
    line = headline(name, request.category, request.resource)
    capability_note = _PURPOSE_NOTES.get((request.category, request.purpose), entry.capability_note)
    options = tuple((scope, SCOPE_LABELS[scope]) for scope in resolution.offered_scopes)
    enforcement_note = None if entry.enforced_by_default else _ENFORCEMENT_NOTE.format(app=name)
    spoken_parts = [line, capability_note]
    if reason_text:
        spoken_parts.append(reason_text)
    else:
        spoken_parts.append(UNKNOWN_REASON_NOTE)
    if enforcement_note:
        spoken_parts.append(enforcement_note)
    spoken_parts.append(
        "Your choices are: " + ", ".join(label for _, label in options) + f", or {DENY_LABEL}."
    )
    return TrustPrompt(
        request_id=request.request_id,
        application_id=request.application_id,
        application_name=name,
        category=request.category,
        category_title=entry.title,
        risk=entry.risk,
        purpose=request.purpose,
        headline=line,
        capability_note=capability_note,
        resource_display=request.resource.display,
        reason=reason_text,
        reason_note=reason_note,
        enforcement_note=enforcement_note,
        revocation=entry.revocation,
        options=options,
        spoken=" ".join(spoken_parts),
    )


#: What each decision reason means to a person. Every code in
#: :data:`trust.decision.DECISION_REASONS` appears; a test asserts the two stay
#: in step, because a decision nothing can explain is a decision that reaches a
#: user as a blank refusal.
_DECISION_SENTENCES: Mapping[str, str] = {
    "malformed-request": "Bunny couldn't understand what {app} asked for, so it said no.",
    "store-unreadable": "Bunny couldn't read your permission settings, so it said no.",
    "store-unwritable": "Bunny couldn't save that decision, so it said no.",
    "not-declared": "{app} asked for something it never said it would need, so Bunny said no.",
    "unknown-application": "Bunny has no record of {app}, so it said no.",
    "beyond-ceiling": "{app} asked for more than its listing allows, so Bunny said no.",
    "user-denied": "You didn't allow this.",
    "user-allowed": "You allowed this.",
    "granted-previously": "You allowed this earlier.",
    "catalog-default": "This was covered by what you agreed to when {app} was installed.",
    "needs-user": "Bunny is waiting for you to decide.",
    "surface-failed": "The permission window didn't work, so Bunny said no.",
    "unanswered": "Nobody answered, so Bunny said no.",
    "replayed": "That answer had already been used, so Bunny said no.",
    "answer-mismatch": "That answer didn't match the question, so Bunny said no.",
    "expired": "The question timed out, so Bunny said no.",
    "scope-not-offered": "That wasn't one of the choices, so Bunny said no.",
}


def decision_sentence(decision: Decision, *, application_name: str | None = None) -> str:
    """One sentence explaining a settled decision, for the activity view."""
    name = application_name or decision.application_id
    template = _DECISION_SENTENCES.get(decision.reason_code)
    if template is None:  # pragma: no cover - guarded by a test over DECISION_REASONS
        return f"Bunny said no to {name}."
    return template.format(app=name)


def revoke_sentence(category: str, *, application_name: str) -> str:
    """What happens, and when, if this permission is withdrawn now.

    The two revocation speeds produce two different sentences because they are
    two different facts. Telling somebody a camera permission is gone when it is
    only gone at the next launch would be the comfortable lie.
    """
    entry = descriptor(category)
    if entry.revocation == "immediate":
        return f"{application_name} loses this straight away."
    return f"{application_name} keeps this until you close it, and won't have it next time."
