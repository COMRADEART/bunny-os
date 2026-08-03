# Multi-display report

> BUNNY WAYLAND SHELL EXPERIMENT
>
> NOT RELEASE QUALIFIED
>
> DO NOT USE AS THE DEFAULT SESSION

## The honest headline

**No multi-display configuration was exercised at runtime.** The nested winit
backend provides exactly one output, and the measurement host is a WSL2 session
with no DRM/KMS access, so a second output could not be created.

What was verified is the *layout model* the compositor uses to decide multi-
display behaviour, through unit tests that run without a display. That is
genuine evidence about the logic and no evidence at all about the hardware path.
The table below never says "works" where it means "the model says so".

## The requested matrix

| Configuration | Runtime result | Model result | Evidence |
|---|---|---|---|
| One 1920×1080 display | Ran; the nested output was 2560×1600 at scale 1.0 | Consistent | **observed** (one output, not this resolution) |
| One 4K display at 200% | Not run | 3840×2160 at scale 2.0 → 1920×1080 logical | **inferred** from unit test |
| Dual 1080p displays | Not run | Two outputs tracked; second added and removed cleanly | **inferred** |
| Mixed 1080p and 4K | Not run | `has_mixed_scaling()` detects the mismatch | **inferred** |
| Portrait secondary display | Not run | Rotated90 swaps logical dimensions to 1080×1920 | **inferred** |
| Display hotplug | Not run | `OutputLayout.add` replaces rather than duplicates | **inferred** |
| Display removal | Not run | `remove` returns false the second time; no ghost output | **inferred** |
| Laptop plus external display | Not run | Primary is the first output added — the built-in panel | **inferred** |

## Stated policies

These are decisions, recorded so they cannot drift into accident.

**Workspaces are global across outputs.** Switching to workspace 2 switches every
output at once, matching GNOME rather than the per-output model some tiling
compositors use. `WorkspaceScope::PerOutput` exists in the type but is not
implemented, so the choice is visible in the code rather than implied by it.

**The top bar and dock live on the primary output only.** The primary output is
the first one added, which for a laptop plus an external display is the built-in
panel — the shell chrome stays where the user's hands are. A dock on every output
competes with itself for the running-application indicators.

**Logical sizes round up.** A 1921-pixel-wide output at scale 1.5 is 1281 logical
pixels, not 1280. Rounding down leaves a strip of the display that no surface
covers, and that strip is exactly how a lock screen ends up with an uncovered
edge.

## Lock-screen coverage

The requirement that a lock screen covers every active output is the one
multi-display property that was verified in depth, because it is the one whose
failure is a security defect rather than a cosmetic one.

Verified by unit tests in both the Rust and Python implementations:

- Locking with two outputs and attaching one surface leaves the lock
  **incomplete**, and the uncovered output still refuses to present the desktop.
- Hotplugging an output while locked immediately returns the lock to
  **incomplete** and lists the new output as uncovered — and that output does not
  show the desktop in the meantime.
- Removing an uncovered output **completes** the lock, because an output that no
  longer exists needs no surface.
- The lock client creates one surface per monitor, iterating
  `Gdk.Display.get_monitors()`, so an output with no surface is structurally
  impossible rather than merely unlikely.

The renderer backs this: while locked, only lock surfaces are composed at all.

## What V4 must measure

Everything in the table above, on real hardware, plus:

- Cursor movement across output boundaries with different scales.
- Window placement when an output is removed while windows are on it.
- Character Mode layout on a portrait secondary display.
- Panel and dock behaviour when the primary output is unplugged.
- Fractional scaling with a real GPU rather than a software rasteriser.
