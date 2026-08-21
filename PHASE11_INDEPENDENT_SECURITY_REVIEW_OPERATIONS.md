<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Phase 11 — Independent Security Review Operations

## STATUS: **PHASE 11 — SECURITY REVIEW AWAITING EXTERNAL EVIDENCE**

Not SECURITY REVIEW UNDER ANALYSIS — no submission exists to analyze. Not
SECURITY REMEDIATION REQUIRED — no accepted finding requires one. Not
SECURITY GATE SATISFIED, and not SECURITY APPROVED — no accepted
independent evidence supports either word, and absence never will. The
review is now fully commissionable: requestable, reproducible, bound to
the exact artifact, auditable, intake-compatible, and actionable — and it
has not happened. That absence remains a blocking condition.

---

## 1. Executive summary

Phase 11 operationalized the independent security review without
performing it. The repository can now hand a reviewer one canonical
package that names exact bytes and refuses trust in its own claims;
freeze the questions before any answer exists; validate a submission
mechanically against a committed contract; accept it only through the
Phase 9 intake; reconcile accepted findings against a pinned historical
baseline; track every finding through a closed state vocabulary whose
closures require evidence bound to the right artifact; record reviewer
conflicts fail-closed instead of averaging them; and derive the security
gate reproducibly — with SATISFIED reachable only through accepted,
contract-valid, approving external evidence. Concretely:

* a **commissioning package** (`qualification/phase11/security-review/`):
  REQUEST, frozen REVIEW_SCOPE (`SCOPE-1`), independently verifiable
  ARTIFACT_IDENTITY, FINDINGS_BASELINE pinned to the Phase 8 package by
  sha256, REVIEWER_INSTRUCTIONS, SUBMISSION_SCHEMA, and a reviewer-side
  validator (VERIFY_SUBMISSION.py) enforced *from* the schema so the two
  cannot drift;
* an **operations tool** (`tools/security_review_ops.py`): baseline
  derivation, contract validation, §7 reconciliation, the nine-state
  finding lifecycle with guarded transitions and standing invariants, the
  Critical-disposition policy, conflict classification, successor and
  requalification validation, and the derived register with one gate
  state;
* a **derived register** (`security-findings.json`): 44 rows (8 Critical,
  36 High), all BASELINE, gate **AWAITING_EXTERNAL_EVIDENCE**,
  reproducible from the baseline, the Phase 9 ledger (read, never
  written), and the artifact graph;
* ten **TEST_FIXTURE_ONLY fixtures** covering every §16 scenario, refused
  as evidence everywhere — including by real Phase 9 registration;
* **57 guard tests** (`tests/release/test_phase11_security_review.py`),
  green on Windows and on the reference target;
* the fourth run of the standing demonstration: **both immutability
  guards refused the Phase 11 tree** (commit `fea277f2` fails both, all
  nineteen files named) until `d8338f96` declared it deliberately.

No review was manufactured. No finding was closed. No blocking condition
weakened. The subject artifact, the intake ledger, and the decision
record are exactly as Phase 10 left them.

## 2. Phase 10 baseline

`PHASE 10 — CANDIDATE OPERATIONS READY` at head `cca29e01`. Candidate
`e906a48793d7` EVIDENCE_PENDING; zero intakes across all five sources;
conditions 1, 2, 7, 8 true; the deterministic priority ladder naming the
independent security review as the next action. All carried forward
unmodified — Phase 11 reads the Phase 8–10 trees and writes nothing into
them. One Phase 10 file changed: the ladder's security-review action text
in `candidate_ops.py` now names the canonical Phase 11 commissioning
package, and `candidate-status.json` was re-derived by `sync` (never
edited by hand); its state, conditions, and evidence lists are unchanged.

## 3. Subject artifact identity

| | |
| --- | --- |
| Identifier | `e906a48793d7` |
| Image | `sha256:c87a6616008ce34f97840f63814e08fdb33574b52202fbb4841b7f5aa7f8562d` |
| qcow2 | `497add9a77db2db02bf2541e85b04b0e285c1833d2c8220d193d0d413a6ce867` |
| ISO | `823d50caba35afe72452768affd5f6fa0ac8cfc13c164f0e1bc909fa887ab421` |
| OCI archive | `205a77f1b6cdf33915bce3afceb0914d6af25f97b434cf2128aec04d199b43dd` |
| raw | `a6ee06dcbc0ed3aa22c9ea07c339882eb97c7f16ce906b654c9a1e1119849d46` |
| Source commit | `e906a48793d74544b39c14cc3e35e0654f5311e2` |
| Signing status | **UNSIGNED** (condition 7 stays true independently of this review) |

