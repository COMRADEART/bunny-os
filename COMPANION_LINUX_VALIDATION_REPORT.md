# Companion Linux Validation Report

Branch `feature/companion-linux-validation`, based on the verified head of
`feature/companion-character-renderer` (`f6c2c02`).

This phase was asked to validate and harden the integrated companion and its
character renderer on real Linux interfaces before voice-runtime work begins.
The single most important outcome is that the intermittent suite failure, which
survived two phases undiagnosed and was described in the renderer report as
"not diagnosed, and it is not being reported as if it were", now has a cause,
a fix, and regression tests that construct the failure rather than wait for it.

## 1. What was actually run, and on what

Three distinct surfaces are involved and they are not interchangeable. Every
claim below names its own.

| Surface | What it is | What it can prove |
| --- | --- | --- |
| **Windows 11 (10.0.26200), CPython 3.14.6** | The development host. No `AF_UNIX`. | Nothing about the shipped transport. It is where the flake reproduces. |
| **Fedora Linux 44 (WSL), kernel 6.18.33.2-microsoft-standard-WSL2, systemd 259, cgroup v2, CPython 3.14.3** | A Hyper-V utility VM with a vendor kernel. **Not** a container, **not** physical hardware. | Real `AF_UNIX`, a real systemd user manager, a real cgroup, a real Wayland client. |
| **`localhost/bunny-os-developer:3fb5eecbb028`** | The image built from this branch. | What is installed, and where it is imported from. |

`scripts/linux_environment_report.py` classifies the surface from evidence and
keeps the evidence beside the verdict. It files WSL2 as its own surface rather
than the container `systemd-detect-virt --container` calls it: that command
answers `wsl`, which is true in systemd's taxonomy and misleading in this one,
because an `systemd-nspawn` container shares the host kernel and WSL2 does not
(`--vm` answers `microsoft`). Filing it as a container would have put it in the
same bucket as nspawn, which is the confusion the classification exists to
prevent.

**No GNOME claim is made anywhere in this report.** The probe records
`isGnomeSession: false`, established by looking for a running `gnome-shell`
rather than by trusting `XDG_CURRENT_DESKTOP`, which any script can export.

## 2. The intermittent failure: two defects, both measured

### How it was approached

`scripts/companion_stress.py` records a per-iteration **inventory** rather than
a verdict: threads by name, descriptors from `/proc/self/fd`, sockets by state
from `/proc/net/unix` and `/proc/net/tcp`, live `CompanionService` and
`CompanionRuntime` objects walked out of `gc.get_objects()`, executor leases,
consent waiters, and `VmRSS`. The rule it exists to apply:

> A leak is a line that goes up. A race is a failure with a flat inventory.

Every failure observed in this phase had a thread and descriptor delta of
**exactly zero**, which ruled out the accumulation hypotheses before any code
was read.

### What was ruled out, and how

- **Ephemeral-port exhaustion from the loopback developer transport** — the
  renderer report's leading hypothesis. Disproved by a controlled experiment:
  one machine, one workload, only the transport differs. 20 integration slices
  over `AF_UNIX` and 20 over a forced loopback transport, **all 40 passed**,
  peak `TIME_WAIT` **0** for both. The `prefer_loopback` diagnostic added for
  this experiment is a constructor argument, never an environment variable, and
  `CompanionService` passes it only when a caller sets it explicitly.
- **Residual threads from previously closed services** — disproved by the flat
  inventories above.

### Defect one: the store's writer had no retry

`companion/store.py` already documented the exact Windows behaviour in
`_read_bytes_stable`: a rename over a path a reader holds open is refused with
`EACCES`, "which is not a damaged file, not a permissions problem, and not
something to report as either" — and it retried. **Only the reader was
defended.** The writer met the same window from the other side with no retry at
all.

The consequence was not a bad read. It was a frozen task:

1. a client polls `get_task` or `get_events`, holding a store file open;
2. the worker writes the task and `os.replace` is refused;
3. the store raises `StoreError`;
4. `CompanionService._serve_work` catches it as an ordinary refusal and moves on;
5. the task stays in `waiting_for_executor` with nothing running, nothing
   queued, and no explanation anywhere.

