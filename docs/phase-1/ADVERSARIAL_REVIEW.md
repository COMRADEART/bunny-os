# Bunny OS Phase 1 — Adversarial Architecture Review

**Status:** review complete; remediation is not independently verified  
**Review and evidence date:** 2026-07-26  
**Workspace repository commit:** `4d5547fe3882c7d94c179c32f0a98ba728bb0f55`  
**Runtime-source evidence basis:** `COMRADEART/bunny` at `f147f078adfb2a414a8366accd358c42dd431875`, as recorded in `SOURCES.md`

This is the durable record of the Phase 1 adversarial review. It corrects one important bookkeeping error: **four independent review agents collectively covered seven required lenses**. There were not seven independent reviewers. These were agent review passes, not a human third-party audit, certification, penetration test, or implementation assessment.

The initial review found design-blocking contradictions. The specification was then revised to describe remediations for many of them. In this report, **resolved in specification** means only that the current prose, ADR, interface contract, or diagram describes a coherent intended repair. It does not mean code exists, a prototype passed, a security property was demonstrated, accessibility conformance was established, or the repaired design received a second independent review.

## 1. Method and evidence boundary

The four independent review agents collectively examined these seven lenses:

1. security and sandbox escape resistance;
2. accessibility;
3. feasibility for a solo maintainer;
4. distributed-state consistency;
5. Linux platform viability;
6. AI safety and provenance; and
7. Phase 0 traceability and internal consistency.

One agent could cover more than one lens, and some concerns crossed lenses. Findings are therefore attributed to lenses, not to an invented one-reviewer-per-lens roster.

Evidence included `BUNNY_OS_PHASE_0.md`; the Phase 1 specification, ADRs, Mermaid diagrams, backlog, and source register; repository evidence recorded against the Bunny runtime source commit above; and the dated primary sources catalogued in `SOURCES.md`. The review also reconciled the post-finding working-tree edits present on 2026-07-26.

The Phase 1 documents were working-tree artifacts not represented by the workspace commit above (`docs/` was untracked at the evidence freeze). The commit identifies the repository state around the review, not a cryptographic identity for these documents. Release decisions need a committed artifact set and a reproducible source manifest.

Priority labels mean:

- **P0:** an architectural blocker, unsafe boundary, or contradiction that prevents approval or safe implementation.
- **P1:** a high-risk gap that can invalidate a major claim, cause unsafe behavior, or make the design infeasible unless closed before the affected feature ships.

Disposition labels mean:

- **Resolved in specification:** a proposed design remediation is now written down.
- **Residual:** the current artifact set still contains a gap, contradiction, or underspecified contract.
- **Blocked:** closure depends on implementation, a prototype, conformance evidence, Phase 0 ratification, user evidence, or staffing that does not yet exist.

No review agent verified that the proposed fixes work. No sandbox profile, IPC boundary, grant transaction, crash-recovery path, accessibility tuple, Linux image, update chain, or prompt-injection defense was accepted on prose alone.

## 2. Exit-criteria verdict

| Criterion | Verdict | Basis |
|---|---|---|
| **17 — adversarial architecture reviewers examined the design** | **PASS** | The review was performed and produced the P0/P1 findings below. Precisely four independent agents covered all seven lenses. This pass records review execution; it does not endorse the remediations. |
| **19 — no major component boundary must be invented during Phase 2** | **FAIL** | The broker/worker split, authorization ledger transaction, durable journal/outbox, capability handoff, TSM/Shell split, per-OS sandbox compilers, and update/recovery boundaries remain unimplemented and prototype-unverified. Several contracts still have residual gaps. Boundary names in a table are not proof that the boundaries are complete. |
| **20 — the architecture is internally consistent** | **FAIL** | The original review found multiple P0 contradictions. Most now have design remediation specified, but those edits have not been independently re-reviewed as a complete design and have not been implemented or exercised under failure. Residual document contradictions remain. |

