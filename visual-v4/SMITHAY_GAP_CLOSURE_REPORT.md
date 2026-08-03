<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Smithay gap closure report

> **VISUAL OR SHELL DEVELOPMENT**
> **NOT RELEASE QUALIFIED**
> **DO NOT MERGE INTO MAIN WITHOUT AN EXPLICIT PRODUCTION INTEGRATION DECISION**
> **GNOME REMAINS THE SUPPORTED FALLBACK**

## Position

The V3 prototype is the starting point and its verdict stands unchanged:
**FEASIBLE WITH MAJOR GAPS**. V4 does not restate V3 measurements and does not
modify V3 evidence; V3 remains at
`f22212fe66ffa0c2b0b237c512a7eeb60ef25806`, which is the base of this branch.

`compositor/bunny-smithay-v4` has not been created. No V3 gap has been closed in
V4, and none is recorded as closed.

## The gaps V4 must close, and their state

| V3 gap | V4 gate | State |
|---|---|---|
| no real screen sharing | `screen-sharing-portal-pipewire` | `NOT_RUN` |
| no screenshot portal | `screenshot-portal` | `NOT_RUN` |
| no input-method implementation | `input-method-v2`, `input-{english,japanese,chinese,korean}` | `NOT_RUN` |
| no assistive-technology validation | `orca-session`, `atspi-navigation` | `NOT_RUN` |
| no XWayland server | `xwayland` | `NOT_RUN` |
| no pointer constraints | `pointer-constraints`, `relative-pointer` | `NOT_RUN` |
| no end-to-end PAM unlock | `pam-unlock`, `secure-session-lock` | `NOT_RUN` |
| chrome launch latency misses targets | C6 performance contract | `UNMEASURED` |
| screenshots did not capture mapped chrome | `resident-shell-chrome` | `NOT_RUN` |
| no GPU qualification | `gpu-rendering`, `linux-dmabuf` | `NOT_AVAILABLE` |
| no real multi-output presentation | `two-output-presentation`, `output-hotplug` | `NOT_AVAILABLE` |

## Why the implementation was not started

The last two rows are the reason.

Smithay's production backend is udev/DRM, and this host has no `/dev/dri`. A
Smithay compositor can be built and run nested here — V3 already proved that much
is achievable, with real GTK 4 clients connecting and nineteen globals observed —
but a nested run cannot close the two gaps that C7 makes mandatory.

So closing the other nine would still leave the arm disqualified, while producing
a compositor whose most safety-relevant properties are untested and whose
scorecard entry looks respectable. A high score beside an unmeasured mandatory
gate is the exact failure mode C8 is written to prevent, and building toward it
deliberately would be worse than not building.

## What the V3 measurements do and do not carry forward

V3 measured, and these remain true of the V3 code: the compositor starts, real
GTK 4 clients connect and map, nineteen Wayland globals are advertised, Bunny
chrome maps as layer surfaces, Regular Mode and Character Mode both work, crash
recovery is bounded, GNOME remains available, and 197 tests pass.

None of that transfers to a V4 gate. Nineteen advertised globals is a protocol
advertisement, and the evidence rules reject protocol advertisement presented as
functionality. The V4 contract asks whether frames reach a PipeWire consumer,
whether Japanese text reaches an application, and whether Orca navigates the
shell — none of which V3 measured.
