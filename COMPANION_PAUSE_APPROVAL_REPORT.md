# Companion Pause and Approval Consistency Report

Branch `fix/companion-pause-approval-consistency`.

| | |
| --- | --- |
| **Starting commit** | `4f8ea552d54654a75f2c6b4014d1c1dfdfb8cca2` |
| **Final / gate commit** | `66652d048fa1eacd3fbdd05892750a73fa255c4e` — all three gates |
| **Base branch** | `feature/companion-linux-validation` |

The previous phase left four things open: service stress at 98/100, the 50-run
suite gate unexecuted, a paused task that could project as blocked, and
animated 2D assets that had never been drawn. This closes them.

## 1. Evidence preserved before anything changed

Committed at `7826f82`, before a line of behaviour was touched, because a phase
that improves a number and keeps only the improved number has published a claim
rather than a measurement. Each file is verbatim with its SHA-256 and a caption
naming what it measured and on which commit:

| Entry | What it records |
| --- | --- |
| `01-before-any-fix` | 18/25, a 28 % failure rate, before either earlier fix |
| `02-before-store-fix-instrumented` | 14/20 loaded — the run that captured the swallowed `StoreError [WinError 5]` |
| `03-after-both-fixes` | 98/100, longest consecutive 39 |
| `04-transport-experiment` | 40/40 across both transports, peak `TIME_WAIT` 0 |
| `05-linux-service-stress` | 12/12 with every inventory delta zero |

`scripts/preserve_stress_evidence.py` refuses to overwrite an existing entry.
Superseding results are added beside what they supersede, never over it. The
prior reports are untouched except for dated correction blocks that leave the
original text standing.

## 2. Pause and approval: the root cause

A paused task projected as `blocked` about once in fifty runs. The task was
correctly paused. What was wrong was the record of what had happened to its
questions.

One plan raises two approvals. Pausing withdrew both, and
`ApprovalGate.invalidate_for_task` recorded them correctly as withdrawn. But
the worker was still inside the second one, and when it returned it called
`gate.resolve`, which raised — and the runtime's handler wrote

```python
"decision": "denied"
```

for **every** `ApprovalError` it caught. `ApprovalExpired` is an
`ApprovalError`. So the record said a person had refused. A denial blocks, and
the paused task showed as blocked.

Nobody refused anything. They pressed pause.

The failing event sequence, captured from a real run:

```
 9 approval_requested
10 approval_requested
11 task_paused
12 approval_resolved  expired  the task was paused; the question was withdrawn, not answered
13 approval_resolved  denied   approval '…:interrupt_user_work' has expired
```

Two questions from one plan, disposed of by two mechanisms with two meanings.

**Pre-existing, not introduced by the previous phase.** The same probe against
base commit `f6c2c02` failed at iteration 137 of 200 with the same signature.

### Three more, and Linux found all of them

Windows passed 120/120 once the vocabulary was fixed. Linux — roughly ten times
faster, and therefore reaching interleavings the development host almost never
does — failed one run in three. Each failure exposed a different defect:

**A transition event overwrote the accurate one.** `_fill_required` supplies
defaults for events emitted *by a state transition*, and for
`approval_resolved` it defaulted to `"denied"` whenever the target was
`blocked`. The runtime had already emitted an accurate record by then, so this
was a second event about the same fact carrying a worse value — and it was the
one the projection folded last. It now reads the decision from the approval
reference that was actually recorded.

**A pause could be overwritten by the runner.** Withdrawing a task's questions
is what makes the runner's next approval check raise, so the runner reaches its
own verdict a moment after the user presses pause. `pause_task` wrote its state
*protectively*, and a protective write declines when it sees a task somebody
else has taken — so the user's pause was silently the loser. It is now
authoritative, for the same reason `resume_task` already is for un-pausing:
whoever the user asked wins. The exception handlers in `run_task` also refuse
to block a task that has already been stopped, because blocking on a refusal
caused *by* the stop records the consequence of the user's action as a fault of
the task's own.

