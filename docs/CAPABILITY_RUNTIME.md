# The Bunny OS capability runtime

Bunny OS is one operating system. It is installed once, and it adapts to the
machine it finds itself on. There is no Low edition, no Balanced mode, no
Desktop build and no DGX build. A 64 MB ARM board and a 512 GB eight-accelerator
server run the same image, the same services and the same explanations; what
differs is which implementations were selected and which features were refused,
and the machine will tell you exactly why in both cases.

This document describes the subsystem that makes that true.

## Naming

The brief that commissioned this work proposed the name *Bunny Capability
Runtime*. This repository already names these components, in
`docs/phase-1/BUNNY_OS_PHASE_1.md` §7, and the existing names are used:

| Phase 1 component | Implemented by |
|---|---|
| **Hardware Capability Service** | `capability/discovery/`, `capability/model.py` |
| **Capability Registry** | `capability/registry.py`, `capability/manifest.py` |
| **Budget Service** | `capability/budget.py` |
| **Capability Router** | `capability/engine.py` (services), `capability/router.py` (tasks) |

The Python package is `capability/`, matching the repository's other top-level
domain packages (`enterprise/`, `installer/`, `release/`, `sync/`).

## The rule this implements

Constitutional requirement **C11 — One Bunny, honest about capability**:

> No editions. Capability negotiated per task from detected resources. [...]
> **Capability profiles derive from detected resources only — a profile keyed on
> a product tier fails review.**

And §13.9 of the same document draws the line precisely:

**Identical at every capability level, non-negotiable:** the intent vocabulary,
the permission model, the plan as source of truth, task history, user controls,
the refuse list, keyboard-only completeness, and every transparency and
disclosure surface.

**May adapt — performance and fidelity only, never capability semantics:**
animation quality, local model size, concurrency, context length, background
processing, caching aggressiveness, sandbox density, and the routing mix.

> A low-capability machine does not get a reduced Bunny. It gets the same Bunny
> that escalates more often and says so.

## Architecture

```text
hardware discovery          capability/discovery/     touches the machine
        v
normalized inventory        capability/model.py       versioned, no identifiers
        v
capability scores           capability/scores.py      13 independent dimensions
        v
resource budgets            capability/budget.py      what may safely be consumed
        v
policy evaluation           capability/engine.py      + registry + policy
        v
execution plan              capability/plan.py        a value, not an action
        v
explanation                 capability/explain.py     measurements, never inference
```

Every stage after discovery is a **pure function** of the stage before it plus
configuration. Same inventory, same policy, same registry, same clock reading →
same plan, on any host, in any order, every time. That property is what makes
the simulated-hardware tests meaningful and what "the engine must not randomly
change decisions" means in practice.

Only `capability/discovery/` reads the machine. Only `capability/engine.py`
reaches a verdict. Nothing in this package starts, stops or suspends anything —
producing a plan is safe on a live machine, which is why
`bunny-os capability plan` can be run at any time.

## Commands

```text
bunny-os capability inspect              the sanitized inventory
bunny-os capability scores               the scored dimensions
bunny-os capability budget               what may be consumed
bunny-os capability plan                 what will run
bunny-os capability status               one line per service
bunny-os capability explain <service>    why, for one service
bunny-os capability policy               the effective policy and its source
bunny-os capability machines             the simulated machines
```

Every command except `machines` accepts:

- `--simulate <machine>` — assess a synthetic machine instead of this one.
  Output is labelled `SIMULATED HARDWARE` everywhere it appears.
- `--inventory <path>` — assess a previously captured inventory.
- `--policy <path>`, `--services <dir>`, `--budget-ms <n>`.
- `--json` — machine-readable output conforming to the published schemas.

The brief sketches these under a `bunnyctl` name; this repository's management
CLI is `bunny-os`, and introducing a second front-end for one subsystem would
have been worse than the one-word difference. The mapping is one-to-one and is
recorded in `tools/bunny-os/bunny_os/capability_cli.py`.

## Capability inventory

Schema: `schemas/capability-inventory.schema.json`. Detailed in
`docs/CAPABILITY_SCHEMA.md`.

