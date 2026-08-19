<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Decision Assembly (Track H)

`assemble_decision(universe, as_of)` gathers — and never invents — the
inputs of the release decision, then derives the candidate state
through Phase 13's own most-restrictive-first ladder. It is an
orchestration layer over Phases 9–13, and it contains no favorable
shortcut: the only `AUTHORIZED` it can report is a validated external
authorization record that already exists.

## What it assembles

artifact identity · the sealed evidence cut · the authorization floor
(five sources) · the security gate state · Alpha sufficiency under the
active policy · blocking conditions (adverse only block; absence keeps
pending) · standing authority (assignments filtered by expiry and
revocation at this cut) · separation-of-duties violations · risk
acceptances with per-cut states · authorizations with per-cut states ·
revocations · time and ordering flags · the favorable-evidence rows.

An authorization claiming `AUTHORIZED` that was cut against **this**
ledger is put through the full Phase 13 validation (floor, assigned
authority, separation, drill check, signer/approver, gate, sufficiency,
blocking, risks, cut match) — refusal is recorded with its reasons. One
cut against an earlier ledger is honored as the sealed record it is,
with its state derived from revocations and expiry, exactly as
Phase 13's status derivation treats it.

## The demonstrated scenarios

| # | Universe | Outcome | Scenario |
| --- | --- | --- | --- |
| 1 | the real repository, read-only | `EVIDENCE_PENDING` / `REQUIRES_MORE_EVIDENCE` — equal to the committed Phase 13 status | PH14-H1 |
| 2 | empty fixture universe | not authorized | PH14-H2 |
| 3 | four of five floor sources | not authorized; absent source named | PH14-H3 |
| 4 | five records, one bound to other bytes | not authorized; the mismatched source counts as absent | PH14-H4 |
| 5 | everything but security unresolved | `SECURITY_REVIEW_PENDING` | PH14-H5 |
| 6 | everything but no sufficiency policy | `SUFFICIENCY_UNDEFINED` | PH14-H6 |
| 7 | active policy, insufficient evidence | `REQUIRES_MORE_EVIDENCE` | PH14-H7 |
| 8 | every mechanical requirement satisfied by fixtures | `AUTHORIZED` — **inside the isolated fixture universe only** | PH14-H8 |
| 9 | scenario 8 followed by revocation | later cut `REVOKED`; earlier cut not rewritten | PH14-H9 |
| 10 | a successor artifact | inherits nothing; authorization never crosses an artifact edge | PH14-H10 |

## The critical invariant

The real artifact can never enter `AUTHORIZED` as a side effect of
fixture testing. Three independent walls enforce it: fixtures are
refused at the Phase 9 boundary and by every Phase 13 validator; the
rehearsals run in scratch trees whose real counterparts are
byte-compared before and after; and `verify` re-assembles the real
universe on every run and refuses any divergence from the committed
Phase 13 state.
