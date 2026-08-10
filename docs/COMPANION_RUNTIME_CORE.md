# The Bunny Companion runtime core

This is the part of the companion that has to be right before anything is drawn
on a screen: what a session is, what a task is, which states a task may move
between, what happened to it and in what order, who was allowed to act, and what
survives the machine being switched off in the middle.

It renders nothing. There is no window, no character, no voice and no commercial
provider anywhere in `companion/`, and none may be added to it. Those are later
phases and they consume this one; building them first would mean deciding the
shape of the record from the shape of the animation, which is how a companion
ends up with a beautiful surface over an event log nobody can replay.

## The pipeline

```
User request
    ↓
Companion session          companion/session.py
    ↓
Task creation              companion/task.py
    ↓
Task classification        companion/runtime.py    classify_request()
    ↓
Capability and policy      companion/capability_bridge.py → capability.router
    ↓
Executor selection         companion/executor.py
    ↓
Approval when required     companion/approvals.py  → capability.apply.approval
    ↓
Execution events           companion/tools.py      ToolBroker
    ↓
Reviewer observations      companion/reviewer.py
    ↓
Result
    ↓
Persistent event history   companion/events.py, companion/store.py
```

## The three properties everything else is arranged around

**The event stream is the truth.** Session and task documents are projections of
their events and can always be rebuilt from them. A field that cannot be derived
from the record is a field that will eventually disagree with it. Every load
compares the projection's revision against the stream's tip, and
`companion.recovery` prefers the stream whenever they disagree — which they will,
every time a process dies between the append and the projection write.

**Uncertainty never becomes action.** An approval nobody answered is a denial. A
capability that could not be established is not a capability. An operation whose
completion event is missing is *unknown*, not *incomplete*, and an unknown
operation is never repeated.

**The executor acts and the reviewers only look.** Exactly one executor holds a
task at a time; reviewers can read a redacted view and say what they think, and
that is the whole of their power.

## Modules

| Module | What it is responsible for |
|---|---|
| `companion/privacy.py` | What may be stored at all, and who may read it |
| `companion/ids.py` | Identifiers, and the derived operation keys recovery depends on |
| `companion/clock.py` | Wall time for the record, monotonic time for every deadline |
| `companion/states.py` | The lifecycle table: which moves are legal and what each emits |
| `companion/events.py` | The hash-chained, append-only event record |
| `companion/session.py` | The standing context a task is submitted into |
| `companion/task.py` | One request, from submission to history |
| `companion/store.py` | Durable storage: atomic appends, locking, retention, migration |
| `companion/executor.py` | The provider-neutral executor contract, and one local implementation |
| `companion/tools.py` | The allowlist, and the only door through it |
| `companion/reviewer.py` | The observation-only reviewer contract, and one local implementation |
| `companion/coordination.py` | Ceilings, the executor lease, and review rounds |
| `companion/capability_bridge.py` | Asking the capability runtime where a task may run |
| `companion/approvals.py` | Consent, and every way an answer stops counting |
| `companion/runtime.py` | The orchestrator — the only thing that makes anything happen |
| `companion/cancellation.py` | Stopping, as a sequence rather than an exception |
| `companion/recovery.py` | What to do about a task the machine was in the middle of |
| `companion/demo.py` | The 21-step headless vertical slice |
| `companion/cli.py` | The `bunny-os companion` command group |

## Task states

```
created → classifying → waiting_for_capability → waiting_for_executor
        → planning ⇄ waiting_for_approval
        → executing → reviewing → (planning again, or) presenting → completed

any active state → paused | cancelling → cancelled | failed | recovering
classifying/waiting_* /planning → blocked → classifying
```

Sixteen states. Fifteen are the brief's; `cancelling` is the addition, because
stopping takes time — pending operations have to be signalled, approvals
invalidated and partial output written down — and during that window the task
must accept no new work. A state that says so is more reliable than a boolean
somebody has to remember to check.

