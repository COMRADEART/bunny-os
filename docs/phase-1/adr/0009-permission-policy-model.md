# ADR 0009 — Permission-policy model

**Status:** Accepted, amended · **Date:** 2026-07-26 · **Spec:** §11

## Context
The current gate is a well-engineered five-layer merge, but it is a **tool-name ACL**, not a permission model: no action class, no scope, no duration, no provenance, no delegation record, and no audit log anywhere in the repository. D6 names three deltas; §3.4 adds a fourth and larger one — grants have no duration or scope dimension at all.

## Decision
**A purpose-built typed evaluator (D15-compliant) over a grant algebra**, split across two components:

- **Policy Evaluator** — a *pure function* over a broker-assembled authorization context and an immutable installed policy bundle, returning a decision and reason. No surviving state, no I/O, no model call. The worker cannot supply authoritative subject, scope, resource identity, provenance, or grant state.
- **Grant Ledger** — the sole holder of durable permission requests and `(action class, scope, duration, conditions, origin-constraint, content-binding)` grants, with request lifecycle, issuance, use, expiry, disuse decay, and revocation.

The split is the correction to §3.4: one component owning both a decision function and grant lifecycle is how duration and scope get lost, which is exactly what happened.

**Three structural inversions:**
1. **Hooks and classifiers may only ever tighten a decision.** A hook returning `allow` is advisory. Today's hook types include model- and third-party-adjudicated handlers, which is a live C4 violation.
2. **The refuse list is compiled into the engine at build time** — not a settings file, because anything loadable is anything overridable.
3. **Provenance is broker-derived state, not a caller input.** It is an immutable lineage/taint graph with a separately authenticated authority edge. Third-party-derived data cannot supply control fields; crossing a boundary with such data requires an exact content-bound user authorization, and the taint remains.

Grants are **content-bound** where the action is content-bearing, closing the TOCTOU that `describe.ts:8` documents.

Every user decision names a previously displayed `PermissionRequest`, expected version and displayed digest; plan approval alone never issues a grant. Low-risk no-prompt work instead receives an exact, one-attempt policy `AuthorizationRecord` bound to operation, `ActionSpec`, effect/context digest, policy/global epochs and evaluator version. The Ledger authors the reservation/terminal mutations used by §25.4's atomic EffectAttempt batches; it exposes no standalone reserve-then-audit path.

## Alternatives
- *A declarative policy language (Cedar, OPA/Rego)* — Cedar is formally verified and genuinely better, and is unavailable to a zero-dependency TypeScript runtime. **D15 therefore buys a strictly weaker policy engine, and this ADR names that as a cost rather than pretending it is free.** Mitigation: verify the typed evaluator against a build-time Cedar harness, which uses the dependency at build time without shipping it.
- *Keeping tool-name ACLs* — rejected: it cannot express Phase 0 §10 at all.

## Consequences
"Always allow" stops being unscoped and permanent. Classes 10–15 never receive an "always" option. `bypassPermissions`, if it survives, becomes "skip the ask, never skip the deny."

## Risks
Approval fatigue is not solved by a better engine alone — the best-instrumented team in the field solved it with a classifier and a sandbox, not a richer algebra. The defensible architecture is **deterministic floor plus sandbox as the guarantee, classifier permitted only as a friction-adding layer.**

## Validation required
P14 (0% effect occurrence against an always-comply stub), P15 (≤10% capability regression), P2 (egress prompt volume under default-deny), B-12 (representative permission usability), and P28 (atomic admission/finalization under crash).

## Phase 0 principles satisfied
C2, C3, C4, D6, D16, §10.