Frozen, unchanged, not rebuilt. `ARTIFACT_IDENTITY.json` hands the
reviewer these digests **with recomputation instructions and an explicit
instruction not to trust them**: the submission records the digest the
reviewer computed, and a test pins the package identity to the intake
ledger's so the reviewer can never be handed an identity the boundary
would refuse.

## 4. Review commissioning package

`qualification/phase11/security-review/` — the canonical package,
superseding the *location* language of the Phase 8 PACKAGE.md (which
predates the intake boundary; per the Phase 9 governance, historical
files are not edited to say so). Contents: `REQUEST.md`,
`REVIEW_SCOPE.md`, `ARTIFACT_IDENTITY.json`, `FINDINGS_BASELINE.json`,
`REVIEWER_INSTRUCTIONS.md`, `SUBMISSION_SCHEMA.json`,
`VERIFY_SUBMISSION.py` — completeness asserted by test. The baseline
derives deterministically from the Phase 8 `review-package.json`
(builder: `security_review_ops.py build-baseline`), assigns stable
`SEC-BL-001…044` identifiers in committed package order, and **pins the
Phase 8 bytes by sha256**: a changed package fails derivation closed
("the baseline is historical evidence and is never silently replaced")
rather than renumbering — executed as a negative control on every run.

## 5. Scope freeze

`REVIEW_SCOPE.md`, version `SCOPE-1`, committed before any reviewer
response exists. Eight questions, SQ-1 through SQ-8, verbatim from the
phase brief: applicability of the 8 Criticals and 36 Highs,
misclassification, missing findings, reachability of vulnerable
functions in shipped binaries, whether presence implies exploitability,
unreviewed attack surface, and Alpha release-blocking impact. The freeze
is one-directional and enforced: the guard test fails if any SQ
identifier leaves the committed document, submissions must name the
scope version they answer (the schema accepts only frozen versions), and
**the reviewer may add findings at any time** — NEW_FINDING is a
first-class reconciliation outcome.

## 6. Reviewer independence model

The minimum evidence for INDEPENDENT_REVIEWER, all machine-checked for
presence: a stable reviewer identifier (pseudonymous `REVIEWER-NNN`
permitted — identity handling may live outside the repository, and no
unnecessary personal information is requested), an independence
declaration in the reviewer's own words, a disclosed relationship to the
project, the review dates, the scope version, and the independently
observed digest. The one structural rule: a reviewer declaring
themselves the release decision authority is refused unless
`policy_exception` names a recorded policy permitting the overlap — and
none exists. The honesty boundary is stated in the tool and the package:
automation verifies the declaration *exists*; whether it is credible is
a human judgment recorded at triage, never manufactured.

## 7. Submission contract

`SUBMISSION_SCHEMA.json` — required: `reviewer_id`, `independence`,
`artifact_digest`, `independently_computed_digest`,
`review_scope_version`, `review_start`, `review_end`, `findings`,
`overall_assessment` (exactly `APPROVED` / `APPROVED_WITH_CONDITIONS` /
`BLOCKED` / `MORE_EVIDENCE_REQUIRED`), plus the five intake-alias
spellings (`reviewer`, `scope`, `date`, `disposition`, `artifactDigest`)
the Phase 9 boundary reads, constrained equal to their canonical
counterparts. Per finding: `reviewer_finding_id`, `title`, `severity`,
`affected_component`, `applicability`, `evidence`, `rationale`,
`recommended_disposition` — and `baseline_advisory` as the public
(GHSA/CVE) reconciliation hook: **the reviewer is never required to use
the project's internal identifiers; the register maintains the
mapping.** `VERIFY_SUBMISSION.py` enforces the contract by *reading the
schema* (required lists, enums, patterns, aliases), and the suite
refuses a schema keyword the validator does not enforce — an unenforced
constraint is a fiction. Four cross-field rules ride on top: alias
equality, both digests within the subject's five, start ≤ end, and the
authority-overlap policy.

## 8. Intake boundary

Exactly one door, unchanged: `qualification/phase9/tools/intake.py
register --source security-review`. Phase 11 created **no second intake
mechanism** — its tooling prepares, validates, analyzes, maps, and
derives; nothing in it appends to the ledger, and the derivation reads
the ledger bytes-before/bytes-after to refuse a run in which they
changed. The layering is deliberate and tested: a record missing the
independently computed digest is ACCEPTED by Phase 9 (which does not
know the field) yet contributes nothing to the gate — the register
records the contract problems and holds the gate at UNDER_ANALYSIS until
a revision arrives. Phase 9 acceptance is entry into triage, not
validity for this gate.

