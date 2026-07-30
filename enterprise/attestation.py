# SPDX-License-Identifier: Apache-2.0
"""Optional device attestation.

Modelled on ``operations/crash.py``, which uses exact-set equality against a
closed allowlist so that a new field cannot be added without a code change and a
review. Attestation is the highest-risk reporting surface in Phase 7 because it
is the one an organisation is most tempted to extend, so the allowlist is
enforced in both directions: an unknown field is a rejection, and a missing
field is a rejection.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

SCHEMA_VERSION = 1

#: The complete set of attestable facts. Every one is a property of the device's
#: software state, not of the person using it.
APPROVED_FIELDS = frozenset({
    "verifiedBootState",
    "secureBootState",
    "osImageDigest",
    "updateChannel",
    "brokerVersion",
    "recoveryAvailable",
    "encryptionState",
    "policyAgentState",
})

#: Fields explicitly named as prohibited. These are rejected by name as well as
#: by the allowlist, so a diff shows the intent rather than only the effect.
PROHIBITED_FIELDS = frozenset({
    "userFiles", "fileNames", "filePaths", "documents",
    "prompts", "promptText", "conversation", "conversations",
    "memory", "memories", "memoryContents",
    "applicationUsage", "usageDuration", "foregroundApp",
    "browserHistory", "terminalHistory", "commandHistory",
    "accountActivity", "userIdentity", "userId", "username", "email",
    "screenshot", "cameraFrame", "microphoneSample", "keystrokes",
    "location", "geolocation",
})

VERIFIED_BOOT_STATES = ("verified", "unverified", "unknown")
SECURE_BOOT_STATES = ("enabled", "enabled-with-limitations", "disabled", "unknown")
UPDATE_CHANNELS = ("developer", "beta", "stable")
ENCRYPTION_STATES = ("encrypted", "not-encrypted", "unknown")
POLICY_AGENT_STATES = ("healthy", "degraded", "stopped", "not-installed")

_SHA256_DIGEST_PREFIX = "sha256:"


class AttestationError(ValueError):
    """Raised when an attestation payload violates the declared boundary."""


@dataclass(frozen=True)
class Attestation:
    verifiedBootState: str
    secureBootState: str
    osImageDigest: str
    updateChannel: str
    brokerVersion: str
    recoveryAvailable: bool
    encryptionState: str
    policyAgentState: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "verifiedBootState": self.verifiedBootState,
            "secureBootState": self.secureBootState,
            "osImageDigest": self.osImageDigest,
            "updateChannel": self.updateChannel,
            "brokerVersion": self.brokerVersion,
            "recoveryAvailable": self.recoveryAvailable,
            "encryptionState": self.encryptionState,
            "policyAgentState": self.policyAgentState,
        }


def _assert_no_prohibited_fields(payload: Mapping[str, Any]) -> None:
    folded = {key.replace("_", "").replace("-", "").casefold(): key for key in payload}
    for prohibited in PROHIBITED_FIELDS:
        candidate = prohibited.replace("_", "").replace("-", "").casefold()
        if candidate in folded:
            raise AttestationError(
                f"prohibited attestation field: {folded[candidate]!r}; "
                "attestation reports device software state only"
            )


def parse_attestation(payload: Mapping[str, Any]) -> Attestation:
    """Validate an attestation payload against the closed allowlist."""
    if not isinstance(payload, Mapping):
        raise AttestationError("attestation payload must be a mapping")

    _assert_no_prohibited_fields(payload)

    if set(payload) != APPROVED_FIELDS:
        missing = sorted(APPROVED_FIELDS - set(payload))
        extra = sorted(set(payload) - APPROVED_FIELDS)
        raise AttestationError(f"attestation fields mismatch; missing={missing}, extra={extra}")

    verified = payload["verifiedBootState"]
    if verified not in VERIFIED_BOOT_STATES:
        raise AttestationError(f"verifiedBootState {verified!r} is not recognised")

    secure_boot = payload["secureBootState"]
    if secure_boot not in SECURE_BOOT_STATES:
        raise AttestationError(f"secureBootState {secure_boot!r} is not recognised")

    digest = payload["osImageDigest"]
    if not isinstance(digest, str) or not digest.startswith(_SHA256_DIGEST_PREFIX):
        raise AttestationError("osImageDigest must be a sha256:<hex> digest")
    hex_part = digest[len(_SHA256_DIGEST_PREFIX):]
    if len(hex_part) != 64 or any(character not in "0123456789abcdef" for character in hex_part):
        raise AttestationError("osImageDigest must contain 64 lowercase hex characters")

    channel = payload["updateChannel"]
    if channel not in UPDATE_CHANNELS:
        raise AttestationError(f"updateChannel {channel!r} is not a recognised channel")

    broker_version = payload["brokerVersion"]
    if not isinstance(broker_version, str) or not broker_version:
        raise AttestationError("brokerVersion must be a non-empty string")

    recovery = payload["recoveryAvailable"]
    if not isinstance(recovery, bool):
        raise AttestationError("recoveryAvailable must be a boolean")

    encryption = payload["encryptionState"]
    if encryption not in ENCRYPTION_STATES:
        raise AttestationError(f"encryptionState {encryption!r} is not recognised")

    agent_state = payload["policyAgentState"]
    if agent_state not in POLICY_AGENT_STATES:
        raise AttestationError(f"policyAgentState {agent_state!r} is not recognised")

    return Attestation(
        verifiedBootState=verified,
        secureBootState=secure_boot,
        osImageDigest=digest,
        updateChannel=channel,
        brokerVersion=broker_version,
        recoveryAvailable=recovery,
        encryptionState=encryption,
        policyAgentState=agent_state,
    )
