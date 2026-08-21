# The capability control plane, as installed

`docs/CAPABILITY_RUNTIME.md` describes the engine that decides;
`docs/CAPABILITY_APPLICATOR.md` describes the layer that acts. This describes
what is actually on an installed Bunny OS, how it starts, what it may touch, and
— just as carefully — which claims in this document are measurements and which
are not.

Every statement below carries one of: **Implemented**, **Unit tested**,
**Integration tested**, **Measured**, **Not run**, **Blocked**, **Planned**.

## Build-input closure

`build/scripts/build-input-closure.py` decides whether a change reaches the
artifact. It exists because that question was answered by inspection once and
answered wrongly. **Implemented, unit tested** (33 tests in
`tests/capability/test_image_integration.py`).

It classifies every repository path as:

| Class | Meaning |
|---|---|
| `installed` | reaches the committed layer. **Build-affecting** |
| `context-only` | visible to the build, installed by no route it can see |
| `unreachable` | absent from every `COPY`; cannot affect the artifact |

It reads two sources: the Containerfile's `COPY` set, and `install-root.py` —
both its literal `copy_file`/`copy_tree` calls, parsed from the AST, and its
`INSTALL_ROUTES` table.

**The table is the interesting part.** Destinations computed inside a loop
cannot be resolved from an AST, and an analyser that reported such a path as
"not installed" would license exactly the mistake it was written to catch. So
`install_capability` is *driven by* the table rather than merely described by
it, and the analyser reads the same table. A declaration the installer obeys
cannot drift from what the installer does.

**Known limitation of static analysis.** A route whose source glob or
destination is computed from a runtime value is still invisible. The analyser
reports its unresolved calls rather than hiding them, and
`closureComplete` goes false when a `COPY` directive cannot be parsed. It is a
gate, not a proof: a `context-only` classification means "no visible route",
which requires an empirical two-build comparison to become "not in the
artifact".

**Also recorded:** every commit changes the OCI configuration digest through the
`revision` label and `/usr/lib/bunny-os/release.json`. An unchanged layer digest
is not an unchanged image.

## Installed filesystem layout

**Implemented, integration tested** (built and inspected in the artifact).

| Path | Contents | Mode | Owner |
|---|---|---|---|
| `/usr/lib/bunny-os/python/capability/` | the package: runtime and applicator, 44 modules | `0444` | root |
| `/usr/share/bunny-os/capability/services/` | 14 service manifests | `0444` | root |
| `/usr/share/bunny-os/schemas/` | versioned schemas | `0444` | root |
| `/usr/libexec/bunny-capability-supervisor` | entry point | `0555` | root |
| `/usr/lib/systemd/system/bunny-capability-supervisor.service` | the unit | `0644` | root |
| `/etc/bunny-os/capability/supervisor.json` | administrator configuration | `0644` | root |
| `/var/lib/bunny-os/capability/` | persistent state | `0700` | root |
| `/var/lib/bunny-os/capability/reservations.json` | reservation ledger | `0600` | root |
| `/var/lib/bunny-os/capability/approvals.json` | approval records | `0600` | root |
| `/var/lib/bunny-os/capability/retries.json` | retry journal | `0600` | root |
| `/run/bunny-os/capability/` | runtime state, recreated each start | `0700` | root |
| `/run/bunny-os/capability/supervisor.lock` | single-instance lock | `0600` | root |
| `/var/log/bunny-os/capability-audit.jsonl` | audit, bounded | `0750` dir | root:systemd-journal |
| `/usr/share/doc/bunny-os/` | this and the other capability documents | `0444` | root |

Properties this layout is required to have, and how each is enforced:

- **Immutable code cannot write into its installation directory.**
  `ProtectSystem=strict` makes `/usr` read-only to the unit, and
  `ReadWritePaths=` names the complete set of exceptions — none under `/usr`.
  A test asserts that. *Kernel-enforced, not conventional.*
- **State paths do not depend on a home directory.** `ProtectHome=yes`, and a
  test asserts every configured path starts with `/var`, `/run` or `/etc`.
- **Persistent state carries an explicit schema version.** Every durable file is
  an envelope with `stateVersion`, `revision`, `checksum` and `payload`. An
  unrecognised version is refused, not interpreted.
