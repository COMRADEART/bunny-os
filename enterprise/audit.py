"""Tamper-evident fleet audit records.

Four protections are required and each is implemented rather than described:

* *unauthorised modification* — every entry hashes its own canonical content plus
  the previous entry's hash, so editing an old entry invalidates every later one;
* *silent deletion* — entries carry a strictly increasing sequence within an
  organisation, so a removed entry leaves a detectable gap;
* *cross-organisation access* — every entry is organisation-scoped and the chain
  is verified per organisation, so one tenant's chain cannot be validated with
  another tenant's entries;
* *secret leakage* — entries are scanned against the shared secret and content
  vocabularies before they are accepted.

Canonical form is ``json.dumps(..., sort_keys=True, separators=(",", ":"))`` over
the entry with ``entryHash`` removed, matching the convention already documented
in ``schemas/README.md`` for update manifests.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Iterable, Mapping, Sequence

from operations.redaction import EXCLUDED_CONTENT_KEYS, SECRET_KEYS

SCHEMA_VERSION = 1

GENESIS_HASH = "0" * 64

RESULTS = ("succeeded", "failed", "refused", "partially-applied", "rolled-back")

AUTHORISATION_METHODS = (
    "local-administrator",
    "oidc",
    "saml",
    "passkey",
    "hardware-security-key",
    "recovery-code",
)

#: Retention is stated explicitly because "kept indefinitely" is itself a privacy
#: decision. Organisations may shorten but not lengthen beyond the maximum.
DEFAULT_RETENTION_DAYS = 400
MAXIMUM_RETENTION_DAYS = 2555

_CORRELATION_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_ORGANISATION_ID = re.compile(r"^org-[a-z0-9][a-z0-9-]{1,62}$")
_RFC3339 = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

_REQUIRED_FIELDS = (
    "schemaVersion",
    "sequence",
    "organisationId",
    "administrator",
    "operation",
    "targetScope",
    "policyVersion",
    "occurredAt",
    "authorisation",
    "result",
    "correlationId",
    "previousHash",
)

_OPTIONAL_FIELDS = ("failureCode", "rolledBack", "entryHash")


class AuditError(ValueError):
    """Raised when an audit entry or chain fails validation."""


def _folded(key: str) -> str:
    return key.replace("_", "").replace("-", "").casefold()


def _assert_no_sensitive_fields(entry: Mapping[str, Any], path: str = "entry") -> None:
    for key, value in entry.items():
        folded = _folded(str(key))
        if folded in SECRET_KEYS:
            raise AuditError(f"audit {path}.{key} would store secret material")
        if folded in EXCLUDED_CONTENT_KEYS:
            raise AuditError(f"audit {path}.{key} would store user content")
        if isinstance(value, Mapping):
            _assert_no_sensitive_fields(value, f"{path}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                if isinstance(item, Mapping):
                    _assert_no_sensitive_fields(item, f"{path}.{key}[{index}]")


def canonical_bytes(entry: Mapping[str, Any]) -> bytes:
    """Return the canonical byte form used for hashing, excluding ``entryHash``."""
    payload = {key: value for key, value in entry.items() if key != "entryHash"}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def compute_hash(entry: Mapping[str, Any]) -> str:
    """Return the sha256 hex digest of an entry's canonical form."""
    return hashlib.sha256(canonical_bytes(entry)).hexdigest()


@dataclass(frozen=True)
class AuditEntry:
    sequence: int
    organisationId: str
    administrator: str
    operation: str
    targetScope: tuple[str, ...]
    policyVersion: int | None
    occurredAt: str
    authorisation: str
    result: str
    correlationId: str
    previousHash: str
    entryHash: str
    failureCode: str | None = None
    rolledBack: bool = False

    def as_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "schemaVersion": SCHEMA_VERSION,
            "sequence": self.sequence,
            "organisationId": self.organisationId,
            "administrator": self.administrator,
            "operation": self.operation,
            "targetScope": list(self.targetScope),
            "policyVersion": self.policyVersion,
            "occurredAt": self.occurredAt,
            "authorisation": self.authorisation,
            "result": self.result,
            "correlationId": self.correlationId,
            "previousHash": self.previousHash,
            "entryHash": self.entryHash,
        }
        if self.failureCode is not None:
            value["failureCode"] = self.failureCode
        if self.rolledBack:
            value["rolledBack"] = True
        return value


