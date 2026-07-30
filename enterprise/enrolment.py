"""Typed organisation enrolment.

Enrolment is the moment a device gains an organisational relationship, so it is
also the moment a user must be told exactly what changes. This module enforces
both halves:

* the *protocol* is typed, single-use, expiring, and replay-protected, following
  the same shape as ``installer/protocol.py`` (exact field sets, RFC 3339
  freshness window, nonce cache, recursive secret rejection);
* the *disclosure* is mandatory, and an enrolment cannot be accepted unless every
  disclosure field an administrator is required to state has been stated.

Secret handling rule: the bearer secret never appears in a protocol payload, a
log line, or a process argument. ``redact_for_log`` is the only supported way to
render an enrolment message for the journal.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
from typing import Any, Iterable, Mapping, MutableSet

SCHEMA_VERSION = 1

#: Ownership models. The distinction drives which remote actions are permitted;
#: see ``enterprise/remote.py``.
ENROLMENT_MODES = (
    "personally-owned",
    "organisation-managed",
    "organisation-owned",
    "shared-laboratory-device",
    "kiosk-or-dedicated-purpose",
)

#: Modes where the device belongs to the organisation rather than the user.
ORGANISATION_OWNED_MODES = frozenset({
    "organisation-owned",
    "shared-laboratory-device",
    "kiosk-or-dedicated-purpose",
})

#: Every fact the enrolment screen must present before a user or administrator
#: may confirm. An absent field blocks enrolment.
REQUIRED_DISCLOSURE_FIELDS = (
    "organisationName",
    "managementServer",
    "policiesApplied",
    "informationVisibleToOrganisation",
    "remoteActionsAvailable",
    "applicationControls",
    "updateControls",
    "unenrolmentRules",
    "personalDataBoundary",
)

#: Ordered enrolment states. Enrolment is resumable: an interruption leaves the
#: device at the last completed state rather than in an undefined condition.
ENROLMENT_STATES = (
    "unenrolled",
    "token-validated",
    "organisation-trust-validated",
    "device-key-generated",
    "certificate-issued",
    "device-registered",
    "policy-bootstrapped",
    "enrolled",
    "unenrolling",
)

_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "unenrolled": frozenset({"token-validated"}),
    "token-validated": frozenset({"organisation-trust-validated", "unenrolled"}),
    "organisation-trust-validated": frozenset({"device-key-generated", "unenrolled"}),
    "device-key-generated": frozenset({"certificate-issued", "unenrolled"}),
    "certificate-issued": frozenset({"device-registered", "unenrolled"}),
    "device-registered": frozenset({"policy-bootstrapped", "unenrolled"}),
    "policy-bootstrapped": frozenset({"enrolled", "unenrolled"}),
    "enrolled": frozenset({"unenrolling"}),
    "unenrolling": frozenset({"unenrolled"}),
}

MESSAGE_TYPES = (
    "enrolment.begin",
    "enrolment.challenge",
    "enrolment.complete",
    "enrolment.resume",
    "unenrolment.request",
)

#: Field names that must never carry a value in an enrolment payload. The bearer
#: secret is presented out of band and proved by challenge response.
SECRET_FIELDS = frozenset({
    "token", "tokensecret", "bearer", "bearersecret", "secret", "password", "passphrase",
    "apikey", "privatekey", "credential", "credentials", "enrolmentsecret", "enrollmentsecret",
    "recoverykey", "psk", "wifipassword",
})

TOKEN_MAX_LIFETIME = timedelta(hours=24)
FRESHNESS_WINDOW_SECONDS = 60

_TOKEN_ID = re.compile(r"^ent-[0-9a-f]{16}$")
_ORGANISATION_ID = re.compile(r"^org-[a-z0-9][a-z0-9-]{1,62}$")
_NONCE = re.compile(r"^[A-Za-z0-9_-]{22,64}$")
_RFC3339 = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")
_HTTPS_URL = re.compile(r"^https://[A-Za-z0-9.-]+(?::\d{2,5})?(?:/[A-Za-z0-9._~/-]*)?$")


class EnrolmentError(ValueError):
    """Raised when an enrolment message or disclosure violates an invariant."""


def _parse_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not _RFC3339.match(value):
        raise EnrolmentError(f"{field} must be an RFC 3339 timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise EnrolmentError(f"{field} requires a timezone")
    return parsed.astimezone(timezone.utc)


def _contains_secret_field(value: Any) -> str | None:
    """Return the first secret-shaped key found at any depth, else ``None``."""
    if isinstance(value, Mapping):
        for key, child in value.items():
            folded = str(key).replace("_", "").replace("-", "").casefold()
            if folded in SECRET_FIELDS:
                return str(key)
            found = _contains_secret_field(child)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _contains_secret_field(item)
            if found:
                return found
    return None


@dataclass(frozen=True)
class EnrolmentToken:
    tokenId: str
    organisationId: str
    issuedAt: str
    expiresAt: str
    singleUse: bool
    mode: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "tokenId": self.tokenId,
            "organisationId": self.organisationId,
            "issuedAt": self.issuedAt,
            "expiresAt": self.expiresAt,
            "singleUse": self.singleUse,
            "mode": self.mode,
        }


def parse_enrolment_token(
    record: Mapping[str, Any],
    *,
    now: datetime | None = None,
    consumed_token_ids: Iterable[str] = (),
) -> EnrolmentToken:
    """Validate a one-time enrolment token descriptor.

    The descriptor carries no secret. It states which organisation issued the
    token, when it expires, and whether it is single-use; the secret itself is
    proved separately through the challenge exchange.
    """
    if not isinstance(record, Mapping):
        raise EnrolmentError("token descriptor must be a mapping")

    allowed = {"schemaVersion", "tokenId", "organisationId", "issuedAt", "expiresAt", "singleUse", "mode"}
    if set(record) != allowed:
        missing = sorted(allowed - set(record))
        extra = sorted(set(record) - allowed)
        raise EnrolmentError(f"token fields mismatch; missing={missing}, extra={extra}")
    if record["schemaVersion"] != SCHEMA_VERSION:
        raise EnrolmentError("unsupported token schemaVersion")

    leaked = _contains_secret_field(record)
    if leaked:
        raise EnrolmentError(f"token descriptor must not carry secret field {leaked!r}")

    token_id = record["tokenId"]
    if not isinstance(token_id, str) or not _TOKEN_ID.match(token_id):
        raise EnrolmentError("tokenId must match ent-<16 hex>")

    organisation_id = record["organisationId"]
    if not isinstance(organisation_id, str) or not _ORGANISATION_ID.match(organisation_id):
        raise EnrolmentError("organisationId must match org-<slug>")

    mode = record["mode"]
    if mode not in ENROLMENT_MODES:
        raise EnrolmentError(f"mode {mode!r} is not a recognised enrolment mode")

    if record["singleUse"] is not True:
        raise EnrolmentError("enrolment tokens must be single-use")

    issued_at = _parse_timestamp(record["issuedAt"], "issuedAt")
    expires_at = _parse_timestamp(record["expiresAt"], "expiresAt")
    if expires_at <= issued_at:
        raise EnrolmentError("expiresAt must be after issuedAt")
    if expires_at - issued_at > TOKEN_MAX_LIFETIME:
        raise EnrolmentError(f"token lifetime exceeds the {TOKEN_MAX_LIFETIME} maximum")

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if current >= expires_at:
        raise EnrolmentError("enrolment token has expired")

    if token_id in set(consumed_token_ids):
        raise EnrolmentError("enrolment token has already been consumed; replay rejected")

    return EnrolmentToken(
        tokenId=token_id,
        organisationId=organisation_id,
        issuedAt=record["issuedAt"],
        expiresAt=record["expiresAt"],
        singleUse=True,
        mode=mode,
    )


def parse_message(
    payload: Mapping[str, Any],
    *,
    now: datetime | None = None,
    seen_nonces: MutableSet[str] | None = None,
) -> dict[str, Any]:
    """Validate one enrolment protocol message.

    Mirrors ``installer/protocol.py``: exact field set, closed message-type
    vocabulary, freshness window, per-message nonce, and recursive rejection of
    secret-shaped fields.
    """
    if not isinstance(payload, Mapping):
        raise EnrolmentError("message must be a mapping")

    allowed = {"schemaVersion", "messageType", "messageId", "organisationId", "nonce", "timestamp", "params"}
    if set(payload) != allowed:
        missing = sorted(allowed - set(payload))
        extra = sorted(set(payload) - allowed)
        raise EnrolmentError(f"message fields mismatch; missing={missing}, extra={extra}")

    if payload["schemaVersion"] != SCHEMA_VERSION:
        raise EnrolmentError("unsupported message schemaVersion")

    message_type = payload["messageType"]
    if message_type not in MESSAGE_TYPES:
        raise EnrolmentError(f"unknown messageType {message_type!r}")

    organisation_id = payload["organisationId"]
    if not isinstance(organisation_id, str) or not _ORGANISATION_ID.match(organisation_id):
        raise EnrolmentError("organisationId must match org-<slug>")

    nonce = payload["nonce"]
    if not isinstance(nonce, str) or not _NONCE.match(nonce):
        raise EnrolmentError("nonce must be 22-64 URL-safe characters")

    params = payload["params"]
    if not isinstance(params, Mapping):
        raise EnrolmentError("params must be an object")
    leaked = _contains_secret_field(params)
    if leaked:
        raise EnrolmentError(f"secret field {leaked!r} is forbidden in enrolment payloads")

    timestamp = _parse_timestamp(payload["timestamp"], "timestamp")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if abs((current - timestamp).total_seconds()) > FRESHNESS_WINDOW_SECONDS:
        raise EnrolmentError("stale enrolment message")

    if seen_nonces is not None:
        if nonce in seen_nonces:
            raise EnrolmentError("enrolment nonce replay rejected")
        seen_nonces.add(nonce)

    return dict(payload)


def evaluate_disclosure(disclosure: Mapping[str, Any], *, mode: str) -> dict[str, Any]:
    """Check that an enrolment disclosure states everything it must.

    Returns a report rather than raising, because the enrolment screen needs to
    show the user which specific statement an administrator failed to provide.
    """
    if mode not in ENROLMENT_MODES:
        raise EnrolmentError(f"mode {mode!r} is not a recognised enrolment mode")
    if not isinstance(disclosure, Mapping):
        raise EnrolmentError("disclosure must be a mapping")

    missing = [field for field in REQUIRED_DISCLOSURE_FIELDS if not disclosure.get(field)]
    problems: list[str] = []

    server = disclosure.get("managementServer")
    if isinstance(server, str) and server and not _HTTPS_URL.match(server):
        problems.append("managementServer must be an https URL")

    for field in ("policiesApplied", "informationVisibleToOrganisation", "remoteActionsAvailable"):
        value = disclosure.get(field)
        if value is not None and not isinstance(value, list):
            problems.append(f"{field} must be a list so each item can be shown individually")

    if mode == "personally-owned":
        if not disclosure.get("unenrolmentRules"):
            problems.append("a personally owned device must disclose how the owner may unenrol")
        boundary = disclosure.get("personalDataBoundary")
        if isinstance(boundary, str) and boundary and "personal" not in boundary.casefold():
            problems.append("personalDataBoundary must state what remains outside organisation visibility")
        if disclosure.get("fullDeviceResetPermitted") is True:
            problems.append(
                "a personally owned device must not disclose blanket full-reset permission; "
                "full reset requires prior policy, strong authorisation, explicit scope, and audit evidence"
            )

    complete = not missing and not problems
    return {
        "mode": mode,
        "complete": complete,
        "missingFields": missing,
        "problems": problems,
        "confirmationRequired": True,
        "organisationOwned": mode in ORGANISATION_OWNED_MODES,
    }


def next_state(current: str, requested: str) -> str:
    """Validate an enrolment state transition, supporting resume and abort."""
    if current not in ENROLMENT_STATES:
        raise EnrolmentError(f"unknown current state {current!r}")
    if requested not in ENROLMENT_STATES:
        raise EnrolmentError(f"unknown requested state {requested!r}")
    if requested == current:
        return current
    if requested not in _ALLOWED_TRANSITIONS[current]:
        raise EnrolmentError(f"enrolment transition {current!r} -> {requested!r} is not permitted")
    return requested


def redact_for_log(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Render an enrolment message for the journal without secrets or params.

    The broker's audit line already establishes the pattern: identifiers and
    outcome, never parameters.
    """
    return {
        "messageType": payload.get("messageType"),
        "messageId": payload.get("messageId"),
        "organisationId": payload.get("organisationId"),
        "timestamp": payload.get("timestamp"),
        "paramsOmitted": True,
    }


def assert_no_secret_in_arguments(argv: Iterable[str]) -> None:
    """Refuse a command line that carries an enrolment secret.

    Process arguments are world-readable on Linux, so a reusable secret passed
    this way is disclosed to every local user.
    """
    for argument in argv:
        lowered = argument.casefold()
        for marker in ("--token=", "--secret=", "--password=", "--passphrase=", "--bearer="):
            if lowered.startswith(marker) and len(argument) > len(marker):
                raise EnrolmentError(
                    f"enrolment secrets must not appear in process arguments: {marker.rstrip('=')}"
                )