- **Runtime state is recreated safely.** `/run/bunny-os/capability` is the
  unit's `RuntimeDirectory=`, so systemd creates it on start and removes it on
  stop. It is deliberately *not* also declared in `tmpfiles.d`: declaring it in
  both would leave a stale directory, and a stale lock file in it, after stop.
- **Approval data is not world-readable; reservation data is not
  world-writable.** `0600` files inside a `0700` directory, and
  `StateDirectoryMode=0700`.
- **Audit retention is bounded.** `tmpfiles.d` ages `/var/log/bunny-os` at 14
  days, and `JsonLinesAuditSink` rotates by line count.
- **Corrupt state enters safe mode rather than resetting.** See below.

## Supervisor lifecycle

**Implemented, unit tested, integration tested** (runs from installed paths in
the built artifact).

```
acquire single-instance ownership   ← before anything else
  → load and validate configuration
  → load and validate the manifest registry
  → recover the ledger, approvals and retry journal
  → observe actual state
  → collect a bounded capability inventory
  → calculate the resource budget
  → generate the desired plan
  → revalidate it
  → reconcile desired against actual
  → apply permitted transitions        ← only in apply mode
  → write audit records
  → wait for a significant event or the bounded interval
  → repeat
```

Ownership is taken first deliberately: discovering a conflict after building a
backend and reading a registry wastes work and produces a confusing diagnostic.

**Modes.** `observe` reads, plans, reconciles and explains, touching nothing.
`dry-run` additionally rehearses transitions through a recording backend.
`apply` performs them. The shipped configuration is `observe`.

**Installed default.** The unit is enabled by preset and the configuration is
observe-only. Whether the supervisor *runs* and whether it may *change* anything
are separate switches on purpose: a control plane that only starts once an
operator is ready to let it act can never tell them what it would do first.

**No busy loop.** Each cycle ends on `Event.wait(interval)`, which returns
immediately when shutdown is signalled, so stopping does not wait out an
interval and nothing spins.

**Bounds.** Discovery has a wall-clock budget; every backend call has a timeout;
one cycle has a deadline and exceeding it is reported. `Restart=on-failure` with
`StartLimitBurst=5` in 300s is the outer bound on the applicator's own retry
policy — two independently bounded mechanisms rather than one unbounded pair.

**Signals.** `SIGTERM`/`SIGINT` stop; `SIGHUP` reloads policy and manifests.
Reload deliberately does *not* re-read the ledger, approvals or lock: forgetting
reservations for services that are still running would be worse than a stale
configuration.

## Single-instance ownership

**Implemented, unit tested** (`tests/capability/test_apply_durability.py`).

Two supervisors applying plans to one machine is the worst failure this
subsystem has, because each is individually correct: each reserves memory it
believes is free, and nothing can detect the overlap.

`fcntl.flock` on `/run/bunny-os/capability/supervisor.lock` is the exclusion.
The kernel releases it when the holder dies, however it dies, so a crashed
supervisor does not strand it. The owner record — pid, boot id, hostname, role —
is a *diagnostic only*; it never decides exclusion.

**A PID file is not a lock**, and the tests say why: a stale owner record from a
previous boot does not grant ownership, corrupt metadata does not prevent
acquisition, and six threads racing produce exactly one owner. The boot id is
what distinguishes a reused PID after a reboot from the process that actually
holds the lock.

On Windows the module falls back to `msvcrt.locking`, which excludes correctly
but whose crash semantics differ. `describe()` reports `crashSafe` only for
`flock`. *That fallback exists for the developer checkout; the installed target
is Linux.*

**Not run:** behaviour on a network filesystem state path.

## Durable ledger semantics

**Implemented, unit tested** — 14 crash boundaries, in
`tests/capability/test_apply_durability.py`.

Every durable write is: serialize with `stateVersion` + checksum → write to a
temporary file **in the same directory** → `flush()` → `os.fsync()` the file →
`os.replace()` → `fsync()` the directory. Each step is a named crash point that
a test can interrupt.

| Boundary | Result after recovery |
|---|---|
| before temporary file | previous state intact |
| mid-write | previous state intact |
| before file flush | previous state intact |
| before replace | previous state intact, temporary cleaned on next load |
| after replace | new state, complete |
| after reservation | reservation held; a second process cannot take the same bytes |
| after limits applied | uncommitted; reclaimed by expiry |
| after process start, before commit | reservation still held — **not** treated as free |
| before commit | reservation present |
| after commit | commitment preserved; second process refused |
| during release | reconciled against actual state |

