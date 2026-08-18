# `tests/companion` — the intermittent failure, measured

§7 of the Phase 5 directive: *"Do not call them 'flaky' without evidence.
Determine the failure probability. Then fix the isolation problem."*

This is the evidence. The word "flaky" does not appear as a conclusion
anywhere in it.

---

## 1. Conditions and rates

Measured on the Fedora 44 reference target, as user `bunny`, from an ext4
`git clone --local` — the conditions
`memory/linux-reference-target-runbook` requires, because `/mnt/c` produces
nine false failures and a root-owned checkout produces one more.

Commit under test: `eca0efaf` for A/B/C.

| # | Condition | Runs | Slice failures | Rate |
| --- | --- | ---: | ---: | --- |
| A | `VerticalSliceAndPerformanceTests` alone | 20 | 0 | **0/20** |
| D | The whole *module* alone | 40 | 0 | **0/40** |
| C | The target immediately after each earlier neighbour, separately | 60 | 0 | **0/60** |
| B | The whole `tests/companion` package | 28 | 2 | **≈2/28** |

Stage C covered **all twelve** modules that `unittest discover` runs before
`test_character_cli_vertical` — discovery sorts by name, so nothing sorting
after it can have touched the state the slice reads — at five repetitions each.

Stage D closes a gap in my own first design. Stages A and C both ran the target
*class*, so neither could ever have seen what `IncidentalRendererFaultTests`
leaves behind — it sorts before `VerticalSliceAndPerformanceTests` in the same
module and monkeypatches `CharacterRendererController.apply` to raise. 40 runs
of the whole module found nothing either, which rules intra-module interference
out as well.

### Against the Phase 4 figure

Phase 4 recorded "5/5 alone and 1-in-3 in-package". The *alone* result
reproduces, on a sample four times larger. The *in-package* rate does not:
**1 in 12 here against 1 in 3 there**.

Both are samples of the same rare event and neither is the rate. What can be
said is that it is rare, that it is in-package only, and that **the 1-in-3
figure should not be quoted as measured** — Phase 4's own closing lesson was
that one run is a sample, and this is that lesson applied to its own number.

---

## 2. What it is not

**It is not one neighbour.** 60 pair runs, twelve neighbours, zero
reproductions. If a specific earlier module left state the slice trips over,
running that module immediately before it sixty times would have found it.

**It is not repetition of the slice itself.** The slice was run 12 times
consecutively in a single process, in isolation: 12/12 clean, no renderer
fault recorded on any of them.

**It is not the instrument being unable to see.** Which is the point of §3.

---

## 3. What it is: the host's own memory pressure

Every failing run carries the identical failure list:

    ['step 17 (trigger controlled presentation pressure)',
     'step 21 (recover only after hysteresis)']

Steps 18, 19 and 20 pass. That pattern is the fingerprint of one state: **the
rung capped below `animated-2d`**, because 17 and 21 are the only two steps
that assert `animated-2d` and the other three assert degradation, which a
degraded renderer satisfies for free.

**Three steps pass because the machine is already broken.** That is why this
has looked like a selector defect for four phases.

### The first hypothesis, and why it was wrong

A recurring renderer fault caps the rung the same way, and injecting one
reproduces the signature exactly. It is not the cause.

The instance caught on attempt 16 of a package hunt recorded
`incidentalRendererFault=None` and `rendererHealthy=True` on both
`VerticalSliceAndPerformanceTests` failures. **No fault occurred.** Every
earlier explanation — a transient renderer fault, host contention, cross-test
interference — predicts a fault. There wasn't one.

### The cause

`CharacterPresenter` builds `base_signals` from `assess_current_machine()` —
the **real host** — and every field `_VISUAL` did not name survived into every
evaluation:

```python
self.base_signals = replace(signals_from_assessment(assessment), ...)
...
signals = replace(self.base_signals, **derived)   # derived includes _VISUAL
```

