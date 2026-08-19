<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Evidence Routing (Track A)

Given a candidate evidence record, `route_evidence` resolves exactly
one answer to each of: which workstream owns it, which validator must
process it, which artifact it claims, and one disposition. The router
fails closed at every step.

## The ten evidence classes

| Class | Owner | Destination | Validator |
| --- | --- | --- | --- |
| `SECURITY_REVIEW` | `AUTH-SECURITY-REVIEWER` | Phase 9 intake `security-review` | intake six questions + Phase 11 submission contract |
| `HARDWARE_VALIDATION` | `AUTH-HARDWARE` | Phase 9 intake `hardware` | intake six questions + Phase 14 hardware review |
| `SIGNING` | `AUTH-KEY` | Phase 9 intake `signing` | intake six questions |
| `SECOND_APPROVAL` | `AUTH-SECOND-APPROVER` | Phase 9 intake `second-approval` | intake six questions |
| `ALPHA_TESTER_REPORT` | `AUTH-ALPHA-PROGRAM` | Phase 9 intake `alpha-feedback` | intake six questions + Phase 12 report contract |
| `AUTHORITY_ASSIGNMENT` | organization | Phase 13 `record assignment` | Phase 13 assignment validation |
| `SUFFICIENCY_POLICY` | `AUTH-ALPHA-PROGRAM` | Phase 13 `record policy` | Phase 13 policy validation |
| `RISK_ACCEPTANCE` | `AUTH-SECURITY-OWNER` | Phase 13 `record risk-acceptance` | Phase 13 risk validation |
| `AUTHORIZATION` | `AUTH-RELEASE` | Phase 13 `record authorization` | Phase 13 full authorization validation |
| `REVOCATION` | `AUTH-RELEASE` | Phase 13 `record revocation` | Phase 13 revocation validation |

Classification is structural: each class has a fingerprint of required
field groups (with the Phase 11/12 alias spellings honored). A record
matching **zero** classes refuses — an unknown class never becomes
generic evidence. A record matching **two** classes refuses — a record
saying two things is saying nothing.

## Dispositions

Exactly one of:

- `ACCEPTABLE_FOR_INTAKE` — an intake-class record that answers the six
  questions and binds to the subject. Routing is not acceptance: the
  only door remains `intake.py register`, which re-validates, scans for
  credentials, ingests, and seals.
- `INCOMPLETE` — required content is missing; the gaps are named.
- `REJECTED` — never valid for its gate (a signing drill, a fixture
  offered as evidence at the boundary, one person approving twice).
- `DOES_NOT_APPLY` — bound to bytes that are not the subject artifact.
  No transfer by default; applicability across artifacts is a Phase 10
  recorded decision, never a router guess.
- `REQUIRES_HUMAN_DECISION` — a complete, bound governance record.
  Recording it is an authority act performed by the operator through
  `release_authority_ops.py record <kind>`, where it validates against
  the sealed assignment registry. The router prepares; it never
  decides.
- `TEST_FIXTURE_ONLY` — the record carries any fixture marker. Checked
  first, terminal: a fixture routes nowhere, whatever it looks like.

## What the router does not do

It writes nothing, registers nothing, seals nothing, and decides
nothing. `route` is analysis; the doors stay where Phases 9 and 13 put
them.
