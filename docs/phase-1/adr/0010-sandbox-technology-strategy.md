# ADR 0010 — Sandbox technology strategy

**Status:** Proposed — pending Phase 0 amendments A1–A3 · **Date:** 2026-07-26 · **Spec:** §12 · **Closes if ratified:** Phase 0 open question §22.1

## Context
There is no sandbox. The Bash tool hands model-generated strings to the platform shell, and the code's own header says it is safe only because every call is prompted. D4 gates everything on closing this. §20 prohibits assuming Bunny must build novel isolation to be credible.

## Decision
**Adopt audited primitives; own only the orchestration.**

- **Linux:** a declarative profile compiled to audited primitives: mount/PID/IPC/UTS/user/network namespaces, a read-only base, cgroup v2 limits, all capabilities dropped, `no_new_privs`, seccomp-bpf, the distribution-native LSM, and Landlock as a second layer. Bunny OS evaluates a pinned rootless OCI runtime as the default compiler; portable Mode A may use a directly tested bubblewrap compiler. Neither mechanism is called a sandbox without the complete effective profile.
- **macOS:** Seatbelt SBPL with writable roots and loopback-proxy-only networking.
- **Windows:** a dedicated low-privilege local account, NTFS DACLs, a Job object, and a WFP egress filter keyed to that account's SID — or WSL2 for the full Linux set.

**Four tiers** (§12.5): T0 Broker-local pure control code, T1 confined first-party effect process, T2 untrusted content with zero undeclared egress and a disposable overlay workspace, T3 hostile. The proposed Phase 2 implementation delivers T0–T2 on Linux. T3 follows only after separate gates: gVisor for compatible high-risk CPU jobs and Firecracker for disposable headless KVM jobs. GPU-bearing work remains trusted unless hardware partitioning or dedicated VFIO assignment passes its own gate.

**Three amendments to Phase 0's guarantees**, surfaced rather than quietly satisfied:
- **Guarantee 6's microVM tier is Phase 2**, not Phase 1. gVisor is a user-space-kernel compatibility tier; Firecracker is a headless KVM tier; neither is a general GPU/desktop sandbox.
- **Guarantee 1's read confinement is prototype-gated** (P3). Two comparable products abandoned read confinement deliberately because the compatibility tax was not payable.
- **Guarantee 7 demotes command parsing to a blast-radius heuristic** rather than deleting it — a sandbox permits total destruction of everything inside it, and the workspace is inside it.

**Fail-closed is the default.** A profile that cannot be satisfied fails; it never silently downgrades. A warn-and-continue fallback is exactly the pattern that produces blind approval.

## Alternatives
- *Build novel isolation* — prohibited by §20 and unaffordable at one-maintainer scale.
- *gVisor everywhere from Phase 1* — rejected on compatibility and maintenance cost; correct as one T3 target after measurement.
- *Firecracker as the universal tier* — rejected: it is headless, requires same-architecture KVM and guest memory, and does not provide a general PCI/GPU/display/USB device model.
- *A commercial sandbox service* — rejected: it would move the trust boundary off the user's machine, contradicting C7 and the whole local-first thesis.

## Consequences
Bunny acquires binary dependencies whose absence prevents starting safely (ADR 0003). At least one **privileged installation step** is unavoidable on every platform — stated constitutionally (§24.3), not buried in an installer. macOS mechanisms rest on a decade-deprecated API, and the per-OS matrix (§12.4) publishes what does not hold.

## Risks
Shared-kernel tiers have a real published escape history. Rootless namespaces remap authority but do not remove that kernel surface; seccomp and cgroups are components, not complete isolation boundaries. Risk is priced by publishing the effective profile and escape record rather than an adjective.

## Validation required
P1, P2, P3, P4, P5, and the sandbox-escape suite (§26.5).

## Phase 0 principles satisfied
C4, C5, C15, D4, D15, §13's twelve guarantees.
