# Bunny OS Phase 2 — Preview Backlog and Post-Preview Roadmap

**Derived from:** `BUNNY_OS_PHASE_1.md` §33 · **Date:** 2026-07-26

Every item carries: exactly one accountable **owner** (the §7 component or named governance role), **deps**, **priority** (P0 blocks the named roadmap stage, P1 blocks dependent work, P2 is explicitly deferred), **source** (the architectural section or ADR requiring it), **security**, **test**, and **done when**. Contributors/assurance roles may be named separately and do not dilute accountability. P0 does not mean every item belongs in one release.

The only Phase 2 release slice **proposed by this provisional plan** is the **Safe Linux CLI Preview** in §33: Fedora 44 x86-64, local stdio, one workspace/turn, `inspect-ro` plus a disposable no-network `work-overlay` and content-bound Broker apply, once grants, immutable `ActionSpec`, and atomic effect admission/finalization. The plan is not implementation authority: A1–A15 must each be resolved by the constitution owner, and the Phase 0 entry criteria plus the A13 accessibility/A14 exception paths in §33 must be closed first. A bounded non-public harness may run as a Phase 1 prototype, not a release. Every excluded transport, extension, job, background shell, failover, memory-write, graphical-client, application-control, and OS-image surface is disabled and tested unreachable. Stages A–H otherwise form a multi-release roadmap.

The repository builds in numbered stages 1–23. **This backlog continues that numbering as Stage 24 onward in commit messages**, using the letters below for planning; inventing a parallel scheme silently would be a handoff defect.

---

## Stage 0 — Repair

Present-risk reduction. This is a repair train, not a “days” estimate: V1–V7 are bounded patches, while V8–V12 contain cross-process ownership, cancellation, and routing design. Until a larger repair passes, its surface defaults off. Shipping architecture on top of a known hostile-repo-writes-the-system-prompt defect would be indefensible.

**S0-1 — Route project instruction loaders through the workspace-trust gate**
Owner: Identity & Profile Service · Contributors: Session & Transcript Service · Deps: none · **P0** · Source: §3.6a V1, invariant I1
Security: Closes the most severe defect found — cloning a hostile repository currently writes attacker-controlled text into the highest-trust region of the model context with no prompt. Exactly four modules consult `security/trust.ts`; `src/memory/claude_md.ts` is not among them.
Test: Self-check — an untrusted workspace containing `CLAUDE.md`, `RULES.md`, `SYSTEM.md`, `.cli/memory/MEMORY.md`, `.cli/skills/**`, `.cli/agents/**` contributes zero bytes to the system prompt.
Done when: I1 is green and no loader reads a project-rooted file outside the single trust-gated reader.

**S0-2 — Resolve-then-check egress, and flip the default to deny**
Owner: Sandbox Manager (proxy) · Deps: none · **P0** · Source: §3.6a V2, §12.3, invariant I5
Security: `evaluateEgress` currently allows `[::ffff:127.0.0.1]`, `127.0.0.1.nip.io`, `169.254.169.254.nip.io`, and `localtest.me` — verified empirically. The last is the cloud-metadata endpoint.
Test: The bypass corpus from §3.6a plus IPv6 and encoding variants; every case blocked. Assert the connect uses the checked address.
Done when: policy evaluates on the resolved IP at connect time, an empty allowlist denies, and I5 is green.

**S0-3 — Replace browser bearer auth with validated, paired device-key sessions**
Owner: Gateway · Deps: none · **P0** · Source: §3.6a V3, ADR 0018
Security: Currently neither header is validated; the bearer token is the only control between a hostile web page and the local agent.
Test: P16 — zero upgrades from a foreign origin, zero non-loopback `Host` accepted, zero exchange-material occurrences in URL/argv/log/output, zero nonce/transcript replay, zero unconfirmed pairing, and zero success by an unpaired same-UID sibling process over UDS/pipe.
Done when: P16 passes; the bearer-token path is removed; every transport proves possession of a paired, client-generated key; and pairing requires a 60-second, single-attempt code confirmed in a trusted local Shell/terminal.

**S0-4 — Attach protected-resource guarding to resources, not tool names**
Owner: Policy Engine · Deps: none · **P0** · Source: §3.6a V4
Security: `isProtectedConfigWrite` covers only Write/Edit/NotebookEdit while `Bash` has no path confinement, so every protected file is writable by shell. `~/.cli/plugin-keys.json` — the plugin trust root — is not protected at all, so the model can install its own publisher key.
Test: For each protected resource, attempt mutation via every write path including Bash; all forced to prompt or denied.
Done when: the guard is resource-keyed and `plugin-keys.json` is included.

**S0-5 — Gate ordering: deny and refuse before mode**
Owner: Policy Engine · Deps: none · **P0** · Source: D6, §3.4, §3.6a V5, invariants I2/I3
Security: `bypassPermissions` returns `allow` as the first statement of `check()`, before rules, hooks, plan mode, and the self-escalation guard — and separately force-trusts the workspace.
Test: Every mode × settings permutation; an explicit deny and the refuse list hold in all of them.
Done when: I2 and I3 are green, and workspace trust is a separate grant from permission mode.

**S0-6 — Interactive default becomes plan approval**
Owner: Policy Engine · Deps: S0-5 · **P0** · Source: D6, C1
Security: `acceptEdits` currently makes "permission-gated" true only for Bash.
Test: A new interactive TTY session starts in plan-approval mode; edits are not auto-approved.
Done when: D6 delta 1 is landed with a self-check.

**S0-7 — Minimal child environment (allowlist, not denylist)**
Owner: Extension Manager · Deps: none · **P1** · Source: §3.6a, C2
Security: `childSafeEnv` is a six-name denylist; anything not enumerated leaks into every spawned MCP server and hook.
Test: A spawned child observes only the explicitly declared variables.
Done when: the function constructs rather than filters.

**S0-8 — Hooks may only tighten**
Owner: Policy Engine · Deps: S0-5 · **P1** · Source: §11.8, ADR 0009
Security: Hooks may currently return `allow`, and handler types include model- and MCP-adjudicated judges — a live C4 violation.
Test: A hook returning `allow` cannot upgrade a `deny` or a `ask`.
Done when: hook `allow` is advisory only.

**S0-9 — Durable jobs cannot hold bypass**
Owner: Plan Engine · Contributors: Policy Evaluator · Deps: S0-5 · **P1** · Source: D4, invariant I9
Security: Persisting bypass mode turns one interactive mistake into unattended ambient authority and lets a later job evade the return-review gate.
Test: Job creation with a bypass mode is refused; a job cannot commit a class 6–15 effect without a return-review acknowledgment.
Done when: I9 is green.