`_VISUAL` pinned `display_available`, `graphics_ready`,
`available_memory_bytes` and `gpu_available`. It did **not** pin
`memory_pressure`, which `diagnostics.signals_from_assessment` reads as:

```python
pressure = inventory.memory.pressure_some_avg10.get(None)
memory_pressure = isinstance(pressure, (int, float)) and pressure >= 0.1
```

That is Linux PSI — `/proc/pressure/memory`, `some avg10` — a **ten-second
rolling average of memory stall**. A suite that has just run several thousand
tests in one process crosses 0.1, intermittently, for reasons that have nothing
to do with this slice.

`adaptation.py` then does what it should:

```python
if signals.memory_pressure:
    degrade(Presentation.STATIC_IMAGE, "memory-pressure",
            "memory pressure disabled animation")
```

### Proved, not inferred

Setting that one field and changing nothing else:

| Host | passed | step 17 | fault | healthy | step 21 |
| --- | --- | --- | --- | --- | --- |
| no memory pressure | **True** | `animated-2d` | None | True | `animated-2d`, 2 samples |
| memory pressure | **False** | **`static-image`** | **None** | **True** | `static-image`, 5 samples |

The failing row's `failures` list is byte-identical to every observed failure,
and step 17's recorded reason reads **"memory pressure disabled animation"**.
`fault=None` and `healthy=True` are the tells, and they match the caught
in-package instance.

It also explains the rates, which no neighbour hypothesis could: **it is the
package that makes the host stall, and no test in it is the cause.** 0/20, 0/40
and 0/60 are all runs too small to move PSI.

---

## 4. The fix, and why it is not silencing a flake

`_VISUAL` now pins every host-derived signal the presentation ladder can
degrade or cap on: `memory_pressure`, `thermal_pressure`, `cpu_pressure`,
`on_battery`, `battery_percent`.

**Pinned in the slice, not the presenter.** The presenter reading the real
machine is correct — on a real machine under real pressure the companion
*should* stop animating. It is the slice that has to declare its conditions.

**The second-order problem was worse than the failure.** Step 18 *declares*
`memory_pressure: True` to prove the selector degrades. On a machine already
under ambient pressure the rung was static before step 18 asked, so **step 18
was passing without testing anything**. Pinning these is what makes steps 17
to 21 measure the selector at all — it is a strengthening, not a suppression.

### The guard is structural

`tests/companion/test_slice_host_invariance.py` parses `adaptation.py` with
`ast`, collects every `signals.<field>` the ladder consults, and requires each
one to be pinned in `_VISUAL` or declared exempt **with a reason**. A signal
added to the ladder cannot reopen this the way `memory_pressure` stayed open
for four phases.

It earned that on its first run: it found a fourteenth signal,
`package_supports_3d`, which was then checked rather than waved through — a
package property read only inside `if requested in THREE_D`, a branch the
slice's `animated-2d` ceiling cannot reach — and declared with that reason.

### Negative controls

| Control | Result |
| --- | --- |
| Remove the `memory_pressure` pin | 6 of 10 tests fail |
| Step 18 must still degrade on *declared* pressure | asserted; a fix that disabled the check fails here |
| Step 19 must still reach `text-only` | asserted |
| Step 17 must reach `animated-2d` **with no pressure reason** | asserted — pinning the signals to any arbitrary value would not satisfy it |

---

## 5. A separate finding, from the same investigation

Stage B was run at a commit where `qualification/__init__.py` had just been
added. The evidence-preservation guard failed on Linux and had passed on
Windows minutes earlier — because on Windows the file was not yet staged, and
the check asks git rather than the filesystem. Declared as maintained tooling,
with the negative control re-run against `qualification/tpm/` (a genuinely
earlier tree) to confirm the guard still fails there.

Not a product defect. Recorded because "the check passed on the development
host" was true and meant nothing, which is the fifth time in this project's
history the reference target has been the only instrument that could answer a
question.
