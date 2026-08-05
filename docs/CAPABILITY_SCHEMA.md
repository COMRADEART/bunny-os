# The capability inventory schema

Schema: `schemas/capability-inventory.schema.json` (version 1).
Model: `capability/model.py`. Producer: `capability/discovery/`.

`bunny-os capability inspect --json` emits a document conforming to it.

## The three availability states

Every measurable fact is an **observation**:

```json
{ "state": "measured", "value": 16777216000, "source": "/proc/meminfo MemTotal" }
{ "state": "absent",   "source": "/sys/class/power_supply", "detail": "no battery" }
{ "state": "unknown",  "source": "cgroup", "detail": "cgroup2 memory.max unparseable" }
```

| State | The probe | The hardware | What a consumer may conclude |
|---|---|---|---|
| `measured` | ran | reported this | the value |
| `absent` | ran | is not there | there is none |
| `unknown` | did not run, timed out, or returned nonsense | unknown | nothing |

`value` is present **only** under `measured`. The model enforces it:
constructing an `Observation` with a value in any other state raises. That one
rule is what stops a plausible-looking default from being read later as a
measurement.

`absent` and `unknown` are not interchangeable. A machine with no battery has an
`absent` battery, which is knowledge a scheduler can use. A machine whose
`power_supply` class could not be read has an `unknown` battery, and the correct
response is caution, not "assume mains".

### Reading an observation

```python
memory.physical_bytes.get(0)      # explicit: treat unmeasured as zero
memory.physical_bytes.get(None)   # explicit: propagate the unknown
memory.physical_bytes.get()       # TypeError - there is no implicit default
```

The mandatory argument is deliberate. It puts the decision about missing data
at the call site, where a reviewer can see it, rather than in a default nobody
chose.

## Document structure

```json
{
  "schemaVersion": 1,
  "detectedAt": "2026-08-03T20:11:19Z",
  "detection": { "budgetMs": 2000, "durationMs": 74, "probes": [...] },
  "system":  { "architecture": {...}, "virtualized": {...}, "containerized": {...} },
  "cpu":     { "logicalThreads": {...}, "quotaCores": {...}, ... },
  "memory":  { "physicalBytes": {...}, "cgroupLimitBytes": {...}, ... },
  "gpu":     [ { "index": 0, "driverReady": false, "runtimes": {...}, ... } ],
  "accelerators": [...],
  "storage": {...}, "network": {...}, "power": {...}, "thermal": {...},
  "display": {...}, "audio": {...},
  "constraints": {...},
  "privacy": { "identifiersCollected": false, "transmitted": false }
}
```

### `detection`

One shared wall-clock budget covers the whole pass, and each probe's outcome is
recorded:

```json
{ "name": "gpu", "state": "skipped", "durationMs": 0,
  "detail": "discovery deadline exhausted before this probe started" }
```

States are `ok`, `failed` and `skipped`. A probe that fails does not fail the
pass — it contributes `unknown` observations and a recorded reason. An inventory
with holes is useful, because every downstream stage is built to be conservative
in exactly those holes. An exception at boot is not.

Per-probe timeouts would not bound boot: twelve probes at three seconds each is
a thirty-six second stall on a machine where every device is wedged. Probes run
cheapest-and-most-decision-critical first, so a truncated pass has still
answered architecture, memory ceiling and CPU quota.

### `cpu`

`quotaCores` is the fractional CPU a cgroup permits, from `cpu.max` (v2) or
`cfs_quota_us`/`cfs_period_us` (v1). `CpuFacts.effective_cores()` returns the
smaller of it and the thread count — schedulable cores, not physical ones. A
systemd unit with `CPUAffinity=`, or a container pinned to two CPUs on a
96-thread host, has two.

`frequencyThrottled` compares `scaling_max_freq` against `cpuinfo_max_freq`, not
the current frequency against the maximum. A CPU at 800 MHz because nothing is
running is idle, not throttled; a probe confusing the two would report constant
thermal distress on a healthy laptop. A reduced *ceiling* is a live constraint.

`instructionSets` records only the flags a scoring or selection decision reads.
Recording all 200-odd x86 flags would make the inventory a fingerprint.

### `memory`

`cgroupLimitBytes` is the single most important field on a constrained
deployment. `MemoryFacts.usable_bytes()` is the smaller of it and
`physicalBytes`.

cgroup v1 spells "no limit" as a number near `2**63`. That sentinel is detected
and reported `absent`, not read as eight exabytes of RAM.

`pressureSomeAvg10` is PSI, and it is the honest signal for "is this machine in
trouble right now". Free-memory headroom is not: a machine can have gigabytes
free and still be stalling on reclaim, and can have almost nothing free and be
perfectly healthy because the page cache is doing its job.

`reservedBytes` sums `reserved` ranges in `/proc/iomem`. An unprivileged reader
gets all-zero ranges; that zeroing is detected and reported `unknown` rather
than as "nothing is reserved", because on small ARM boards reserved carve-outs
are a large share of installed RAM.

### `gpu`