**S0-10 — Pin and track the MCP protocol revision**
Owner: Extension Manager · Deps: none · **P1** · Source: §19.7, ADR 0014
Security: Protocol confusion can silently change capability, authentication, cancellation or error semantics; an unsupported revision must never be guessed into a permissive shape.
Test: Version negotiation covered by self-check; the hardcoded constant is removed from both sites.
Done when: the client negotiates rather than asserts a version.

**S0-11 — Documentation truth-up**
Owner: Docs and Support · Contributors: Gateway · Deps: S0-1..3 · **P2** · Source: §3.6, C-4
Security: False transport, test-count or confinement claims can cause operators to enable a surface under controls that do not exist.
Test: Documentation-link/check fixtures compare every transport and self-check count against the executable registry; golden `bunny doctor` output for each supported tuple names effective and missing controls with no generic support claim.
Done when: `docs/APP_SERVER.md` no longer claims transports are deferred that ship; the self-check count in `CHANGELOG.md` is corrected; `bunny doctor` prints the live per-OS guarantee matrix.

**S0-12 — External security review of protocol-termination surfaces**
Owner: Gateway · Assurance: independent security reviewer · Deps: S0-3 · **P1** · Source: D15's own amendment, ADR 0003
Security: Hand-rolled protocol termination is a parser, authentication, request-smuggling and cross-origin boundary; self-review cannot be its sole assurance.
Test: The independent reviewer runs foreign-Origin/Host, malformed-frame, slow/oversized-input, replay, same-UID sibling, OAuth state/redirect and secret-leak fixtures; every P0/P1 finding has a landed fix and rerun or an explicit disabled surface.
Done when: the WebSocket, HTTP, and OAuth surfaces have an attributable independent report, zero open P0/P1 findings on enabled paths, and retained rerun evidence.

**S0-13 — One fenced writer per thread across transports and processes**
Owner: Session & Transcript Service · Contributors: Gateway · Deps: none · **P0** · Source: §3.6a V8, §7.2, §10.8, §23.2–§23.3
Security: TCP and WebSocket currently create one stateful `BunAppServer` per connection. A process-wide map fixes that race only until two Bunny processes or a crash/restart contend for the same persisted thread.
Test: Race two connections and then two independent OS processes on `thread/resume` + `turn/start`; exactly one fenced owner is admitted. Crash the owner, recover a stale lease, and prove the old epoch cannot append. Five turns across processes still hit the global limit. Event IDs and per-thread sequences remain durable and unique.
Done when: transports hold connection state only; admission uses a durable compare-and-swap lease keyed by thread ID with owner, fencing epoch, heartbeat and stale-owner recovery; JSONL has one fenced writer or is replaced by a transactional journal; mixed-mode and global limits use that authority.

**S0-14 — Scope background Bash tasks to their owning session/workspace**
Owner: Execution Controller · Deps: none · **P0** · Source: §3.6a V9
Security: The module-global task map and bare predictable IDs let another session auto-read output and advance the shared cursor.
Test: Session B cannot enumerate, read, consume, or kill Session A's task; two authorized readers do not steal each other's output cursor.
Done when: task identity includes owner scope, reads are authorized, cursors are per consumer, and owner teardown has explicit semantics.

**S0-15 — Propagate emergency stop through durable-job process trees**
Owner: Execution Controller · Deps: S0-9 · **P0** · Source: §3.6a V10, C6
Security: The daemon abort signal currently stops only polling/sleep; an active headless child continues with its stored authority.
Test: Trigger emergency stop while a job has spawned a child and grandchild; both terminate within the bounded grace window and one durable cancellation event is recorded.
Done when: the runner owns a process group/Job object, propagates cancellation, force-kills after grace, and verifies no descendant survives.

**S0-16 — Make MCP cancellation honest and end-to-end**
Owner: Extension Manager · Contributors: Execution Controller · Deps: none · **P0** · Source: §3.6a V11, Appendix A.8
Security: The MCP tool wrapper ignores `ToolContext` and does not pass the turn abort signal, so a remote effect can continue after Bunny reports interruption.
Test: Interrupt a cancellable MCP mutation and observe protocol cancellation; interrupt a non-cancellable mock and observe `cancellation_pending` followed by a reconciled terminal outcome, never a false `interrupted` success.
Done when: cancellation is threaded wherever supported and unknown remote-effect state is durable and user-visible everywhere else.

**S0-17 — Put council and failover behind routing/privacy/budget policy**
Owner: Capability Router · Contributors: Budget Service · Deps: S0-5 · **P0** · Source: §3.6a V12, §13.1
Security: Council currently sends the full prompt to all configured providers by default; ordinary failover can cross locality without consent.
Test: Privacy-strict posture produces zero hosted calls. A three-provider council displays destinations and maximum cost once, then sends only after approval. A rejected destination receives zero bytes.
Done when: every multi-provider call is an explicit plan with locality, minimization, cost ceiling, per-destination consent, and egress-ledger records.

**S0-18 — Replace bare-name permanent MCP approvals with scoped grants**
Owner: Grant Ledger · Contributors: Extension Manager · Deps: S0-5 · **P0** · Source: §3.6a V7, §11.3
Security: Today's “always allow” persists only a tool name, so one approved call authorizes every future argument, workspace, destination and payload for that name.
Test: Approve one exact MCP invocation, then change each argument, resource, workspace, destination, payload digest, tool-description digest, duration and caller subject. Every widened call is denied or receives a new displayed request; expiry and revocation invalidate the original.
Done when: no MCP persistence path stores a bare tool name as authority, and every retained approval is a versioned Grant with subject, action class, resource, scope, duration, conditions, content binding and epoch.

---

## Stage A — Foundations

### Independent canonical-schema tracks (A-1a through A-1c)
The sub-items freeze independently; Memory research cannot block the preview's authorization boundary.

**A-1a — Authorization, ActionSpec, execution-intent, and AuditEvent schemas**
Owner: Grant Ledger · Contributors: Execution Controller, Audit Service · Deps: reachable Stage 0 repairs · **P0 preview** · Source: §10.2, §11.3, §22, §25.4
Security: Principal, lineage, exact effect, grant reservation, operation id and audit start must be durable before capability release.
Test: Missing or caller-authored authority fields fail schema validation; the pre-effect transaction is atomic.
Done when: P1/P14/P28 fixtures can consume the versioned schemas without an implementation-specific escape hatch.

**A-1b — Plan and owner-event schemas**
Owner: Plan Engine · Contributors: Durable Event Journal · Deps: reachable Stage 0 repairs · **P0 preview** · Source: §10.1–§10.2, §23.3
Security: Confusing aggregate sequence, graph identity, projection cursor or caller-authored provenance can authorize stale work or let a projection become a competing source of truth.
Test: `stream_sequence` and canonical `graph_hash` cannot be confused; unknown authority events force safe mode.
Done when: the preview's linear log is versioned and a later DAG can extend it without rewriting history.

