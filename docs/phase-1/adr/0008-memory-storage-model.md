# ADR 0008 — Memory storage model

**Status:** Accepted · **Date:** 2026-07-24 · **Spec:** §14 · **Closes:** Phase 0 open question §22.2

## Context
D5 retired "virtual brain"; §12 fixed nine principles. `src/memory/` is 137 lines that splice a truncated `MEMORY.md` into the system prompt — no retrieval, no provenance, no deletion. Phase 0 asked how far plain-file inspectability stretches before structured storage is needed, and D15 forbids an npm dependency in Core.

## Decision
**Two layers with an unambiguous authority order.**

**Layer 1, system of record: plain files.** One record per file, canonical documented JSON, `.md` sidecar for human-authored records. Inspectable with `cat`, searchable with the existing `ccgrep` binary, diffable, exportable with `cp -r`.

**Layer 2, derived and disposable index: SQLite** via a ~50-line owned adapter over `node:sqlite` (Node) and `bun:sqlite` (Bun). Holds FTS5, bi-temporal columns, the derivation-lineage edge table with `ON DELETE CASCADE`, and later embedding BLOBs. **Never authoritative** — `bunny memory reindex` rebuilds it from files, and a failed capability probe degrades to file scan plus `ccgrep`.

The dependency question was **resolved empirically, and the documentation was wrong in both directions**: Node v24.18.0 ships `node:sqlite` with FTS5 (contradicting every source claiming it is compiled out); Bun 1.3.14 does *not* implement `node:sqlite` (contradicting its own compatibility matrix) but `bun:sqlite` has FTS5.

**Sensitive-body boundary:** personal/secret bodies remain solely in the Memory Service and use a random per-record DEK wrapped by a scoped OS-keystore key. Transcripts, audit records, checkpoints and indexes receive opaque refs, hashes and classification only. Erasing one wrapped DEK must not erase or retain every other record for the same subject.

## Alternatives
- *SQLite as system of record* — rejected: it defeats C7's inspectability and portability, and makes erasure a database problem rather than a file problem.
- *Files only, no index* — viable and the fallback, but full-scan retrieval does not survive corpus growth, and the index pays for itself first on session search rather than on memory.
- *A bi-temporal knowledge graph* — **adopt the timestamp fields, decline the graph.** The systems that pioneered it lack formal contradiction resolution; the graph is expensive, unproven, adds per-message extraction cost, and widens the poisoning surface.

## Consequences
Erasure executes on files with the FK cascade keeping the index honest. **No ANN/HNSW index, ever** — soft-deleted vectors are reconstructible.

## Risks
A future runtime drops FTS5. Mitigated by a startup probe asserted in `--self-check` that falls back rather than crashing.

## Validation required
P6 (adapter parity across runtimes and platforms), **P7 (crypto-shredding — the schema must not freeze before it reports)**, P8 (brute-force cosine viability).

## Phase 0 principles satisfied
C7, C8, D10, §12 principles 1–9.
