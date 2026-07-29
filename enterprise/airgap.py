"""Air-gapped and partially disconnected fleet management.

The design rule is that being offline never lowers the trust requirement. There
is no "trusted local" bundle, no unsigned import path, and no way to mark a
bundle as exempt because it arrived on removable media.

Two replay problems are handled explicitly, because they are the realistic
attacks on a sneakernet workflow:

* *stale policy replay* — a bundle carries a monotonic sequence per organisation,
  and applying a bundle whose sequence is not greater than the last applied one is
  refused, mirroring the update agent's highest-sequence rule;
* *bundle expiry* — a bundle carries ``expiresAt`` so an old export cannot be
  applied indefinitely after it was produced.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
from typing import Any, Mapping

SCHEMA_VERSION = 1

BUNDLE_KINDS = (
    "policy-bundle",
    "update-export",
    "application-mirror",
    "enrolment-proxy-configuration",
    "offline-recovery-package",
    "status-report",
)

#: Air-gap workflow stages, in order.
WORKFLOW_STAGES = (
    "exported",
    "transported",
    "verified",
    "applied",
    "status-exported",
    "status-imported",
)

MAXIMUM_BUNDLE_LIFETIME = timedelta(days=90)
MAXIMUM_BUNDLE_BYTES = 8 * 1024 * 1024 * 1024

_BUNDLE_ID = re.compile(r"^bnd-[0-9a-f]{16}$")
_ORGANISATION_ID = re.compile(r"^org-[a-z0-9][a-z0-9-]{1,62}$")
_RFC3339 = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_KEY_ID = re.compile(r"^fleet-[a-z0-9-]{2,48}$")


class AirGapError(ValueError):
    """Raised when an offline bundle is unsigned, stale, expired, or malformed."""


def _parse_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not _RFC3339.match(value):
        raise AirGapError(f"{field} must be an RFC 3339 timestamp")
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


@dataclass(frozen=True)
class OfflineBundle:
    bundleId: str
    kind: str
    organisationId: str
    sequence: int
    createdAt: str
    expiresAt: str
    contentDigest: str
    signatureKeyId: str
    sizeBytes: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "bundleId": self.bundleId,
            "kind": self.kind,
            "organisationId": self.organisationId,
            "sequence": self.sequence,
            "createdAt": self.createdAt,
            "expiresAt": self.expiresAt,
            "contentDigest": self.contentDigest,
            "signatureKeyId": self.signatureKeyId,
            "sizeBytes": self.sizeBytes,
        }


def parse_bundle(
    record: Mapping[str, Any],
    *,
    now: datetime | None = None,
    last_applied_sequence: int = 0,
    revoked_key_ids: frozenset[str] = frozenset(),
) -> OfflineBundle:
    """Validate an offline bundle manifest.

    ``signatureVerified`` must be ``True``. There is no flag, environment
    variable, or bundle kind that makes signature verification optional.
    """
    if not isinstance(record, Mapping):
        raise AirGapError("bundle manifest must be a mapping")

    allowed = {
        "schemaVersion", "bundleId", "kind", "organisationId", "sequence", "createdAt",
        "expiresAt", "contentDigest", "signatureKeyId", "signatureVerified", "sizeBytes",
    }
    unexpected = sorted(set(record) - allowed)
    if unexpected:
        raise AirGapError("unknown bundle fields: " + ", ".join(unexpected))
    missing = sorted(allowed - set(record))
    if missing:
        raise AirGapError("missing bundle fields: " + ", ".join(missing))

    if record["schemaVersion"] != SCHEMA_VERSION:
        raise AirGapError("unsupported bundle schemaVersion")

    if record["signatureVerified"] is not True:
        raise AirGapError(
            "offline bundle signature is not verified; there is no unsigned or 'trusted local' import path"
        )

    bundle_id = record["bundleId"]
    if not isinstance(bundle_id, str) or not _BUNDLE_ID.match(bundle_id):
        raise AirGapError("bundleId must match bnd-<16 hex>")

    kind = record["kind"]
    if kind not in BUNDLE_KINDS:
        raise AirGapError(f"kind {kind!r} is not a recognised bundle kind")

    organisation_id = record["organisationId"]
    if not isinstance(organisation_id, str) or not _ORGANISATION_ID.match(organisation_id):
        raise AirGapError("organisationId must match org-<slug>")

    key_id = record["signatureKeyId"]
    if not isinstance(key_id, str) or not _KEY_ID.match(key_id):
        raise AirGapError(
            "signatureKeyId must be in the reserved 'fleet-' namespace; fleet-control signing keys "
            "are separate from OS update keys and from OEM keys"
        )
    if key_id in revoked_key_ids:
        raise AirGapError(f"signatureKeyId {key_id!r} is revoked")

    digest = record["contentDigest"]
    if not isinstance(digest, str) or not _SHA256.match(digest):
        raise AirGapError("contentDigest must be 64 lowercase hex characters")

    size = record["sizeBytes"]
    if not isinstance(size, int) or isinstance(size, bool) or not 0 < size <= MAXIMUM_BUNDLE_BYTES:
        raise AirGapError(f"sizeBytes must be between 1 and {MAXIMUM_BUNDLE_BYTES}")

    sequence = record["sequence"]
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
        raise AirGapError("sequence must be a positive whole number")
    if sequence <= last_applied_sequence:
        raise AirGapError(
            f"bundle sequence {sequence} is not greater than the last applied sequence "
            f"{last_applied_sequence}; stale policy replay refused"
        )

    created_at = _parse_timestamp(record["createdAt"], "createdAt")
    expires_at = _parse_timestamp(record["expiresAt"], "expiresAt")
    if expires_at <= created_at:
        raise AirGapError("expiresAt must be after createdAt")
    if expires_at - created_at > MAXIMUM_BUNDLE_LIFETIME:
        raise AirGapError(f"bundle lifetime exceeds the {MAXIMUM_BUNDLE_LIFETIME.days}-day maximum")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if current >= expires_at:
        raise AirGapError("offline bundle has expired")

    return OfflineBundle(
        bundleId=bundle_id,
        kind=kind,
        organisationId=organisation_id,
        sequence=sequence,
        createdAt=record["createdAt"],
        expiresAt=record["expiresAt"],
        contentDigest=digest,
        signatureKeyId=key_id,
        sizeBytes=size,
    )


def next_stage(current: str, requested: str) -> str:
    """Validate an air-gap workflow transition."""
    if current not in WORKFLOW_STAGES or requested not in WORKFLOW_STAGES:
        raise AirGapError("both stages must be recognised workflow stages")
    source = WORKFLOW_STAGES.index(current)
    target = WORKFLOW_STAGES.index(requested)
    if target != source + 1:
        raise AirGapError(
            f"air-gap workflow must proceed in order; {current!r} may only advance to "
            f"{WORKFLOW_STAGES[source + 1]!r}"
        )
    return requested


def describe_workflow() -> list[dict[str, str]]:
    """Return the documented air-gapped management workflow."""
    return [
        {"stage": "exported", "action": "The console exports a signed policy bundle for one organisation."},
        {"stage": "transported", "action": "The bundle is carried on approved removable media."},
        {"stage": "verified", "action": "The device or local proxy verifies the signature, key namespace, digest, sequence, and expiry."},
        {"stage": "applied", "action": "Policy is applied through typed operations only."},
        {"stage": "status-exported", "action": "The device exports a signed status report containing operational state only."},
        {"stage": "status-imported", "action": "The console verifies and imports the status report."},
    ]
