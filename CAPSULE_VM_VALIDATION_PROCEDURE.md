# VM validation procedure — App Capsules, Trust and the Companion slice

**Date** 2026-08-10 · **Status** written, **not executed**

Static tests are insufficient (§34) and everything in this phase is currently
static. This document is the procedure that moves it from *tested* to *runtime
validated* — the third row of the maturity ladder — written so that somebody else
can run it and so that a partial run is legible as a partial run.

Every step states what is being measured, what result counts, and what the result
must **not** be recorded as. That last column exists because the failure mode of a
validation run is a green tick attached to a check that did not really happen.

---

## 0. Prerequisites

| | |
|---|---|
| Host | Fedora WSL builder (`fedora-wsl-is-a-full-builder`), `/root/bunny-os`, never `/mnt/c` |
| Image | A Bunny OS image built from this branch |
| VM | QEMU/KVM, the existing `make vm-smoke` harness |
| User | Run the suites as `bunny` on ext4, never as root and never from `/mnt/c` |
| Session | A graphical session for §4 and §7; a console is enough for §1–§3 |

**Before anything else**, and independent of the VM:

```sh
# On the Fedora builder, as bunny, from an ext4 checkout
make test-capsule-phase
```

Three symlink tests are `NOT_RUN` on a Windows host. Until this passes on Linux,
the symlink rows in `APP_CAPSULE_SECURITY_REVIEW.md` §2.3 are design claims, not
measurements. **This is the single cheapest item in this document and it blocks
the interpretation of the security review.**

---

## 1. Backend availability is measured, not assumed

**Measures:** that `MachineProbe.measure()` reports the real machine.

```sh
python3 -c "from capsules.backends import MachineProbe, available_backends; \
p=MachineProbe.measure(); print(p); print(available_backends(p))"
cat /proc/sys/user/max_user_namespaces
ls -l "$XDG_RUNTIME_DIR/bus"
```

**Passes if** the reported programs, namespace availability and portal socket
match what the shell shows independently.

**Negative control:** set `user.max_user_namespaces=0`, re-run, and confirm
`available_backends` drops `bubblewrap` and `flatpak`. **A run without this
control does not count** — the four gate failures recorded in
`checks-that-punish-their-own-strengthening` are the reason.

**Must not be recorded as:** evidence that a sandbox works. It is evidence that
the probe reads the machine.

---

## 2. A capsule is provisioned and persists

**Measures:** §6's persistence claim on a real filesystem.

1. Install a capsule from a catalogue entry (`gimp`).
2. `ls -la ~/.local/share/bunny/capsules/*/` — seven directories, mode `0700`.
3. Write a file into `data/`.
4. Reboot the VM.
5. Open the same application; the file is still there and the capsule directory
   is the same one.
6. `stat` the grant store: mode `0600`.

**Passes if** the directory name matches `<slug>.<16 hex>`, modes are as stated,
and the file survives the reboot.

**Must not be recorded as:** isolation evidence. Nothing has been confined yet.

---

## 3. The sandbox is entered, and the plan is what is enforced

**The step that matters.** Everything in the security review's §2.3 that says
"refused" becomes a measurement here or stays a design claim.

1. Grant one file (`~/Pictures/cat.png`, read).
2. Build the plan, render the argv, and run it with a shell **inside** the
   sandbox rather than the application:
   ```sh
   python3 -c "…build plan…; print(' '.join(argv))"   # inspect first
   # then substitute /usr/bin/bash for the application command
   ```
3. From inside, record:

| Check | Expected | Command |
|---|---|---|
| Home directory absent | no `/home/bunny` | `ls /home` |
| Granted file present, read-only | present; write fails `EROFS` | `cat /run/bunny/files/*/cat.png; : > /run/bunny/files/*/cat.png` |
| A *non*-granted file unreachable | not found | `cat ~/Pictures/dog.png` |
| Another capsule's data unreachable | not found | `ls ~/.local/share/bunny/capsules/` |
| Camera device absent | no `/dev/video0` | `ls /dev/video*` |
| Render node absent without a gpu grant | no `/dev/dri` | `ls /dev/dri` |
| Environment is the eight keys | exactly those | `env \| sort` |
| No network without a grant | fails | `getent hosts example.com` |
| `/tmp` is a tmpfs, not the host's | empty | `mount \| grep ' /tmp '` |
| Capsule directories writable | writes succeed | `touch /run/bunny/app/data/x` |

4. Repeat with a `gpu` grant and confirm `/dev/dri` appears **and nothing else
   does**.
5. Repeat with a `network` grant of `internet` and confirm resolution works.

