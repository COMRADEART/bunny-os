# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Capability Registry: the validated catalogue of declared services.

Individual manifests are validated in :mod:`capability.manifest`. This module
validates the things only the *set* can be wrong about — a dependency naming a
service nobody ships, a cycle, an essential service that depends on an optional
one — and computes the one number the budget engine needs from it: the summed
minimum of everything essential.

Those cross-manifest checks are not pedantry. An essential service depending on
an optional one is a control plane that can be switched off by a resource
decision, which is how a machine ends up unable to report why it is unable to
do anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from .budget import ALL_CATEGORIES, ESSENTIAL_CATEGORY
from .manifest import ManifestError, ServiceManifest, load_manifests

__all__ = ["DEFAULT_SERVICE_DIRECTORY", "Registry", "build_registry"]

#: Manifests shipped with Bunny OS, read from the source tree.
DEFAULT_SERVICE_DIRECTORY = Path(__file__).resolve().parent / "services"

#: Where manifests will live on an installed system. **Nothing installs them
#: there yet** — this package is not part of the image build. Adding files to
#: the image would change the built artifact and invalidate the current
#: reproducibility candidate, which is not a side effect this change is entitled
#: to have. The lookup is written now so that wiring the image later needs no
#: code change here; until then it simply never matches and the source tree is
#: used. Recorded in ``KNOWN_LIMITATIONS.md``.
_INSTALLED_SERVICE_DIRECTORY = Path("/usr/share/bunny-os/capability/services")


@dataclass(frozen=True)
class Registry:
    services: Mapping[str, ServiceManifest]

    def __iter__(self):
        return iter(self.ordered())

    def __len__(self) -> int:
        return len(self.services)

    def get(self, identifier: str) -> ServiceManifest | None:
        return self.services.get(identifier)

    def ordered(self) -> tuple[ServiceManifest, ...]:
        """Essential first, then by descending priority, then by id.

        This is start order and it is also the order resources are handed out
        in, so it must be total and stable. Ties broken by id rather than by
        directory listing order, because the latter differs between filesystems
        and would make a plan depend on which machine produced it.
        """
        return tuple(sorted(
            self.services.values(),
            key=lambda item: (not item.essential, -item.priority, item.id),
        ))

    def start_order(self) -> tuple[ServiceManifest, ...]:
        """:meth:`ordered`, rearranged so dependencies precede dependents.

        The engine evaluates in this order so that "is my dependency running"
        is answerable when the question is asked, rather than requiring a second
        pass. Cycles are impossible here because :func:`build_registry` refuses
        them, so the walk terminates.
        """
        emitted: list[ServiceManifest] = []
        placed: set[str] = set()

        def emit(service: ServiceManifest) -> None:
            if service.id in placed:
                return
            placed.add(service.id)
            for dependency in sorted(service.requires):
                target = self.services.get(dependency)
                if target is not None:
                    emit(target)
            emitted.append(service)

        for service in self.ordered():
            emit(service)
        return tuple(emitted)

    def essential(self) -> tuple[ServiceManifest, ...]:
        return tuple(item for item in self.ordered() if item.essential)

    def minimum_bytes(self, service: ServiceManifest) -> int:
        """The least memory this service can be started with, locally.

        Built from the *cheapest* local implementation rather than the richest:
        a service with a lean fallback does not oblige the machine to fund its
        best form in order to exist.
        """
        candidates = [
            item.requirements.minimum_memory_bytes
            for item in service.ordered_implementations()
            if item.locality == "local" and item.requirements.minimum_memory_bytes is not None
        ]
        if candidates:
            return min(candidates)
        return service.requirements.minimum_memory_bytes or 0

    def essential_floor_bytes(self) -> int:
        """Summed minimum memory of every essential service.

        Minimum rather than recommended: this is the figure that decides whether
        the machine can run Bunny OS at all, and it should describe the smallest
        honest configuration, not a comfortable one.
        """
        return sum(self.minimum_bytes(service) for service in self.essential())

    def dependents_of(self, identifier: str) -> tuple[str, ...]:
        return tuple(sorted(
            service.id for service in self.services.values() if identifier in service.requires
        ))


def _check_dependencies(services: Mapping[str, ServiceManifest]) -> list[str]:
    problems: list[str] = []
    for service in services.values():
        for dependency in service.requires:
            if dependency not in services:
                problems.append(f"{service.id} requires {dependency}, which no manifest declares")
            elif service.essential and not services[dependency].essential:
                problems.append(
                    f"{service.id} is essential but requires the optional service {dependency}; "
                    "an essential service must not be able to lose its dependency to a resource decision"
                )
        for conflict in service.conflicts_with:
            if conflict in services and service.id not in services[conflict].conflicts_with:
                problems.append(
                    f"{service.id} declares a conflict with {conflict} that {conflict} does not declare back; "
                    "conflicts must be symmetric or the engine's decision depends on evaluation order"
                )
        if service.budget_category not in ALL_CATEGORIES:
            problems.append(
                f"{service.id} declares budgetCategory {service.budget_category!r}, "
                f"which is not one of {sorted(ALL_CATEGORIES)}"
            )
        elif service.essential != (service.budget_category == ESSENTIAL_CATEGORY):
            # The two say the same thing, so they must agree. A service that is
            # essential but draws from a discretionary pool could be outbid by an
            # optional one, and an optional service in the essential category
            # would take memory off the top it has no claim to.
            problems.append(
                f"{service.id} is {'essential' if service.essential else 'optional'} but declares "
                f"budgetCategory {service.budget_category!r}; essential services must use "
                f"{ESSENTIAL_CATEGORY!r} and optional services must not"
            )
    return problems


def _check_cycles(services: Mapping[str, ServiceManifest]) -> list[str]:
    """Depth-first cycle detection over the requires graph."""
    problems: list[str] = []
    visiting: set[str] = set()
    done: set[str] = set()

    def walk(identifier: str, trail: tuple[str, ...]) -> None:
        if identifier in done:
            return
        if identifier in visiting:
            cycle = " -> ".join([*trail[trail.index(identifier):], identifier])
            problems.append(f"dependency cycle: {cycle}")
            return
        visiting.add(identifier)
        service = services.get(identifier)
        for dependency in (service.requires if service else ()):
            if dependency in services:
                walk(dependency, (*trail, identifier))
        visiting.discard(identifier)
        done.add(identifier)

    for identifier in sorted(services):
        walk(identifier, ())
    return problems


def build_registry(manifests: Iterable[ServiceManifest]) -> Registry:
    """Validate a set of manifests into a registry, or refuse the set."""
    services: dict[str, ServiceManifest] = {}
    duplicates: list[str] = []
    for manifest in manifests:
        if manifest.id in services:
            duplicates.append(manifest.id)
        services[manifest.id] = manifest

    problems = [f"duplicate service id {identifier}" for identifier in sorted(set(duplicates))]
    problems.extend(_check_dependencies(services))
    problems.extend(_check_cycles(services))
    if problems:
        raise ManifestError("the service registry is not consistent:\n  - " + "\n  - ".join(problems))
    return Registry(services)


def load_registry(directory: Path | None = None) -> Registry:
    """Load the shipped registry, preferring an installed copy over the tree."""
    if directory is not None:
        return build_registry(load_manifests(directory))
    source = _INSTALLED_SERVICE_DIRECTORY if _INSTALLED_SERVICE_DIRECTORY.is_dir() else DEFAULT_SERVICE_DIRECTORY
    return build_registry(load_manifests(source))
