# Resource budget calculation

Implementation: `capability/budget.py`. Schema:
`schemas/resource-budget.schema.json`. Command: `bunny-os capability budget`.

## Two memory figures

```text
usable                = min(physical memory, cgroup ceiling)
protected reserve     = clamp(usable x fraction, floor, ceiling), and never > usable/2
allocatable           = usable - reserve              [- any user ceiling]
currently allocatable = min(allocatable - essential, available - reserve), floored at 0
```

**allocatable** is what Bunny OS may consume on an idle machine. It is the
planning number and it is stable — it does not move when a user opens a browser.

**currently allocatable** is what may be committed right now, from memory
actually free. It is the admission number, and a service is started against it.

Budgeting against only the first over-commits a loaded machine. Budgeting
against only the second makes the plan flap every time a tab opens. Both exist
because both questions get asked, by different callers.

`foregroundWorkloadBytes` is `usable - available`: everything already in use
that is not ours. Budgeting on top of it, rather than pretending it will be
released, is what stops an admission decision from evicting the user's work.

## The protected reserve

Allocatable by **nothing**, essential services included. The engine never
receives it as a number it could spend, so no code path exists by which an
optional service could consume it.

| Bound | Value | Why |
|---|---|---|
| fraction | 20% (`protectedReserveFraction` may raise it) | |
| floor | 24 MiB | 20% of 64 MiB is 13 MiB, which is not enough slack for the kernel to reclaim, fork, or run the OOM killer's own bookkeeping without stalling |
| ceiling | 2 GiB | 20% of 256 GB would strand tens of gigabytes to protect against a risk that stopped scaling long before |
| absolute | never more than `usable / 2` | reserving more than the machine has produces a negative allocatable budget, which is an arithmetic accident rather than a safety property |

## Essential services

`essentialServicesBytes` is the summed **minimum** of every essential service —
minimum, not recommended, because this figure decides whether the machine can
run Bunny OS at all and should describe the smallest honest configuration.

Each service contributes the minimum of its *cheapest local implementation*: a
service with a lean fallback does not oblige the machine to fund its best form.

It is taken off the top, before the discretionary pool exists, which is why
`essential_services` is not one of the weighted categories below. A category
that could be outbid by an optional service would not be essential.

`viable` is false when the essential floor exceeds allocatable memory. A
non-viable machine funds whatever control plane it can and refuses everything
optional, so that the component able to report the problem is the one that runs.

## Discretionary categories

The pool left after the reserve and the essential floor is split by weight:

| Category | Weight | Useful floor |
|---|---|---|
| `user_applications` | 0.30 | 64 MiB |
| `local_ai_inference` | 0.25 | 512 MiB |
| `optional_services` | 0.15 | 8 MiB |
| `companion_rendering` | 0.10 | 192 MiB |
| `speech_recognition` | 0.05 | 256 MiB |
| `agent_orchestration` | 0.05 | 32 MiB |
| `caching` | 0.04 | 8 MiB |
| `text_to_speech` | 0.03 | 48 MiB |
| `logs` | 0.02 | 2 MiB |
| `temporary_files` | 0.01 | 2 MiB |

**A category whose share falls below its useful floor is reported unfunded, with
the shortfall stated**, and its weight is redistributed. It is not given a token
allocation. This is §5 implemented as arithmetic rather than as a promise: a
64 MB device does not receive a 3 MB "local AI inference budget" that no model
could ever load into.

The redistribution loop drops the **single worst-funded** category, recomputes,
and repeats. Dropping every short category at once would discard ones the
redistribution would have rescued. It is bounded by the category count and is
deterministic: same pool in, same split out, in the same order, on any machine.

The consequence on a very small machine is that many tiny allocations collapse
into one usable allocation, which is the right trade — 12 MiB in one place is
useful, 12 MiB split six ways is not.

## Worked example: the 64 MB device

`bunny-os capability budget --simulate embedded-64mb`:

```text
  usable memory          64.0 MiB
  available right now    44.0 MiB
  protected reserve      24.0 MiB  (never allocatable, by anything)
  allocatable (idle)     40.0 MiB
  allocatable (now)      12.0 MiB
  essential services     28.0 MiB
  foreground workload    20.0 MiB

  Memory categories
    optional_services        12.0 MiB   Background Bunny OS services nobody is waiting on
    user_applications        unfunded   share would be 6 MiB against a 64 MiB floor; funding
                                        it would allocate memory too small to be used
    local_ai_inference       unfunded   share would be 3 MiB against a 512 MiB floor; ...
    companion_rendering      unfunded   share would be 1 MiB against a 192 MiB floor; ...
    speech_recognition       unfunded   share would be 0 MiB against a 256 MiB floor; ...
    [...]

  CPU
    effective cores      1
    background quota     0%
    interactive quota    100%

  GPU
    local inference      not permitted
    rendering            not permitted
    - No GPU devices were enumerated.
```

The five essential services fit in 28 MiB of the 40 MiB allocatable. Everything
else is refused, and each refusal names its own arithmetic.

## CPU quotas

`backgroundQuotaPercent` is `background_capacity x 0.6`, halved by
`preferLowEnergy`, then capped by `maximumBackgroundCpuPercent`. When background
headroom was not measured it is 10% — enough for the control plane to make
progress, small enough that a wrong guess does not hurt an interactive user.

`interactiveQuotaPercent` is whatever background does not take, floored at 10%.

`effectiveCores` is schedulable cores including any cgroup quota, not the
physical count.

## GPU permissions

`localInferenceAllowed` requires a usable GPU exposing CUDA or ROCm **and**
measured dedicated VRAM. A compute runtime with no measured VRAM does not
qualify, and the reason says so.

`renderingAllowed` requires a usable GPU with a verified Vulkan runtime **and** a
connected display. A rendering-capable GPU on a headless machine is refused,
with the reason naming the display rather than the GPU.

`preferLowEnergy` withdraws inference permission.

Every outcome carries its reasons, so `not permitted` is never bare.

## Storage budgets

10% of free space for cache (max 20 GiB), 2% for logs (16 MiB..512 MiB), half of
`/tmp` for temporary files (max 4 GiB). If the three together exceed free space
they are scaled down proportionally, so the budget never promises more than
exists.

A **read-only root grants no cache or log budget at all**, with the reason
stated.

## When memory cannot be measured

Essential services are funded at their declared minimums and the discretionary
pool is zero. The control plane is what reports that nothing could be measured,
so refusing it would leave the machine silent; everything optional is refused
until memory can be measured. `confidence` is `unknown` and a note says so.

This is §16's "missing data causes conservative behaviour rather than crashes",
made concrete.

## User constraints

All narrowing only:

| Setting | Effect |
|---|---|
| `maximumServiceMemoryBytes` | caps `allocatable`; a value *above* the derived budget does not widen it |
| `maximumBackgroundCpuPercent` | caps the background quota |
| `protectedReserveFraction` | raises the reserve, shrinking the budget |
| `preferLowEnergy` | halves background CPU, withdraws GPU inference permission |

Each applied cap adds a note naming itself, so a user who set a limit can see it
took effect.