Traced rather than guessed — the runner read `waiting_for_approval`, reached
its verdict, and the pause did not end up persisted. The exact interleaving is
not reconstructed and is not claimed; the rule is.

**An approval could be answered twice.** Replay protection asked the durable
store whether a decision existed — but that decision is written by the
*worker*, after it wakes from the consent call. A second answer arriving before
that found `pending` and was accepted, at about one run in thirty.
`InteractiveConsent` now records the answer at the moment it takes it and
returns `"replayed"` without consulting anything that has to catch up. This one
is security-relevant: replay protection that depends on another thread's
progress is not protection.

**The protective write was not atomic.** `_save_running_task` guards every
write on the run path: it reads the persisted task and declines if somebody
else has taken it — terminal, cancelling, or paused. But the read and the write
were two steps, and pausing is exactly what happens in between. Traced with a
stack dump at the write site: the pause and the runner's block *both* observed
`waiting_for_approval`, both concluded they were clear to proceed, and the
block's write landed second. Holding the lifecycle lock across the pair is what
makes the guard mean anything; without it, it was advisory.

**The lifecycle epoch could be reset by a stale write.** The same shape one
field down. A worker holding a task object from before a resume writes it back,
and the object carries `lifecycle_epoch` from the previous attempt — so the
epoch went to zero and approval outcomes from before the resume started
matching again, which is precisely what the epoch exists to prevent.
`_save_running_task` now merges the persisted epoch when it is higher, for the
same reason it already merged the cancellation fields: the runner has
legitimate progress to record and only that one field is stale. Found by one of
this phase's own tests, at two failures in fifty.

Result: the Linux pause probe went from **1 failure in 3** to **250/250**.

**Six defects, and the last three were each found by a gate rather than ahead
of it.** That is the gates working, and it is also the honest shape of this
phase: reasoning found the first, and measurement found the rest.

### One shape, closed everywhere rather than where it was caught

Every one of the six is the same shape: **two writers on one task document,
separated by a check that had gone stale by the time the write happened.** Once
that was clear, the remaining lifecycle transitions were put under the same lock
without waiting for a gate to find them — `resume_task` and
`companion.cancellation.cancel_task` both read the task, decide, and write
several times, and a pause landing in the middle would interleave with all of
it.

Fixing only what a gate catches leaves the rest of the class in place. The lock
is reentrant, so the transitions that call each other are unaffected, and it
covers pausing, resuming, cancelling, the runner's block, and every protective
write on the run path.

No path holds it across the blocking consent call — the protective write takes
and releases it *before* `seek_consent` — so pausing never waits for the answer
it exists to stop waiting for. It is always acquired before the consent
source's own lock and never the reverse, so there is no ordering inversion.

### Three of these tests were mine, and they were flaky

Stated because it is part of the record. Three tests in
`test_lifecycle_races.py` used `ParkedTaskCase.parked()` — which deliberately
leaves a *real* worker thread running — and then asserted on the task document.
Asserting on a document two threads are writing makes a test about concurrency
whether or not it meant to be one, and these meant to be about what pause and
resume *mean*. They failed at about one run in fifteen on Linux.

The failures were mine, not the product's. `ResumeTests` now settles the worker
before asserting, and the concurrency property has its own test in
`PauseRaceTests` where it belongs. Measured after: **50 consecutive clean runs
of the whole race matrix on Linux.**

A soak that catches your own bad test is still the soak working. It is worth
noticing that the same reflex — assert on shared state without establishing who
else can write it — produced both the defects and the tests that failed to pin
them down.

## 3. Corrected event semantics

§6's terminal states now exist, and each exception names its own:

| State | Meaning | Raised by |
| --- | --- | --- |
| `approved` | the person allowed it | — |
| `denied-by-user` | **the person refused** | `ApprovalDenied` |
| `expired` | the clock ran out with nobody acting | `ApprovalExpired` |
| `invalidated` | withdrawn; the task stopped | `ApprovalInvalidated` |
| `superseded` | the plan changed under it | `ApprovalMismatch`, `ApprovalReplayed` |
| `cancelled-with-task` | withdrawn by cancellation | `ApprovalInvalidated` |
| `cancelled-with-pause` | withdrawn by pausing | `ApprovalInvalidated` |

