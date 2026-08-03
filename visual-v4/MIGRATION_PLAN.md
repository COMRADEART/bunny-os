<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Migration plan

> **VISUAL OR SHELL DEVELOPMENT**
> **NOT RELEASE QUALIFIED**
> **DO NOT MERGE INTO MAIN WITHOUT AN EXPLICIT PRODUCTION INTEGRATION DECISION**
> **GNOME REMAINS THE SUPPORTED FALLBACK**

A migration plan needs a destination, and V4 has not selected one. What follows
is therefore the plan for **reaching a verdict**, not for migrating to a
framework. The framework-specific migration is written once C9 produces an
allowed verdict, and not before.

## Step 0 — a host that can conclude

Nothing else on this list can start without it. Required: a Linux machine with a
real DRM device (`/dev/dri` present), hardware GL, and two real outputs.

Re-run `visual-v4/tools/probe_environment.sh` there. It reclassifies the five
environment-blocked gates automatically, and its verdict line states whether the
host can qualify a compositor at all.

## Step 1 — the Smithay arm

Create `compositor/bunny-smithay-v4`, extending V3 without modifying V3 evidence.
Close the nine `NOT_RUN` gaps in `SMITHAY_GAP_CLOSURE_REPORT.md`, then measure the
two that needed hardware.

Record each result in `visual-v4/contract/measured-results.json` with an evidence
reference. The harness refuses a `PASS` without one, so this is enforced rather
than remembered.

## Step 2 — the libmutter arm

Create `compositor/bunny-mutter-v4` as the smallest real downstream Bunny shell,
and measure the same 31 gates. Do not carry any result across from GNOME Shell:
C3 forbids it, and the harness has no mechanism for it.

## Step 3 — the shared application matrix

C4's fourteen applications against both arms, recording launch, mapping,
keyboard, pointer, resizing, maximise, fullscreen, modal dialogs, clipboard,
drag-and-drop, portals, notifications, fractional scaling, screen sharing and
crash behaviour.

## Step 4 — the verdict

`python visual-v4/tools/v4.py report` computes it. If both arms qualify it
returns `CONTINUE_DUAL_TRACK`; if one does, it selects that one; if neither does,
it withholds. There is no step where somebody chooses.

If the measurements show the native shell cannot satisfy the mandatory gates,
`NATIVE_SHELL_NOT_READY` is an allowed and expected outcome, and Bunny Desktop V2
on GNOME becomes the supported architecture. That is Final Program State 3, not a
failure of the programme.

## Throughout

GNOME remains installed, supported and default. The Bunny shell stays
non-default for the whole of V4 and V5. No prototype package is a release
artifact, and no V4 branch merges into `main` without an explicit production
integration decision.

## Character assets

Before any public packaging, D3 applies: identify the rights holder for the
reference image, record permission for derivative assets, assign a project
licence, record generation provenance, confirm redistribution rights, and verify
no unlicensed third-party character is embedded. Until that is complete the
character assets are development-only and are excluded from public distributions.
