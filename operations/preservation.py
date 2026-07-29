"""Compare content-free data-preservation manifests across maintenance actions."""

from __future__ import annotations

import re
from typing import Any, Mapping


DATASETS = (
    "home", "bunnyDatabase", "bunnyMemory", "providerCredentialReferences", "localModels", "plugins",
    "workspaceMetadata", "userApplications", "userSettings", "checkpoints", "documents",
)
SAFE_DIGEST = re.compile(r"sha256:[a-f0-9]{64}\Z")


def validate_manifest(raw: Mapping[str, Any]) -> dict[str, str]:
    if set(raw) != set(DATASETS):
        raise ValueError("preservation manifest must cover every protected dataset")
    for name, digest in raw.items():
        if not isinstance(digest, str) or not SAFE_DIGEST.fullmatch(digest):
            raise ValueError(f"{name} must be represented by a SHA-256 digest, never content")
    return dict(raw)


def compare(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    left = validate_manifest(before)
    right = validate_manifest(after)
    changed = sorted(name for name in DATASETS if left[name] != right[name])
    return {"preserved": not changed, "changedDatasets": changed, "contentIncluded": False}
