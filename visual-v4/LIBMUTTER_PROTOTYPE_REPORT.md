<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# libmutter prototype report

> **VISUAL OR SHELL DEVELOPMENT**
> **NOT RELEASE QUALIFIED**
> **DO NOT MERGE INTO MAIN WITHOUT AN EXPLICIT PRODUCTION INTEGRATION DECISION**
> **GNOME REMAINS THE SUPPORTED FALLBACK**

## Position

`compositor/bunny-mutter-v4` has not been created. Every gate for this arm is
`NOT_IMPLEMENTED`, except the five the host blocks outright, which are
`NOT_AVAILABLE`.

## What this arm is required to be

The smallest **real downstream Bunny shell** built on libmutter. Not GNOME Shell
with a theme, and not a GNOME Shell extension — V1 and V2 already explored the
extension route and it is a different architecture with different limits.

C3 is explicit that GNOME Shell capabilities must not be assumed to transfer to a
Bunny downstream shell, and that the actual downstream prototype is what gets
tested. That instruction is the whole reason this arm is not obviously the
cheaper one.

libmutter's attraction is that screen sharing, portals, input methods, Orca,
magnification, XWayland and multi-monitor already work — *in GNOME Shell*. None
of that is evidence that they work in a different downstream compositor built on
the same library, because the downstream is where the session lifecycle, the lock
surface, the portal backend wiring and the accessibility bus registration
actually live. Those are precisely the things a Bunny shell would be replacing.

So this arm is not cheaper than the Smithay arm by the amount GNOME already does.
It is cheaper by however much of that survives being rehosted, and that quantity
is unknown until it is measured. Estimating it from GNOME Shell's behaviour would
be assuming the conclusion the arm exists to test.

## Prerequisites not present on this host

`mutter`, `libmutter-16` / `libmutter-15` development files, and `gnome-shell`
are absent. They are installable from Fedora, so this arm's gates are recorded
`NOT_IMPLEMENTED` — a statement about this branch, not about the host.

## Why building it here would not have concluded anything

The five environment-blocked gates apply to this arm identically. A libmutter
compositor with no DRM device cannot qualify GPU rendering or two-output
presentation either, because those gates are blocked by the absence of hardware
rather than by anything about the framework.

Both arms are therefore disqualified on this host for the same two reasons, which
is also why the comparison between them is currently empty rather than close.
