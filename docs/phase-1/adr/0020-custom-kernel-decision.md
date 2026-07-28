# ADR 0020 — Custom kernel decision

**Status:** **Ratified by Phase 0 — closed.** Recorded here for completeness and to prevent re-litigation. · **Date:** 2026-07-24 · **Spec:** §2.4 conflict C-2, §20

## Context
The Phase 1 brief lists "custom kernel decision" among the required ADRs. **Phase 0 §18 already evaluated and permanently retired both options**, and D2 adopted that conclusion as a constitutional decision. §20 lists "new kernel; kernel fork" as out of scope, and prohibited assumption 4 forbids assuming Bunny must build novel low-level technology to be credible.

This ADR therefore records a closed decision. It does not reopen one.

## Decision
**No kernel fork, ever. No new kernel, ever. Configuration only.**

Bunny OS uses an upstream kernel supplied by its base image, configured but never patched, never forked, and never carried as a tree.

## Alternatives
Both were evaluated in Phase 0 and rejected:

- *A customized upstream kernel* — the published record shows out-of-tree kernels producing multi-month lags and years of investment to un-fork. Bunny has **zero kernel-level differentiation to express**: nothing in the intent model, the permission gate, the memory system, the provider seam, or the trust UX touches kernel design.
- *A new kernel from scratch* — retired by Phase 0 as a prohibited assumption. It exists in the option space only to be formally closed, and it now is.

## Consequences
Every isolation mechanism Bunny uses must be one an upstream kernel already provides — namespaces, cgroups, seccomp, Landlock (ADR 0010). This is a constraint on the sandbox design and it is the correct one: §20's prohibited assumption 4 says Bunny does not need novel isolation technology to be credible, and the sandbox architecture is built entirely from adopted primitives.

Kernel modules become the one genuine hard limit in the install ladder (§20.6) — they must be built against the running kernel, so they can only be handled by an image rebuild.

## Risks
None to the decision. The residual risk is drift: a future contributor proposing a kernel patch to solve an isolation problem. Mitigated by this ADR existing and by §20's scope boundaries being cited in the Phase 1 planning doc, so such a proposal is returned rather than debated.

## Validation required
None. This is a closed constitutional decision, not a hypothesis.

## Phase 0 principles satisfied
D2, C15 (rent the kernel), Phase 0 §18 options 6 and 7, Phase 0 §20 scope boundaries and prohibited assumption 4.
