# Mode migration report

Scope: every reference in this repository to a low / balanced / high / ultra /
performance / hardware-tier or similar mode implementation, classified and
dispositioned.

Method: a repository-wide sweep of tracked files (`git ls-files`) for mode and
tier vocabulary in `*.py`, `*.json`, `*.js`, `*.yaml`, `*.yml`, plus a
documentation sweep, plus a read of every hardware-classification function.

## Headline finding

**Bunny OS never implemented user-facing performance modes.** There was nothing
to remove. The sweep found no `PerformanceMode`, no `HardwareTier`, no
`performance_mode` configuration key, and no code branching on a named
capability level anywhere in the tracked tree.

The project rule was already the design. `docs/phase-1/BUNNY_OS_PHASE_1.md`
states it as constitutional requirement C11 — *"No editions. Capability
negotiated per task from detected resources [...] a profile keyed on a product
tier fails review"* — and §13.9 draws the line between what is identical at
every capability level and what may adapt. What was missing was the machinery to
make that true, not the intent. That machinery is `capability/`.

One genuinely mode-shaped runtime artefact existed and has been migrated. Five
classification systems were examined and retained, each for a stated reason.
Everything is listed below.

## Migrated

### 1. `tools/bunny-os/bunny_os/info.py` — `_model_suitability()`

**Was:** a function that collapsed a machine into one of three labels —
`candidate-20b-moe`, `candidate-small-local`, `classification-only-or-hosted` —
from total RAM and a Boolean "is there an active GPU". Surfaced in the
`bunny-os hardware` JSON as `localModelSuitability` and printed to users as
`Local model assessment: <label>`.

**Why it had to go:** this is exactly the "single misleading power level" the
brief prohibits, and it was wrong in ways that mattered:

- It read `MemTotal`, so a workstation inside a 512 MB cgroup was assessed
  `candidate-20b-moe`.
- Its "active GPU" test accepted any device in `driver-active` state, so a card
  with no render node counted.
- It ignored storage entirely, so a read-only appliance with 200 MB free got the
  same answer as a machine with a terabyte.
- Three labels cannot express "the GPU is fine and the memory is not", which is
  the single most common real configuration this subsystem has to handle.

**Now:** replaced by thirteen independent scored dimensions
(`bunny-os capability scores`), of which `local_ai`, `memory_available`,
`gpu_compute` and `gpu_memory` cover what the label attempted. They cannot mask
one another; see `docs/CAPABILITY_SCORING.md`.

**Backward compatibility:** the `localModelSuitability` key is **retained for one
release** because `contractCapabilities` is a versioned surface and removing a
key is a contract change. It now carries:

```json
{
  "assessment": "candidate-small-local",
  "verified": false,
  "deprecated": true,
  "replacedBy": "bunny-os capability scores",
  "deprecationReason": "A single label cannot represent a machine. ..."
}
```

The human-readable output **no longer prints the label**. It points at
`bunny-os capability scores` and `bunny-os capability plan` instead. Showing a
user one word where the honest answer is thirteen independent measurements is
the thing this work exists to stop.

Removal is scheduled with the next `contractVersion` increment.

**Tests:** `tests/unit/test_info.py` gained
`test_model_suitability_is_marked_deprecated_and_names_its_replacement` and
`test_the_collapsed_label_is_no_longer_shown_to_a_user`.

### 2. Priority band vocabulary (new code, corrected before landing)

The first draft of `capability/manifest.py` used `critical / high / normal /
low / background` for service priority bands. Those are correct English for a
priority ranking and are *not* performance modes — but this is the one codebase
where "low" and "high" are reserved words, and a reader grepping this tree for a
performance mode should find nothing rather than find a priority and have to
decide.

Renamed to `critical / important / standard / deferred / background`, in the
parser, the JSON Schema, and all nine affected manifests.
`tests/capability/test_manifest.py::test_no_manifest_contains_a_mode_word_anywhere`
now asserts the absence as a property of the shipped bytes, which is only
possible because the vocabulary was changed.

## Deprecated

### 3. Mode-based policy keys (`capability/policy.py`)

Seven configuration keys are **refused** with their capability-shaped
replacement named:

| Refused key | Message |
|---|---|
| `performanceMode`, `performance_mode` | set `maximumBackgroundCpuPercent` and `maximumServiceMemoryBytes` instead |
| `hardwareTier`, `hardware_tier`, `capabilityTier` | capability is derived from measurement; there is no tier to declare |
| `profile`, `mode` | use `disabledServices` and `pinnedImplementations` to constrain specific services |
| `powerLevel` | set `preferLowEnergy`, or a `maximumBackgroundCpuPercent` |

**None of these ever shipped in this repository.** They are listed because §15
requires a migration path and because a user arriving from another adaptive-OS
design will reach for exactly these names. Refusing is deliberate: silently
ignoring an unknown key would leave an operator believing a limit was in force
when it was not.

Tested in `tests/capability/test_cli.py::PolicyFileTests`.

## Retained, with reasons

Each of these matched a mode-vocabulary sweep and each is a different thing.

### 4. `installer/hardware/preflight.py` — `classify()`