The invariant every one of these asks about is the same: **after recovery, can
the same remaining budget be handed out twice?** No boundary permits it.

`flush()` gets bytes to the kernel; `fsync()` gets them to the device. Skipping
the second is the single most common way a "crash-safe" writer turns out not to
be. Directory fsync is attempted and its unavailability recorded rather than
assumed — Windows and some network filesystems refuse it.

**Safe mode.** A file whose checksum fails, whose version is unrecognised, or
which does not parse is **moved aside, not repaired**. The caller enters safe
mode: observe and explain, apply nothing. A ledger that silently reset would
hand out memory already in use; one that kept a truncated tail would be worse.
The damaged file is preserved because "it reset itself" has no answer if the
reader threw it away.

## Approval store

**Implemented, unit tested.** Persisted at
`/var/lib/bunny-os/capability/approvals.json`, mode `0600`.

Three properties do the security work, and file permissions are only the third:

1. **A decision names the plan it was made against.** Approving a dispatch under
   a plan estimating four cents does not approve it under one estimating four
   dollars. Supersession invalidates, with the reason stated.
2. **A decision cannot be forged by editing a field.** The record carries a
   digest over what was consented to — plan, transition, action, destination,
   cost, decision, timestamp, actor. Flipping `decision` to `granted` without
   recomputing it produces a record the store refuses. *This is not
   cryptographic authentication and does not claim to be:* somebody who can
   write the file can recompute the digest. It defends against a well-meaning
   administrator or a buggy tool, and permissions defend against the rest.
3. **Nothing is granted by default.** Unestablished, expired, superseded and
   revoked all resolve to denial. There is no path where absence of an answer
   becomes an answer.

Sensitive actions — remote dispatch, paid provider, interrupting user work,
discarding unsaved state, stopping an essential service, overriding a pin,
sending sensitive data — must state an alternative and must default to denial.
Constructing a request that violates either raises.

## systemd units and privilege

**Implemented, integration tested.** One unit:
`bunny-capability-supervisor.service`.

**The unit runs as root, and that deserves the justification it gets in the
unit file.** The supervisor calls `systemctl` on system units; no unprivileged
identity can do that without a polkit rule granting the same authority under
another name, or a setuid helper with a wider attack surface. The authority is
narrowed **where it is exercised**, not where it is granted:

- unit names are **derived** from service ids by a fixed rule, never read from a
  manifest — so a manifest cannot name a unit, and therefore cannot name
  somebody else's;
- the derived name is checked against an allowlist built from the shipped
  manifests;
- no shell, ever: every invocation is an argument array with `shell=False`;
- the child environment is minimal, so nothing in the parent can redirect it;
- `CapabilityBoundingSet=CAP_KILL CAP_SYS_RESOURCE CAP_DAC_READ_SEARCH` — it
  starts and stops units and reads the kernel; it cannot load modules, change
  time, bind ports or own devices.

**Two hardening directives are deliberately absent, with the measurement behind
each recorded in the unit:**

- `ProtectControlGroups=yes` — **incompatible**. The applicator verifies
  enforcement by reading a unit's real cgroup. With this set the read-back
  cannot happen and every transition would be correctly reported unenforceable
  and rolled back.
- `PrivateNetwork=yes` — **incompatible** with the network probe's route
  enumeration, which is how the plan decides whether remote execution is even
  reachable.

`ProtectKernelTunables=yes` is compatible today and still left off, because the
discovery layer's own bounded readers are the intended control and enabling it
would silently change what a future probe can see.

**Planned, not implemented:** a polkit action set and a constrained helper, so
the supervisor can drop root entirely. The present design is the narrowest one
this repository supports today.

## cgroup v2 enforcement

**Implemented, integration tested against a real kernel.**

The correction that made this work is preserved: **do not create a cgroup and
assume the service entered it.** systemd places units under
`system.slice/<unit>`; writing into a Bunny OS-owned subtree limited an empty
cgroup while the service ran unconstrained elsewhere — and reported enforcement.

`SystemdResourceController` applies limits through
`systemctl set-property --runtime` and then reads the effective values back from
the cgroup **systemd reports**, not one this code assembled. Verification
happens *after* start, because a stopped unit has no cgroup; `--runtime` writes
a drop-in that applies before the service's first instruction, so the limit is
in force even though it cannot yet be read.

