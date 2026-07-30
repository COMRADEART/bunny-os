"""Authenticated device pairing.

The attack this module is built around is *server-side key substitution*: a
compromised sync service offers its own public key as the new device's key, and
thereafter receives every collection key wrapped for it. No amount of transport
security prevents that, because the service terminates the transport.

The defence is a short authenticator both sides compute from the actual key
material and a session binding, which the user compares out of band. If the
service substitutes a key, the fingerprints differ and pairing is refused.

Also prevented here: replay of a pairing session, silent device addition without a
confirmed fingerprint, method downgrade below the initiating device's method, and
reuse of a one-time code.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import re
from typing import Any, Mapping, MutableSet

SCHEMA_VERSION = 1

#: Pairing methods, strongest first. A session may not downgrade to a weaker
#: method than the one the initiating device offered.
PAIRING_METHODS = (
    "existing-trusted-device",
    "passkey-backed-account",
    "verified-qr-exchange",
    "recovery-secret",
    "one-time-code",
)

_METHOD_STRENGTH = {method: len(PAIRING_METHODS) - index for index, method in enumerate(PAIRING_METHODS)}

PAIRING_STATES = ("offered", "authenticator-displayed", "confirmed", "completed", "refused", "expired")

SESSION_LIFETIME = timedelta(minutes=10)
AUTHENTICATOR_GROUPS = 4
AUTHENTICATOR_GROUP_SIZE = 4

_DEVICE_KEY_ID = re.compile(r"^dev-[0-9a-f]{16}$")
_SESSION_ID = re.compile(r"^pair-[0-9a-f]{32}$")
_BASE64 = re.compile(r"^[A-Za-z0-9+/]+={0,2}$")
_RFC3339 = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")


class PairingError(ValueError):
    """Raised when a pairing session is invalid, replayed, or unauthenticated."""


def compute_fingerprint(public_key: bytes, *, session_id: str) -> str:
    """Return the human-comparable pairing authenticator.

    Binding the session id prevents a fingerprint captured from one pairing from
    being replayed into another. The output is grouped for reliable reading aloud.
    """
    if not isinstance(public_key, (bytes, bytearray)) or len(public_key) < 32:
        raise PairingError("public key material must be at least 32 bytes")
    if not _SESSION_ID.match(session_id):
        raise PairingError("sessionId must match pair-<32 hex>")

    digest = hashlib.sha256(b"bunny-os/sync/v1/pairing|" + session_id.encode("ascii") + b"|" + bytes(public_key)).hexdigest()
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    value = int(digest, 16)
    characters: list[str] = []
    for _ in range(AUTHENTICATOR_GROUPS * AUTHENTICATOR_GROUP_SIZE):
        characters.append(alphabet[value % len(alphabet)])
        value //= len(alphabet)
    return "-".join(
        "".join(characters[index:index + AUTHENTICATOR_GROUP_SIZE])
        for index in range(0, len(characters), AUTHENTICATOR_GROUP_SIZE)
    )


def fingerprints_match(left: str, right: str) -> bool:
    """Compare two authenticators in constant time."""
    return hmac.compare_digest(left.strip().upper(), right.strip().upper())


@dataclass(frozen=True)
class PairingSession:
    sessionId: str
    method: str
    newDeviceKeyId: str
    newDeviceName: str
    initiatingDeviceKeyId: str
    createdAt: str
    expiresAt: str
    authenticator: str
    state: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "sessionId": self.sessionId,
            "method": self.method,
            "newDeviceKeyId": self.newDeviceKeyId,
            "newDeviceName": self.newDeviceName,
            "initiatingDeviceKeyId": self.initiatingDeviceKeyId,
            "createdAt": self.createdAt,
            "expiresAt": self.expiresAt,
            "authenticator": self.authenticator,
            "state": self.state,
        }

    def display(self) -> dict[str, str]:
        """Return exactly what the user must be shown before confirming."""
        return {
            "newDeviceName": self.newDeviceName,
            "keyFingerprint": self.authenticator,
            "instruction": (
                "Compare this code with the one shown on the other device. "
                "If they differ, refuse the pairing: the codes only match when both devices hold "
                "the same key, and a mismatch means the key was substituted in transit."
            ),
        }


def _parse_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not _RFC3339.match(value):
        raise PairingError(f"{field} must be an RFC 3339 timestamp")
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def parse_session(
    record: Mapping[str, Any],
    *,
    public_key: bytes,
    now: datetime | None = None,
    consumed_session_ids: MutableSet[str] | None = None,
    initiating_method: str | None = None,
) -> PairingSession:
    """Validate a pairing session and recompute its authenticator locally.

    The authenticator is *never* taken from the record. It is recomputed from the
    key material the device actually received, which is what makes substitution
    detectable.
    """
    if not isinstance(record, Mapping):
        raise PairingError("pairing session must be a mapping")

    allowed = {
        "schemaVersion", "sessionId", "method", "newDeviceKeyId", "newDeviceName",
        "initiatingDeviceKeyId", "createdAt", "expiresAt", "state", "newDevicePublicKey",
    }
    unexpected = sorted(set(record) - allowed)
    if unexpected:
        raise PairingError("unknown pairing fields: " + ", ".join(unexpected))
    missing = sorted(allowed - {"newDevicePublicKey"} - set(record))
    if missing:
        raise PairingError("missing pairing fields: " + ", ".join(missing))

    if record["schemaVersion"] != SCHEMA_VERSION:
        raise PairingError("unsupported pairing schemaVersion")

    session_id = record["sessionId"]
    if not isinstance(session_id, str) or not _SESSION_ID.match(session_id):
        raise PairingError("sessionId must match pair-<32 hex>")

    if consumed_session_ids is not None and session_id in consumed_session_ids:
        raise PairingError("pairing session replay refused: this session id was already used")

    method = record["method"]
    if method not in PAIRING_METHODS:
        raise PairingError(f"pairing method {method!r} is not recognised")
    if initiating_method is not None:
        if initiating_method not in PAIRING_METHODS:
            raise PairingError(f"initiating method {initiating_method!r} is not recognised")
        if _METHOD_STRENGTH[method] < _METHOD_STRENGTH[initiating_method]:
            raise PairingError(
                f"pairing downgrade refused: session offers {method} but the initiating device "
                f"required {initiating_method}"
            )

    new_key_id = record["newDeviceKeyId"]
    if not isinstance(new_key_id, str) or not _DEVICE_KEY_ID.match(new_key_id):
        raise PairingError("newDeviceKeyId must match dev-<16 hex>")

    initiating_key_id = record["initiatingDeviceKeyId"]
    if not isinstance(initiating_key_id, str) or not _DEVICE_KEY_ID.match(initiating_key_id):
        raise PairingError("initiatingDeviceKeyId must match dev-<16 hex>")
    if initiating_key_id == new_key_id:
        raise PairingError("a device cannot pair itself")

    name = record["newDeviceName"]
    if not isinstance(name, str) or not name or len(name) > 64:
        raise PairingError("newDeviceName must be a short non-empty string")

    state = record["state"]
    if state not in PAIRING_STATES:
        raise PairingError(f"pairing state {state!r} is not recognised")

    declared_key = record.get("newDevicePublicKey")
    if declared_key is not None:
        if not isinstance(declared_key, str) or not _BASE64.match(declared_key):
            raise PairingError("newDevicePublicKey must be base64 when present")

    created_at = _parse_timestamp(record["createdAt"], "createdAt")
    expires_at = _parse_timestamp(record["expiresAt"], "expiresAt")
    if expires_at <= created_at:
        raise PairingError("expiresAt must be after createdAt")
    if expires_at - created_at > SESSION_LIFETIME:
        raise PairingError(f"pairing session lifetime exceeds {SESSION_LIFETIME}")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if current >= expires_at:
        raise PairingError("pairing session has expired")

    authenticator = compute_fingerprint(public_key, session_id=session_id)

    return PairingSession(
        sessionId=session_id,
        method=method,
        newDeviceKeyId=new_key_id,
        newDeviceName=name,
        initiatingDeviceKeyId=initiating_key_id,
        createdAt=record["createdAt"],
        expiresAt=record["expiresAt"],
        authenticator=authenticator,
        state=state,
    )


def confirm_pairing(
    session: PairingSession,
    *,
    userConfirmedAuthenticator: str,
    consumed_session_ids: MutableSet[str] | None = None,
) -> dict[str, Any]:
    """Complete pairing only when the user-confirmed authenticator matches.

    A mismatch is reported as a substitution warning rather than a typo, because
    treating it as user error is how this class of attack succeeds.
    """
    if not isinstance(userConfirmedAuthenticator, str) or not userConfirmedAuthenticator.strip():
        raise PairingError("the user must confirm the displayed authenticator")

    if not fingerprints_match(session.authenticator, userConfirmedAuthenticator):
        raise PairingError(
            "pairing refused: the confirmed code does not match the code derived from the key this "
            "device received. The sync service may have substituted the device key. Do not retry "
            "without verifying the other device out of band."
        )

    if consumed_session_ids is not None:
        consumed_session_ids.add(session.sessionId)

    return {
        "sessionId": session.sessionId,
        "newDeviceKeyId": session.newDeviceKeyId,
        "newDeviceName": session.newDeviceName,
        "method": session.method,
        "state": "completed",
        "collectionsGranted": [],
        "note": (
            "The new device holds no collection keys until the user selects which collections to "
            "grant. Selective sync defaults to granting nothing."
        ),
    }
