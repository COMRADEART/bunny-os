"""Signing role separation, key lifecycle, and the development/production wall.

Seven signing roles exist, each with a disjoint key-id namespace. The namespaces
are checked at parse time rather than by convention, so a key minted for one
authority cannot be presented for another: a fleet policy key cannot cause an OS
image to be installed, and a recovery key cannot sign an application catalogue.

The second wall is between development and production keys. Every development
key id carries a mandatory ``dev-`` prefix *before* its role prefix, and
:func:`require_production_key` refuses it. A development signing drill can
therefore exercise the entire path end to end without any possibility that the
artifacts it produces satisfy a production release gate.

No private key material is handled here. This module reasons about key
*identities*, lifecycle state, and role fitness; the actual signing is done by
``build/scripts/sign-stable-rc.py`` with keys stored outside the repository.
"""

from __future__ import annotations

from dataclasses import dataclass
import datetime as _datetime
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

SCHEMA_VERSION = 1

#: Role name to key-id namespace prefix. No prefix may be a prefix of another,
#: which :func:`validate_namespaces` asserts.
SIGNING_ROLES: dict[str, str] = {
    "osRelease": "bunny-os-release-",
    "updateMetadata": "update-",
    "recoveryImage": "recovery-",
    "applicationCatalogue": "catalogue-",
    "oemProfile": "oem-",
    "fleetPolicy": "fleet-",
    "syncServiceIdentity": "sync-",
}

#: What each role is permitted to authorise. Recorded so a review can check the
#: blast radius of one compromised key without reading the implementation.
ROLE_AUTHORITY: dict[str, str] = {
    "osRelease": "Can cause an artifact to be accepted as an official Bunny OS release.",
    "updateMetadata": "Can cause an enrolled device to install a new OS image.",
    "recoveryImage": "Can cause recovery media to be accepted as genuine and booted.",
    "applicationCatalogue": "Can cause an application catalogue entry to be installable.",
    "oemProfile": "Can cause an OEM customisation to apply to a matching hardware model. Cannot alter update trust, privacy defaults, or security protections.",
    "fleetPolicy": "Can cause an enrolled device to apply organisation policy. Cannot cause an OS image to be installed and cannot disable signature verification.",
    "syncServiceIdentity": "Can authenticate a sync service to a device. Cannot decrypt user content.",
}

#: Roles where a two-person approval is practical and therefore required. Sync
#: service identity rotates operationally and is excluded; the rest gate rarely
#: enough that two people is not an obstacle.
TWO_PERSON_ROLES = frozenset({"osRelease", "updateMetadata", "recoveryImage", "oemProfile"})

DEVELOPMENT_PREFIX = "dev-"
KEY_CLASSES = ("development", "production")
KEY_STATES = ("active", "pending", "rotating", "revoked", "expired")

_KEY_SUFFIX = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_RFC3339 = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")


class SigningError(ValueError):
    """Raised when a key identity, role, or lifecycle state is invalid."""


def validate_namespaces(roles: Mapping[str, str] = SIGNING_ROLES) -> None:
    """Assert that no role prefix is a prefix of another role's prefix."""
    prefixes = sorted(roles.values())
    if len(set(prefixes)) != len(prefixes):
        raise SigningError("signing role prefixes must be unique")
    for outer in prefixes:
        for inner in prefixes:
            if outer != inner and inner.startswith(outer):
                raise SigningError(
                    f"namespace {outer!r} is a prefix of {inner!r}; roles would not be separable"
                )
    for name, prefix in roles.items():
        if prefix.startswith(DEVELOPMENT_PREFIX):
            raise SigningError(f"role {name} may not use the reserved development prefix")


@dataclass(frozen=True)
class KeyIdentity:
    keyId: str
    role: str
    keyClass: str

    @property
    def isDevelopment(self) -> bool:
        return self.keyClass == "development"

    def as_dict(self) -> dict[str, Any]:
        return {"keyId": self.keyId, "role": self.role, "keyClass": self.keyClass}


