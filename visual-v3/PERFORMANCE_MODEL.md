# Performance model

> BUNNY WAYLAND SHELL EXPERIMENT
>
> NOT RELEASE QUALIFIED
>
> DO NOT USE AS THE DEFAULT SESSION

The targets for this phase, and how each is defined. Measured results are in
`PERFORMANCE_REPORT.md`; this document is the specification the harness measures
against.

These are **prototype targets, not release guarantees**. A miss is recorded as a
miss.

| Metric | Target | Definition |
|---|---|---|
| Cold shell startup | < 3 s | Process start to the compositor's first presented frame |
| Top bar ready | < 2 s | Launching the top-bar component to its layer surface mapping |
| Command palette visible | < 150 ms | Launching the palette to its layer surface mapping |
| Quick Settings visible | < 150 ms | Launching Quick Settings to its layer surface mapping |
| Workspace transition | 60 FPS | Sustained frame rate during a workspace change |
| Idle CPU | < 1% | Compositor CPU over 10 s with no clients attached |
| Idle GPU | no continuous decorative rendering | No animation runs when nothing changed |
| Regular shell memory | < 450 MB | Compositor resident set size in Regular Mode |
| Character asset incremental use | < 100 MB | Additional resident memory attributable to the guide illustration |
| Shell restart | < 3 s | Compositor stop to the next compositor's socket being ready |

## Measurement rules

**A failed measurement is never a result.** If the harness cannot establish a
value it writes `unavailable` with the reason. It never substitutes an estimate,
and it never reports a target as missed because the measurement itself did not
happen. This rule was added after a harness bug reported every protocol as absent
when `wayland-info` had failed to run — the most damaging kind of false evidence
this phase could produce.

**Frame timing measures work, not pacing.** The recorded frame time is the cost
of producing a frame, before any wait for presentation, so it means "how long a
frame takes" rather than "how often we chose to draw one".

**A frame-rate sample needs enough frames.** In a nested run the host compositor
decides when our window is presented and `submit()` blocks until it does. Below
60 presented frames in a run, frame rate and idle CPU are treated as unmeasured,
because they would describe the host's scheduling rather than the shell's cost.

**The environment is stated with every number.** All V3 measurements were taken
on Mesa llvmpipe, a software rasteriser, inside WSL2. Numbers are not adjusted
for that, and the environment is recorded next to the result rather than used to
explain a miss away.

## Targets that assume something V3 does not have

Two targets are unreachable by construction in this prototype, and saying so is
part of the model rather than an excuse discovered afterwards:

- **150 ms for a panel to become visible** assumes resident chrome. V3 spawns a
  process, starts a Python interpreter, re-executes with `LD_PRELOAD` and
  initialises GTK. No toolkit reaches 150 ms from a cold process launch.
- **Idle GPU with no continuous decorative rendering** assumes damage tracking.
  V3 redraws the whole output every frame, so it cannot satisfy this target even
  when nothing is animating.

Both are recorded as V4 requirements.
