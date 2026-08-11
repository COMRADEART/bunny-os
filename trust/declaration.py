# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What an application said it would need, before it needed it.

Deny-by-default has a weak reading and a strong one. The weak reading is "ask
before allowing". The strong one, and the one implemented here, is *an
application cannot ask for a capability it never declared*. A photo editor whose
declaration lists files and the GPU cannot produce a microphone prompt at all —
not a prompt a careful user would decline, but no prompt, because the request is
refused before any surface sees it. That closes the whole class of attack where a
prompt is timed, worded or repeated until somebody clicks the wrong button.

A declaration comes from the curated catalogue entry (:mod:`catalog.entries`) and
is a plain value here so that :mod:`trust` does not depend on :mod:`catalog`. The
trust layer must be able to answer a question about an application whose
catalogue entry has been removed, and the answer in that case is denial for
anything not already granted — which requires the declaration to be *absent*, a
state this type can represent, rather than the import failing.

Three fields, and the distinction between the first two is the one that matters:

``required``
    the application does not work without it. May be covered by one install-time
    consent, but only for low and medium risk categories — see
    :attr:`~trust.categories.CategoryDescriptor.catalog_grantable`, which is
    derived from risk so that no catalogue entry can promote itself.
``optional``
    a feature uses it. Never pre-granted. Asked for at the moment of use, with
    the resource in front of the person.
``reasons``
    per category, what the catalogue says it is for. This is the *only* source of
    a permission reason that is neither the application speaking for itself nor
    the user's own request; see :class:`trust.request.Reason`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .categories import CATEGORIES, descriptor
from .errors import TrustSchemaError
from .request import MAX_REASON_LENGTH, Reason
from .resources import NETWORK_CLASSES

__all__ = ["PermissionDeclaration", "UNDECLARED"]


@dataclass(frozen=True)
class PermissionDeclaration:
    """The permissions one application declared, and what for."""

    application_id: str
    required: frozenset[str] = frozenset()
    optional: frozenset[str] = frozenset()
    reasons: Mapping[str, str] = field(default_factory=dict)
    #: The widest network class the catalogue entry declares. A request for a
    #: wider one is refused even when ``network`` is declared, so that an entry
    #: saying "reaches api.example.com" cannot become "reaches the internet"
    #: without the catalogue changing.
    network_ceiling: str = "none"
    #: The domains an ``allowlisted`` ceiling names. Part of the ceiling rather
    #: than a separate policy: "may reach two named hosts" is a materially
    #: different declaration from "may reach any host somebody adds later", and
    #: an entry that left the set open would be an internet declaration wearing a
    #: narrower word.
    network_domains: frozenset[str] = frozenset()
    #: Whether the curated entry is present at all. ``False`` is the state for an
    #: application Bunny knows is installed and has no metadata for; everything
    #: not already granted is refused, and the refusal says so.
    known: bool = True

    def __post_init__(self) -> None:
        overlap = self.required & self.optional
        if overlap:
            raise TrustSchemaError(f"declared both required and optional: {sorted(overlap)}")
        for category in sorted(self.required | self.optional):
            descriptor(category)
        for category, text in self.reasons.items():
            if category not in CATEGORIES:
                raise TrustSchemaError(f"reason for unknown category: {category!r}")
            if category not in self.required and category not in self.optional:
                raise TrustSchemaError(f"reason for undeclared category: {category!r}")
            if not isinstance(text, str) or not text.strip():
                raise TrustSchemaError(f"empty reason for {category}")
            if len(text) > MAX_REASON_LENGTH:
                raise TrustSchemaError(f"reason for {category} exceeds {MAX_REASON_LENGTH} characters")
        if self.network_ceiling not in NETWORK_CLASSES:
            raise TrustSchemaError(f"unknown network class: {self.network_ceiling!r}")
        if self.network_ceiling != "none" and "network" not in (self.required | self.optional):
            raise TrustSchemaError("a network ceiling without a declared network permission")
        if self.network_domains and self.network_ceiling != "allowlisted":
            raise TrustSchemaError("only an allowlisted ceiling names domains")
        if self.network_ceiling == "allowlisted" and not self.network_domains:
            raise TrustSchemaError("an allowlisted ceiling needs at least one domain")

    def ceiling_identifier(self) -> str:
        """The ceiling in the same encoding a network resource uses.

        One encoding for both sides of the comparison, so the subset test in
        :func:`trust.resources.network_covers` is the *only* place that knows how
        an allowlist is written down.
        """
        if self.network_ceiling != "allowlisted":
            return self.network_ceiling
        return "allowlisted:" + ",".join(sorted(self.network_domains))

    def declares(self, category: str) -> bool:
        return category in self.required or category in self.optional

    def reason_for(self, category: str) -> Reason:
        """The catalogue's stated reason, or an honest absence.

        Never a guess. A category the catalogue declared without saying why
        produces :meth:`Reason.unknown`, and the prompt then tells the person
        nobody said why — which is information they can act on.
        """
        text = self.reasons.get(category)
        if not text:
            return Reason.unknown()
        return Reason(source="catalog", text=text)

    def install_consent_set(self) -> tuple[str, ...]:
        """The required categories one install-time consent may cover.

        High and critical risk categories are excluded here rather than at the
        prompt, so that a surface cannot present them as part of an install
        bundle even by mistake.
        """
        return tuple(
            sorted(
                category
                for category in self.required
                if CATEGORIES[category].catalog_grantable
            )
        )

    def as_record(self) -> Mapping[str, Any]:
        return {
            "applicationId": self.application_id,
            "known": self.known,
            "required": sorted(self.required),
            "optional": sorted(self.optional),
            "reasons": dict(sorted(self.reasons.items())),
            "networkCeiling": self.network_ceiling,
            "networkDomains": sorted(self.network_domains),
        }


def UNDECLARED(application_id: str) -> PermissionDeclaration:  # noqa: N802 - reads as a constructor
    """The declaration for an application the catalogue does not describe.

    Named in capitals because it is used as a value, not as a factory: every call
    site is saying *there is no declaration*, and the loud name keeps that from
    reading as an ordinary empty one.
    """
    return PermissionDeclaration(application_id=application_id, known=False)
