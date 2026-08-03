# Bunny Desktop V2 performance specification

> VISUAL PROTOTYPE ONLY · NOT RELEASE QUALIFIED · DO NOT MERGE INTO MAIN

## Interaction targets

| Interaction | Target |
| --- | ---: |
| Command Palette input-ready | <150 ms |
| Quick Settings input-ready | <150 ms |
| Assistant panel input-ready | <250 ms |
| Visual-mode reflow | <300 ms |
| Idle CPU | Effectively zero |

Shell state updates use a `Gio.FileMonitor`; no timer-based polling loop is
allowed. The wallpaper is static. Character art has no continuous animation.
Regular Mode creates no asset loader. Character Mode loads only the derived
active pose and retains at most three recent `Gio.FileIcon` handles; returning
to Regular Mode clears the cache.

`PerformanceRecorder` keeps at most 32 in-memory measurements and performs no
network or disk writes. `performance_audit.py` records deterministic build and
static-source checks. Live GNOME timings require a Linux nested or disposable
preview session and must never be inferred from deterministic rendering time.