Captured verbatim once the worker was made to keep what it swallowed:

```
StoreError: ...\store\sessions\ses-...\tasks\task-....json
  could not be written: [WinError 5]
```

`WinError 5` is `ERROR_ACCESS_DENIED`. `_replace_stable` now gives the writer
the reader's treatment, bounded and re-raising the last failure so a store that
genuinely cannot be written still says so.

This is **Windows-only**: on POSIX a rename over an open file simply succeeds.
That is why 52 consecutive Linux runs never reproduced it while one Windows run
in three did — and that asymmetry is what pointed at platform filesystem
semantics rather than at the companion's own logic.

### Defect two: an approval was visible before it was answerable

An approval request reaches the store — and therefore the Approval Centre —
before the single worker calls `InteractiveConsent.answer` and registers a
waiter. Anything a client did inside that window was discarded:

- an answer found nobody listening and was **dropped**, and the worker then
  waited out its entire consent budget with the answer already given;
- a cancellation released nothing, so the worker went on to park on a question
  belonging to a task that had already been cancelled — held for the whole
  budget, which is precisely what cancelling is supposed to prevent.

`InteractiveConsent` now holds an answer that arrives early, and refuses on
arrival a question whose task has gone. Both are keyed by **request id and
never by task id**: a paused task resumes and asks again with *new* request
ids, so refusing by task would leave a resumed task unable to obtain consent
for the rest of the service's life.

Holding is privileged. `resolve()` discards an unclaimed answer by default;
only a caller that has already established the question is live may ask for it
to be held, and `CompanionGateway.resolve_approval` establishes exactly that —
the request exists, every binding field matches what the person was shown, it
has not expired, and it has not been answered — *before* it calls. A held
answer still expires with its question and is dropped when the task is
cancelled or the service stops.

### The observability defect behind both

`_serve_work` caught `CompanionError` and did nothing with it — `pass`, with a
comment asserting that the runtime had already written the refusal to the event
stream. For a `StoreError` that assertion is false by construction: the thing
that failed *was* the write. Swallowing an exception and destroying it are
separable, and only the first was ever necessary. Recent faults are now kept in
a bounded deque and reported through `health`, and the protocol test that times
out prints them. **This is what turned a two-phase mystery into a one-line
answer.**

### Result

| Measurement | Result |
| --- | --- |
| Windows, `--target service`, 25 runs, **before** | **18/25**, longest streak 12 |
| Windows, `--target service`, 20 runs, **before**, loaded | **14/20**, longest streak 4 |
| Windows, `--target service`, 100 runs, **after** | **98/100**, longest streak 39 |
| Linux, `--target service`, 12 runs | **12/12**, every delta zero |
| Linux, integration slice over `AF_UNIX`, 20 runs | **20/20** |
| Linux, integration slice over forced loopback, 20 runs | **20/20** |
| Linux, installed character slice, 20 runs | **20/20** |

The failure rate on the reproducing host fell from **28 %** to **2 %**. Failure
durations before the fix were 48–108 s against a 19 s baseline — a wait budget
being consumed in full — and **after the fix no long-wait failure occurred at
all**: both residual failures took the normal 19 s. Seventy-two consecutive
Linux runs across four different shapes produced no failure of any kind.

## 3. The installed artifact

Built from this branch as `localhost/bunny-os-developer:3fb5eecbb028`.
`scripts/installed_artifact_report.py` inventories it **inside the image**:

- **104 entries, 98 Python modules, 6 directories, 0 symlinks** under
  `/usr/lib/bunny-os/python`;
- every required module present — `runtime`, `service`, `protocol`,
  `presentation`, `store`, `character/surface`, `character/animated_renderer`,
  `character/package`;
- **no** byte-code, tests, fixtures, `__pycache__`, sockets, token files,
  runtime stores, approval stores or stress logs;
- everything root-owned and not group- or world-writable;
- a **single distinct mtime** across the whole tree, which is the build's
  timestamp clamping working.

The report treats an empty package directory as a failure rather than a pass,
because that is the shape a missing `COPY` produces — the build succeeds and
installs nothing, which has happened on this repository before.

## 4. Import provenance

