"""Sync metadata disclosure.

The honest position: end-to-end encryption protects *content*, not the fact that
content exists. A service that routes and versions objects necessarily observes
some operational metadata, and this module states exactly what.

``describe_visible_metadata`` is the source of truth for ``docs/ENCRYPTED_SYNC.md``
and for the privacy review. ``assert_no_zero_knowledge_claim`` exists because the
temptation to market this as "zero knowledge" is real and the claim would be false
while the metadata below remains visible.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

#: Metadata the service can observe, with why it is unavoidable.
VISIBLE_METADATA = (
    {
        "field": "accountIdentifier",
        "visible": "yes",
        "why": "Required to authenticate the account and route its objects.",
    },
    {
        "field": "deviceKeyId",
        "visible": "yes",
        "why": "Required to register devices, wrap keys per device, and honour revocation.",
    },
    {
        "field": "collectionIdentifier",
        "visible": "yes",
        "why": "Required to group objects and coordinate per-collection versions.",
    },
    {
        "field": "objectIdentifier",
        "visible": "yes",
        "why": "Required to address an object for upload, download, and deletion.",
    },
    {
        "field": "objectVersion",
        "visible": "yes",
        "why": "Required to detect conflicts and prevent version rollback.",
    },
    {
        "field": "encryptedObjectSize",
        "visible": "yes",
        "why": "Inherent to storing a blob. Padding reduces but does not remove size correlation.",
    },
    {
        "field": "uploadTimestamp",
        "visible": "yes",
        "why": "Inherent to accepting a write; used for quota and abuse limits.",
    },
    {
        "field": "versionCount",
        "visible": "yes",
        "why": "Inherent to versioned storage; reveals roughly how often an object changes.",
    },
    {
        "field": "objectContent",
        "visible": "no",
        "why": "Encrypted on the device before upload under a key the service never holds.",
    },
    {
        "field": "objectTitleOrFilename",
        "visible": "no",
        "why": "Descriptive fields are refused by the envelope validator.",
    },
    {
        "field": "bunnyPromptsAndMemories",
        "visible": "no",
        "why": "Encrypted content; also excluded from every fleet and diagnostic surface.",
    },
    {
        "field": "collectionKind",
        "visible": "no",
        "why": "Collection identifiers are opaque; the service is not told which collection is memory.",
    },
)

#: What an observer can infer from the visible set, stated plainly.
INFERABLE_FROM_METADATA = (
    "That an account exists and how many devices it has.",
    "Roughly how much data an account stores and how often it changes.",
    "When a device was active, at the granularity of upload timestamps.",
    "That two devices belong to the same account.",
)

_PROHIBITED_CLAIMS = re.compile(
    r"(?i)\b(zero[\s-]?knowledge|we know nothing|no metadata|metadata[\s-]?free|"
    r"completely anonymous|fully anonymous|untraceable)\b"
)


class MetadataClaimError(ValueError):
    """Raised when documentation or UI text overstates the privacy guarantee."""


def describe_visible_metadata() -> list[dict[str, str]]:
    """Return the metadata disclosure table."""
    return [dict(item) for item in VISIBLE_METADATA]


def visible_fields() -> list[str]:
    """Return only the field names the service can observe."""
    return [item["field"] for item in VISIBLE_METADATA if item["visible"] == "yes"]


def assert_no_zero_knowledge_claim(text: str) -> None:
    """Refuse text that claims more privacy than the design provides."""
    if not isinstance(text, str):
        raise MetadataClaimError("text must be a string")
    match = _PROHIBITED_CLAIMS.search(text)
    if match:
        raise MetadataClaimError(
            f"the phrase {match.group(0)!r} overstates the guarantee: operational metadata "
            f"({', '.join(visible_fields())}) remains visible to the sync operator. "
            "Describe the design as end-to-end encrypted content with disclosed metadata instead."
        )


def minimisation_report(observed_fields: Iterable[str]) -> dict[str, Any]:
    """Compare what a service actually stores against the declared minimum."""
    declared = set(visible_fields())
    observed = set(observed_fields)
    excess = sorted(observed - declared)
    return {
        "declaredVisibleFields": sorted(declared),
        "observedFields": sorted(observed),
        "excessFields": excess,
        "minimised": not excess,
        "note": (
            "An excess field means the service stores more than the documented minimum and either the "
            "service or the documentation must change."
        ),
    }