Measured on Fedora 44 / kernel 6.18.33.2 / systemd 259:

| Check | Result |
|---|---|
| unit cgroup path | `/sys/fs/cgroup/system.slice/bunny-bunny-capability-probe.service` |
| `memory.max` requested vs effective | 33554432 requested, 33554432 effective |
| `memory.current` | 17682432 — a real resident working set |
| `cgroup.procs` vs `MainPID` | `[1164]` vs `1164` — the process is *in* the limited cgroup |

A transition whose limits cannot be proven enforced **fails and rolls back**;
the service is not left running unconstrained, because the budget engine's
arithmetic assumed a ceiling that would not exist.

**Validated:** `MemoryMax`, `memory.current`, cgroup membership, unit-not-running,
controller availability, delegation detection. **Not run:** `MemoryHigh`,
`CPUWeight`, `CPUQuota`, `TasksMax` read-back; parent-slice restriction; kernel
clamping; unit restarting; read-only hierarchy on a real host.

## Unknown observations

**Implemented, unit tested, integration tested.**

```
absence of observation ≠ evidence of mismatch
```

`systemctl` cannot report which *implementation* of a service is running.
Comparing `None` against the desired implementation made every running service
look like it needed replacing, and a real host issued stop-then-start for each
of them on every cycle — the oscillation the hysteresis and cooldown machinery
exists to prevent, reintroduced underneath all of it. The vertical slice caught
it; regression tests cover it.

**Cost, recorded rather than hidden:** a service that should switch
implementations will not be switched by the systemd backend. It converges to
whatever is running and stays. Recording the implementation at start — a marker
under the unit's `RuntimeDirectory`, or a runtime drop-in — is the fix and is
**planned, not implemented**.

## WSL2 validation scope

**This is the most important scoping statement in the document.**

All real-kernel validation ran on:

| | |
|---|---|
| Kernel | 6.18.33.2-microsoft-standard-WSL2 |
| Distribution | Fedora 44 |
| systemd | 259 (259.8-1.fc44) |
| cgroup | v2, controllers `cpuset cpu io memory hugetlb pids rdma` |
| Python | 3.14.3 |
| `systemd-detect-virt` | `wsl` |
| Architecture | x86_64 |

**WSL2 is a virtualized Linux environment.** It is a real kernel with real
cgroups and real systemd, which is what makes the service-control and
enforcement results meaningful. It is **not physical hardware** and **not a
booted Bunny OS image**. No result in this document is a statement about
physical hardware, and none is a statement about Bunny OS at boot.

## Memory methodology and the 64 MiB classification

**Measured**, with every figure read from the cgroup the process was in.

Method: each configuration runs the supervisor inside
`systemd-run --scope --property=MemoryMax=<limit> --property=MemorySwapMax=0`,
so the limit is kernel-enforced and swap is off.

| Ceiling | Peak | Headroom | OOM | Reclaim |
|---|---|---|---|---|
| 64 MiB | 20.89 MiB | 43.11 MiB | 0 | 0 |
| 128 MiB | 17.53 MiB | 110.47 MiB | 0 | 0 |
| 256 MiB | 17.61 MiB | 238.39 MiB | 0 | 0 |
| 512 MiB | 17.46 MiB | 494.54 MiB | 0 | 0 |

Attribution by phase, at 64 MiB (`memory.current`):

| Phase | RSS | PSS | cgroup current |
|---|---|---|---|
| interpreter started | 10.75 | 6.73 | 4.71 |
| modules imported | 25.32 | 18.52 | **16.55** |
| supervisor prepared | 25.58 | 18.72 | 16.55 |
| cycle 1 | 25.72 | 18.86 | 19.01 |
| cycle 2 | 25.81 | 18.95 | 19.66 |
| idle after cycles | 25.70 | 18.84 | 19.59 |

Module import is the dominant cost — about 11.8 MiB of the peak. The supervisor
itself is roughly 3 MiB and each cycle adds about 0.6 MiB before flattening.

### The classification

```text
Control-plane process envelope under a 64 MiB cgroup ceiling:
PASS

Measured environment:
WSL2 virtualized Linux environment
systemd 259
cgroup v2
swap disabled

Measured peak:
20.89 MiB

Full Bunny OS boot within 64 MiB:
NOT_MEASURED

System-level 64 MiB gate:
NOT_RUN / BLOCKED
```

