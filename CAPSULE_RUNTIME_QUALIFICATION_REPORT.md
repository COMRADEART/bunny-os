# App Capsule runtime qualification — what was measured, and what was not

**Branch** `feature/bunny-companion-capsules-trust`
**Evidence commits** `37f74c0` (host runtime), `57068ea` (VM boot)
**Host** Fedora Linux 44, kernel 6.18.33.2-microsoft-standard-WSL2, ext4, user `bunny` (uid 1000)
**Date** 2026-08-10

---

## 1. Evidence levels

§21 asks that no result be called "working" without saying at which level. Every
claim in this document carries one of these six and nothing else:

| Level | Meaning | Reached in this phase |
|---|---|---|
| **IMPLEMENTED** | source exists and is reviewed | yes |
| **UNIT TESTED** | an automated test asserts it and passes | yes — 262 tests |
| **HOST RUNTIME VALIDATED** | observed on a running Linux host | yes — 8 sections, real capsules |
| **VM RUNTIME VALIDATED** | observed on a booted Bunny OS image | **boot only** — see §6 |
| **PHYSICAL HARDWARE VALIDATED** | observed on real hardware | no |
| **RELEASE QUALIFIED** | inside a passing `gate-stable-release` | no |

The gap between rows four and five is the honest position of this phase, and §6
is precise about where it falls.

---

## 2. The qualification host

Recorded before anything ran, in `qualification/capsules/evidence/37f74c0*/host.json`.

| | |
|---|---|
| OS | Fedora Linux 44 |
| Kernel | 6.18.33.2-microsoft-standard-WSL2 |
| Bubblewrap | 0.11.0 |
| systemd | 259 (259.8-1.fc44) |
| Flatpak | **absent** |
| cgroup | v2, `cpu memory pids` delegated to the user manager |
| User namespaces | `max_user_namespaces=63133` |
| SELinux | **Disabled** |
| Filesystem | ext4 |
| Virtualisation | wsl |
| User | `bunny`, uid 1000, not root |

**Three limits of this host are recorded in the evidence rather than left for a
reader to infer.** Flatpak is not installed, so its backend is `NOT_RUN` and
every result below is the bubblewrap backend. SELinux is Disabled, so nothing in
§3–§5 is evidence about SELinux — the capsule design treats it as one layer among
namespaces, cgroups, portals and Polkit, and only the other layers were active.
And the kernel is Microsoft's, not Fedora's stock one, so a namespace or cgroup
behaviour measured here should be re-measured on the shipped kernel before it is
called a property of Bunny OS.

---

## 3. The negative control

Every isolation result below is a *comparison*. The same probe program runs twice
— once inside a capsule, once outside as the same user on the same machine — and
a check counts as isolation only when the control reached the thing and the
capsule did not. `compare()` refuses to conclude anything from a run whose
control reached nothing.

This is not ceremony. Two things it caught:

* **A host with no camera scores as a working camera restriction.** `/dev/video*`
  does not exist here. Without the control, `camera: DENIED` inside would have
  read as enforcement; with it, the row is `INCONCLUSIVE` and says so.
* **Mount-namespace isolation looks like ENOENT, not EACCES.** A path outside the
  namespace produces "no such file", which is indistinguishable from a host that
  never had the file — *unless* the control shows the file is there. The first
  version of the comparison counted only `DENIED` and scored 2 isolated checks;
  the corrected version scores 17.

The resources section has its own control for the same reason: a plain systemd
user scope with no capsule and no bubblewrap anywhere near it (§5).

---

## 4. Isolation — HOST RUNTIME VALIDATED

`isolation.json`, `crossapp.json`, `filegrant.json`, `network.json`.

**17 checks isolated**, each reached by the control:

