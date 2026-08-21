# Performance follow-up

## Status: **NOT_RUN**, and runnable — which is not the same as blocked

Every other open item in Phase 6 needs a person or a machine this project does
not have. This one does not. It needs a VM boot and a desktop session, and it
was not run. That distinction is recorded rather than blurred, because a
`NOT_RUN` that is nobody's fault reads very differently from one that is.

---

## 1. The question, as it stands

A **1.27 percentage-point** unexplained regression in `gnome-shell` idle CPU:

| | CPU | RSS |
| --- | ---: | ---: |
| Comparator `7edd3fd` | 0.80 % | 391.2 MiB |
| Subject artifact, 30 s window | **2.07 %** | 387.4 MiB |

Memory did not move. Only CPU did.

**The poller hypothesis is refuted and must not be resurrected without new
evidence.** `/proc` reads were measured at **0.006 %** of one core — two hundred
times too small to account for it. `interval()` is instrumented per named poller
and deliberately unused.

The surviving candidate is **rendering and redraw cost** under the software
renderer.

---

## 2. What to measure

Conditions first, because they decide whether the numbers mean anything.

* **The same instrument as the baseline.** The comparator is
  `qualification/design/performance.json` at `7edd3fd`, measured by the `probe
  performance` verb: CPU as the delta of `utime+stime` clock ticks from `/proc`
  over a fixed idle interval. `qualification/voice-release/.../cpu-idle.json` is
  **not** the comparator — different instrument, different window, different
  workload — and comparing against it produces a number true of neither.
* **Hidden and visible measured separately, never averaged.** This is the whole
  experiment. If redraw explains the regression, the difference between
  Companion-hidden and Companion-visible idle is where it lives; averaging them
  destroys the only signal that could answer the question.
* **The renderer named alongside every figure.** Under QEMU that will be
  llvmpipe, and every number must be labelled as such.

| # | Measurement | Why |
| --- | --- | --- |
| 1 | idle CPU, Companion **hidden** | isolates shell-only cost |
| 2 | idle CPU, Companion **visible** | the difference from 1 is the Companion's redraw cost |
| 3 | idle CPU, Companion visible, per renderer mode | attributes cost to a mode rather than to the feature |
| 4 | redraw frequency (frame callbacks per second, idle) | a redraw that fires when nothing changed is the cheapest possible explanation |
| 5 | CPU per redraw | separates "too often" from "too expensive" |
| 6 | frame scheduling — is the loop paced by the host frame callback? | a nested compositor that self-paces dies; one that over-schedules burns CPU |
| 7 | the same set at `7edd3fd` | the comparator has to be re-measured on the same host, or the delta includes the host |

Measurement 7 is easy to skip and is the one that matters most. The 1.27 points
were taken from a record made on a different day; part of the gap may be the
host rather than the change.

---

## 3. Rules for attributing it

* **Do not attribute cost until measurement supports attribution.** The poller
  hypothesis was plausible, specific, and wrong by a factor of two hundred.
* **A number without a renderer string cannot be compared with anything.**
* **llvmpipe measurements may never be presented as real-GPU results.** The
  hardware journey `H2-renderer` carries the same rule; if it ever runs, its
  measurement set is deliberately the same one, so the two are comparable.
* **Measure interleaved or not at all** where two configurations are being
  compared on one host. Sequential runs pick up drift and attribute it to the
  change.

---

## 4. Why it did not run

Phase 6 bound its evidence to `e906a48793d7` and built no new artifact, so §16's
own condition — *"once a new build is justified"* — was not met. The measurement
would also still be an llvmpipe measurement, which §8 forbids using for a
real-GPU claim.

Neither of those makes it worthless: measurements 1 to 5 would locate the cost
inside the VM even under software rendering, and that is a genuine result about
where to look next.

**It is recorded as NOT_RUN and as engineering work outstanding, not as
blocked.** It is not a release gate and does not appear in the gate matrix.
