# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Memory Service: files in, snippets out, never a silent online dump.

Write path is grant-shaped even without a Grant Ledger in this build: the
person's :class:`companion.memory_boundary.MemoryPolicy` is the gate, system
category is read-only, and a model cannot confirm its own inference.

Recall returns refs plus snippets under a taint envelope. The
``conversation-summary`` context slot stays empty — this module will not invent
one. A future caller may pass :meth:`recall_envelope_for_local_context` into
local generation only; remote generate still refuses durable keys.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping, Sequence

from companion.clock import Clock, SystemClock, iso8601
from companion.errors import MemoryError
from companion.memory.crypto import (
    dek_path,
    generate_dek,
    open_body,
    seal_body,
    shred_dek,
    write_dek,
)
from companion.memory.files import (
    iter_record_files,
    read_json,
    record_path,
    remove_record_files,
    write_record,
)
from companion.memory.index import INDEX_FILE_NAME, MemoryIndex
from companion.memory.record import (
    CRYPTO_STATUS_KEYSTORE_UNVERIFIED,
    PLUGIN_TO_CATEGORY,
    MemoryRecord,
    canonical_body_hash,
    map_classification,
    new_ulid,
    plugin_store_scope,
    read_time_confidence,
)
from companion.memory_boundary import (
    MemoryDecision,
    MemoryPolicy,
    authorize_cloud_context,
    authorize_remote_generate,
    may_store,
)

__all__ = [
    "MAX_K",
    "MAX_READS_PER_TURN",
    "MAX_RECALL_BYTES",
    "MAX_SNIPPET_BYTES",
    "MemoryService",
    "RecallHit",
    "RecallResult",
    "memory_root",
]

MAX_K = 8
MAX_SNIPPET_BYTES = 512
MAX_RECALL_BYTES = 4096
MAX_READS_PER_TURN = 4

#: conversation-summary stays unwired. Do not invent a summary to fill it.
CONVERSATION_SUMMARY_UNWIRED = True


def memory_root(companion_root: Path) -> Path:
    return Path(companion_root) / "memory"


@dataclass(frozen=True)
class RecallHit:
    """One retrieval result: a pointer, not a durable body."""

    ref: str
    plugin: str
    category: str
    snippet: str
    sensitivity: str
    confirmation: str
    taints: tuple[str, ...]
    confidence: float
    recorded_at: str
    file_path: str
    envelope: str

    def to_json(self) -> dict[str, object]:
        return {
            "ref": self.ref,
            "plugin": self.plugin,
            "category": self.category,
            "snippet": self.snippet,
            "sensitivity": self.sensitivity,
            "confirmation": self.confirmation,
            "taints": list(self.taints),
            "confidence": self.confidence,
            "recordedAt": self.recorded_at,
            "envelope": self.envelope,
        }


@dataclass(frozen=True)
class RecallResult:
    """Two-channel retrieval: first-party hits vs tainted hits, never mixed."""

    first_party: tuple[RecallHit, ...]
    tainted: tuple[RecallHit, ...]
    used_index: bool
    fts5: bool
    fallback: str | None
    query: str

    def to_json(self) -> dict[str, object]:
        return {
            "query": self.query,
            "firstParty": [item.to_json() for item in self.first_party],
            "tainted": [item.to_json() for item in self.tainted],
            "usedIndex": self.used_index,
            "fts5": self.fts5,
            "fallback": self.fallback,
            "conversationSummary": "",
            "conversationSummaryUnwired": CONVERSATION_SUMMARY_UNWIRED,
        }

    def snippets_payload(self) -> dict[str, object]:
        """What a model may see locally: refs + snippets, not bodies."""
        return {
            "firstParty": [
                {"ref": item.ref, "snippet": item.snippet, "plugin": item.plugin}
                for item in self.first_party
            ],
            "tainted": [
                {
                    "ref": item.ref,
                    "snippet": item.snippet,
                    "plugin": item.plugin,
                    "taints": list(item.taints),
                    "envelope": "third_party_or_unverified",
                }
                for item in self.tainted
            ],
        }


