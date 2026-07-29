"""Versioned encrypted-object envelope.

The envelope is what the service stores and routes. Its defining property is that
it carries *no* plaintext about the object it protects and *no* key material: a
service operator holding every envelope ever uploaded still cannot read a single
object.

Two checks enforce that rather than assert it:

* ``_assert_no_plaintext_fields`` refuses descriptive fields — titles, filenames,
  tags, previews — that would leak content through metadata;
* ``_assert_no_key_material`` refuses anything that looks like a key, wrapped key,
  passphrase, or recovery secret, so a client bug cannot upload the very material
  the design keeps away from the server.

Associated data is bound explicitly. The collection, object, version, and envelope
version are authenticated, so the service cannot move a ciphertext between
objects or replay an older version as a newer one without detection.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping

ENVELOPE_VERSION = 1

#: Reviewed AEAD constructions. Both are widely implemented and analysed; the
#: choice is deployment-dependent, not novel.
SUPPORTED_ALGORITHMS = {
    "XChaCha20-Poly1305": 24,
    "AES-256-GCM": 12,
}

KEY_REFERENCE_KINDS = ("collection-key", "object-key", "backup-key")

#: Fields that would describe the plaintext. Refused by name.
_PLAINTEXT_FIELDS = frozenset({
    "title", "name", "filename", "path", "displayname", "subject", "summary", "preview",
    "snippet", "excerpt", "tags", "labels", "keywords", "description", "content", "body",
    "text", "plaintext", "prompt", "prompts", "memory", "memories", "conversation",
    "mimetype", "contenttype", "extension", "author", "participants",
})

#: Fields that would carry key material to the service. Refused by name.
_KEY_MATERIAL_FIELDS = frozenset({
    "key", "keys", "keymaterial", "secretkey", "privatekey", "symmetrickey", "datakey",
    "wrappedkey", "unwrappedkey", "keybytes", "passphrase", "password", "recoverysecret",
    "recoveryphrase", "rootkey", "userrootkey", "masterkey", "seed", "entropy",
})

_COLLECTION_ID = re.compile(r"^col-[a-z0-9][a-z0-9-]{1,62}$")
_OBJECT_ID = re.compile(r"^obj-[0-9a-f]{32}$")
_KEY_ID = re.compile(r"^(?:ck|ok|bk)-[0-9a-f]{16}$")
_BASE64 = re.compile(r"^[A-Za-z0-9+/]+={0,2}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RFC3339 = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")

MAXIMUM_CIPHERTEXT_BYTES = 5 * 1024 * 1024 * 1024


class EnvelopeError(ValueError):
    """Raised when an envelope is malformed or would leak plaintext or keys."""


def _folded(key: str) -> str:
    return key.replace("_", "").replace("-", "").casefold()


def _assert_no_plaintext_fields(payload: Mapping[str, Any], path: str = "envelope") -> None:
    for key, value in payload.items():
        if _folded(str(key)) in _PLAINTEXT_FIELDS:
            raise EnvelopeError(
                f"{path}.{key} would expose plaintext metadata to the sync service"
            )
        if isinstance(value, Mapping):
            _assert_no_plaintext_fields(value, f"{path}.{key}")


def _assert_no_key_material(payload: Mapping[str, Any], path: str = "envelope") -> None:
    for key, value in payload.items():
        if _folded(str(key)) in _KEY_MATERIAL_FIELDS:
            raise EnvelopeError(
                f"{path}.{key} would place key material in an uploaded envelope; "
                "the sync operator never receives a plaintext decryption key"
            )
        if isinstance(value, Mapping):
            _assert_no_key_material(value, f"{path}.{key}")


def _decoded_length(value: str) -> int:
    """Return the byte length a base64 string decodes to, without decoding it."""
    padding = value.count("=")
    return (len(value) // 4) * 3 - padding


@dataclass(frozen=True)
class KeyReference:
    kind: str
    keyId: str
    generation: int

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "keyId": self.keyId, "generation": self.generation}


@dataclass(frozen=True)
class Envelope:
    envelopeVersion: int
    algorithm: str
    collectionId: str
    objectId: str
    objectVersion: int
    keyReference: KeyReference
    nonce: str
    ciphertextDigest: str
    ciphertextBytes: int
    createdAt: str
    deviceKeyId: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "envelopeVersion": self.envelopeVersion,
            "algorithm": self.algorithm,
            "collectionId": self.collectionId,
            "objectId": self.objectId,
            "objectVersion": self.objectVersion,
            "keyReference": self.keyReference.as_dict(),
            "nonce": self.nonce,
            "ciphertextDigest": self.ciphertextDigest,
            "ciphertextBytes": self.ciphertextBytes,
            "createdAt": self.createdAt,
            "deviceKeyId": self.deviceKeyId,
        }

    def associated_data(self) -> dict[str, Any]:
        """Return the authenticated associated data bound to this ciphertext.

        Binding these four values prevents an operator from relocating a
        ciphertext to a different object or replaying an older version.
        """
        return {
            "envelopeVersion": self.envelopeVersion,
            "collectionId": self.collectionId,
            "objectId": self.objectId,
            "objectVersion": self.objectVersion,
        }


def parse_envelope(record: Mapping[str, Any]) -> Envelope:
    """Validate one encrypted-object envelope."""
    if not isinstance(record, Mapping):
        raise EnvelopeError("envelope must be a mapping")

    _assert_no_plaintext_fields(record)
    _assert_no_key_material(record)

    allowed = {
        "envelopeVersion", "algorithm", "collectionId", "objectId", "objectVersion",
        "keyReference", "nonce", "ciphertextDigest", "ciphertextBytes", "createdAt", "deviceKeyId",
    }
    unexpected = sorted(set(record) - allowed)
    if unexpected:
        raise EnvelopeError("unknown envelope fields: " + ", ".join(unexpected))
    missing = sorted(allowed - set(record))
    if missing:
        raise EnvelopeError("missing envelope fields: " + ", ".join(missing))

    version = record["envelopeVersion"]
    if version != ENVELOPE_VERSION:
        raise EnvelopeError(f"unsupported envelopeVersion {version!r}; this client understands {ENVELOPE_VERSION}")

    algorithm = record["algorithm"]
    if algorithm not in SUPPORTED_ALGORITHMS:
        raise EnvelopeError(
            f"algorithm {algorithm!r} is not a reviewed AEAD construction; supported: "
            + ", ".join(sorted(SUPPORTED_ALGORITHMS))
        )

    collection_id = record["collectionId"]
    if not isinstance(collection_id, str) or not _COLLECTION_ID.match(collection_id):
        raise EnvelopeError("collectionId must match col-<slug>")

    object_id = record["objectId"]
    if not isinstance(object_id, str) or not _OBJECT_ID.match(object_id):
        raise EnvelopeError("objectId must match obj-<32 hex>")

    object_version = record["objectVersion"]
    if not isinstance(object_version, int) or isinstance(object_version, bool) or object_version < 1:
        raise EnvelopeError("objectVersion must be a positive whole number")

    reference = record["keyReference"]
    if not isinstance(reference, Mapping) or set(reference) != {"kind", "keyId", "generation"}:
        raise EnvelopeError("keyReference requires exactly kind, keyId, and generation")
    kind = reference["kind"]
    if kind not in KEY_REFERENCE_KINDS:
        raise EnvelopeError(f"keyReference.kind {kind!r} is not recognised")
    key_id = reference["keyId"]
    if not isinstance(key_id, str) or not _KEY_ID.match(key_id):
        raise EnvelopeError("keyReference.keyId must match ck-/ok-/bk- followed by 16 hex characters")
    generation = reference["generation"]
    if not isinstance(generation, int) or isinstance(generation, bool) or generation < 1:
        raise EnvelopeError("keyReference.generation must be a positive whole number")

    nonce = record["nonce"]
    if not isinstance(nonce, str) or not _BASE64.match(nonce):
        raise EnvelopeError("nonce must be base64")
    expected_nonce_bytes = SUPPORTED_ALGORITHMS[algorithm]
    if _decoded_length(nonce) != expected_nonce_bytes:
        raise EnvelopeError(
            f"{algorithm} requires a {expected_nonce_bytes}-byte nonce; "
            f"got {_decoded_length(nonce)} bytes"
        )

    digest = record["ciphertextDigest"]
    if not isinstance(digest, str) or not _SHA256.match(digest):
        raise EnvelopeError("ciphertextDigest must be 64 lowercase hex characters")

    size = record["ciphertextBytes"]
    if not isinstance(size, int) or isinstance(size, bool) or not 0 < size <= MAXIMUM_CIPHERTEXT_BYTES:
        raise EnvelopeError(f"ciphertextBytes must be between 1 and {MAXIMUM_CIPHERTEXT_BYTES}")

    created_at = record["createdAt"]
    if not isinstance(created_at, str) or not _RFC3339.match(created_at):
        raise EnvelopeError("createdAt must be an RFC 3339 timestamp")

    device_key_id = record["deviceKeyId"]
    if not isinstance(device_key_id, str) or not re.match(r"^dev-[0-9a-f]{16}$", device_key_id):
        raise EnvelopeError("deviceKeyId must match dev-<16 hex>")

    return Envelope(
        envelopeVersion=version,
        algorithm=algorithm,
        collectionId=collection_id,
        objectId=object_id,
        objectVersion=object_version,
        keyReference=KeyReference(kind=kind, keyId=key_id, generation=generation),
        nonce=nonce,
        ciphertextDigest=digest,
        ciphertextBytes=size,
        createdAt=created_at,
        deviceKeyId=device_key_id,
    )


def assert_no_version_rollback(stored: Mapping[str, Any], incoming: Mapping[str, Any]) -> None:
    """Refuse a server response that presents an older object version as current.

    This is the client-side defence against a compromised or rolled-back service
    replaying stale ciphertext.
    """
    current = parse_envelope(stored)
    candidate = parse_envelope(incoming)
    if candidate.objectId != current.objectId:
        raise EnvelopeError("cannot compare envelopes for different objects")
    if candidate.objectVersion < current.objectVersion:
        raise EnvelopeError(
            f"server offered version {candidate.objectVersion} for {candidate.objectId} but the device "
            f"already holds version {current.objectVersion}; server rollback refused"
        )
    if candidate.objectVersion == current.objectVersion and candidate.ciphertextDigest != current.ciphertextDigest:
        raise EnvelopeError(
            f"server offered a different ciphertext for {candidate.objectId} at the same version; "
            "ciphertext substitution refused"
        )
