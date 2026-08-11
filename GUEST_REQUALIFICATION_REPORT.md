# Guest runtime requalification — the rebuilt image

Deliverables 4 to 7. What the production image-task route does inside a booted
Bunny OS guest with SELinux enforcing, and what three regressions found there.

Two guest runs are reported, not one. The first found a defect; the second is
the re-run against an image containing its fix. Both are committed.

| | First run | Second run |
|---|---|---|
| Image commit | `0482f4c90f00` | `39a5c575da9e` |
| Evidence | `qualification/capsules/evidence/guest-4c6e101bd354/` | `.../guest-524107e50b2e/` |
| Sections passing | 10 of 11 | **11 of 11** |
| SELinux | Enforcing, targeted v35 | Enforcing, targeted v35 |
| Confining backends | flatpak, bubblewrap | flatpak, bubblewrap |

---

## 4. Guest runtime requalification

Run as `bunny` (uid 1000) in a real login session, kernel 7.1.5-200.fc44.x86_64,
against the **installed** packages under `/usr/lib/bunny-os/python`. The
qualification tooling is injected; the code under test is not. That distinction
is why this report exists separately from the host one.

| Section | Verdict | What it establishes |
|---|---|---|
| host | PASS | flatpak and bubblewrap both present; `systemd-scope` excluded by name |
| isolation | PASS | 17 checks isolated, each reached by the control; 19 mounts inside against 35 outside |
| crossapp | PASS | B could not read or enumerate A's private storage before or after an authorised transfer |
| filegrant | PASS | granted readable, neighbour denied, revoked denied, allow-once left no grant |
| failclosed | PASS | six failure paths, six distinct reasons, no grant written by any of them |
| network | PASS | `none` denied external, DNS and loopback; the allowlist gap still disclosed |
| selinux | PASS | every expected capsule operation worked with the policy loaded, mode Enforcing |
| crash | PASS | killing the launcher left no process in the host namespace; no orphans, none unconfined |
| **launcher** | PASS | the capsule launches under both Companion units' own directives, and the pre-fix scope shape still fails under both |
| **apptask** | PASS | the whole Companion route, end to end, on a real file |
| resources | PASS | memory intervened by the cgroup; tasks enforced |

`launcher` and `apptask` had never run in a guest before this phase.

### The image task, inside the guest

```
program     /usr/libexec/bunny-image-tool, mode 0555, installed by the route
prompt      "Bunny Image Tool wants to open Pictures/holiday.png. It will save
             a copy as holiday-resized.png. Your original file will not be
             changed. It runs in its protected space with no network access."
authorised  Pictures/holiday.png — one file
neighbour   present in the same directory, never authorised, byte-identical after
network     shown "Off"; plan class none; enforced true
result      holiday-resized.png, 100x50 from 400x200, 182 bytes, exit 0
elapsed     214.4 ms
original    byte-identical afterwards
```

Host and guest agree on every one of these. The guest is 214 ms against the
host's 170 ms, which is the virtualisation cost and not a behavioural
difference.

---

## 5. Approval content-binding regression

The defect: `Resource.digest` hashes *kind and path*, because a grant is about a
location. It therefore cannot notice that the bytes at that location changed —
which is exactly the substitution the brief asks about.

Sequence, run against the approval that was already issued (re-preparing would
build a binding over the new content and prove nothing):

1. approval issued for `Pictures/holiday.png` and its content digest;
2. the file's bytes replaced;
3. execution attempted with the original approval.

```json
{"bytesActuallyChanged": true,
 "refused": true,
 "code": "SECURITY_POLICY_BLOCKED",
 "detail": "the file changed between the question and the answer"}
```

**REFUSED**, in both guest runs.

---

## 6. Allow-once lifecycle — the defect this phase found

`once` is what the person is offered and what they get. It cannot be what the
*grant* says: Trust deliberately never persists an allow-once decision, and the
isolation plan is built from persisted grants, so a `once` grant produces no
bind and the application receives a path to nothing. The lifetime is expressed
instead as a session grant that the runtime drops when the capsule stops.

**First guest run — FAIL.**

```json
{"ok": false,
 "remainingFileGrants": [{"category": "files", "scope": "session", ...}],
 "remainingGrantCount": 1}
```

The task completed, the capsule stopped, and the file grant was still there.

**Root cause.** `CapsuleRuntime.stop` drops session grants and returns early for
a capsule that is already stopped — and `reconcile()`, called on its first line,
is what stopped it. For an application that exits by itself, which is every task
application, the drop never ran. "Allow once" left a permission behind for the
rest of the login.

**Fix.** The drop moves to `reconcile()`, which is where the runtime *learns*
the process has ended. A permission granted "while you are using it" is over at
that moment whether or not anybody asked for a stop.

**Second guest run — PASS.**

```json
{"ok": true, "remainingFileGrants": [], "remainingGrantCount": 0}
```

The unit suite passed both before and after the fix, so a test that fails
without it now exists (`tests/capsules/test_runtime.py`), with a control
asserting a still-running capsule keeps its grant — a drop that fired mid-task
would take the file away underneath the application.

---

## 7. systemd exit-state regression

Three answers, and never a synthesised fourth:

| Observed | Reported |
|---|---|
| program exits 0 and writes the file | success |
| program exits non-zero | `CAPSULE_EXITED`, with the program's own message |
| program cannot be executed | `CAPSULE_EXITED`, with bwrap's message |
| manager cannot produce a status | `EXIT_STATUS_UNKNOWN` (`-2`) — read as failure by every caller |

```json
{"ok": true, "collectsTheUnit": false, "unknownStatus": -2}
```

`--collect` is absent from the rendered vector — a collected unit takes its exit
status with it, which is how "could not be executed at all" once became
"succeeded, produced nothing". The unknown case is asserted rather than
simulated: it cannot be provoked reliably, and a test that faked it would be
asserting the fake.

---

## Known limitations, stated rather than worked around

**AVC evidence is still not collectable in this image.** `kernel.dmesg_restrict`
is 1, `journalctl` carries no kernel lines, `ausearch` is not installed, and the
kernel buffer is empty even to root. The section reports *blind* with a positive
control rather than reporting zero denials. What is established is the
substantive property — every expected capsule operation worked with the policy
loaded and enforcing, and no policy change was made — but a denial count is not
claimed. A qualification-only profile carrying audit tooling is the fix and has
not been built.

**`network=none` is enforced; destination allowlisting is not.** These are kept
apart in the plan, the projection and this report. A capsule granted the
allowlisted class reached a domain outside its list; a capsule with class `none`
reached nothing. The first operation runs with `none`.

**Repeated-build comparison was not performed** for either image.

**The pre-existing TTS provenance failure is untouched** and is not a regression
from this work; see the separate note in `NEXT_PHASE.md`.
