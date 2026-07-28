# ADR 0013 — Personality–provider separation

**Status:** Accepted · **Date:** 2026-07-24 · **Spec:** §15

## Context
C9 requires personality and provider to be orthogonal; C10 requires the character to be optional everywhere and consent surfaces de-characterized; D8 forbids third-party model names as personalities.

## Decision
**Separation by absence, not by rule.** The personality package schema contains **no fields** that reach the Policy Engine, the Capability Router, the Grant Ledger, or any disclosure surface. There is nothing to validate and nothing to bypass, because the capability does not exist.

The character is a **subscriber to state it cannot originate** — it renders Plan Engine states and has no channel to author one. Consent, permission, and destructive-action surfaces are rendered by a **reserved surface** that no personality, theme, or extension may restyle.

Model and provider names appear in exactly one place: the route indicator, in plain text, with no third-party logos. A personality may express a route *preference*, which the Router may ignore, and may never conceal a route.

## Alternatives
- *Allow personalities to carry a permission profile* — rejected: it would make personality a privilege-escalation vector and would let a charming character ask for authority, which is exactly C10's failure mode.
- *Allow personalities to influence routing* — rejected: it would make capability claims ride the personality rather than the route, which T8 in Phase 0 §19 resolves the other way.

## Consequences
Personality authoring is safe by construction, which is what makes a third-party personality format possible at all under C16.

## Risks
Users may still attribute capability to a personality regardless. Bounded by C9's route chip and moment-of-change disclosure, and by C4/C6 — misplaced trust cannot authorize what the deterministic layer forbids.

## Validation required
Schema assertion in CI: a personality package containing any permission, routing, disclosure, safety, or accessibility key fails validation.

## Phase 0 principles satisfied
C9, C10, D7, D8, D12, §8.
