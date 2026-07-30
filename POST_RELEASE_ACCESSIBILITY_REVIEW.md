# Post-release accessibility review

Date: 2026-07-29. Status: **not applicable; no release has been published.**

## Current position

No release, no users, and — more importantly — **no assistive technology has ever been used against this system at any point in its development.** Not in Phase 1, not in Phase 2, not since. That is the honest state and it does not improve by being restated carefully.

`PUBLIC_BETA_ACCESSIBILITY_REVIEW.md` sets out the same gap in detail. This document records what a post-release review would have to establish and why the project is not in a position to conduct one.

## What this review will examine, once there is a release

| Area | Question it must answer |
|---|---|
| Essential workflows | Can each be completed with a screen reader, by keyboard alone, and under magnification |
| Early boot | Can a disk encryption passphrase be entered without sight |
| Installation | Can the system be installed with assistive technology |
| Recovery | Can a broken system be recovered with assistive technology |
| Security warnings | Are they perceivable and actionable through every supported modality |
| Regressions | Did any update degrade an accessibility behaviour that previously worked |
| Reports | What did users who depend on assistive technology actually report |
| Conformance | Measured against `docs/phase-1/ACCESSIBILITY_CONFORMANCE_MATRIX.md`, with failures named |

## Why the two boot-time rows matter most

Passphrase entry at early boot and the recovery console are the only two moments where there is no alternative path, no second device to fall back to, and no way to ask the system for help. An accessibility failure anywhere else is an obstacle. An accessibility failure in those two places locks a person out of their own computer.

Neither has ever been tested.

## What exists

Settings for reduced motion, reduced transparency, high contrast and text scaling from 75 to 200 percent, all implemented, validated and covered by source tests. A conformance matrix defining the intended target. And a Phase 7 protection worth noting: `NEVER_MANAGEABLE_SETTINGS` prevents an organisation from managing away a user's accessibility settings, which is enforced in code and tested.

None of that is evidence that the system is usable with assistive technology.

## Independence

No independent accessibility audit has been commissioned. A self-review by the people who wrote the software is the weakest possible form of this particular review, because the failure mode is precisely not noticing what you never needed.

## Recommendation

Commission an independent audit before any release reaches users, and treat the two boot-time workflows as blocking rather than as findings.
