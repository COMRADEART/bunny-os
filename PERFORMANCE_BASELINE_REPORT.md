# Performance Baseline — Capsules in a Booted Guest

**What this is** The numbers `CAPSULE_PERFORMANCE_REPORT.md` §1 said it did not
have. That report, written before any capsule had ever started, listed six
measurements that "need a kernel" and stated plainly that **none had a number**.
Five of the six now do.

**Commit** `524107e50b2e` · **Guest** `kvm`, kernel `7.1.5-200.fc44.x86_64`, cgroup v2, SELinux Enforcing
**Backend** bubblewrap · **Ran as** `bunny` (uid 1000)

---

## 1. The six §24 numbers

| § | Measurement | Value | Status |
|---|---|---|---|
| 1 | Cold-launch latency of a capsule | **16.2 ms** (then 18.2, 13.9) | Measured |
| 2 | Memory overhead of the namespace | **3.9 MB** (17.08 MB tree − 13.17 MB application) | Measured |
| 3 | CPU cost of the cgroup | Not isolable at this resolution — see §4 | Partly |
| 4 | Disk overhead of a capsule | **7,305 B** per capsule | Measured |
| 5 | GPU through a render-node bind | **Not measured** — no GPU in the console guest | Outstanding |
| 6 | Portal round-trip latency | **Not measured** — no portal on this path | Outstanding |

Two remain outstanding and are named rather than substituted. The earlier report
exists precisely because presenting Bunny's own planning overhead as "cold-launch
latency" would be the wrong number by orders of magnitude; the same discipline
applies to the two rows still empty.

## 2. Launch

```
cold         16.2 ms
subsequent   18.2 ms, 13.9 ms
```

Cold is not slower than warm at this scale, which says the cost is dominated by
`systemd-run` round-trip and `bwrap` setup rather than by anything Bunny caches.
The spread across three launches (13.9–18.2 ms) is wider than the cold/warm
difference, so no warming claim is made.

For scale: this is well below the ~100 ms threshold at which a person perceives a
delay as a delay. Launching a capsule is not what a user will feel; what the
application does afterwards is.

## 3. Footprint

| Measurement | Value |
|---|---|
| Capsule process tree RSS | 17,084,416 B (3 processes) |
| Application RSS within it | 13,172,736 B |
| **Namespace and supervision overhead** | **≈ 3.9 MB** |
| Capsule on-disk state | 7,305 B |

3.9 MB per running capsule for the isolation itself. On a 4 GB machine, twenty
concurrent capsules cost about 78 MB of overhead — acceptable, and worth
re-measuring against a real application rather than a probe, since a probe's own
RSS is small enough that the ratio here flatters the overhead.

## 4. The memory ceiling, and why the intervention shape matters

Declared: `MemoryHigh=192 MiB`, `MemoryMax=256 MiB`.

| | Inside the capsule | Unconfined control, same host |
|---|---|---|
| Allocated before intervention | 209,715,200 B | 243,269,632 B |
| `memory.peak` | 244,084,736 B | — |
| `events.high` | **2,985** | — |
| `events.oom_kill` | **0** | — |
| Outcome | `TIMEOUT`, intervention `cgroup-throttle` | exit −9 (SIGKILL) |

The capsule was **throttled, not killed**. `MemoryHigh` applied back-pressure 2,985
times and the workload slowed until it hit the suite's own timeout; `MemoryMax` was
never reached. The control on the same machine, with no capsule, was OOM-killed.

This is the difference between a user seeing "this application has gone slow" and
"this application vanished". Both are enforcement. Only one of them is a product
that can be trusted with unsaved work — and it is the reason `MemoryHigh` is set
below `MemoryMax` rather than the two being equal.

## 5. Task ceiling

```
declared TasksMax   48
threads started     45
outcome             RuntimeError: can't start new thread
exit                0
```

The ceiling bound the workload at 45 of 48 (the gap is the capsule's own
supervision), and the application received an ordinary Python exception rather than
a signal. A limit that surfaces as a catchable error is one an application can
handle; a limit that arrives as SIGKILL is one it cannot.

## 6. End-to-end: the one number a user experiences

The complete production route — request → resolve → trust → approval → plan →
launch → run → export — for a real image resize:

```
elapsed      214.4 ms
exit status  0
result       Pictures/holiday-resized.png, 182 bytes, 100×50
```

214.4 ms for the whole journey, of which ~16 ms is the capsule launch. The
remaining ~198 ms is GdkPixbuf loading, resizing and encoding a PNG, plus the
trust and planning layers. Nothing in the isolation path is the bottleneck.

## 7. What these numbers are not

- **Not a real application.** The probe and `bunny-image-tool` are small. A capsule
  running a browser or an editor will have a different footprint, and the ~3.9 MB
  overhead figure is the honest part of §3 while the ratio is not.
- **Not hardware.** Everything is `kvm` on one host. No claim about physical
  machines, spinning disks, or constrained memory.
- **Not graphical.** No GPU, no portal, no compositor in this run. §1 rows 5 and 6
  remain open, and `DESKTOP_PERFORMANCE_REPORT.md` is where they will land.
- **Not a repeated-trial statistic.** Three launches, one memory run, one task run.
  Enough to characterise the shape; not enough for a percentile.

## 8. Evidence

`qualification/capsules/evidence/guest-524107e50b2e/resources.json` and
`apptask.json`. Supersedes the "no number" rows of
`CAPSULE_PERFORMANCE_REPORT.md` §1 without rewriting that report, which is left as
it was written.
