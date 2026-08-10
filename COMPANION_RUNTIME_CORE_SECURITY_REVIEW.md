# Companion runtime core — security review

Scope: `companion/` (21 modules) and `tools/bunny-os/bunny_os/companion_cli.py`,
on `feature/companion-runtime-core`.
Method: independent adversarial review against nine stated properties, every
finding reproduced by execution rather than inferred, followed by remediation
and **two further adversarial passes against the fixes**. Every pass reproduced
its findings by execution.
Date: 2026-08-04.

The re-review passes mattered more than the first. Round two found that two of
round one's fixes had a surviving path and that one had introduced a regression.
Round three found five more — including a change of mine that would have made
every existing store permanently unreadable, and the single most important
cancellation window, which the first two rounds had both walked past. Remediation
is not an ending; it is the thing most worth reviewing.

The review was asked explicitly not to trust the docstrings. That instruction
earned its place: **five docstrings claimed properties the code did not have**,
and in a package whose entire value is auditability, a docstring that overstates
is worse than a missing one, because it is what the next reviewer will read
instead of the code.

## Result

| Severity | Found | Fixed | Remaining |
|---|---:|---:|---|
| Critical | 0 | — | — |
| High | 6 | 6 | 0 |
| Medium | 9 | 9 | 0 |
| Low | 7 | 5 | 2 accepted, documented |

* **Round one** — 13 findings, 4 High, against the original code.
* **Round two** — 4 findings against round one's fixes: two surviving paths, one
  collision introduced by a fix, one regression introduced by a fix.
* **Round three** — 5 findings against round two's fixes, 2 High: a schema
  version that was not bumped when the hashed material changed, a fifth
  cancellation window in the approval wait, a non-atomic append, a masked
  diagnostic, and a fail-open default.

Twenty of the twenty-two are fixed; two are accepted and documented. **Eight of
the twenty-two were introduced or left behind by a previous round's fix**, which
is the number worth remembering when deciding whether re-review is optional.

## Claimed properties, after remediation

| # | Property | Before | After |
|---|---|---|---|
| 1 | Credentials, hidden reasoning, audio and screen content never persisted | **failed** | holds |
| 2 | Reviewers are observation-only | partial | holds |
| 3 | Executors return plans only; the runtime performs via the broker | holds | holds |
| 4 | Remote/paid needs approval; unanswered ⇒ denial | holds | holds |
| 5 | Approvals bound to task, transition, plan and destination | holds | holds |
| 6 | The chain detects tampering, reordering and gaps | partial | holds |
| 7 | Identifiers cannot escape the store directory | holds | holds |
| 8 | Above-ceiling data withheld, including in exports | **failed** | holds |
| 9 | Writes are atomic and durable; appends serialised | partial | holds |

## High

### H1 — the redaction check missed every snake_case field name

`companion/privacy.py`. Eleven alternatives in `_FORBIDDEN_FIELD` were anchored
with `\b`. In Python `_` is a **word** character, so `\bcookie` never matches
after an underscore. An earlier fix had split on camelCase transitions only,
which repaired `sessionCookie` and left `session_cookie` wide open — and the
docstring for that fix claimed the opposite, stating it had previously caught
`session_cookie`.

Verified bypassed: `client_secret`, `user_password`, `session_cookie`,
`github_token`, `api_token`, `oauth_credential`, `raw_screenshot`,
`the_scratchpad`, `mic_waveform`, `frame_buffer`, `pass_phrase`, `MY_SECRET`,
`APITOKEN` — all stored verbatim and permanently, at any classification. This is
the invariant the module exists to enforce and the one every later phase will
consume without re-reading.

**Fixed.** `normalise_key()` splits camelCase *and* maps every non-alphanumeric
run to a space before matching; compounds in the pattern accept `[-_ ]?` between
their parts; the missing `api[-_ ]?token` was added.

**Round two found the mirror image still open.** Because `normalise_key`
*inserts* separators, an alternative spelled as a single word can be split apart
by a field name that spells it in two — and `\bpasswords?\b` is itself
*pass*+*word*, so `passWord`, `pass_word`, `PassWord` and `PASS_WORD` were all
still stored. `passWord` is a spelling people write. Fixed with
`\bpass[-_ ]?words?\b`, and the test now enumerates **separator placements at
real word boundaries**: 39 concepts, 496 spellings, zero bypasses. Benign
near-misses — `secretary_name`, `cookbook`, a 64-character digest, a numeric
`tokenCount` — are all kept.