Criterion 17 therefore passes while criteria 19 and 20 fail. Treating review execution as verification of the author's response would collapse three different gates into one and recreate the self-review problem the criterion was intended to prevent.

## 3. Consolidated disposition

| Lens | Resolved in specification only | Residual or blocked |
|---|---|---|
| Security / sandbox | Mandatory broker/worker boundary; inherited per-launch worker IPC; paired device-key client auth; exact `ActionSpec`; atomic EffectAttempt batches; fixed-operation root helper; operation-bound credential use | Every effective profile and fail-closed path; all implementation, replay, sibling-process and escape testing |
| Accessibility | TSM/Shell ownership split; stable semantic IDs; focus and announcement rules; self-voicing rejected; WCAG/EN matrix and A1–A16/B1–B7 backlog gate added | No AT, braille, disabled-user, or supported-tuple evidence; every applicable matrix row is unverified; Phase 0 gate conflict remains |
| Solo-maintainer feasibility | Safe Linux CLI Preview is now the only next release slice; A–H is explicitly multi-release; excluded surfaces must be unreachable; all prototypes have maximum envelopes | Preview boundary remains substantial and unimplemented; second maintainer absent; post-preview roadmap still requires rescoping at each gate |
| Distributed-state consistency | Owner-local streams/outbox, graph hash versus sequence, two allowlisted EffectAttempt batches, global stop epoch, truthful cancellation, overlays/reservations, N/N−1 migration, retry identity and lineage-preserving dedupe specified | Cross-process writer fencing, revocation cleanup, atomic-batch fault behavior and crash recovery remain unimplemented and untested |
| Linux viability | Fedora 44/SELinux preview tuple fixed; Ubuntu/AppArmor split; public OS/NVIDIA deferred; T3/GPU narrowed; freshness, FDE validation and N/N−1 specified | Rootless/profile viability, portals, AT-SPI, update enforcement, FDE/recovery and hardware evidence remain unproven |
| AI safety / provenance | Broker-derived provenance graph; authority separated from taint; typed control/data split; exact authorization edge; sensitive-memory refs; identical-body observations preserve lineage | Live hostile-repository and unattended-job defects remain; taint integrity and utility budget untested |
| Phase 0 traceability | Conflicts and amendment requests are now explicit; this record corrects reviewer accounting | Four entry criteria and fifteen amendments remain open; accessibility and refuse-floor changes require ratification; evidence is not yet a committed reproducible bundle |

Every item in the middle column remains subject to the implementation and independent-re-review blocks in criteria 19 and 20.

## 4. Original P0/P1 findings and current disposition

### 4.1 Security and sandbox