def parse_key_id(keyId: str, *, expectedRole: str | None = None) -> KeyIdentity:
    """Resolve a key id to its role and class, refusing ambiguity."""
    if not isinstance(keyId, str) or not keyId:
        raise SigningError("key id must be a non-empty string")

    key_class = "production"
    remainder = keyId
    if keyId.startswith(DEVELOPMENT_PREFIX):
        key_class = "development"
        remainder = keyId[len(DEVELOPMENT_PREFIX) :]

    matched: list[str] = [
        name for name, prefix in SIGNING_ROLES.items() if remainder.startswith(prefix)
    ]
    if not matched:
        raise SigningError(
            f"key id {keyId!r} is in no signing namespace; expected one of "
            + ", ".join(sorted(SIGNING_ROLES.values()))
        )
    if len(matched) > 1:  # pragma: no cover - validate_namespaces prevents this
        raise SigningError(f"key id {keyId!r} matches multiple namespaces: {', '.join(sorted(matched))}")

    role = matched[0]
    suffix = remainder[len(SIGNING_ROLES[role]) :]
    if not _KEY_SUFFIX.match(suffix):
        raise SigningError(f"key id {keyId!r} has an invalid suffix {suffix!r}")

    if expectedRole is not None and role != expectedRole:
        raise SigningError(
            f"key {keyId!r} belongs to the {role} authority but was presented for {expectedRole}; "
            "signing roles are not interchangeable"
        )
    return KeyIdentity(keyId=keyId, role=role, keyClass=key_class)


def require_production_key(key: KeyIdentity) -> KeyIdentity:
    """Refuse a development key on a production path."""
    if key.isDevelopment:
        raise SigningError(
            f"key {key.keyId!r} is a development key and can never satisfy a production release "
            "gate; development artifacts are not releasable"
        )
    return key


@dataclass(frozen=True)
class KeyRecord:
    keyId: str
    role: str
    keyClass: str
    state: str
    publishedAt: str
    expiresAt: str
    publicKeyReference: str
    storage: str
    twoPersonApproval: bool
    supersedes: str | None = None
    revokedAt: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "keyId": self.keyId,
            "role": self.role,
            "keyClass": self.keyClass,
            "state": self.state,
            "publishedAt": self.publishedAt,
            "expiresAt": self.expiresAt,
            "publicKeyReference": self.publicKeyReference,
            "storage": self.storage,
            "twoPersonApproval": self.twoPersonApproval,
            "supersedes": self.supersedes,
            "revokedAt": self.revokedAt,
        }


def parse_key_record(record: Mapping[str, Any]) -> KeyRecord:
    required = (
        "keyId",
        "state",
        "publishedAt",
        "expiresAt",
        "publicKeyReference",
        "storage",
        "twoPersonApproval",
    )
    missing = [name for name in required if name not in record]
    if missing:
        raise SigningError(f"key record missing fields: {', '.join(missing)}")

    identity = parse_key_id(str(record["keyId"]))
    state = record["state"]
    if state not in KEY_STATES:
        raise SigningError(f"{identity.keyId}: state must be one of {', '.join(KEY_STATES)}")
    for name in ("publishedAt", "expiresAt"):
        if not _RFC3339.match(str(record[name])):
            raise SigningError(f"{identity.keyId}: {name} must be an RFC 3339 timestamp")
    if record.get("revokedAt") is not None and not _RFC3339.match(str(record["revokedAt"])):
        raise SigningError(f"{identity.keyId}: revokedAt must be an RFC 3339 timestamp")
    if not isinstance(record["twoPersonApproval"], bool):
        raise SigningError(f"{identity.keyId}: twoPersonApproval must be a boolean")

    if (
        identity.keyClass == "production"
        and identity.role in TWO_PERSON_ROLES
        and not record["twoPersonApproval"]
    ):
        raise SigningError(
            f"{identity.keyId}: the {identity.role} authority requires two-person approval"
        )

    storage = str(record["storage"])
    if identity.keyClass == "production" and storage not in {"hardware-token", "offline-hsm", "protected-signing-service"}:
        raise SigningError(
            f"{identity.keyId}: production key storage must be a hardware token, offline HSM, or "
            f"protected signing service; got {storage!r}"
        )

    return KeyRecord(
        keyId=identity.keyId,
        role=identity.role,
        keyClass=identity.keyClass,
        state=state,
        publishedAt=str(record["publishedAt"]),
        expiresAt=str(record["expiresAt"]),
        publicKeyReference=str(record["publicKeyReference"]),
        storage=storage,
        twoPersonApproval=bool(record["twoPersonApproval"]),
        supersedes=record.get("supersedes"),
        revokedAt=record.get("revokedAt"),
    )


