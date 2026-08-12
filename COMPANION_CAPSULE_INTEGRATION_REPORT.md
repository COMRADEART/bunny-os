# Companion → Trust → Capsule Integration — Phase Report

**Branch** `feature/bunny-companion-capsules-trust`
**Branch point** `262b06d`
**Date** 2026-08-12

**The problem this phase was given:** *"`capsule_bridge.py` exists, Capsule
security works, and the Companion works, but the production Companion task path
does not call the Capsule bridge."* The user-facing system and the security
execution system were disconnected.

**They are now connected**, and the connection has been exercised on a real
kernel with SELinux enforcing — including the part §30 of the brief exists for:
the permission question was **answered on screen**, by a pointer event pressing
*Allow this Bunny action* at its own accessibility extents, after which the
capsule ran and the file appeared. The graphical harness has no code path that
can resolve an approval any other way.

What remains for §30 is the **denied** and **failing** slices through the same
surface; until those run, the phase is **INCOMPLETE**.

---

## 1. The route, as built

```
User
 └─ Companion UI  (GNOME Shell extension, GJS)
     └─ bunny-shell-assistant          the desktop's only route to the runtime
         └─ CompanionClient            AF_UNIX, newline-delimited JSON
             └─ Gateway.submit_task
                 ├─ _capsule_inputs_for_request   ← the ONE place words become a path
                 └─ Runtime
                     ├─ classify → capability → executor
                     ├─ ToolBroker: image.resize
                     ├─ TrustGate + ConsentSurface   ← the person is asked
                     └─ CapsuleTaskBridge
                         └─ capsules.runtime
                             └─ systemd-run --user --unit=…   (a service, not a scope)
                                 └─ bwrap --unshare-{user,pid,ipc,uts,cgroup,net}
                                          --remount-ro / --clearenv
                                     └─ /usr/libexec/bunny-image-tool
                                         └─ exports/ → Pictures/    (the runtime copies out)
```

No second task engine, no unconstrained fallback, and no visual simulation
disconnected from real execution — the three things the brief forbade.

The resolver deserves its own line. `_capsule_inputs_for_request` is the only
place in the system where a request's *words* become a *path*. It is outside the
executor, the plan and the operation table, so a provider proposing an operation
cannot choose the file it runs on, and a resolved path never travels in an
argument list where a later reader might treat it as data. Resolution is closed:
a plain name, inside the user's own Pictures directory, symlinks resolved and the
parent re-checked.

## 2. Defects this phase found and fixed

Eighteen. Every one was found by running something, not by reading it — a
kernel, a compositor, a screenshot or the test suite. None came from review.

| # | Defect | Found by |
|---|---|---|
| 1 | A capsule launched as a `--scope` inherits the caller's seccomp filter and mount namespace, so under the Companion's own `RestrictNamespaces=yes` **the Companion could never launch a capsule at all** | Host runtime |
| 2 | `ProtectHome=read-only` blocked the capsule root and trust store; installing a capsule failed on the first write | Host runtime |
| 3 | `Resource.digest` hashed kind+path, not content, so the substitution check compared identical digests | Host runtime |
| 4 | `--collect` plus `poll()` returning 0 turned "could not be executed" into "succeeded, wrote nothing" | Host runtime |
| 5 | Allow-once produced **no bind**: Trust never persists `once`, and the plan was built from persisted grants | Host runtime |
| 6 | Transient-unit stdout was inherited and discarded, so a failure had no diagnosis | Host runtime |
| 7 | A session grant outlived its task: the drop lived in `stop()`, which returns early for an already-stopped capsule, and `reconcile()` is what had stopped it | **Guest** regression (the unit suite passed before *and* after) |
| 8 | Export failed with EROFS — the Companion could do everything except put the result down | **Guest** boot |
| 9 | `CapsuleTaskFailure` was a plain `Exception`; the runtime only catches `CompanionError`, so tasks stalled in `waiting_for_executor` | Guest |
| 10 | **A failed operation produced a `completed` task.** `TaskResult` had no failure channel and the runtime asked nobody | Guest, failing slice |
| 11 | The shell's `ask` deadline ran while a person was being asked, so a pending permission was reported as "the runtime did not finish within the deadline" | **Screenshot** |
| 12 | The desktop claimed "Assistant offline" because the health check was asked once, before the companion's socket existed | **Screenshot** |
| 13 | **P0: the assistant bridge was committed with CRLF, so its shebang named `/usr/bin/python3\r` and the kernel refused the exec.** The desktop could never start its assistant | **Screenshot**, then asking the image directly |
| 14 | The desktop keeps its *own* 200 s watchdog, which also knew nothing of approvals and replaced the permission prompt with "The assistant did not answer in time" | **Screenshot** |
| 15 | A permission question appeared without taking focus, so a keyboard user had to hunt for it and a screen reader announced nothing | Accessibility pass |
| 16 | The desktop ignores `text-scaling-factor` and `high-contrast` entirely | Accessibility pass — *found, not fixed*; see §6 |
| 17 | Five of eight launcher labels ellipsised, four sharing the prefix that told them apart | Screenshot |
| 18 | A `guestfish` probe in the qualification injector whose result was never read — an extra VM boot per injection | ShellCheck, in the suite |

