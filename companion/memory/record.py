# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""MemoryRecord v1 — the one-way door in ADR 0008 / Phase 1 §14.3.

Every field here is mandatory unless marked optional. There is **no**
model-authored ``confidence`` or ``importance`` column: those are computed at
read time so a poisoned write cannot promote itself. Inference lands
``proposed`` with a ``model_generated`` taint and is not a user-confirmed fact.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import secrets
from typing import Any, Mapping, Sequence

from companion.errors import MemoryError, SchemaError
from companion.privacy import DATA_CLASSES, rank

__all__ = [
    "CATEGORIES",
    "CONFIRMATION_STATUSES",
    "CRYPTO_STATUS_FILE_DEK",
    "CRYPTO_STATUS_KEYSTORE_UNVERIFIED",
    "MEMORY_SCHEMA_VERSION",
    "PLUGINS",
    "PLUGIN_TO_CATEGORY",
    "SENSITIVITIES",
    "STATES",
    "TAINTS",
    "WRITER_KINDS",
    "MemoryRecord",
    "canonical_body_hash",
    "map_classification",
    "new_ulid",
    "plugin_store_scope",
    "read_time_confidence",
]

MEMORY_SCHEMA_VERSION = 1

#: Plugin packs. Distinct from §14 ``category``. Models consume these; they
#: do not own the store.
PLUGINS = (
    "working",
    "conversation",
    "preference",
    "task",
    "system",
    "episodic",
    "semantic",
    "companion",
    "application",
    "routines",
    "project",
)

#: §14.3 categories. One ontology; plugins map onto it and do not fork it.
CATEGORIES = (
    "episodic",
    "semantic",
    "procedural",
    "task_state",
    "system",
    "performance",
)

PLUGIN_TO_CATEGORY: Mapping[str, str] = {
    "working": "task_state",
    "conversation": "episodic",
    "preference": "procedural",
    "task": "task_state",
    "system": "system",
    "episodic": "episodic",
    "semantic": "semantic",
    "companion": "procedural",
    "application": "task_state",
    "routines": "procedural",
    "project": "semantic",
}

#: Which memory-policy scope a plugin write needs. Working is always on;
#: conversation/task wait on session; the rest wait on durable. System is
#: read-only to this service regardless.
PLUGIN_STORE_SCOPE: Mapping[str, str] = {
    "working": "working",
    "conversation": "session",
    "task": "session",
    "preference": "durable",
    "system": "durable",
    "episodic": "durable",
    "semantic": "durable",
    "companion": "durable",
    "application": "durable",
    "routines": "durable",
    "project": "durable",
}

STATES = ("active", "proposed", "superseded", "tombstoned", "shredded")
WRITER_KINDS = ("user", "model", "tool", "agent", "system")
SOURCE_KINDS = ("conversation", "file", "tool_output", "web", "mcp", "import")
AUTHORITY_SOURCES = ("user_expression", "approved_plan", "system_policy", "none")
TAINTS = ("third_party_content", "model_generated", "imported_unverified")
CONFIRMATION_STATUSES = ("user_confirmed", "unconfirmed", "model_proposed")
SCOPE_KINDS = ("task", "plan", "workspace", "user")
#: §14.3 sensitivity. Companion classes collapse into these three.
SENSITIVITIES = ("public", "personal", "secret")

CRYPTO_STATUS_FILE_DEK = "file-dek-stdlib"
CRYPTO_STATUS_KEYSTORE_UNVERIFIED = "os-keystore-wrap NOT VERIFIED"

#: Crockford Base32, ULID alphabet.
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_ulid(*, timestamp_ms: int, randomness: bytes | None = None) -> str:
    """A 26-character ULID. Time-sortable; no extra dependency."""
    if timestamp_ms < 0 or timestamp_ms >= 2**48:
        raise MemoryError("ULID timestamp is out of range")
    entropy = randomness if randomness is not None else secrets.token_bytes(10)
    if len(entropy) != 10:
        raise MemoryError("ULID randomness must be 10 bytes")
    value = (int(timestamp_ms) << 80) | int.from_bytes(entropy, "big")
    chars = ["0"] * 26
    for index in range(25, -1, -1):
        chars[index] = _CROCKFORD[value & 31]
        value >>= 5
    return "".join(chars)