Only `denied-by-user` means somebody said no. `USER_REFUSAL_STATES` is the
single place that is decided, and `terminal_record()` carries every field §6
requires: approval id, task id, plan id, transition id, previous state, reason,
timestamp, actor, binding digest, and the lifecycle epoch.

The **durable store keeps its four-word vocabulary** (`granted`, `denied`,
`expired`, `pending`). It is shared with the capability applicator and answers
a different question — "may this act proceed" rather than "what happened to the
question". The distinction lives beside it in `ApprovalGate.withdrawn`.

## 4. Corrected projection semantics

`_SYSTEM_WITHDRAWALS` — `invalidated`, `superseded`, `cancelled-with-task`,
`cancelled-with-pause` — never move the presentation phase. The phase stays
where the stream had it, so a paused task projects as paused **because its
lifecycle is paused**, not because "paused" was given a higher visual rank to
paper over a withdrawal recorded as a refusal.

An approval outcome from an earlier attempt at the task is ignored. Comparing
plan and transition ids cannot do this: a resume that produces an identical
plan produces identical ids *on purpose*, so that an answer which still applies
is kept. `CompanionTask.lifecycle_epoch` is the field that cannot match, and
`resume_task` increments it.

For clients, seven states summarise to four (`granted`, `denied`, `expired`,
`withdrawn`) — one new value in the presentation schema. Collapsing `withdrawn`
into `denied` at the surface would be the same defect one layer up: telling
somebody they refused something they never saw.

## 5. Approval waiter ordering

§4's order, and every step of it matters:

1. **build** the identity — nothing written anywhere;
2. **register** the consent waiter;
3. **persist** the durable request — *this is what makes it displayable*;
4. **emit** `approval_requested`;
5. the Approval Centre may display it;
6. **await** resolution.

Registering after persistence left a window in which a person could see a
question and answer it with nothing listening. `ApprovalGate.build` and
`persist` split what `prepare` did in one step; `prepare` is now their
composition, so there is one construction of a question and not two.

Rollback: if persistence fails the registration is undone, nothing is emitted
and nothing is displayable. If registration fails nothing is persisted at all —
a question nobody can answer must not exist.

## 6. Store writer behaviour

The writer retried **every** `OSError`. A full disk, a read-only filesystem and
a genuinely locked-down destination are all permanent; retrying them adds a
delay to an error that was correct the first time and invites a reader to
believe the store tried hard enough that the failure must be real.

`_is_transient_replacement_failure` now retries exactly one situation: on
Windows, a rename refused with `ERROR_ACCESS_DENIED` (5) or
`ERROR_SHARING_VIOLATION` (32) while another handle holds a destination that
exists and is writable. Five attempts, 10–50 ms backoff, 150 ms total. The
original exception is preserved. On POSIX a rename over an open file succeeds,
so an `EACCES` there means what it says and is raised at once.

The temporary is created in the destination's own directory — which is what
makes the replacement atomic *and* what makes the retry safe, since the
directory has demonstrably already accepted a file. It is discarded on
`BaseException` as well as `OSError`, because interrupts arrive most easily
during the backoff and a store interrupted often enough accumulated one orphan
per attempt in the directory it later scans. Nothing reports a successful save
before the replacement lands.

**A measured limit, recorded rather than tuned away.** A reader that reopens
the file continuously with no gap starves the writer through all five attempts;
this was found by writing the test, not assumed. The store's readers are
request-driven and the fastest poller in the product runs at 50 ms, so this is
a property of a spin loop rather than of the product — but the retry is a bound,
not a lock.

## 7. Worker-fault recording

A swallowed `CompanionError` produced one sentence. It now produces the fault
type, task id, operation, lifecycle phase, timestamp, sanitized message,
whether a retry was attempted, whether the task state changed, and whether
user-visible recovery is required. Reachable through `health()`.