**A-1c — MemoryRecord schema**
Owner: Memory Service · Deps: P6, P7 · **P0 for Stage D; excluded from preview** · Source: §14.3, ADR 0008
Security: Records written without provenance, lineage, scope, per-record keying, or deletion semantics cannot acquire them later.
Test: Schema and byte-forensics assertions from P7.
Done when: P6 and P7 report and the architecture owner explicitly accepts the one-way door.

**A-2 — Protocol versioning and schema drift guards**
Owner: Gateway · Deps: A-1a, A-1b · **P0** · Source: §23.2, ADR 0005
Security: Uncoordinated schema drift can reinterpret an authority field, drop a revocation, or make an old client issue a meaning it did not display.
Test: CI fails if any schema changes without regeneration — extending the pattern the app-server protocol already has.
Done when: every new schema is generated and drift-guarded.

**A-3 — Fork a child scope per concurrent unit**
Owner: Session & Transcript · Deps: none · **P0** · Source: §10.8, §3.7
Security: A single mutable slot per scope means a subagent cannot hold a worktree or mode independent of its parent; a scope leak across concurrent turns becomes a security bug once memory scope rides on it.
Test: A dedicated adversarial self-check running concurrent turns in different scopes, asserting zero cross-scope reads.
Done when: concurrent plans hold independent scopes.

**A-4 — Owner streams, transactional outbox, and idempotent projections**
Owner: Durable Event Journal · Contributors: domain state owners · Deps: A-2 · **P0** · Source: §23.3, ADR 0006
Security: Split writers, lost revocations and duplicate effect projections can create or preserve authority after the authoritative owner denied it.
Test: Concurrent commands with the same expected aggregate sequence admit one writer; crash between owner append and projection loses neither because the outbox is atomic; duplicate delivery is harmless. Reconnect at an arbitrary projection cursor reconstructs exactly. An unknown authorization/revocation event forces safe mode, while an unknown projection-only event may be skipped.
Done when: every authoritative event carries stream id, aggregate sequence, global event id, command/idempotency id, causation, correlation, provenance and schema version; owner event plus outbox append atomically; thread subscription positions are explicitly derived rather than authoritative.

**A-5 — Repository restructuring for the broker split**
Owner: Bunny Broker maintainer · Deps: A-1a · **P1** · Source: §7.1, ADR 0004
Security: A mechanical move that leaves an in-process effect fallback or duplicates decision ownership would defeat the later process boundary while appearing complete.
Test: Existing self-checks pass unchanged.
Done when: modules that will move into the broker are separated behind interfaces, with no behaviour change.

---

## Stage B — Authority and isolation

**B-1 — Policy Engine as a pure function**
Owner: Policy Evaluator · Deps: A-1a · **P0 preview** · Source: §11.1, ADR 0009
Security: A decision function influenced by anything other than its arguments cannot be proven to resist injection.
Test: Determinism assertion — identical inputs yield identical outputs with no I/O.
Done when: the refuse list is compiled in and unreachable from any settings path (I3).

**B-2 — Grant Ledger with (class, scope, duration)**
Owner: Grant Ledger · Deps: B-1 · **P0** · Source: §11.3, §3.4
Security: The largest single gap between constitution and code — there is no duration or scope dimension today.
Test: Concurrent requests cannot double-spend. `admitEffect` atomically commits the owner-authorized reservation/policy record, `ExecutionStarted`, `AuditStart` and outbox before capability release; `finalizeEffect` atomically advances Grant, Execution and Audit on one outcome digest. A once reservation reaches committed, released-before-effect, or indeterminate and is never reusable after a possible effect. Revocation increments the checked epoch.
Done when: no standalone reserve/mint or audit-start call can partially advance an attempt; no code path can create an unscoped permanent grant by default; the preview exposes `once` only; and classes 10–15 never offer "always".

**B-3 — Broker-derived provenance and control/data separation**
Owner: Bunny Broker · Contributors: Gateway, Plan Engine · Deps: B-1 · **P0** · Source: §11.6
Security: A worker-supplied trust bit is forgeable. Origins and taints are immutable broker-issued edges; transformations union taints, and typed effect schemas prevent untrusted data from becoming an operation, destination, path, command, credential, or scope.
Test: Forge labels at every worker API; mix user and third-party inputs through summaries and subagents; attempt to place tainted data in every control field. All fail. A boundary effect carrying tainted data requires an exact digest-bound user authorization and retains its lineage.
Done when: every consequential record references a broker-issued provenance graph and every effect schema distinguishes control fields from bounded data slots.

**B-4 — Content binding for approvals**
Owner: Grant Ledger · Deps: B-2 · **P1** · Source: §11.7, `describe.ts:8`
Security: Closes the TOCTOU where the user approves a rendered diff and the tool re-reads at execute time.
Test: Mutating the target between approval and execution invalidates the grant rather than applying it.
Done when: content-bearing grants carry a digest.

**B-5 — The broker split**
Owner: Sandbox Manager · Deps: A-5, B-1, B-2, C-3 · **P0 preview** · Source: §12.1, ADR 0004
Security: The decision everything else depends on. The split is incomplete until the Agent Worker is confined before untrusted input; deny becomes the absence of a capability.
Test: P1 — direct filesystem/network/device syscalls, forged user approvals, forged evaluator inputs, replayed decisions, and cross-worker capability transfer all fail; each attempt is audited. Measure p99 IPC without weakening confinement.
Done when: the authenticated user-decision terminator and authority live in the Broker, the Agent Worker starts confined before untrusted input, the Fedora preview has distinct `inspect-ro` and disposable `work-overlay` profiles plus content-bound Broker apply, consequential execution has no in-process fallback, and workers receive spawn-time mounts/descriptors or operation-bound channels rather than booleans. Dynamic arbitrary-FD transfer is deferred unless P1 justifies an audited native helper.

**B-6 — Operation-bound credential and egress mediation**
Owner: Sandbox Manager · Deps: B-5 · **P0** · Source: §12.6, guarantee 4
Security: A sandbox-visible sentinel is a bearer credential by another name. Credential use binds worker, operation id, scheme/host/port, method/verb, normalized path/resource, payload constraints/digest, ActionSpec, lease epoch, one-use count and expiry.
Test: P4 — authorized HTTP, Git and registry operations succeed once. Mutate every binding field, replay, transfer between workers and redirect DNS; all fail, and the real secret appears nowhere in a worker. Unsupported protocols refuse agentic authenticated mode.
Done when: tested protocol adapters or one-shot helper channels mediate supported tools, no ambient placeholder exists, and there is no generic TLS-interception claim.

**B-7 — Broader support-tuple confined-process profiles**
Owner: Sandbox Manager · Deps: B-5 · **P1 post-preview** · Source: §12.4–§12.5, ADR 0010
Security: A profile proven on one kernel/LSM tuple may silently lose namespaces, filtering or teardown on another; no tuple inherits a support claim by analogy.
Test: The full §12.3 criteria per distro/version/architecture/kernel/LSM tuple; P5 for a claimed native-Windows tuple. Ubuntu/AppArmor is independent from Fedora/SELinux.
Done when: the support-tuple matrix is published and `bunny doctor` prints the probed live result; no generic “Linux passed” claim remains.