| ID | Priority | Original finding | Current disposition |
|---|---:|---|---|
| SEC-1 | P0 | The design alternated between one in-process Core, an optional in-process/IPC evaluator, and a mandatory broker. If approvals, policy, credentials, audit writing, and effects remained reachable inside the model-directed address space, a compromised worker could forge or bypass authority. | **Resolved in specification; blocked in implementation.** §7.1, §12.1, ADR 0004, and Appendix A now require an unprivileged Broker/control plane plus sandboxed Agent Worker, direct authenticated approval termination, no consequential in-process fallback, and a separate fixed-operation root helper. P1 must demonstrate the boundary. |
| SEC-2 | P0 | “Action is a member of an approved plan” bound a display-level node, not the concrete effect. Arguments, path, destination, executable, payload, route, or budget could drift while retaining nominal plan membership. | **Resolved in specification; blocked in implementation.** §10.2 and invariant I6 define an immutable content-addressed `ActionSpec` and typed control/data fields. P14/P15 and implementation tests must prove untrusted data cannot widen a control slot. |
| SEC-3 | P0 | `PermissionRequest` ownership was split, and `lookup` followed by `consume` allowed a once grant to be raced, double-spent, or reused after an indeterminate effect. The permission diagram originally consumed after execution. | **Resolved in specification; blocked in implementation.** The Grant Ledger solely owns request/decision/grant/authorization semantics. Every user decision names a displayed request/version/digest; `admitEffect` atomically commits its reservation with `ExecutionStarted` and `AuditStart`; `finalizeEffect` advances all three owners together; an indeterminate once authorization is never reused. |
| SEC-4 | P0 | An unsandboxed “system administration” profile would have converted a grant into generic root shell or container-engine authority. That authority cannot be meaningfully scoped by a model-facing prompt. | **Resolved in specification; ratification blocked.** I10 and A15 prohibit model-directed UID 0, unrestricted sudo, rootful container sockets, `/dev/uinput`, and generic privileged commands. Administrative effects use a minimal typed helper; direct root terminal use is Manual Control. A15 still requires Phase 0 action. |
| SEC-5 | P1 | A sandbox-visible credential sentinel was a bearer credential by another name: a worker could replay or redirect it unless it was bound to the exact operation and payload. | **Resolved in specification; blocked in implementation.** §12.6 binds broker-side protocol operations to worker identity, operation ID, endpoint, verb, normalized resource, payload constraint/digest, `ActionSpec`, lease epoch, one-use count, and expiry; no reusable placeholder enters the sandbox. |
| SEC-6 | P1 | Filesystem permissions on a Unix-domain socket do not by themselves authenticate another process running as the same user. The design named “authenticated IPC” without fixing peer identity, channel binding, or replay handling. | **Resolved in specification; blocked in implementation.** §12.1 removes the reconnectable worker listener: the Broker creates a per-launch anonymous inherited socketpair/pipe and binds it to the child identity, sandbox, launch generation and monotonic counter. §24.4 requires every client transport—including UDS/pipe—to prove possession of a paired device key over a fresh nonce and transcript; filesystem/DACL permissions are defence in depth only. P16 includes same-UID sibling, replay and unconfirmed-pairing fixtures. |
| SEC-7 | P1 | The sandbox honesty matrix described desired guarantees before any complete effective profile was compiled and measured on real hosts. Rootless namespaces, LSM policy, seccomp, cgroups, Landlock, egress, teardown, and degradation interact; a list of primitives is not a boundary. | **Blocked.** P1–P5 and the escape corpus have not run. Each shipped profile must publish the effective controls and refuse execution when any required primitive silently degrades. |

### 4.2 Accessibility

| ID | Priority | Original finding | Current disposition |
|---|---:|---|---|
| A11Y-1 | P0 | The current browser client is unsafe as an approval surface: it steals focus, uses blocking prompts, exposes unlabeled decisions, has no announcement/focus model, and drops the permission `body` and `persistNote`, so the user cannot know the content or persistence being approved. | **Resolved in specification; residual in the product.** §16.9 retires the client instead of treating it as a base. The shipped code remains until removed or disabled, so it must not be used to authorize consequential or remote work. |
| A11Y-2 | P0 | Phase 0 makes WCAG 2.2 AA a Phase 1→2 gate, while the implementation plan defers the Shell and all conformance evidence to Phase 2 Stage F. Both cannot be true. | **Residual; ratification blocked.** A13 correctly exposes the choice: deliver and test the minimum task/approval surface before Phase 1 exits, or have Phase 0 move the gate while keeping UI decisions provisional. No ratification or conformance evidence exists. |
| A11Y-3 | P1 | Automated structural checks were described as “enforcing WCAG.” Automation cannot establish full-page, complete-process, accessibility-supported-technology, or non-interference conformance. | **Resolved in the current specification; evidence blocked.** §28 and backlog F-5 now separate automation from conformance, require A1–A16/B1–B7, and link a clause-by-clause matrix. Every applicable evidence row remains unverified. |
| A11Y-4 | P1 | A server-side semantic tree cannot own browser/native focus, localized names, or announcements, and stable IDs alone do not prove focus retention. The earlier Semantic Twin language risked creating a second authority. | **Resolved in specification; blocked in prototypes.** The TSM is a deterministic derived projection; each Shell owns role/name mapping, focus fallback, and narration. P9/P10 and mutation tests remain unrun. |
| A11Y-5 | P1 | Accessibility support was discussed by engine or OS rather than by tested tuples. Packaged Chromium→UIA/AX/AT-SPI, browser, screen reader, braille stack, locale, input settings, and terminal combinations can fail independently. | **Matrix specified; evidence blocked.** `ACCESSIBILITY_CONFORMANCE_MATRIX.md` defines candidate tuples, complete processes, braille and paid-participant evidence. No row has passed and Phase 0 entry criterion 5 remains unmet. |
| A11Y-6 | P1 | “Self-voice critical flows” is not a Linux accessibility fallback; it bypasses the user's screen reader and braille display and cannot substitute for AT-SPI/Orca integration. | **Resolved in specification; ratification blocked.** A6 requests removal. Linux tuples and the separate terminal matrix still require evidence. |

