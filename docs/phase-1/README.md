# Bunny OS — Phase 1

**Architecture and Technical Specification** · Version 1.1 · 2026-07-26
**Status: provisional** — pending the fifteen Phase 0 amendments requested in §31.1, the four substantively unmet Phase 0 entry criteria recorded in §5.4, and the prototype/conformance gates. The adversarial review has run; its record is [`ADVERSARIAL_REVIEW.md`](ADVERSARIAL_REVIEW.md) and its verdicts are carried into Appendix B. **Exit criterion 17 passes, but criteria 19 and 20 fail:** the remediations the review prompted are written down, not implemented, prototyped, or independently re-reviewed.

Phase 0 (`../../BUNNY_OS_PHASE_0.md`) is the product constitution and **outranks everything here.** Where this specification conflicts with it, the conflict is declared in §2.4 or raised as an amendment request in §31.1 — never resolved silently.

## Contents

| Path | What it is |
|---|---|
| [`BUNNY_OS_PHASE_1.md`](BUNNY_OS_PHASE_1.md) | The specification. §§1–35, Appendix A (thirteen interface contracts), Appendix B (verification report). |
| [`PHASE_2_BACKLOG.md`](PHASE_2_BACKLOG.md) | Safe Linux CLI Preview backlog plus the post-preview Stage A–H roadmap. |
| [`TRACEABILITY_MATRIX.md`](TRACEABILITY_MATRIX.md) | Accountable C1–C16 / D1–D17 ledger with owner, evidence, backlog, and amendment status. |
| [`ACCESSIBILITY_CONFORMANCE_MATRIX.md`](ACCESSIBILITY_CONFORMANCE_MATRIX.md) | WCAG 2.2 A/AA, conformance, EN 301 549, support-tuple, complete-process, and evidence matrix. All applicable rows currently unverified. |
| [`SOURCES.md`](SOURCES.md) | Dated primary-source claim map, qualifications, and evidence limitations. |
| [`ADVERSARIAL_REVIEW.md`](ADVERSARIAL_REVIEW.md) | Independent review lenses, findings, dispositions, and residual risks. |
| [`verify.ps1`](verify.ps1) | Reproducible structural checks for sections, contracts, amendments, prototypes, trace rows, ADR fields/statuses, diagrams/state-block presence, WCAG rows, links, and stale identifiers. |
| [`adr/`](adr/) | Twenty architecture decision records, one file each. |
| [`diagrams/`](diagrams/) | Fifteen Mermaid diagrams covering the ten required artifacts. All fifteen, plus the five inline state machines extracted from §9.6 and §10.3–10.6, re-rendered without error under `mermaid-cli` 11.12.0 against this tree on 2026-07-28. |

## Start here

- **If you are implementing:** §33, then `PHASE_2_BACKLOG.md`. Begin with **Stage 0**, then only the bounded Safe Linux CLI Preview. Stages A–H are a multi-release roadmap, not one Phase 2 commitment.
- **If you are reviewing the security model:** §11 (policy and permissions), §12 (sandbox), §26 (threat model). The ten structural invariants are §26.3.
- **If you are checking constitutional compliance:** §2 (traceability and the conflict register), then §31.1 (requested amendments).
- **If you are deciding whether to trust this:** [`ADVERSARIAL_REVIEW.md`](ADVERSARIAL_REVIEW.md) — §2 for the exit-criteria verdict, §6 for the reduced slice it recommends instead of the full architecture.
- **If you want the short version:** §1, then §35.

## What this document found

Four things worth surfacing before anyone reads 58,000 words.

**Twelve live security and authority defects** are catalogued in the current codebase, beyond the three Phase 0 already named; nine were reconfirmed directly against the current private-repository head during this work. The most severe (§3.6a V1): project instruction files are folded into the system prompt **without a workspace-trust check**, so cloning a hostile repository writes attacker-controlled text into the highest-trust region of the model context with no prompt. §35 recommends closing or explicitly accepting all twelve before any Phase 2 architecture work begins.

**The authoritative interface does not exist on the wire.** Phase 0 designates the ordered task list as authoritative, but the app-server protocol carries no plan, no task list, and no grant state — so plan-level oversight is currently *less* structured over the protocol than in the terminal (§16.1).

**`failoverChain` has no privacy classification**, so a workspace configured local-first silently escalates private context to a hosted provider on local failure (§13.1).

**The full architecture is not a responsible next implementation commitment for one maintainer.** That is the adversarial review's own conclusion, not a hedge added afterwards. Its §6 defines the smallest slice that tests the thesis without producing a half-secure platform — a Linux x86-64 reference application on one Fedora host tuple, not Bunny OS — and six gates that must close before scope expands. §33 and Stage 0 of the backlog are written to that boundary.

## Diagrams

Render command (when the pinned tool is available):

```
npx @mermaid-js/mermaid-cli -i diagrams/01-system-context.mmd -o out.svg
```

| Required artifact | File |
|---|---|
| System context | `01-system-context.mmd` |
| Container / service | `02-container-services.mmd` |
| Deployment (six) | `03`–`08` |
| Trust boundaries | `09-trust-boundaries.mmd` |
| Intent → execution | `10-intent-to-execution.mmd` |
| Permission sequence | `11-permission-sequence.mmd` |
| Local → cloud escalation | `12-local-to-cloud-escalation.mmd` |
| Failure and recovery | `13-failure-recovery.mmd` |
| Memory retrieval and update | `14-memory-retrieval-update.mmd` |
| Plugin execution | `15-plugin-execution.mmd` |

The five required state machines are inline Mermaid in §9.6 and §10.3–10.6.

## Conventions

**Evidence discipline** (§"How to read"): repository facts cite a path and are marked **[verified here]** or **[research]**; external claims carry a source; unverifiable claims are marked **[unverified]** and are never load-bearing. All schemas and pseudocode are **illustrative**, not production code.

**Do not use the term "Virtual Brain."** Phase 0 D5 retired it as both a term and a claim. The component is the **Memory Service** (§14).