**Passes if** every row matches. **A single mismatch is a security finding**, not
a configuration note.

**Negative control:** run the same shell *without* `bwrap` and confirm the checks
fail in the opposite direction. A test that passes because the command was wrong
looks identical to one that passes because the sandbox works.

**Must not be recorded as:** evidence about the application. It is evidence about
the sandbox.

---

## 4. Portals deny what was not granted

**Measures:** the five portal-mediated categories.

1. With no `camera` grant, have the capsule call the Camera portal. Expect a
   refusal from the portal, not from Bunny.
2. Grant `camera` at `session`, repeat, expect success.
3. Stop the capsule. Confirm the session grant is dropped
   (`trust/store.py:end_session`) and the next call is refused again.
4. Repeat for microphone, screen capture, location and notifications.
5. Attempt a D-Bus call to a destination not in `dbusTalk` and confirm the proxy
   refuses.

**Passes if** each refusal comes from the portal or the proxy. **If a refusal
comes from Bunny's own code, the test has not measured what it claims** — Bunny
refusing is a policy result; the portal refusing is an enforcement result.

---

## 5. Privileged operations still go through the broker

**Measures:** that no new privileged path was created.

1. Trigger a `sensitive_system` permission and confirm the operation reaches
   `bunny-system-broker` over `/run/bunny/broker.sock`, with Polkit consulted.
2. Confirm the capsule cannot reach the broker socket directly:
   `ls /run/bunny/` from inside the sandbox.
3. Confirm nothing in the capsule tree is setuid: `find ~/.local/share/bunny -perm -4000`.

---

## 6. Fail-closed behaviour, on a real system

Each of these is a deliberate break, and each must produce a denial rather than a
default.

| Break | Expected |
|---|---|
| `kill` the permission surface while a prompt is up | Operation denied, `surface-failed`, **no grant written** |
| Corrupt `grants.json` (truncate it) | Every check denies, `store-unreadable`, and Settings says so |
| Remove `bwrap` and disable user namespaces | Launch refuses, naming what is missing; **the application does not start unconfined** |
| Kill the companion runtime mid-task | The capsule's processes remain confined (check `/proc/<pid>/ns/mnt` differs from init's) |
| Fill the disk, then revoke a permission | Either the revocation lands durably or it reports failure; **never reports success without landing** |
| Set the clock backwards one hour | No expired grant returns |

**§22's central claim is the fourth row.** If the companion runtime dying widens
anything, the architecture is wrong and the phase does not pass.

---

## 7. The §33 vertical slice, with a person

Run by somebody who did not write it, without a terminal open.

1. Boot to the desktop. The Companion is visible.
2. Say/type: *"Help me edit this image."*
3. A choice appears including a commercial option and a free one, with costs.
4. Choose the free one.
5. A permission prompt appears naming **one file**.
6. Allow once.
7. Watch the task workspace: seven steps, real progress.
8. The result appears in Pictures with a new name.
9. Open the original: byte-identical.
10. Open Settings → App Capsules → the application: see the permission, the
    reachable path, the storage, the activity.
11. Revoke the permission. Confirm the sentence says when it takes effect.
12. Re-run the task. Confirm it asks again.

**Passes if** steps 1–12 complete **without opening a terminal** (§33's closing
requirement), and the tester can afterwards say what the application was allowed
to see.

**Record:** a screen recording, the `activity.jsonl`, the isolation plan, and the
tester's own description of what happened in their words. The last one is the
evidence that matters and the one most often skipped.

---

## 8. Performance, measured for real

The seven metrics `CAPSULE_PERFORMANCE_REPORT.md` §5 lists, with
`SubprocessExecutor`. Cold launch, warm launch, memory, CPU, disk, GPU
compatibility, portal latency.

**Record the host** — CPU, RAM, disk type, whether nested. A number without a
machine attached is not a measurement.

---

## 9. Recording the outcome

For each section: `PASS`, `FAIL`, `NOT_RUN`, or `NOT_AVAILABLE`. Nothing else, and
in particular **never `PASS` for a step that was skipped** — `NEXT_PHASE.md`'s
rule for the V4 visual track applies here identically.

A completed run produces:

* `evidence/capsules/<commit>/` with the command output for each section
* the isolation plans and argument vectors used
* the `activity.jsonl` from §7
* the host record from §8
* a one-page summary that states which sections did **not** run

**Do not update `COMPANION_CAPSULES_TRUST_REPORT.md` §20 from anything but a
completed section.** The report currently says nothing has been runtime validated;
that sentence is correct until a section here says otherwise, and changing it
early is how a repository comes to disagree with itself.