Sanitized on the way in: user paths, anything self-describing as a token, key,
password or bearer, and long hex runs are replaced; the message is bounded at
400 characters. A fault log is read by whoever is debugging, and that is not
necessarily whoever owns the data.

The worker still survives — one bad task must not take every later task with
it. Swallowing an exception and destroying it are separable, and only the first
was ever necessary.

## 8. Race-test matrix

`tests/companion/test_lifecycle_races.py` — **19 tests in 2 seconds**, every
one constructing its interleaving with barriers and events. None sleeps to make
a race likely. A regression test that reproduces a fault one run in fifty is
not a regression test; it is a second flaky test.

| # | Interleaving | Result |
| --- | --- | --- |
| 1 | answer before waiter registration | not held; safe default |
| 2 | answer after registration, before persistence | delivered |
| 3 | answer immediately after persistence | delivered |
| 4 | second waiter for one question | refused |
| 5 | rolled-back registration | nothing answerable |
| 6 | pause while a question is displayed | withdrawn, worker released |
| 7 | pause with two questions | both withdrawn |
| 8 | pause with the task projection lagging the durable state | withdrawn from the durable authority |
| 9 | duplicate pause | idempotent, one `task_paused` |
| 10 | four concurrent pauses | one event, no error |
| 11 | cancel during pause | one terminal state |
| 12 | pause of a finished task | refused |
| 13 | resume advances the epoch | 0 → 1 → 2 |
| 14 | four rounds of pause/resume with approvals | never carried over |
| 15 | approval replay after resume | terminal, not replayable |
| 16 | invalidation never becomes a denial | holds |
| 17 | expiry after invalidation | terminal state unchanged |
| 18 | restart while paused | still paused |
| 19 | restart during invalidation | question not resurrected |

Writing them found a gap in my own reasoning: a freshly submitted task is in
`created` and cannot be paused — correctly, since there is nothing to set
aside. `ParkedTaskCase` produces a task genuinely waiting on its first
question by letting the runner reach the consent call and stopping it there.

## 9. Animated GTK result

`scripts/gtk_animation_probe.py`, GTK **4.22.4**, renderer imported from
`/usr/lib/bunny-os/python`, on WSLg's Wayland compositor:

| Check | Result |
| --- | --- |
| frame assets decode | **291 frames** delivered to `Gtk.Picture` over 3 s |
| frames advance | indices `[0, 1]`, 9 changes |
| configured frame rate observed | **3.0/s observed against 4.0/s configured** |
| looping returns | yes |
| one-shot completes | holds its single frame, does not advance |
| interruption | `working` interrupted to `error` |
| reduced motion → static | `static-first-frame`, loop false |
| degradation → static | drawable frame produced |
| renderer restart | returns to the current state |
| GLib criticals | **0** (0 records total) |
| timers surviving teardown | none; context drained in 2 iterations |
| task identity and result | unchanged — the renderer is presentation-only |

The rate undershoots by 25 %, reported rather than tuned: an 8 ms tick against
250 ms frames drifts, and the tolerance band is deliberately wide because this
is a timer on a shared development machine.

**Environment: WSLg, a remoted Wayland compositor inside a WSL2 utility VM.**
Not a GNOME session, not physical hardware, not a performance figure for any
target device. The probe records `isGnomeSession: false` and
`isPhysicalHardware: false` in its own output.

## 10. Gates

All three ran against `66652d048fa1eacd3fbdd05892750a73fa255c4e`, recorded per
iteration by the harness rather than once in a header — a header would not
prove the tree stayed still underneath a run.

| Gate | Required | Measured | Met |
| --- | --- | --- | --- |
| Installed vertical slices | 20 consecutive | **20/20**, all 25 steps, 0.422–0.484 s | **yes** |
| Complete companion-suite runs | 50 consecutive | **50/50**, longest 50, 15.7–17.5 s | **yes** |
| Service-driven suite runs | 100 consecutive | **100/100**, longest 100, 18.4–19.7 s | **yes** |