**The overall 64 MiB system gate is not Result A.** Result A applies to the
control-plane process envelope and nothing else. What was measured is a Python
interpreter running the supervisor inside a cgroup on a host that was already
booted. A booted system additionally carries a kernel, an init, a service
manager and the base userspace, none of which is in the figure above.

Kinds of memory, and which are measured:

| Kind | Status |
|---|---|
| Python process RSS | **Measured** (`smaps_rollup`) |
| PSS | **Measured** (`smaps_rollup`) |
| cgroup `memory.current` | **Measured** |
| cgroup `memory.peak` | **Measured** |
| Kernel memory | **Not measured** — outside the cgroup, and the WSL2 kernel is not a Bunny OS kernel |
| Init and base-userspace memory | **Not measured** — the host's are shared, not attributed |
| Full-image boot memory | **Not measured** — no image was booted |

The measured data is preserved exactly as taken. Its scope is narrower than the
gate; that narrows the claim, not the data.

## AArch64 status

**NOT_RUN / BLOCKED.**

| | |
|---|---|
| Required tool | `qemu-system-aarch64` |
| Present | No |
| Available instead | `qemu-aarch64-static` (user-mode emulation) |

**Why user-mode emulation is insufficient.** `qemu-aarch64-static` translates
userspace instructions and forwards system calls to the *host* x86_64 kernel. It
provides no AArch64 kernel, so there is no AArch64 cgroup hierarchy, no AArch64
systemd as PID 1, and no boot. Every result this phase depends on —
service control through systemd, `memory.max` enforcement read back from a
kernel, cgroup membership of a real `MainPID` — would be measuring the x86_64
host kernel through an ARM-shaped userspace. That is not architecture
validation; it is the same measurement with extra steps.

What remains architecture-neutral and *is* covered: the whole capability and
applicator unit suite, which is pure Python over simulated inventories and
includes `raspberry-pi-class` and `embedded-64mb` AArch64 simulations. Those
exercise detection, scoring, budgeting, planning and reconciliation logic on
AArch64-shaped inputs. They say nothing about kernel or systemd behaviour.

**Release impact.** The integrated runtime is **not operationally qualified on
AArch64**. This does not invalidate the x86_64 local repeatability measurement,
which is an x86_64 claim. It does block any statement that the control plane has
been qualified across the intended architecture range.

## Reproducibility candidate process

The repository's model, followed exactly:

```
implementation commit                     ← build-affecting source is final here
      ↓
two clean local builds, compared          ← same-host determinism only
      ↓
qualification-target.json names the       ← parentCommit = implementation commit
implementation commit as parentCommit
      ↓
Commit C = the commit containing that file
```

`qualification-target.json` cannot name the commit that contains it — writing
that hash in would change it. It names its parent, and the target is the child.
`scripts/supply-chain/assert-target-commit.py` checks that relationship, so
"Commit C" is a fact about a commit rather than a convention to remember.

**Local repeatability is not reproducibility.** Two builds on one host share a
kernel, a container store, a clock and an operator; a defect in any of them
reproduces in both. The comparison records its own claim as
`same-host-repeatability` for that reason.

## Operator enablement

The supervisor ships observing. To let it act:

```bash
# 1. See what it would do. Changes nothing.
bunny-os capability reconcile
bunny-os capability apply            # dry run against this machine

# 2. Read the explanation for anything surprising.
bunny-os capability transitions --explain <transition-id>

# 3. Enable apply.
sudo sed -i 's/"mode": "observe"/"mode": "apply"/' \
    /etc/bunny-os/capability/supervisor.json
sudo systemctl restart bunny-capability-supervisor

# 4. Confirm the mode changed, and watch.
systemctl status bunny-capability-supervisor
sudo tail -f /var/log/bunny-os/capability-audit.jsonl
```

To go back, set `"mode": "observe"` and restart. Nothing the applicator did is
undone by that — it stops making new changes.

## Developer dry-run workflow

```bash
# Everything below is safe in a checkout. None of it can reach a real service.
python -m unittest discover -s tests/capability -t .
bunny-os capability apply --simulate laptop        # simulated inventory + model
bunny-os capability apply                          # this machine, observed, not modified
python build/scripts/build-input-closure.py --range main..HEAD
```