`§2` requires that a run claiming to test the installed artifact is not
quietly testing the checkout. `linux_environment_report.py --require-installed`
puts **only** `/usr/lib/bunny-os/python` on `sys.path` — exactly what
`/usr/libexec/bunny-companion-service` does — and then classifies what
resolved, rejecting a repository checkout, a bind mount, a developer
`PYTHONPATH`, the working directory and user site-packages. Bind mounts are
detected from `/proc/self/mountinfo`, where a bind of a subdirectory has a root
that is not `/`; without that check a bind mount can make a checkout look
exactly like the installed tree.

Inside the image:

| Role | Module | `__file__` | Class |
| --- | --- | --- | --- |
| canonical runtime | `companion.runtime` | `/usr/lib/bunny-os/python/companion/runtime.py` | `installed` |
| presentation layer | `companion.presentation` | `/usr/lib/bunny-os/python/companion/presentation.py` | `installed` |
| renderer | `companion.character.surface` | `/usr/lib/bunny-os/python/companion/character/surface.py` | `installed` |

Gate passed. The same four modules — plus `companion.protocol` — were recorded
again from the live service in §5, with the same answer.

## 5. The installed service on real Linux interfaces

The artifact was extracted from the image onto the Fedora host and the shipped
user unit run under the **real** systemd user manager, as an unprivileged user,
with lingering enabled.

```
Active: active (running)   Main PID: 444
listening on /run/user/1000/bunny-companion/runtime.sock (unix-socket)
CGroup: /user.slice/user-1000.slice/user@1000.service/app.slice/bunny-companion.service
```

**Endpoint.** Socket mode `600 bunny:bunny` inside a directory at
`700 bunny:bunny`. The service reports `peerUserValidated: true`,
`transport: unix-socket`, `tokenRequired: false` — no token exists on this
transport because there is nothing one would add that the socket's own
permissions and the peer check do not already provide.

**A task, end to end, over that socket.** Completed in **0.477 s** and
**0.518 s** across two runs, 26 events, hash chain verified, presentation phase
`success`, `recentWorkerFaults: []`.

**Duplicate instance.** A second runtime exits **3** with "another Bunny
companion runtime is already listening on this endpoint; one runtime owns the
session". It does not displace the first.

**Restart and stop.** Restart returns the socket at `0600`; stop removes the
runtime directory entirely.

**Memory and descriptors** (§12 — this is process and cgroup memory for the
runtime alone; it is **not** a Bunny OS boot measurement, and no such figure is
offered):

| | Before the task | After the task |
| --- | ---: | ---: |
| cgroup `memory.current` | 31,719,424 | 32,600,064 |
| cgroup `memory.peak` | 33,792,000 | 33,492,992 |
| `VmRSS` | 27,856 kB | 28,620 kB |
| threads | 3 | 3 |
| open descriptors | 4 | 4 |
| `pids.current` | 3 | 3 |

Against the unit's own `MemoryMax=128M` and `TasksMax=64`. Threads and
descriptors are unchanged across a complete task.