**B-8 — Model API calls do not originate in the sandbox**
Owner: Sandbox Manager · Contributors: Capability Router · Deps: B-6 · **P0** · Source: §12.2
Security: The single most important structural decision in the sandbox track. A sandbox that can reach a model API can exfiltrate arbitrary text through a prompt.
Test: A task sandbox has no route to any model endpoint; assert at the network namespace.
Done when: provider traffic is broker traffic.

**B-9 — Execution profiles**
Owner: Sandbox Manager · Deps: B-7 · **P1** · Source: §12.7
Security: A named profile is not a boundary unless its effective mounts, devices, egress, limits and teardown are compiled and verified together; partial availability must fail closed.
Test: Each of the nine profiles enforces its declared mounts, limits, network policy, and cleanup. A profile that cannot be satisfied **fails** rather than downgrading.
Done when: all nine exist and no silent-downgrade path does.

**B-10 — Durable jobs under the T1 profile**
Owner: Plan Engine · Deps: B-7, S0-9 · **P0** · Source: D4
Security: D4 names this explicitly as the first thing brought under the rule.
Test: A job runs sandboxed with the tightest egress and produces a return-review ledger.
Done when: no headless execution path runs unsandboxed.

**B-11 — Read-confinement decision**
Owner: Sandbox Manager · Deps: B-7 · **P1** · Source: §12.2 amendment A1
Security: Over-broad base reads expose credentials/private data and can complete the lethal trifecta; an unrealistically narrow profile instead creates unsafe user pressure to disable confinement.
Test: P3 — nine real workflows with a base-mount set under 25 entries.
Done when: guarantee 1 is either confirmed as written or amended to write-confinement plus a credential deny list, **with the outcome recorded in ADR 0010.**

**B-12 — Representative permission-prompt usability and volume gate**
Owner: Policy Evaluator · Contributors: Identity and Security UX, User Research · Deps: B-1, B-2, B-4 · **P0 before any interactive product release** · Source: C3, §11.3–§11.4, §28
Security: Excess or opaque prompts train approval habituation; suppressed prompts hide authority. P2 covers egress only and cannot stand in for the whole permission experience.
Test: On a versioned first-/third-party workflow corpus, first-party non-consequential operations emit zero permission dialogs; one approved plan emits zero redundant per-step prompts inside its exact envelope; each novel consequential scope/effect prompts exactly once; 100% of prompts carry requester, broker-derived provenance, exact effect digest and blast radius; paid participants correctly identify the requested effect and denial path at the pre-registered comprehension threshold.
Done when: the corpus, prompt counts, schema results, participant protocol/threshold and all failures are retained as release evidence; any missed/duplicate/underspecified consequential prompt blocks the affected surface.

---

## Stage C — Plan and execution

**C-1 — Plan Engine: event-sourced task graph**
Owner: Plan Engine · Deps: A-1b · **P0 preview** · Source: §10.1, ADR 0007
Security: A silent plan rewrite or confusion between sequence and content identity can execute an effect the user never reviewed.
Test: A revision that is not expressible as a diff fails; compare-and-append uses `stream_sequence`, while approval and execution bind a canonical `graph_hash`.
Done when: silent rewrites are structurally impossible and sequence identity cannot be confused with content identity.

**C-2 — The five state machines**
Owner: Plan Engine · Contributors: Policy Evaluator, Execution Controller · Deps: C-1 · **P0** · Source: §9.6, §10.3–§10.6
Security: Illegal transitions can reuse consumed authority, hide pending effects, or project cancellation/success states that did not occur.
Test: Transition coverage including `ManualControl`, `AwaitingAuthorization`, `GrantInvalidated`, `RequestAutoDenied`, `AuthorizationOpen`, `GrantExhausted`, `CancelRequested`, `CancellationPending`, `CancelledNoEffect`, `Compensated`, `Indeterminate`, the A10-selected rollback outcomes, and `RecoveryPointPending`. Assert the UI cannot project “stopped” from a pending state or one Grant reservation as the Grant itself.
Done when: every state and guard is reachable and tested.

**C-3 — Immutable ActionSpecs as the enforced effect envelope**
Owner: Execution Controller · Deps: A-1a, C-1, B-3 · **P0 preview** · Source: §26.4, invariant I6
Security: A graph-node name does not constrain an attack that changes the command, target, URL, payload or destination. Each executable step binds an immutable `ActionSpec`; untrusted values can populate only typed data slots.
Test: I6/P14 — add new nodes and mutate every control-significant field of existing approved nodes, including resource identity, route, payload bound, budget and approved graph hash. Attempt open-ended shell preapproval. Every changed effect is denied or reauthorized.
Done when: the graph and ActionSpecs are content-hashed before untrusted input, broker-checked before capability release, and no unconstrained control slot is approvable.

**C-4 — Verification as a distinct state**
Owner: Execution Controller · Deps: C-2 · **P1** · Source: §10.7
Security: Treating absence of an error as success can conceal a partial or redirected consequential effect and trigger unsafe dependent work.
Test: Per action class, the declared evidence is checked. Where deterministic evidence is unavailable, the result is `unverified` — never `succeeded`.
Done when: "the tool did not error" is nowhere treated as success.

**C-5 — Recovery points and the constitution-selected reversibility classes**
Owner: Update & Recovery · Deps: C-2 · **P0** · Source: §12.10, §25.3, pending A10
Security: Snapshots live outside the sandbox's writable view, or a compromised task deletes its own undo.
Test: A step declared reversible whose recovery point could not be captured is downgraded and re-surfaced **before** execution.
Done when: if A10 is ratified, `notifiable` and `partially_reverted` are first-class outcomes; if A10 is rejected, the constitution owner's selected alternative is implemented; if deferred, operations needing the proposed outcomes remain disabled.

**C-6 — Crash-window handling**
Owner: Update & Recovery · Deps: A-1a, C-5 · **P0 preview** · Source: §25.4, pending A10–A11
Security: An `Indeterminate` non-idempotent effect must **never** auto-retry. If A10 is ratified, that includes every `notifiable` effect; otherwise the proposed class is not enabled.
Test: P28 — crash before and after every durability boundary. Assert that ActionSpec + authorization reservation + operation id + audit-start commit before capability release; a missing terminal record yields `Indeterminate`; mutation under a reused operation id fails; an exact duplicate returns the original state; provider-idempotency-key and fresh-id bypasses fail; and read-only reconciliation cannot repeat an effect. Exercise the A10/A11 branch selected by the constitution owner; deferred branches remain unreachable.
Done when: pre-effect persistence failure prevents execution, post-effect terminal-write failure triggers reconciliation rather than a false failure claim, and resumption follows the constitution-selected rule while stating its assumptions. A rejected/deferred A10 cannot silently enable `notifiable`; a deferred A11 blocks affected resume.

