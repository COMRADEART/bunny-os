# Capability scoring methodology

Implementation: `capability/scores.py`. Command: `bunny-os capability scores`.

## The contract

Every dimension is:

- **bounded** to `0.0..100.0` inclusive, or `None` when nothing relevant was
  measured;
- **deterministic** — a pure function of the inventory. Same inventory, same
  numbers, on any host, in any order;
- **accompanied by its raw measurements**, in `inputs`, so any number can be
  re-derived by hand;
- **accompanied by a confidence**, which is *not* a score: `measured` (every
  input was measured), `partial` (some were), `unknown` (none were, and the
  score is `None`);
- **independently testable**.

A score outside `0..100`, or a `None` score with a confidence other than
`unknown`, raises at construction.

## There is no overall score

A machine is not "high" or "low". It is a vector of thirteen numbers, and no
arithmetic path exists by which one compensates for another.

The concrete failure a single score produces: a workstation with two RTX 6000s
and 4 GB of usable RAM inside a restrictive cgroup scores "very high" on any
weighted average, and the policy engine starts a service that is then
OOM-killed. Here the same machine scores ~97 on `gpu_compute` and ~55 on
`memory_available`, and the memory dimension is the one that gates the service.

`ScoreSet.to_json()` carries the rule in the document itself:

> There is no overall score. Dimensions are independent by design: a high score
> in one may not be used to satisfy a requirement in another.

## `None` is not zero

A dimension with no evidence scores `None`. Zero means *measured, and there is
none* — a machine with no GPU scores `gpu_compute: 0.0` with `measured`
confidence, which is knowledge. A machine whose DRM could not be read scores
`None` with `unknown` confidence, which is not.

Consumers must state their treatment of missing data:

```python
score.at_least(40.0, when_unknown=False)   # requirement check: unmeasured != satisfied
score.at_least(40.0, when_unknown=True)    # safety check: don't fire on missing data
score.at_least(40.0)                       # TypeError
```

## The curves

Both size curves are **logarithmic**, because every resource scored here is
perceived logarithmically. The step from 512 MB to 1 GB changes what Bunny OS
can run; the step from 64 GB to 64.5 GB changes nothing. A linear scale would
put every constrained device — the exact devices this subsystem exists to
serve — into an indistinguishable smear near zero.

```text
score = 100 x log2(value / floor) / log2(ceiling / floor), clamped to 0..100
```

| Dimension | Floor (scores 0) | Ceiling (scores 100) |
|---|---|---|
| `memory_available` | 64 MiB | 128 GiB |
| `gpu_memory` | 512 MiB | 96 GiB |
| `storage_capacity` | 1 GiB | 2 TiB |
| `cpu_compute` | 1 effective core | 64 effective cores |

The `memory_available` floor is 64 MiB because that is §5's explicit
architectural constraint: the smallest board Bunny OS must boot on scores 0, and
0 is a real, correct score for it rather than an error.

Worked examples on the memory curve:

| Usable memory | Score |
|---|---|
| 64 MiB | 0.0 |
| 128 MiB | 9.1 |
| 512 MiB | 27.3 |
| 1 GiB | 36.4 |
| 4 GiB | 54.5 |
| 16 GiB | 72.7 |
| 64 GiB | 90.9 |
| 128 GiB and above | 100.0 |

## The thirteen dimensions

### `cpu_compute`

*How much CPU work can this machine do, given its schedulable cores?*

`effective_cores` on the log curve, plus 8 for wide-vector instructions
(`avx2`, `avx512f`, `sve`, `sve2`, `asimd`, `amx_int8`).

`effective_cores`, not the physical count: a container holding 0.5 CPU on a
96-thread host scores as half a core, because that is what it can use. A cgroup
quota adds a note naming itself as the binding limit.

This is **capacity**, and it does not move with load. Headroom is
`background_capacity`.

### `memory_available`

*How much memory may Bunny OS actually use, after every imposed ceiling?*

`usable_bytes` — the smaller of physical memory and any cgroup limit — on the log
curve. Notes name a cgroup ceiling when one is in force and PSI pressure above
10%.

### `gpu_compute`

*Is there a GPU that work can genuinely be submitted to?*

Per device, the best of:

| Condition | Score |
|---|---|
| no bound driver or no render node | 0 |
| discrete + CUDA or ROCm verified | 95 |
| discrete + Vulkan verified | 70 |
| discrete, driver only | 45 |
| integrated + Vulkan | 40 |
| integrated | 25 |
| virtual adapter | 10 |

Plus at most 5 for additional usable devices: more accelerators raise throughput
but not the ceiling of what a single job can do.

A machine with devices but none usable scores `0.0` with `measured` confidence
and a note naming which of driver or render node is missing. A machine whose GPU
probe did not complete scores `None`.

### `gpu_memory`

*How much dedicated video memory is there?*

The **largest single device** on the log curve, not the sum: a model must fit in
one of them.

Shared-memory devices score `0.0` with `measured` confidence and a note. They are
deliberately **not** scored against system RAM — doing so would let an
integrated GPU borrow the memory dimension's score and defeat the separation
this module exists to enforce.

Usable devices whose VRAM has no trustworthy source score `None`.

### `storage_capacity` / `storage_performance`

Free space on the log curve; a read-only root adds a note that capacity is not
writable capacity.

Performance starts at 85 (solid-state) or 30 (rotational), reduced
proportionally by I/O PSI: a filesystem stalling half the time loses half its
score. An undeterminable device class scores `None` — speed is not guessed.

### `network_quality`

Offline (a *measured* absence of a default route) scores `0.0` with `measured`
confidence, so anything requiring the network is ineligible rather than merely
slow. An unreadable routing table scores `None`.

Online: 85 wired, 60 wireless, 50 unclassified; minus 25 if metered, minus 20 if
a route exists but no configured endpoint answered (a captive portal).

### `local_ai`

*Can model inference run on this machine at all?*

Two independent paths, larger wins — weights in VRAM, or weights in RAM:

```text
accelerated = min(gpu_compute, gpu_memory)      when gpu_compute >= 60 and VRAM > 0
cpu_path    = min(memory_available, cpu_compute + 20)
```

Underneath both is a **hard feasibility floor**: below `HOST_RUNTIME_FLOOR_BYTES`
(1 GiB) of usable system memory the score collapses to `10 x usable / 1 GiB`,
whatever the accelerators say.

That floor is the correction that makes this dimension honest, and it was added
because the first implementation got it wrong. Bounding only the CPU path by
memory let the *GPU* path score 96 on the constrained-container machine — eight
80 GB accelerators inside a 512 MiB cgroup — which is the exact
"powerful GPU hides a severe memory shortage" failure this module exists to
prevent, reproduced inside the function meant to prevent it. A CUDA or ROCm
context, the loader and the process all live in system memory; the accelerator
only changes where the *weights* live.

`tests/capability/test_scores.py::test_the_host_runtime_floor_collapses_local_ai_whatever_the_gpu`
is the regression.

### `graphics`

No connected display scores `0.0` with `measured` confidence: local rendering has
nowhere to go, whatever the GPU can do. With a display, `25 + gpu_compute x 0.75`
— floored at 25 because software rendering is always possible.

### `audio`

65 for a playback endpoint, 35 for capture. Absent endpoints add notes naming
the consequence: no playback means text output is the fallback; no capture means
speech recognition cannot run locally.

### `interactive_desktop`

Headless scores 0. A display with no input device scores 5 — nobody can drive
that session. Otherwise the **minimum** of graphics, memory and CPU+15: a desktop
is only as good as its worst input.

### `background_capacity`

`cpu_compute` reduced by measured saturation (`load / effective_cores`), halved
when cooling is engaged, halved again on battery, and bounded by
`memory_available` — background work that cannot allocate is not headroom.

This is the dimension that shrinks under pressure while `cpu_compute` stays put.
Capacity is a property of the hardware; headroom is a property of the moment.

### `energy_thermal_headroom`

100 on mains. On battery: `30 + 40 x percent/100` above 20% charge, and
`10 x percent/20` below it — steep, because below 20% the machine is minutes
from the user losing work. An active power-saving profile caps at 45: the
platform has already chosen economy and Bunny OS does not compete with it.
Engaged cooling reduces proportionally.

## Adding a dimension

Adding one is a schema change; **collapsing two is a design change** that has to
be argued rather than done. `DIMENSIONS` in `capability/scores.py` is the public
contract, and `tests/capability/test_scores.py` asserts every machine produces
every dimension and that each is bounded or explicitly unmeasured.
