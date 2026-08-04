# Overlap matrix: runtime-core against the UX-shell donor

One record per overlapping concern, in the form §3 asks for. The donor branch is
`codex/companion-runtime-ux-shell` at `4896be5b`; the runtime core is
`feature/companion-runtime-core` at `2f39d58c`; their merge base is `ff751ab7`.

The donor branch also carries the capability-image-integration commits
(`5325f7f`…`9d3b0ad`, including Commit C′). **None of those were taken.** They
belong to `feature/capability-image-integration` and its hosted reproducibility
evidence, and nothing in this integration touches them.

A note on the shape of every decision below: the donor was not a UX layer over
the runtime core, it was a *second companion runtime* with a UX layer attached.
So for every module that owns state the answer is the same, and the interesting
part is what was kept from the donor's behaviour rather than which branch won.

---

## `companion/runtime.py`

| | |
| --- | --- |
| **Runtime-core** | `CompanionRuntime`: state machine over `TRANSITIONS`, capability bridge, approval gate, tool broker, review rounds, event-before-and-after-everything. |
| **UX-shell** | A second `CompanionRuntime`: phase enum, provider router, speech and microphone orchestration, SQLite persistence. |
| **Chosen authority** | Runtime-core. |
| **Donor behaviour retained** | The idea that the runtime should expose a snapshot suitable for a UI, and that a client should reconnect with an `afterSequence`. Both are now `get_presentation_state`. |
| **Donor behaviour discarded** | Its whole lifecycle, its phase model as a *runtime* concept (it survives as a presentation concept only), its provider routing, and its speech orchestration. Speech is a client concern: audio that reached the runtime would be audio that reached durable storage. |
| **Adapter** | `companion/service.py` — `CompanionGateway` exposes thirteen operations over the canonical runtime. |
| **Schema migration** | None. Nothing donor-shaped is persisted. |
| **Tests** | `test_integration_authority.py` asserts by AST that exactly one class in the package defines both `submit_task` and `run_task`. |
| **Compatibility impact** | None. The donor runtime never shipped. |

## `companion/events.py`

| | |
| --- | --- |
| **Runtime-core** | `TaskEvent`: hash-chained, versioned hashing rules per schema version, per-field `internalFields` classification, sanitized at construction. |
| **UX-shell** | `TaskEvent` with `record_kind`, `occurred_at`, a `generated_description` variant, and event types including `tool_requested`, `speech_started`, `response_drafting`, `connection_lost`. No chain. |
| **Chosen authority** | Runtime-core. The chain is what makes ordering, corruption detection, partial-write recovery and deduplication one mechanism instead of four. |
| **Donor behaviour retained** | The observation that the UI needs a *human* sentence per event. It is now `_STATUS` in `companion/presentation.py`, derived deterministically from the canonical event and its sanitized payload. |
| **Donor behaviour discarded** | Its event vocabulary. `connection_lost` and `speech_started` are client-side facts and are not events: an event is something that happened to a task. Listening and speaking are carried in the projection via `with_indicators`, not in the record. |
| **Adapter** | `EVENT_PHASES` maps every canonical type to a phase. |
| **Schema migration** | None. `EVENT_SCHEMA_VERSION` stays 2. |
| **Tests** | `test_presentation_projection.py::MappingTests` asserts `set(EVENT_TYPES) == set(EVENT_PHASES)`. |
| **Compatibility impact** | None. |

## `companion/store.py`