### H2 — cancellation did not stop a running task

`companion/runtime.py`. Cancellation stopped the *operations* and then let the
pipeline carry the task through review, result and completion. The stream said
`task_cancelled` at sequence 15 and `task_completed` at 19; the persisted state
was `completed` with `cancellationState` reset to `none`. The record asserted
that a task the user stopped had finished normally.

Root cause was a lost update: `save_task`/`load_task` are unsynchronised (the
session lock guards only the event log), so the runner wrote its stale in-memory
copy over the canceller's write and then read its own value back.

**Round one fixed the operation loop only, and round two found two more windows
open**: a cancel landing during *review* (up to `maximum_reviewers ×
reviewer_timeout_seconds`, twenty seconds by default) or during
`executor.result()` (unbounded, third-party) still reached `result_created` and
`task_completed`. The lesson is exact: the fix had been written where the bug
was found rather than at every boundary of the same kind.

**Fixed.** `_stopped()` re-reads the persisted task at **four** boundaries — top
of the plan loop, after execution, after review, after the result —
and `_plan_and_execute` returns immediately when the task is terminal or
cancelling. `_save_running_task` writes **nothing** once the persisted task is
terminal or being cancelled. `_checkpoint` now takes `authoritative=`: the run
path gets the protective write, and cancellation — which *is* the authority for
its own final state — passes `authoritative=True`. Five tests cover the five
windows, and **each fails if its own guard is removed**.

### H3 — recovery repeated operations, including ones recorded `unknown`

`companion/ids.py`. The idempotency key included the plan id and revision.
Recovery always returns a task to `planning` and the runtime always increments
the revision, so **every key was new on the resumed run**, `completed_operation_keys()`
could never intersect, and the skip branch was unreachable in practice.

The record actively contradicted itself: the ledger entry read *"whether it
happened is not known and it will not be repeated"* while a second entry beside
it showed the same operation running again. An operation the stream **proved**
completed was also re-executed.

**Fixed.** `operation_key` now digests the *act* — task, name, tool,
destination, canonical arguments — so the same operation under any later
revision carries the same key. **Round two found a collision in that fix**: the
five fields were joined with a `0x1F` separator and three of them are free
strings an executor controls, so shifting a `0x1F` across a boundary produced
identical material for two different acts — one would be deduplicated away
against the other and never performed, while the record claimed it "was not
repeated". Now `canonical_json` of the whole tuple, which has no boundary to
move because the encoder escapes the separator inside a value. `TaskContext.unknown_operation_keys` was added,
and the runtime now **refuses** to perform an operation whose key is `unknown`,
recording the refusal and its reason in the stream rather than relying on the
executor to cooperate. Completed operations are skipped with their prior value
carried forward from the stream. Two tests cover it; both fail if the key is
made act-unstable.

### H4 — the event log was created world-readable

`companion/store.py`. The append path used the process umask (0644 on a default
install) while every other file was explicitly 0600. The event log is the
authoritative record and carries the richest payloads, up to `secret`. Session
directories were 0755. `companion/cli.py` explicitly reasons about shared
machines and then rested on the parent directory alone.

**Fixed.** `_append_private` uses `os.open` with `O_NOFOLLOW` and mode 0600 —
which also closes L2. `_private_directory` creates each level of the chain at
0700, because `mkdir(parents=True, mode=…)` applies the mode only to the leaf and
left `sessions/` at 0755. The lock file is opened the same way.

Measured on ext4 under WSL with `umask 022`: **every file 0600, every directory
0700, zero group- or other-readable entries.**

## Medium

### M1 — failure text carried above-ceiling content at `internal`

`operation_failed` was pinned at `internal` however sensitive the task, and its
`error` field is the tool's exception message — which routinely quotes the
offending value. A `secret` task's contents were reproduced verbatim in an export
for the `remote` audience. **Fixed:** `operation_failed`, `task_failed` and
`session_created` are now user-content events, classified at the task's (or
session's) own level.

**Round two found this had cost the audit audience the session policy.**
`session_created` carries a title the user wrote *and* the privacy, cost and
locality policies that were in force — and classifying the whole event at the
title's level withheld the policy from exactly the audience whose job is to
check a claim like "nothing was permitted to leave this device". Fixed by adding
`sensitiveFields` to the event record: a payload can name which of its top-level
keys carry the user's material, and the rest are rendered at `internal`. It is
inside the hash, so which fields were treated as sensitive cannot be changed
after the fact.