### 4.3 Solo-maintainer feasibility

| ID | Priority | Original finding | Current disposition |
|---|---:|---|---|
| SOLO-1 | P0 | The proposed Phase 2 surface—Broker, egress proxy, authorization ledger, event journal, memory service with crypto-shredding, router, TSM/Shell, extension isolation, per-OS sandbox adapters, Linux image/update system, and eighteen-plus prototypes—is not a responsible one-maintainer V1. Security-critical breadth makes partial implementation more dangerous than explicit deferral. | **Resolved at planning level; execution blocked.** §33 now makes the Fedora 44 x86-64 Safe Linux CLI Preview the only next release slice and calls A–H a roadmap. The slice still requires implementation and independent boundary review and is explicitly pre-V1. |
| SOLO-2 | P0 | Phase 0 requires a second maintainer with merge and review authority before architecture begins. The absence is especially material for security boundaries and release/update keys. | **Blocked.** Phase 0 entry criterion 6 remains unmet. Four agent reviews reduce blind spots in prose; they do not supply durable human ownership, incident response, key custody, or code-review authority. |
| SOLO-3 | P1 | Tri-OS sandbox parity plus x86-64/ARM64 Core, Linux compositor/application compatibility, browser and terminal accessibility matrices, and a bootc image create separate continuous qualification programs. | **Resolved for the preview; residual for the roadmap.** The preview has one Fedora/SELinux/x86-64 tuple and terminal/stdio only. Each later OS/client tuple is an independent evidence gate rather than inherited support. |
| SOLO-4 | P1 | The prototype inventory has measurable thresholds but no capacity budget, stop rule, or rule for retiring components when gates fail. A backlog can encode more work than a maintainer can safely own. | **Resolved at prototype level.** §32 now gives P1–P29 an owner, smallest implementation, maximum scope, inverse failure rule, and feature-specific kill/defer consequence. Overall roadmap maintenance capacity remains a release-by-release decision. |

### 4.4 Distributed-state consistency

