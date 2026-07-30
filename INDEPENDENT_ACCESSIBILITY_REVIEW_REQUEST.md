<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Independent accessibility review request

**Status: prepared and not sent. No reviewer has been identified and no completion
date exists.**

The request itself is `reviews/accessibility/REQUEST.md`.

## What is being asked for

Whether a user of each named assistive technology can complete **seventeen
essential workflows unaided**, and what happens when they cannot.

Bunny OS has **zero** runtime accessibility evidence. No assistive-technology
session has ever been driven against it.

## Why this review and no other route

This is the review where being wrong harms a person rather than leaving a box
unticked. An inaccessible encryption prompt or recovery tool locks somebody out of
their own machine, permanently, with no recourse.

Static accessibility tests pass and are explicitly not sufficient:
`release/matrix.py` refuses a source-inspection pass in the accessibility matrix,
and `release/accessibility.py` refuses a `PASS` with no recorded steps and rejects
`source-inspection` as an environment.

The project can drive its own flows and should. It cannot be the party that decides
its own interfaces are usable by people whose needs it does not share, and
`evaluate_evidence` requires `independentReviewComplete` even when all seventeen
flows pass.

## What the request contains

| Section | Substance |
|---|---|
| Exact scope | 17 workflows in priority order, with why each matters |
| Commit | evidence baseline `80df25b09f65…` |
| Artifacts | the evidence plan, the evidence record, `installer/`, `shell/`, `ui/`, the current 0-of-14 report, and an explicit statement of what is *not* provided |
| Threat model | 6 users the project must not exclude, and the failure that matters most |
| Questions | 9, beginning with the load-bearing one |
| Expected report format | per-workflow fields, plus a signed record |
| Severity model | 5 levels; `critical` is defined as "cannot own or recover the machine" |
| Expected independence statement | 3 things, plus an invitation to say if an operator is a daily user of the technology |
| Confidentiality | **not embargoed** — an accessibility failure is not a vulnerability |
| Prohibited claims | 5, including any conformance badge and any pass inferred from source inspection |

## The load-bearing question

> Can a screen-reader user complete an encrypted installation unaided, including
> entering and confirming a passphrase and recording a recovery key?

**Nobody knows.** That is the honest position and it is why the row blocks.

## The seven flows whose failure blocks a release

`keyboard-only-installation`, `screen-reader-installation`, `disk-selection`,
`encryption`, `recovery-key-display`, `login`, `recovery`.

Each is required to own or recover the machine. No other flow's success compensates
for one of these failing, and `release/accessibility.py` reports them separately as
`criticalUnresolvedFlows`.

## What the project cannot supply

Two of the seventeen — installer screen reader and keyboard-only installation —
happen before an installed system exists and need an installer ISO plus either
physical hardware or an interactive VM session. The project has neither built the
ISO nor acquired the hardware.

If the reviewer can supply the environment, that is welcome. If not, those two are
recorded as not run rather than inferred from the others.

## What it would unblock

| Unblocked | Currently |
|---|---|
| The `accessibility-evidence` candidate prerequisite | `PENDING_EXTERNAL_REVIEW` — 17 of 17 not run |
| The `Accessibility` evidence category | `NOT_RUN` |
| The Accessibility protected approval | pending |

## An honest report of seventeen failures is the useful outcome

There are no users yet. Nothing is at stake in the answer being bad, and everything
is at stake in it being wrong.

## Intake

Place the report in `reviews/accessibility/`, record the signed
`IndependentReviewRecord`, populate
`operations/data/accessibility-evidence.json` with the per-flow results, and run:

```text
python scripts/release.py validate-accessibility-evidence
python scripts/release.py validate-independent-reviews
```

A flow driven twice keeps its **worst** result: a later pass with a different
assistive technology does not erase an earlier failure. Media involving a person is
accepted only with recorded consent and a completed redaction pass.
