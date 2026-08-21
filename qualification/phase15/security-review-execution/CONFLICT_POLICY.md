<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Conflict policy — conflicts stay visible

One policy, inherited whole from Phases 11, 13, and 14: **nothing is
averaged, nothing is voted, the effective state pending resolution is
the most blocking one, and a conflict that needs interpretation derives
a human-decision requirement.** Phase 15 adds executed demonstrations,
not new rules.

## A. Two reviewers disagree

```text
APPROVED + BLOCKED → CONTRADICTORY_CONCLUSIONS → RESOLUTION_REQUIRED
```

Phase 11's `classify_conflict` records the disagreement, both
submissions survive verbatim, the effective assessment is the most
blocking (`BLOCKED`), and the receipt state is
`CONFLICT_REQUIRES_DECISION`. The only exits are the recorded outcome
vocabulary (`ADDITIONAL_REVIEW_REQUIRED`, `REMEDIATION_REQUIRED`,
`BLOCKED`) — a governance rule recorded through the Phase 13 mechanism,
never an inference. There is no "two PASS beats one FAIL" anywhere in
this repository, and the guard suite greps for none appearing.

## B. Favorable internal interpretation

A local repository operation — a passing test, a rerun, a re-derivation,
an internal JSON asserting a friendlier reading — **cannot overrule a
real unfavorable external finding**. Enforced structurally: the register
derives from the intake bytes, so an unfavorable accepted submission
keeps deriving its unfavorable consequence no matter what runs locally;
and the Phase 14 resolution wall raises `BoundaryViolation` if any
resolution would make the effective assessment *more favorable* than
the most blocking observation.

## C. Expired favorable authority

A favorable record (risk acceptance, authorization, assignment) with
`expires_at` confers nothing at any cut past its expiry. Expiry is
evaluated only at an explicit as-of boundary — no clock is read — and
once any expiring record exists, every standing evaluation without an
explicit as-of refuses. The record itself is never edited; what changes
is the evaluation, per cut.

## D. Revoked authority

Revocation affects cuts at or after its effective boundary. An earlier
sealed cut re-derives exactly as sealed — demonstrated by re-assembling
that cut's *inputs*, the record set that existed then — and every later
cut observes the revocation and derives `REVOKED`. No sealed record is
rewritten in either direction.

## E. Conflicting dispositions on one Critical

When accepted submissions classify the same Critical incompatibly (one
applicable-ish, one `NOT_APPLICABLE`), the register overlay derives
`EVIDENCE_CONFLICT` and holds the row at `UNDER_REVIEW` — the
most-blocking effective assessment wins pending an established, valid,
recorded disposition. Specifically refused:

* averaging severities or "meeting in the middle";
* majority vote among reviewers;
* count-based favorability of any kind;
* the repository selecting the favorable interpretation because it is
  local, newer, or better formatted.

## Where each rule is enforced

| Rule | Owner | Mechanism |
| --- | --- | --- |
| most-blocking effective assessment | Phase 11 | `ASSESSMENT_SEVERITY` ordering in `classify_conflict` |
| conflict resolution vocabulary | Phase 11 | `CONFLICT_OUTCOMES`, `validate_conflict_resolution` |
| no favorable resolution | Phase 14 | the resolution wall (`BoundaryViolation`), with its injected-stub negative control |
| per-finding conflict hold | Phase 11 | `_evidence_states` → `EVIDENCE_CONFLICT` at `UNDER_REVIEW` |
| expiry / revocation per cut | Phase 13 (evaluated by 14/15 per as-of) | `expires_at` / revocation records; `--as-of` mandatory |
| human decision surfacing | Phase 15 | receipt state `CONFLICT_REQUIRES_DECISION`; status output names the conflict |

Phase 15's contribution is the last row: making the standing conflict
visible in the receipt register and `EXTERNAL_STATUS.json` until an
authorized process resolves it. Visibility, not resolution — the
repository records decisions; it does not make them.