def usable_key(
    record: KeyRecord,
    *,
    role: str,
    now: _datetime.datetime,
    revokedKeyIds: Iterable[str] = (),
    requireProduction: bool = True,
) -> tuple[bool, str]:
    """Return ``(usable, reason)`` for one key at one moment."""
    if record.role != role:
        return False, f"key belongs to the {record.role} authority, not {role}"
    if record.keyId in set(revokedKeyIds) or record.state == "revoked":
        return False, "key is revoked"
    if requireProduction and record.keyClass == "development":
        return False, "development key presented on a production path"
    expires = _datetime.datetime.fromisoformat(record.expiresAt.replace("Z", "+00:00"))
    if expires <= now:
        return False, f"key expired at {record.expiresAt}"
    published = _datetime.datetime.fromisoformat(record.publishedAt.replace("Z", "+00:00"))
    if published > now:
        return False, f"key is not yet published (publishedAt {record.publishedAt})"
    if record.state not in {"active", "rotating"}:
        return False, f"key state is {record.state}"
    return True, "usable"


def rotation_overlap(previous: KeyRecord, replacement: KeyRecord) -> tuple[bool, str]:
    """Rotation must publish the replacement before the predecessor expires."""
    if previous.role != replacement.role:
        return False, "rotation must stay within one signing authority"
    if replacement.supersedes != previous.keyId:
        return False, f"{replacement.keyId} does not declare that it supersedes {previous.keyId}"
    published = _datetime.datetime.fromisoformat(replacement.publishedAt.replace("Z", "+00:00"))
    expires = _datetime.datetime.fromisoformat(previous.expiresAt.replace("Z", "+00:00"))
    if published >= expires:
        return False, (
            "no overlapping trust period: the replacement is published at or after the predecessor "
            "expires, so a device that updates late would trust neither key"
        )
    return True, f"overlap of {(expires - published).days} days"


#: The nine checks the development signing drill must perform.
DRILL_CHECKS = (
    "release-image-signing",
    "recovery-image-signing",
    "update-manifest-signing",
    "catalogue-signing",
    "verification",
    "key-rotation",
    "revoked-key-rejection",
    "wrong-role-rejection",
    "corrupted-artifact-rejection",
)


@dataclass(frozen=True)
class DrillResult:
    check: str
    outcome: str
    detail: str
    command: str

    def as_dict(self) -> dict[str, Any]:
        return {"check": self.check, "outcome": self.outcome, "detail": self.detail, "command": self.command}