The legal moves live in `companion.states.TRANSITIONS` as data, not as control
flow. A move that is not in the table cannot happen, and the tests enumerate
every pair. Two rules in that table are load-bearing:

* **`recovering → executing` does not exist.** A task found mid-execution after a
  crash goes to `planning`, where the executor replans with the completed
  operation keys in front of it. An operation whose outcome is unknown is
  *decided about* rather than *repeated*.
* **`blocked` is not terminal.** A task blocked for want of an eligible executor
  becomes runnable again when the machine changes, and returns through
  `classifying` so the capability question is asked again from the beginning.

Every transition emits exactly one typed event. Most map to an event from the
brief's vocabulary; a few lifecycle moves carry no meaning beyond the move
itself and emit `task_state_changed`, which is the one event type added to the
brief's list.

## The event chain

Each event carries the hash of the one before it. The chain turns four separate
requirements into one mechanism:

* **ordering** — a reordered stream fails to verify, because the hashes name a
  specific predecessor rather than merely "the previous line";
* **corruption detection** — a rewritten payload changes its own hash and every
  hash after it;
* **incomplete final writes** — a truncated last line has no valid hash, so the
  reader drops exactly one event and keeps the rest;
* **deduplication** — a replayed event carries a hash that does not follow the
  current tip and is refused.

Only a structurally incomplete *final* record is ever dropped, and the drop is
reported. Anything else wrong — a bad hash in the middle, a sequence gap, a
duplicate id — raises. The store will not manufacture a missing event to make a
chain verify.

The chain is unkeyed. It is not a defence against an attacker who can rewrite
the whole file; it defends against what actually happens to a file on a
constrained device. See "Known limitations".

## Persistence

```
<root>/store/store.json                      what this store is
<root>/store/sessions/<id>/session.json      the session projection
<root>/store/sessions/<id>/stream.json       anchor, retention and migrations
<root>/store/sessions/<id>/events.jsonl      the append-only chain
<root>/store/sessions/<id>/tasks/<id>.json   task projections
<root>/approvals.json                        approval questions and answers
```

Everything is owner-only: files 0600, directories 0700, `O_NOFOLLOW` on the
append path — not left to the umask and not resting on the parent directory,
because the store root is configurable and can be pointed somewhere another user
can write. Measured on ext4 under `umask 022`: zero group- or other-readable
entries.

No database. A session's history is an append-only sequence of small records read
in order — which is a log, and a log implemented as a log costs a file handle.
Bunny OS is expected to run in 64 MB and the qualified base image carries no
server. If a future phase needs an access pattern this cannot serve — full-text
search across sessions is the obvious one — that is the documented need and the
decision can be revisited then.

Appends are `fsync`ed under an exclusive session lock before they are
acknowledged. Projections are written to a temporary file, fsynced, and moved
into place with `os.replace`. Retention prunes from the *front* of a chain and
records the hash the new head follows, so history removed on purpose stays
distinguishable from history removed by damage.

## Capability integration

There is no hardware detection in `companion/`. `capability.discovery` measures
the machine, `capability.scores` grades it, `capability.budget` decides what may
be spent and `capability.router` decides where a task runs.
`companion/capability_bridge.py` translates a task into the router's
`TaskRequest`, asks, and records the plan identity the answer was given against.

Every narrowing in the translation is deliberate: `personal` maps up to the
router's `sensitive`; the effective locality is the *stricter* of the task's and
the session's; `remote_allowed` is the session's permission rather than the
task's wish; and `user_approved` is always false, because approval is decided
against a specific plan and destination by `companion/approvals.py`.

The router's rule survives intact: **local incapability is never an argument for
remote execution.** A task that cannot run locally and may not run remotely
becomes a *blocked* task carrying the router's own reasons.

## Approvals

Built on `capability.apply.approval.ApprovalStore`, which already defines the
request shape and the rule that matters most: an unanswered request involving
remote execution, money, destruction of user work, or interruption of something
in progress is **denied**.