def canonical_body_hash(text: str) -> str:
    """SHA-256 of the canonical UTF-8 body. Dedup key and content address."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def map_classification(classification: str) -> str:
    """Collapse companion data classes onto §14.3 sensitivity."""
    if classification not in DATA_CLASSES:
        raise MemoryError(f"unknown classification: {classification!r}")
    if rank(classification) >= rank("sensitive"):
        return "secret"
    if rank(classification) >= rank("personal"):
        return "personal"
    return "public"


def plugin_store_scope(plugin: str) -> str:
    if plugin not in PLUGIN_STORE_SCOPE:
        raise MemoryError(f"unknown memory plugin: {plugin!r}")
    return PLUGIN_STORE_SCOPE[plugin]


def read_time_confidence(
    *,
    confirmation: str,
    taints: Sequence[str],
    corrections: int,
    age_seconds: float,
) -> float:
    """Deterministic confidence. Never stored; never taken from a model.

    User-confirmed, untainted, uncorrected facts start high and decay with
    age. A model proposal cannot outrank a confirmed fact by writing a number.
    """
    if confirmation == "user_confirmed":
        value = 0.85
    elif confirmation == "unconfirmed":
        value = 0.4
    else:
        value = 0.2
    if "model_generated" in taints:
        value *= 0.5
    if "third_party_content" in taints or "imported_unverified" in taints:
        value *= 0.4
    value *= 1.0 / (1.0 + max(0, int(corrections)))
    if age_seconds > 0:
        # Half-life of ~30 days. A number, not a claim about human memory.
        value *= 0.5 ** (age_seconds / (30.0 * 86400.0))
    return round(max(0.0, min(1.0, value)), 3)


@dataclass(frozen=True)
class MemoryRecord:
    """One durable fact. The file is the truth; the index only points at it."""

    id: str
    rev: int
    body_hash: str
    state: str
    valid_from: str
    observed_at: str
    recorded_at: str
    writer_kind: str
    writer_id: str
    source_kind: str
    source_ref: str
    provenance_ref: str
    authority_source: str
    scope_kind: str
    scope_id: str
    plugin: str
    category: str
    sensitivity: str
    owner: str
    confirmation: str
    body_text: str
    schema_version: int = MEMORY_SCHEMA_VERSION
    valid_to: str | None = None
    superseded_by: str | None = None
    writer_model_id: str | None = None
    writer_provider: str | None = None
    source_span: str | None = None
    grant_id: str | None = None
    taints: tuple[str, ...] = ()
    promoted_from: str | None = None
    promotion_grant_id: str | None = None
    identity_context: bool = False
    expires_at: str | None = None
    derived_from: tuple[Mapping[str, object], ...] = ()
    derivation_kind: str | None = None
    embedding_ref: str | None = None
    last_used_at: str | None = None
    use_count: int = 0
    corrections: int = 0
    sidecar_markdown: str | None = None
    body_wrapped: Mapping[str, object] | None = None
    confirmed_at: str | None = None
    confirmed_by: str | None = None
    deleted_at: str | None = None
    deleted_by: str | None = None
    deletion_reason: str | None = None
    extra: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.schema_version != MEMORY_SCHEMA_VERSION:
            raise SchemaError(
                f"memory schema {self.schema_version} is not {MEMORY_SCHEMA_VERSION}"
            )
        if self.state not in STATES:
            raise SchemaError(f"unknown memory state: {self.state!r}")
        if self.plugin not in PLUGINS:
            raise SchemaError(f"unknown memory plugin: {self.plugin!r}")
        if self.category not in CATEGORIES:
            raise SchemaError(f"unknown memory category: {self.category!r}")
        if PLUGIN_TO_CATEGORY[self.plugin] != self.category:
            raise SchemaError(
                f"plugin {self.plugin!r} maps to {PLUGIN_TO_CATEGORY[self.plugin]!r}, "
                f"not {self.category!r}"
            )
        if self.writer_kind not in WRITER_KINDS:
            raise SchemaError(f"unknown writer kind: {self.writer_kind!r}")
        if self.source_kind not in SOURCE_KINDS:
            raise SchemaError(f"unknown source kind: {self.source_kind!r}")
        if self.authority_source not in AUTHORITY_SOURCES:
            raise SchemaError(f"unknown authority source: {self.authority_source!r}")
        if self.scope_kind not in SCOPE_KINDS:
            raise SchemaError(f"unknown scope kind: {self.scope_kind!r}")
        if self.sensitivity not in SENSITIVITIES:
            raise SchemaError(f"unknown sensitivity: {self.sensitivity!r}")
        if self.confirmation not in CONFIRMATION_STATUSES:
            raise SchemaError(f"unknown confirmation: {self.confirmation!r}")
        for taint in self.taints:
            if taint not in TAINTS:
                raise SchemaError(f"unknown taint: {taint!r}")
        if not self.provenance_ref:
            raise SchemaError("a MemoryRecord without provenance is unstorable")
        if self.identity_context:
            raise SchemaError(
                "identity_context memory requires its own grant; this build "
                "refuses it rather than storing an unmarked identity fact"
            )
        if self.embedding_ref:
            raise SchemaError(
                "embedding_ref is reserved; embeddings stay disabled until "
                "brute-force cosine (P8) is real. No ANN/HNSW."
            )
        if self.writer_kind == "model":
            if "model_generated" not in self.taints:
                raise SchemaError(
                    "model-written memory must carry the model_generated taint"
                )
            if self.confirmation == "user_confirmed" and not self.confirmed_by:
                raise SchemaError(
                    "a model writer cannot mark a record user-confirmed; "
                    "a person must confirm it"
                )
            if self.plugin == "routines" and self.confirmation != "user_confirmed":
                if self.state == "active":
                    raise SchemaError(
                        "routines stay proposed until the person confirms them"
                    )

    @property
    def is_sensitive(self) -> bool:
        return self.sensitivity in ("personal", "secret")

    @property
    def is_user_confirmed(self) -> bool:
        return self.confirmation == "user_confirmed"

    def snippet(self, *, limit: int = 240) -> str:
        """Recall payload: a short excerpt, never a durable dump.

        Sensitive bodies are not copied into the snippet. The caller gets a
        labelled ref and must ``read`` locally for the body.
        """
        if self.state in ("tombstoned", "shredded"):
            return ""
        if self.is_sensitive:
            return f"{self.plugin} {self.category} ({self.sensitivity})"
        text = self.body_text.strip().replace("\n", " ")
        if len(text) <= limit:
            return text
        return text[: limit - 1].rstrip() + "…"

    def to_json(self) -> dict[str, object]:
        body: dict[str, object]
        if self.body_wrapped is not None:
            body = dict(self.body_wrapped)
        elif self.state in ("tombstoned", "shredded"):
            body = {"kind": "absent"}
        else:
            body = {"kind": "text", "text": self.body_text}
        document: dict[str, object] = {
            "schemaVersion": self.schema_version,
            "id": self.id,
            "rev": self.rev,
            "bodyHash": self.body_hash,
            "state": self.state,
            "validFrom": self.valid_from,
            "validTo": self.valid_to,
            "observedAt": self.observed_at,
            "recordedAt": self.recorded_at,
            "supersededBy": self.superseded_by,
            "writer": {
                "kind": self.writer_kind,
                "id": self.writer_id,
                "modelId": self.writer_model_id,
                "provider": self.writer_provider,
            },
            "source": {
                "kind": self.source_kind,
                "ref": self.source_ref,
                "span": self.source_span,
            },
            "grantId": self.grant_id,
            "provenanceRef": self.provenance_ref,
            "authoritySource": self.authority_source,
            "taints": list(self.taints),
            "confirmation": {
                "status": self.confirmation,
                "confirmedAt": self.confirmed_at,
                "confirmedBy": self.confirmed_by,
            },
            "scope": {"kind": self.scope_kind, "id": self.scope_id},
            "promotedFrom": self.promoted_from,
            "promotionGrantId": self.promotion_grant_id,
            "plugin": self.plugin,
            "category": self.category,
            "sensitivity": self.sensitivity,
            "identityContext": self.identity_context,
            "owner": self.owner,
            "expiresAt": self.expires_at,
            "derivedFrom": [dict(item) for item in self.derived_from],
            "derivation": (
                {"kind": self.derivation_kind} if self.derivation_kind else None
            ),
            "body": body,
            "embeddingRef": None,
            "lastUsedAt": self.last_used_at,
            "useCount": self.use_count,
            "corrections": self.corrections,
            "crypto": {
                "sensitiveBody": self.is_sensitive,
                "scheme": (
                    self.body_wrapped.get("scheme") if self.body_wrapped else None
                ),
                "fileDek": CRYPTO_STATUS_FILE_DEK if self.is_sensitive else None,
                "keystoreWrap": CRYPTO_STATUS_KEYSTORE_UNVERIFIED,
            },
            "deletedAt": self.deleted_at,
            "deletedBy": self.deleted_by,
            "deletionReason": self.deletion_reason,
        }
        return document

    @classmethod
    def from_json(cls, document: Mapping[str, Any], *, sidecar: str | None = None) -> "MemoryRecord":
        writer = document.get("writer") if isinstance(document.get("writer"), Mapping) else {}
        source = document.get("source") if isinstance(document.get("source"), Mapping) else {}
        scope = document.get("scope") if isinstance(document.get("scope"), Mapping) else {}
        confirmation = (
            document.get("confirmation")
            if isinstance(document.get("confirmation"), Mapping)
            else {}
        )
        body = document.get("body") if isinstance(document.get("body"), Mapping) else {}
        taints = tuple(str(item) for item in document.get("taints") or ())
        derived = tuple(
            item for item in document.get("derivedFrom") or () if isinstance(item, Mapping)
        )
        derivation = document.get("derivation")
        derivation_kind = None
        if isinstance(derivation, Mapping):
            kind = derivation.get("kind")
            derivation_kind = str(kind) if kind else None
        wrapped = None
        text = ""
        if str(body.get("kind") or "") == "wrapped":
            wrapped = dict(body)
        elif str(body.get("kind") or "") == "text":
            text = str(body.get("text") or "")
        confirmation_status = str(confirmation.get("status") or "unconfirmed")
        return cls(
            id=str(document.get("id") or ""),
            rev=int(document.get("rev") or 1),
            body_hash=str(document.get("bodyHash") or ""),
            state=str(document.get("state") or ""),
            schema_version=int(document.get("schemaVersion") or 0),
            valid_from=str(document.get("validFrom") or ""),
            valid_to=_optional_str(document.get("validTo")),
            observed_at=str(document.get("observedAt") or ""),
            recorded_at=str(document.get("recordedAt") or ""),
            superseded_by=_optional_str(document.get("supersededBy")),
            writer_kind=str(writer.get("kind") or ""),
            writer_id=str(writer.get("id") or ""),
            writer_model_id=_optional_str(writer.get("modelId")),
            writer_provider=_optional_str(writer.get("provider")),
            source_kind=str(source.get("kind") or ""),
            source_ref=str(source.get("ref") or ""),
            source_span=_optional_str(source.get("span")),
            grant_id=_optional_str(document.get("grantId")),
            provenance_ref=str(document.get("provenanceRef") or ""),
            authority_source=str(document.get("authoritySource") or ""),
            taints=taints,
            confirmation=confirmation_status,
            confirmed_at=_optional_str(confirmation.get("confirmedAt")),
            confirmed_by=_optional_str(confirmation.get("confirmedBy")),
            scope_kind=str(scope.get("kind") or ""),
            scope_id=str(scope.get("id") or ""),
            promoted_from=_optional_str(document.get("promotedFrom")),
            promotion_grant_id=_optional_str(document.get("promotionGrantId")),
            plugin=str(document.get("plugin") or ""),
            category=str(document.get("category") or ""),
            sensitivity=str(document.get("sensitivity") or ""),
            identity_context=bool(document.get("identityContext") or False),
            owner=str(document.get("owner") or ""),
            expires_at=_optional_str(document.get("expiresAt")),
            derived_from=derived,
            derivation_kind=derivation_kind,
            body_text=text,
            body_wrapped=wrapped,
            embedding_ref=_optional_str(document.get("embeddingRef")),
            last_used_at=_optional_str(document.get("lastUsedAt")),
            use_count=int(document.get("useCount") or 0),
            corrections=int(document.get("corrections") or 0),
            sidecar_markdown=sidecar,
            deleted_at=_optional_str(document.get("deletedAt")),
            deleted_by=_optional_str(document.get("deletedBy")),
            deletion_reason=_optional_str(document.get("deletionReason")),
        )


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None