Five of the last eight were found by *looking at a picture*. Nine text-only
diagnostics had not found #11; and #13 was introduced by the fix for #11, one
commit before the run that exhibited it, which is why the two are told as one
sequence in §2.1.

#11 and #14 are the same defect in two places, which is the more useful
observation: fixing the bridge's clock did not fix the desktop's, and neither
knew that a question on somebody's screen is the system working. The rule that
came out of it is in `TRUST_RUNTIME_REPORT.md` §4.1.

### 2.1 The two that say the most

**#1, the launcher shape.** A scope runs in the caller's context. The fix — a
manager-spawned transient service — is one word, and without it the product's
central promise could not work on any machine in any configuration. The old shape
is kept as a live negative control, so a change that reverts to a scope fails a
test rather than silently shipping an unlaunchable product.

**#13, the CRLF shebang.** `.gitattributes` names this exact hazard, for this
exact directory, in a comment that describes the failure mode precisely. It marks
the path `-text` so git will not *introduce* CRLF — which is a different
guarantee from the bytes being clean. `-text` reproduces verbatim, so once the
bytes are committed the guard is what keeps them. The guard is now on the bytes,
checked against what git *stores*.

The bytes were introduced by **the fix for #11**: the shebang was LF at
`670381a` and CRLF at `1b58edf`, because that file was edited from a Windows
working copy and every line ending was rewritten. So #11 and #13 are one
sequence — a real defect, a fix, and a second defect created by the fix, which
then hid whether the first fix had worked. That is the argument for the byte
guard existing at all, and for looking at the screen after every change rather
than after the ones that seem risky.

## 3. What the qualification did and did not see

Eleven guest sections passed, with SELinux Enforcing, on an image whose desktop
could not talk to its own runtime.

None of those results is wrong. They are true statements about layers below the
broken one: the apptask section builds a `PlannedOperation` and calls the broker;
the readiness probe asks the runtime's socket directly. Neither goes through
`/usr/bin/bunny-shell-assistant`, and nothing did until a driver tried to use the
desktop the way a person does.

**The gap was never a missing assertion. It was a missing user.**

The correction is not more assertions at the same layer. It is that the phase now
has a driver which types with a pointer, waits on the character's state, finds a
control by its accessible name and presses it at its own screen coordinates — and
which, when there is no prompt, asks the runtime which event it wrote last rather
than guessing.

## 4. The maturity table

Rows are the phase's claims; columns are the repository's own five-state ladder
(`NEXT_PHASE.md`, "Maturity ladder, 2026-07-30").

| Claim | Implemented | Tested | Runtime validated | Hardware validated | Release qualified |
|---|:--:|:--:|:--:|:--:|:--:|
| **Isolation** |||||
| Namespace, mount, filesystem isolation | ✅ | ✅ | ✅ VM | ❌ | ❌ |
| Credential and IPC isolation | ✅ | ✅ | ✅ VM | ❌ | ❌ |
| Cross-application separation | ✅ | ✅ | ✅ VM | ❌ | ❌ |
| Network class `none` | ✅ | ✅ | ✅ VM | ❌ | ❌ |
| Network allowlisting | ✅ | ✅ | ❌ **not enforced** | ❌ | ❌ |
| Camera / GPU / clipboard isolation | ✅ | ✅ | ❌ inconclusive | ❌ | ❌ |
| SELinux non-interference | ✅ | ✅ | ✅ VM | ❌ | ❌ |
| SELinux denial count | — | — | ❌ **not measured** | ❌ | ❌ |
| **Trust** |||||
| Fail-closed, six paths | ✅ | ✅ | ✅ VM | ❌ | ❌ |
| Grant lifecycle incl. allow-once | ✅ | ✅ | ✅ VM | ❌ | ❌ |
| Resource changed after approval | ✅ | ✅ | ✅ VM | ❌ | ❌ |
| Approval names file, app and network | ✅ | ✅ | ✅ VM | ❌ | ❌ |
| **The route** |||||
| Companion → Trust → Capsule | ✅ | ✅ | ✅ VM | ❌ | ❌ |
| A failed operation fails the task | ✅ | ✅ | ✅ VM | ❌ | ❌ |
| Export, original preserved | ✅ | ✅ | ✅ VM | ❌ | ❌ |
| Crash and orphan boundaries | ✅ | ✅ | ✅ VM | ❌ | ❌ |
| **The surface** |||||
| Graphical session reaches readiness | ✅ | ✅ | ✅ VM | ❌ | ❌ |
| The desktop can start its assistant | ✅ | ✅ | ✅ VM | ❌ | ❌ |
| The Trust prompt renders | ✅ | ✅ | ✅ VM | ❌ | ❌ |
| **The prompt is answered by pressing it** | ✅ | ✅ | **✅ VM** | ❌ | ❌ |
| The task completes from that press, and the file appears | ✅ | ✅ | ✅ VM | ❌ | ❌ |
| Visible sandbox state | ✅ | ✅ | ❌ not reached on screen | ❌ | ❌ |
| Trust history is reachable by a person | ✅ | ✅ | ❌ not reached on screen | ❌ | ❌ |
| A choice between applications | — | — | ❌ **one application registered** | ❌ | ❌ |
| Accessibility: names, roles, focus, safe default | ✅ | ✅ | ❌ | ❌ | ❌ |
| Accessibility: the screen reader is present and starts | ✅ | ✅ | ✅ VM | ❌ | ❌ |
| **Accessibility: text scaling and high contrast** | ❌ **ignored** | ✅ | ✅ VM *(measured absent)* | ❌ | ❌ |
| **Performance** |||||
| Launch, memory, disk, ceilings | ✅ | ✅ | ✅ VM | ❌ | ❌ |
| GPU / portal latency | — | — | ❌ not measured | ❌ | ❌ |

