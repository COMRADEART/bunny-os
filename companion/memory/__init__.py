# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Bunny Memory Core — Python port of ADR 0008 / Phase 1 §14.

Two layers, one authority order:

* **Layer 1, system of record: plain files.** One record per file, canonical
  JSON, optional ``.md`` sidecar for human-authored records. Inspectable with
  ``cat``, searchable, diffable, exportable with ``cp -r``.
* **Layer 2, derived disposable index: SQLite.** FTS5 when the runtime probe
  says so; bi-temporal columns; derivation-lineage with ``ON DELETE CASCADE``.
  Never authoritative. ``reindex`` rebuilds from files. A failed probe degrades
  to file scan.

Models consume memory; they do not own it. Plugin packs stay distinct from
§14 categories. There is no ANN/HNSW path, and ``bunny.memory.vector`` stays
deferred.

The ``conversation-summary`` context slot is **not** filled here. Retrieval
returns a taint envelope of refs and snippets; invented summaries are refused.
"""

from __future__ import annotations

from .record import (
    CATEGORIES,
    MEMORY_SCHEMA_VERSION,
    PLUGINS,
    PLUGIN_TO_CATEGORY,
    MemoryRecord,
    new_ulid,
)
from .service import (
    MemoryService,
    RecallHit,
    RecallResult,
    memory_root,
)

__all__ = [
    "CATEGORIES",
    "MEMORY_SCHEMA_VERSION",
    "PLUGINS",
    "PLUGIN_TO_CATEGORY",
    "MemoryRecord",
    "MemoryService",
    "RecallHit",
    "RecallResult",
    "memory_root",
    "new_ulid",
]
