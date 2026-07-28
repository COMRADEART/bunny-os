# ADR 0012 — Model-router strategy

**Status:** Accepted · **Date:** 2026-07-24 · **Spec:** §13 · **Closes:** Phase 0 open question §22.5

## Context
There is no router. `failoverChain` concatenates providers with **zero privacy classification**, so a local-first user with a configured failover silently escalates private context to a cloud provider — a live §11 and C12 violation shipping today.

## Decision
A **Capability Router** above the unchanged provider seam, with four properties:

1. **Locality is a security boundary.** Every provider is classified loopback / private-network / hosted at config load. Failover is posture-aware and **rejects a cross-boundary candidate loudly rather than filtering it silently** — the turn halts and surfaces a consent prompt carrying the seven disclosure duties.
2. **Escalation is gated on deterministic observables**, ranked: plan step count, tool-call schema failure, repeated no-progress turns, context exceeding the model's true `n_ctx` read from `/props`, a missing declared capability, provider health.
3. **The model's self-reported confidence is explicitly excluded.** Instruct models in the 3–9B range report >90% confidence regardless of correctness, and the mechanism is answer-independent — the signal is not weak, it is absent. This is C4 restated as an engineering constraint.
4. **Machines are tiered by usable memory × *measured* achieved throughput**, not by memory bandwidth (not portably readable) and not by TOPS.

## Alternatives
- *Confidence-based routing* — rejected on the evidence above. It is the obvious design and it does not work.
- *A hosted routing service* — rejected: it would move a privacy decision off the machine.
- *Static config-only selection (today's behaviour)* — rejected: it is the violation.

## Consequences
Every routing decision emits an explanation record reconstructible after the fact. Because cost declarations are machine-readable and forecasts reconcile against actuals, **D17's no-hidden-markup rule becomes computable rather than promissory.**

## Risks
An over-eager escalation threshold leaks context that could have stayed local; an under-eager one wastes the user's time on work that gets redone. Both are measured by the §13.8 eval rather than tuned by intuition.

## Validation required
P13 (zero cross-boundary egress across the matrix, asserted at the provider seam, including under bypass), P12 (step count achieves ≥0.75 recall while escalating <50% of tasks).

## Phase 0 principles satisfied
C9, C11, C12, C14, D17, §11.