| ID | Priority | Original finding | Current disposition |
|---|---:|---|---|
| STATE-1 | P0 | Failure and recovery originally wrote workspace files before the “intent-to-write” record, while audit text claimed a post-effect logging failure could prevent the effect. That inverted write-ahead semantics and could lose the only durable fact that an effect might have happened. | **Resolved in specification; blocked in crash testing.** §23/§25.4 define a realizable single-Journal transaction: owner-authorized Grant/policy reservation, `ExecutionStarted`, `AuditStart` and outbox commit before capability materialization. A matching terminal batch advances Grant, Execution and Audit together; open attempts reconcile read-only to a verified result or `Indeterminate`. P28 must prove it. |
| STATE-2 | P0 | Interruption was treated as a clean terminal outcome even when a remote or descendant effect could still run. Plan, execution, and grant state machines disagreed about `Interrupted`, `Cancelled`, `CancellationPending`, `Unknown`, and partial rollback. | **Resolved in specification; blocked in implementation.** Cancellation is now a request with `CancelRequested`, pending, truthful terminal, reconciliation, process-tree kill, and lease/proxy revocation semantics. The live unattended-job defect remains. |
| STATE-3 | P0 | TCP and WebSocket created per-connection state owners. A process-wide map would still fail across two Bunny processes, restart, or unlocked JSONL writers; it could violate one-active-turn and sequence invariants. | **Resolved in design/backlog; residual in current code.** The repair now requires one durable compare-and-swap lease per thread, owner identity, fencing epoch, heartbeat, stale-owner recovery, and one fenced writer/transactional journal. It is not implemented. |
| STATE-4 | P1 | The plan event log, transcript sequence, Gateway view, and Event Bus could become competing authoritative histories, with no atomic owner-write/projection handoff. | **Resolved in specification; blocked in implementation.** Owner-local streams plus an atomic journal/outbox and idempotent projections are now specified. A crash/replay prototype must prove no lost or duplicated authoritative transition. |
| STATE-5 | P1 | A monotonic plan sequence was used as both a concurrency token and an approval/content identity. Equal position does not imply equal graph, and equal graph does not imply equal sequence. | **Resolved in specification.** `stream_sequence` is the compare-and-append token and canonical `graph_hash` is the approval identity. This still needs schema and drift-guard tests. |
| STATE-6 | P1 | Concurrent plans could write the same workspace and later apply a global recovery snapshot, overwriting another plan's or the user's newer work. Capability-level `parallelSafe` booleans were too weak to express conflicts. | **Resolved in specification; blocked in implementation.** Per-plan overlays/worktrees, canonical resource reservations, base hashes, optimistic merges, and plan-scoped recovery replace global restore. Conflict-key behavior remains to be proven. |
| STATE-7 | P1 | “Forward-only migrations” conflicted with OS rollback and older readers silently ignoring unknown state. An old build could skip a new revocation or authorization event and reconstruct unsafe authority. | **Resolved in specification; blocked in implementation.** §22 now requires N/N−1 readers plus down-migration or deployment-bound snapshot, while §23 forces safe mode for unknown authority events. Migration/rollback tests have not run. |
| STATE-8 | P1 | Idempotency was named but not tied consistently to stable operation ID, expected version, effect digest, and outcome digest. Retrying an indeterminate non-idempotent remote effect could duplicate it. | **Resolved in specification; blocked in implementation.** §25.4 fixes one Broker-minted tuple across Policy, Grant, Execution, protocol and Audit boundaries; rejects field mutation under a reused id; derives provider keys; separates read-only reconciliation; and forbids a fresh-id retry of an `Indeterminate` original without verified no-effect or a new explicit authorization. Appendix A.10 and P28 make the rule testable. |
| STATE-9 | P1 | Emergency stop and extension revocation span grants, jobs, processes, memory, proxy leases, and projections owned by different components. Calling the operation “atomic” did not define a realizable transaction. | **Resolved in specification; blocked in implementation.** The Execution Controller owns durable `GlobalAdmissionState`; one allowlisted Journal batch stops admission, advances global revocation/admission epochs and appends Audit before bounded cleanup. Resume is authenticated and reconciliation-gated. Extension revocation uses the separate epoch-first idempotent cleanup saga in §19.6; partial cleanup remains denied and visible. |

### 4.5 Linux viability

