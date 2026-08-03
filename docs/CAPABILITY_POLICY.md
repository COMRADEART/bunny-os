# Policy precedence, orchestration and explanation

Implementation: `capability/engine.py`, `capability/plan.py`,
`capability/explain.py`. Schema: `schemas/execution-plan.schema.json`.

## Precedence

Highest first. Each level may only narrow what the level above permits.

| # | Level | Source | May it widen? |
|---|---|---|---|
| 1 | **Physical reality** | the inventory | no — a machine cannot be configured into having a display |
| 2 | **Protected reserve** | `capability/budget.py` | no — the engine never receives it as a spendable number |
| 3 | **Essential-service priority** | `Registry.start_order()` | no — enforced by allocation order, not by a check |
| 4 | **System policy** | `/etc/bunny-os/capability-policy.json` | within 1–3 |
| 5 | **User policy** | `$XDG_CONFIG_HOME/bunny-os/capability.json` | no — narrowing only |
| 6 | **Service manifests** | `capability/services/*.json` | within 1–5 |
| 7 | **Automatic derivation** | scores and budgets | within 1–6 |

Level 5's narrowing rule is mechanical, in `capability.policy._narrow`:

| Field | Merge |
|---|---|
| numeric ceilings | the smaller |
| `protectedReserveFraction` | the larger |
| booleans that permit | logical AND |
| booleans that require | logical OR |
| `permittedProviders` | **intersection** — a user may decline a provider the system permits, never add one |
| `disabledServices` | **union** — either layer may switch a service off; neither may switch on what the other switched off |

A user cannot grant themselves remote execution the system withheld. That is
what keeps this a preference surface rather than a policy bypass.

## The engine is a pure function

```python
evaluate(inventory, scores, budget, registry, policy, previous=None, now=0.0) -> ExecutionPlan
```

Same inputs, same plan, on any host, in any order, every time. `now` is a
monotonic clock **reading**, not a call — which is what makes hysteresis and
cooldown testable without sleeping, and what "the engine must not randomly change
decisions" means in practice.

A plan is a **value**. Producing one starts nothing, which is why
`bunny-os capability plan` is safe on a live machine.

## Allocation order enforces essential priority

Services are walked in `start_order()` and memory is handed out along that walk.
A high-priority service is funded before a low-priority one competes for the same
bytes. This is how "essential services always receive priority" is enforced —
not by a check that could be forgotten, but by the order the pool is consumed in.

Essential services draw on their own reserved pool first and fall back to the
discretionary one. Optional services see only the latter, so an optional service
cannot consume memory set aside to keep the control plane alive.

**An essential service may take more than its minimum only from memory no later
essential service needs for its own minimum.** Without that rule the first
essential service evaluated takes its recommended size and the last is refused
for want of six megabytes, and start order silently decides which parts of the
control plane exist. Under a genuine shortfall the reservation is dropped —
there is nothing left to protect, and holding memory back would refuse the
highest-priority services to keep a promise to the lowest.

The engine asserts its own invariant before returning: total granted memory never
exceeds `currentlyAllocatable + essentialServices`. A violation is a bug in the
allocation walk, and it surfaces there rather than as an OOM kill an hour later.
It has already earned its keep once — see the cooldown rule below.

## Actions

| Action | Meaning |
|---|---|
| `start_local` | run here, at the selected implementation |
| `start_remote` | dispatch to a permitted remote provider |
| `suspend` | was running, must yield resources, can resume |
| `stop` | was running, must yield resources, cannot suspend |
| `defer` | cannot start yet; a dependency is not up |
| `reject` | will not start, with a stated reason |

"Start with reduced limits" and "select a lightweight backend" are **not**
separate actions. Reducing a service *is* selecting a lower-ranked
implementation, and modelling it twice would let the two disagree.

## Decision order for one service

1. `disabledServices` → `reject` (`user-disabled`)
2. a conflicting service is running → `reject` (`conflict`)
3. a required dependency is not running → `defer` or `reject`
4. the machine cannot fund its essential services and this one is optional →
   `reject` (`essential-shortfall`)
5. walk the implementation ladder, pinned implementation first if any:
   - **remote**: consent, then configuration, then connectivity — see
     `docs/CAPABILITY_REMOTE_EXECUTION.md`
   - **local**: memory gate, then every declared requirement
6. first eligible implementation wins → `start_local` / `start_remote`
7. nothing eligible → `suspend` if running and suspendable, `stop` if running,
   `reject` otherwise

A **pin** is tried first and only first. A pin that does not fit is refused with
a reason and the ladder proceeds normally: a user's preference is a preference,
not an override of the machine's limits, and honouring it into an OOM kill would
serve nobody.

## Hysteresis

A Schmitt trigger on the memory gate:

```text
running service:  minimum x (1 - hysteresis)     easier to keep
stopped service:  minimum x (1 + hysteresis)     harder to start
```

The gap between the two thresholds is dead space in which nothing changes. That
is what stops a service flapping when free memory oscillates across a boundary.
Default `hysteresisFraction` is 0.15.

**Essential services are exempt.** The budget engine reserves exactly the sum of
essential minimums, so a 15% start surcharge on top of that reservation would
refuse the control plane on any machine sized to its own stated requirements —
including the 64 MB device this subsystem exists to serve. An essential service
also does not flap: if it cannot run, the machine is not viable and that is
reported rather than retried.

## Cooldown

Inside `stateChangeCooldownSeconds` (default 60) a service keeps its previous
action. Two classes of change are **never** held:

**Refusals that are not about resources** — `user-disabled`, `conflict`,
`dependency-unavailable`, `essential-shortfall`, `sensitive-data-local-only`,
`remote-not-permitted`. Holding a switched-off service running for another
minute is a bug wearing a feature's clothes.