| Check | Capsule | Control |
|---|---|---|
| the user's home directory | absent | 8 entries |
| `~/.ssh`, `~/.ssh/id_ed25519` | absent | readable |
| `~/.gnupg`, `~/.mozilla`, `~/.config` | absent | readable |
| another capsule's private storage | absent | enumerable |
| a neighbouring file in a granted folder | absent | readable |
| `/etc/passwd` via `../../../..` traversal | absent | readable |
| a symlink from the capsule pointing at a credential file | absent | readable |
| writing outside the sandbox | denied | permitted |
| writing at the sandbox root | denied | denied |
| external network, DNS, loopback | denied | reachable |
| system and session D-Bus | absent | connectable |

**Structural properties, not counts.** An earlier version of this harness capped
the number of mounts, which is a magic number that breaks when a bind is added
and passes when the wrong thing is mounted. What is asserted now:

* every mount point inside is one the plan asked for — 22 inside against 39
  outside, all under `/`, `/dev`, `/proc`, `/tmp`, `/usr` and the seven capsule
  directories;
* the environment is **exactly** the eight keys the plan declares, with
  `LD_PRELOAD`, `PYTHONPATH` and `http_proxy` set in the harness and absent
  inside;
* 2 processes visible inside against 102 outside.

**Positive controls too.** A sandbox that denied everything would pass every row
above and be useless, so the capsule is also required to read and write its own
private data, start a subprocess, and have a working `/tmp`. All four pass.

**Cross-application.** App B could neither read nor enumerate App A's private
storage before or after an authorised transfer, and after the transfer could read
exactly the one artefact it was granted. A's private directory was never mounted
anywhere.

**File grants.** No grant → denied. Granted → readable. A neighbouring file in the
same folder → denied. Allow-once left no standing grant. A standing grant was
reused without being rewritten and survived a restart. Revoked → denied.

**Network.** No grant → external, DNS and loopback all denied. Granted internet →
reachable. An allowlist naming `example.com` → the capsule also reached
`example.org`; recorded as a disclosed gap and now reported by the product (§7).

---

## 5. Crash boundaries and resources — HOST RUNTIME VALIDATED / BLOCKED

**Crash — PASS.** `crash.json`.

* Killing the launcher while a capsule ran left **no process in the host mount
  namespace**. The survivors' `/proc/N/ns/mnt` were compared against the
  harness's own; none matched.
* Stopping the systemd scope terminated the whole tree — **0 orphans**.
* Corrupting the permission store while the system was running made the next
  request deny with `store-unreadable`. The policy path fails closed at runtime,
  not only in a unit test.

**Resources — BLOCKED, and BLOCKED is the accurate verdict.** `resources.json`.

| Measurement | Result |
|---|---|
| `TasksMax=48` | **enforced** — 45 threads started, then "can't start new thread" |
| `MemoryMax=256 MB` | **not enforced** — the application allocated 2 GB |
| Cold launch | 1.3–1.9 ms to the launcher returning |
| Steady state | 17.2 MB RSS over 3 processes |
| Capsule disk | 6 KB after a first run |

The memory row is the one worth reading carefully. `memory.max` reads back
exactly as set, the `memory` controller is delegated to the user manager, and the
kernel does not act on the limit. The negative control settles it: **a plain
systemd user scope with no capsule and no bubblewrap allocated the same 2 GB
against the same ceiling.** Bunny applies the limit correctly; this kernel ignores
it. That is not a PASS and it is not a Bunny failure, so the section reports
`BLOCKED` — this host cannot answer the question.

An earlier version of this check counted any SIGKILL as enforcement. On a host
that ignores `MemoryMax` the process is duly killed — at 4.5 GB, by the machine's
own out-of-memory killer — which reads as the cgroup working and is the opposite
of the truth. The rule is now that the allocation must stop *near the ceiling*.

**Cold launch is 1.3 ms to the launcher returning, not to a window appearing.**
That number is Bunny's overhead. An application's time-to-first-frame has not
been measured and is not claimed.

---

## 6. The VM — boot, then the full suite inside it

`vmboot.json`, at commit `57068ea`. The qualification run inside the booted
guest is §9.

