<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Production requirements

> **VISUAL OR SHELL DEVELOPMENT**
> **NOT RELEASE QUALIFIED**
> **DO NOT MERGE INTO MAIN WITHOUT AN EXPLICIT PRODUCTION INTEGRATION DECISION**
> **GNOME REMAINS THE SUPPORTED FALLBACK**

What a Bunny compositor must do before it can be considered for the product
image, independent of which framework provides it.

## Non-negotiable

1. **The session survives its own failures.** A crashing shell component must not
   expose the desktop, and must not take the session with it.
2. **The authentication boundary is real.** Unlock goes through PAM. The lock
   surface cannot be bypassed by killing the lock client.
3. **Assistive technology works before launch, not after.** Orca navigates the
   shell, keyboard-only operation reaches every control, and the character layer
   never becomes duplicated content a screen reader must wade through.
4. **Input is not Latin-only.** Japanese, Chinese and Korean input reach real
   applications, with candidate popups positioned correctly.
5. **Screen sharing is consented and real.** Frames reach an external client only
   after explicit portal approval, and the privacy indicator reflects it.
6. **The GPU path is qualified on the hardware it will ship on.** Software
   rasterisation is a development fallback and never evidence.
7. **Multiple displays present.** Two outputs, mixed DPI, and hotplug, measured
   on real connectors.

## Character policy, which is architectural

The guide character is constrained by where it may be drawn, not by review:

- exactly one canonical guide character
- inside approved surfaces only
- never on the wallpaper, top bar, dock, or over applications
- **never on a password or authentication screen**
- success poses only after an observed success
- an approval pose never replaces approval controls
- reduced motion honoured

V3 made this structural rather than checked, and V4 keeps it that way: a surface
that is not approved has no code path that can draw the character.

## GNOME stays

GNOME remains the supported architecture and must not be removed before a
production replacement is qualified. The Bunny shell remains non-default for the
whole of V4 and V5. An experimental session must never become the default
session.