**C-7 — Workspace resource coordination and conflict-safe recovery**
Owner: Plan Engine · Contributors: Execution Controller · Deps: C-1, C-5 · **P0** · Source: §10.8, §12.10, §25.2
Security: Two plans writing one workspace can corrupt each other, and restoring a global snapshot can erase another plan's or the user's later changes.
Test: Run overlapping writers in separate plan overlays; conflicting canonical resources serialize or enter merge review. Change a base file outside the plan, then attempt rollback; the later write survives and the plan enters reconciliation. Non-overlapping plans still proceed concurrently.
Done when: each writing plan uses an overlay/worktree, canonical resource reservations and base hashes; commit is an explicit optimistic merge; recovery never restores across a changed base without user-visible reconciliation.

**C-8 — Content-bound base-workspace apply and restore adapter**
Owner: Update & Recovery · Contributors: Execution Controller, Grant Ledger, Audit Service · Deps: B-2, B-5, C-3, C-5 · **P0 preview** · Source: §10.2, §12.10, §25.4, Appendix A.6
Security: This is the preview's sole base-workspace write boundary. A worker-controlled path, symlink, mode, preimage, base generation, recovery point or replay could escape the overlay or apply content the user did not approve.
Test: Bind a displayed once request to an exact `WorkspaceApplyManifest`, then mutate every field and race the base after approval. Reject traversal, normalization/case collisions, mount crossings, hard links, symlinks, special files, xattrs/ACLs, submodules and `.git/**`; reject missing/stale recovery points and every preimage/base CAS mismatch. Crash before admission, before first rename, between every file and before terminal persistence; observe only proven no effect, exact verified postimages, or visible `Indeterminate`, with no automatic re-apply. Restore follows a new request and the same lifecycle.
Done when: only the Execution Controller can invoke the fixed adapter after `admitEffect`; the adapter consumes no caller path or replacement bytes outside the immutable manifest; all observations finalize through the Grant+Execution+Audit batch; and model-directed processes never mount the base or `.git` control paths writable.

---

## Stage D — Memory

**D-1 — File record store and schema** · Owner: Memory · Deps: A-1c · **P0 for Stage D; excluded from preview** · Source: §14.2–14.3
Security: Provenance mandatory; no model-forgeable field; confidence computed at read time.
Test: A record without provenance is unstorable. Done when: the schema is frozen after P7 reports.

**D-2 — SQLite index adapter** · Owner: Memory · Deps: D-1 · **P1** · Source: §14.2, ADR 0008
Security: The index is disposable derived state and may never become an authorization, deletion or provenance authority; corruption or SQL failure must fall back to the file records rather than fabricate results.
Test: P6 — identical behaviour on both runtimes, all three platforms, adapter under 100 lines, probe falls back without crashing. Done when: `reindex` rebuilds from files.

**D-3 — Parameterized path confinement** · Owner: Session & Transcript Service · Contributors: Memory Service · Deps: none · **P0** · Source: §14.7 step 1, D6 delta 3
Security: The confinement root is Broker/owner-derived; allowing a model or caller to choose it would turn a reusable helper into arbitrary host-file access.
Test: Both documented containment bypasses closed with no behaviour change. Done when: `confineTo(root, path)` replaces the hardcoded root.

**D-4 — Incremental transcript indexer** · Owner: Session · Deps: D-2 · **P1** · Source: §14.7 step 2
Security: A stale index can resurrect trashed/private transcript material or cross thread/workspace scope; authoritative files and lifecycle events must determine membership.
Test: P20 — digest equality across fork, resume, compaction, archive, trash, restore, pin, and concurrent turns. Done when: session search stops full-scanning.

**D-5 — Scoped retrieval** · Owner: Memory · Deps: D-1 · **P0** · Source: §14.4
Security: **Scope is not a parameter** — it is read from the ALS. The model has no argument through which to widen it.
Test: Cross-scope leak rate exactly zero (a release blocker). Done when: `recall` returns refs and snippets only, with per-turn caps in code.

**D-6 — Deletion cascade and per-record crypto-shredding** · Owner: Memory · Deps: D-1 · **P0** · Source: §14.5
Security: Sensitive bodies remain solely in Memory Service. A random per-record DEK is wrapped by a scoped keystore key, so deleting one memory neither retains nor erases unrelated records.
Test: P7 — zero recoverable plaintext bodies across Memory Service files, index, temp paths, transcripts, audit and checkpoints; those non-memory stores contain refs only. Destroy one record's wrapped DEK and prove other records remain readable. Done when: the erasure receipt lists out-of-bound backups/exports and no per-subject key couples unrelated erasures.

**D-7 — Consolidation with quarantined extraction** · Owner: Memory · Deps: D-5, B-1 · **P1** · Source: §14.6
Security: The extractor structurally cannot emit a tool call. Broker-issued lineage unions every source taint. Auto-promotion of tainted candidates is refused constitutionally.
Test: Red-team suite seeded with MemGhost- and MINJA-shaped injections; auto-promotion rate for tainted candidates must be zero; harness-notification rate 100%. Done when: I7 is green.

**D-8 — Batch memory-proposal consent gate** · Owner: Memory Service · Contributors: Identity and Security UX, User Research · Deps: D-1, D-5 · **P1 before batch approval** · Source: §14.6, C8, P19
Security: A batch interaction can hide one false, unsafe or over-scoped memory among benign candidates and convert prompt reduction into durable poisoning.
Test: P19 — across the registered seeded batches, participants reject at least 95% of unsafe/false candidates, falsely accept at most 2% of valid candidates as correction targets, finish at median ≤45 s, and use one approval interaction per batch.
Done when: the fixed corpus, participant protocol and item-level decision receipts are retained; failure keeps memory proposals individually reviewable and disables batch approval.

**D-9 — Portable memory export and equivalent re-import** · Owner: Memory Service · Contributors: Identity & Profile Service, Privacy owner · Deps: D-1, D-5, D-6 · **P1 before schema freeze** · Source: C7, D10, §14.2–§14.6, ADR 0008
Security: Export can disclose sensitive bodies, while import can forge provenance or turn an archive into durable prompt injection. Destination, included scopes and sensitivity classes require explicit disclosure; the default bundle is encrypted and integrity-manifested. Imported records preserve source lineage and untrusted taint and can never manufacture user authority or a Grant.
Test: Export a golden store containing duplicate bodies with distinct lineage, contradictions, corrections, scoped records, sensitive records and deletion tombstones; import into a fresh profile and compare the canonical logical digest after excluding local key wrapping and permitted local timestamps. One-byte tampering, missing manifests, scope widening and provenance deletion fail closed. An explicitly selected plaintext export warns before writing and is not the default.
Done when: export→re-import is logically equivalent record-for-record and edge-for-edge; encryption/integrity and sensitivity disclosures pass; no imported field can widen scope, lower taint, create authority or resurrect a deleted record.