The image this branch produces was built (2.97 GB qcow2, 3.1 GB OCI archive,
8m47s) and booted under QEMU. **VM RUNTIME VALIDATED** for exactly this:

* GRUB offers `Bunny OS 0.1.0 (development) (ostree:0)`;
* `bunny-system-broker` socket and service both start;
* `bunny-health-check` finishes;
* `gdm` starts and `graphical.target` is reached;
* 51 units started, 67 targets reached, **no failed unit**;
* SELinux is **enforcing** in the guest — the first place in this phase that
  layer is active at all.

Separately verified: the image contains `/usr/lib/bunny-os/python/{trust,capsules,catalog}`
and `/usr/share/bunny-os/catalog/*.json`, and all three import inside the image
with the catalogue resolving to the installed path.

**What the VM has not shown.** The harness boots and greps a serial log. It
performs no login, starts no graphical session, launches no capsule, draws no
Companion and answers no permission prompt. Therefore:

| Claim | Status |
|---|---|
| the image boots to a graphical target | VM RUNTIME VALIDATED |
| the three packages are in the image and import there | VM RUNTIME VALIDATED |
| a capsule confines an application on the booted system | VM RUNTIME VALIDATED — §9 |
| SELinux is enforcing while a capsule runs, and refuses nothing it needs | VM RUNTIME VALIDATED — §9 |
| `MemoryMax` is a boundary on the shipped kernel | VM RUNTIME VALIDATED — §9 |
| AVC denials during capsule operation | **NOT MEASURABLE in this image** — every collector is blind; §9 |
| the Companion can launch a capsule at all | HOST RUNTIME VALIDATED — the `launcher` section post-dates the guest run |
| the Companion is visible on a Bunny desktop | **NOT RUN** |
| the Trust prompt is drawn and answerable | **NOT RUN** |
| the §15 image-editing journey completes | **NOT RUN** |
| the failure variant behaves safely on screen | **NOT RUN** |
| accessibility driven with Orca, keyboard, high contrast | **NOT RUN** — Orca is not installed on the qualification host |

The isolation and permission columns were first measured on a Linux host running
the production runtime and then again inside the booted guest, and the two are
kept apart above rather than merged. What remains unmeasured is everything with
a person in it: nothing in this phase has drawn a Companion, raised a Trust
prompt on a screen, or completed a task a person asked for. That is not a gap in
the security evidence; it is the whole of the user-facing claim, and it is
recorded as NOT RUN rather than inferred from the parts that do work.

---

## 7. Defects found, and what changed

Ten, none of which was visible from a Windows developer host. Four made the
feature not work at all — and the last two of those, L-9 and L-10, were not
visible from a Linux host either until something asked the question the product
asks: not "can a capsule be launched" but "can the thing that launches capsules
launch one".

