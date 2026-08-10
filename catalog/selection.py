# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Turning "I need Photoshop" into a list of honest choices.

§14 is the section this module implements, and its hardest requirement is
negative: *do not falsely claim open-source software is identical to commercial
software.* Every mechanism here exists to make that claim impossible to produce
rather than merely discouraged.

**Nothing in a choice is written at runtime.** The name, the cost, the licence,
the account requirement and the ``differences`` paragraph all come from the
curated entry. The Companion reads them out. It cannot compare two applications
it has never run and it is given no field in which to try.

**The commercial option is shown, not hidden.** A person who asks for Photoshop
is told Photoshop exists, what it costs and what it requires, and is *also*
shown what runs locally in a capsule. Omitting the commercial option would be a
different dishonesty from overselling the free one, and it is the one an
open-source project falls into by default.

**A cost is stated before anything is installed, and nothing is ever bought.**
:attr:`ApplicationChoice.commitment` names what installing commits the person to
— an account, a subscription, a trial that becomes one. §14's last line is
absolute: the Companion never purchases software and never accepts terms. There
is no code path here that could; the choice list ends at *this is what it would
require*.

**Already-installed options come first when they fit.** Not because they are
better, but because the alternative is a system that proposes installing
something to do a job the machine can already do, which is how a disk fills up.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .entry import CatalogEntry, HardwareRequirements
from .errors import CatalogSchemaError
from .registry import CatalogRegistry

__all__ = [
    "COMMITMENTS",
    "ApplicationChoice",
    "ChoiceSet",
    "MachineFacts",
    "choices_for",
]

#: What installing an option commits the person to, in the words shown. Closed,
#: so a surface can render each one and a test can assert every entry maps to
#: exactly one.
COMMITMENTS: Mapping[str, str] = {
    "none": "Free. No account.",
    "account": "Free, but you need to make an account.",
    "paid": "You have to buy it.",
    "subscription": "You have to subscribe, and keep subscribing.",
    "freemium": "Free to start; some things need a paid plan.",
}


@dataclass(frozen=True)
class MachineFacts:
    """What this machine has, for the fit check.

    Injectable so a test can describe a small machine. Absent facts are
    ``None`` and produce no claim: a choice list that said "this needs more
    memory than you have" without having read the memory would be inventing.
    """

    memory_bytes: int | None = None
    free_disk_bytes: int | None = None
    has_gpu: bool | None = None
    architecture: str = "x86_64"
    online: bool = True
    installed_application_ids: frozenset[str] = frozenset()


@dataclass(frozen=True)
class ApplicationChoice:
    """One option in front of a person, with everything they need to pick."""

    entry: CatalogEntry
    kind: str
    #: ``capsule``, ``browser`` or ``not-available``. See
    #: :attr:`catalog.entry.CatalogEntry.delivery`.
    delivery: str
    installed: bool
    installable: bool
    commitment: str
    commitment_note: str
    #: Why this option cannot be offered, when it cannot. Empty when it can.
    blocked_reason: str = ""
    #: Facts about fit, each of which is only present because a fact was known.
    fit_notes: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        return self.entry.name

    def as_record(self) -> Mapping[str, Any]:
        return {
            "entryId": self.entry.entry_id,
            "applicationId": self.entry.application_id,
            "name": self.entry.name,
            "publisher": self.entry.publisher,
            "purpose": self.entry.purpose,
            "kind": self.kind,
            "delivery": self.delivery,
            "installed": self.installed,
            "installable": self.installable,
            "cost": self.entry.cost,
            "commitment": self.commitment,
            "commitmentNote": self.commitment_note,
            "license": self.entry.license_id,
            "trustStatus": self.entry.trust_status,
            "differences": self.entry.differences,
            "sandboxCompatible": self.entry.sandbox_compatible,
            "sandboxNote": self.entry.sandbox_note,
            "highRiskPermissions": list(self.entry.high_risk_permissions),
            "blockedReason": self.blocked_reason,
            "fitNotes": list(self.fit_notes),
        }