Every measurable fact is an **observation** carrying a value *and* the reason it
has that value, in one of three states:

| State | Meaning |
|---|---|
| `measured` | The probe ran and returned this value. |
| `absent` | The probe ran; the thing is not there. A machine with no battery has an `absent` battery, which is knowledge. |
| `unknown` | The probe could not run, timed out, or returned something unparseable. Nothing is known. |

The distinction is the point. If a GPU probe fails and the field defaults to
`0 VRAM`, the router makes a confident wrong decision. If it becomes `unknown`,
the router is conservative and says why. A silently wrong capability field
produces a silently wrong routing decision, which is worse than a missing one.

`Observation.get()` therefore takes a **mandatory** default: there is no
zero-argument form, so every call site records what it decided to assume.

## What is detected

**CPU** — architecture, vendor, model, physical cores, logical threads,
instruction sets, maximum frequency, virtualization support, **cgroup quota**,
load average, frequency capping.

**Memory** — physical, available, **cgroup ceiling**, cgroup usage, swap, PSI
pressure, firmware-reserved.

**GPU and accelerators** — per device: vendor, device id, class, bound driver,
render node, VRAM, and per-runtime readiness for CUDA, ROCm, Vulkan and OpenCL.
NPUs and kernel `accel` devices are enumerated but never claimed usable.

**Storage** — total, available (`f_bavail`, not `f_bfree`), filesystem,
read-only state, rotational/solid-state class, I/O pressure, `/tmp` space.

**Network** — interfaces, carrier, default route (IPv4 and IPv6), connection
type, metering, and *optionally* bounded reachability.

**Power and thermal** — supply, battery presence and charge, power-saving
profile, thermal zones, engaged cooling.

**Display and interaction** — connected outputs, maximum mode, keyboard,
pointer, touch, audio output and input, camera.

Three rules govern all of it, and they are worth stating because each prevents a
specific class of wrong answer:

**A cgroup ceiling binds, not the host's hardware.** `usable_bytes` is the
smaller of physical memory and any imposed limit; `effective_cores` is the
smaller of the thread count and any CPU quota. A 512 MB container on a 512 GB
host has 512 MB, and a budget engine reading `MemTotal` would size a service for
the host and watch the kernel kill it.

**Presence is not usability.** A PCI function with vendor `0x10de` proves a card
is bolted to the board. It does not prove a driver bound, that a render node
exists, or that CUDA is installed. `Inventory.usable_gpus` requires a bound
driver *and* a render node, and runtime readiness is a further, separate
question.

**Vendor tools are the only VRAM source.** Read from `amdgpu` sysfs counters and
`nvidia-smi`. A generic adapter-memory field is never read, because it is a
well-known wrong number (Phase 1 §13.4).

## Scoring

Schema and methodology: `docs/CAPABILITY_SCORING.md`.

Thirteen dimensions, each bounded `0.0..100.0` or `None`, each deterministic,
each carrying the raw measurements behind it and a confidence:

```text
cpu_compute              memory_available         gpu_compute
gpu_memory               storage_capacity         storage_performance
network_quality          local_ai                 graphics
audio                    interactive_desktop      background_capacity
energy_thermal_headroom
```

**There is no overall score.** A machine is not "high" or "low"; it is a vector
of thirteen numbers, and no arithmetic path exists by which one compensates for
another. The concrete failure a single score produces: a workstation with two
accelerators and 4 GB of usable RAM inside a restrictive cgroup would score
"very high" on any weighted average, and the policy engine would start a service
that is then OOM-killed.

`None` is not zero. A dimension with no evidence scores `None` with `unknown`
confidence, because zero means "measured, and there is none" and would let a
decision proceed on a fact nobody established. `Score.at_least()` therefore takes
a mandatory `when_unknown` argument, so the treatment of missing data appears at
the call site and in review.

## Budgets

Schema: `schemas/resource-budget.schema.json`. Detailed in
`docs/CAPABILITY_BUDGETS.md`.

Two memory figures, and the difference matters:

- **allocatable** — what may be consumed on an idle machine. Derived from usable
  memory minus the protected reserve. The planning number; it does not move when
  a user opens a browser.
- **currently allocatable** — what may be committed right now, from memory
  actually free. The admission number.

Budgeting against only the first over-commits a loaded machine; against only the
second makes the plan flap every time a tab opens.

The **protected reserve** is allocatable by nothing, essential services
included — the engine never sees it as a number it could spend. Its floor is
absolute (20% of 64 MB is 13 MB, which is not enough slack for the kernel to
reclaim) and its ceiling is absolute (20% of 512 GB would strand a hundred
gigabytes for no benefit).

Discretionary memory is split by weight across ten categories, and a category
whose share falls below the size at which funding it is pointless is reported
**unfunded with the shortfall stated**, not given a token allocation. A 64 MB
device does not receive a 3 MB "local AI inference budget" that no model could
load into.

## Service manifests

Schema: `schemas/service-capability-manifest.schema.json`. Detailed in
`docs/SERVICE_MANIFESTS.md`.

A service declares what it needs; the engine decides whether it gets it. The
manifests Bunny OS ships are in `capability/services/`.

**Implementations are the degradation ladder.** The brief lists degradation
steps separately from implementation selection; they are the same mechanism seen
twice. `bunny.companion` with a 3D implementation, a 2D one, a static avatar, an
audio-only form and a text-only floor *is* a service with five degradation
levels, and modelling it once means selection and degradation cannot disagree.
Rank 1 is the richest; the engine walks upward and takes the first whose
requirements are met.

Manifests are JSON, not the YAML the brief sketches. This repository validates
JSON in `release/validation.py`, ships JSON Schemas in `schemas/`, and cannot
rely on PyYAML — its workflow validator degrades to SKIP when PyYAML is missing.
A manifest format that cannot be validated on every host is one that is not
validated.

## Policy and orchestration

`capability/engine.py`. Detailed in `docs/CAPABILITY_POLICY.md`.

Services are evaluated in `Registry.start_order()`: essential first, then
descending priority, with dependencies pulled ahead of their dependents. Memory
is handed out along that walk. **This is how "essential services always receive
priority" is enforced** — not by a check that could be forgotten, but by the
order the pool is consumed in.

An essential service may take more than its minimum only from memory no later
essential service needs for its own minimum. Without that rule the first
essential service evaluated takes its comfortable size and the last is refused
for want of six megabytes, and start order silently decides which parts of the
control plane exist.

Actions: `start_local`, `start_remote`, `suspend`, `stop`, `defer`, `reject`.
"Start with reduced limits" and "select a lightweight backend" are not separate
actions — reducing a service *is* selecting a lower-ranked implementation.

**Hysteresis** is a Schmitt trigger on the memory gate: a running service is
re-evaluated at `minimum x (1 - h)`, a stopped one at `minimum x (1 + h)`. The
gap is dead space in which nothing changes. Essential services are exempt,
because the budget engine reserves exactly the sum of essential minimums and a
start surcharge on top of that reservation would refuse the control plane on any
machine sized to its own stated requirements.

**Cooldown** holds a service at its previous action inside a window, with two
exceptions that are never held: refusals that are about correctness or consent
rather than resources (the user switched it off, a dependency died, a conflict
appeared), and a running service whose previous grant no longer fits the current
budget. Stability may not be bought by overcommitting the machine.

## Local versus remote

`capability/router.py`. Detailed in `docs/CAPABILITY_REMOTE_EXECUTION.md`.

The routing order is **permission first, capability second**. A task that may
not leave the device is refused before anything asks whether it could have run
locally. Local incapability is never an argument for remote execution:

> Sensitive tasks must not be sent remotely merely because the local device is
> weak.

Defaults, all independent of one another:

```yaml
remote_execution:
  enabled: false                # off
  require_user_approval: true   # even when on
  allow_sensitive_data: false   # even when on and approved
  permitted_providers: []       # "on" is not a destination
```

An empty allowlist permits nothing even when `enabled` is true. A provider that
has not declared its retention, training use and locality **fails closed** — it
cannot be the destination for a decision the user is entitled to understand.