`--host` is the only flag that reaches a real service manager. It additionally
requires systemd to be present and is refused alongside `--simulate` or
`--inventory`: a rehearsal against synthetic hardware must not be able to act on
real services.

## Local completion gate results

Five areas were required before a hosted dispatch could be considered. All ran
against a real kernel; none is a hosted or physical-hardware result.

### Installed-path vertical slice — **PASS**

Run inside the built artifact under `systemd-nspawn`, importing from
`/usr/lib/bunny-os/python/capability` (asserted, not assumed). 18 steps.

| Check | Observed |
|---|---|
| code provenance | `/usr/lib/bunny-os/python/capability` |
| unit cgroup | `/sys/fs/cgroup/system.slice/bunny-bunny-capability-probe.service` |
| `memory.max` requested / effective | 33554432 / 33554432 |
| `memory.current` | 17518592 |
| `cgroup.procs` / `MainPID` | `[432]` / `432` |
| reservation | committed then released |
| reconciliation at convergence | no transition requested |

### Runtime adaptation under real pressure — **PASS**

A real allocator filling a 512 MiB cgroup to 96%, with the monitor reading
`memory.current` and `memory.max` from the kernel.

- a transient spike raised **nothing** (debounce)
- sustained pressure raised **one** `memory_pressure_entered`
- the pressured plan granted 23068672 bytes against 73400320 before it
- **no optional service ran while an essential one was refused** — the refused
  service was the lowest-priority essential, and the protected reserve was
  never drawn on
- a single good reading raised **nothing**; sustained recovery raised
  `memory_pressure_recovered`
- repeated replanning reached a fixed point
- the whole cycle raised **2 events**

**This found the cooldown defect.** The recovery event was being destroyed
rather than delayed. See `docs/CAPABILITY_APPLICATOR.md`.

### Failure injection — **PASS** (partial coverage)

Covered: systemd absent, startup timeout, health failure after start, read-only
state directory, full disk during write and during audit, corrupt ledger, stale
lock metadata, approval expiry, plan supersession. Each asserts no leaked
reservation, no unconstrained process, and that the explanation names the first
failed invariant.

**Not covered:** externally-managed transition on a real host, network loss
before a remote dispatch (no provider exists to lose), circuit-breaker opening
against a real repeatedly-failing unit.

### Security boundaries — **PASS**

Unit-name traversal, cgroup path traversal, manifest unit injection, plan
fingerprint mismatch, replay, supersession, expired approval, approval for a
different plan, secret redaction, state permissions, symlink redirection of
state and approval files, atomic replacement confined to the state directory,
observe-only cannot mutate, dry-run cannot reach the real backend, oversized and
deeply nested structured input.

**This found the `unit_name_for` input-validation gap.**

### Cold pull of retained inputs — **PASS locally**

All three published inputs resolve **anonymously by digest** from an isolated
store — fresh `HOME`, empty auth file, no host `registries.conf`, no operator
keyring, `GITHUB_TOKEN` removed from the environment, TLS verification on.

| Input | Digest agreement |
|---|---|
| base | verified |
| builder | verified |
| snapshot | verified |

**This does not retire the recorded cold-pull failure.** That failure was on a
hosted runner, and only a hosted run can retire it. What this establishes is
that the inputs are publicly fetchable by digest without this repository's
credentials, from a machine that is not the publisher's CI.

## Known limitations

- **No Bunny OS image has been booted.** All real-kernel validation ran on a
  Fedora 44 WSL2 host. **Blocked** on a boot harness for the constrained case.
- **The 64 MiB system gate is NOT_RUN.** See above.
- **AArch64 is NOT_RUN.** `qemu-system-aarch64` is absent.
- **Independent reproducibility is not established.** Two local builds agree;
  they are not independent builders.
- **Implementation changes are not detected by the systemd backend.** See
  "Unknown observations".
- **Suspend, resume, reload and ungraceful kill are not integration tested**
  against real systemd. Start, stop, limit and health-check are.
- **`MemoryHigh`, `CPUWeight`, `CPUQuota` and `TasksMax` are applied but their
  read-back is not integration tested.** Only `MemoryMax` is.
- **The supervisor runs as root.** A polkit-scoped or helper-mediated design is
  planned and not implemented.
- **No remote provider exists.** The state machine is complete; nothing
  dispatches.
- **The approval digest is not authentication.** It defends against accidental
  edits, not against an attacker who can write the file.
