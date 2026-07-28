# ADR 0004 — Service boundaries and the process model

**Status:** Accepted, amended · **Date:** 2026-07-26 · **Spec:** §7.1, §12.1

## Context
The Phase 1 brief lists 29 candidate components. Its own output standards forbid premature microservices. Quality goal 8 — maintainability under a bus factor of one — is a first-class architecture input because D13 is unmet.

## Decision
**“Bunny Core” is a logical runtime, not one address space.** Its safe configuration has three security roles: a trusted **Bunny Broker/control-plane process** with the authenticated client-decision terminator and bounded authoritative modules; a sandboxed **Agent Worker** containing the model-directed loop and no ambient authority; and separately confined **task/action and extension workers**. The Agent Worker is confined before untrusted input and cannot directly access user files, network, devices, credentials, grants, or audit storage. Provider calls are broker-side operations made for the worker; returned model output is still untrusted.

The split is mandatory rather than optional. The Broker hosts the immutable Policy Evaluator, Grant Ledger, capability issuer, egress adapters, credential boundary, execution admission controller, and Audit Service (ADR 0009, ADR 0010). Authenticated approvals terminate there and bind principal, request digest, plan sequence/hash, and exact `ActionSpec`; the Agent Worker cannot synthesize them. Consequential execution has no in-process fallback. Any root privilege is isolated in a minimal fixed-operation helper with no shell or generic command API. Without these boundaries, Phase 0 §13 guarantee 9 is not implementable.

The Execution Controller contains a stateless Effect Admission Coordinator, not another state owner. For admission and finalization it gathers owner-authorized Grant, Execution and Audit mutations and submits a fixed-member batch to the one local Durable Event Journal. The Journal commits all members/outbox rows or none; no usable capability exists before the admission receipt, and no terminal owner can advance alone. This relies on the bounded modules sharing one Broker process/store. Moving them across network services would require a new ADR and consistency model.

The Broker creates each worker's anonymous duplex socketpair/pipe before launch and passes only the child endpoint into the already-configured sandbox. It records child PID/process handle, sandbox identity, launch generation and monotonic channel counter; Unix verifies peer credentials and Windows verifies the dedicated sandbox SID/Job and pipe client. There is no reconnectable same-user worker listener. A compromised worker can propose on its own channel but cannot impersonate a user decision, another worker, or a later generation.

Module boundaries are drawn so that any of them *could* become a process boundary later without redesign. That reversibility, rather than paying for distribution now, is the property worth having.

## Alternatives
- *Full service decomposition* — rejected: the operational surface would exceed what one maintainer can carry, and no component needs independent scaling. Bunny is a local, single-user, single-machine runtime; distribution buys nothing and costs the simplicity quality goal 8 requires.
- *Monolith with no broker* — rejected: it is the current architecture, and it is precisely what makes C4 unenforceable (§12.1).

## Consequences
Two process roles minimum in the safe configuration (broker/control plane plus Agent Worker), plus action sandboxes and isolated extension processes as needed. IPC cost and process-lifecycle complexity are measured rather than assumed.

## Risks
The broker's IPC parser and launcher become attack surfaces. Mitigated by the inherited non-listening channel, child identity/generation binding, monotonic counters, a minimal versioned length-prefixed format with no dynamic dispatch, and P1 fuzz/bypass testing.

## Validation required
P1 — all bypass attempts fail with an `EPERM`/`ENOENT`-class error, each appears in the audit log, and p99 round trip is under 5 ms. P28 — crashes at every admission/finalization boundary produce no partial owner state or duplicate effect.

## Phase 0 principles satisfied
C4, C15, Phase 0 §13 guarantee 9.