---

## Stage E — Routing

**E-1 — Locality classification and posture-aware failover** · Owner: Router · Deps: A-1a · **P0** · Source: §13.1–13.2, ADR 0012
Security: Closes a live violation — `failoverChain` has no privacy classification today.
Test: P13 — zero cross-boundary egress across the matrix including bypass, asserted at the provider seam. Done when: a cross-boundary candidate is rejected loudly, not filtered.

**E-2 — Hardware Capability Service** · Owner: HCS · Deps: none · **P1** · Source: §13.4
Security: Plausible but wrong capacity/accelerator facts can select an unsafe or impossible route and make a missing control look available; probe failure must be explicit.
Test: P24 — zero silently-wrong fields on every declared support tuple; a failed probe reports explicitly absent. Done when: GPU is detected via vendor tools only.

**E-3 — Deterministic escalation signals** · Owner: Router · Deps: E-1, C-1 · **P1** · Source: §13.3
Security: Model self-reported confidence is excluded — it is answer-independent above 90%.
Test: P12 — step count achieves ≥0.75 recall while escalating <50% of tasks. Done when: no model-supplied signal gates escalation.

**E-4 — Capability declarations and disclosure rendering** · Owner: Provider Adapters · Deps: E-1 · **P1** · Source: §13.6
Security: Undeclared or stale locality, retention, cost and capability metadata can conceal data egress or misrepresent the active provider; declarations are enforcement input, not marketing text.
Test: All seven duties render mechanically from declared metadata; an undeclared provider cannot be routed to. Done when: local capability fields are *read* from `/props`, not declared.

**E-5 — Budget hard stop** · Owner: Budget · Deps: E-1 · **P0** · Source: §13.7, Appendix B principle 2
Security: **No downgrade path may exist as code**, so it cannot be reached by a bug.
Test: Exhaustion halts; no silent model substitution; no silent truncation. Done when: the gate runs before provider selection.

**E-6 — MoE catalog and hardware-aware engine assets** · Owner: Local Inference · Deps: E-2 · **P2** · Source: §13.5, ADR 0011
Security: Asset selection accepts only content-hashed, non-executable model formats and verified engine binaries; repository-supplied custom loader code and silent CPU/GPU substitution are refused.
Test: A machine with a discrete GPU does not silently run CPU inference. Done when: `activeParams` exists and `recommend()` optimizes for interactive throughput.

**E-7 — Engine binary integrity** · Owner: Local Inference · Deps: none · **P1** · Source: §3.5, ADR 0011
Security: Models are sha256-verified; the executable that runs them is not.
Test: A tampered engine asset is refused. Done when: a per-asset sha256 table is vendored.

**E-8 — Generated-output applicability, disclosure, and export binding** · Owner: Audit Service · Contributors: Provider Adapters, Bunny Shell, Legal · Deps: E-4, A-1a · **P0 for any affected public output; excluded from preview** · Source: D12, §15.5, §27, Appendix A.13
Security: Records carry generator facts, exact output digest, applicability-policy version, human disclosure and marking status without duplicating prompt or memory bodies. Personality and route cannot suppress them.
Test: Every public image/audio/video/text fixture receives a versioned applicability decision; changed bytes invalidate the binding; conversion emits a transformation record; unsupported or lost marks are visible; required disclosure cannot be hidden. Legal counsel reviews the output/applicability matrix.
Done when: the schema and exporter contract are implemented, the legal-review owner is named, all enabled output paths have a signed dated applicability decision, and no unsupported marking is described as verified.

**E-9 — Measured-throughput routing benchmark** · Owner: Local Inference Manager · Contributors: Hardware Capability Service, Capability Router · Deps: E-2, E-6 · **P1 before throughput enters routing** · Source: §13.5, P23
Security: An unvalidated throughput proxy can route sensitive work to a hosted provider or miss deadlines while appearing deterministic; only measured, tuple-bound evidence may influence locality-preserving selection.
Test: P23 — on the registered device/model/deadline corpus, throughput routing misses ≤10% of feasible deadlines and improves error by ≥25% relative to the bandwidth-only baseline.
Done when: benchmark inputs/results and hardware fingerprints are retained, the signal is versioned, and failure leaves live tok/s out of the authoritative Hardware Capability profile.

---

## Stage F — Shell

**F-1 — Protocol additions** · Owner: Gateway · Deps: A-2, C-1, B-2 · **P0** · Source: §16.1, §23.2
Security: The authoritative interface does not exist on the wire today, so plan-level oversight is currently *less* structured over the protocol than in the terminal.
Test: A client can subscribe to plan, grant, and TSM state and resume from a sequence. Done when: `ExitPlanMode` no longer degrades to a free-text y/N.

**F-2 — Task Surface Model projector** · Owner: TSM Projector · Deps: F-1 · **P0** · Source: §16.3
Security: The TSM is a rebuildable projection; if it can invent, suppress or mutate authoritative Plan/Grant/Execution state, presentation becomes an authorization bypass. Unknown authority events force safe mode.
Test: TSM projection is deterministic from owner streams; p95 input-to-paint ≤100 ms at 4× replay; zero missing nodes. Semantic kinds/message keys map to tested platform roles and localized names in the Shell. Mutation tests cover removal, hiding, disabling, reparenting and reprojection with deterministic focus fallback. Done when: the TSM is canonical but derived, no security state lives only in it, and Shell-local focus/narration ownership is explicit.

**F-3 — Narration Router** · Owner: Shell · Deps: F-2 · **P0** · Source: §16.4
Security: A missed approval/error or focus-stealing announcement can cause uninformed consent; noisy duplicates train users to silence the safety channel.
Test: P11 — 100% of approvals alert within 5 s, remain in the persistent queue, and are keyboard reachable without focus theft; no participant silences the interface. Done when: the four channels exist at first paint and the registered boundary taxonomy passes.

**F-4 — T1 client** · Owner: Shell · Deps: F-2 · **P0** · Source: §16.6, ADR 0002
Security: The conventional accessible surface must expose every consequential action and state; a capability available only through spatial/character UI creates hidden authority and an inaccessible stop path.
Test: A9 — T1 renders every capability T3 exposes. Done when: no feature ships in T3 that is undemonstrated in T1.

