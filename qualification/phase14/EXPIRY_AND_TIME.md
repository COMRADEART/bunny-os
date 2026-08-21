<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Expiry, Time, and Revocation (Track I)

No clock is ever read. Every date in this layer is either a record's
own claim, an operator-stated evaluation date (`--as-of`), or a fixed
rehearsal constant. The commit is the tamper-evident time. Whenever
time semantics cannot be determined, evaluation fails closed.

## Expiry between cuts

A record carrying `expires_at` is `STANDING` or `EXPIRED` *per
evaluation date*, derived, never flipped by hand:

- an **authority assignment** past expiry confers nothing at later cuts
  (`standing_assignments`); acts it validly enabled at earlier cuts are
  not rewritten (PH14-I1, PH14-G8);
- a **risk acceptance** past expiry blocks rather than helps
  (Phase 13's rule; PH14-B5, PH14-I2);
- an **authorization** past its mandatory `expires_at` derives
  `EXPIRED` (Phase 13's rule).

The moment any expiring record exists among a decision's inputs, an
evaluation without `--as-of` refuses — the cut builder, the Phase 13
state derivations, and the assembly all enforce it (PH14-B7, PH14-I7).

## Revocation

- Revoking an authorization is a Phase 13 sealed record;
  `AUTHORIZED → REVOKED` holds with the record, `REVOKED` never returns
  to `AUTHORIZED`, and revocation outranks expiry — all Phase 13,
  re-exercised here through cuts (PH14-B6, PH14-H9).
- A revocation targeting an authorization that does not exist refuses:
  a revocation of nothing revokes nothing (PH14-I3).
- **Assignment revocation** has no real registry — introducing one is
  an owner decision. Phase 14 defines the record shape
  (`ASSIGNMENT_REVOCATION_FIELDS`) and evaluates it inside fixture
  universes only, so the mechanism is proven before the registry exists
  (PH14-G9).

## Time-consistency screening

`time_consistency_problems` flags, conservatively and fail-closed:

- **future-dated evidence** — a claimed observation later than its
  intake receipt conflicts with intake ordering (PH14-I4);
- **a revision received before its original** — a correction cannot
  precede what it corrects (PH14-I5);
- **an ambiguous time basis** — two dates for one act that disagree are
  not resolved by choosing the convenient one (PH14-I6);
- **unparseable dates** — undeterminable time is a problem, not a
  default.

Every flag derives `REQUIRES_HUMAN_DECISION`. The assembly reports
these as `timeFlags` and `orderingFlags` beside the decision inputs;
they are screening for the operator and the deciding authority, and
they never make anything more favorable.
