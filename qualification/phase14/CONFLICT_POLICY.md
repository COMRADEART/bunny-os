<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Conflict Policy (Track C)

One policy, across every external workstream, composed from the
machinery Phases 11 and 13 committed:

1. **Nothing is averaged.** There is no "more PASS than FAIL" anywhere
   in this repository, and Phase 14 adds none.
2. **The effective state is never more favorable because a conflict
   exists.** `most_blocking` wraps Phase 13's classifier and
   additionally *refuses* any result in which a favorable assessment
   became effective through a conflict — a guard on the guard.
3. **Conflicts that need interpretation derive
   `REQUIRES_HUMAN_DECISION`**, naming the domain authority that must
   decide (security → `AUTH-SECURITY-OWNER`, hardware →
   `AUTH-HARDWARE`, alpha → `AUTH-ALPHA-PROGRAM`, release →
   `AUTH-RELEASE`). Only a sealed resolution by that assigned authority
   changes the outcome.

## The demonstrated cases

| Case | Outcome | Scenario |
| --- | --- | --- |
| Security: `ACCEPTED_RISK` beside `UNRESOLVED` | the more blocking state (`UNRESOLVED`) stands; human decision required | PH14-C1 |
| Hardware: one machine passes, another fails | both preserved per machine, per dimension; **no** "SUPPORTED ON PCS" | PH14-C2, PH14-F6 |
| Alpha: successes beside an unreproduced severe issue | the issue stays open; `NOT_REPRODUCED` is about attempts, never validity | PH14-C3 |
| Signing: valid evidence, wrong artifact | `DOES_NOT_APPLY`; moves no gate | PH14-C4 |
| Approval: valid decision, unauthorized role | contributes nothing; the required authority is named | PH14-C5 |
| Authorization: four of five floor sources | `AUTHORIZED` impossible; the absent source named | PH14-C6 |
| Any: favorable and unfavorable observations | `CONFLICT → REQUIRES_HUMAN_DECISION`, unfavorable effective | PH14-C7 |

## Hardware is special only in shape

Machine results never merge: `hardware_effective_state` keeps every
per-machine, per-dimension status forever, marks divergence without
escalating it (a machine result describes that machine), and its
aggregate claim is structurally `null`. `hardware_claims` — the only
way to ask for an aggregate — raises: no pre-existing policy defines an
aggregate hardware-support claim, and a finite set of machines proves
nothing about machines outside it.