### M2 — the task projection and export leaked past the ceiling

`CompanionTask.view()` masked only two fields; `outputs[].summary` and
`errors[].summary` survived at every audience, and `store.export()` embedded the
session document with no projection at all. **Fixed:** errors are masked with the
task, each output is masked at its **own** classification, and
`CompanionSession.view()` masks the title against the strictest class among the
session's tasks. Verified: for `remote`, `audit` and `reviewer`, neither the task
content nor the session title appears anywhere in an export.

### M3 — `migrate()` could launder a tampered chain

`migrate()` re-sealed every record without verifying the chain first. A stream
that `read_stream` correctly refuses came out of a migration verifying
perfectly, with the attacker's edit now correctly hashed — and the migration
record's `originalTipHash` was read from the attacker's own file, so the audit
trail was theirs too. Marking records with an older version was the way in.

**Fixed.** `_verify_before_migrating()` authenticates every record *before* any
re-seal, against the hashing rule of the version it declares
(`_HASHED_FIELDS_BY_VERSION`), and refuses outright a version whose rule this
build does not implement — closing the downgrade path to an unverified state.

### M4 — `ReviewContext` was frozen in name only

`@dataclass(frozen=True)` freezes the attribute bindings, not the dictionaries
behind them, and one instance was passed to every reviewer in sequence. A
reviewer could append to `plan["operations"]` and flip the next reviewer's
verdict from a blocking disagreement to "no issues" — suppressing a finding, in a
module whose docstring said no channel between reviewers existed.

**Fixed.** Each reviewer receives a deep copy. The hard boundary — no store, no
broker, no approval store, and `ToolBroker.invoke` refusing `reviewer` callers —
was genuinely sound; only the isolation claim was overstated, and the docstring
now says what is actually true.

### N1 — a field entered version 1's hashed material without a version bump *(round three)*

`companion/events.py` and `companion/__init__.py`. Fixing M1 added
`sensitiveFields` to the hashed material but left `EVENT_SCHEMA_VERSION = 1`.
Every event the previous build had written was hashed over material *without*
that key, so a store written before the change became **permanently
unreadable**: `read_stream` raised `IntegrityError`, `validate()` reported
legitimate data as tampering, and `migrate()` refused to help because it saw no
version change to act on.

This is exactly what the version table exists to prevent — its own comment says
to authenticate "against the rule it was written under, not the current one" —
and the field had been added to version 1's rule instead of creating version 2.
The blast radius was development stores only, because this is pre-merge. After
ship it would have been unrecoverable user data.

**Fixed.** `EVENT_SCHEMA_VERSION = 2`; `HASHED_FIELDS_BY_VERSION` moved into
`companion/events.py` and is now used by the **reader** as well as the migrator,
so `computed_hash()` restricts material to the rule of the version each record
declares. A version 1 chain reads, verifies and migrates forward. Two tests
guard it: one writes a record under the v1 rule and reads it back, and one
asserts every version's field set is distinct and a strict superset of the one
before — so a field added without a version bump fails.

### N2 — a fifth cancellation window, in the approval wait *(round three)*

`companion/runtime.py`. `_settle_approvals` held the last unprotected
`store.save_task` on the run path and had no `_stopped()` check spanning the
consent call. A cancel arriving while consent was pending was clobbered, and the
plan ran on — including the operations that had needed the consent.

This was the worst of the six, not the least. A real Approval Centre **blocks**
here, so it is where a task spends most of its wall-clock time, it is the moment
a user is looking at a dialog and most likely to press stop, and the work that
then proceeds is precisely the work somebody was being asked about.

**Fixed.** The write is protective and there are `_stopped()` checks inside the
per-requirement loop and after the batch. Verified: with a consent source that
cancels instead of answering, the task ends `cancelled` and
`broker.invocations` is **empty** — not even the harmless word count ran.

### N3 — `_emit` reads the tip and appends non-atomically *(round three)*

The session lock is taken inside `append_many`, so two writers to one session
race: twelve concurrent cancels produced two `IntegrityError`s out of
`cancel_task` and four dead runner threads. It failed *closed* — no corruption —
but the cancellation did not happen and the CLI would traceback.

**Fixed.** `_emit` retries against the fresh tip, bounded at eight attempts. The
store's refusal is correct behaviour and is left alone; what changed is that the
caller now treats a lost race as a lost race. Twelve concurrent cancels now run
clean, and the test fails with the retry budget set to one.