| # | Defect | Severity | Fix |
|---|---|---|---|
| L-1 | **Every capsule launch failed.** `SubprocessExecutor` started the launcher with `env={}`, and `systemd-run --user` cannot reach the session bus without it. The sandbox was fine; nothing could start it. | **Blocker** | Two named launcher variables; `--clearenv` still separates them from the application |
| L-2 | **A capsule whose process exited stayed `running` forever**, so the second launch of any application refused permanently. | **Blocker** | pid recorded, executor polled, `reconcile()` before any launch decides; `last_exit_code` is now filled |
| L-3 | **A resource display defaulted to the whole absolute path** — on a person's screen and in the audit record. Windows hid it because its temp directory sits under the user profile. | High | Default to the user's own directories; a separate `log_display` elides the directory for a path outside them |
| L-4 | **A network grant was unusable**: a capsule could reach a raw address and not resolve a name, because nothing told it where a resolver was. | High | A network grant brings a read-only resolver and trust store; no grant brings neither |
| L-5 | **The allowlisted network class is not a boundary.** A capsule granted `example.com` reached `example.org`. | High, disclosed | `network_enforced` on the plan; Settings and the status surface say so; the category's enforcement text names which two of four classes are a kernel boundary |
| L-6 | **A route the build context could not see reported as installed.** The three new packages were in `install_routes.py` and not in the Containerfile; the image would have shipped a companion importing packages that were not there. | **Blocker** | Containerfile copies them; a fourth classification `route-without-context`; a test asserts every route source is inside a context root |
| L-7 | The sandbox root was writable — contained, but a capability the capsule had and the unconfined control did not. | Low | `--remount-ro /` after the binds, measured to keep the capsule's own directories writable |
| L-8 | **`MemoryMax` is declared and this host ignores it**, with nothing saying so. | Medium, disclosed | The plan reports limits whose controller is not delegated; Settings and the status surface show them |
| L-9 | **The Companion could not launch a capsule at all.** A capsule was a `systemd-run --user --scope`, a scope is forked by whoever asks for it and inherits that process's seccomp filter, and both Companion units set `RestrictNamespaces=yes` — while bubblewrap's whole mechanism is `unshare(2)`. Always, on every machine. Every section of this suite had launched from a login shell, which nothing in the product does. | **Blocker** | The renderer asks the manager for a transient *service*; the manager spawns it, so nothing of the launcher's is inherited. The capsule keeps its cgroup and its declared limits |
| L-10 | **The Companion could start a capsule and not keep one.** Installing a capsule writes the capsule root and recording a grant writes the trust store, both under the user's XDG directories, which `ProtectHome=read-only` covers. The install failed on its first write. | **Blocker** | `ReadWritePaths=` on the runtime unit only, plus the user-tmpfiles rule that makes the roots exist — a `ReadWritePaths=` path that does not exist fails namespace setup with 226/NAMESPACE before `ExecStart` |

Six harness defects were also found and are worth recording because each would
have produced a false PASS: counting only `DENIED` as isolation (2 checks instead
of 17), truncating structured probe output so a comparison silently skipped,
counting any SIGKILL as memory enforcement, probing writability at the harness's
own `/tmp` override — where `PrivateTmp=`, not `ProtectHome=`, decides the answer
— reproducing a unit's restrictions without its `ReadWritePaths=` relaxation, so
the fix was invisible to the check, and reading a *stale installed* unit on the
developer host in preference to the one under test.

### Why L-9 and L-10 took a new section

Every section above launches a capsule from a plain login shell. That is the
right place to measure what a capsule can *reach* and the wrong place to measure
whether one can be *started*, because nothing in the product starts one from a
login shell. The `launcher` section reproduces the launch inside a transient unit
carrying each shipped Companion unit's own directives — read out of the unit
files rather than copied, so a directive added to a unit is measured without
anybody remembering to — and runs four shapes:

| Shape | Before the fix | After |
|---|---|---|
| `direct` — the vector from a plain process | started | started |
| `permissive` — nested in a transient unit with no properties | started | started |
| `hardened` — nested in a unit with the Companion's own properties | **failed** | started |
| `scope` — the pre-fix vector, same properties | failed | **still fails** |

The fourth is the section's own control. Everything passing is the intended
result and is also exactly what a section that had quietly stopped measuring
anything would report; without a shape that must fail there is no way to tell
those apart. It is asserted in both directions on the writability half too: the
runtime unit must be able to write the state roots, and the window unit must not
— a renderer that can write the trust store can mint its own grants.

---

## 8. Stop conditions

§24 lists eight. None occurred.

| Condition | Observed |
|---|---|
| sandbox escape | no |
| unexpected home access | no — home absent inside, present to the control |
| cross-app data leak | no — before and after an authorised transfer |
| approval replay | no — refused with `replayed` |
| permission fail-open | no — six failure paths, six distinct reasons, no grant written |
| unconfined fallback | no — and `select_backend` refuses rather than downgrading |
| privilege escalation | no |
| credential leakage | no — `~/.ssh` and friends absent inside, readable to the control |