@dataclass(frozen=True)
class ChoiceSet:
    """Everything Bunny can offer for one capability, and what it cannot."""

    capability: str
    choices: tuple[ApplicationChoice, ...]
    #: Set when the catalogue has nothing at all. A surface renders this rather
    #: than an empty list, because "Bunny has nothing for that" is a sentence and
    #: an empty list is a blank space.
    nothing_found: bool = False

    @property
    def offerable(self) -> tuple[ApplicationChoice, ...]:
        return tuple(choice for choice in self.choices if not choice.blocked_reason)

    def as_record(self) -> Mapping[str, Any]:
        return {
            "capability": self.capability,
            "nothingFound": self.nothing_found,
            "choices": [dict(choice.as_record()) for choice in self.choices],
        }


def _commitment(entry: CatalogEntry) -> str:
    if entry.cost == "paid":
        return "paid"
    if entry.cost == "subscription":
        return "subscription"
    if entry.cost == "freemium":
        return "freemium"
    return "account" if entry.requires_account else "none"


def _fit_notes(entry: CatalogEntry, machine: MachineFacts) -> tuple[str, ...]:
    """Statements about fit, each conditional on a fact actually being known."""
    notes: list[str] = []
    hardware: HardwareRequirements = entry.hardware
    if machine.architecture not in hardware.architectures:
        notes.append(f"Not built for this computer's {machine.architecture} processor.")
    if hardware.memory_bytes is not None and machine.memory_bytes is not None:
        if machine.memory_bytes < hardware.memory_bytes:
            notes.append(
                f"Wants about {hardware.memory_bytes // (1024**3)} GB of memory; this computer has "
                f"{machine.memory_bytes // (1024**3)} GB."
            )
    if hardware.disk_bytes is not None and machine.free_disk_bytes is not None:
        if machine.free_disk_bytes < hardware.disk_bytes:
            notes.append(f"Needs about {hardware.disk_bytes // (1024**3)} GB of free space.")
    if hardware.needs_gpu and machine.has_gpu is False:
        notes.append("Needs a graphics card this computer does not have.")
    if entry.delivery == "browser" and not machine.online:
        notes.append("This one only works online, and this computer is offline.")
    return tuple(notes)


def _blocked(entry: CatalogEntry, machine: MachineFacts, fit: Sequence[str]) -> str:
    """Why this option cannot be taken up right now, in one sentence, or empty.

    A web option is *not* blocked: it is usable, in a browser, and
    :attr:`ApplicationChoice.delivery` is what tells the surface to say so. What
    is blocked is an application that cannot run here at all, one whose
    provenance Bunny has not checked, and one whose architecture is wrong.
    """
    if machine.architecture not in entry.hardware.architectures:
        return "It is not built for this computer."
    if entry.delivery == "not-available":
        return entry.sandbox_note or "There is no version of this for Bunny OS."
    if entry.trust_status == "unverified":
        return "Bunny has not checked where this comes from, so it will not install it for you."
    if entry.delivery == "browser" and not machine.online:
        return "This one needs the internet."
    return ""


def choices_for(
    capability: str,
    registry: CatalogRegistry,
    *,
    machine: MachineFacts | None = None,
) -> ChoiceSet:
    """The options for one capability, ordered as a person should meet them.

    Installed first, then the order the catalogue's own sort produces, which is
    installable-before-not and then §14's option order. Nothing is scored and
    nothing is recommended: the person chooses, and the list gives them what they
    need to.
    """
    facts = machine or MachineFacts()
    entries = registry.providing(capability)
    if not entries:
        return ChoiceSet(capability=capability, choices=(), nothing_found=True)

    built: list[ApplicationChoice] = []
    for entry in entries:
        installed = entry.application_id in facts.installed_application_ids
        fit = _fit_notes(entry, facts)
        blocked = _blocked(entry, facts, fit)
        commitment = _commitment(entry)
        built.append(
            ApplicationChoice(
                entry=entry,
                kind=entry.option_kind,
                delivery=entry.delivery,
                installed=installed,
                installable=entry.installable and not blocked,
                commitment=commitment,
                commitment_note=COMMITMENTS[commitment],
                blocked_reason=blocked,
                fit_notes=fit,
            )
        )
    built.sort(key=lambda choice: (not choice.installed, bool(choice.blocked_reason)))
    return ChoiceSet(capability=capability, choices=tuple(built))
