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
| C | The target immediately after each earlier neighbour, separately | 60 | 0 | **0/60** |
| B | The whole `tests/companion` package | 12 | 1 | **1/12** |

Stage C covered **all twelve** modules that `unittest discover` runs before
`test_character_cli_vertical` — discovery sorts by name, so nothing sorting
after it can have touched the state the slice reads — at five repetitions each.

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

## 3. What it is: the signature, and the mechanism behind it

Every failing run carries the identical failure list:

    ['step 17 (trigger controlled presentation pressure)',
     'step 21 (recover only after hysteresis)']

Steps 18, 19 and 20 pass. That pattern is not arbitrary — it is the fingerprint
of one specific state, and it was reproduced deterministically to confirm it.

**The controlled experiment.** `CharacterRendererController.apply` was
monkeypatched to raise, and the slice run three ways:

| Injection | `passed` | step 17 presentation | `retryCleanOfFaults` | failures |
| --- | --- | --- | --- | --- |
| none | **True** | `animated-2d` | — | `[]` |
| one transient fault at call 10 | **True** | `animated-2d` | `True` | `[]` |
| a recurring fault from call 40 | **False** | **`static-image`** | **`False`** | **`['step 17 …', 'step 21 …']`** |

The third row is the observed failure, exactly. Not a similar failure — the
same two steps, in the same order, with 18-20 still passing.

**The mechanism.** A renderer fault sets the presenter unhealthy
(`CharacterPresenter.report_failure` → `_healthy = False`). An unhealthy
renderer is capped below `animated-2d` by the capability selector. So:

* step 17 asserts `animated-2d` → sees `static-image` → **fails**
* step 18 asserts `static-image` under memory pressure → already there →
  passes
* step 19 asserts `text-only` when the display goes → passes
* step 20 asserts "not `animated-2d`" → passes trivially
* step 21 asserts recovery to `animated-2d` → **fails**

**Three steps pass because the machine is already broken.** That is why the
failure has looked like a selector defect for four phases: the three steps that
would have caught the real state are the three that a degraded renderer
satisfies for free.

**The design already tries to survive this.** `_pressure_sequence` returns
whether the renderer stayed healthy; on a fault the slice advances 15 synthetic
seconds past `_HEALTH_RECOVERY_SECONDS`, lets the selector's hysteresis run,
and asks the whole sequence again. A *single* fault is therefore absorbed and
named. The failing runs are the ones where **the retry faulted too**.

---

## 4. What was fixed, and what is open

### Fixed: the failure is diagnosable

The slice report has always carried `incidentalRendererFault`,
`retryCleanOfFaults` and the renderer events **with the exception text on
them**, and every assertion printed `report.failures` — a list of step names —
and nothing else. Four phases of investigation started from a step number
because the field beside it was never printed.

`tests/companion/test_character_cli_vertical.py` now formats the diagnosis into
the assertion message. The next failure says which state it was in and why.

This is the Phase 4 rule applied: *make the thing that failed report what it
saw. That diagnosis would have been one field long.*

### Open: which real exception fires in-package

The class of cause is settled — a renderer fault, twice, during the pressure
sequence. The specific exception is not, because it has not been caught with
the new diagnostic attached. A run of 30 full-package attempts is in progress
for exactly that.

**It is not closed and this document does not close it.** The reference-suite
gate requires CLEAN and the suite is not clean.

### What the fix must not be

The tempting repair is to make steps 17 and 21 tolerant of a degraded rung.
That would delete the only assertion in the slice that the companion ever
reaches `animated-2d`, and it would pass on a build where the renderer never
worked at all. `IncidentalRendererFaultTests` already carries the negative
control for this — a persistent fault must still fail — and any repair has to
keep that test failing for the right reason.

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
