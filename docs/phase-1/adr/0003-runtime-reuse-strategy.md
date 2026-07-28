# ADR 0003 — Existing Bunny runtime reuse strategy, and where D15's carve-out sits

**Status:** Proposed — pending Phase 0 amendment A9 · **Date:** 2026-07-26 · **Spec:** §3.8, §12.2, §26.1

## Context
D15 retains the zero-runtime-dependency policy for Bunny Core through Phase 1, with two amendments: security-critical protocol surfaces get an external security review, and the policy explicitly does not extend to the sandbox layer or extensions. §20's prohibited assumption forbids building novel isolation to be credible.

## Decision
Adopt the reuse matrix in §3.8. The D15 changes below are **conditional on A9 ratification**:

1. **Extend D15's carve-out** to cover *any code that terminates a network protocol or parses attacker-controlled wire formats* — not only the sandbox layer and extensions. Keep zero-dependency for the agent core, tools, and CLI.
2. **Restate the policy precisely:** *no npm runtime dependencies in Core, plus pinned managed native artifacts that always have a degraded pure-TS or refuse-to-run floor.* The literal phrase is already inaccurate — `src/local/engine.ts` downloads and executes a llama.cpp release, and `src/search/findGrepBinary.ts` resolves a native binary.
3. Accept that the sandbox layer introduces **hard external binary dependencies** (`bubblewrap`, `socat`, an AppArmor profile on some distributions) whose absence prevents starting in the safe configuration.

## Alternatives
- *Keep the carve-out where Phase 0 drew it* — rejected. The hand-rolled RFC6455 implementation in Bunny Core reproduced the exact defect (missing `Origin`/`Host` validation) that the maintained ecosystem had already found and fixed as a CVE. The demonstrated cost sits **inside** the boundary Phase 0 protected, which is evidence the boundary is in the wrong place.
- *Abandon zero-dependency entirely* — rejected: it bought real portability and discipline, and the dual-runtime tri-OS CI proves the value.

## Consequences
An external security review of the WebSocket, HTTP, and OAuth surfaces becomes a Stage 0 item rather than an eventual one. Public claims must stop saying "zero dependencies" unqualified (R-4).

## Risks
An adopted binary regresses or is absent. Mitigated by pinning tested version ranges in `bunny doctor` output and testing against distro LTS packages.

## Validation required
External security review of the protocol-termination surfaces — D15's own stated amendment — before Mode B ships.

## Phase 0 principles satisfied
D15, C15, C4, §19 R6.