## 9. Finding reconciliation

`reconcile_submission` classifies every reviewer finding against the
pinned baseline into exactly one of **CONFIRMED / NOT_APPLICABLE /
NEW_FINDING / SEVERITY_CHANGED / SCOPE_CHANGED / EVIDENCE_CONFLICT /
REQUIRES_FURTHER_ANALYSIS**. An undetermined or unestablished conclusion
is held at REQUIRES_FURTHER_ANALYSIS; severity and scope disagreements
are named, not absorbed; a finding outside the baseline is NEW_FINDING;
contradictory conclusions between accepted submissions about the same
advisory become EVIDENCE_CONFLICT at register level, where every
submission is visible at once. Unaddressed baseline rows stay in their
prior state — **silence about a finding never dispositions it** — and
the Phase 8 baseline itself is never replaced: it remains historical
evidence under its own pin.

## 10. Finding lifecycle

Nine states: BASELINE → UNDER_REVIEW → CONFIRMED | NOT_APPLICABLE;
CONFIRMED → REMEDIATION_REQUIRED | ACCEPTED_RISK | DEFERRED |
NOT_APPLICABLE; REMEDIATION_REQUIRED → FIXED_PENDING_REQUALIFICATION →
CLOSED; ACCEPTED_RISK → CLOSED | REMEDIATION_REQUIRED; DEFERRED →
REMEDIATION_REQUIRED | UNDER_REVIEW; NOT_APPLICABLE → CLOSED |
UNDER_REVIEW. **CONFIRMED → CLOSED is not a declared transition** — its
absence is asserted, and the full undeclared-pair sweep executes every
refusal on every run. Guards: review states require the accepted intake
ID; NOT_APPLICABLE requires establishing evidence ("not exploitable"
alone is insufficient); ACCEPTED_RISK requires the five-field acceptance
record; FIXED_PENDING_REQUALIFICATION requires a successor that is not
the frozen artifact; CLOSED requires closure evidence bound to the right
artifact. The same rules exist twice deliberately: as transition guards
(refusing illegal steps) and as standing invariants over committed rows
(`validate_register_row`), so a row written by any other route still
cannot claim a state without that state's evidence — derivation fails
closed on a violation.

## 11. Critical finding policy

A confirmed Critical admits exactly **FIX_BEFORE_ALPHA / ACCEPTED_RISK /
NOT_APPLICABLE**; any other disposition string on a Critical row is an
invariant violation. ACCEPTED_RISK requires decision authority,
rationale, affected artifact, Alpha scope impact, and an
expiration/review date — an accepted risk without an expiry is a
permanent waiver nobody granted. NOT_APPLICABLE requires the recorded
establishing evidence. A confirmed Critical still awaiting its
disposition is not a violation — the decision follows confirmation — but
`critical_disposition_gaps` lists it as the work queue and the gate
cannot be SATISFIED past it, which is condition 2 kept true by
machinery rather than by promise.

## 12. Remediation path

If accepted review evidence requires product changes, `e906a48793d7` is
not modified — the path is finding → remediation plan → source change →
new commit → new artifact → artifact graph edge → Phase 10 impact
analysis → requalification plan. `validate_successor_entry` refuses a
successor that is not REMEDIATES, not parented on the finding's
artifact, without its own digest, or born in any state but
**REQUALIFICATION_REQUIRED** — it inherits no PASS. Closure of the
originating finding then requires requalification evidence bound to the
*successor*: closure evidence naming the parent is refused with
"approval does not transfer", executed in the walk test.

## 13. Requalification rules

For every security-driven successor, six recorded requirements: new
artifact identity, artifact digest verification, security rescan,
affected functional qualification, regression suite, release gate
recomputation. `validate_security_requalification_plan` runs the Phase
10 planner's own validation (a plan cannot express PASS) and
additionally refuses any plan in which SECURITY or RELEASE has been
weakened below REQUIRED for a product-affecting successor. External
review applicability for the successor is evaluated by the Phase 10
engine, where the default across artifacts is DOES_NOT_APPLY — **the old
review is never assumed to apply**, tested against a modelled successor.

## 14. Reviewer conflict handling

When accepted independent reviews disagree, nothing is averaged and both
submissions are preserved (the intake is append-only by construction).
`classify_conflict` records the conflict as CONTRADICTORY_CONCLUSIONS
(an approving outcome against BLOCKED) or DIVERGENT_ASSESSMENTS, sets
the effective assessment to the **most blocking** pending resolution,
and constrains resolution to RESOLUTION_REQUIRED /
ADDITIONAL_REVIEW_REQUIRED / REMEDIATION_REQUIRED / BLOCKED — an
invented outcome ("MOST_FAVORABLE") is refused. In the dry run, APPROVED
versus BLOCKED over the same grpc Critical yields the recorded conflict,
an EVIDENCE_CONFLICT row held at UNDER_REVIEW, and a BLOCKED gate.