def parse_entry(record: Mapping[str, Any], *, verify_hash: bool = True) -> AuditEntry:
    """Validate one audit entry, optionally verifying its self-hash."""
    if not isinstance(record, Mapping):
        raise AuditError("audit entry must be a mapping")

    allowed = set(_REQUIRED_FIELDS) | set(_OPTIONAL_FIELDS)
    unexpected = sorted(set(record) - allowed)
    if unexpected:
        raise AuditError("unknown audit fields: " + ", ".join(unexpected))
    missing = sorted(set(_REQUIRED_FIELDS) - set(record))
    if missing:
        raise AuditError("missing audit fields: " + ", ".join(missing))

    _assert_no_sensitive_fields(record)

    if record["schemaVersion"] != SCHEMA_VERSION:
        raise AuditError("unsupported audit schemaVersion")

    sequence = record["sequence"]
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
        raise AuditError("sequence must be a positive whole number")

    organisation_id = record["organisationId"]
    if not isinstance(organisation_id, str) or not _ORGANISATION_ID.match(organisation_id):
        raise AuditError("organisationId must match org-<slug>")

    administrator = record["administrator"]
    if not isinstance(administrator, str) or not administrator:
        raise AuditError("administrator must be a non-empty identifier")

    operation = record["operation"]
    if not isinstance(operation, str) or not operation:
        raise AuditError("operation must be a non-empty string")

    scope = record["targetScope"]
    if not isinstance(scope, list) or not scope or any(not isinstance(item, str) or not item for item in scope):
        raise AuditError("targetScope must be a non-empty list of non-empty strings")

    policy_version = record["policyVersion"]
    if policy_version is not None and (not isinstance(policy_version, int) or isinstance(policy_version, bool) or policy_version < 1):
        raise AuditError("policyVersion must be a positive whole number or null")

    occurred_at = record["occurredAt"]
    if not isinstance(occurred_at, str) or not _RFC3339.match(occurred_at):
        raise AuditError("occurredAt must be an RFC 3339 timestamp")

    authorisation = record["authorisation"]
    if authorisation not in AUTHORISATION_METHODS:
        raise AuditError(f"authorisation {authorisation!r} is not a recognised method")

    result = record["result"]
    if result not in RESULTS:
        raise AuditError(f"result {result!r} is not a recognised outcome")

    correlation_id = record["correlationId"]
    if not isinstance(correlation_id, str) or not _CORRELATION_ID.match(correlation_id):
        raise AuditError("correlationId must be a UUID")

    previous_hash = record["previousHash"]
    if not isinstance(previous_hash, str) or not _SHA256.match(previous_hash):
        raise AuditError("previousHash must be 64 lowercase hex characters")

    failure_code = record.get("failureCode")
    if result == "failed" and not failure_code:
        raise AuditError("a failed entry must record a failureCode")
    if failure_code is not None and (not isinstance(failure_code, str) or not failure_code):
        raise AuditError("failureCode must be a non-empty string when present")

    rolled_back = record.get("rolledBack", False)
    if not isinstance(rolled_back, bool):
        raise AuditError("rolledBack must be a boolean")

    expected_hash = compute_hash(record)
    entry_hash = record.get("entryHash", expected_hash)
    if verify_hash and entry_hash != expected_hash:
        raise AuditError(
            f"audit entry {sequence} hash mismatch; the entry was modified after it was written"
        )

    return AuditEntry(
        sequence=sequence,
        organisationId=organisation_id,
        administrator=administrator,
        operation=operation,
        targetScope=tuple(scope),
        policyVersion=policy_version,
        occurredAt=occurred_at,
        authorisation=authorisation,
        result=result,
        correlationId=correlation_id,
        previousHash=previous_hash,
        entryHash=entry_hash,
        failureCode=failure_code,
        rolledBack=rolled_back,
    )


def append_entry(chain: Sequence[Mapping[str, Any]], record: Mapping[str, Any]) -> dict[str, Any]:
    """Return ``record`` completed with its sequence, previousHash, and entryHash."""
    if chain:
        last = parse_entry(chain[-1])
        sequence = last.sequence + 1
        previous_hash = last.entryHash
        if record.get("organisationId") != last.organisationId:
            raise AuditError("cannot append an entry for a different organisation to this chain")
    else:
        sequence = 1
        previous_hash = GENESIS_HASH

    candidate = {key: value for key, value in record.items() if key not in {"sequence", "previousHash", "entryHash"}}
    candidate["schemaVersion"] = SCHEMA_VERSION
    candidate["sequence"] = sequence
    candidate["previousHash"] = previous_hash
    candidate["entryHash"] = compute_hash(candidate)
    parse_entry(candidate)
    return candidate


def verify_chain(entries: Iterable[Mapping[str, Any]], *, organisation_id: str) -> dict[str, Any]:
    """Verify a per-organisation audit chain.

    Returns a report naming the first detected problem rather than raising, so an
    auditor can see how far the chain verified before it broke.
    """
    if not _ORGANISATION_ID.match(organisation_id):
        raise AuditError("organisationId must match org-<slug>")

    problems: list[str] = []
    verified = 0
    expected_sequence = 1
    expected_previous = GENESIS_HASH

    for record in entries:
        try:
            entry = parse_entry(record)
        except AuditError as error:
            problems.append(f"entry {expected_sequence}: {error}")
            break

        if entry.organisationId != organisation_id:
            problems.append(
                f"entry {entry.sequence}: belongs to {entry.organisationId}, not {organisation_id}; "
                "cross-organisation audit access refused"
            )
            break
        if entry.sequence != expected_sequence:
            problems.append(
                f"expected sequence {expected_sequence} but found {entry.sequence}; "
                "an audit entry appears to have been deleted"
            )
            break
        if entry.previousHash != expected_previous:
            problems.append(
                f"entry {entry.sequence}: previousHash does not match the preceding entry; the chain was altered"
            )
            break

        verified += 1
        expected_sequence += 1
        expected_previous = entry.entryHash

    return {
        "organisationId": organisation_id,
        "intact": not problems,
        "verifiedEntries": verified,
        "problems": problems,
    }


def retention_policy(days: int | None = None) -> dict[str, Any]:
    """Return the retention and export policy for audit records."""
    value = DEFAULT_RETENTION_DAYS if days is None else days
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= MAXIMUM_RETENTION_DAYS:
        raise AuditError(f"retention must be between 1 and {MAXIMUM_RETENTION_DAYS} days")
    return {
        "retentionDays": value,
        "maximumRetentionDays": MAXIMUM_RETENTION_DAYS,
        "exportFormat": "newline-delimited JSON with the per-organisation hash chain included",
        "exportScope": "one organisation per export; a multi-organisation export is not produced",
        "deletionIsAppendOnly": True,
        "notes": [
            "Expiry removes whole entries from the head of the chain and records a signed truncation marker, "
            "so expiry is distinguishable from tampering.",
            "Exports never include secrets, user content, prompts, or memory.",
        ],
    }
