<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Phase 10 — Candidate operations dashboard

Derived, not asserted: every row below is recomputable from
`qualification/phase10/candidate-status.json`, which itself recomputes from
the intake ledger, the artifact graph, the findings registries, and the
pre-committed blocking conditions —
`python qualification/phase10/tools/candidate_ops.py verify` proves it, and
`tests/release/test_phase10_operations.py` proves it on every suite run.

## Active candidate

| | |
| --- | --- |
| Artifact | `e906a48793d7` (ROOT; the only artifact in the graph) |
| Digest | `sha256:c87a6616008ce34f97840f63814e08fdb33574b52202fbb4841b7f5aa7f8562d` |
| State | **EVIDENCE_PENDING** (frozen since Phase 7; intake open since Phase 9; UNSIGNED) |

## External evidence

| Status | Count |
| --- | --- |
| Accepted | 0 |
| Incomplete | 0 |
| Rejected | 0 |
| Pending (in flight) | 0 |

Zero intakes across all five sources. Absence is NOT_RUN; it authorizes
nothing and it blocks per the conditions below.

## Findings

| | Count |
| --- | --- |
| Open | 0 |
| Confirmed | 0 |
| Remediation required | 0 |
| Closed | 0 |

## Qualification

| | Gates |
| --- | --- |
| Required (awaiting owners) | Independent security review · Physical hardware qualification · Production signing · Second approval · Alpha tester validation |
| Completed | Artifact identity (PASS) · Internal engineering certification (PASS, closed Phase 7) |
| Pending internal work | none — every remaining gate belongs to an external owner |

## Release conditions

| State | Conditions |
| --- | --- |
| Met (condition false) | 6 — artifact identity verifies |
| Unmet (condition true, blocking) | 1 (no completed review) · 2 (Criticals undispositioned) · 7 (unsigned, no exception) · 8 (no second approval) |
| Undetermined | 3, 4, 5, 9, 10 — no testing evidence either way |

## Next blocking action

**Commission the independent security review.** The package has been ready
since Phase 8 (`qualification/phase8/security-review/PACKAGE.md`), and
conditions 1 and 2 stay true until its owner acts. Everything else — signing,
second approval, hardware, testers — is also waiting, but the review is the
longest-lead item and the only one that can move two blocking conditions at
once; there is no tie.