| ID | Priority | Original finding | Current disposition |
|---|---:|---|---|
| LNX-1 | P0 | No complete Linux isolation profile has been demonstrated. Bubblewrap is a low-level constructor; rootless OCI/user namespaces remain shared-kernel boundaries and can be restricted by host policy; seccomp, Landlock, cgroups, namespaces, LSM rules, and default-deny egress must work together. | **Blocked.** P1–P5 and distro-host tests must pass on the exact supported kernels and policies. If a required primitive is absent or silently ignored, Bunny must refuse that profile rather than advertise a weaker sandbox. |
| LNX-2 | P1 | Fedora/bootc establishes an image-update direction, not a production desktop, verified boot, encrypted-install UX, recovery, state-compatible rollback, or sustainable one-maintainer release channel. `/var` and `/etc` have different rollback semantics. | **Resolved in specification; blocked in prototypes.** ADR 0016 now separates atomic deployment from state compatibility, adds `N/N-1`, health rollback, TUF-style freshness, and a TPM2-LUKS validation path. P17/P18 and signature/recovery tests have not run. |
| LNX-3 | P1 | AT-SPI, ScreenCast, RemoteDesktop, and libei are a plausible ladder, but compositor/toolkit coverage, restore-token behavior, query latency, and user-consent semantics are not portable assumptions. A portal token is not a Bunny grant. | **Resolved as a proposed ladder; blocked.** ADR 0015 binds portal artifacts to the Grant Ledger and refuses `/dev/uinput`. P26/P27 and supported-compositor negotiation remain unproven and depend on A15. |
| LNX-4 | P1 | Firecracker was alternately described as lacking generic PCI work and as a future desktop/GPU tier. Generic VirtIO/PCI progress does not create stable general VFIO/GPU/desktop passthrough; gVisor GPU support also exposes host-driver risk. | **Resolved in specification.** T3 is Phase 2, Firecracker is headless/KVM, and hostile GPU work is refused without a measured hardware boundary. This is a deferral, not a delivered isolation tier. |
| LNX-5 | P1 | The support promise combined Ubuntu and Fedora hosts, a Fedora bootc image, NVIDIA and non-NVIDIA streams, x86-64 first, ARM64 Core, multiple compositors, app compatibility, and accessibility tuples without a maintained qualification matrix. | **Resolved for preview scope; later work blocked.** Fedora 44/SELinux/x86-64 is the sole preview tuple; Ubuntu/AppArmor is separate, public OS/NVIDIA/ARM/UI control are deferred, and each later tuple needs named systems and evidence. |
| LNX-6 | P1 | Time-sensitive platform statements drifted inside the artifact set. In particular, ADR 0001 said bootc “lacks [FDE] entirely,” while the source register and ADR 0016 record current `tpm2-luks` install support; sealed composefs remains experimental. | **Resolved in current artifacts.** ADR 0001 now adopts and tests bootc's native TPM2-LUKS path; `SOURCES.md` dates the claim. Release-time rechecking remains mandatory. |

### 4.6 AI safety and provenance

| ID | Priority | Original finding | Current disposition |
|---|---:|---|---|
| AI-1 | P0 | Provenance was a caller-supplied single bit and was used inconsistently: one rule said a third-party-boundary action was never authorized while the permission flow allowed exact user approval. A single trust bit cannot represent authority, data lineage, code identity, transformations, or mixed inputs. | **Resolved in specification; blocked in implementation.** §11.6 now separates authenticated authority origin, monotonic taint, and derivation lineage in a broker-built graph. Exact user approval adds an attributable edge without erasing taint. |
| AI-2 | P0 | A hostile repository can currently inject project instructions into the system-prompt region before workspace trust, giving third-party text the highest model-context authority. | **Residual live defect.** It is now V1/Stage 0/invariant I1, but no implementation fix was verified. Until closed, hostile repositories must not be treated as safe agent inputs. |
| AI-3 | P0 | Sensitive memory bodies were allowed into transcript/audit/checkpoint flows despite the Phase 0 requirement that they never appear there, making crypto-shredding ineffective once plaintext had replicated. | **Resolved in specification; blocked by P7.** Sensitive bodies remain in the Memory Service under per-record envelope encryption; other stores receive refs/hashes/classification. P7 must find zero recoverable plaintext across all secondary stores. |
| AI-4 | P1 | Memory poisoning and provenance preservation were weakened by idempotency keyed only on `body_hash`: identical text from a new source became a no-op, losing new lineage, authority, confidence, and staleness evidence. | **Resolved in specification; blocked by P7.** Appendix A.3 now keys observations on operation/proposal id; identical bodies may share a blob but retain distinct lineage/validity edges. |
| AI-5 | P1 | The prose risked treating provenance as prompt-injection immunity. The real attack surface moves to adapter integrity, parser/schema confusion, taint joins, control/data classification, and authorization binding; containment can also reduce task utility. | **Blocked.** P14 must show zero unauthorized effects with a compromised model, and P15 must measure the utility loss against the fixed budget. Neither has run. |
| AI-6 | P1 | Model output, extension manifests, MCP tool annotations, and provider metadata could influence classification but must never create authority or lower a disposition. | **Resolved in specification; blocked in implementation.** Broker-derived context, compiled policy, manifest/grant intersection, and “annotations are hints” rules now state the correct direction. Boundary tests must prove hostile metadata cannot issue or widen a capability. |