What the companion adds is binding. An approval belongs to one task, at one
transition, under one plan, to one destination, and stops counting the moment any
of those change:

| Refusal | What it prevents |
|---|---|
| expired | consent to act now used later |
| replayed | one approval spent on two acts |
| wrong task | an answer for one task authorising another |
| wrong transition | an answer for one step authorising a different step |
| superseded | the plan changed under the approval |
| changed destination | the place the data would go changed after the answer |

Transition identifiers are derived from the **plan fingerprint**, so a replan
producing an identical plan asks the same question and an answer already given
still applies — and a replan producing a different plan asks a new one.

Whatever stands in for the person is a `ConsentSource`. The default,
`RefusingConsent`, records every question and grants nothing.

## Privacy

Classes, in increasing sensitivity:

```
public < internal < personal < sensitive < secret
```

Never stored, at any classification, for any audience: API keys, access and
refresh tokens, authorisation headers, credentials, passwords, cookies, hidden
model chain-of-thought, scratchpads, raw microphone audio and full screen
content. There is no flag that turns these on. They are removed before an event
is constructed, and the *fact* of removal is kept in the event's `redactions`
field — which is inside the hash, so the record of what was taken out is as
unforgeable as the record of what was kept.

Audience ceilings:

| Audience | Sees up to | Why |
|---|---|---|
| `executor` | `secret` | the on-device thing doing the work |
| `ui` | `sensitive` | the user's own surface |
| `reviewer` | `internal` | observation does not require the contents |
| `audit` | `internal` | proving what happened, not archiving what it was about |
| `remote` | `internal` | off-device, and only when policy permits anything at all |

The name check is convention-independent — `sessionCookie`, `session_cookie`,
`SESSION_COOKIE` and `session.cookie` are one thing — and the test suite asserts
35 concepts across 6 naming conventions. What it cannot catch is a credential in
a field with an innocuous name and an unrecognised shape; the value check covers
well-known prefixes and claims nothing more.

Above the ceiling, *structure* survives and *content* does not: keys remain,
values become `[withheld: <class>]`. A reviewer can therefore see that a task had
a `recipients` field and say something useful about it without being told who the
recipients were.

Events are classified by what their own payload carries, not by the task.
Classifying every event at the task's level is the obvious implementation and it
quietly breaks review: a reviewer of a `personal` task would find the executor's
name, the memory figures and the plan's step count all withheld, and would have
nothing left to review.

## Cancellation

A sequence, and each step is recorded:

1. the task enters `cancelling` — a state, so new operations are refused from
   that instant without every call site having to ask;
2. the executor is signalled, once, and its answer is not waited on;
3. operations that were started and never settled become `unknown` — never
   `failed`, because a failure is a claim about what happened;
4. pending approvals are withdrawn;
5. whatever partial output exists is written down;
6. a final `task_cancelled` event is appended.

Causes are kept distinct — `user`, `policy`, `timeout`, `capability_loss`,
`provider_loss`, `supervisor_shutdown` — so a user can tell "I stopped this" from
"the machine stopped this because the battery died".

## Recovery

After a restart, per session: validate the chain, find incomplete tasks, check
the executor still exists, inspect pending operations, invalidate stale
approvals, resume only when it is supported and safe, otherwise park in
`paused`, `blocked` or `failed`, and record the decision as an event either way.

The hard case is one operation wide: an `operation_started` with no
`operation_completed`. The record cannot say whether the work happened. That
operation becomes `unknown`, the task returns to **planning** — never to
executing — and the runtime **refuses** to perform any operation whose key is
`unknown`, recording the refusal and its reason in the stream. The guarantee
does not rest on the executor cooperating.

