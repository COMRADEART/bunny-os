# Performance — App Capsules and the Trust layer

**Date** 2026-08-10 · **Commits** `fc1e58a`, `adce2c5`

§24 asks that isolation not make the desktop feel slow, and that the answer be
measured rather than assumed. This report contains real measurements of what was
built and is explicit about the much larger number it does **not** contain.

---

## 1. What is measured here, and what is not

**Measured:** Bunny's own overhead — resolving a permission, building an
isolation plan, rendering an argument vector, provisioning a capsule, and running
a whole task end to end with a recording tool.

**Not measured:** everything that needs a kernel. Cold-launch latency of a real
application, memory overhead of a `bwrap` namespace, CPU cost of the cgroup, disk
overhead of a Flatpak runtime, GPU compatibility through a render-node bind, and
portal round-trip latency. §24 names all six; **none has a number** because no
capsule has been started.

Presenting Bunny's overhead as "cold-launch latency" would be the exact
substitution this report exists to avoid. The two differ by orders of magnitude
and the missing one is the one a person feels.

### Host

| | |
|---|---|
| Platform | Windows 11 (10.0.26200), NTFS |
| Python | 3.14.6 |
| Method | `time.perf_counter`, 5 warm-up iterations discarded, n as stated |

**This is the wrong host and the numbers are the wrong numbers.** Bunny OS runs
on Linux on ext4; `os.fsync` on NTFS through Python behaves differently from
ext4, and every figure below that involves a write is dominated by fsync. They
are recorded because a measured wrong-host number with its host named is more
useful than an estimate, and because the *shape* — which operation is expensive
and how it scales — carries over.

---

## 2. Measurements

| Operation | Median | p95 | Max | n |
|---|---:|---:|---:|---:|
| Open an existing capsule (read manifest + state) | 0.236 ms | 0.305 ms | 0.407 ms | 60 |
| Build an isolation plan (1 grant) | 0.392 ms | 0.451 ms | 1.006 ms | 60 |
| Render the bwrap argument vector | 0.005 ms | 0.006 ms | 0.021 ms | 60 |
| Load the trust store | 0.078 ms | 0.255 ms | 0.301 ms | 60 |
| **Permission check against a standing grant** | **4.040 ms** | 5.101 ms | 8.253 ms | 60 |
| Provision a new capsule tree (7 directories) | 2.649 ms | 2.883 ms | 2.928 ms | 30 |
| Whole task, recording tool, 1 file | 42.091 ms | 44.234 ms | 125.230 ms | 25 |

### Plan build scales with the number of standing grants

| Grants | Median | p95 | Max |
|---:|---:|---:|---:|
| 1 | 0.405 ms | 1.014 ms | 2.115 ms |
| 25 | 7.160 ms | 8.510 ms | 10.730 ms |
| 100 | 31.762 ms | 34.159 ms | 35.052 ms |

Linear at roughly **0.3 ms per grant**, paid on every launch.

---

## 3. The two findings worth acting on

### 3.1 A permission check costs 4 ms even when the answer is already stored

This is the surprising number. Resolving a standing grant is a dictionary lookup
and a digest comparison — microseconds. The 4 ms is the **audit append**: one
`open(O_NOFOLLOW)`, one write, one `fsync`, one close, per decision.

That is a deliberate durability choice — §21 wants an audit that survives a power
cut — and 4 ms is invisible for one file. It is not invisible for a task over a
folder of two hundred images, where it becomes 800 ms of pure fsync.

**Not a defect today**, because no such flow exists: `capsule_bridge` asks once
per named input and a person names a handful. It becomes one the moment a batch
capability is added. Recorded now so that whoever adds one meets this paragraph
rather than the symptom.

*Option if it bites:* batch the audit for decisions inside one task and fsync once
at the task boundary. The durability property weakens from per-decision to
per-task, which is a real trade and should be a deliberate one.

### 3.2 Plan build is linear in grants, at 0.3 ms each

The cost is per-grant `os.path.realpath` plus `os.path.exists` plus a type check —
deliberate, because the grant holds a path that may have been replaced by a
symlink, a directory or a FIFO since it was given, and re-resolving at plan time
is what catches that. It is one of the four refusals in the security review.

At a realistic 5–20 grants per application this is 2–6 ms and irrelevant. At 100
it is 32 ms, which is a third of a frame budget's worth of launch latency for a
person who has said "always allow" to a lot of files.

**Not optimised.** Any cache would have to be invalidated by a filesystem change
that Bunny does not watch, and a stale cache here means binding a path that is no
longer what was granted. The correct fix, if this ever matters, is to bound the
number of standing file grants and offer a folder grant instead — which is a
product decision, not a performance one.

---

## 4. Design choices that were made for performance

**A persistent capsule, not a container per task.** §24 asks for this directly.
Opening costs 0.236 ms because it is two JSON reads; the alternative — building an
image or a container per launch — is seconds. This is the single largest
performance decision in the phase and it is structural rather than tuned.

**The plan is a pure value.** Building one touches the filesystem only to resolve
and stat granted paths. Nothing mounts, nothing spawns, nothing waits on D-Bus.
That is why the number above is sub-millisecond and why it can be measured at all.

**Portal availability is probed by socket existence, not by a D-Bus call.** A
round trip in the launch path is latency on every start. A socket that exists and
does not answer is caught later by the call failing, which denies.

**The store is written whole.** A few hundred grants is a small document and
whole-file replacement removes the partial-update path in which a revocation lands
and the grant it replaced does not. At 100 grants the write is still well under a
millisecond of serialisation; the cost is fsync, which a partial update would pay
too.

---

## 5. The measurements that are missing, and how to get them

Each needs a booted image. The VM procedure has the steps; this is what each would
settle.

| Metric | §24 asks for | How |
|---|---|---|
| Cold launch, first ever | launch latency | `time` from `runtime.launch` to the application's first frame, `SubprocessExecutor`, empty capsule |
| Warm launch, second run | launch latency | Same, capsule already provisioned. The gap is what persistence buys |
| Memory overhead | memory overhead | RSS of the `bwrap` process tree minus the same application unconfined |
| CPU overhead | CPU overhead | `systemd-cgtop` on the scope during a fixed workload |
| Disk overhead | disk overhead | Capsule tree size after first run; Flatpak runtime size if shared |
| GPU compatibility | GPU compatibility | Whether a render-node bind lets the application use hardware acceleration at all, and on `llvmpipe` versus real hardware |
| Portal latency | portal latency | Time from a portal request to a decision, with the dialog drawn |

Until then this report contains no claim about how Bunny OS feels to use, because
no measurement here is about that.

---

## 6. Regressions

None. No existing code path was modified for performance or otherwise, and the
full suite runs in 276 s before and after (4,608 → 4,856 tests; the 248 new tests
add roughly 6 s).
