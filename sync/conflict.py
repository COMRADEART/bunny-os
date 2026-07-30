# SPDX-License-Identifier: Apache-2.0
"""Deterministic sync conflict resolution.

Version vectors decide *whether* two versions conflict; per-domain rules decide
*what to do* when they do. Both halves are needed: last-write-wins on a clock is
neither deterministic across devices nor safe for deleted data.

The rule that matters most: a deleted memory is never silently resurrected. If one
device deletes a memory and another edits it concurrently, the deletion is
preserved and the edit is surfaced for explicit user review. Sensitive data that
comes back on its own is a privacy failure, not a merge convenience.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

SCHEMA_VERSION = 1

#: Relationship between two version vectors.
RELATIONS = ("identical", "ancestor", "descendant", "concurrent")

#: Resolution strategies. Every domain maps to exactly one.
STRATEGIES = (
    "deletion-wins-with-review",
    "deletion-wins",
    "conflict-copy",
    "merge-fields",
    "highest-completion-wins",
    "manual-review",
)

DOMAIN_STRATEGIES: dict[str, str] = {
    "settings": "merge-fields",
    "preferences": "merge-fields",
    "tasks": "highest-completion-wins",
    "plans": "manual-review",
    "workspaces": "merge-fields",
    "memory": "deletion-wins-with-review",
    "memory-correction": "deletion-wins-with-review",
    "bookmarks": "merge-fields",
    "files": "conflict-copy",
    "conversation-metadata": "merge-fields",
}

#: Domains where a resurrection would expose data the user chose to remove.
SENSITIVE_DOMAINS = frozenset({"memory", "memory-correction", "conversation-metadata"})


class ConflictError(ValueError):
    """Raised when a conflict input is malformed."""


def _validate_vector(vector: Any, name: str) -> dict[str, int]:
    if not isinstance(vector, Mapping) or not vector:
        raise ConflictError(f"{name} must be a non-empty mapping of deviceKeyId to counter")
    parsed: dict[str, int] = {}
    for device, counter in vector.items():
        if not isinstance(device, str) or not device:
            raise ConflictError(f"{name} has a non-string device key")
        if not isinstance(counter, int) or isinstance(counter, bool) or counter < 0:
            raise ConflictError(f"{name}[{device}] must be a non-negative whole number")
        parsed[device] = counter
    return parsed


def compare_vectors(left: Mapping[str, int], right: Mapping[str, int]) -> str:
    """Return the relation of ``left`` to ``right``."""
    first = _validate_vector(left, "left")
    second = _validate_vector(right, "right")
    devices = set(first) | set(second)
    left_greater = any(first.get(device, 0) > second.get(device, 0) for device in devices)
    right_greater = any(second.get(device, 0) > first.get(device, 0) for device in devices)
    if left_greater and right_greater:
        return "concurrent"
    if left_greater:
        return "descendant"
    if right_greater:
        return "ancestor"
    return "identical"


def merge_vectors(left: Mapping[str, int], right: Mapping[str, int]) -> dict[str, int]:
    """Return the element-wise maximum of two version vectors."""
    first = _validate_vector(left, "left")
    second = _validate_vector(right, "right")
    return {device: max(first.get(device, 0), second.get(device, 0)) for device in set(first) | set(second)}


@dataclass(frozen=True)
class Resolution:
    domain: str
    relation: str
    strategy: str
    outcome: str
    requiresUserReview: bool
    conflictCopyCreated: bool
    tombstonePreserved: bool
    explanation: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "relation": self.relation,
            "strategy": self.strategy,
            "outcome": self.outcome,
            "requiresUserReview": self.requiresUserReview,
            "conflictCopyCreated": self.conflictCopyCreated,
            "tombstonePreserved": self.tombstonePreserved,
            "explanation": self.explanation,
        }


def resolve(candidate: Mapping[str, Any], stored: Mapping[str, Any]) -> Resolution:
    """Resolve one incoming change against the stored state.

    Each side is ``{"domain", "vector", "deleted": bool, "objectId"}``. Domains
    must match; comparing across domains is a programming error.
    """
    for name, side in (("candidate", candidate), ("stored", stored)):
        if not isinstance(side, Mapping):
            raise ConflictError(f"{name} must be a mapping")
        unexpected = sorted(set(side) - {"domain", "vector", "deleted", "objectId", "completed"})
        if unexpected:
            raise ConflictError(f"{name} has unknown fields: " + ", ".join(unexpected))

    domain = candidate.get("domain")
    if domain != stored.get("domain"):
        raise ConflictError("cannot resolve a conflict across different domains")
    strategy = DOMAIN_STRATEGIES.get(domain)
    if strategy is None:
        raise ConflictError(f"no resolution strategy is defined for domain {domain!r}")

    relation = compare_vectors(candidate.get("vector", {}), stored.get("vector", {}))
    candidate_deleted = bool(candidate.get("deleted", False))
    stored_deleted = bool(stored.get("deleted", False))

    if relation == "identical":
        return Resolution(
            domain=domain,
            relation=relation,
            strategy=strategy,
            outcome="no-change",
            requiresUserReview=False,
            conflictCopyCreated=False,
            tombstonePreserved=stored_deleted,
            explanation="Both devices already agree on this version.",
        )

    if relation == "ancestor":
        return Resolution(
            domain=domain,
            relation=relation,
            strategy=strategy,
            outcome="keep-stored",
            requiresUserReview=False,
            conflictCopyCreated=False,
            tombstonePreserved=stored_deleted,
            explanation="The incoming change is older than what this device already has; it is discarded.",
        )

    if relation == "descendant":
        if stored_deleted and not candidate_deleted and domain in SENSITIVE_DOMAINS:
            return Resolution(
                domain=domain,
                relation=relation,
                strategy=strategy,
                outcome="keep-deletion-and-queue-review",
                requiresUserReview=True,
                conflictCopyCreated=False,
                tombstonePreserved=True,
                explanation=(
                    "This item was deleted on another device. The newer edit does not restore it "
                    "automatically; it is queued for you to review and restore deliberately."
                ),
            )
        return Resolution(
            domain=domain,
            relation=relation,
            strategy=strategy,
            outcome="apply-candidate",
            requiresUserReview=False,
            conflictCopyCreated=False,
            tombstonePreserved=candidate_deleted,
            explanation="The incoming change supersedes the stored version.",
        )

    if candidate_deleted or stored_deleted:
        if domain in SENSITIVE_DOMAINS:
            return Resolution(
                domain=domain,
                relation=relation,
                strategy="deletion-wins-with-review",
                outcome="keep-deletion-and-queue-review",
                requiresUserReview=True,
                conflictCopyCreated=False,
                tombstonePreserved=True,
                explanation=(
                    "One device deleted this item while another changed it. The deletion is kept and "
                    "the change is queued for review, so deleted sensitive data is never resurrected "
                    "without your decision."
                ),
            )
        return Resolution(
            domain=domain,
            relation=relation,
            strategy="deletion-wins",
            outcome="keep-deletion",
            requiresUserReview=False,
            conflictCopyCreated=False,
            tombstonePreserved=True,
            explanation="One device deleted this item; the deletion propagates.",
        )

    if strategy == "conflict-copy":
        return Resolution(
            domain=domain,
            relation=relation,
            strategy=strategy,
            outcome="create-conflict-copy",
            requiresUserReview=True,
            conflictCopyCreated=True,
            tombstonePreserved=False,
            explanation=(
                "Both devices changed this file while offline. Both versions are kept and the "
                "incoming one is saved as a conflict copy; nothing is overwritten."
            ),
        )

    if strategy == "merge-fields":
        return Resolution(
            domain=domain,
            relation=relation,
            strategy=strategy,
            outcome="merge-per-field",
            requiresUserReview=False,
            conflictCopyCreated=False,
            tombstonePreserved=False,
            explanation=(
                "Both devices changed different fields. Fields are merged individually; "
                "a field changed on both sides is resolved in favour of the higher version vector."
            ),
        )

    if strategy == "highest-completion-wins":
        candidate_completed = bool(candidate.get("completed", False))
        stored_completed = bool(stored.get("completed", False))
        completed = candidate_completed or stored_completed
        return Resolution(
            domain=domain,
            relation=relation,
            strategy=strategy,
            outcome="mark-completed" if completed else "merge-per-field",
            requiresUserReview=False,
            conflictCopyCreated=False,
            tombstonePreserved=False,
            explanation=(
                "A task completed on either device is treated as completed, so concurrent edits "
                "never un-complete work."
            ),
        )

    return Resolution(
        domain=domain,
        relation=relation,
        strategy="manual-review",
        outcome="queue-manual-review",
        requiresUserReview=True,
        conflictCopyCreated=False,
        tombstonePreserved=False,
        explanation="Concurrent changes cannot be merged safely; both versions are kept for you to review.",
    )


def describe_strategies() -> list[dict[str, str]]:
    """Return the per-domain conflict rules for documentation."""
    return [
        {"domain": domain, "strategy": strategy, "sensitive": str(domain in SENSITIVE_DOMAINS).lower()}
        for domain, strategy in sorted(DOMAIN_STRATEGIES.items())
    ]