This works because the operation key is a digest of the **act** —
`(task, name, tool, destination, arguments)` — and not of its position in a plan.
An earlier version included the plan revision, which changes on every replan: no
key ever matched, the skip was unreachable, and the runtime re-ran uncertain work
while the ledger beside it said it would not. That defect was found by
independent security review and is recorded in
`COMPANION_RUNTIME_CORE_SECURITY_REVIEW.md`.

A session whose chain will not verify is reported and skipped; every other
session is still recovered. One damaged file must not cost a user the rest of
their history.

## Commands

```bash
bunny-os companion sessions
bunny-os companion session create   [--title T] [--locality L] [--allow-remote]
bunny-os companion session inspect  <session-id>
bunny-os companion session pause|resume|close <session-id>
bunny-os companion task submit      --session <id> --request <text> [--run]
bunny-os companion task run         <task-id>
bunny-os companion task inspect     <task-id> [--audience A]
bunny-os companion task events      <task-id> [--audience A]
bunny-os companion task cancel      <task-id> [--cause C]
bunny-os companion approvals        [--grant <request-id>] [--deny <request-id>]
bunny-os companion recover          [--dry-run]
bunny-os companion run-demo         [--refuse-approval]
```

Every command returns a JSON-serialisable document carrying an `effect` field:
`"read-only"`, or a sentence naming what changed. The UX shell consumes the
structure and must never parse the human rendering. All commands accept
`--simulate <machine>` and `--inventory <path>`; simulated output is labelled.

## The headless vertical slice

```bash
make companion-demo
# or
bunny-os --json companion --simulate laptop run-demo
```

Twenty-one steps: start, create a session, submit a task, classify it, evaluate
the capability plan, select the local executor, plan, request a harmless
approval, resolve it, execute, emit progress, review, record the observation,
revise, produce a result, complete, stop, restart, reload, replay every event
against the hash chain, and confirm the completed result is unchanged.

No network, no provider, no credential, no display. `--refuse-approval` runs the
same slice with nobody answering, which stops at step 9 with the task blocked and
the notice never published.

## Tests

```bash
make test-companion
# or
python3 scripts/task.py test-companion
```

The schema conformance test needs `jsonschema` and skips without it; the
enumeration-agreement tests, which catch the failure that actually happens — a
state or event type added in one place and not the other — run unconditionally.

## Security review

Three adversarial passes, each run against the previous one's fixes. Twenty-two
findings, six High; twenty fixed, two accepted and documented. **Eight were
introduced or left behind by a previous round's fix** — including a schema
version that was not bumped when the hashed material changed, which would have
made every existing store permanently unreadable.

Three findings falsified properties this documentation had claimed: the
redaction check missed every snake_case field name, recovery repeated operations
it said it would not, and cancellation did not stop a task it said it stopped —
that last one across six separate windows, found in three batches over three
rounds. Five docstrings claimed properties the code did not have and now say
what is true.

`COMPANION_RUNTIME_CORE_SECURITY_REVIEW.md` has the detail, the reproductions and
the residual risk.

## Known limitations

* **The chain is unkeyed.** Anyone who can write the store can recompute it.
  Detecting a hostile rewrite needs a signing layer and is out of scope here.
* **A reviewer that hangs cannot be stopped.** The timeout frees the *task*, not
  the CPU: Python has no safe way to interrupt an arbitrary call, so the worker
  is a daemon thread that keeps running.
* **Consent does not survive a restart.** Monotonic expiry restarts with the
  machine, so approvals from a previous run are expired on load rather than
  re-evaluated. The audit trail survives; the permission does not.
* **`run_task` is synchronous.** Concurrency *across* tasks works — each has its
  own lease and its own events — but the scheduler that runs several at once
  belongs with the UX shell.
* **Classification is a regex.** Deliberately, so that this phase's event stream
  is reproducible. A real classifier is a later phase.
* **Recovery rebuilds the operation ledger, not the whole document.** The stream
  is authoritative about what happened; the projection is where the request text
  and the policy live, and those do not change after submission.
