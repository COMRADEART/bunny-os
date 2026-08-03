# Performance report

> BUNNY WAYLAND SHELL EXPERIMENT
>
> NOT RELEASE QUALIFIED
>
> DO NOT USE AS THE DEFAULT SESSION

## The environment, stated first

- Host: Fedora Linux 44 on WSL2, nested under WSLg
- Renderer: **Mesa llvmpipe (software rasteriser)**
- Hardware accelerated: **False**

These are software-rendering numbers. They are the honest result for this host and are not adjusted for it.

## Results

| Metric | Target | Measured | Verdict |
|---|---|---|---|
| cold shell startup | 3000.0 ms | 879.4 ms | **meets** |
| top bar ready | 2000.0 ms | 3290.7 ms | **misses** |
| command palette visible | 150.0 ms | 3341.2 ms | **misses** |
| Quick Settings visible | 150.0 ms | 3193.9 ms | **misses** |
| workspace transition | 60.0 fps | — | not measured |
| idle CPU | 1.0 % | — | not measured |
| regular shell memory | 450.0 MB | 209.1 MB | **meets** |
| character asset incremental use | 100.0 MB | — | not measured |
| shell restart | 3000.0 ms | 3070.8 ms | **misses** |

**2 met, 4 missed, 3 not measured.**

## Why frame rate and idle CPU are not reported

only 2 frames were presented during the run; the nested backend blocks in submit() until the host compositor schedules the window, so frame rate and idle CPU could not be attributed to the shell.

Reporting a frame-rate miss from that sample would be as dishonest as reporting a pass. Both numbers need a DRM/KMS session on real hardware, where the compositor owns the page flip instead of waiting for a host to schedule it.

## The misses

- **top bar ready**: 3290.7 ms against a 2000.0 ms target.
- **command palette visible**: 3341.2 ms against a 150.0 ms target.
- **Quick Settings visible**: 3193.9 ms against a 150.0 ms target.
- **shell restart**: 3070.8 ms against a 3000.0 ms target.

The chrome-visibility misses share one cause and it is architectural, not incidental. Each panel is a separate process that starts a Python interpreter, imports PyGObject, re-executes itself with `LD_PRELOAD` set for gtk4-layer-shell, initialises GTK, and only then maps a surface. Three seconds is what that costs on this host. A 150 ms target is unreachable for a cold process launch by any toolkit — the target assumes resident chrome, and V4 must keep the panels running and toggle visibility instead of spawning them.

## What these numbers are worth

Startup and memory are real results and both are comfortable: the compositor reaches its first frame well inside the target and uses less than half the memory budget, on a software rasteriser. They would only improve with a GPU.

The chrome-visibility numbers are real measurements of the wrong architecture, and the fix is known. The frame-rate and idle-CPU numbers are not results at all in this environment and are reported as unmeasured.