| | |
| --- | --- |
| **Runtime-core** | Append-only JSONL per session, hash-chained, fsync before acknowledgement, atomic projection replacement, 0600/0700, `O_NOFOLLOW`, retention anchors, forward migration. |
| **UX-shell** | SQLite with `companion_tasks` and `companion_events`, WAL, `synchronous=FULL`. |
| **Chosen authority** | Runtime-core. The evaluation is the table in §8 of `COMPANION_INTEGRATION.md`. |
| **Donor behaviour retained** | Its indexed-query ergonomics as a *stated future need*, not as an implementation. |
| **Donor behaviour discarded** | SQLite entirely. |
| **Adapter** | None needed. |
| **Schema migration** | `companion/migration.py` archives a donor database rather than importing it, for the reasons in §9. |
| **Tests** | `test_migration_and_recovery.py`; plus an AST check that no module except `migration.py` imports a database driver. |
| **Compatibility impact** | A developer with a donor store keeps it. It is preserved, never deleted, and never silently merged. |

## `companion/approval.py` (donor) → `companion/approvals.py` (canonical)

| | |
| --- | --- |
| **Runtime-core** | `ApprovalGate` over `CompanionApprovalStore`, binding to task + transition + plan revision + destination fingerprint, with six named refusals and a per-run consumed set. Built on the existing `capability.apply.approval` contract. |
| **UX-shell** | `ApprovalCentre` with `ApprovalView`/`ApprovalResolution`, a decision vocabulary of `approve`/`deny`/`cancel_task`, and its own error hierarchy. |
| **Chosen authority** | Runtime-core. |
| **Donor behaviour retained** | Two things, both important. (a) The resolution should carry the binding *back*, not just a yes — that became `ApprovalPresentation.binding()` and the gateway's field-by-field comparison. (b) The dialog needs the alternatives, the safe default and the cost in front of the person — that became the Approval Centre rows. |
| **Donor behaviour discarded** | `cancel_task` as an approval *decision*. Cancelling is not an answer to a question; it is a separate operation with its own event, its own unknown-operation handling and its own output retention. Folding it into a decision would have hidden all of that behind a button label. |
| **Adapter** | `CompanionGateway.resolve_approval` (claim check) → `InteractiveConsent` (delivery) → `ApprovalGate.resolve` (act check). |
| **Schema migration** | None. `companion-approval.schema.json` is not carried over; the binding is in `companion-presentation-state.schema.json`. |
| **Tests** | `test_protocol_ipc.py::ApprovalRefusalTests` — eight refusal paths; plus slice step 12. |
| **Compatibility impact** | None. |

## `companion/state.py` (donor) → `companion/presentation.py` (new)

| | |
| --- | --- |
| **Runtime-core** | Nothing. This is the gap the integration filled. |
| **UX-shell** | `CompanionStateController` with a 23-phase enum, an `ALLOWED_TRANSITIONS` table and `restore()` from events. |
| **Chosen authority** | New, canonical: `PresentationProjector`. |
| **Donor behaviour retained** | The phase vocabulary (nearly intact), the per-event status sentence, and rebuilding by replay. |
| **Donor behaviour discarded** | The *transition table*. A presentation state machine that refuses a move is a second lifecycle that will eventually disagree with the real one, and its refusals would be raised in the layer least able to do anything about them. The projection maps and prioritises; it never refuses. Also discarded: `InvalidStateTransition` as a UI-layer exception. |
| **Adapter** | `EVENT_PHASES` + `TASK_STATE_PHASES` + `PHASE_PRIORITY`. |
| **Schema migration** | `companion-state.schema.json` superseded by `companion-presentation-state.schema.json`, which is explicitly non-authoritative. |
| **Tests** | `test_presentation_projection.py` — 39 tests. |
| **Compatibility impact** | None. |

## `companion/model.py` (donor) → `companion/task.py` + `session.py` (canonical)