**A running service whose grant no longer fits the current budget.** Holding it
would carry a memory grant sized for a machine that no longer exists. This rule
exists because the invariant assertion caught its absence: a companion granted
2 GiB on a workstation was being held through a cooldown onto a 1 GiB machine,
producing a plan that promised 8 GB against a 29 MB ceiling. **Stability may not
be bought by overcommitting the machine.**

## Runtime adaptation

Pass the previous plan and a new clock reading. Typical revisions:

| Condition | Revision |
|---|---|
| memory pressure | background indexing suspended (`background` priority, suspendable) |
| display unplugged | companion selects a lower-ranked implementation; shell held through its cooldown |
| audio devices gone | speech synthesis refused; companion falls to `text-only` |
| cooling engaged | background CPU quota halved |
| on battery | background quota halved, energy headroom collapses below 20% |
| GPU pressure | rendering permission withdrawn at the budget layer |
| recovery | a stable machine re-evaluated repeatedly produces an identical plan |

The last row is the strongest anti-oscillation property, and it is asserted:
`test_repeated_evaluation_on_an_unchanged_machine_never_changes_the_plan`.

Suspension is preferred to stopping wherever a service declares itself
suspendable. Nothing here takes an action that risks losing user work.

## Explanation

Every decision carries **structured** reasons, not prose. Prose assembled at the
point of refusal cannot be tested, cannot be translated, and drifts from the
arithmetic that produced it.

```json
{ "code": "budget-exhausted",
  "message": "2048 MiB is required and 217 MiB of the memory budget remains",
  "required": 2469396480, "measured": 227737600 }
```

`requirement-unmet` and `requirement-unknown` are distinct codes. Telling a user
their machine lacks 512 MB it may well have is a different and worse error than
telling them it could not be measured.

`capability/explain.py` renders these and recomputes nothing. If an explanation
could disagree with the arithmetic that produced it, one of them is wrong and the
user has no way to tell which.

**This is not model reasoning.** Every line comes from a measurement, a declared
requirement or a policy setting. Each explanation says so in its own footer.

## Worked example: one feature, three machines

The requirement from §18: the same Bunny OS feature, implemented differently
across a constrained ARM device, a laptop and a GPU workstation, without
exposing separate OS modes. All three outputs below are verbatim from
`bunny-os capability explain bunny.companion --simulate <machine>`.

### Constrained ARM device (`raspberry-pi-class`, 1 GB, shared-memory GPU)

```text
bunny.companion runs locally.

Reason:
  - animated-3d: 2048 MiB is required and 217 MiB of the memory budget remains
  - animated-2d: 768 MiB is required and 217 MiB of the memory budget remains
  - static-avatar: 256 MiB is required and 217 MiB of the memory budget remains
  - audio-only was selected instead of a richer implementation this machine cannot support
  - Voice with no visual presence (local) satisfies every declared requirement

Requirements satisfied:
  ok   memory.minimumBytes: required 96.0 MiB, measured 217.2 MiB
  ok   audio.outputRequired: required True, measured True

Implementation ladder (richest first):
     animated-3d            local   Full 3D character
     animated-2d            local   Animated 2D avatar
     static-avatar          local   Static avatar with speech bubbles
  -> audio-only             local   Voice with no visual presence
     text-only              local   Text status only
```

### Laptop (16 GB, integrated graphics)

```text
bunny.companion runs locally.

Reason:
  - animated-3d: 2048 MiB is required and 746 MiB of the memory budget remains
  - animated-2d: 768 MiB is required and 746 MiB of the memory budget remains
  - static-avatar was selected instead of a richer implementation this machine cannot support
  - Static avatar with speech bubbles (local) satisfies every declared requirement

Requirements satisfied:
  ok   memory.minimumBytes: required 256.0 MiB, measured 746.0 MiB
  ok   display.required: required True, measured 1

Implementation ladder (richest first):
     animated-3d            local   Full 3D character
     animated-2d            local   Animated 2D avatar
  -> static-avatar          local   Static avatar with speech bubbles
     audio-only             local   Voice with no visual presence
     text-only              local   Text status only
```

### GPU workstation (32 GB, one 16 GB discrete GPU)

```text
bunny.companion runs locally.

Reason:
  - Full 3D character (local) satisfies every declared requirement

Requirements satisfied:
  ok   memory.minimumBytes: required 2.0 GiB, measured 15.7 GiB
  ok   gpu.required: required vulkan, measured 1
         a GPU with a verified vulkan runtime; presence of a PCI device alone
         does not satisfy this
  ok   display.required: required True, measured 2
  ok   display.minimumResolution: required 1280x720, measured 3840x2160
  ok   scores.graphics: required 60.0, measured 96.25

Implementation ladder (richest first):
  -> animated-3d            local   Full 3D character
     animated-2d            local   Animated 2D avatar
     static-avatar          local   Static avatar with speech bubbles
     audio-only             local   Voice with no visual presence
     text-only              local   Text status only
```

### What is identical

The service id. The five implementations. The ladder, shown in full on all
three, with the same names in the same order. The explanation format. The
vocabulary the user uses to talk to the companion, the permission model, the
controls, the transparency surfaces.

### What differs

One line: which rung was selected, and the arithmetic that selected it — which
is visible on all three.

### What does not exist

Any mode. No machine was assigned a level, a tier or an edition. The workstation
did not install "Bunny OS Ultra". The ARM board is not running a "Lite edition".
Each ran the identical fourteen-manifest registry through the identical engine
and got a different answer to the same question, because it is a different
machine.

The comparison that makes the point sharpest is `multi-gpu-ai-server`: eight
80 GB accelerators, 512 GB of RAM, and it also selects `text-only` — because
nothing is plugged into it. Capability is per-requirement. There is no level to
be at.