def evaluate_drill(results: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Evaluate a development signing drill record."""
    rows: list[DrillResult] = []
    for record in results:
        check = record.get("check")
        if check not in DRILL_CHECKS:
            raise SigningError(f"unknown drill check {check!r}")
        outcome = record.get("outcome")
        if outcome not in {"PASS", "FAIL", "NOT_RUN"}:
            raise SigningError(f"{check}: outcome must be PASS, FAIL or NOT_RUN")
        rows.append(
            DrillResult(
                check=check,
                outcome=outcome,
                detail=str(record.get("detail", "")),
                command=str(record.get("command", "")),
            )
        )
    seen = {row.check for row in rows}
    missing = sorted(set(DRILL_CHECKS) - seen)
    failing = sorted(row.check for row in rows if row.outcome != "PASS")
    return {
        "schemaVersion": SCHEMA_VERSION,
        "checks": [row.as_dict() for row in rows],
        "missingChecks": missing,
        "failingChecks": failing,
        "result": "PASS" if not missing and not failing else "FAIL",
        "keyClass": "development",
        "note": (
            "A development signing drill proves the signing path works. It is not release signing "
            "evidence: every key used carries the reserved dev- prefix and is refused by "
            "require_production_key."
        ),
    }


# --------------------------------------------------------------------------- #
# Two-person approval
# --------------------------------------------------------------------------- #

#: The nine checks a two-person drill must perform.
TWO_PERSON_DRILL_CHECKS = (
    "signer-a-approval",
    "signer-b-approval",
    "distinct-keys",
    "distinct-key-ids",
    "distinct-operation-logs",
    "artifact-digest-agreement",
    "role-verification",
    "revocation-test",
    "disagreement-refusal",
)

SIGNER_DECISIONS = ("approve", "refuse")


@dataclass(frozen=True)
class SignerApproval:
    signerId: str
    keyId: str
    role: str
    keyClass: str
    operatorFingerprint: str
    operationLogReference: str
    artifactDigest: str
    decision: str
    approvedAt: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "signerId": self.signerId,
            "keyId": self.keyId,
            "role": self.role,
            "keyClass": self.keyClass,
            "operatorFingerprint": self.operatorFingerprint,
            "operationLogReference": self.operationLogReference,
            "artifactDigest": self.artifactDigest,
            "decision": self.decision,
            "approvedAt": self.approvedAt,
        }


def parse_signer_approval(record: Mapping[str, Any], *, expectedRole: str | None = None) -> SignerApproval:
    """Validate one signer's approval of one artifact."""
    if not isinstance(record, Mapping):
        raise SigningError("signer approval must be an object")
    required = (
        "signerId",
        "keyId",
        "operatorFingerprint",
        "operationLogReference",
        "artifactDigest",
        "decision",
        "approvedAt",
    )
    missing = [name for name in required if not str(record.get(name) or "").strip()]
    if missing:
        raise SigningError(f"signer approval missing fields: {', '.join(sorted(missing))}")

    identity = parse_key_id(str(record["keyId"]), expectedRole=expectedRole)
    decision = record["decision"]
    if decision not in SIGNER_DECISIONS:
        raise SigningError(f"{identity.keyId}: decision must be one of {', '.join(SIGNER_DECISIONS)}")
    if not _RFC3339.match(str(record["approvedAt"])):
        raise SigningError(f"{identity.keyId}: approvedAt must be an RFC 3339 timestamp")
    digest = str(record["artifactDigest"])
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise SigningError(f"{identity.keyId}: artifactDigest must be a SHA-256 hex digest")

    return SignerApproval(
        signerId=str(record["signerId"]),
        keyId=identity.keyId,
        role=identity.role,
        keyClass=identity.keyClass,
        operatorFingerprint=str(record["operatorFingerprint"]),
        operationLogReference=str(record["operationLogReference"]),
        artifactDigest=digest,
        decision=str(decision),
        approvedAt=str(record["approvedAt"]),
    )


def evaluate_two_person_approval(
    first: SignerApproval,
    second: SignerApproval,
    *,
    role: str,
) -> dict[str, Any]:
    """Decide whether two approvals constitute a valid two-person authorisation.

    The check that matters is ``operatorFingerprint``. Two key ids and two
    operation logs are trivially produced by one person with two files; a
    fingerprint derived from the operating account and host is not. It is not
    proof — a determined operator can defeat it — but it converts "one person
    supplying two signer identities" from the default outcome into a deliberate
    act, and it is the strongest control available without a second human.
    """
    reasons: list[str] = []
    satisfied: list[str] = []

    def check(name: str, ok: bool, why: str) -> None:
        (satisfied if ok else reasons).append(name if ok else f"{name}: {why}")

    if role not in TWO_PERSON_ROLES:
        raise SigningError(
            f"{role} does not require two-person approval; the roles that do are "
            + ", ".join(sorted(TWO_PERSON_ROLES))
        )

    check("role-verification", first.role == role and second.role == role,
          f"approvals are for {first.role} and {second.role}, not {role}")
    check("distinct-key-ids", first.keyId != second.keyId,
          f"both approvals use key {first.keyId}; one key is not two signers")
    check("distinct-operation-logs", first.operationLogReference != second.operationLogReference,
          "both approvals cite the same operation log")
    check(
        "distinct-signers",
        first.operatorFingerprint != second.operatorFingerprint,
        (
            f"both approvals carry operator fingerprint {first.operatorFingerprint}; one person "
            "supplying two signer identities is not two-person approval"
        ),
    )
    check("distinct-signer-ids", first.signerId != second.signerId,
          f"both approvals name signer {first.signerId}")
    check("artifact-digest-agreement", first.artifactDigest == second.artifactDigest,
          f"signers approved different artifacts: {first.artifactDigest[:12]} vs {second.artifactDigest[:12]}")

    both_approve = first.decision == "approve" and second.decision == "approve"
    check("unanimous-approval", both_approve,
          "at least one signer refused; two-person approval requires both, and a refusal is final")

    return {
        "schemaVersion": SCHEMA_VERSION,
        "role": role,
        "signers": [first.as_dict(), second.as_dict()],
        "satisfied": satisfied,
        "reasons": reasons,
        "authorised": not reasons,
        "keyClasses": sorted({first.keyClass, second.keyClass}),
        "productionCapable": first.keyClass == "production" and second.keyClass == "production",
        "result": "PASS" if not reasons else "FAIL",
        "note": (
            "Two development keys establish that the two-person path works. They do not provision "
            "the role: a production two-person authorisation needs two production keys held by two "
            "people, and no production key of any role exists."
        ),
    }


def evaluate_two_person_drill(document: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate a recorded two-person development signing drill."""
    if document.get("schemaVersion") != SCHEMA_VERSION:
        raise SigningError("two-person drill schemaVersion is invalid")

    rows: list[DrillResult] = []
    for record in document.get("checks", []):
        check = record.get("check")
        if check not in TWO_PERSON_DRILL_CHECKS:
            raise SigningError(f"unknown two-person drill check {check!r}")
        outcome = record.get("outcome")
        if outcome not in {"PASS", "FAIL", "NOT_RUN"}:
            raise SigningError(f"{check}: outcome must be PASS, FAIL or NOT_RUN")
        rows.append(
            DrillResult(
                check=str(check),
                outcome=str(outcome),
                detail=str(record.get("detail", "")),
                command=str(record.get("command", "")),
            )
        )

    seen = {row.check for row in rows}
    missing = sorted(set(TWO_PERSON_DRILL_CHECKS) - seen)
    failing = sorted(row.check for row in rows if row.outcome != "PASS")

    signers = document.get("signers") or []
    signer_detail: Any = None
    if len(signers) == 2:
        role = str(document.get("role", "osRelease"))
        first = parse_signer_approval(signers[0], expectedRole=role)
        second = parse_signer_approval(signers[1], expectedRole=role)
        if "production" in {first.keyClass, second.keyClass}:
            raise SigningError(
                "a development drill may not use a production key; the drill exists precisely so "
                "that the path can be exercised without releasable output"
            )
        signer_detail = evaluate_two_person_approval(first, second, role=role)
        if not signer_detail["authorised"]:
            failing = sorted(set(failing) | {"signer-a-approval", "signer-b-approval"})

    return {
        "schemaVersion": SCHEMA_VERSION,
        "checks": [row.as_dict() for row in rows],
        "missingChecks": missing,
        "failingChecks": failing,
        "twoPersonApproval": signer_detail,
        "keyClass": "development",
        "result": "PASS" if not missing and not failing else "FAIL",
        "satisfiesProductionRequirement": False,
        "note": (
            "This drill validates the two-person process with two separate development keys. It "
            "does not satisfy the production second-signer requirement, which needs a second "
            "person, a key ceremony, and hardware-token or offline-HSM custody."
        ),
    }


def load(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


__all__ = [
    "DEVELOPMENT_PREFIX",
    "DRILL_CHECKS",
    "KEY_STATES",
    "ROLE_AUTHORITY",
    "SIGNER_DECISIONS",
    "SIGNING_ROLES",
    "TWO_PERSON_DRILL_CHECKS",
    "TWO_PERSON_ROLES",
    "DrillResult",
    "KeyIdentity",
    "KeyRecord",
    "SignerApproval",
    "SigningError",
    "evaluate_drill",
    "evaluate_two_person_approval",
    "evaluate_two_person_drill",
    "parse_key_id",
    "parse_key_record",
    "parse_signer_approval",
    "require_production_key",
    "rotation_overlap",
    "usable_key",
    "validate_namespaces",
]