**F-5 — Accessibility release-evidence gate** · Owner: Accessibility DRI · Contributors: Bunny Shell, Release QA, User Research · Deps: F-3, F-4 · **P0** · Source: §28, `ACCESSIBILITY_CONFORMANCE_MATRIX.md`
Security: Inaccessible authentication, approval, cancellation or error flows can create coerced/false consent; automated lint is not evidence that a complete process works with supported AT.
Test: A1–A16 automation plus manual B1–B7 complete-process testing on every declared OS/Shell/browser/AT/terminal tuple. Every WCAG 2.2 A/AA and applicable EN 301 549 row has evidence or a release-specific justified N/A; automation is never presented as conformance.
Done when: the matrix has no applicable `Unverified` row, disabled-user findings are dispositioned, and the release scope/relied-on technologies/languages are published. A failing row blocks the claimed surface.

**F-6 — Retire the current browser client** · Owner: Shell · Deps: F-4 · **P1** · Source: §16.9
Security: The current client drops permission detail, steals focus and uses unsafe blocking prompts, so leaving any reachable consequential path preserves an ambiguous approval surface.
Test: Build/static and protocol tests find zero imports, served assets or routes for `src/app/web_client.ts`; a network/browser fixture cannot reach it or submit a consequential decision through it.
Done when: `src/app/web_client.ts` is removed and evolving it is forbidden by convention.

**F-7 — Intent envelope and modality normalization** · Owner: Intent · Deps: F-1 · **P1** · Source: §17.1
Security: Voice/gesture confidence or caller-supplied modality fields must not lower confirmation for an action or create an intent unreachable through the authenticated conventional path.
Test: A1 — build-time assertion that every intent reachable by voice or gesture is reachable by keyboard. Done when: `requiresConfirmation` is computed deterministically and gesture fields are reserved.

**F-8 — Spatial projection behind accessibility and evidence gates** · Owner: Shell · Deps: F-2, F-3, F-4, F-5, Phase 0 entry criterion 5 · **P2** · Source: §16.7
Security: An optional projection may not obscure, reorder or interfere with the authoritative accessible path; visual benefit cannot waive focus, motion or approval safeguards.
Test: P10. Keyboard/screen-reader equivalence, semantic-DOM non-interference, visible focus, zoom/reflow, forced colors and reduced/none motion are hard ship gates. Only then does ≥20% pointer-task improvement determine default status. Done when: an accessibility failure kills the mode; a pointer-benefit failure leaves an otherwise conforming mode optional or removes it.

**F-9 — SpeechProvider, captions, correction, and local adaptation** · Owner: Media and Voice · Contributors: Intent Service, Accessibility DRI, Privacy owner · Deps: F-5 · **P2** · Source: §17.3, §28
Security: Recognition spoofing, missing captions and undeletable adaptation data can authorize the wrong intent or retain biometric-like speech features; voice never supplies authority by itself.
Test: P29 on each proposed language/device tuple, including caption timing, pause/stop/volume, barge-in, interrupted-caption persistence, keyboard alternative, correction, non-standard speech, and deletion of local adaptation data.
Done when: a named local provider and corpus pass for a specific tuple; all other tuples remain disabled. Voice never becomes the only path.

**F-10 — Localization, visual/cognitive, braille, terminal, and disabled-user evidence** · Owner: Accessibility DRI · Contributors: Bunny Shell, Terminal Client, Release QA, User Research · Deps: F-3, F-4 · **P0 with F-5** · Source: Phase 0 §15, §28 B4–B7
Security: Locale, visual, cognitive, braille or terminal failures can hide consequence, destination, denial or stop status; unsupported hosts must never inherit a support claim.
Test: Forced colors/contrast/text spacing, visible focus, pause/flash, errors/authentication, consistent help, locale/language/RTL, refreshable braille, and terminal parity on published matrices; paid keyboard, screen-reader, braille/deafblind, motor, cognitive, and vestibular participants complete the registered flows.
Done when: evidence is linked row-by-row from the conformance matrix and unsupported hosts enter an explicit refusal/degraded state rather than a generic accessibility claim.

---

## Stage G — Extensions

**G-1 — Manifest and constitution-selected isolation-tier mapping** · Owner: Extension Manager · Deps: B-9 · **P0** · Source: §19.2, §19.5, ADR 0014, pending A4
Security: Installation confers no ambient authority; undeclared use is evidence of compromise. A proposed capability-keyed mapping cannot silently replace C16's publisher mapping.
Test: Undeclared capability use is refused without a prompt and logged. Done when: if A4 is ratified, isolation keys on declared capability; if rejected/deferred, C16's publisher mapping remains and capability facts only tighten it. A deferred branch cannot ship the proposed replacement.

**G-2 — Constitution-selected extension egress** · Owner: Extension Manager · Deps: B-6, G-1 · **P0** · Source: §19.3, pending A5
Security: Host allowlists alone are vulnerable to resolution/rebinding and confused-deputy use; every connect binds extension, operation, resolved address, protocol and payload constraints.
Test: If A5 is ratified, an extension reaches only declared hosts through the bound proxy. If rejected/deferred, community extensions have literal zero egress and network-dependent community MCP is unreachable. Done when: the selected constitutional branch is enforced without treating deferral as the proposed exception.

**G-3 — Tool-description fingerprint and pin** · Owner: Extension Manager · Deps: G-1 · **P1** · Source: §19.4
Security: The only defence against the rug-pull pattern; no MCP revision provides it.
Test: A changed description after approval re-triggers consent. Done when: hashes are recorded at install.

**G-4 — Epoch revocation, cleanup saga, and kill switch** · Owner: Extension Manager · Contributors: Grant Ledger, Execution Controller, Memory Service · Deps: G-1 · **P1** · Source: §19.6
Security: Authority must disappear in one epoch transition even when process, registry, job or memory cleanup crashes; stale/forged kill-switch metadata must not grant or revoke silently.
Test: Incrementing the extension epoch immediately blocks new and in-flight broker-mediated use. Crash after each cleanup step; replay finishes context, registry, job and memory cleanup idempotently while authority remains denied. Done when: “atomic” refers to authority invalidation, partial cleanup is visible/retryable, and the kill-switch list is signed, cached, freshness-checked, and non-blocking when offline.

---

## Stage H — Linux and OS

**H-1 — systemd user services and installer** · Owner: platform adapter · Deps: B-7 · **P1** · Source: §8.4, §20
Security: Includes the one-time privileged installation step, presented in the action-class vocabulary (§24.3).
Test: Fresh install, upgrade, uninstall and declined-privilege fixtures verify exact unit hardening, file ownership, no retained root helper/shell, and deterministic degraded-mode feature refusal; `bunny doctor` matches the effective profile.
Done when: if the user declines, the exact degraded profile permits model chat, transcript inspection, and explicitly selected read-only files only; Bash, writes, jobs, plugins, application control, package installation, browser automation and network listeners are unreachable.