Nothing in this phase reaches **Hardware validated** — there is no device — or
**Release qualified**: `gate-stable-release` is `NO-GO` and this phase does not
change that.

## 5. Numbers

| | |
|---|---|
| Guest qualification | 11 of 11 sections PASS, suite exit 0 |
| Test suite | **5076 tests, 0 failures, 9 skipped**, exit 0 — as `bunny` on ext4, from a clone, at HEAD |
| Capsule cold launch | 16.2 ms |
| Namespace overhead | ≈ 3.9 MB per running capsule |
| Capsule disk | 7,305 B |
| End-to-end journey | 214.4 ms, exit 0 |
| Memory ceiling | throttled at 200 MB (2,985 `memory.high` events, 0 OOM kills); the unconfined control was SIGKILLed |
| Isolation checks | 32 paired; 17 ISOLATED, 6 SHARED (5 of them isolated in content), 6 INCONCLUSIVE, 3 BOTH-DENIED |

## 6. Disclosed gaps

Each was recorded by the measurement that found it, alongside a pass, rather than
being omitted:

1. **Network allowlisting is a declaration, not a boundary.** A capsule granted
   `example.com` connected to `example.org`. Only `none` is enforced. No
   user-facing string may imply per-domain enforcement.
2. **SELinux denials could not be observed.** `dmesg_restrict=1`, no `ausearch`,
   zero kernel lines in the journal. The recorded count of `0` means *nobody
   looked*.
3. **Six isolation checks are inconclusive** because the console control could
   not reach the resource either. Counting them as passes would have inflated 17
   to 23 and made the suite weakest where it looked strongest.
4. **No hardware.** Everything is `kvm` on one host.
5. **The approval has never been answered by a person.**
6. **The desktop ignores text scaling and high contrast.** Measured, not
   inferred: setting either leaves the screen pixel-identical, because 43 of 43
   font sizes in the shell stylesheet are absolute pixels and all 151 colour
   literals are hardcoded. This is the largest accessibility gap in the product
   and it is not a small fix.

## 7. The reports

| Report | Covers |
|---|---|
| `GUEST_CAPSULE_QUALIFICATION_REPORT.md` | The 11 sections in a booted guest, SELinux enforcing |
| `CAPSULE_VM_SECURITY_REPORT.md` | The boundary as built, and what the measurement cannot see |
| `TRUST_RUNTIME_REPORT.md` | The permission layer as it behaved, not as specified |
| `GRAPHICAL_SESSION_REPORT.md` | Eight readiness conditions, and how guessing was removed |
| `VISUAL_SLICE_REPORT.md` | The journey, and the chain of three defects behind the prompt |
| `VISUAL_QA_REPORT.md` | Findings from looking at the desktop |
| `PERFORMANCE_BASELINE_REPORT.md` | The six §24 numbers; five now exist |
| `TRUST_ACCESSIBILITY_REPORT.md` | Assistive technology against the booted session. **Not** `ACCESSIBILITY_QUALIFICATION_REPORT.md`, which is generated from `operations/data/qualification-matrices.json` and must not be hand-edited |
| **this document** | The route, the defects, and the maturity table |

## 8. What must happen before this phase can be called complete

1. **A person presses Allow.** The driver exists, the bridge now starts, and the
   prompt renders. This is the one blocking item.
2. The denied and failing slices, through the same surface.
3. The accessibility run against the prompt while it is on screen — keyboard
   reachability of a permission dialog is a security property, not a nicety.

Everything else in the brief is delivered, and the gaps above are disclosed
rather than closed.