**All three met, on one commit.** The 50-run gate had never been executed
before this branch, and the last time that test module ran under stress it
failed five times in fifty. The 100-run gate stood at 98/100 when this phase
began.

Gate 1 recorded **no non-zero delta against its baseline at all** — every
thread, descriptor, socket, lease, waiter, held answer, pending approval and
store-lock count returned to where it started, on all 100 iterations.

Per iteration the harness records: run number, commit, exit status, duration,
thread delta, descriptor delta, listening-socket delta, temporary-file count,
pending approvals, active executors, executor leases, consent waiters, held
answers and held store locks. The last six are absolute rather than
differenced — they should be *empty* between iterations, and a delta of zero
against a baseline that already had one reads as clean when it is not.

Two corrections were made to the harness before the gates ran, both because the
previous version could have passed while hiding something:

- the "complete suite" target was a **hand-written list of 22 modules**, and a
  hand-written list of everything is wrong the moment somebody adds a file. Five
  modules written during this phase were missing from it, including the ones
  covering the defect the gate exists to catch. It now discovers: **27
  modules**;
- pending approvals, active executors, held answers and held store locks were
  not recorded at all.

### Thread, socket, descriptor and memory trends

From the 50-run complete-suite gate on Linux, which is the longest continuous
run and therefore the one a trend would show in:

| | Result |
| --- | --- |
| threads against baseline | **+2 by iteration 2, then flat at +2 for the remaining 48** |
| non-daemon threads | **0** — nothing that would hold the process open |
| descriptor delta per iteration | **0** across all 50 |
| listening-socket delta | **0** |
| temporary directories | **0** |
| executor leases / consent waiters / held answers / pending approvals / store locks | **empty** at every iteration |
| RSS against baseline | rises for roughly the first twenty iterations, then oscillates around +52 MiB without trending |

Threads, sockets, descriptors and temporary files **do not accumulate** — §14.12
is met. The `+2` is worth stating precisely rather than rounding to zero: it
appears in the first two iterations and never moves again, which is two threads
created on first use, not two per run. Forty-eight consecutive iterations at the
same value is the evidence for that, and the non-daemon count of zero is the
evidence that neither would keep the process alive.

Memory reaches a steady state and oscillates. Stated as what it is: a plateau
over fifty runs, not a proof about a service left running for a week.

## 11. Windows and Linux measure different things

Kept separately, and neither substitutes for the other:

- **Windows** has no `AF_UNIX`. It validates the loopback fallback's lifecycle
  and the atomic replacement behaviour — and it is the only host on which the
  replacement defect reproduces at all.
- **Linux** validates the installed transport, `SO_PEERCRED` peer identity and
  systemd user-service integration, over a real Unix socket.

**Neither host is the stricter one, and that is the argument for keeping both.**
This phase is the case in point. Windows found the replacement defect and
cannot find the lifecycle races; Linux found three defects Windows had passed
over — and, because it is about ten times faster, found them at one run in
three rather than one in a hundred and thirty-seven.

Linux also found two defects in the *tests*, both of which had been passing for
the wrong reason:

- the store tests patched `os.name`, which reaches tempfile and pathlib as
  well. On Windows the patch to `"nt"` was a no-op, so the tests passed without
  ever exercising what they claimed to; on Linux they lied to the standard
  library and six failed. `store._WINDOWS` is now the seam;
- the character tests copied the *installed* package — mode 0444 and
  root-owned, correctly — and then wrote to it. Twenty-three tests failed on
  any machine with Bunny OS actually installed and passed everywhere else.

Twenty-three tests failing on the machine most like the product, and passing on
the developer host, is the direction that matters.

Skip counts differ for a reason worth stating: **18 skipped on Windows, 1 on
Linux**. The difference is `AF_UNIX` and `/proc` — the tests written for the
shipped transport do not run on the host that has no shipped transport.

## 12. Complete test results

Every suite §13 names, on both hosts where the host can run it.

