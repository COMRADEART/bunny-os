<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Real evidence has one door

The real ledger — `qualification/phase9/intake/LEDGER.json` — remains
authoritative, and evidence enters it through exactly one mechanism:

```text
python qualification/phase9/tools/intake.py register
```

Phase 15 adds an operator wrapper (`tools/review_execution_ops.py
receive`) for the security-review workflow. The wrapper is thin by
construction and this document is the contract that keeps it thin.

## What Phase 15 does not introduce

* **No second intake directory.** Phase 15 owns no evidence store. Its
  `fixtures/` directory holds marked synthetic material the boundary
  rejects; its derived outputs (`EXTERNAL_STATUS.json`,
  `FAILURE_RECOVERY_MATRIX.json`, cut records) contain no evidence
  bytes, only derivations over the one ledger.
* **No direct-write shortcut.** Nothing in this phase writes
  `LEDGER.json` or the intake tree except by calling the Phase 9
  `register` function — the same function the CLI runs.
* **No "trusted reviewer" bypass.** There is no reviewer identity that
  skips validation. Every submission answers the six questions,
  whoever sent it.
* **No special path for security findings.** A security finding
  travels the same door as everything else; severity buys no shortcut.
* **No append without the boundary.** The wrapper cannot append an
  accepted entry the boundary did not validate, because the wrapper
  has no append code — it calls `register` and reports what the
  boundary decided.

## The wrapper contract

`receive` accepts explicit inputs only — a record path, attachment
paths, `--received-on`, `--submitted-by`, optional `--revises` — and
passes them to the Phase 9 `register` function unmodified. It adds
zero pre-processing of the submission bytes: no reformatting, no field
repair, no digest fill-in, no marker stripping. Anything the Phase 9
boundary would reject, the wrapper run rejects, because the boundary
is the code path.

**A Phase 15 wrapper that accepts evidence the Phase 9 boundary would
reject is a defect.** The guard suite demonstrates this equivalence
directly: for each refusal class (credential material, private key,
fixture marker, tampered ledger, duplicate attachment name), the
wrapper's outcome equals the boundary's outcome on the same bytes, in
a scratch universe that started as a byte-copy of the real ledger.

The wrapper must not weaken, and mechanically cannot weaken:

| Property | Where enforced | Wrapper's relationship to it |
| --- | --- | --- |
| digest binding | `validate_record` (Phase 9) | never recomputes or substitutes a digest |
| hygiene scanning | `detect_secret_classes`, before ingestion | never pre-reads to "clean" a file |
| fixture rejection | `register` (structural marker check) | never strips or renames a marker |
| ledger sealing | `seal_entry` on every append | has no append code of its own |
| revision handling | `next_intake_id` | passes `--revises` through verbatim |
| immutability | seals + pins + `verify` | writes nothing into `intake/` |

## No "latest automatically"

Every Phase 15 command operates on explicit paths and IDs or refuses
ambiguity. There is no command that selects "the newest submission",
"the current review", or "the latest cut" implicitly — selecting the
wrong evidence could change a release decision, so selection is always
an operator-stated input. Where a derivation must consider every entry
(receipt register, status), it enumerates all of them and reports per
ID; it never picks one silently.

## Real evidence contingency

If real evidence arrives while any Phase 15 work is in flight:

1. stop treating that path as a fixture scenario;
2. preserve the source bytes exactly as received;
3. register through the Phase 9 intake (`receive` or the CLI — same
   code);
4. record the intake ID;
5. validate artifact binding and the Phase 11 contract (`validate`);
6. reconcile through the Phase 11 engine (`reconcile`);
7. create an explicit evidence cut if a decision will reference the
   state (`cut`);
8. derive the candidate state (`assemble`, `status`);
9. report the actual outcome — favorable, unfavorable, malformed, or
   mismatched, exactly as derived.

The evidence is never modified to make it conform; a malformed
submission is recorded in its correct refusal state; an unfavorable
submission is preserved and blocks; new findings are never suppressed.
