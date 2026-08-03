<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Bunny Shell V4 framework closure report

> **VISUAL OR SHELL DEVELOPMENT**
> **NOT RELEASE QUALIFIED**
> **DO NOT MERGE INTO MAIN WITHOUT AN EXPLICIT PRODUCTION INTEGRATION DECISION**
> **GNOME REMAINS THE SUPPORTED FALLBACK**

## Verdict: none

V4 was to choose between Smithay and libmutter. It has not, and this branch does
not pretend otherwise.

```text
$ python visual-v4/tools/v4.py report
VERDICT: WITHHELD
$ echo $?
2
```

C9 permits five verdicts. `WITHHELD` is not a sixth — it is the absence of one.
The harness computes it because both arms have all eight mandatory gates
unsatisfied, and C7 forbids selecting a framework while any mandatory gate is
unqualified.

Base: `f22212fe66ffa0c2b0b237c512a7eeb60ef25806`, the V3 head. Not `main`.

## What was built

A contract and the machinery to hold work to it — not an implementation.

| Artefact | What it is |
|---|---|
| `visual-v4/contract/shared-test-contract.json` | 31 gates, 8 mandatory, 2 arms, the C8 weights |
| `visual-v4/contract/measured-results.json` | every gate's state and why it is not `PASS` |
| `visual-v4/tools/v4.py` | validates, scores, derives the verdict |
| `visual-v4/tools/probe_environment.sh` | measures what the host can support |
| `visual-v4/tools/render_reports.py` | generates the matrices from the data |
| `tests/visual_v4/test_framework_closure.py` | 25 tests, mostly mutation tests of the guards |

`compositor/bunny-smithay-v4` and `compositor/bunny-mutter-v4` do **not** exist.

## Why no arm was implemented

Two of the eight mandatory gates cannot be measured on the available host, and
they are blocked by absent hardware rather than absent effort.

Measured, in `visual-v4/evidence/environment-probe-wsl2-fedora44.txt`:

```text
dev-dri: ABSENT
  consequence: no KMS. No page-flip, no vblank, no connectors.
renderer: llvmpipe (LLVM 22.1.8, 256 bits)
  classification: SOFTWARE RASTERISER
```

`gpu-rendering` and `two-output-presentation` are consequently `NOT_AVAILABLE`
for both arms, along with `linux-dmabuf`, `frame-pacing` and `output-hotplug`.

Building either compositor here would have closed some of the other
twenty-six gates and left the arm disqualified anyway — while producing a
scorecard entry that looked like progress. C8 exists to stop a number
outweighing an unmeasured mandatory gate, and building toward that number
deliberately would be worse than not building.

## The state of every gate

Nothing is `PASS`. Nothing is `FAIL` either, because nothing was measured.

| Arm | States |
|---|---|
| Smithay | `NOT_RUN` × 26, `NOT_AVAILABLE` × 5 |
| libmutter | `NOT_IMPLEMENTED` × 26, `NOT_AVAILABLE` × 5 |

Scores: Smithay 0, libmutter 0, of 100.

`NOT_RUN` and `NOT_AVAILABLE` are distinguished deliberately. Both score zero and
both block, so the harness treats them identically — but the first is cleared by
doing the work and the second only by different hardware. Collapsing them would
hide that part of V4 is not waiting on anybody's effort.

## How this branch resists being walked forward

The rules that matter are enforced by code and tested by breaking them, rather
than left to a reader's diligence:

- a `PASS` without an evidence reference is refused as malformed
- a duplicate result, a missing result, an unknown state, an invented gate or a
  dropped arm are all refused
- the score counts `PASS` and nothing else; `PARTIAL` earns zero
- `verdict()` checks mandatory gates before it looks at any score
- `report` exits 2 while the verdict is withheld, so a caller cannot read
  "nothing measured" as "nothing wrong"

One test asserts the property the whole contract exists for: an arm passing every
gate except one mandatory one still scores in the seventies and is still refused.

## Stop condition

C12 is **not met**. Of its requirements, none of the following has happened: both
arms measured, real Orca run, real CJK input run, real PipeWire screen sharing
run, real PAM lock/unlock run, GPU rendering measured, two outputs presenting
frames, screenshots showing real mapped Bunny chrome, a scorecard citing
evidence, or an allowed verdict selected.

What is done: the branch exists, is pushed, and has a draft PR that must not be
merged.

V4 therefore remains **open**. It needs a Linux host with a real DRM device and
two real outputs; everything here is written to run there unchanged.

## Position unchanged

GNOME remains the supported architecture. The native shell remains experimental
and non-default. The V3 verdict of **FEASIBLE WITH MAJOR GAPS** stands, and V3
evidence at `f22212f` is untouched.

Stable release remains **NO-GO**. Pilots remain **BLOCKED**. Nothing on this
branch bears on either, and nothing here may be cited as qualification evidence.