### 4.7 Phase 0 traceability and internal consistency

| ID | Priority | Original finding | Current disposition |
|---|---:|---|---|
| TRACE-1 | P0 | Phase 1 began while Phase 0 entry criteria 3, 5, 6, and 7 were substantively unmet; criteria 2 and 4 were completed only after architecture work started. Traceability does not authorize proceeding out of order. | **Blocked.** §5.4 now reports the breach plainly. The criteria must be satisfied or A14 ratified by the constitution owner; the architecture remains provisional. |
| TRACE-2 | P0 | Several Phase 1 decisions materially amended Phase 0—sandbox guarantees, microVM timing, self-voicing, reversibility outcomes, accessibility gate timing, and the privileged-control refuse floor—without constitutional ratification. | **Blocked.** §31.1 now records A1–A15 instead of silently overriding Phase 0. None is approved merely because the Phase 1 prose prefers it. |
| TRACE-3 | P1 | The accessibility exit gate, Stage F schedule, and Phase 0 user-validation requirement contradicted one another. | **Residual.** A13 and §5.4 expose the conflict, but a decision and evidence are still missing. Criterion 14 can mean “criteria are specified”; it cannot mean accessibility conformance passed. |
| TRACE-4 | P1 | Repository evidence was not reproducible from the architecture workspace alone: the Phase 1 docs were untracked, runtime claims pointed at a separate source commit/package snapshot, and some path mappings had drifted. | **Residual.** `SOURCES.md` now names the runtime commit, but Phase 1 needs a committed manifest containing document commit, runtime commit, source/package identity, commands, and generated-evidence hashes. |
| TRACE-5 | P1 | The verification appendix said seven reviewers had all failed to return findings. That was factually wrong and confused seven lenses with reviewer count. | **Resolved.** Appendix B and this record state four independent agents covering seven lenses and criterion 17 passes only for review execution. |
| TRACE-6 | P1 | “Pass as specified” was used where a requirement depended on current implementation or independent validation, especially browser authority, accessibility, component boundaries, and consistency. | **Resolved in reporting; delivery blocked.** Appendix B now separates document-level passes, current-product failures, unverified evidence, and criteria 19/20 failures. |

## 5. What the review does and does not close

The review closes only the evidence gap behind criterion 17: adversarial examination happened, across every required lens, and produced actionable findings.

It does **not** close:

- the live current-product P0 defects;
- the Phase 0 entry criteria or amendment requests;
- any sandbox, crash-consistency, accessibility, Linux, update, or injection prototype;
- the absence of a second maintainer;
- the missing committed/reproducible evidence bundle;
- criterion 19's implementation-boundary question; or
- criterion 20's requirement for an independently re-reviewed, internally consistent design.