**One honest note about the unit.** `bunny-companion.service` is
`PartOf=graphical-session.target`, so it stops when that target stops — correct
by design, since the companion belongs to the graphical session. On a headless
host `graphical-session.target` refuses manual start ("may be requested by
dependency only"), so a headless validation must start the service directly and
keep a single login session open for the duration. A first attempt at this used
one `su` per step and reported the service as dead; the unit was behaving
exactly as designed and the script was wrong.

## 6. The Unix transport's security claims, executed

`tests/companion/test_unix_transport.py` — **12 tests, 0.052 s**, run as an
unprivileged user on ext4. Until now none of these properties had ever been
executed on a platform that has `AF_UNIX`, because the development host has
none and the suite ran against the loopback fallback.

The module **skips** rather than substituting the fallback. §6 forbids reading
loopback behaviour as evidence about the shipped transport, and a test that
quietly passed on loopback would report a property of the developer transport
under the name of the shipped one.

Covered: the endpoint is a socket and not a regular file; mode `0600`; owned by
the caller; directory `0700`; a stale socket left by a killed runtime is
replaced rather than mistaken for a live peer; the peer credential is read from
the kernel and names this process (which is what stops a `_peer_uid_check` that
had quietly become `return True` from passing everything else); a foreign uid
is refused; an unreadable credential is refused; `AF_UNIX` is chosen and
carries no token; `require_unix` refuses the fallback rather than downgrading.

Writing them found a further defect. `CompanionServer.close` called
`socketserver.shutdown`, which waits for `serve_forever` to acknowledge — and
when nothing is serving that acknowledgement never comes, so `close` **blocked
for ever** rather than raising. The guard around it caught an exception that is
never thrown, leaving the real hazard in place: a runtime that fails between
binding and serving, and is then closed by a `finally`, hung on the way out
still holding its socket. Found by this module hanging instead of failing.

## 7. Gates

§15 asks for 100 consecutive service-driven runs, 50 consecutive full
companion-suite runs and 20 consecutive installed vertical slices, all on the
same finalized code, with no upward thread, socket or descriptor trend, and the
count reset after any defect is fixed.

| Gate | Required | Measured | Met |
| --- | --- | --- | --- |
| Installed vertical slices | 20 consecutive | **20/20**, 0.426–0.441 s, all 25 steps | **yes** |
| Service-driven suite runs | 100 consecutive | 98/100, longest run 39 | **no** |
| Full companion-suite runs | 50 consecutive | not attempted at this scale | **no** |

The full companion suite passes as a single run — **559 tests, 17 skipped, 40 s,
OK** — which is what makes the residue below worth stating rather than hiding:
one run proves nothing about a 1-in-50 failure.

**Two of the three gates are not met, and nothing is claimed on their behalf.**

Both residual failures are the *same test* —
`test_pausing_a_task_waiting_for_consent_actually_stops_it` — at the normal
19 s duration with flat inventories, so it is a race and not a leak.

The task is correctly `paused`. The *projection* reports `blocked`. One plan
raises two questions, and on a failing run they are disposed of by two
different mechanisms with two different meanings:

```
 9 approval_requested
10 approval_requested
11 task_paused
12 approval_resolved  expired  the task was paused; the question was withdrawn, not answered
13 approval_resolved  denied   approval '…:interrupt_user_work' has expired
```

One is withdrawn, which is right. The other **expires**, and an expiry is
recorded as a *denial* — which outranks a pause in the presentation phase
ordering, so the projection reports `blocked` for a task that is paused.

**This is a third defect, distinct from the two above, and it is not fixed.**

It is also **not a regression from this phase**, which was established rather
than assumed. The same probe was run against the phase's base commit
`f6c2c02` in a separate worktree: it failed at iteration **137 of 200**, with
the same test and the same event signature. This branch failed at iteration 55
of 80. One failure each is not enough to distinguish those rates, and no claim
is made that either is worse. An earlier 60-run base sample passed 60/60 and
was reported here as evidence of a regression; at a rate near 1 in 137 a clean
run of 60 is unsurprising, and that reading was wrong.

A fix belongs where `abandon` and `ApprovalGate.invalidate_for_task` meet —
the boundary between "nobody answered", "the question expired" and "the
question was withdrawn", which the record currently collapses into a denial.
It is left open rather than patched at the projection, which would hide it.

One narrowing was made in passing: `pause_task` no longer pre-refuses the
questions a worker has not reached. Pre-refusing them records denials where
withdrawals belong, and pausing already withdraws them correctly — a paused
task holds no worker anyway, because the runner notices the pause at its next
phase boundary. Measured before and after: the change did **not** alter the
failure rate, so it is a correctness improvement and not a fix.

## 8. Scope held

- No AI providers, commercial voice services, speech recognition, full 3D
  rendering or desktop automation were added.
- No reproducibility candidate was created.
- No capability qualification evidence was modified.
- **No claim is made that prior reproducibility evidence covers this branch.**
  The image built here was built to inspect what it installs, not to be
  compared against anything.
- The archived donor `archive/companion-character-renderer-c2f2acf` remains a
  named Git reference and must accompany these branches when they are pushed.

## 9. Corrections to the standing record

§18 requires that a prior incorrect claim is corrected without deleting the
correction history.

- `COMPANION_CHARACTER_RENDERER_REPORT.md` §20 keeps its "unresolved flake"
  paragraph verbatim and gains a dated correction block naming both defects and
  recording that **both** of the mechanisms it called "most likely" were wrong.
- The same report's limitation 11 is struck through rather than removed, with
  the resolution beside it.
- `companion/protocol.py`'s `prefer_loopback` docstring asserted a measurement
  the experiment contradicted — it claimed "AF_UNIX clean and loopback
  failing". Both transports passed 20/20. It now records the refutation.

## 10. What this phase did not establish

Stated plainly, because a validation report that only lists successes is not
one:

1. **Two of the three §15 gates are not met**, and a third defect in the pause
   path is open and undiagnosed to root cause. See §7.
2. **No physical hardware.** Every Linux result here is from a WSL2 utility VM.
   Firmware, real drivers and a real GPU are untouched.
3. **No GNOME session, and no desktop-session claim.** The GTK layer ran
   against WSLg's compositor, which is a real Wayland target and not a session
   compositor.
4. **No booted installed system.** The artifact was inspected inside the image
   and extracted onto a host; the disk image produced by `osbuild` was not
   booted.
5. **The animated renderer's PNG frames were not drawn.** §11 records what the
   GTK run did and did not cover.
6. **A different-user peer rejection was proved against a substituted kernel
   credential**, not against a second real user connecting.
7. **Process memory only.** §5's figures are the runtime's own; they are not a
   Bunny OS boot measurement.

## 11. GTK execution, precisely

`scripts/gtk_execution_probe.py` refuses to run without a display — there is no
headless mode and no offscreen substitute, because a widget tree built without
a compositor proves nothing about one shown on a compositor.

Against WSLg (`wayland-wslg-remoted`), GTK **4.22.4**, with `gtk_shell.py`
imported from `/usr/lib/bunny-os/python`:

- the `ApplicationWindow` is **constructed, realized, mapped and visible**;
- the full widget tree is realized and mapped — `ScrolledWindow` → `Viewport`,
  both `Scrollbar`s and their `Range`s, `HeaderBar` → `WindowHandle` →
  `CenterBox`;
- a `Gtk.Picture` exists and holds
  `/usr/share/bunny-shell/companion/default-bunny.svg`, the shipped asset from
  its installed path;
- **zero** GLib log records and **zero** criticals, captured through
  `log_set_writer_func` because GTK reports most widget faults through the log
  rather than by raising. Success is not inferred from the absence of an
  exception.

This retires the renderer report's admission that "no compositor was available;
the widget code has never been executed" for the **static** path. It does not
retire the animation claim: the probe did not drive phase changes through the
animated renderer, so `Gtk.Picture` switching PNG frames at rate remains
unexecuted and is listed in §10.

Two details worth recording rather than smoothing over: the window reports a
size of `[0, 0]` because the compositor had not allocated one within the
probe's 60 main-loop iterations, and the static character and the character
*package* are different artifacts — `/usr/share/bunny-shell/companion/
default-bunny.svg` and `/usr/share/bunny-os/companion/characters/
default-bunny/` respectively. Both are installed by the image; a first probe
run reported `staticCharacterLoaded: false` purely because the host extraction
had not copied `/usr/share`.

## 12. Files

New:

- `scripts/companion_stress.py` — the inventory-capturing stress harness
- `scripts/linux_environment_report.py` — surface classification and the
  import-provenance gate
- `scripts/installed_artifact_report.py` — installed inventory and refusals
- `scripts/gtk_execution_probe.py` — GTK execution against a real compositor
- `tests/companion/test_consent_delivery.py` — 14 tests, the approval race
- `tests/companion/test_unix_transport.py` — 12 tests, the socket's claims

Changed:

- `companion/store.py` — `_replace_stable`
- `companion/service.py` — held answers, refuse-on-arrival, fault recording
- `companion/protocol.py` — `close` no longer blocks; corrected docstring
- `tests/companion/test_events_store.py` — the replace-retry regression tests
- `tests/companion/test_protocol_ipc.py` — failures print swallowed faults

Evidence: `qualification/companion-linux/evidence/`.
