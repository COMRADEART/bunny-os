# ADR 0007 — Plan and task persistence

**Status:** Proposed — pending Phase 0 amendment A11 · **Date:** 2026-07-26 · **Spec:** §10.1, §25.4

## Context
The brief asks whether the plan is a DAG, a stateful workflow, an event-sourced task graph, or something else. Phase 0 §9 requires versioning, revision-as-diff, carried history, branching, resume after restart, and persistence as the unit of resumable work. There is no plan object in the product today — `ExitPlanMode` passes a plan as an opaque string and discards it, and `TodoWrite` lets the model silently rewrite the whole task list.

## Decision
**An event-sourced task graph: a DAG materialized from an append-only event log, with periodic snapshots.** The question contains a false choice — two different things are being represented. The *task structure* (steps and dependencies) is a DAG; the *plan's evolution* (proposal, approval, revision, failure, takeover, resume) is the log.

Each plan has two different identifiers: a monotonic `stream_sequence` for compare-and-append concurrency, and a canonical `graph_hash` for approval and effect binding. Conflating an event-log offset with content identity is unsafe. Diffs are derived and silent rewrites are structurally impossible. Every event carries its author and broker-issued provenance reference.

Each executable node references an immutable `ActionSpec` binding the approved graph hash, stable capability identity/version, canonical control arguments or typed constraints, canonical resource handles, destination/route constraints, data-slot bounds, limits, reversibility, and content digests. A changed control field is a new effect and new plan version even if the display label is unchanged.

**Explicitly not Temporal-style deterministic replay.** Bunny's workflow contains a rented, non-deterministic model, and memoizing model calls to make replay deterministic would replay a *stale world-model* — which directly contradicts Phase 0 §9's requirement that resumption re-validate context first. **Restore-and-revalidate, not replay** (§25.4, amendment A11).

## Alternatives
- *A stateful workflow engine* — the state-model lesson is adopted (record the intent to act before the act); the engine is not. D15 forbids the dependency in Core, and its operational surface would exceed the thing it manages.
- *A plain DAG with mutable node state* — rejected: cannot express revision-as-diff, cannot answer "what did this plan look like when I approved it?", and turns crash recovery into a reconciliation problem rather than a replay.

## Consequences
Replay is O(events) and logs grow; mitigated by snapshots. The approval unit is an **effect envelope plus an initial step list**, not a frozen display list. Graph scheduling may evolve without reapproval only while every authorized `ActionSpec` and typed constraint remains unchanged. Open-ended shell commands and unconstrained argument slots cannot be preauthorized.

## Risks
A long-running plan accumulates a log slow to replay. Bounded by snapshot frequency and measured, not assumed.

## Validation required
P28 (crash-recovery window width), and replay time at realistic plan sizes.

## Phase 0 principles satisfied
C1, C6, §9, §24 (reversibility audit — this is a one-way door).