The appropriate next review is not a repetition of the original exercise. It is a focused independent pass over the remediated authority path—authenticated decision → exact `ActionSpec` → grant reservation/lease → durable pre-effect record → capability release → truthful terminal/reconciliation—plus the minimum accessible task/approval surface and Linux profile. That pass should use committed artifacts and the prototype results.

## 6. Responsible reduced-slice recommendation

The full architecture is not a responsible next implementation commitment for a one-maintainer project. The smallest slice that tests the thesis without manufacturing a half-secure platform is:

| Area | Include now | Explicitly defer |
|---|---|---|
| Repair | Stage 0: close the live P0 authority, egress, browser, process-ownership, cancellation, environment, MCP, and unattended-job defects with self-checks | Any feature work built on an open Stage 0 P0 |
| Platform | **Linux x86-64 reference application**, not Bunny OS; one Fedora host tuple with `inspect-ro`, disposable `work-overlay`, and content-bound Broker apply; fail closed when any required control is unavailable | Bunny OS image, ARM64 Mode D, Windows/macOS sandbox-parity claims, multi-distro expansion |
| Topology | One unprivileged Broker containing bounded modules, one sandboxed Agent Worker, per-action confined children, and one local transactional journal | Separate services beyond trust boundaries, remote multi-user operation, horizontal/distributed design |
| Work model | One user, one workspace, one active writing plan; immutable `ActionSpec`; one fenced writer; plan overlay and explicit commit | Concurrent writing plans, shared Box, unattended durable jobs, cross-device synchronization |
| Capability set | Observe/read; bounded edit and test inside a disposable workspace overlay; default-deny egress; no host credentials in the worker | Send/spend/publish, generic shell outside the sandbox, system administration, app driving, capture, hardware control, hostile GPU, T3/microVM |
| Providers | One configured provider/locality at a time; explicit refusal rather than silent failover across privacy boundaries | General capability router, automatic local→hosted escalation, cost market, multi-provider optimization |
| Memory | Session/transcript durability and references only where required for audit/recovery | Consolidation, embeddings, long-term personal/secret memory, cross-session inference until P7 passes |
| Extensions | No third-party extension or MCP egress in the safe slice | Marketplace, community extensions, standing extension grants, multi-owner revocation saga |
| Interface | Existing terminal with exact `TERM-LNX`/B6 evidence. Under the current unamended Phase 0 gate, a minimum DOM task/plan/approval surface and its WCAG/disabled-user evidence must be completed in Phase 1 before Stage S; if A13 moves that gate, the DOM surface moves to Stage F | Spatial view, character animation, voice/gesture, broad multimodal UI, Bunny Box |

This Linux-first reference slice is an engineering-validation sequence, not permission to redefine D3's cross-platform V1 silently. If it becomes the product release scope, Phase 0 must ratify that scope change. Unsupported platforms may not inherit Linux safety claims by analogy.

Expansion should stop until all of these are true:

1. Stage 0's P0 repairs and their regression tests pass.
2. P1/P3/P14/P28 prove the Broker, two preview profiles, content-bound apply and EffectAttempt batches. P4 is required before later authenticated egress, which is unreachable in the preview.
3. P14 shows zero unauthorized effects under the compromised-model corpus, and P15 keeps the measured utility loss within the declared budget.
4. The A13 fork is resolved: absent ratification, the minimum DOM approval/task surface passes the Phase 1 WCAG/disabled-user gate before Stage S; with ratification, the graphical gate moves to F, while the preview terminal still passes its exact tuple and exposed complete processes.
5. A second maintainer has merge, review, incident-response, and release-key authority.
6. The reduced design and its prototype evidence receive an independent re-review, closing the residuals in this file before criteria 19 and 20 are reconsidered.

Until those gates close, the responsible product statement is: **Phase 1 is a provisional, adversarially reviewed architecture proposal with specified remediations—not a verified architecture and not an implemented security boundary.**
