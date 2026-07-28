# ADR 0019 — Observability and audit retention

**Status:** Accepted · **Date:** 2026-07-24 · **Spec:** §29, §23.3

## Context
C14 requires money and data flows to be always visible. §10 requires an audit trail that is the user's, local, readable, and **never editable by the agent layer**. Phase 0 also forbids exposing hidden model reasoning. A repository-wide search for "audit" today returns only self-check test names — there is no audit log.

## Decision
**Four separate streams** with different audiences, retention, and redaction: user-visible activity, security audit, developer diagnostics, and transient telemetry.

**The security audit log is append-only and hash-chained, written by the broker** — a process the agent layer cannot address. That is what makes "never editable by the agent layer" a structural property rather than a policy.

**Retention:** audit defaults to indefinite and is user-configurable with a floor; developer diagnostics are local, redacted, and opt-in; telemetry is **off by default and the product is fully functional without it**. Diagnostic bundles are generated locally and show their full contents before anything is shared.

**User-facing explanation is structured evidence, not narration** — which memories were retrieved and their provenance, which route was chosen and its six other duty fields, which grant authorized an action, what verification checked. **Hidden model reasoning is never exposed in any stream.**

**Deterministic replay where it is honest:** the plan event log replays exactly and provider interactions replay from the existing golden SSE fixtures. **Model calls are not memoized for replay** — that would resurrect a stale world-model (ADR 0007). Replay reconstructs *what happened*, not *what would happen now*, and says so wherever it is offered.

## Alternatives
- *A single unified log* — rejected: it would either over-expose diagnostics to users or under-retain security events, and it would make redaction policy uniform where it must not be.
- *Agent-writable audit* — rejected: it is the property the whole trust model depends on not having.

## Consequences
Egress-ledger completeness is achievable by construction because all egress converges on the broker's proxy (§12), rather than depending on diligent instrumentation at every call site.

## Risks
Indefinite audit retention grows unbounded and itself contains sensitive resource identifiers. Mitigated by the same sensitivity classification and crypto-shredding the Memory Service uses.

## Validation required
Egress-ledger reconciliation test — every outbound byte maps to a grant, a destination, and a plan step, with no gaps.

## Phase 0 principles satisfied
C14, C7, §10 (audit history), §23 (the answerable privacy question).
