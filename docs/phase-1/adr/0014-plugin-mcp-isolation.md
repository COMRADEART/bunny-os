# ADR 0014 — Plugin and MCP isolation

**Status:** Proposed — pending Phase 0 amendments A4–A5 · **Date:** 2026-07-26 · **Spec:** §19

## Context
Bunny has correct Ed25519 signing and **no isolation**: a plugin's `.mcp.json` spawns an arbitrary command that runs with the same OS privileges as Bunny itself. C16 requires signed, manifested, least-privileged, sandbox-tiered, revocable extensions.

## Decision

The replacement mappings in decisions 1 and 3 are conditional on A4 and A5 respectively. If either amendment is rejected or deferred, current C16 controls for that axis; a capability-derived profile may tighten the required publisher tier, but no proposed branch can weaken or replace Phase 0 without ratification.

1. **Isolation keys on declared capability; publisher tier modulates consent friction and default-grant generosity only.** This is a requested amendment to C16 (A4), which states publisher tiers map to sandbox tiers. Publisher reputation is precisely what attackers acquire — the confirmed malicious MCP server was published by its own legitimate maintainer and would have been legitimately signed.
2. **Signing provides attribution and tamper-evidence, not containment.** Stated explicitly so nobody later relaxes isolation *because* an extension is signed.
3. **"No egress" means no *undeclared* egress** (amendment A5). A literal no-egress community tier is useless for the dominant MCP class — GitHub, Slack, Gmail servers are network clients by definition. The manifest declares hosts; the broker's proxy enforces them.
4. **Tool descriptions are contained by capability confinement and made tamper-evident by fingerprint-and-pin**, not neutralized at the text layer. Twelve text-layer defences were broken at >90% success; a description must enter model context to be usable. Delimiters are provenance rendering, not a security boundary.
5. **Undeclared capability use is refused without a prompt** and logged as evidence of compromise. Manifest expansion on update re-triggers consent.
6. **Protocol version is negotiated, not constant.** Bunny hardcodes `2025-06-18` while the latest authorization profile verified for this evidence snapshot is `2025-11-25`; unsupported revisions fail closed rather than relying on forecast changes.

## Alternatives
- *Publisher-tier-keyed isolation* — rejected, see (1).
- *Text-layer description sanitization* — rejected: it cannot exist, and pursuing it would violate C4 by making a probabilistic control load-bearing.

## Consequences
Revocation atomically increments an authority epoch, then runs an idempotent cleanup saga across contexts, registry, jobs and extension-derived memories. The kill-switch list is signed, freshness-checked and cached; offline absence does not block the product. A deferred A4/A5 leaves the dependent extension branch disabled unless it implements current C16 literally.

## Risks
Per-extension isolation costs startup latency; an extension model where a tool call takes seconds is unusable. WASI-by-default for plugin execution keeps the common case cheap.

## Validation required
Extension-isolation prototype measuring per-invocation startup cost per tier; revocation atomicity test across all five surfaces.

## Phase 0 principles satisfied
C2, C5, C16, D4, §16.
