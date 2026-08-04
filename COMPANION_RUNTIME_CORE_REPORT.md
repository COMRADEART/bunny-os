# Bunny Companion Runtime Core — implementation report

Phase: the first headless companion runtime.
Branch: `feature/companion-runtime-core`.
Date: 2026-08-03 – 2026-08-04.

---

## 1. Starting branch and commit

| | |
|---|---|
| Branch at the start of the session | `codex/companion-runtime-ux-shell` |
| Commit at the start of the session | `273a967` — *Integrate Bunny Companion runtime into the desktop build* |
| Working tree at the start | dirty: 9 modified files under `companion/`, `tests/companion/` and `docs/` |

The uncommitted work belonged to the branch it was on, not to this phase. It was
preserved with `git stash push -u` before anything else happened, under the
message *"codex/companion-runtime-ux-shell WIP preserved before branching to
feature/companion-runtime-core"*, and the branch was left at `273a967`.

**A concurrent session then committed to that branch.** During this work
`codex/companion-runtime-ux-shell` advanced `273a967 → ac87a84 → 4896be5`. Those
two commits are not mine — nothing in this session ran `git commit` against that
branch — and they contain the same hardening the stash held. Comparing the stash
against the new tip leaves only a six-line difference in
`tests/companion/test_vertical_slice.py`, where the *committed* version is the
newer shape. **The stash is therefore superseded and can be dropped** with
`git stash drop`; it is left in place because dropping it is irreversible and is
the user's call.

## 2. New branch and commit lineage

```
main (70995ea)
  └─ … feature/capability-runtime (96ca61f)
       └─ feature/capability-applicator (ff751ab)   ← base
            └─ feature/companion-runtime-core        ← this work
```

Base chosen: **`feature/capability-applicator` (ff751ab)**, not `main` and not the
current branch. Reasons:

* `main` has no `capability/` package at all, and §11 and §12 require the
  existing capability runtime and the existing `ApprovalStore` interface;
* `feature/capability-applicator` has both and has **no** `companion/` code, so
  this is genuinely the *first* headless companion runtime rather than an
  addition to an existing one;
