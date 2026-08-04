# Companion runtime integration — report

The headless runtime core and the GTK UX prototype, reconciled into one
companion with one authority for everything that owns state.

The architecture notes are in [`docs/COMPANION_INTEGRATION.md`](docs/COMPANION_INTEGRATION.md),
the file-by-file reconciliation in [`docs/COMPANION_OVERLAP_MATRIX.md`](docs/COMPANION_OVERLAP_MATRIX.md),
and the security work in [`COMPANION_INTEGRATION_SECURITY_REVIEW.md`](COMPANION_INTEGRATION_SECURITY_REVIEW.md).
This is the account of what was done and what it measures.

---

## 1. Starting branch and SHA

| | |
| --- | --- |
| Branch at start | `feature/companion-runtime-core` |
| Commit | `2f39d58ca2957f01615fc7ccb0bd14d7dd76c1da` |
| Expected | `2f39d58ca2957f01615fc7ccb0bd14d7dd76c1da` — **verified against the repository before any file was touched** |
| Working tree | clean |

## 2. Integration branch and lineage

| | |
| --- | --- |
| Branch | `feature/companion-runtime-integration` |
| Created from | `feature/companion-runtime-core` at `2f39d58c` |
| Parent commit | `2f39d58ca2957f01615fc7ccb0bd14d7dd76c1da` |

No commit was made to either source branch. `feature/capability-image-integration`,
Commit C′, the hosted reproducibility evidence, the qualification target metadata
and PR #26's evidence history are untouched — none of those paths appears in this
branch's diff.

## 3. Runtime-core head

`2f39d58c` — "Add companion demo command". One commit ahead of the merge base.

## 4. UX donor head

`4896be5b246bd735c6dbf4746382c03b08103404` — "Document and verify the companion
vertical slice". Eleven commits ahead of the merge base.

## 5. Branch-divergence analysis