---

## 9. What was measured inside the booted guest

Run at image commit `57068ea4b2b5`, kernel 7.1.5-200.fc44, SELinux **Enforcing**
with the targeted policy at version 35, as `bunny` (uid 1000) in a real login
session. Evidence under `qualification/capsules/evidence/guest-d9a36620044d/`.
All eight sections then present returned PASS.

Two results the WSL host could not produce:

**Memory is enforced by this kernel.** The capsule allocated 209,715,200 bytes
against a 268,435,456 ceiling with 2,934 `memory.events.high`, zero `max` and
zero `oom_kill`: `MemoryHigh` throttled it and it never reached `MemoryMax`. The
control — same ceiling, no `MemoryHigh` — was killed by the cgroup at
243,269,632 bytes. On the WSL host the same control allocated 2 GB against the
same ceiling and nothing stopped it. So `MemoryMax` is a real boundary on the
shipped kernel; L-8 is a property of the development host, not of Bunny OS.

**AVC collection is blind, and says so.** `journalctl` carries no kernel lines,
`ausearch` is not installed, and `dmesg` refuses the ordinary user because
`kernel.dmesg_restrict` is 1 — and returns an empty buffer even to root. The
section reports *blind* with a positive control rather than reporting zero
denials. A zero nobody could have seen is not a measurement, and the honest
consequence is that this build has no evidence either way about AVC denials
during capsule operation. Adding `audit` to the qualification test profile is
the fix; it has not been done, because a test profile must not ship.

The `launcher` section post-dates that run and has been measured on the Linux
host only. Re-running it in the guest needs an image rebuild, because the guest
runs the packages the image installed and only the harness is injected.

### 9.1 Non-PASS records, and what supersedes them

Evidence is append-only, so a record that later code or a later run answered
stays on disk saying what it said. The table below is the disposition of every
non-PASS record under `qualification/capsules/evidence/`, so nobody has to
re-derive whether a FAIL is live.

| record | verdict | disposition |
| --- | --- | --- |
| `37f74c038d41/resources.json` | BLOCKED | Host limitation: that kernel ignores `MemoryMax` (no `memory` cgroup row). Superseded by the guest run in §9, where memory **is** enforced. |
| `596d9e1bf9eb/resources.json` | BLOCKED | Same cause, same disposition. |
| `596d9e1bf9eb/selinux.json` | BLOCKED | SELinux Disabled on the qualification host. Superseded by guest records at Enforcing. |
| `guest-4c6e101bd354/apptask.json` | FAIL | `allowOnceLifetime.ok: false` — a session grant survived its task. Fixed in `39a5c575` (`capsules/runtime.py`, drop moved into `reconcile()`); superseded by `guest-524107e50b2e/apptask.json`, a direct descendant of the fix, which records `allowOnceLifetime.ok: true`, PASS. |

No live FAIL remains in this tree. No evidence file was edited.

---

## 10. What to do next, in order

1. **Rebuild the image and re-run the guest qualification**, so `launcher` — and
   therefore both L-9 and L-10 — is measured against the units the image
   actually installs rather than the ones in the checkout.
2. **Install Flatpak on the qualification host and re-run.** One backend of two
   is currently `NOT_RUN`, and Flatpak is the one most applications will use.
3. **Get a login into the VM and drive the §15 journey.** The harness has no
   login injection; the desktop work in this repository (`desktop-drive.py`,
   virtio-tablet pointer injection, AT-SPI) is the existing route.
4. **Install Orca and drive the accessibility pass.** The Trust prompt is the
   only modal Bunny raises unasked; if it does not raise correctly in the AT-SPI
   tree a screen-reader user meets a silent modal, which is worse than anything
   this phase fixed.
5. **Decide about the allowlisted network class**: implement per-name filtering,
   or remove the class and offer only off / local / on. It is currently a word
   that promises more than it does, disclosed but still present.

Items 1 and 2 need nothing but time on the existing builder.