* the current branch already ships a GTK shell, character packages and voice —
  all of which this phase is explicitly forbidden to implement — so branching
  from it would have made deliverable 12 ("No companion UI or character artwork
  is required") untrue by construction.

### Branch safety

| Requirement | Status |
|---|---|
| Record the starting branch and commit | done — §1 above |
| Capability qualification branch clean | `feature/capability-image-integration` at `43316cb`, **byte-identical before and after**; never checked out for writing, never merged, never rebased |
| Create `feature/companion-runtime-core` | done, from `ff751ab` |
| Commits exist only on the new branch | **no commits have been made yet** — the work is staged in the working tree of `feature/companion-runtime-core` for review before committing |
| Commit C′, qualification targets, hosted evidence, PR #26 untouched | untouched; `qualification/`, `evidence/`, `release/` and `.github/` carry no changes |
| Classified as a new build-affecting development line | yes — §21 |
| No claim of coverage by the capability reproducibility candidate | explicitly disclaimed — §21 |

## 3. Repository assessment

* `capability/` (14,806 lines) is the established capability runtime:
  `discovery → inventory → scores → budgets → policy → plan → adaptation`, plus
  `capability/router.py` which decides local-versus-remote **per task** and
  already enforces *local incapability is never an argument for remote
  execution*. This phase reuses it and adds no second hardware classifier.
* `capability/apply/approval.py` defines `ApprovalRequest`, `ApprovalResponse`
  and the `ApprovalStore` protocol, and states the safe-default rule. This phase
  builds on that interface rather than defining a new one.
* `capability/apply/approval_store.py` (`DurableApprovalStore`) exists on
  `feature/capability-image-integration` and on the codex branch, **not** on the
  chosen base. Rather than take a dependency on a branch under qualification,
  `companion/approvals.py` implements the published `ApprovalStore` protocol
  itself.
* `tools/bunny-os/bunny_os/cli.py` is the management CLI; subsystems attach via
  `add_arguments(sub)` / `dispatch(args)` and return JSON-serialisable
  documents. `companion` follows that pattern exactly.
* `scripts/task.py` dispatches `test-<component>` to
  `tests/<component>`; `test-companion` needed only a name in the choice list.
* The `codex/companion-runtime-ux-shell` companion (6,839 lines) is a *different*
  design — agents, providers, presentation, characters, GTK — and is not reused
  here. It remains available on its own branch.

## 4. Architecture summary

```
User request
    ↓  companion/runtime.py  submit_task()
Companion session ─────────── companion/session.py
    ↓
Task creation ─────────────── companion/task.py
    ↓
Task classification ───────── companion/runtime.py  classify_request()
    ↓
Capability and policy ─────── companion/capability_bridge.py → capability.router
    ↓
Executor selection ────────── companion/executor.py  + coordination lease
    ↓
Approval when required ────── companion/approvals.py → capability.apply.approval
    ↓
Execution events ──────────── companion/tools.py  ToolBroker (the only door)
    ↓
Reviewer observations ─────── companion/reviewer.py  (observation-only)
    ↓
Result
    ↓
Persistent event history ──── companion/events.py + companion/store.py
```

Three properties everything is arranged around:

1. **The event stream is the truth.** Session and task documents are projections
   and are rebuilt from the stream whenever they disagree with it.
2. **Uncertainty never becomes action.** Unanswered approval → denial.
   Unestablished capability → not a capability. Missing completion event →
   *unknown*, and unknown is never repeated.
3. **The executor acts and the reviewers only look.** One executor per task, held
   by a lease; reviewers get a frozen redacted value and nothing else.

## 5. File-by-file changes

### New — `companion/` (8,778 lines)

| File | Lines | Responsibility |
|---|---:|---|
| `__init__.py` | 76 | package doc, schema versions |
| `errors.py` | 177 | every refusal, typed |
| `privacy.py` | 404 | what may be stored; who may read it |
| `ids.py` | 138 | identifiers; derived operation keys |
| `clock.py` | 97 | wall time for the record, monotonic for deadlines |
| `states.py` | 244 | the 16-state lifecycle table |
| `events.py` | 597 | hash-chained append-only event record |
| `session.py` | 330 | session model, privacy and cost policy |
| `task.py` | 556 | task model, operation/approval/output/error references |
| `store.py` | 1074 | durable store: locking, atomicity, retention, migration |
| `executor.py` | 603 | executor contract + deterministic local executor |
| `tools.py` | 248 | the tool allowlist and the only door through it |
| `reviewer.py` | 256 | reviewer contract + deterministic local reviewer |
| `coordination.py` | 320 | ceilings, executor lease, review rounds |
| `capability_bridge.py` | 370 | capability runtime integration |
| `approvals.py` | 741 | consent binding and the durable approval store |
| `runtime.py` | 1284 | the orchestrator |
| `cancellation.py` | 210 | stopping as a recorded sequence |
| `recovery.py` | 366 | post-restart decisions |
| `demo.py` | 294 | the 21-step headless vertical slice |
| `cli.py` | 393 | the `bunny-os companion` command group |

### New — tests (3,203 lines, 202 tests)

`tests/companion/{__init__,support,test_sessions_tasks,test_events_store,`
`test_executors_reviewers,test_approvals,test_recovery_cancellation,`
`test_privacy_slice,test_cli,test_schemas}.py`

### New — schemas and docs

`schemas/companion-core-session.schema.json`,
`schemas/companion-core-task.schema.json`,
`schemas/companion-core-event.schema.json`,
`schemas/companion-core-reviewer-observation.schema.json`,
`docs/COMPANION_RUNTIME_CORE.md`, this report, and
`COMPANION_RUNTIME_CORE_SECURITY_REVIEW.md`.

### Modified — three files, additive only

| File | Change |
|---|---|
| `tools/bunny-os/bunny_os/cli.py` | import `companion_cli`, register its arguments, add one `elif args.command == "companion"` branch |
| `scripts/task.py` | add `"test-companion"` to the command choices (the existing `test-*` fallback does the rest) |
| `Makefile` | add `test-companion` and `companion-demo` targets and their `.PHONY` entries |

### New — CLI adapter

`tools/bunny-os/bunny_os/companion_cli.py` (39 lines), a thin adapter so the
tests exercise the same code the CLI runs.

## 6. Session schema

`schemas/companion-core-session.schema.json`. Fields: `sessionId`, `title`,
`createdAt`, `lastActivityAt`, `status` (`active|paused|closed`),
`activeTaskIds`, `completedTaskIds`, `privacyPolicy`, `costPolicy`,
`localityPreference`, `selectedExecutor`, `selectedReviewers`,
`capabilityPlanReference`, `eventStreamRevision`.

Defaults are the strict end: `defaultClassification: personal`,
`maximumRemoteClassification: internal`, `allowRemote: false`,
`localityPreference: device-only`, every cost limit `0`. `maximumRemoteClassification`
cannot be `secret` — there is no way to express that secret data may leave. Cost
limits have no "unlimited" value, because a spend authorised by omission is not
an authorisation. Create / load / resume / pause / close / recover are all
supported; §17 steps 18–19 demonstrate reload after restart.

## 7. Task schema

`schemas/companion-core-task.schema.json`. Every field the brief lists is
present. Three deserve comment:

* `originalRequest` is kept **in full and credential-scrubbed**, bounded at 8192
  characters *where it is accepted* rather than truncated where it is stored, so
  a request that is too long is refused rather than half-answered.
* `operations[]` is the idempotency ledger — `key`, `name`,
  `status ∈ {started, completed, failed, unknown}`, sequences, `recoveryNote`.
* `deadlineConsumedSeconds` stores a *consumed budget* rather than an instant,
  because monotonic time does not survive a reboot.

No field exists for credentials or hidden reasoning, and none can be added
through the executor contract, which returns only plans and outputs.

## 8. Event schema

`schemas/companion-core-event.schema.json`. Fields: `eventId`, `sessionId`,
`taskId`, `sequence`, `eventType`, `timestamp`, `producer`, `payload`,
`classification`, `auditReference`, `redactions`, `previousHash`, `eventHash`.

All 24 event types from the brief, plus `task_state_changed` for lifecycle moves
that carry no meaning beyond the move itself — added so that §5's "every
transition must produce a typed event" holds without a gap in the replay.

| Required property | How |
|---|---|
| Ordered per task | one stream per session, gapless sequence, filtered by `taskId` |
| Deduplicated | append refuses an event that does not follow the tip; `deduplicate()` drops exact repeats and raises on id conflicts |
| Replayable | §17 step 20; the demo replays 42 events and compares the result |
| Recoverable | `companion/recovery.py` |
| Bounded payload | 16 KiB total, 4 KiB per string, 128 items, 8 levels — **refused, not truncated** |
| Schema validated | required-field table per event type in `events.py`; JSON Schema in `schemas/` |
| Sensitive-field redaction | `privacy.sanitize()` inside `build_event()` — there is no other constructor |
| Corruption detection | SHA-256 chain over every field |
| Incomplete final writes | only a structurally incomplete *final* record is dropped, and the drop is reported |

`eventId` is derived from the stream position rather than minted. This was a
defect found by the tests: `SequentialIds` restarted after a restart and produced
colliding ids. A derived id is unique within its stream by construction.

## 9. Persistence design

```
<root>/store/store.json                      store descriptor and schema version
<root>/store/sessions/<id>/session.json      session projection (atomic replace)
<root>/store/sessions/<id>/stream.json       anchor, retention, migration record
<root>/store/sessions/<id>/events.jsonl      append-only chain, one JSON per line
<root>/store/sessions/<id>/tasks/<id>.json   task projections (atomic replace)
<root>/approvals.json                        approval questions and answers
```

No database, and the reason is recorded rather than assumed: a session's history
is an append-only sequence of small records read in order, which is a log; Bunny
OS targets 64 MB and the qualified base image carries no server. The documented
need that would reopen the decision is cross-session search.

| Requirement | How |
|---|---|
| Atomic append | write + `flush` + `fsync` under an exclusive session lock before the call returns |
| Locking | `fcntl.flock` → `msvcrt.locking` → `O_EXCL` lock file with a staleness timeout |
| Process restart | projections are rebuilt from the stream; §17 steps 18–21 |
| Truncated-write detection | a file not ending in `\n`, or a final line that will not parse |
| Schema migration | `migrate()` re-seals every event and records `fromVersions`, `toVersion`, `originalTipHash`, `newTipHash` in `stream.json` — a migration is a declared rewrite, not an undeclared one |
| Integrity validation | `validate()` per session; `verify_chain()` per stream |
| Bounded retention | `prune()` drops from the front and records the anchor hash the new head follows |
| Sanitized export | `export(session_id, audience=…)` renders through the audience ceiling |
| No invented events | only the final incomplete record is ever dropped; everything else raises |

Appending reads only the last record (`_fast_tip`) rather than the whole chain,
so a session is not quadratic in its own length; full verification happens on the
reads where it means something — open, replay, export, recover.

## 10. Executor interface

`companion/executor.py`. An executor **decides what should be done and does none
of it**. `Executor` has `health()`, `plan()`, `result()`, `cancel()` — and no
`run`. It is handed a `TaskContext` holding a redacted task view, the completed
operation keys, the previous round's observations and the remaining budget, and
**no** store, runtime, broker or approval store.

`ExecutorDeclaration` states: `executorId`, `providerId`, `implementationId`,
`local`, `supportedTaskTypes`, `supportsTools`, `supportsStructuredOutput`,
`supportsStreaming`, `supportsCancellation`, `supportsResume`,
`contextLimitTokens`, `costClass ∈ {free, metered, paid}`,
`maximumPrivacyClass`, `requiresAuthentication`. Undeclared fails closed;
`health()` separates availability, authentication and health because they fail
separately and call for different actions.

One implementation ships: `DeterministicLocalExecutor` — pure, local, free,
reproducible. **There is no commercial-provider adapter and no stub for one.**

## 11. Reviewer interface

`companion/reviewer.py`. Reviewers may inspect a redacted task, its plan and its
events, and return structured observations. They may not execute tools, modify
files, approve actions, control applications, change configuration, send task
data anywhere, or override the executor — enforced by what they are given
(`ReviewContext` is a frozen value with no capability at all) and, as a second
line, by `ToolBroker.invoke` refusing any caller of kind `reviewer` and
recording the attempt.

Observation shape is the brief's, field for field:

```json
{
  "reviewerId": "local.test-reviewer",
  "severity": "info",
  "category": "correctness",
  "summary": "The proposed output omits the requested validation step.",
  "suggestedAction": "Run validation before completion.",
  "evidenceEventIds": []
}
```

`reviewerId` is checked against the identity the runtime invoked, so a reviewer
cannot attribute a remark — or a disagreement — to another.

## 12. Coordination policy

| Rule | Mechanism | Default |
|---|---|---|
| Exactly one active executor per task | `ExecutorLeases`, refuses the second | — |
| Zero or more reviewers | supported; zero is a valid configuration | — |
| Review-round limit | `maximum_review_rounds` | 2 |
| Reviewer timeout | daemon thread + join | 5 s |
| Event-count limit | `maximum_events_per_task` | 500 |
| Tool-call limit | `maximum_tool_calls` | 32 |
| Cost ceiling | `cost_ceiling_units` | 0 |
| Execution deadline | `execution_deadline_seconds` | 300 s |
| Context-sharing policy | `reviewer_context_ceiling`, may only tighten | `internal` |
| Cancellation propagation | state machine: operations only in `executing` | — |

Reviewers cannot enter uncontrolled conversations: the `ReviewContext` is built
**once per round, before any reviewer runs**, and the same frozen value goes to
each. There is no channel between them. The executor may answer observations
with a new plan revision, and material disagreement is written as a
`reviewer_disagreement` event that is never retracted.

## 13. Capability integration

`companion/capability_bridge.py` contains **no hardware detection**. It
translates a task into `capability.router.TaskRequest`, calls `route()`, and
reads the §11 signals out of the same `Assessment` the router used — so the
decision and its explanation come from one measurement.

Signals recorded: `localAiEligible` / `localAiScore` / `localAiConfidence`,
`usableMemoryBytes`, `availableMemoryBytes`, `allocatableBytes`, `budgetViable`,
`cpuScore`, `gpuAvailable`, `gpuScore`, `networkOnline` / `networkOffline`,
`networkMetered`, `meteredNetworkAllowed`, `remoteExecutionEnabled`,
`remoteRequiresApproval`, `remoteAllowsSensitiveData`, `onBattery`,
`batteryPercent`, `powerSaving`, `thermalThrottled`, `preferLocal`,
`preferLowEnergy`.

Every translation narrows: `personal → sensitive` for the router, the *stricter*
of the task's and session's locality wins, `remote_allowed` is the session's
permission rather than the task's wish, and `user_approved` is always false.

The plan is recorded by `planId` **and** a `planFingerprint` over the plan id,
the signals and the task, so the decision can be recognised as stale.

If nothing is eligible the task is **blocked** with the router's own structured
reasons, and the reasons travel with the task's error record — not only in the
event payload — so `companion task inspect` answers "why can this not run".
There is no path by which a weak machine argues its way into remote execution.

## 14. Approval integration

Built on `capability.apply.approval.ApprovalStore`.
`companion/approvals.py::CompanionApprovalStore` implements that protocol and
persists with the same atomic-replace discipline as the event store; a question
is made durable **when it is asked**, not when it is answered.

Approvals are created for: remote execution, paid provider use, sensitive data
transfer, destructive operations, user-work interruption and any new external
destination. They are derived from the **tool and provider declarations**, not
from the executor's opinion — an executor that sets `requiresApproval: false` on
a destructive tool still produces a requirement.

Refused: expired, replayed, wrong task, wrong transition, superseded plan,
changed destination. **No response defaults to no action**; the default
`ConsentSource` is `RefusingConsent`, which records every question and grants
nothing.

Transition identifiers derive from the **plan fingerprint**, so an identical
replan asks the same question and a different plan asks a new one.

## 15. Privacy model

Classes: `public < internal < personal < sensitive < secret`.

Never stored, at any classification, for any audience: API keys, access/refresh/
id/bearer/auth/session/CSRF tokens, authorisation headers, credentials,
passwords, passphrases, cookies, chain-of-thought, scratchpads, internal
monologue, raw audio, microphone recordings, waveforms, screen content, screen
captures and framebuffers. Removal is recorded in the event's `redactions` field,
which is inside the hash.

| Audience | Ceiling |
|---|---|
| `executor` (on-device) | `secret` |
| `ui` | `sensitive` |
| `reviewer` | `internal` |
| `audit` | `internal` |
| `remote` | `internal` |

Above the ceiling, structure survives and content does not. Events are
classified by **what their own payload carries**, not by the task — otherwise a
reviewer of a `personal` task would find the executor's name and the memory
figures withheld and have nothing to review.

## 16. Cancellation model

First-class, and a recorded sequence rather than an exception: enter
`cancelling` (a state, so operations stop by the state machine); signal the
executor once without waiting; mark unsettled operations `unknown` (never
`failed`); withdraw pending approvals; keep partial output; emit
`task_cancelled`. Causes: `user`, `policy`, `timeout`, `capability_loss`,
`provider_loss`, `supervisor_shutdown`. Cancelling twice is harmless; a finished
task refuses.

## 17. Recovery model

Per session: validate the chain, find incomplete tasks, check the executor still
exists, inspect pending operations, invalidate approvals from before the
restart, resume only when supported and safe, otherwise park in `paused`,
`blocked` or `failed`, and record the decision as an event either way.

The load-bearing rule: an operation with a start and no settlement becomes
**`unknown`**, and the task returns to **`planning`** — never to `executing`.
`recovering → executing` does not exist in the transition table. Operation keys
are derived from `(task, plan, revision, index, name)`, so the same operation in
a replan carries the same key and can be recognised rather than repeated.

A session whose chain will not verify is reported and skipped; the others are
still recovered. Recovery is safe to run twice: a task already decided about is
reported `intact`.

## 18. CLI commands

All nine commands the brief lists exist, plus `task run`, `session pause/resume/
close` and `recover`. Every command returns a JSON document with an `effect`
field — `"read-only"` or a sentence naming what changed. `--simulate` and
`--inventory` are accepted and simulated output is labelled.

## 19. Test results

```
$ python3 scripts/task.py test-companion
Ran 202 tests — OK
```

| Module | Tests | Covers |
|---|---:|---|
| `test_sessions_tasks.py` | 29 | session/task models, the 16-state table, valid and invalid transitions, concurrent tasks, completion, pause/resume, restart |
| `test_events_store.py` | 39 | ordering, duplicates, out-of-order, truncated, corrupt, oversized, unknown type, migration (including refusal to launder a tampered chain), replay, retention, traversal |
| `test_executors_reviewers.py` | 31 | one-executor lease, unavailable, malformed plan and result, capability/privacy/cost incompatibility, reviewer boundary, timeout, malformed observation, disagreement, round ceiling, withheld context |
| `test_approvals.py` | 25 | requirement derivation, expired, replayed, wrong task, wrong plan, wrong transition, changed destination, denied, no response, superseded, durability across restart |
| `test_recovery_cancellation.py` | 28 | crash before / during / after an operation, stale approval, missing executor, corrupt store, non-repetition of unknown **and** completed acts, three cancellation windows, all six causes |
| `test_privacy_slice.py` | 30 | data classes, redaction across 35 concepts × 6 naming conventions, projection, bounds, capability binding, the vertical slice, reproducibility |
| `test_cli.py` | 13 | every command, effect labelling, audience rendering, JSON structure |
| `test_schemas.py` | 7 | schema/constant agreement; end-to-end conformance under `jsonschema` |

Whole repository: `python3 scripts/task.py test` → **2681 tests, 1 error**. The
one error is `tests.display_stack.test_evidence_gate.MutationTests.
test_duplicate_boot_check_is_load_bearing`, which fails with
`OSError: [WinError 1314] A required privilege is not held by the client` when
creating a symlink. **It is pre-existing**: it fails identically on the base
commit `feature/capability-applicator` with this branch's changes stashed, it is
a Windows privilege limitation rather than a defect, and it touches no file this
branch changes. `tests/capability` → 697 tests, OK.

Ten guarantees are **mutation-checked** — the guard is removed and the test is
confirmed to fail, so the test is known to be load-bearing rather than merely
passing: the six cancellation windows, the append retry, the terminal-task
guard, act-stable operation keys, and non-repetition after a crash. This is the
practice that made the incomplete fixes visible: a test that still passes with
its guard removed is not testing the guard, and one of mine did exactly that
until it was strengthened.

Store permissions were **measured on ext4** (Fedora under WSL, `umask 022`)
rather than inferred: every file 0600, every directory 0700, zero group- or
other-readable entries. Windows cannot express POSIX modes, so this could not
have been established on the development filesystem.

### Defects this work found during construction

Six, all caught by the tests rather than by inspection:

1. **Event-id collision across restarts.** `SequentialIds` restarted at 1 after a
   restart and produced ids that already existed in the stream. Fixed by
   deriving `eventId` from the stream position.
2. **The raw request was persisted unscrubbed.** `CompanionTask.create` scrubbed
   the display summary and stored `originalRequest` verbatim, so a credential
   typed into a request reached disk. Fixed with `privacy.scrub_text`.
3. **camelCase field names bypassed redaction.** `\bcookie` does not match
   `sessionCookie`. Fixed by splitting on case transitions — which turned out to
   be only half the problem; see H1 below.
4. **Failure handlers reverted to a stale task.** An exception unwound past the
   phase locals, so a blocked task was written without the approval reference
   recording what had been asked. Fixed by reloading the latest projection.
5. **An out-of-band cancellation mark was clobbered.** The runner wrote its own
   in-memory copy over a cancellation written by another process.
6. **A crash-recovery test was vacuous.** It used a hard-coded operation key
   that could never match a derived one, so it asserted non-repetition against a
   key nothing would ever produce.

### Defects the independent security review found

**Twenty-two across three rounds**, of which **twenty are fixed** and two are
accepted and documented. Round one found thirteen against the original code;
round two found four against round one's fixes; round three found five against
round two's fixes.

**Eight of the twenty-two were introduced or left behind by a previous round's
fix.** That is the number worth carrying forward from this phase: my
remediations were wrong or incomplete more often than I would have guessed, and
only re-reviewing them found it. One round-three finding — a schema version I
failed to bump — would have made every existing store permanently unreadable had
it shipped.

Full detail in `COMPANION_RUNTIME_CORE_SECURITY_REVIEW.md`. The ones that
mattered:

* **H1 — the redaction check missed every snake_case field name.** `_` is a word
  character in Python, so the `\b`-anchored half of the pattern never fired
  after an underscore. `client_secret`, `user_password`, `session_cookie`,
  `api_token`, `raw_screenshot` and eight more were stored verbatim. Round two
  then found the mirror image — `\bpasswords?\b` is itself *pass*+*word*, so
  `passWord` and `pass_word` still slipped. The test now enumerates separator
  placements at real word boundaries: 39 concepts, 496 spellings.
* **H2 — cancellation did not stop a running task.** Six distinct windows, found
  in three batches across all three rounds. The last and worst was the approval
  wait, where a real Approval Centre blocks — so it is where a task spends most
  of its time and where a user is most likely to press stop.
* **H3 — recovery repeated operations, including ones recorded `unknown`.** The
  idempotency key included the plan revision, so the skip branch was
  unreachable and the guarantee stated in three docstrings held nowhere. My
  replacement then joined its fields with a separator three executor-controlled
  fields could contain, so two *different* acts could collide.
* **H4 — the event log was created world-readable** (0644) while every other
  file was 0600. Now 0600/0700 throughout, measured on ext4.
* **N1 (High) — a schema version that was not bumped.** Adding a field to
  version 1's hashed material made every store written by the previous build
  unreadable: the integrity system reported legitimate data as tampering and
  `migrate()` saw no version change to act on. Now version 2, with the version
  table used by the reader as well as the migrator.
* **M1–M4, N3–N5** — failure text leaking above its ceiling, the task and
  session projections leaking in exports, `migrate()` laundering a tampered
  chain, `ReviewContext` frozen in name only so one reviewer could suppress
  another's finding, a non-atomic append that made concurrent cancels raise, a
  terminal task masking the real diagnostic, and a fail-open default.
* **L1** — the execution deadline was declared and never enforced.

Five docstrings claimed properties the code did not have. All five now say what
is true, and each records what was wrong — in a package whose value is
auditability, an overstated docstring is what the next reviewer trusts instead
of reading the code.

## 20. Headless vertical-slice result

```
$ bunny-os --json companion --simulate laptop run-demo
passed: true | network: none | provider: none | credentials: none
```

| | Step | Evidence |
|---:|---|---|
| 1 | start the runtime | store created |
| 2 | create a session | `ses-000001` |
| 3 | submit a harmless local task | `task-000001` |
| 4 | classify the task | `taskType=compute` |
| 5 | evaluate the capability plan | `planId=plan-359f0dbbf30b9e7c`, `localAiEligible=true` |
| 6 | select the deterministic local executor | `local.deterministic`, `local=true` |
| 7 | start planning | 2 revisions |
| 8 | request a harmless approval | `interrupt_user_work` |
| 9 | resolve the approval | `granted` (and one `expired` for the superseded plan) |
| 10 | execute a deterministic local operation | count-words, publish-notice, validate-count — three acts, each performed **once**. Before the idempotency-key fix this read `count-words, publish-notice, count-words, validate-count, publish-notice`: the revision re-ran work the record already proved done |
| 11 | emit progress events | 5 |
| 12 | invoke one observation-only local reviewer | `local.test-reviewer`, 0 tool attempts |
| 13 | record the reviewer observation | recorded, 1 disagreement |
| 14 | allow the executor to revise or continue | revision 2, 2 review rounds |
| 15 | produce a result | `result-…` |
| 16 | complete the task | `completed` |
| 17 | stop the runtime | — |
| 18 | restart it | new runtime, new clock, new id source |
| 19 | reload the session | `completed`, in `completedTaskIds` |
| 20 | replay all task events | 38 events, `chainVerified=true`, no incomplete tail |
| 21 | confirm the result is unchanged | `words=16; validation=consistent` before **and** after; output digests equal |

`run-demo --refuse-approval` runs the same slice with nobody answering: it stops
at step 9 with the task **blocked** and `notice.publish` never invoked.

The slice is reproducible — two runs in different directories produce the same
tip hash.

## 21. Build-impact classification

**This is a new build-affecting development line.**

`companion/` is new Python that would ship in the image, and
`tools/bunny-os/bunny_os/cli.py` changes the management CLI. Nothing here is
installed by the current image build yet — no `systemd/` unit, no
`config/tmpfiles` entry, no `install-root.py` change was added, deliberately, so
that this phase cannot alter an image while it is still moving.

**This work is not covered by Commit C′ and is not covered by the capability
reproducibility candidate or its qualification cycle.** No new reproducibility
candidate has been created, and none should be until this branch reaches a
defined integration milestone. `feature/capability-image-integration` is
unchanged at `43316cb`.

## 22. Known limitations

1. **The event chain is unkeyed.** Anyone who can write the store can recompute
   it. Detecting a hostile rewrite needs a signing layer, which is out of scope.
2. **A reviewer that hangs cannot be stopped.** The timeout frees the *task*, not
   the CPU; Python cannot safely interrupt an arbitrary call, so the worker is a
   daemon thread that keeps running.
3. **Consent does not survive a restart.** Monotonic expiry restarts with the
   machine, so approvals from a previous run are expired on load. The audit trail
   survives; the permission does not. A user must answer again.
4. **`run_task` is synchronous.** Concurrency *across* tasks works; a scheduler
   belongs with the UX shell.
5. **Classification is a regex**, chosen so this phase's stream is reproducible.
6. **Recovery rebuilds the operation ledger, not the whole document.**
7. **Retention prunes only on demand** — there is no background compaction.
8. **The `O_EXCL` lock fallback is weaker than `flock`**: it distinguishes a live
   holder from a dead one only by age.
9. **Directory `fsync` is a no-op on Windows**, so rename durability there rests
   on the filesystem. Bunny OS runs on Linux and gets the strong form.
10. **No systemd unit, no installed-image integration, no D-Bus or socket
    service.** The runtime is a library plus a CLI.
11. **A grant recorded by `companion approvals --grant` cannot authorise
    anything** (security review L4, accepted). Every CLI invocation is a new
    process and consent does not survive one, so the recorded answer is expired
    on the next load. It fails *closed*, and the command now says so rather
    than implying a standing permission — but it does mean the *granting*
    direction of the approval path is only ever exercised in-process, by the
    vertical slice and the tests.
12. **The approval's destination fingerprint is anchored in the task
    projection** rather than in the durable `ApprovalRequest` (security review
    L5, accepted). All six checks are present and correctly ordered, and the
    lost-update window that made this worth noting is closed; carrying the
    fingerprint in `resource_impact` is recorded as future hardening.

## 23. Unverified assumptions

1. **The store has only been exercised on Linux-hosted and Windows developer
   filesystems.** `fcntl.flock` behaviour on the installed system's actual
   filesystem is assumed, not measured.
2. **Durability is assumed from `fsync`**, not proven by power-cut testing. No
   crash-consistency harness was run against real hardware; the crash tests
   simulate a stopped process, not a stopped machine.
3. **Memory footprint has not been measured.** The 64 MB target is asserted as a
   design constraint; no equivalent of `scripts/capability_memory_measure.py`
   has been run against this runtime.
4. **The credential patterns are a list of known shapes, not a proof.** The
   *name* check is now convention-independent and covered by a 210-name table,
   so a forbidden concept cannot hide behind a naming style. The *value* check
   is a short list of well-known prefixes and claims nothing more: a credential
   with an innocuous field name and an unrecognised format would be stored. An
   entropy heuristic was considered and rejected — it would eat the digests,
   ids and fingerprints this record exists to carry.
5. **Reviewer isolation is enforced by construction and by the broker's caller
   check.** A reviewer that imported `os` directly is a packaging problem this
   layer does not solve.
6. **`ScriptedConsent` stands in for a person.** No real consent surface exists,
   so the granting path has only ever been exercised by a stand-in.
7. **The router's remote path is exercised with a test double.** No provider
   integration exists, so "remote is refused correctly" is verified and "remote
   works correctly" is not — by design.
8. **Schema conformance was verified with `jsonschema` 4.26.0** on a developer
   machine; the qualification host's `python3-jsonschema` version was not used.
9. **Store permissions were measured on one filesystem.** ext4 under Fedora WSL
   with `umask 022`. Behaviour on the installed system's actual root filesystem,
   and under a restrictive umask or unusual ACLs, is assumed rather than
   measured.

## 24. Remaining work for the UX shell

1. **A long-running service.** Today the runtime is constructed per CLI
   invocation. A session-scoped service — systemd user unit plus a socket —
   is needed before a shell can hold a session open.
2. **A consent surface.** `ConsentSource` is the interface; the Approval Centre
   is what has to implement it, including rendering `alternatives` and the
   `safeDefault`.
3. **Event subscription.** The shell needs to follow a stream rather than poll.
   The sequence number is the cursor; a `--follow` mode or a socket push is not
   built.
4. **A scheduler.** Concurrent `run_task` across tasks, with a queue and a
   concurrency limit informed by the capability budget.
5. **Presentation classification.** Which events a shell should surface, and how
   a `[withheld: personal]` marker is rendered so it reads as "not shown to this
   reviewer" rather than "empty".
6. **Cursor-based paging** for `task events` — the whole stream is returned today.
7. **Localisation.** Reasons and effects are English strings; the *codes* are
   stable and translatable, the sentences are not yet separated from them.
8. **Installed-image integration** — unit files, tmpfiles, `install-root.py`,
   and the memory measurement that must precede any of it.

## 25. Remaining work for voice and characters

Nothing in this phase implements, stubs or prepares for either, and that is
deliberate. What this phase leaves them:

1. **Speech input** would enter as a task request. `privacy.MAX_REQUEST_LENGTH`
   and `scrub_text` already apply; what does not exist is an audio classification
   above `personal`, or any path by which audio reaches the store — the
   redaction list forbids `rawAudio`, `microphoneRecording` and `waveform`
   outright, so a future phase must add a *reference* to audio held elsewhere
   rather than the audio itself.
2. **Speech output** is a presentation concern and should consume
   `result_created`, not add an event type.
3. **Voice cloning** is not implementable under the current privacy model
   without a new data class and an explicit approval action; neither exists, and
   adding them should be a reviewed decision rather than an implementation
   detail.
4. **Character packages** need a manifest, a signature and a resource estimate
   checked against the capability budget. The `codex/companion-runtime-ux-shell`
   branch has a design for this; it is not carried here.
5. **Character state** (idle, listening, thinking, speaking) is derivable from
   the task state machine and should be derived rather than stored — a second
   state machine would be a second thing that can disagree.
6. **An asset licence and provenance record** must exist before any artwork
   ships; `THIRD_PARTY_NOTICES.md` and `LICENSE_COMPLIANCE_REPORT.md` are where
   it belongs.

---

## Completion standard

| # | Requirement | Status | Evidence |
|---:|---|---|---|
| 1 | Sessions and tasks persist across restart | met | `test_sessions_tasks.py::test_sessions_and_tasks_survive_a_restart`; slice steps 18–19 |
| 2 | Task events are ordered and replayable | met | `test_events_store.py` (32 tests); slice step 20, 42 events, chain verified |
| 3 | Exactly one executor controls a task | met | `ExecutorLeases`; `test_executors_reviewers.py::test_exactly_one_executor_holds_a_task` |
| 4 | Reviewers cannot execute tools | met | `ReviewContext` holds no capability; broker refuses `reviewer:` callers and records the attempt |
| 5 | Capability decisions come from the existing capability runtime | met | `capability_bridge.py` calls `capability.router.route`; no detection code in `companion/` |
| 6 | Remote and paid execution require approval | met | `requirements_for()`; `test_approvals.py`; remote-only task blocks |
| 7 | Cancellation stops new operations | met | three windows tested (during, between, mid-run), each guard mutation-checked; a cancelled task can no longer reach `completed` |
| 8 | Recovery does not repeat uncertain operations | met | act-derived operation keys; the runtime **refuses** an `unknown` key and records the refusal; two tests, both mutation-checked |
| 9 | Sensitive information is redacted | met | 210-name convention table in `test_privacy_slice.py`; no credential reaches the store; store files 0600 measured on ext4 |
| 10 | The complete headless slice passes without a commercial provider | met | 21/21, `provider: none`, `network: none` |
| 11 | No companion UI or character artwork required | met | `companion/` imports only stdlib and `capability` |
| 12 | Capability qualification evidence untouched | met | `feature/capability-image-integration` at `43316cb`, unchanged |