**H-2 — AT-SPI-first application driving** · Owner: platform adapter · Deps: H-1 · **P1** · Source: §20.5, ADR 0015
Security: If A15 is ratified, `/dev/uinput`, `ydotoold`, input-group and generic privileged-control paths join the constitutional refuse floor. If rejected/deferred, they remain excluded from this proposed product scope without claiming D16 was amended, and ADR 0015 cannot advance on the proposed constitutional rationale.
Test: P26 and P27 — target identity binds application ID plus accessible path/ID, role, localized name, state and precondition; action completion and portal restart/revocation behavior pass across named GTK, Qt, Chromium, GNOME and KDE tuples. Done when: the A15 outcome is recorded, no coordinate-driven path exists in the enabled branch, and untested applications are explicitly unsupported; deferral leaves the affected feature disabled.

**H-3 — bootc image, CI build, signing and freshness policy** · Owner: Release Engineering · Assurance: two release-authorized maintainers · Deps: H-1 · **P1** · Source: §20.2–§20.3, ADR 0001, ADR 0016
Security: Authenticity without freshness/rollback resistance still permits a signed vulnerable image; one-person key custody cannot satisfy the declared threshold/recovery model.
Test: P25 refuses unsigned, wrong-key, expired, replayed, lower-version, stale-channel and below-threshold metadata with no override and exercises offline recovery/rotation; P18 covers build economics.
Done when: artifact authenticity, freshness, rollback resistance, key custody/rotation/revocation and registry retention are verified through two non-public release cycles. Any failure defers public OS distribution; documentation is not a substitute.

**H-4 — greenboot substrate health check** · Owner: Update & Recovery · Deps: H-3 · **P1** · Source: §20.3
Security: A build can boot successfully while its permission, sandbox, grant or memory substrate is broken; liveness-only health would retain an unsafe deployment.
Test: P17 — a machine that boots fine but whose permission gate failed to load rolls itself back. Done when: C6 covers substrate failure, not just boot failure.

**H-5 — Validate bootc TPM2-LUKS enrolment and recovery** · Owner: Update & Recovery · Deps: H-3 · **P1** · Source: §20.1
Security: current bootc supplies `--block-setup tpm2-luks`; the remaining product risk is recovery-key custody, TPM absence/failure, hardware coverage, reinstall and data-recovery UX.
Test: Install encrypted on supported reference hardware and VM TPM; prove normal unlock, recovery unlock, TPM-cleared failure behavior and documented data recovery. Done when: Bunny adopts the upstream path without inventing cryptography and refuses an image target on which the declared encryption floor cannot be met.

**H-6 — Install ladder** · Owner: Execution Controller · Deps: H-3 · **P2** · Source: §20.6
Security: Install tiers cross package, host and privilege boundaries; the model must not turn a convenience fallback such as `usr-overlay` into untracked persistent modification.
Test: `bootc usr-overlay` is never used as an install path. Done when: the four tiers exist and default hard to tier 1.

**H-7 — Workspace and memory roots outside portal grant paths** · Owner: platform adapter · Deps: H-1 · **P1** · Source: §20.7, §27
Security: Flatpak is a packaging boundary, not a trust boundary; any app granted `filesystem=home` can share a trust domain with a memory store placed there.
Test: An ordinary `filesystem=home` application cannot read the memory root. Done when: roots sit outside the standard grant paths.

---

## Cross-cutting external and governance gates

These are not software tickets and cannot be “completed” by architecture prose.

**X-1 — Second-maintainer onboarding and authority exercise** · Owner: Project maintainer · Deps: none · **P0 before approved Phase 2/product release** · Source: D13, Phase 0 entry criterion 6, §5.4
Security: A single maintainer is a review, incident-response and release-key single point of failure; AI review cannot hold durable authority or accountability.
Test: A named second maintainer independently builds the project, diagnoses one seeded issue, authors and merges a nontrivial change through review, and exercises the documented incident/release path.
Done when: the exercise record, ownership map and real review/incident authority exist; an AI review agent does not satisfy this gate.

**X-2 — Brand, personality-name, and trademark clearance** · Owner: Product Owner · Assurance: qualified counsel · Deps: none · **P0 before public brand/UI investment** · Source: D8, D14, §15.4
Security: Name/provider ambiguity can mislead users about who supplies intelligence and make urgent renaming break protocol, extension and disclosure surfaces.
Test: Obtain dated professional clearance for the Bunny family/composite mark, written disposition for vendor/model-name risks, current brand-term review, and a mechanically checked rename-surface inventory.
Done when: signed advice and Product Owner decision records are retained; absence means no public commitment.

**X-3 — NVIDIA key-pooling terms review** · Owner: Product Owner · Assurance: qualified counsel · Deps: none · **P0 before commercial positioning** · Source: D9, §13.5
Security: Assuming pooled-key authority or terms can expose user credentials/accounts and build routing around a legally or technically unavailable boundary.
Test: Obtain a dated review of the exact pooling implementation and current applicable terms; a marketing/code-surface search finds no pooling claim or dependency before approval.
Done when: a written allow/modify/remove decision exists and routing does not depend on an assumed legal outcome.

**X-4 — Business model and visible resale-margin decision** · Owner: Product Owner · Contributors: Budget Service · Deps: E-4, E-5 · **P0 before monetized routing** · Source: D17, §13.8
Security: Hidden margin or entitlement-gating of safety/privacy/accessibility/transparency creates deceptive spend and unequal protection.
Test: Every provider charge, user charge and margin reconciles and renders in the product; static/schema tests find no entitlement gate for the protected feature categories.
Done when: the business model can be stated verbatim in the UI and the anti-tier static test passes.

---

## Cross-cutting: the structural invariants

Written **as each component lands**, never deferred. A failure is a release blocker.

| Invariant | Lands with |
|---|---|
| I1 — instruction loaders trust-gated | S0-1 |
| I2 — deny never cleared by any mode | S0-5 |
| I3 — refuse set from code, not settings | S0-5, B-1 |
| I4 — no trifecta in one context | B-8, B-9 |
| I5 — egress checked on resolved IP at connect | S0-2 |
| I6 — complete ActionSpec matches the approved effect envelope | C-3 |
| I7 — memory provenance immutable, no tainted record in the system prompt | D-1, D-7 |
| I8 — workspace trust defaults denied | S0-5 |
| I9 — durable jobs cannot hold bypass | S0-9, B-10 |
| I10 — no model-directed generic privileged execution | B-5, B-9 |

## Gating summary

The Safe Linux CLI Preview cannot begin as Phase 2 until A1–A15, the Phase 0 entry criteria, and the applicable A13 accessibility/A14 exception paths in §33 are resolved. It ships only after every §33 gate, P1/P3/P14/P28 across both preview profiles and Broker apply, and the applicable Fedora `TERM-LNX`/B6 complete-process evidence. Bunny Box ships only after C, the accessible F evidence gate, and hostile-LAN authentication. The memory schema freezes after P6/P7; public OS distribution waits for P17/P18/P25 and the two-maintainer operational gate. No claim that the architecture resists injection is made before P14/P15 report and an independent boundary review passes.
