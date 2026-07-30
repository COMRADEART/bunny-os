# SPDX-License-Identifier: Apache-2.0
"""Sync account recovery.

Recovery is the hardest trade-off in the design. Any mechanism that lets a user
recover without holding a secret also lets the operator — or an attacker who
compromises the operator — recover. Bunny OS therefore refuses server-side
recovery of private content: a recovery path must present the recovery secret, or
be authorised by an already-trusted device.

Organisation recovery exists but is bounded: it can recover *organisation-owned
data* on an *organisation-owned device*. It cannot recover a personal account's
private collections, and the boundary is enforced here rather than promised.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping

SCHEMA_VERSION = 1

RECOVERY_METHODS = (
    "recovery-phrase",
    "recovery-file",
    "trusted-existing-device",
    "organisation-recovery-policy",
)

#: Methods that prove possession of the user's recovery secret or an existing key.
USER_HELD_METHODS = frozenset({"recovery-phrase", "recovery-file", "trusted-existing-device"})

#: Collections an organisation recovery policy may ever reach.
ORGANISATION_RECOVERABLE_COLLECTIONS = frozenset({
    "organisation-configuration",
    "organisation-documents",
    "organisation-backup",
})

#: Recovery phrase parameters. 24 words from a 2048-word list is ~264 bits of
#: entropy before checksum; the specification is stated so an implementation
#: cannot quietly weaken it.
RECOVERY_PHRASE_WORDS = 24
RECOVERY_PHRASE_WORDLIST_SIZE = 2048
MINIMUM_RECOVERY_ENTROPY_BITS = 128

_PHRASE = re.compile(r"^(?:[a-z]{3,8})(?: [a-z]{3,8}){23}$")
_RECOVERY_FILE_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_DEVICE_KEY_ID = re.compile(r"^dev-[0-9a-f]{16}$")


class RecoveryError(ValueError):
    """Raised when a recovery attempt is unauthorised or malformed."""


@dataclass(frozen=True)
class RecoveryDecision:
    method: str
    permitted: bool
    recoverableCollections: tuple[str, ...]
    refusals: tuple[str, ...]
    warnings: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "permitted": self.permitted,
            "recoverableCollections": list(self.recoverableCollections),
            "refusals": list(self.refusals),
            "warnings": list(self.warnings),
        }


def evaluate_recovery(request: Mapping[str, Any]) -> RecoveryDecision:
    """Decide whether a recovery attempt may proceed and over what scope."""
    if not isinstance(request, Mapping):
        raise RecoveryError("request must be a mapping")

    allowed = {
        "schemaVersion", "method", "requestedCollections", "recoveryPhrasePresented",
        "recoveryFileDigest", "trustedDeviceKeyId", "organisationOwnedDevice",
        "organisationPolicyReference", "serverAssisted",
    }
    unexpected = sorted(set(request) - allowed)
    if unexpected:
        raise RecoveryError("unknown recovery fields: " + ", ".join(unexpected))
    if request.get("schemaVersion") != SCHEMA_VERSION:
        raise RecoveryError("unsupported recovery schemaVersion")

    method = request.get("method")
    if method not in RECOVERY_METHODS:
        raise RecoveryError(f"recovery method {method!r} is not recognised")

    requested = request.get("requestedCollections", [])
    if not isinstance(requested, list) or not requested:
        raise RecoveryError("requestedCollections must be a non-empty list")
    if any(not isinstance(item, str) or not item for item in requested):
        raise RecoveryError("requestedCollections entries must be non-empty strings")

    refusals: list[str] = []
    warnings: list[str] = []

    if request.get("serverAssisted") is True and method not in USER_HELD_METHODS:
        refusals.append(
            "server-assisted recovery of private content is refused; the sync service cannot decrypt "
            "user collections and will not recover them without the recovery secret"
        )

    if method == "recovery-phrase":
        phrase = request.get("recoveryPhrasePresented")
        if not isinstance(phrase, str) or not _PHRASE.match(phrase.strip().lower()):
            refusals.append(f"a valid {RECOVERY_PHRASE_WORDS}-word recovery phrase was not presented")
    elif method == "recovery-file":
        digest = request.get("recoveryFileDigest")
        if not isinstance(digest, str) or not _RECOVERY_FILE_DIGEST.match(digest):
            refusals.append("a valid recovery file digest was not presented")
    elif method == "trusted-existing-device":
        device = request.get("trustedDeviceKeyId")
        if not isinstance(device, str) or not _DEVICE_KEY_ID.match(device):
            refusals.append("a trusted existing device key id was not presented")

    recoverable: tuple[str, ...]
    if method == "organisation-recovery-policy":
        if request.get("organisationOwnedDevice") is not True:
            refusals.append(
                "organisation recovery applies only to organisation-owned devices; "
                "a personally owned device's private collections are never organisation-recoverable"
            )
        if not request.get("organisationPolicyReference"):
            refusals.append("organisation recovery requires a reference to the disclosed recovery policy")
        out_of_scope = sorted(set(requested) - ORGANISATION_RECOVERABLE_COLLECTIONS)
        if out_of_scope:
            refusals.append(
                "organisation recovery cannot reach these collections: " + ", ".join(out_of_scope)
            )
        recoverable = tuple(sorted(set(requested) & ORGANISATION_RECOVERABLE_COLLECTIONS))
        warnings.append(
            "Organisation recovery is limited to organisation-owned data and is recorded in the audit log."
        )
    else:
        recoverable = tuple(sorted(set(requested)))

    return RecoveryDecision(
        method=method,
        permitted=not refusals,
        recoverableCollections=() if refusals else recoverable,
        refusals=tuple(refusals),
        warnings=tuple(warnings),
    )


def key_loss_warning() -> dict[str, Any]:
    """Return the mandatory warning shown when sync encryption is first enabled."""
    return {
        "headline": "If you lose every key and your recovery secret, your synced data cannot be recovered.",
        "detail": [
            "Your data is encrypted on your devices with keys the sync service never receives.",
            "That means nobody at the service, and nobody at Bunny OS, can decrypt it for you.",
            "Keep your recovery phrase or recovery file somewhere separate from your devices.",
            "Losing all paired devices and the recovery secret makes the data permanently unreadable.",
        ],
        "acknowledgementRequired": True,
        "recoveryOptions": list(RECOVERY_METHODS),
    }


def describe_methods() -> list[dict[str, Any]]:
    """Return the recovery method catalogue for documentation."""
    return [
        {
            "method": "recovery-phrase",
            "proves": f"possession of a {RECOVERY_PHRASE_WORDS}-word phrase",
            "scope": "all collections the account holds",
            "serverCanPerformAlone": False,
        },
        {
            "method": "recovery-file",
            "proves": "possession of an exported key file",
            "scope": "all collections the account holds",
            "serverCanPerformAlone": False,
        },
        {
            "method": "trusted-existing-device",
            "proves": "an already-paired device authorises the new one",
            "scope": "collections that device can read",
            "serverCanPerformAlone": False,
        },
        {
            "method": "organisation-recovery-policy",
            "proves": "a disclosed organisation policy on an organisation-owned device",
            "scope": "organisation-owned collections only",
            "serverCanPerformAlone": False,
        },
    ]