## 15. Negative controls

Every refusal executes on every suite run; none is policy prose:

| Control | Result |
| --- | --- |
| Fixture wrapper registered through real Phase 9 code | REJECTED, "a fixture is never evidence" |
| Reviewer digest of other bytes | ARTIFACT_MISMATCH at intake; contract names blocking condition 6 |
| Missing independently computed digest | Phase 9 ACCEPTED, contract invalid, gate contribution zero |
| Alias disagreement / invented outcome / unfrozen scope version | contract invalid, each named |
| Reviewer is the release decision authority, no policy | refused — no such policy exists |
| CONFIRMED → CLOSED directly | refused; the transition does not exist |
| Close without closure evidence / accepted risk without its record / NOT_APPLICABLE without analysis | refused, each with its reason |
| Closure evidence bound to the parent instead of the successor | refused, "approval does not transfer" |
| Root review evaluated against a successor | DOES_NOT_APPLY, "the default is no transfer" |
| Requalification plan weakening SECURITY, or smuggling PASS | refused by plan validation |
| Changed Phase 8 package under the baseline pin | derivation refuses; "historical evidence" |
| Fixture-marked ledger entry reaching derivation | BoundaryViolation |
| Both immutability guards vs the undeclared tree | commit `fea277f2` fails both, nineteen files named; `d8338f96` declares |

## 16. Validation

Windows (win32, Python 3.14): release suite **277 tests** (220 prior +
57 new), OK, 1 skip (the POSIX interpreter question — skipped, not
passed); portability suite **205 tests**, OK, 3 platform skips; both
immutability guards green after the declaration; `intake.py verify`,
`candidate_ops.py verify`, and `security_review_ops.py verify` all
clean. Discovery verified explicitly: `discover().countTestCases()`
reports 277 and 205, so the new file is reached by the runner, not
merely present.

Reference target (FedoraLinux-44 WSL2, ext4 clone, as `bunny`, at
`d8338f96`): release **277** OK (1 pre-existing skip: a gate-state test
wanting a generated candidate artifact), portability **205** OK (1 skip:
the Windows temporary-path form), both guards **13** OK, all three phase
verifies clean.

## 17. Actual external evidence received

**None.** Zero security-review intakes; zero intakes of any kind. The
ledger's entry list is exactly as Phase 9 created it, byte-identical
before and after every dry run — the tests compare bytes, never assert
emptiness, so the suite stays green on the day real evidence arrives.
Every submission exercised in this phase was a structurally marked
fixture registered into constructed scratch trees only.

## 18. Current security status

From `qualification/phase11/security-findings.json`, derived and
reproducible: 44 findings, 8 Critical + 36 High, all in state
**BASELINE**; applicability REQUIRES_REVIEW ×41 and UNKNOWN ×3, exactly
as the Phase 8 package left them; zero dispositions; zero closures; zero
conflicts; gate **AWAITING_EXTERNAL_EVIDENCE** — "absence blocks, it
does not authorize."

## 19. Blocking conditions

Unchanged from Phases 9–10, none weakened: conditions **1, 2, 7, 8
TRUE** (no completed review; Criticals undispositioned; unsigned with no
exception; no second approval), **6 FALSE** (identity verifies), **3, 4,
5, 9, 10 UNDETERMINED** (no testing evidence either way). This phase
built the machinery that will move conditions 1 and 2 when evidence
arrives; it moved neither, and could not have.

## 20. Next required action

Exactly one, unchanged in substance and now precisely equipped: **hand
`qualification/phase11/security-review/REQUEST.md` to an actual
independent reviewer.** Everything the reviewer needs is committed — the
identity to verify against, the frozen questions, the pinned baseline,
the contract, and the validator — and everything the project needs to
process the answer is built and tested, including its refusals. Until a
person outside this repository acts, the correct description of the
security gate is the one at the top of this report, and no machinery
here can improve it.

# PHASE 11 — SECURITY REVIEW AWAITING EXTERNAL EVIDENCE

The repository may prepare the question, verify the evidence, reproduce
the finding, fix the product, build a successor, and requalify it. It
may not review itself into authorization. The question is now fully
prepared; the answer must cross the external boundary and survive the
intake, the binding, the reconciliation, and the release-decision
controls that were waiting for it before it moves anything.
