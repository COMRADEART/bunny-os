# Public beta accessibility review

Date: 2026-07-29. Result: **NO-GO. Accessibility is the least evidenced area in the project.**

## The honest position

Accessibility cannot be established by the kind of testing this project has done. Static checks confirm that settings exist, that a high-contrast theme is defined, that reduced motion and reduced transparency are honoured in source, and that text scaling is bounded. None of that tells you whether a person using a screen reader can install the operating system.

No essential workflow has been exercised with assistive technology. Not one.

## Essential workflows, none verified

| Workflow | State |
|---|---|
| Boot and reach the login screen with a screen reader | not tested |
| Complete installation with a screen reader | not tested; no installer exists |
| Enter a disk encryption passphrase at early boot | not tested |
| Complete first-run setup by keyboard only | not tested |
| Recover a system from recovery media | not tested |
| Read and act on a security warning | not tested |
| Use Bunny Shell with magnification | not tested |
| Complete an update and restart | not tested |

## What exists

`docs/ACCESSIBILITY.md` and `docs/phase-1/ACCESSIBILITY_CONFORMANCE_MATRIX.md` define the intended conformance. Settings for reduced motion, reduced transparency, high contrast and text scale between 75 and 200 percent are implemented and validated. `tests/accessibility` covers their source behaviour.

`enterprise/kiosk.py` refuses to let an organisation manage away a user's accessibility settings — `reducedMotion`, `reducedTransparency`, `theme` and `textScalePercent` are in `NEVER_MANAGEABLE_SETTINGS`. That is a real protection and it is tested.

## Findings

**Blocker — no assistive technology has ever been used against this system.** Orca, magnification, keyboard-only navigation and high-contrast rendering have not been exercised on a booted system.

**Blocker — early boot and recovery are unexamined.** Passphrase entry at boot and the recovery console are the two moments where an accessibility failure is most severe, because there is no alternative path and no way to ask for help. Neither has been tested.

**Major — no independent audit.** An accessibility review by the people who wrote the software is the weakest possible form of this review. An independent audit has not been commissioned.

## Recommendation

Do not run a public beta. A participant who depends on assistive technology and cannot complete installation, or cannot unlock their disk, has been handed a broken machine with no recourse. The project has no evidence that this would not happen.

This is the one review where the gap is not merely missing evidence but a genuine risk of harm to a specific group of users.
