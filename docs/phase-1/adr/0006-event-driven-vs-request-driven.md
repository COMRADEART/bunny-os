# ADR 0006 — Event-driven vs request-driven orchestration

**Status:** Accepted, amended · **Date:** 2026-07-26 · **Spec:** §23.3, §10.1

## Context
Bunny must stream plan progress to clients, resume after restart, support concurrent plans, and keep a complete audit trail while remaining a local runtime one maintainer can reason about. Plans span threads; grants, revocations, budgets, and emergency stop span plans, so one per-thread sequence cannot be the authoritative order for all state.

## Decision
**Hybrid, split by semantics rather than by taste.** Commands are request/response with idempotency id and expected aggregate sequence. Each authoritative owner uses compare-and-append on an owner-local stream in one local durable journal. Events carry global event id, stream id, aggregate sequence, command/idempotency id, causation, correlation, broker-issued provenance, and schema version. A state change atomically appends its event and an outbox entry; idempotent projectors feed the in-memory Event Bus and Gateway.

Three security operations are fixed multi-owner Journal batches: effect admission, effect finalization and global emergency stop. Every semantic owner validates and authors its proposed event with an expected version; the Journal enforces the named member set and commits all owner events plus outbox rows or none. It cannot invent another owner's event, and there is no general cross-owner transaction surface. The model is deliberately local: one Broker process and transactional store, not distributed services.

The plan's stream sequence is its concurrency token; its canonical graph hash is its approval identity (ADR 0007). Thread/Gateway sequences are derived subscription cursors, not competing authoritative versions. There is no required global total order.

## Alternatives
- *Pure request/response* — rejected: cannot express streaming progress or resumable subscription, and would force clients to poll.
- *Pure event-driven with no commands* — rejected: an action with an effect needs a correlated response and an idempotency key, and modelling "did this work?" as an event correlation is how ordering bugs become correctness bugs.
- *An external message broker* — rejected: D15, and a local single-user runtime has nothing to distribute.

## Consequences
Backpressure is handled by coalescing projection deltas, **never by dropping owner events**. Reconnection replays a projection from its cursor. Unknown authoritative or security-relevant event types fail closed; only explicitly projection-only records may be skipped by an older reader.

## Risks
Event-log growth. Mitigated by periodic materialized snapshots with logical rather than physical truncation, following the pattern the transcript store already uses.

## Validation required
P9 (client absorbs a live turn's event rate without dropping nodes) and P28 (fault injection proves fixed batches never partially advance owners or duplicate an effect).

## Phase 0 principles satisfied
C1, C6, §7 (supervising and returning).
