<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Baseline reconciliation protocol

Reconciliation runs through the real Phase 11 machinery
(`qualification/phase11/tools/security_review_ops.py`), unmodified.
Phase 15 adds no second reconciler; the `reconcile` command invokes
Phase 11's derivation, and this document states how each distinction
the workflow needs maps onto vocabulary Phase 11 already owns.

## The baseline

8 Critical + 36 High findings, 44 stable identifiers
(`SEC-BL-001..044`), derived deterministically from the pinned Phase 8
package and never edited by hand. `build-baseline` refuses to renumber:
a changed Phase 8 package is a new baseline version cut deliberately,
never a silent replacement.

## The distinctions, mechanically

| Workflow concept | Phase 11 vocabulary | Where derived |
| --- | --- | --- |
| baseline finding addressed | the advisory appears in a submission's classifications | `reconcile_submission` |
| baseline finding confirmed | `CONFIRMED` (applicable, same severity, same scope) | `reconcile_submission` |
| baseline finding disputed | `SEVERITY_CHANGED` / `SCOPE_CHANGED` | `reconcile_submission` |
| baseline finding unresolved | `REQUIRES_FURTHER_ANALYSIS`, or row still `BASELINE` | register derivation |
| new finding | `NEW_FINDING` (advisory outside the baseline) | `reconcile_submission` |
| not applicable | `NOT_APPLICABLE` — requires establishing evidence + rationale | `reconcile_submission`, `_established` |
| accepted risk | `ACCEPTED_RISK` — requires authority, rationale, artifact, scope impact, expiry | `security_finding_transition` |
| insufficient evidence | `REQUIRES_FURTHER_ANALYSIS` (undetermined or unestablished conclusion) | `reconcile_submission` |
| conflicting assessment | `EVIDENCE_CONFLICT` (register level, across submissions) | `_evidence_states` |

## The rules Phase 15 demonstrates, none of them new

1. **A reviewer saying "not exploitable" does not close a finding.**
   `NOT_APPLICABLE` without evidence and rationale is held at
   `REQUIRES_FURTHER_ANALYSIS`; with them, the row becomes
   `NOT_APPLICABLE`, and *closure* still requires the establishing
   evidence at the `CLOSED` transition.
2. **A closure satisfies the evidence and binding rules.** `CLOSED`
   requires closure evidence naming a reference and an artifact;
   closure evidence bound to a different artifact refuses ("approval
   does not transfer").
3. **`NOT_APPLICABLE` carries analysis.** Enforced at three layers:
   reconciliation (unestablished → `REQUIRES_FURTHER_ANALYSIS`), the
   transition guard, and the standing-row validator.
4. **`ACCEPTED_RISK` requires authority and expiry.** All five fields
   (`decisionAuthority`, `rationale`, `affectedArtifact`,
   `alphaScopeImpact`, `reviewBy`); a risk acceptance without an
   expiry is a permanent waiver nobody granted, and one without a
   *valid* authority is ineffective at the Phase 13 layer even if the
   fields are filled.
5. **Omission is measurable, not silent.** A submission that omits a
   baseline finding leaves it exactly where it was;
   `unaddressedBaseline` counts and names the omitted advisories on
   every reconciliation, and the register keeps the row's prior state.
   Silence never dispositions a finding.

## New findings are first-class

The review scope is frozen (`SCOPE-1`); the finding set is not. A
genuine new finding:

* keeps the reviewer's own identifier (`reviewer_finding_id`);
* receives **no renumbering of existing baseline rows** — `SEC-BL-NNN`
  identifiers are assigned by committed package order, once;
* enters the derived register as a `NEW_FINDING` row in
  `UNDER_REVIEW`, carrying its source intake ID;
* receives its own triage identifier at first triage
  (`(SEC)-(P9|EXT)-NNN`), never minted by the register;
* expands the reconciled register **without modifying the original
  immutable intake record** — the register is derived, the intake
  bytes are sealed.

Demonstrated shape:

```text
baseline review + NEW_FINDING → expanded reconciled register
```

A prior submission is never rewritten to insert a finding. New material
arrives as a Phase 9 revision (`--revises INTAKE-NNN`), preserving the
original beside it.

## Critical policy

A confirmed Critical admits exactly three dispositions:
`FIX_BEFORE_ALPHA`, `ACCEPTED_RISK` (full acceptance record),
`NOT_APPLICABLE` (establishing evidence). A confirmed Critical without
one is a disposition gap: not an invariant violation — the decision is
human and follows confirmation — but the gate cannot be `SATISFIED`
while one exists, and `critical_disposition_gaps` is the work queue.
A new Critical enters the register and blocks until appropriately
resolved, exactly like a baseline one.