Returns `supported`, `supported_with_limitations`, `experimental`,
`unsupported`, `unknown` per hardware item at install time.

**Retained.** These are *installability support statements* derived from an
evidence table, answering "has Bunny OS been qualified on this", not "how fast
is this machine". Nothing branches on them at runtime, and they are consumed
only by installer preflight display. They belong to the qualification programme
(`docs/HARDWARE_SUPPORT.md`), which is a separate concern with separate
evidence rules. Conflating support status with runtime capability would let an
unqualified-but-capable machine be throttled and a qualified-but-tiny one be
overcommitted.

### 5. `installer/hardware/preflight.py` — `minimum_requirements()`

Named profiles: `base_desktop`, `cloud_models`, `small_local_models`,
`medium_local_models`, `developer`, each with RAM and storage minimums.

**Retained, and this is the closest call in the report.** These read as tiers.
They are not: they are *published minimum system requirements* — the table a
user consults before downloading, equivalent to "4 GB RAM, 40 GB disk" on a
product page. Nothing selects one, nothing stores one, and no code branches on
one. The function returns a document; it takes no arguments and has no effect.

The distinguishing test: a mode is *assigned to a machine and changes its
behaviour*. These are never assigned. A machine meeting `small_local_models`
does not thereby run in a small-local-models configuration; it runs the same
Bunny OS, and what actually starts is decided by the capability runtime from
measurement.

`docs/CAPABILITY_RUNTIME.md` cross-references them so a reader arriving from the
installer finds the runtime path.

### 6. `operations/hardware.py` — `TIERS`

`Stable recommended`, `Stable supported`, `Best effort`, `Experimental`,
`Unsupported`, `Untested`.

**Retained.** Evidence-derived qualification classifications: `classify_hardware`
reads a report of *executions and observed evidence* and returns how much has
been proven about a device. `Untested` is its default. This is a statement about
the testing programme, not about the machine's capability, and it is what the
stable support matrix publishes.

### 7. `operations/modes.py` — `MODE_REQUIREMENTS`

`multi-user`, `local-only`, `bunny-disabled`.

**Retained.** Qualification *scenarios* — deployment configurations under test,
each with a list of evidence that must be present. Not performance levels, not
assigned to machines, not user-selectable as a capability setting.

### 8. `hardwareClass` in `schemas/beta-feedback.schema.json` and `schemas/hardware-qualification.schema.json`

**Retained.** A free-text descriptive label for a physical machine in bug reports
and qualification records ("ThinkPad X1 Carbon Gen 11"), used to group reports by
device. Bounded at 256 characters, never parsed, never branched on.

## Competing policy systems

**There is exactly one.** `capability/engine.py` is the only component that
decides whether a Bunny OS service runs. No prior implementation was left active
alongside it, because none existed.

The three retained classification systems (4, 6, 7) operate at install time and
in the qualification programme. None of them is consulted by the runtime engine,
and the engine is consulted by none of them. The boundary is: **anything that
decides what runs on a booted machine goes through `capability/`; anything that
records what has been proven about a device stays in the qualification
programme.**

## Reference table

| # | Reference | Location | Kind | Disposition |
|---|---|---|---|---|
| 1 | `_model_suitability()` | `tools/bunny-os/bunny_os/info.py` | user-facing collapsed label | **migrated**, deprecated for one release |
| 1a | `localModelSuitability` | `bunny-os hardware --json` | contract key | **deprecated**, marked in payload |
| 1b | `Local model assessment:` | `bunny-os hardware` text | user-facing | **removed** |
| 2 | priority bands `low`/`high` | `capability/manifest.py` (new) | internal vocabulary | **renamed** before landing |
| 3 | seven mode config keys | `capability/policy.py` | configuration | **refused with replacement named** |
| 4 | `classify()` statuses | `installer/hardware/preflight.py` | install-time support | **retained** |
| 5 | `minimum_requirements()` | `installer/hardware/preflight.py` | published minimums | **retained** |
| 6 | `TIERS` | `operations/hardware.py` | qualification evidence | **retained** |
| 7 | `MODE_REQUIREMENTS` | `operations/modes.py` | qualification scenarios | **retained** |
| 8 | `hardwareClass` | two schemas | free-text device label | **retained** |
| — | `low`/`balanced`/`high`/`ultra` mode code | anywhere | — | **none found** |

## What a user or operator must do

**Nothing.** No configuration file changes, no migration script, no data
conversion. There was no mode system to migrate away from.

An operator who writes one of the seven refused keys into a policy file gets an
error naming the replacement. A consumer reading `localModelSuitability` finds
`deprecated: true` and `replacedBy` in the same object.

## Verification

```text
python scripts/task.py validate          # includes the Capability manifests validator
python scripts/task.py test-capability   # 311 tests
python -m unittest discover -s tests/unit -t .
```

The absence of mode vocabulary in shipped manifests is asserted by
`tests/capability/test_manifest.py`; the absence of a mode or tier in any
generated document is asserted by
`tests/capability/test_machines.py::test_no_machine_is_given_a_mode_or_a_tier`.
