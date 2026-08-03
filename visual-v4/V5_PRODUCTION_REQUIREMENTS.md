<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# V5 production requirements

> **VISUAL OR SHELL DEVELOPMENT**
> **NOT RELEASE QUALIFIED**
> **DO NOT MERGE INTO MAIN WITHOUT AN EXPLICIT PRODUCTION INTEGRATION DECISION**
> **GNOME REMAINS THE SUPPORTED FALLBACK**

## V5 has not started, and cannot

D says V5 starts only after V4 produces a framework verdict. V4 has produced
`WITHHELD`, which is not one of the five allowed verdicts — it is the absence of
one. So no V5 branch exists, and none of these is created yet:

    visual/bunny-shell-v5-smithay-production
    visual/bunny-shell-v5-libmutter-production
    visual/bunny-shell-v5-dual-track
    visual/bunny-shell-v5-framework-search
    visual/bunny-desktop-v2-production

The branch name is chosen by the verdict, so choosing one now would be selecting
a framework by the back door.

## What V5 will have to deliver

Recorded here so the V4 measurements are taken with the right target in view.

Session and trust: stable session lifecycle, a trusted authentication boundary,
suspend/resume, crash recovery.

Portals and capture: portal integration, screen sharing, screenshots.

Input and accessibility: input methods including CJK, on-screen keyboard, Orca,
magnification, keyboard accessibility.

Display: GPU rendering, damage tracking, frame pacing, XWayland, pointer
constraints, multi-monitor, mixed scaling, hotplug.

Bunny surfaces: Regular Mode, Character Mode, Normal Layout, Compact Layout,
FocusMode, Bunny Assistant, Approval Center, privacy indicators, diagnostics,
update and recovery surfaces.

## D2, which constrains all of it

GNOME remains available until the Bunny production shell passes actual
installation, actual first login, repeated boot, repeated login, lock/unlock,
crash recovery, accessibility, screen sharing, input methods, GPU and
multi-monitor **on physical hardware**.

The Bunny shell remains non-default for the whole of V5 engineering. A shell that
works in a nested session is not a reason to merge it into the product image.

## D4

V5 exits only when a production-candidate shell architecture exists and can enter
the operating-system qualification process — which is a different and longer
process than V5 itself, governed by the protected release gates.
