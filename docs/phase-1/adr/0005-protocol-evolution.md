# ADR 0005 — App-server protocol evolution and the ACP posture

**Status:** Accepted · **Date:** 2026-07-24 · **Spec:** §16.8, §23.2

## Context
The existing protocol is a genuine asset: a declarative method table that generates a JSON Schema, with a CI drift guard that fails the build if the two diverge. But it carries no plan, no task list, no grant state, and no reversibility surface — so Phase 0's authoritative interface does not exist on the wire (§16.1). Meanwhile the Agent Client Protocol has standardized much of this layer, with meaningful adoption and a registry. C15 directs Bunny to rent standards; Phase 0 names only MCP.

## Decision
**Adopt ACP's shapes, ship an ACP compatibility profile, and keep Bunny's protocol as the documented superset.** Adopt the streaming update envelope, the tool-call representation, and the plan-entry vocabulary.

**Deviate deliberately and document the deviation on plan updates.** ACP mandates full replacement of the plan entry list, which destroys node identity and would break focus persistence and incremental accessibility updates (§16.3). Bunny requires stable node IDs and incremental deltas.

Bunny-specific surfaces — the grant model, reversibility class, memory operations, routing disclosure, spend — go in ACP's designated extension mechanism. Add `plan/*`, `grant/*`, `intent/*`, `memory/*`, `tsm/*`, `route/*`, and `budget/*`, plus a per-thread monotonic sequence persisted in the transcript rather than a per-connection counter.

## Alternatives
- *Adopt ACP wholesale* — rejected: it cannot express the C2 grant model, and its plan semantics are incomplete for Bunny's authoritative TSM projection and approval contracts.
- *Ignore ACP and continue bespoke* — rejected: a live C15 conflict that grows more expensive every month, and interoperability is a real user benefit.

## Consequences
Third-party ACP clients can drive Bunny for the subset ACP expresses. The schema drift guard extends to every new schema introduced.

## Risks
ACP evolves in a direction incompatible with stable node IDs. Mitigated by the superset posture — Bunny's own protocol remains authoritative and the compatibility profile is an adapter.

## Validation required
P21 — a real third-party ACP client drives a full Bunny turn including plan display and permission approval, with the set of Bunny concepts ACP cannot express bounded at ≤8 and confined to permissions, memory, routing, and spend.

## Phase 0 principles satisfied
C15 (rent standards), C1, C13.
