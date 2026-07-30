"""Privacy-preserving device identity.

The hard constraint comes from ``docs/PRIVACY.md``, which prohibits "persistent
tracking IDs", and from ``operations/redaction.py``, whose ``IDENTIFIER_KEYS``
already redacts ``deviceid`` and ``serial`` from any export. A device identity
therefore has to be:

* locally generated, so no party issues an identifier the device did not create;
* rotatable, so a long-lived identifier is not forced;
* unlinkable from hardware, so it cannot be correlated with a unit sold or a
  network interface observed.

Hardware identifiers remain usable for *local* diagnostics, which existing
hardware probes already redact on export. They are never the remote identity.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable, Mapping

SCHEMA_VERSION = 1

#: The four identity concepts Phase 7 keeps distinct. Collapsing any two of them
#: is the failure mode this vocabulary exists to prevent.
IDENTITY_KINDS = ("device-identity", "boot-attestation", "compliance-status", "user-identity")

#: Sources that may never be used as, or derived into, a remote identity.
FORBIDDEN_IDENTITY_SOURCES = frozenset({
    "mac-address",
    "macaddress",
    "wifi-mac",
    "ethernet-mac",
    "bluetooth-address",
    "motherboard-serial",
    "board-serial",
    "chassis-serial",
    "product-serial",
    "system-serial",
    "storage-serial",
    "disk-serial",
    "nvme-serial",
    "cpu-serial",
    "processor-serial",
    "imei",
    "advertising-id",
    "advertising-identifier",
    "idfa",
    "gaid",
})

#: Where a device private key may live. Software keys are permitted because TPM
#: presence is optional across the hardware matrix, but the storage choice is
#: always recorded rather than implied.
KEY_STORAGE = ("tpm-2.0", "software-protected")

#: Reasons a rotation may be recorded. A closed vocabulary keeps rotation history
#: auditable without free-text that could carry user content.
ROTATION_REASONS = (
    "scheduled",
    "operator-requested",
    "suspected-compromise",
    "storage-migration",
    "reinstall",
    "unenrolment",
    "decommission",
)

_INSTALLATION_ID = re.compile(r"^[0-9a-f]{32}$")
_KEY_ID = re.compile(r"^dev-[0-9a-f]{16}$")
_RFC3339 = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")

MINIMUM_INSTALLATION_ID_BITS = 128


class IdentityError(ValueError):
    """Raised when a device identity record violates a Phase 7 invariant."""


@dataclass(frozen=True)
class DeviceIdentity:
    installationId: str
    deviceKeyId: str
    keyStorage: str
    locallyGenerated: bool
    createdAt: str
    certificateSerial: str | None
    enrolmentIdentity: str | None
    rotationHistory: tuple[dict[str, Any], ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "installationId": self.installationId,
            "deviceKeyId": self.deviceKeyId,
            "keyStorage": self.keyStorage,
            "locallyGenerated": self.locallyGenerated,
            "createdAt": self.createdAt,
            "certificateSerial": self.certificateSerial,
            "enrolmentIdentity": self.enrolmentIdentity,
            "rotationHistory": [dict(item) for item in self.rotationHistory],
        }


def _reject_hardware_derivation(record: Mapping[str, Any]) -> None:
    """Refuse any record that names a hardware identifier as an identity source."""
    declared = record.get("derivedFrom")
    if declared is None:
        return
    if isinstance(declared, str):
        declared = [declared]
    if not isinstance(declared, list):
        raise IdentityError("derivedFrom must be a list of source names")
    offending = sorted(
        str(item) for item in declared
        if str(item).replace("_", "-").casefold() in FORBIDDEN_IDENTITY_SOURCES
    )
    if offending:
        raise IdentityError(
            "device identity may not be derived from hardware identifiers: " + ", ".join(offending)
        )


def parse_device_identity(record: Mapping[str, Any]) -> DeviceIdentity:
    """Validate and parse a device identity record.

    Raises ``IdentityError`` rather than returning a partial identity, so a
    caller cannot accidentally proceed with an identity that failed a rule.
    """
    if not isinstance(record, Mapping):
        raise IdentityError("device identity record must be a mapping")

    allowed = {
        "schemaVersion", "installationId", "deviceKeyId", "keyStorage", "locallyGenerated",
        "createdAt", "certificateSerial", "enrolmentIdentity", "rotationHistory", "derivedFrom",
    }
    unexpected = sorted(set(record) - allowed)
    if unexpected:
        raise IdentityError("unknown device identity fields: " + ", ".join(unexpected))

    if record.get("schemaVersion") != SCHEMA_VERSION:
        raise IdentityError(f"unsupported schemaVersion {record.get('schemaVersion')!r}")

    installation_id = record.get("installationId")
    if not isinstance(installation_id, str) or not _INSTALLATION_ID.match(installation_id):
        raise IdentityError("installationId must be 32 lowercase hex characters of locally generated randomness")

    key_id = record.get("deviceKeyId")
    if not isinstance(key_id, str) or not _KEY_ID.match(key_id):
        raise IdentityError("deviceKeyId must match dev-<16 hex>")

    storage = record.get("keyStorage")
    if storage not in KEY_STORAGE:
        raise IdentityError(f"keyStorage must be one of {', '.join(KEY_STORAGE)}")

    if record.get("locallyGenerated") is not True:
        raise IdentityError(
            "locallyGenerated must be true; a device identity is never issued by a server "
            "or derived from a factory-assigned identifier"
        )

    created_at = record.get("createdAt")
    if not isinstance(created_at, str) or not _RFC3339.match(created_at):
        raise IdentityError("createdAt must be an RFC 3339 timestamp")

    certificate_serial = record.get("certificateSerial")
    if certificate_serial is not None and (not isinstance(certificate_serial, str) or not certificate_serial):
        raise IdentityError("certificateSerial must be a non-empty string when present")

    enrolment_identity = record.get("enrolmentIdentity")
    if enrolment_identity is not None and (not isinstance(enrolment_identity, str) or not enrolment_identity):
        raise IdentityError("enrolmentIdentity must be a non-empty string when present")

    _reject_hardware_derivation(record)

    history = record.get("rotationHistory", [])
    if not isinstance(history, list):
        raise IdentityError("rotationHistory must be a list")
    parsed_history: list[dict[str, Any]] = []
    previous_at = ""
    for index, entry in enumerate(history):
        if not isinstance(entry, Mapping):
            raise IdentityError(f"rotationHistory[{index}] is not an object")
        entry_allowed = {"rotatedAt", "reason", "previousKeyId"}
        if set(entry) - entry_allowed:
            raise IdentityError(f"rotationHistory[{index}] has unknown fields")
        rotated_at = entry.get("rotatedAt")
        if not isinstance(rotated_at, str) or not _RFC3339.match(rotated_at):
            raise IdentityError(f"rotationHistory[{index}].rotatedAt must be RFC 3339")
        if rotated_at < previous_at:
            raise IdentityError(f"rotationHistory[{index}] is out of chronological order")
        previous_at = rotated_at
        reason = entry.get("reason")
        if reason not in ROTATION_REASONS:
            raise IdentityError(f"rotationHistory[{index}].reason {reason!r} is not a recognised reason")
        previous_key = entry.get("previousKeyId")
        if not isinstance(previous_key, str) or not _KEY_ID.match(previous_key):
            raise IdentityError(f"rotationHistory[{index}].previousKeyId must match dev-<16 hex>")
        parsed_history.append(dict(entry))

    return DeviceIdentity(
        installationId=installation_id,
        deviceKeyId=key_id,
        keyStorage=storage,
        locallyGenerated=True,
        createdAt=created_at,
        certificateSerial=certificate_serial,
        enrolmentIdentity=enrolment_identity,
        rotationHistory=tuple(parsed_history),
    )


def assert_distinct_identity_kinds(payload: Mapping[str, Any]) -> None:
    """Refuse a payload that mixes two identity concepts into one field.

    A fleet record may carry a device identity *and* a compliance status, but it
    must not present a user identity inside the device identity block, which is
    how an operational record silently becomes a person-tracking record.
    """
    device_block = payload.get("device-identity")
    if isinstance(device_block, Mapping):
        leaked = sorted(
            key for key in device_block
            if key.replace("_", "").replace("-", "").casefold()
            in {"userid", "username", "email", "upn", "principal", "employeeid", "subject"}
        )
        if leaked:
            raise IdentityError(
                "device-identity must not contain user identity fields: " + ", ".join(leaked)
            )
    unknown = sorted(set(payload) - set(IDENTITY_KINDS))
    if unknown:
        raise IdentityError("unknown identity kinds: " + ", ".join(unknown))


def local_diagnostic_fields(fields: Iterable[str]) -> list[str]:
    """Return the subset of hardware fields permitted for *local* diagnostics.

    Hardware identifiers stay allowed locally because ``docs/DIAGNOSTICS.md``
    already scopes diagnostics to a local, mode-0600 export. Anything in this
    list is still redacted by ``operations/redaction.py`` on export.
    """
    return sorted(
        field for field in fields
        if field.replace("_", "-").casefold() in FORBIDDEN_IDENTITY_SOURCES
    )