| | |
| --- | --- |
| **Runtime-core** | `CompanionTask` and `CompanionSession`: operation ledger keyed by derived idempotency key, approval references with destination fingerprints, consumed-deadline accounting that survives a reboot. |
| **UX-shell** | `TaskSession`, `AgentIdentity`, `ToolOperation`, `TaskOutput`, `TaskError`, `ReviewerObservation`, plus enums. |
| **Chosen authority** | Runtime-core. |
| **Donor behaviour retained** | Its *display* decomposition — executor identity, current tool, outputs and errors as separate panel rows — as the shape of `PresentationState` and `task_rows()`. |
| **Donor behaviour discarded** | Its task model. `deadline_consumed_seconds` alone is worth the whole decision: a deadline stored as an instant on a monotonic clock is meaningless after a reboot, and the donor stored instants. |
| **Adapter** | `PresentationState`. |
| **Schema migration** | `companion-task.schema.json` (donor) not carried over; `companion-core-task.schema.json` stands. |
| **Tests** | Existing `test_sessions_tasks.py`, unchanged. |
| **Compatibility impact** | None. |

## `companion/coordination.py`

| | |
| --- | --- |
| **Runtime-core** | `CoordinationPolicy` ceilings, `ExecutorLeases` (one executor per task, refused not queued), reviewer isolation by deep copy per reviewer. |
| **UX-shell** | Its own coordination with agent registration and reviewer scheduling. |
| **Chosen authority** | Runtime-core. |
| **Donor behaviour retained** | Nothing beyond the confirmation that reviewer identities belong in the UI. |
| **Donor behaviour discarded** | Its scheduler. |
| **Adapter** | None. |
| **Schema migration** | None. |
| **Tests** | Existing `test_executors_reviewers.py`; `test_integration_authority.py::OneAuthorityTests`. |
| **Compatibility impact** | None. |

## `companion/providers.py` (donor) → not carried over

| | |
| --- | --- |
| **Runtime-core** | `Executor` protocol with one shipped implementation, `DeterministicLocalExecutor`. No provider adapter, not even a stub. |
| **UX-shell** | `AgentProviderDescriptor`, `VoiceProvider`/`VoiceRouter`/`SystemVoiceProvider`, `SpeechInputProvider`, `MicrophoneController`. |
| **Chosen authority** | Runtime-core for execution; the voice and microphone parts extracted to `companion/voice.py`. |
| **Donor behaviour retained** | `SystemVoiceProvider`'s argv construction per synthesiser, and `MicrophoneController`'s activation rule almost verbatim — both were right. |
| **Donor behaviour discarded** | `AgentProviderDescriptor` and the provider router. §11 forbids a provider in this phase, and a descriptor with an `authentication_state` field is a shape for a real integration to be poured into without anybody reviewing the decision to have one. Also discarded: `VoiceRouter`'s remote/paid branches, since no remote voice exists and adding the routing before the provider is the same mistake one layer down. |
| **Adapter** | `companion/voice.py`. |
| **Schema migration** | `companion-provider.schema.json` not carried over. |
| **Tests** | `test_voice_character.py`. |
| **Compatibility impact** | None. |

## `companion/characters.py`

| | |
| --- | --- |
| **Runtime-core** | Nothing. |
| **UX-shell** | A full character-package importer: manifest schema, zip validation, symlink and traversal refusal, compression-ratio checks, animation maps, 15 required animation states. |
| **Chosen authority** | New, deliberately much smaller: one static asset, validated. |
| **Donor behaviour retained** | The *checks* on the one asset that ships: no symlink, no executable bit, bounded size, declared type. |
| **Donor behaviour discarded** | The importer, the archive reader, the manifest and the animation map — **deferred, not rejected.** §14 says the character-renderer branch implements secure package import, and a loader for third-party desktop content deserves to be reviewed as that rather than arriving as a supporting file in a UX integration. |
| **Adapter** | `load_static_character` + `describe_phase`. |
| **Schema migration** | `companion-character-package.schema.json` moves to the character-renderer branch with the importer. |
| **Tests** | `test_voice_character.py::StaticCharacterTests`, including five active-content refusals. |
| **Compatibility impact** | None. |

## `companion/cli.py`