| Suite | Windows | Linux |
| --- | --- | --- |
| Complete companion tests (includes character, protocol, approvals, store, pause/resume, recovery, presentation) | **599 OK**, 18 skipped | **599 OK**, 1 skipped |
| Capability tests | **697 OK** | not re-run (unchanged by this branch) |
| Repository validation (`task.py validate`) | **PASS**, 0 failing validators | — |
| Full repository suite (`task.py test`) | 3078 tests, **1 error**, 37 skipped | the failing test passes |
| Real GTK smoke | — | **pass**, 0 criticals |
| Real GTK animation | — | **pass**, 0 criticals |
| Installed artifact inventory | — | **pass**, 98 modules, 0 refusals |
| Installed provenance | — | **pass**, all three modules installed |
| Installed vertical slice | — | **20/20**, 25 steps |

**Classification of the one non-pass.**
`tests.display_stack.test_evidence_gate.MutationTests.test_duplicate_boot_check_is_load_bearing`
fails on Windows with `OSError [WinError 1314] A required privilege is not
held by the client` — creating a symbolic link needs a privilege this account
does not have. It is **unsupported environment**, not a regression: the same
test was run on Linux and passes, and nothing in this branch touches the
display stack.

## 13. NOT_RUN items

Distinguished from passes, because a check that never ran is not a check that
succeeded:

- **ShellCheck** — not installed on this host; repository validation records
  the skip rather than counting it.
- **systemd unit analysis** — needs `BUNNY_VERIFY_SYSTEMD=1` and
  `systemd-analyze` against an installed Fedora fixture.
- **Windows symlink test** — above.
- **Capability suite on Linux** — not re-run there; this branch changes nothing
  under `capability/`, and it passes on Windows.
- **A booted disk image** — the artifact was installed onto a host and
  inspected; `osbuild`'s image was not booted.
- **Physical hardware** — none.
- **A second real user for peer rejection** — substituted credential only.

## 14. Known limitations

1. **No physical hardware.** Every Linux result is from a WSL2 utility VM.
2. **No GNOME session**, and no desktop-session claim.
3. **No booted installed system.** The artifact was installed onto a host and
   inspected; the disk image was not booted.
4. **A spin-loop reader can starve the writer** — §6.
5. **The mapper's `playback_policy` still reads `loop` for the degraded case.**
   Degradation is applied at the renderer, and the frame produced is correct;
   that is what is claimed and no more.
6. **`ApprovalGate.withdrawn` is in memory.** After a restart the durable
   store still shows the question settled, but the *reason* it was withdrawn is
   not carried across. A task is recovered rather than resumed mid-question, so
   nothing depends on it — but it is a gap, not a design.
7. **The exact interleaving behind the pause-overwrite is not reconstructed.**
   What was traced is that the runner read `waiting_for_approval`, reached its
   verdict, and the pause did not end up persisted. The fix is a rule — the
   pause is authoritative for its own state — and the regression test asserts
   the rule rather than the interleaving, because reproducing the interleaving
   needs two threads inside one lock. The rule is the thing that has to hold.
8. **`InteractiveConsent`'s replay record is in memory and per-process.** A
   second runtime over the same store would not see it. There is only ever one
   runtime per endpoint — the protocol refuses a duplicate with exit 3 — so
   nothing depends on it today.
9. **The lifecycle lock is per-runtime, not cross-process.** It serialises
   pause, resume, cancel and the runner's block against each other inside one
   process. Two processes over one store are already refused at the socket.
10. **A different-user peer rejection** is proved against a substituted kernel
   credential, not a second real user.
11. **Frame-rate figures are development-machine figures.**

## 15. Reproducibility and build impact

- **Build-affecting.** `companion/` is copied into the image by
  `install-root.py`, so every change here changes the artifact.
- **No reproducibility candidate was created**, and no reproducibility or
  release qualification is claimed for this branch.
- **No capability qualification evidence was modified.**
- Prior reproducibility evidence does **not** cover this branch.