Merge base: `ff751ab7c37cfcf4725c559e9c43443f062d8351` ("Apply the capability
plan"), which is on both.

| Branch | Commits ahead | Content |
| --- | --- | --- |
| `feature/companion-runtime-core` | 1 | the headless demo command |
| `codex/companion-runtime-ux-shell` | 11 | 8 capability-image-integration commits (`5325f7f`…`9d3b0ad`, including Commit C′ and its evidence) + 3 companion UX commits (`273a967`, `ac87a84`, `4896be5`) |

Only the last three are companion work. The eight capability-image commits
belong to `feature/capability-image-integration` and were **not** taken: this
branch does not touch `build/inputs/qualification-target.json`,
`qualification/capability-integration/**`, `capability/apply/**` or
`capability/supervisor.py`.

## 6. Overlap matrix

Twelve overlapping concerns, each with a reconciliation record giving the
runtime-core implementation, the UX-shell implementation, the chosen authority,
what donor behaviour was retained, what was discarded and why, the adapter, any
schema migration, the tests and the compatibility impact. Full text in
[`docs/COMPANION_OVERLAP_MATRIX.md`](docs/COMPANION_OVERLAP_MATRIX.md).

| Concern | Authority | Donor outcome |
| --- | --- | --- |
| `runtime.py` | runtime-core | second runtime discarded; snapshot idea kept as `get_presentation_state` |
| `events.py` | runtime-core | vocabulary discarded; per-event human sentence kept |
| `store.py` | runtime-core | SQLite discarded; archived rather than imported |
| `approval.py` → `approvals.py` | runtime-core | binding-returned-with-the-answer kept; `cancel_task`-as-a-decision discarded |
| `state.py` → `presentation.py` | new canonical | phase vocabulary and replay kept; the transition *table* discarded |
| `model.py` → `task.py`/`session.py` | runtime-core | display decomposition kept; task model discarded |
| `coordination.py` | runtime-core | scheduler discarded |
| `providers.py` | split | voice argv and microphone rule kept; provider descriptors discarded |
| `characters.py` | new, smaller | asset checks kept; importer deferred to the renderer branch |
| `cli.py` | runtime-core | two entry points kept; `argv[0]` dispatch discarded |
| `protocol.py` | new canonical | transport design kept; open dispatch, `!=` token compare and silent downgrade discarded |
| `gtk_shell.py` | new canonical | layout and view-model split kept; raw-record interpretation discarded |

**No module in the package now owns state that another module also owns.**

## 7. Canonical authority decisions

Sessions, tasks, task lifecycle, event identity, ordering, integrity, replay,
persistent history, executor ownership, reviewer restriction, approval binding,
cancellation, recovery, privacy classification, cost limits, capability routing
and the CLI are all runtime-core, unchanged in substance.

Three are new and canonical: presentation state (`companion/presentation.py`),
local IPC (`companion/protocol.py`) and service lifetime
(`companion/service.py`).

`tests/companion/test_integration_authority.py` parses the whole package on
every run and asserts that exactly one class defines `submit_task`+`run_task`,
exactly one defines `save_task`+`load_task`, exactly one defines
`hashed_material`+`computed_hash`, that no module but `migration.py` imports a
database driver, that nothing unpickles, evaluates or reaches a shell, and that
the presentation layer imports no decision-making module.

## 8. File-by-file changes

**New (21):**

```
companion/presentation.py          the canonical projection
companion/protocol.py              envelope, socket, client
companion/service.py               runtime service, gateway, interactive consent
companion/gtk_shell.py             view model + GTK 4 window
companion/voice.py                 local voice, microphone boundary
companion/characters.py            static character loading and validation
companion/migration.py             donor SQLite archive/rollback
companion/vertical_slice.py        the 27-step integrated slice
schemas/companion-presentation-state.schema.json
schemas/companion-protocol.schema.json
systemd/user/bunny-companion.service
services/bunny-companion/bunny_companion_service.py
shell/services/bin/bunny-companion
shell/components/applications/art.comrade.BunnyCompanion.desktop
shell/assets/companion/default-bunny.svg
scripts/companion_measure.py
docs/COMPANION_INTEGRATION.md
docs/COMPANION_OVERLAP_MATRIX.md
COMPANION_INTEGRATION_SECURITY_REVIEW.md
COMPANION_INTEGRATION_REPORT.md
tests/companion/{test_presentation_projection,test_protocol_ipc,
                 test_integration_authority,test_voice_character,
                 test_migration_and_recovery,test_integration_slice}.py
```

**Modified (7):**

| File | Change |
| --- | --- |
| `companion/approvals.py` | `prepare`/`seek_consent` split out of `raise_request`; `invalidate_for_task` also asks the store |
| `companion/runtime.py` | emits `approval_requested` before consent is sought; pause protection in `_stopped`, `_save_running_task`, `_plan_and_execute`, `_execute_plan`; `pause_task` withdraws outstanding questions; `resume_task` writes authoritatively; `task_created` declares its runtime-fact fields |
| `companion/store.py` | bounded retry on reads that meet a projection mid-replacement |
| `companion/cli.py` | `health`, `presentation`, `serve`, `shell`, `migrate-ux-store`, `run-integration-slice` |
| `build/scripts/install-root.py` | installs `capability`, `companion`, the libexec entry point and the character asset |
| `config/systemd/60-bunny-os-user.preset` | enables `bunny-companion.service` |
| `release/validation.py` | one alias so the validator can resolve `bunny-companion-service` to its source, as it already does for `bunny-update-agent` |
| `Makefile` | `companion-slice`, `companion-measure` |

Both changes outside `companion/` were made because `scripts/task.py validate`
refused the branch: the unit named a program the validator could not resolve, and
the protocol schema declared no top-level `type`. Both are now fixed and
`validate` passes.

Every change to `runtime.py`, `approvals.py` and `store.py` was made because a
test found a defect; each is recorded in §4 of the security review with the
failure it fixes.

## 9. Schema unification

| Schema | Authority | Status |
| --- | --- | --- |
| `companion-core-session` | canonical | unchanged |
| `companion-core-task` | canonical | unchanged |
| `companion-core-event` | canonical | unchanged |
| `companion-core-reviewer-observation` | canonical | unchanged |
| `companion-presentation-state` | presentation only | **new** |
| `companion-protocol` | transport envelope | **new** |

The donor's `companion-state`, `companion-task`, `companion-event`,
`companion-approval`, `companion-provider` and `companion-character-package`
were **not** carried over. Three duplicated canonical authority; the approval one
is subsumed; the provider one describes adapters that do not exist and would be a
shape for one to be poured into without review; the character one goes with the
importer to the renderer branch. Since none ever shipped from this line, there
are **no deprecated schemas and no compatibility aliases** — there is nothing to
be compatible with.

Both new schemas carry `$id`, a version, strict `required`, bounded strings and
arrays, and `additionalProperties: false`. Tests validate every prefix of a real
run's projection against the presentation schema, validate real requests and
responses against the protocol schema, and assert the protocol schema's
operation enum equals the implemented table exactly.

## 10. Persistence decision

**The runtime-core append-only event store remains canonical.** The nine-dimension
evaluation §8 asks for is in `docs/COMPANION_INTEGRATION.md` §8. The decisive
points: the donor's SQLite has no integrity chain, so ordering and corruption are
untestable properties of it; and a database engine inside a 64 MB budget is a
dependency taken for familiarity.

No index was added — nothing yet needs one. Cross-session querying is a linear
scan and is listed as a known limitation with the fix named (a derived index
beside the stream, not a different authority). An AST test asserts no module but
`migration.py` imports a database driver, because that is how the decision would
actually be reversed.

## 11. Approval decision

One authority: `ApprovalGate` over `CompanionApprovalStore`, built on the
existing `capability.apply.approval` contract.

The binding is: request id, session id, task id, plan id, transition id,
provider, destination, data classification, cost, and (where recorded)
destination fingerprint. Expiry is bound and validated **from the runtime's
record rather than the client's claim**.

Three layers, and a client is outside all of them: the gateway checks the claim
against the recorded request; `InteractiveConsent` carries only
granted/denied/nothing; the gate checks the recorded reference against the plan
about to run, with a per-run consumed set.

Refusals verified: expired, replayed, wrong task, wrong plan, wrong step, wrong
action, changed provider, changed destination, changed cost, changed
classification, fabricated request id, and a decision that is neither granted nor
denied. The UI never touches an approval file.

## 12. IPC protocol

Unix socket at `$XDG_RUNTIME_DIR/bunny-companion/runtime.sock`, mode 0600, in a
directory mode 0700, `SO_PEERCRED` peer check. 64 KiB request, 4 MiB response,
30 s timeouts, one newline-terminated JSON object each way, schema version 1 with
no negotiation. Thirteen operations from a closed table; parameters declared per
operation and strictly validated; no pickle, no `eval`, no shell, no attribute
lookup from the wire. Structured errors from a fixed code list, bounded to one
sentence.

## 13. Presentation projection

A pure fold over canonical events, with §12's mapping and §12's priority order
(asserted as a subsequence of the implemented order). Every canonical event type
and every canonical task state is mapped, checked against the runtime's own
constants. Redacted at the `ui` ceiling; bounded lists; monotonic progress;
markup neutralised once at the point of production. A client can fold the same
events and reach the same state — verified from a single response, so the
comparison is not a race.

## 14. GTK integration

Two halves: `CompanionViewModel` (no GTK, the whole of the behaviour) and
`BunnyCompanionApplication` (the widgets, no decisions). Centre/docked/compact,
task panel, Approval Centre, speech bubble, captions, text-only view, hide,
restore, minimise, keyboard navigation, screen-reader labels, reduced motion
(no animations declared at all), high-contrast via named system colours.

A refresh never touches focus; only an approval brings the window forward, and
that is decided by the phase. Absolute Wayland placement is not claimed and
`absolute_placement_available` is `False` with no path that sets it otherwise.

## 15. Static-character integration

One original GPL asset, transparent, no external reference, no font, no script.
Closed path list; symlinks refused; SVG/PNG only; size-bounded; executable bit
refused; five classes of active content refused. `describe_phase` gives the state
in words for every phase, so text-only is the same surface without the picture.
A missing asset is not an error. The package importer is deferred to the
character-renderer branch, deliberately.

## 16. Voice integration

Local Speech Dispatcher / eSpeak NG / platform voice. Argument arrays, never a
shell string, with `--` before the text. Bounded input, refused rather than
shortened when oversized. Cancellation per utterance and in bulk. No remote
transmission, no cloning, no upload, no commercial dependency. Every failure is
an outcome; **voice failure cannot fail a task**, because the caption is produced
and displayed first and nothing consults the speech result except the speaking
indicator.

## 17. Microphone boundary

No recognition is implemented and none is pretended. The boundary is: nothing at
start-up, explicit activation as a required argument, indicator raised before the
provider is reached and cleared in `finally`, separate consent for an
always-listening mode, approval for any recogniser that would send audio off the
device, one interaction at a time. `AbsentSpeechRecognition` raises rather than
returning an empty transcript.

## 18. systemd user service

One service, `bunny-companion.service`, starting `/usr/libexec/bunny-companion-service`
in the graphical session. `RuntimeDirectory=` 0700 socket directory,
`StateDirectory=` 0700 store, `UMask=0077`, `RestrictAddressFamilies=AF_UNIX`,
`NoNewPrivileges`, `ProtectSystem=strict`, `MemoryDenyWriteExecute`,
`SystemCallFilter=@system-service`, `MemoryMax=128M`, bounded restart,
`TimeoutStopSec=15s`. The desktop entry launches a *client* that refuses to
become a runtime. There is no second service owning task state.

## 19. Migration behaviour

Archive, not import, for the reasons in §9 of the architecture notes. Dry run by
default; the copy is the backup and is digest-verified; every row transcribed;
a manifest written; nothing enters `sessions/`; the canonical store is never
opened for writing; the donor database is never moved or deleted; importing
twice is refused; rollback removes only the archive and refuses a directory it
did not write. Tasks the donor record cannot settle stay `uncertain`; approvals
without a complete binding are not copied and are listed with the missing field.

## 20. Security-test results

All twenty-three items in §21, plus three more, pass. Four defects were found and
fixed during the work (double-escaped status text, a withheld privacy indicator,
a silently erased pause, and a withdrawal that missed the window it most needed
to cover), and two risks are accepted and named (the developer loopback
transport; the projection not being authenticable on the wire). Full detail in
`COMPANION_INTEGRATION_SECURITY_REVIEW.md`.

## 21. Complete test results

Host: Windows 11 (10.0.26200), CPython 3.14.6, `jsonschema` present.

| Suite | Tests | Result |
| --- | ---: | --- |
| `tests/companion` (all) | **346** | **OK**, 3 skipped |
| — pre-existing runtime-core tests | 202 | OK (unchanged, and unchanged in content) |
| — `test_presentation_projection.py` | 39 | OK |
| — `test_protocol_ipc.py` | 37 | OK (2 skipped: platform-specific peer checks) |
| — `test_voice_character.py` | 30 | OK (1 skipped: symlink creation) |
| — `test_integration_authority.py` | 15 | OK |
| — `test_migration_and_recovery.py` | 15 | OK |
| — `test_integration_slice.py` | 8 | OK |
| `scripts/task.py test-capability` | 697 | OK |
| `scripts/task.py validate` | 48 schemas, 22 units, 531 files | **PASS** |
| `companion --simulate laptop run-demo` | 21 steps | passed |
| `companion run-integration-slice` | 27 steps | passed |

The full companion suite was run **six consecutive times** with no failure, after
the two intermittent failures found during development were traced and fixed —
one to a real defect (the withdrawal gap) and one to a test that compared two
calls and so measured the gap between them.

The three skips are platform-conditional and named where they occur; none skips a
*property*, only a check that this host cannot perform.

## 22. End-to-end vertical-slice result

`bunny-os companion run-integration-slice` — **27/27 steps, passed, no failures.**

Start the service; open a client; create a session; submit a harmless local task;
the runtime records it; the capability bridge evaluates eligibility; the
deterministic local executor is selected; the presentation reaches planning; an
approval is requested; the Approval Centre displays it with its binding and
alternatives; **an answer with an altered destination is refused with
`approval_mismatch`**; the honest answers are accepted (two of them — the
reviewer forces a replan which supersedes the first consent); operations are
performed by the runtime; progress reaches the surface; an observation-only
reviewer produces an observation; the client displays it with its authority
stated; the task completes; the character reflects the canonical state; the
caption carries the result; local voice speaks where available and the task is
unaffected either way; the client is closed; the runtime is still running; a new
client reopens; the missing events are replayed into its own projection and agree
with the served state; the completed result is unchanged by value; the runtime is
restarted; the completed state and result are still unchanged.

No network, provider or credential. The GTK **widget** layer is not exercised and
the report says so in its own output.

## 23. Performance results

Measured by `make companion-measure` on the host above. **This host only. No
Raspberry Pi, ARM, 64 MiB full-system or GPU figure is produced or implied** —
the measurement program has no code path that produces one.

| Measurement | First | Median | Max |
| --- | ---: | ---: | ---: |
| `health` round trip | 4.6 ms | 1.4 ms | 15.3 ms |
| Task submission | 12.0 ms | 12.3 ms | 37.8 ms |
| Event-to-UI (`get_presentation_state`) | 14.6 ms | 10.8 ms | 22.0 ms |
| Event replay (`get_events`, 500) | 21.4 ms | 12.6 ms | 37.9 ms |
| Session creation | 33.0 ms | 13.1 ms | 33.0 ms |
| Client first connect | 31.7 ms | 31.7 ms | 75.4 ms |
| Client refresh | 10.0 ms | 9.9 ms | 27.7 ms |

| Measurement | Value |
| --- | --- |
| Runtime restart (bind + full recovery pass + worker) | 118.7 ms |
| Service stop | 197.8 ms |
| Store growth per task | 20,792 bytes (207,915 bytes across 10 tasks) |
| Events per task | 26 |
| Approval-response latency | one `resolve_approval` round trip (≈ submission latency) plus the worker's wake, which is immediate — the waiter is an event, not a poll |

**Not measured, and why:**

- *Runtime idle, GTK idle and combined idle memory*: this host has no `/proc`, so
  resident memory is not measurable. The program reports `null` and says so
  rather than substituting Python's heap accounting, which measures a different
  thing. These must be taken on Linux before any memory claim is made.
- *GTK idle memory and window latency*: the window needs a compositor.
- *Voice process overhead*: no local synthesiser on this host.

All latencies are over the **loopback-TCP developer transport**, which is slower
and noisier than the Unix socket that ships. They are an upper bound on the real
figures, not an estimate of them.

## 24. Build-impact classification

**Build-affecting.** This branch changes `build/scripts/install-root.py` to
install the `capability` and `companion` packages, `/usr/libexec/bunny-companion-service`,
a user unit, a desktop entry, a launcher and the character asset; and changes the
user preset to enable the service.

It is **not** covered by candidate `79bb99d`, Commit C′, the capability H1/H2
hosted evidence, or any previous visual prototype reproducibility measurement.
**No reproducibility candidate was created**, per §26. Schema unification, runtime
authority, store authority, approval unification, IPC, the GTK client, the
vertical slice, the security review, the performance measurement and the
documentation are complete; a qualification cycle for this line has not begun and
nothing here should be read as one.

## 25. Known limitations

1. One worker thread; a task parked on an approval holds it. Answering or
   cancelling frees it and neither goes through the worker.
2. The GTK widget layer has no automated test. Everything below it does.
3. The loopback-TCP transport is a developer fallback, not what ships.
4. No speech recognition behind the microphone boundary.
5. No animated 2D or 3D renderer, and no provider adapter of any kind.
6. Cross-session querying is a linear scan.
7. Pause takes effect at the next phase boundary, and a pause issued the instant
   a question appears may record the phase before the question. Both are
   resumable and no work is lost.
8. Memory figures are unmeasured on this host.

## 26. Unverified assumptions

- **That the Unix-socket path performs like the loopback path, only better.**
  Untested: this host has no `AF_UNIX`. The code path differs and must be
  measured on Linux.
- **That `SO_PEERCRED` behaves as expected on the installed image.** The refusal
  logic is unit-tested with a synthetic failure; the success path has never run
  on a real Linux socket here.
- **That the systemd unit starts cleanly.** It is syntactically checked by the
  repository's unit validation, but no installed system has run it. In
  particular `RestrictAddressFamilies=AF_UNIX` with `SystemCallFilter=@system-service`
  has not been verified against a live `systemd --user`.
- **That the GTK window renders correctly.** No compositor was available. The
  widget code is written against the GTK 4 API and has never been executed.
- **That 128 MiB is the right `MemoryMax`.** Chosen, not measured.
- **That the store's growth of ~20 KiB per task holds at scale.** Measured over
  ten tasks in one session; retention has not been exercised at its ceiling.

## 27. Remaining work for animated 2D

A renderer; a frame source; an animation-state map from the presentation phase; a
frame budget tied to the capability signals; the character-package importer (on
the renderer branch) to supply anything but the shipped static asset; and the
addition of `animated-2d` to `IMPLEMENTED_PRESENTATIONS` — which is the single
line that would make the presentation state start claiming it, and should be the
*last* thing done rather than the first.

## 28. Remaining work for 3D

Everything in §27, plus a GPU capability signal the router is prepared to act on
(`gpuAvailable` exists; VRAM does not), a mesh and skeleton format in the package
schema, a renderer that can degrade mid-frame under the pressure signals the
presentation layer already computes, and a memory budget that survives the 64 MB
target — which on present evidence it will not, so the honest first step is a
measurement showing which machines could support it at all.

## 29. Remaining work for real AI providers

The runtime is already shaped for this and deliberately empty:
`ExecutorDeclaration` states cost class, locality and privacy ceiling;
`capability_bridge` routes on them; `requirements_for` derives the approvals;
`RemoteProvider` is a parameter the runtime accepts and is always `()`.

What is missing, in order: a credential store that the event sanitizer's
forbidden-field list is tested against; a provider adapter implementing
`Executor` without a `run` method (it may only ever *propose*); a health and
authentication model distinguishing "not installed" from "signed out" from
"answering with nonsense"; usage and cost accounting that feeds
`CoordinationPolicy.check_cost` before the spend rather than after; and a
provider descriptor schema — which was deliberately *not* carried over from the
donor, because a descriptor with an `authentication_state` field, shipped before
the adapter, is where a credential eventually appears.

## 30. Reproducibility implications

This branch adds Python source, a unit, a desktop entry, a launcher and one SVG
to the image. All are deterministic text installed with fixed modes, so the
expected effect on reproducibility is a changed but stable set of layer digests.

That is an expectation, not a measurement. **No reproducibility run was
dispatched and no candidate was created**, per §26. Before any such claim:

1. this branch needs its own qualification cycle, independent of Commit C′;
2. `__pycache__` must be confirmed absent from the installed tree. `copy_tree`
   already skips any path with `__pycache__` in its parts, and the local package
   directory does contain one after a test run — so the exclusion is doing real
   work here rather than being decorative, and a build should confirm it;
3. the two `copy_tree` calls added for `capability` and `companion` will conflict
   textually with `feature/capability-image-integration` if that branch adds the
   capability one too; the resolution is trivial and expected, and is noted here
   so it is not mistaken for a semantic conflict;
4. nothing in this branch may be used to support a claim about
   `79bb99d`, Commit C′ or the H1/H2 evidence, all of which remain untouched.

**This branch requires its own future qualification cycle and has not had one.**