### N4 — a terminal task replaced the real diagnostic *(round three)*

`_block`/`_fail` re-read the persisted task, so a cancel landing while the run
path was raising handed them a terminal one. The illegal transition raised
`InvalidTransition` out of `run_task`, replacing the actual reason — the
approval refusal, the capability refusal — with a confusing one about the state
machine. State on disk stayed correct. **Fixed:** both return the persisted task
unchanged when it is already terminal.

### N5 — the per-field classification list was fail-open *(round three)*

Naming the *sensitive* fields meant every unnamed key rendered at `internal`.
No live leak — the only call site named its fields correctly — but a key added
to that payload later would have been downgraded silently, inverting this
codebase's own "undeclared fails closed" principle. **Fixed** by inverting it:
the list now names the fields that are *runtime fact*, and anything unnamed
carries the event's classification, so forgetting over-classifies.

## Low

| | Finding | Disposition |
|---|---|---|
| L1 | `check_deadline` had no callers and `deadlineConsumedSeconds` was never written — the 300 s ceiling was inert | **Fixed**: checked between operations, consumption persisted |
| L2 | Symlink follow on the event log and lock file | **Fixed** by H4's `O_NOFOLLOW` |
| L3 | `$` in `ID_PATTERN`, `_PRODUCER`, `_TIMESTAMP` accepts a trailing newline | **Fixed**: `\Z`. Traversal was never possible — the leading-alnum rule already rejected `..`, `/` and `\` |
| L4 | A grant recorded by `companion approvals --grant` can never authorise anything, because every CLI invocation is a new process and consent does not survive one | **Accepted.** It fails *closed*. The CLI message now says so explicitly rather than implying a standing permission. An in-process consent surface is UX-shell work |
| L5 | The approval's destination fingerprint is anchored in the task projection rather than in the durable `ApprovalRequest` | **Accepted.** All six §12 checks are present and correctly ordered; H2's fix removes the lost-update window that made this worth noting. Recorded as future hardening |

## Confirmed sound

* **No ReDoS.** Both patterns are alternations of literals with non-overlapping
  separators. At the enforced 4096-character bound, adversarial inputs
  (`"eyJ"*1365`, `"-----BEGIN " + "A"*4000`, `("eyJ" + "A"*40 + ".")*90`) all
  completed in under 0.4 ms.
* **The executor boundary holds cleanly.** `TaskContext` and `ReviewContext`
  carry values only. `broker.invoke` is called from exactly one place, with
  `caller="runtime"`, and refuses `reviewer` callers loudly rather than
  returning a failed outcome.
* **The approval binding holds.** Expired, replayed, wrong-task,
  wrong-transition, superseded-plan and changed-destination are each a distinct
  exception in a sensible order, and `transition_id` embeds the plan fingerprint.
* **`_fast_tip` is safe under the lock.** It parses through
  `TaskEvent.from_json`, which re-verifies the record's own hash, and returns
  `None` on any anomaly so the caller falls back to the full verifying read.
* **Fail-closed defaults are real, not decorative:** `RefusingConsent`,
  `CostPolicy(0)` meaning *no spend* rather than *no limit*, `PrivacyPolicy`
  defaulting to `personal` with no remote, `fully_declared`, the refusal to let a
  non-local executor declare `secret`, and `user_approved=False` always handed to
  the router.
* **Non-finite floats and non-string keys are rejected at the sanitize
  boundary** rather than discovered on read-back.

## Residual risk

1. **The chain is unkeyed.** Anyone who can write the store can recompute it.
   The integrity mechanism defends against partial writes, bit rot and crashed
   processes — not against an attacker with write access. A signing layer is out
   of scope for this phase and is the honest answer to that threat.
2. **Credential detection is a list of known shapes.** A credential in a field
   with an innocuous name and an unrecognised format would be stored. The name
   check is now convention-independent; the *value* check covers well-known
   prefixes and claims nothing more.
3. **A hostile reviewer is contained, not sandboxed.** It cannot reach the
   broker, the store or another reviewer's view, but it is in-process code
   somebody installed and can still import whatever Python can.
4. **Consent does not survive a restart**, by design. Recorded decisions are
   audit history, not standing permission.
5. **The store has not been power-cut tested.** Durability rests on `fsync`
   plus atomic replace; the crash tests simulate a stopped process, not a
   stopped machine.