class MemoryService:
    """Custodian of the file store. Providers never are."""

    def __init__(
        self,
        root: Path,
        *,
        policy: MemoryPolicy | None = None,
        clock: Clock | None = None,
        ids: Callable[[int], str] | None = None,
    ) -> None:
        self.root = Path(root)
        self.records_root = self.root / "records"
        self.keys_root = self.root / "keys"
        self.index = MemoryIndex(self.root / "index" / INDEX_FILE_NAME)
        self.policy = policy or MemoryPolicy()
        self.clock = clock or SystemClock()
        self._ids = ids
        self.index.open()

    def insert(
        self,
        *,
        body: str,
        plugin: str,
        owner: str,
        scope_kind: str,
        scope_id: str,
        classification: str,
        writer_kind: str,
        writer_id: str,
        source_kind: str,
        source_ref: str,
        provenance_ref: str,
        authority_source: str,
        grant_id: str | None = None,
        taints: Sequence[str] = (),
        expires_at: str | None = None,
        sidecar_markdown: str | None = None,
        derived_from: Sequence[Mapping[str, object]] = (),
        derivation_kind: str | None = None,
        writer_model_id: str | None = None,
        source_span: str | None = None,
        now: str | None = None,
        record_id: str | None = None,
    ) -> MemoryRecord:
        if plugin == "system":
            raise MemoryError(
                "system-category memory is read-only to the Memory Service"
            )
        store_scope = plugin_store_scope(plugin)
        decision = may_store(classification, store_scope, self.policy)
        if not decision.allowed:
            raise MemoryError(decision.reason)
        if writer_kind != "user" and not grant_id and writer_kind != "system":
            raise MemoryError(
                "non-user writers need a grant_id; this write has none"
            )
        if derivation_kind and not derived_from:
            raise MemoryError(
                "a derived record that cannot name its inputs must not be written"
            )
        timestamp = now or iso8601(self.clock.wall())
        text = body if isinstance(body, str) else str(body)
        body_hash = canonical_body_hash(text)
        existing = self._find_duplicate(body_hash, scope_kind, scope_id, plugin)
        if existing is not None:
            return existing
        category = PLUGIN_TO_CATEGORY[plugin]
        sensitivity = map_classification(classification)
        writer_taints = tuple(taints)
        confirmation = "user_confirmed"
        state = "active"
        if writer_kind == "model":
            writer_taints = tuple(dict.fromkeys((*writer_taints, "model_generated")))
            confirmation = "model_proposed"
            state = "proposed"
        elif writer_kind != "user":
            confirmation = "unconfirmed"
        if plugin == "routines" and confirmation != "user_confirmed":
            state = "proposed"
        record_id = record_id or self._next_id()
        wrapped = None
        stored_text = text
        if sensitivity in ("personal", "secret"):
            dek = generate_dek()
            write_dek(self.keys_root, record_id, dek)
            wrapped = seal_body(text.encode("utf-8"), dek)
            stored_text = ""
        record = MemoryRecord(
            id=record_id,
            rev=1,
            body_hash=body_hash,
            state=state,
            valid_from=timestamp,
            observed_at=timestamp,
            recorded_at=timestamp,
            writer_kind=writer_kind,
            writer_id=writer_id,
            writer_model_id=writer_model_id,
            source_kind=source_kind,
            source_ref=source_ref,
            source_span=source_span,
            grant_id=grant_id,
            provenance_ref=provenance_ref,
            authority_source=authority_source,
            taints=writer_taints,
            confirmation=confirmation,
            confirmed_at=timestamp if confirmation == "user_confirmed" else None,
            confirmed_by=writer_id if confirmation == "user_confirmed" else None,
            scope_kind=scope_kind,
            scope_id=scope_id,
            plugin=plugin,
            category=category,
            sensitivity=sensitivity,
            owner=owner,
            expires_at=expires_at,
            derived_from=tuple(derived_from),
            derivation_kind=derivation_kind,
            body_text=stored_text if wrapped is None else text,
            body_wrapped=wrapped,
            sidecar_markdown=sidecar_markdown,
        )
        # Persist wrapped body without leaving plaintext in the JSON for
        # personal/secret records. The in-memory object still has body_text
        # so the caller who just wrote it can read it back this turn.
        persist = record
        if wrapped is not None:
            persist = replace(record, body_text="")
        path = write_record(self.records_root, persist)
        self.index.upsert(persist, path)
        return record

    def confirm(self, record_id: str, *, by: str) -> MemoryRecord:
        """Person confirms a proposed/inferred fact. Models cannot call this."""
        record = self.read(record_id, decrypt=True)
        timestamp = iso8601(self.clock.wall())
        confirmed = replace(
            record,
            state="active",
            confirmation="user_confirmed",
            confirmed_at=timestamp,
            confirmed_by=by,
            rev=record.rev + 1,
            recorded_at=timestamp,
        )
        persist = confirmed if confirmed.body_wrapped is None else replace(confirmed, body_text="")
        path = write_record(self.records_root, persist)
        self.index.upsert(persist, path)
        return confirmed

    def recall(
        self,
        query: str = "",
        *,
        plugin: str | None = None,
        category: str | None = None,
        scope_kind: str | None = None,
        scope_id: str | None = None,
        k: int = MAX_K,
        include_proposed: bool = False,
    ) -> RecallResult:
        """Refs + snippets. Scope is taken from the caller, not from the model.

        ``include_proposed`` is for the person reviewing staging. Default recall
        used by a model path must leave it false so inference is not treated as
        a confirmed fact.
        """
        limit = max(1, min(int(k), MAX_K))
        used_index = False
        fallback = None
        rows: tuple[dict[str, object], ...] = ()
        if self.index.available:
            try:
                rows = self.index.search(
                    text=query,
                    plugin=plugin,
                    category=category,
                    scope_kind=scope_kind,
                    scope_id=scope_id,
                    state="active",
                    limit=limit * 4,
                )
                used_index = True
            except MemoryError as exc:
                fallback = f"index search failed: {exc}"
        if not used_index:
            fallback = fallback or self.index.failure or "file scan"
            rows = self._file_scan(
                query=query,
                plugin=plugin,
                category=category,
                scope_kind=scope_kind,
                scope_id=scope_id,
                limit=limit * 4,
            )
        hits: list[RecallHit] = []
        now = self.clock.wall()
        seen: set[str] = set()
        for row in rows:
            record_id = str(row.get("id") or "")
            if not record_id or record_id in seen:
                continue
            try:
                record = self._load(record_id, decrypt=False)
            except MemoryError:
                continue
            if record.state != "active":
                continue
            if record.expires_at and record.expires_at < iso8601(now):
                continue
            if not include_proposed and record.confirmation != "user_confirmed":
                continue
            if plugin and record.plugin != plugin:
                continue
            if category and record.category != category:
                continue
            if scope_kind and record.scope_kind != scope_kind:
                continue
            if scope_id and record.scope_id != scope_id:
                continue
            if query and not self._matches(record, query):
                continue
            seen.add(record_id)
            age = max(0.0, now - _parse_epoch(record.recorded_at))
            envelope = (
                "tainted"
                if record.taints
                else "first_party"
            )
            hits.append(
                RecallHit(
                    ref=record.id,
                    plugin=record.plugin,
                    category=record.category,
                    snippet=record.snippet(limit=min(240, MAX_SNIPPET_BYTES)),
                    sensitivity=record.sensitivity,
                    confirmation=record.confirmation,
                    taints=record.taints,
                    confidence=read_time_confidence(
                        confirmation=record.confirmation,
                        taints=record.taints,
                        corrections=record.corrections,
                        age_seconds=age,
                    ),
                    recorded_at=record.recorded_at,
                    file_path=str(record_path(self.records_root, record)),
                    envelope=envelope,
                )
            )
        hits.sort(key=lambda item: (item.confidence, item.recorded_at), reverse=True)
        first_party = tuple(item for item in hits if item.envelope == "first_party")[:limit]
        tainted = tuple(item for item in hits if item.envelope == "tainted")[:limit]
        first_party = _cap_bytes(first_party)
        tainted = _cap_bytes(tainted)
        return RecallResult(
            first_party=first_party,
            tainted=tainted,
            used_index=used_index,
            fts5=bool(used_index and self.index.fts5),
            fallback=None if used_index else (fallback or "file scan"),
            query=query,
        )

    def read(self, record_id: str, *, decrypt: bool = True) -> MemoryRecord:
        """One body, locally. Individually attributable. Never for remote."""
        return self._load(record_id, decrypt=decrypt)

    def reindex(self) -> dict[str, object]:
        loaded: list[tuple[MemoryRecord, Path]] = []
        for path in iter_record_files(self.records_root):
            try:
                record = MemoryRecord.from_json(read_json(path))
            except (MemoryError, OSError, ValueError):
                continue
            loaded.append((record, path))
        count = self.index.replace_all(loaded)
        return {
            "effect": f"REBUILT disposable index from {len(loaded)} files",
            "files": len(loaded),
            "indexed": count,
            "fts5": self.index.fts5,
            "available": self.index.available,
            "failure": self.index.failure,
            "authoritative": "files",
        }

    def forget(self, record_id: str, *, by: str, reason: str = "forget") -> dict[str, object]:
        """Erase the file, shred its DEK, cascade derived files, drop index rows."""
        record = self._load(record_id, decrypt=False)
        cascaded = list(self.index.children_of(record_id))
        if not cascaded:
            cascaded = list(self._children_from_files(record_id))
        receipts = []
        for child_id in cascaded:
            if child_id == record_id:
                continue
            receipts.append(self.forget(child_id, by=by, reason=f"cascade:{record_id}"))
        path = record_path(self.records_root, record)
        shredded = shred_dek(self.keys_root, record_id)
        timestamp = iso8601(self.clock.wall())
        tombstone = replace(
            record,
            state="shredded" if shredded or record.is_sensitive else "tombstoned",
            body_text="",
            body_wrapped=None,
            sidecar_markdown=None,
            deleted_at=timestamp,
            deleted_by=by,
            deletion_reason=reason,
            rev=record.rev + 1,
            recorded_at=timestamp,
        )
        write_record(self.records_root, tombstone)
        if path.with_suffix(".md").exists():
            remove_record_files(path.with_suffix(".md"))
        self.index.delete(record_id)
        return {
            "effect": f"ERASED memory {record_id}",
            "id": record_id,
            "dekShredded": shredded,
            "cascaded": [item["id"] for item in receipts],
            "indexCascade": "ON DELETE CASCADE",
            "keystoreWrap": CRYPTO_STATUS_KEYSTORE_UNVERIFIED,
            "couldNotErase": [],
        }

    def export_tree(self) -> Path:
        """The directory ``cp -r`` copies. Files, not the index, are the export."""
        return self.records_root

    def conversation_summary_slot(self) -> str:
        """Always empty. Invented summaries are a MemGhost channel."""
        return ""

    def recall_envelope_for_local_context(self, result: RecallResult) -> Mapping[str, object]:
        """Taint-enveloped snippets for a *local* context builder.

        Does not populate ``conversation-summary``. Remote generate must not
        be handed this mapping — :meth:`authorize_online_dump` refuses it.
        """
        return {
            "source": "memory-recall",
            "conversationSummary": "",
            "payload": result.snippets_payload(),
        }

    def authorize_online_dump(
        self,
        result: RecallResult,
        *,
        classification: str,
        remote_transfer_ceiling: str,
        remote_dispatch_granted: bool,
    ) -> MemoryDecision:
        """Persistent store NEVER dumped to online models."""
        payload = {
            "memory_records": [item.ref for item in result.first_party + result.tainted],
            "snippets": [item.snippet for item in result.first_party],
            "durable": True,
        }
        return authorize_remote_generate(
            payload,
            classification=classification,
            remote_transfer_ceiling=remote_transfer_ceiling,
            remote_dispatch_granted=remote_dispatch_granted,
            policy=self.policy,
        )

    def authorize_cloud_snippets(
        self,
        snippets: Mapping[str, object],
        *,
        classification: str,
        remote_transfer_ceiling: str,
        allowed_fields: Sequence[str] = (),
    ) -> MemoryDecision:
        """Even a minimised snippet set needs an explicit allow-list.

        Durable keys are not in the remote generate allow-list; this path
        exists so tests can prove ``authorize_cloud_context`` still refuses
        a whole-store payload.
        """
        return authorize_cloud_context(
            snippets,
            classification=classification,
            policy=self.policy,
            remote_transfer_ceiling=remote_transfer_ceiling,
            allowed_fields=allowed_fields,
        )

    def probe(self) -> dict[str, object]:
        self.index.open()
        return {
            "layer1": "files",
            "layer2": "sqlite-disposable",
            "indexAvailable": self.index.available,
            "fts5": self.index.fts5,
            "failure": self.index.failure,
            "ann": False,
            "hnsw": False,
            "vectorService": "deferred",
            "keystoreWrap": CRYPTO_STATUS_KEYSTORE_UNVERIFIED,
            "conversationSummaryUnwired": CONVERSATION_SUMMARY_UNWIRED,
        }

    def _next_id(self) -> str:
        timestamp_ms = int(self.clock.wall() * 1000)
        if self._ids is not None:
            return self._ids(timestamp_ms)
        return new_ulid(timestamp_ms=timestamp_ms)

    def _find_duplicate(
        self, body_hash: str, scope_kind: str, scope_id: str, plugin: str
    ) -> MemoryRecord | None:
        for path in iter_record_files(self.records_root):
            try:
                document = read_json(path)
            except (MemoryError, OSError, ValueError):
                continue
            if str(document.get("bodyHash") or "") != body_hash:
                continue
            if str(document.get("state") or "") in ("tombstoned", "shredded"):
                continue
            scope = document.get("scope") if isinstance(document.get("scope"), Mapping) else {}
            if (
                str(document.get("plugin") or "") == plugin
                and str(scope.get("kind") or "") == scope_kind
                and str(scope.get("id") or "") == scope_id
            ):
                return self._load(str(document.get("id") or ""), decrypt=True)
        return None

    def _load(self, record_id: str, *, decrypt: bool) -> MemoryRecord:
        matches = [
            path for path in iter_record_files(self.records_root)
            if path.stem == record_id
        ]
        if not matches:
            raise MemoryError(f"memory {record_id!r} is not in the file store")
        path = matches[0]
        sidecar = None
        md_path = path.with_suffix(".md")
        if md_path.is_file():
            sidecar = md_path.read_text(encoding="utf-8")
        record = MemoryRecord.from_json(read_json(path), sidecar=sidecar)
        if decrypt and record.body_wrapped is not None:
            dek_file = dek_path(self.keys_root, record.id)
            if not dek_file.is_file():
                if record.state in ("shredded", "tombstoned"):
                    return record
                raise MemoryError(
                    f"DEK for {record.id} is missing; body is crypto-shredded"
                )
            plaintext = open_body(dict(record.body_wrapped), dek_file.read_bytes())
            record = replace(record, body_text=plaintext.decode("utf-8"))
        return record

    def _file_scan(
        self,
        *,
        query: str,
        plugin: str | None,
        category: str | None,
        scope_kind: str | None,
        scope_id: str | None,
        limit: int,
    ) -> tuple[dict[str, object], ...]:
        rows: list[dict[str, object]] = []
        for path in iter_record_files(self.records_root):
            try:
                record = MemoryRecord.from_json(read_json(path))
            except (MemoryError, OSError, ValueError):
                continue
            if record.state != "active":
                continue
            if plugin and record.plugin != plugin:
                continue
            if category and record.category != category:
                continue
            if scope_kind and record.scope_kind != scope_kind:
                continue
            if scope_id and record.scope_id != scope_id:
                continue
            if query and not self._matches(record, query):
                continue
            rows.append({"id": record.id, "recorded_at": record.recorded_at})
            if len(rows) >= limit:
                break
        return tuple(rows)

    def _children_from_files(self, parent_id: str) -> tuple[str, ...]:
        children: list[str] = []
        for path in iter_record_files(self.records_root):
            try:
                document = read_json(path)
            except (MemoryError, OSError, ValueError):
                continue
            derived = document.get("derivedFrom") or ()
            for item in derived:
                if isinstance(item, Mapping) and str(item.get("id") or "") == parent_id:
                    children.append(str(document.get("id") or ""))
        return tuple(item for item in children if item)

    def _matches(self, record: MemoryRecord, query: str) -> bool:
        needle = query.strip().lower()
        if not needle:
            return True
        if record.id.lower() == needle or record.body_hash.lower() == needle:
            return True
        haystack = " ".join(
            (
                record.plugin,
                record.category,
                record.owner,
                record.snippet(),
                record.body_text if not record.is_sensitive else "",
            )
        ).lower()
        return needle in haystack


def _cap_bytes(hits: Sequence[RecallHit]) -> tuple[RecallHit, ...]:
    total = 0
    kept: list[RecallHit] = []
    for hit in hits:
        size = len(hit.snippet.encode("utf-8"))
        if total + size > MAX_RECALL_BYTES:
            break
        kept.append(hit)
        total += size
    return tuple(kept)


def _parse_epoch(stamp: str) -> float:
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0