Providers are an interface, not an integration. `RemoteProvider` is a protocol;
`NullProvider` and the test doubles are the only implementations in this
repository. No credential is read, stored or logged here, and no named
commercial service is contacted.

## Runtime adaptation

Conditions change, so `evaluate()` accepts the previous plan and a monotonic
clock reading and produces a revised one. The clock is a parameter rather than
a call, which is what makes hysteresis and cooldown testable without sleeping.

What the engine will do: suspend background indexing under memory pressure,
select a lower-ranked companion implementation when a display is unplugged, halve
background CPU on battery or when cooling engages, refuse rendering when
headless, fall back to text when audio disappears.

What it will not do: anything that risks losing user work. Suspension is
preferred to stopping wherever a service declares itself suspendable, and
services that cannot be suspended (the shell session) are held through their
cooldown rather than torn down the instant a cable moves.

## Constrained hardware

64 MB is an explicit architectural constraint, and the arithmetic is stated
rather than promised. On the simulated 64 MB board:

```text
usable                    64.0 MiB
protected reserve         24.0 MiB   (never allocatable, by anything)
allocatable (idle)        40.0 MiB
essential services        28.0 MiB
discretionary             12.0 MiB
```

Five essential services start — broker, capability runtime, health, recovery,
update. Every heavy feature is refused with a stated reason: the shell, local
inference, the companion, speech, browser automation, the vector index. Nine of
ten budget categories report unfunded.

The device is **not a separate edition**. Same registry, same fourteen
manifests, same schema version, same explanations. It is the same Bunny OS with
less of it started, and `bunny-os capability explain` on that board answers the
same questions in the same format as it does on a workstation.

## Security and privacy

`docs/CAPABILITY_SECURITY.md` documents the trust boundaries. In brief:

- Probes run **no shell**, ever. `capability/discovery/sources.py` holds an
  allowlist of absolute paths; a bare command name is refused because it would
  resolve through `PATH`.
- Every subprocess and read is time- and size-bounded, under one shared deadline
  for the whole pass, so boot cannot stall on a wedged device.
- Parsed output becomes strings, ints and bools. It never becomes a path that is
  opened or an argument passed back to a subprocess.
- The inventory contains **no serial numbers, MAC addresses, hostnames or
  machine UUIDs**, and is transmitted by nothing. Asserted by a test.
- Policy files that are group- or world-writable are reported, because a
  capability policy decides whether remote execution is permitted.
- Manifests are validated, and a malformed one raises rather than being
  partially honoured.

## Known limitations

Recorded in `KNOWN_LIMITATIONS.md` under "Capability runtime". The load-bearing
ones:

- **The 64 MB target is not measured.** The arithmetic shows the declared
  essential floor fits in the declared budget. Nothing in this repository has
  run Bunny OS on a 64 MB board, and no such claim is made.
- **No physical hardware has been exercised.** Every result here comes from
  simulated inventories or from whichever host ran the tests.
- **Declared service memory figures are estimates**, not measurements. They are
  the manifest authors' declarations and have not been profiled.
- **The package is not in the image build.** Manifests are read from the source
  tree. Adding files to the image would change the built artifact and invalidate
  the current reproducibility candidate.
- **The plan is produced, not applied.** Nothing here starts, stops or
  resource-limits a service.
- **Bandwidth is never measured.** An honest measurement means moving real
  traffic on a user's connection.
- Metering requires NetworkManager; without it, metering is `unknown`, which
  policy treats as possibly metered.

## Reading order for developers

1. `docs/CAPABILITY_SCHEMA.md` — the inventory and its three availability states
2. `docs/CAPABILITY_SCORING.md` — the dimensions and their curves
3. `docs/CAPABILITY_BUDGETS.md` — the reserve and the categories
4. `docs/SERVICE_MANIFESTS.md` — declaring a service
5. `docs/CAPABILITY_POLICY.md` — precedence, hysteresis, explanation
6. `docs/CAPABILITY_REMOTE_EXECUTION.md` — the task abstraction and providers
7. `MODE_MIGRATION_REPORT.md` — what was migrated and what was found