| | |
| --- | --- |
| **Runtime-core** | `bunny-os companion` — sessions, session, task, approvals, recover, run-demo. Every command returns a document; nothing prints. |
| **UX-shell** | A `main(program)` dispatcher shared by `bunny-companion` and `bunny-companion-service`. |
| **Chosen authority** | Runtime-core. |
| **Donor behaviour retained** | The two separate entry points, kept as what they are: `/usr/libexec/bunny-companion-service` runs the runtime, `/usr/bin/bunny-companion` opens a window. |
| **Donor behaviour discarded** | One dispatcher deciding which of the two it is from `argv[0]`. That is how a client comes to be able to start a runtime. |
| **Adapter** | New subcommands: `health`, `presentation`, `serve`, `shell`, `migrate-ux-store`, `run-integration-slice`. |
| **Schema migration** | None. |
| **Tests** | Existing `test_cli.py`. |
| **Compatibility impact** | `bunny-os companion` gains commands and loses none. |

## `companion/protocol.py`

| | |
| --- | --- |
| **Runtime-core** | Nothing. |
| **UX-shell** | JSON-lines over `AF_UNIX` with a loopback fallback, `SO_PEERCRED`, request and response bounds, six commands. |
| **Chosen authority** | New, canonical, rewritten. |
| **Donor behaviour retained** | Most of the transport design, and it was good: newline-delimited JSON, the size bounds, the peer check, the loopback-plus-token fallback, the duplicate-runtime probe and the refusal to replace a non-socket path. |
| **Donor behaviour discarded** | (a) `dispatch` reading `command` and branching in one long chain — replaced by a declared operation table with per-operation parameter specs, so an undeclared parameter is *refused* rather than ignored. (b) A token compared with `!=`, which leaks it a byte at a time to a local process that can reconnect; now `hmac.compare_digest`. (c) `schemaVersion` mismatch as a generic `ProtocolError`; now a distinct `unsupported_version`, because a downgrade that succeeds is a downgrade attack. |
| **Adapter** | `RuntimeGateway`. |
| **Schema migration** | New `companion-protocol.schema.json`. |
| **Tests** | `test_protocol_ipc.py` — 37 tests. |
| **Compatibility impact** | None. |

## `companion/gtk_shell.py`

| | |
| --- | --- |
| **Runtime-core** | Nothing. |
| **UX-shell** | GTK 4 application with a view model, task panel, Approval Centre, captions, character picture and a window policy. |
| **Chosen authority** | New, rewritten against the canonical projection. |
| **Donor behaviour retained** | The layout, the panel decomposition, the header-bar size controls, the accessible-property calls, the 750 ms poll, and the decision to keep a `CompanionViewModel` separate from the widgets. |
| **Donor behaviour discarded** | (a) The view model reading raw `task`/`events` documents and deriving the caption itself — it now consumes the projection, so there is one interpretation of the record. (b) `_clear_dynamic` walking the body box looking for a sentinel widget; the dynamic panels are now in their own container. (c) Rendering `approval.to_json()` as the resolution payload, which sent display fields back as though they were binding fields — the protocol's strict validation refuses that, and `binding()` is now a separate method. |
| **Adapter** | `CompanionViewModel` over `CompanionClient`. |
| **Schema migration** | None. |
| **Tests** | `test_integration_slice.py::ClientLifecycleTests`; the widget layer is untested and said to be. |
| **Compatibility impact** | None. |

## Files taken from the donor with only licence and path changes

- `shell/assets/companion/default-bunny.svg` — the project's own asset, GPL, unchanged in substance.
- `shell/components/applications/art.comrade.BunnyCompanion.desktop` — reworded comment and keywords.

## Files with the same name and no shared content

- `systemd/user/bunny-companion.service` — rewritten: more hardening directives, a `ConditionPathExists` for the capability runtime, and a different `ExecStart` contract.
- `services/bunny-companion/bunny_companion_service.py` — rewritten: builds a `CompanionService` directly rather than dispatching through the CLI by program name.
- `shell/services/bin/bunny-companion` — rewritten: probes for a runtime and refuses to become one.