```json
{
  "index": 0,
  "vendor": { "state": "measured", "value": "nvidia" },
  "kind":   { "state": "measured", "value": "discrete" },
  "driver": { "state": "absent", "detail": "no driver is bound to this device" },
  "renderNode": { "state": "absent", "detail": "no render node was created for this card" },
  "driverReady": false,
  "vramTotalBytes": { "state": "unknown", "detail": "no trustworthy VRAM source" },
  "runtimes": { "cuda": {...}, "rocm": {...}, "vulkan": {...}, "opencl": {...} }
}
```

Three separate questions, never collapsed:

1. **presence** — the device exists (sysfs enumeration)
2. **driver** — a driver is bound *and* a render node exists (`driverReady`)
3. **runtime** — CUDA / ROCm / Vulkan / OpenCL can actually be used

`Inventory.usable_gpus` filters on (2). `driverReady: false` on a detected
device is the difference between a CPU-only plan and a boot failure that looks
like a hardware fault.

VRAM comes from `amdgpu`'s sysfs counters or `nvidia-smi`, and from nothing else.
A shared-memory device (i915, xe, v3d, panfrost, ...) reports `absent`, which
means *known to have none* — a fact about the design, not a failed probe.

### `storage`

`rootAvailableBytes` uses `f_bavail`, not `f_bfree`: reserved blocks are not
available to Bunny OS, and counting them turns "10 GB free" into ENOSPC.

`storageClass` resolves the backing block device through `/proc/self/mounts`,
handling `nvme0n1p1 -> nvme0n1` and `mmcblk0p1 -> mmcblk0` as well as `sda1 ->
sda`. Overlayfs, tmpfs, NFS and device-mapper targets report `unknown` with the
reason, because the honest answer is "not determinable from here", not
"unknown-and-probably-a-disk".

### `network`

`defaultRoute` is read from `/proc/net/route` and `/proc/net/ipv6_route`. IPv6 is
checked separately because an IPv6-only machine is online and would otherwise be
reported offline.

`NetworkFacts.offline` and `.online` are **not** each other's negation:

```python
offline = default_route.is_known and default_route.get(False) is not True
online  = default_route.get(False) is True
```

Unknown connectivity is neither. Treating an unrun probe as "no network" would
disable remote execution on a healthy machine; treating it as "network present"
would send a task into a void.

`metered` requires NetworkManager, queried through `nmcli` with a fixed
read-only argument list. Without it the answer is `unknown`, and policy treats
unknown as possibly metered.

`bandwidthBitsPerSecond` is **always** `unknown`, with the reason stated. An
honest measurement means moving real traffic, and this subsystem will not spend
a user's metered allowance measuring itself.

`endpointReachable` and `latencyMs` are populated only when a caller explicitly
requested reachability probing *and* supplied endpoints. Nothing is contacted
during a default pass.

### `display`

`connectedOutputs` counts `/sys/class/drm/*/status == "connected"`.
`DisplayFacts.has_display` requires a positive count, so an unmeasured display
does not claim one — conservative in the safe direction, since a renderer is not
started on a display nobody observed.

Keyboard detection tests for the alphabetic block (Q, P and A), not merely for
key events. A power button and a lid switch both report key events, and a
headless server would otherwise report a keyboard.

Every input capability bit tested is below 32. The kernel prints capability
bitmasks as `unsigned long` groups whose width is 32 or 64 depending on the
kernel, and the group count does not reveal which. Every bit tested lives in the
*last* group either way, so the parse cannot silently misread.

### `constraints`

Derived booleans naming what makes this machine smaller than its hardware:

```json
{ "memoryLimited": true, "cpuQuotaLimited": true, "containerized": true,
  "virtualized": false, "readOnlyRoot": false, "headless": true,
  "offline": false, "onBattery": false, "thermallyThrottled": false,
  "meteredNetwork": false }
```

Each is `false` unless positively observed, with two documented exceptions:

- `headless` is `true` when no display was *observed*, including when the probe
  could not run. Conservative in the direction that refuses to start a renderer.
- `offline` is `false` when connectivity is unknown, because unknown is not
  offline. A consumer needing certainty reads `network.defaultRoute` directly.

### `privacy`

```json
{ "identifiersCollected": false, "transmitted": false }
```

Both are `const: false` in the schema, so a document claiming otherwise fails
validation. No serial number, MAC address, hostname or machine UUID is
collected. `system.bootIdPresent` is a **boolean** — that a boot id exists tells
a caller this is a booted Linux system; its value would be a machine identifier.

`tests/capability/test_model.py::test_no_identifying_information_is_collected`
asserts this over every simulated machine.

## Round-tripping

`inventory_from_json()` rebuilds an `Inventory` from its JSON form, which is what
lets `bunny-os capability plan --inventory captured.json` reproduce a plan on a
machine that is not the one it came from. The round-trip is byte-stable and is
asserted for every simulated machine.

An unsupported `schemaVersion` raises rather than being best-effort parsed.

## Simulated inventories

`capability/simulate.py` builds inventories as real `Inventory` values rather
than JSON fixtures, so a change to the model breaks them at import time instead
of producing a subtly wrong document that still parses.

Any document produced from one carries `simulationNotice`, and every CLI
rendering of one carries a `SIMULATED HARDWARE` banner. **A plan produced from a
simulation is a statement about the policy engine and never about hardware.**
