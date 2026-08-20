<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Phase 16 — External Security-Review Intake and Gate Execution

## STATUS: **SECURITY-REVIEW INTAKE READY / EXTERNAL EVIDENCE AWAITING SUBMISSION**

**PHASE 16 DOES NOT APPROVE OR AUTHORIZE THE ARTIFACT. NO REAL EXTERNAL
SUBMISSION WAS RECEIVED.**

The subject artifact `e906a48793d7` remains ROOT, FROZEN, UNCHANGED, and
UNSIGNED. The real Phase 9 ledger remains byte-identical at zero entries. The
receipt boundary and Phase 15 workflow both derive `AWAITING_SUBMISSION`; the
Phase 11 security gate derives `AWAITING_EXTERNAL_EVIDENCE`; Phase 13 derives
`EVIDENCE_PENDING`; and the candidate decision remains
`REQUIRES_MORE_EVIDENCE`. Separately, the intake machinery is operational:
25/25 executable scenarios derive `AS_EXPECTED` without changing a real input.

## 1. Executive status

Phase 16 makes the first genuine independent security-review submission
receivable end to end. A reviewer handoff can be reproduced from pinned bytes;
a prospective package can be inspected and validated without intake; the
`receive` command carries explicit paths through the standing Phase 15 wrapper
to the one Phase 9 boundary; and accepted evidence can then be bound by Phase
10, reconciled and gated by Phase 11, cut by Phase 14 into the standing Phase
15 archive, and assembled through Phase 14/13 without a repository-local
shortcut to approval.

This is operational readiness, not evidence about the artifact. All favorable
demonstrations are `FIXTURE_DEMONSTRATION_ONLY` in isolated temporary
universes. The one real-universe matrix row is read-only and derives the actual
pending state.

The certification commit is `9c4f06d3413980499b89af27f6796297d3f06a0b`.
Windows and Fedora 44 independently passed the full release and portability
suites, both standing guards, all eleven Phase 9–16 verification commands, and
byte-identical matrix/status re-derivation at that commit.

## 2. Subject artifact identity

The identity consumed by Phases 9–16 remains:

| Field | Value |
| --- | --- |
| Identifier | `e906a48793d7` |
| Source commit | `e906a48793d74544b39c14cc3e35e0654f5311e2` |
| Graph relationship | `ROOT` |
| Frozen | `true` |
| Signing status | `UNSIGNED` |
| Candidate qualification state | `EVIDENCE_PENDING` |
| Image digest | `sha256:c87a6616008ce34f97840f63814e08fdb33574b52202fbb4841b7f5aa7f8562d` |
| ISO sha256 | `823d50caba35afe72452768affd5f6fa0ac8cfc13c164f0e1bc909fa887ab421` |
| OCI tar sha256 | `205a77f1b6cdf33915bce3afceb0914d6af25f97b434cf2128aec04d199b43dd` |
| qcow2 sha256 | `497add9a77db2db02bf2541e85b04b0e285c1833d2c8220d193d0d413a6ce867` |
| raw sha256 | `a6ee06dcbc0ed3aa22c9ea07c339882eb97c7f16ce906b654c9a1e1119849d46` |

No artifact was rebuilt, replaced, signed, or re-identified. No successor or
transfer decision exists. Commit ancestry is not used as artifact identity.

## 3. Starting state

Phase 16 began at Phase 15 report commit `615f272c279b3f9908ca1c0c744724d9e03cf309`
with these standing facts:

| Input | Starting fact |
| --- | --- |
| Phase 9 ledger | sha256 `b24ef74023cbd1d949053b8c9f842243c4e7d8818cb5b4dfcec1ab1fc0c1624b`; zero entries |
| Phase 10 graph/status | one ROOT artifact; `EVIDENCE_PENDING`; no successor |
| Phase 11 baseline/register | 8 Critical + 36 High; 44 baseline rows; gate `AWAITING_EXTERNAL_EVIDENCE` |
| Phase 12 | Alpha sufficiency policy remains undefined; no qualifying external Alpha evidence |
| Phase 13 | `EVIDENCE_PENDING` / `REQUIRES_MORE_EVIDENCE`; all five floor sources missing |
| Phase 14 | router, scratch universes, sealed-cut contract, and assembler available |
| Phase 15 | receipt `AWAITING_SUBMISSION`; CUT-001 seals the zero-entry universe |

Every one of those facts still holds because no genuine external evidence
crossed the Phase 9 boundary.

## 4. Phase objective

The objective was to make a real independent security review executable from
handoff through release consequence while preserving the difference between:

1. machinery being operational;
2. a submission crossing the immutable boundary;
3. a reviewer recording an assessment;
4. the security gate being satisfied;
5. release authorization existing; and
6. the candidate decision.

Phase 16 achieves that objective through composition and negative controls.
It does not manufacture any missing evidence or authority.

## 5. Scope and non-goals

In scope were reviewer handoff, preflight inspection, one-door receipt,
contract validation, identity observation, attachment integrity, credential
hygiene, artifact applicability, security reconciliation, conflict handling,
explicit evidence cuts, historical reconstruction, decision assembly, status
derivation, executable failure/recovery scenarios, and cross-platform
verification.

Explicit non-goals were rebuilding or signing the frozen artifact, creating a
reviewer or reviewer conclusion, editing a malformed submission, transferring
evidence by Git ancestry, resolving conflicts automatically, assigning
authority, accepting risk, satisfying another external floor member, or
turning an internal `AUTHORIZED` claim into authorization.

## 6. Architecture and engine composition

`qualification/phase16/tools/security_review_intake_ops.py` owns orchestration
and presentation only:

| Concern | Owning engine | Phase 16 composition |
| --- | --- | --- |
| immutable receipt, file pins, seals, secret scan | Phase 9 `intake.py` | delegate through Phase 15; derive receipt view |
| artifact graph, applicability, explicit transfer | Phase 10 `candidate_ops.py` | call `evaluate_applicability` |
| submission contract, baseline reconciliation, conflict, security gate | Phase 11 `security_review_ops.py` | validate and derive; never duplicate |
| Alpha evidence used in release assembly | Phase 12 register | consumed through the standing Phase 13/14 universe |
| authority, risk, authorization floor and decision ladder | Phase 13 `release_authority_ops.py` | evaluate/display only |
| router, time semantics, sealed cuts, decision assembly | Phase 14 `evidence_execution_ops.py` | call standing functions |
| reviewer package carrier, workflow receipt, cut archive | Phase 15 `review_execution_ops.py` | reuse and extend |

The operator exposes only `prepare`, `inspect`, `receive`, `validate`, `bind`,
`reconcile`, `cut`, `assemble`, `status`, and `sync-status`, plus the distinct
verification/matrix-generation operations. No command mutates a derived status
directly.

The AST boundary verifier rejects owning-engine function definitions, clock
calls, append-mode opens, direct writes through `PHASE9_LEDGER`, and any
`receive` implementation that stops delegating to `_phase15().receive`.

## 7. External reviewer handoff

`prepare --out <new-directory>` first verifies ten SHA-256 contract pins, then
reuses the Phase 15 package builder and adds Phase 16's operational handoff and
identity ceremony. It refuses an existing destination and any destination
inside the repository. Two independently prepared packages compare
byte-identically and create no review, reviewer identity, ledger row, or
candidate change.

The handoff identifies the exact artifact, Phase 11 request and scope, schema,
validator, baseline, submission route, findings formats, attachment rules,
credential prohibition, revision route, and human escalation route. It states
the two critical boundaries verbatim:

> The repository's expected digest is not evidence of your observation.
> Compute the artifact identity yourself, from the bytes you actually
> reviewed, and record how you computed it.

> Acceptance into the intake means only that your submission crossed the
> evidence boundary intact. It is not agreement, not a security approval,
> and not a release authorization.

## 8. Identity ceremony

The executable ceremony preserves the standing four-state vocabulary:

| State | Meaning |
| --- | --- |
| `VERIFIED` | one well-formed independent digest matches a subject-artifact digest and the computation basis is recorded |
| `OBSERVED_UNVERIFIED` | a matching value is stated without enough evidence that it was independently observed |
| `MISSING` | no independent observation was supplied |
| `MISMATCH` | the independent observation identifies different bytes |

Lists, prose, malformed tokens, and ambiguous observations refuse rather than
being guessed into a state. Copying the repository's expected digest without a
measurement basis derives `OBSERVED_UNVERIFIED`, never `VERIFIED`. A matching
source commit without an artifact digest is insufficient for binding. The
ceremony is read-only and never fills or repairs a reviewer field.

## 9. Receipt state machine

The boundary vocabulary is `AWAITING_SUBMISSION`, `RECEIVED`, `REJECTED`,
`INCOMPLETE`, `UNVERIFIABLE`, `DOES_NOT_APPLY`, `ACCEPTED`, and derived
`SUPERSEDED`. `APPROVED`, `SATISFIED`, `PASS`, and `AUTHORIZED` are forbidden
receipt words.

`AWAITING_SUBMISSION` can move only to `RECEIVED`; `RECEIVED` can resolve to a
Phase 9 outcome; refused states can re-enter only as an explicitly named new or
revised submission; `ACCEPTED` can become only `SUPERSEDED`; and `SUPERSEDED`
has no successor. The complete state cross-product is executed, so absence
from the transition table is a refusal rather than an implicit transition.

`ACCEPTED` records boundary crossing only. The Phase 15 workflow receipt,
review assessment, Phase 11 gate, Phase 13 authorization state, and candidate
decision remain separate keys in `INTAKE_STATUS.json`.

## 10. Intake boundary

`receive` is a thin carrier of explicit record path, attachment paths,
operator-stated receipt date, submitter string, and optional revision ID. Its
entire write-bearing delegation is:

```text
Phase 16 receive -> Phase 15 receive -> Phase 9 register
```

Phase 16 does not open the ledger for append, construct an entry, compute a
ledger seal, or write below the real intake directory. A source-level AST test
and the verifier enforce this structurally. Direct and wrapped submissions
produce identical Phase 9 outcome, binding, file, and seal semantics.

Malformed bytes become a preserved `UNVERIFIABLE` intake. Incomplete,
rejected, mismatched, and accepted originals remain immutable. A revision gets
the standing `INTAKE-NNN-RN` lineage; the earlier stored result is unchanged
and its effective state becomes `SUPERSEDED` only by derivation.

## 11. Credential hygiene

The Phase 9 byte-level scanner runs before ingestion over the record and every
attachment. Phase 16 exercises private-key material, bearer tokens, API/session
token assignments, passwords, nested credentials, and attachment credentials.
On a hit:

- the outcome is `REJECTED`;
- no submitted file is copied beneath intake;
- the filename and credential class are reported where applicable;
- the value itself is not repeated in output, the ledger, derived views, or
  failure records; and
- recovery requires a masked/clean revision and separate treatment of any
  genuinely exposed credential as compromised.

Controls also prove that prose discussing passwords and a public fingerprint
do not become false credential positives when no secret value is present.

## 12. Artifact binding

Binding delegates to Phase 10 and defaults foreign or missing identity to a
non-applicable result. Exact subject bytes apply. A related successor inherits
nothing by default, and commit ancestry supplies no identity.

The transfer branch requires an explicit graph relationship and a complete
recorded decision containing source artifact, destination artifact, evidence
scope, result, reasoning, deciding authority, and date. Incomplete transfer
records transfer nothing, and a fixture cannot be a transfer source. The real
graph has no successor and no transfer decision.

## 13. Security-review reconciliation

Only contract-valid, gate-eligible, effectively accepted Phase 9 security
review entries contribute to the Phase 11 register. Reconciliation preserves:

- baseline finding reassessments by explicit public advisory identity;
- every unaddressed baseline row as unaddressed rather than silently closed;
- each new reviewer finding as a first-class `NEW_FINDING` row;
- unresolved evidence as `UNDER_REVIEW`;
- unmapped findings without guessing a baseline identity; and
- every contradictory submission and its provenance.

`security-findings.json` re-derives exactly from the real ledger, artifact
graph, baseline, and intake files. Its certification sha256 is
`a9a80f747bf6659606f6a729b582083eb46a5ec0715b501a468acf9db37e57ad`.

## 14. New findings and Critical policy

An approving assessment does not erase a newly reported finding. A new
Critical enters untriaged, lacks an internal ID by design, is named by its
reviewer finding ID, and holds the gate `UNDER_ANALYSIS` until a standing
disposition exists. A new non-Critical that remains `UNDER_REVIEW` also holds
the gate; this closes an inherited path that could otherwise derive
`SATISFIED` from an approving assessment while a new High finding remained
unresolved.

Critical rows are favorable only when their standing status/disposition is one
of the Phase 11 accepted conclusions. Risk acceptance remains a separate Phase
13 record: reviewer prose cannot create it, it never means `NOT_AFFECTED`, it
never closes a finding, it expires, and it does not transfer to another
artifact.

## 15. Conflicts and human decision handling

Contradictory reviews are retained, classified, and evaluated at the most
blocking assessment. The engine does not average conclusions or choose the
convenient submission. Conflicted findings stay under review and the gate
blocks until an assigned human authority records a valid resolution through
the standing Phase 13 process.

The current `humanDecisionRequired` value is `false` only because there is no
real accepted review and therefore no real conflict. It is not a claim that no
future conflict or vulnerability exists.

## 16. Evidence cuts

Phase 16 reuses the single append-only Phase 15 archive rather than creating a
parallel cuts directory. A cut pins ledger bytes, graph bytes, security and
Alpha register bytes, authority/governance inputs, intake IDs, entry count,
explicit `asOf`, per-record time state, and a canonical seal.

The committed CUT-001 still reconstructs the pre-Phase-16 zero-evidence
universe:

| Field | Value |
| --- | --- |
| Cut ID | `CUT-001` |
| `asOf` | `2026-08-19` |
| Ledger entries | 0 |
| Ledger sha256 | `b24ef74023cbd1d949053b8c9f842243c4e7d8818cb5b4dfcec1ab1fc0c1624b` |
| Cut seal | `3e042c0fa7cfab2fc538334af860b125020fc808a6ead7209f059c9bdf21447e` |
| Cut-file sha256 | `caefc94f76fa3b98a1c687cc8b9f4a586b1117bcd5c25c90c0177be1d784a9c8` |

An existing label refuses; post-cut evidence is excluded and named; ledger or
sealed-record edits break integrity; even a maliciously resealed current
ledger differs from the cut's pinned hash; and cut tampering breaks its seal.
Historical reconstruction uses the cut inputs, so a later authority revocation
does not rewrite an earlier valid state.

## 17. Decision assembly

`assemble` is read-only and calls the Phase 14 assembler over the real
universe. It then exposes the Phase 13 authorization state and candidate
decision without writing an authorization record.

Executed controls prove:

1. zero evidence derives a non-authorizing result;
2. an accepted blocking review remains non-authorizing;
3. a hypothetical satisfied security gate alone still names the other missing
   floor sources;
4. an internal JSON claiming `AUTHORIZED` is refused against absent evidence;
   and
5. even a favorable all-Critical scratch review changes no real artifact,
   ledger, graph, register, cut, status, or authority record.

The real assembly agrees exactly with committed Phase 13 status sha256
`f14a546708cec6418ce1a082493dd9ef04b59afbf1d30d1e97b713725f7013b0`.

## 18. Zero-evidence real state

The current real row is derived, not asserted empty as a permanent invariant.
At certification it observes:

| Fact | Derived value |
| --- | --- |
| Real Phase 9 ledger entries | 0 |
| Real security-review intakes | 0 |
| Accepted real security reviews | 0 |
| Boundary receipt | `AWAITING_SUBMISSION` |
| Phase 15 workflow receipt | `AWAITING_SUBMISSION` |
| Accepted reviewer assessments | none |
| Security gate | `AWAITING_EXTERNAL_EVIDENCE` |
| Authorization | `EVIDENCE_PENDING` |
| Candidate decision | `REQUIRES_MORE_EVIDENCE` |

The tests compare real bytes before and after. They will continue to pass when
legitimate evidence arrives because S01 dynamically checks the then-current
ledger, register, assembly, and cut relationship rather than requiring zero.

## 19. Fixture demonstrations and their limits

Four committed wrappers carry all three structural markers:
`fixtureClass: TEST_FIXTURE_ONLY`, `fixture: true`, and
`test_fixture_only: true`. Their inner payload is deliberately unmarked so the
real production functions can process that shape only after it is copied into
an isolated scratch universe.

A marked wrapper is terminal at real intake, cannot serve as an evidence
transfer source, and satisfies none of the Phase 13 floor. The favorable
all-Critical review is built at runtime from the committed baseline inside a
scratch universe and is never committed as evidence. A successful fixture row
therefore proves a code path, not the artifact, reviewer, gate, or release.

## 20. Failure and recovery matrix

`MATRIX.json` and `FAILURE_RECOVERY_MATRIX.json` are two views of one execution,
not hand-maintained PASS tables. The runner executes 25 scenarios: one dynamic
`REAL_UNIVERSE_READ_ONLY` row and 24 `FIXTURE_DEMONSTRATION_ONLY` rows. All
25 derive `AS_EXPECTED`.

Each route row records scenario ID/name, route, evidence class, identity,
intake, binding, reconciliation, gate, cut, assembly, recovery result,
designation, expected/observed outcome, and SHA-256 identities of the ledger,
graph, security register, and baseline. Each recovery row records the expected
and observed result, recovery path, fixture flag, and the same input identities.

The required cases are S01 no submission; S02 malformed; S03 missing
observation; S04 substituted expectation; S05 wrong observation; S06 foreign
artifact; S07 ambiguous identity; S08 private key; S09 nested credential; S10
attachment credential; S11 incomplete finding; S12 new Critical; S13
contradictory reviewers; S14 post-cut evidence; S15 revision; S16 tampered
ledger; S17 resealed ledger; S18 tampered cut; S19 expired risk; S20 revoked
authority; S21 internal `AUTHORIZED`; S22 fixture at real intake; S23 novel
shape; S24 historical reconstruction; and S25 satisfied gate with absent floor.

Certification hashes:

| Generated view | SHA-256 |
| --- | --- |
| `MATRIX.json` | `2469dd87577eff5d8820fa419734c5cbb15ce2cbdc4546d7a0d074838487c962` |
| `FAILURE_RECOVERY_MATRIX.json` | `f7a9913646f914021e0ba98035f616ba54b972cd1b31e75debc0e02387a1c728` |
| `INTAKE_STATUS.json` | `33cd471e56facc10fd0cc058c30cd36c047188078881073d353d22f7f8a8960e` |

## 21. Negative controls

| Claim | Executed control | Result |
| --- | --- | --- |
| one evidence door | AST scan for append/direct-write/substitute seal plus wrapped/direct outcome equivalence | no Phase 16 bypass exists |
| independent identity | expected digest supplied without observation basis | `OBSERVED_UNVERIFIED` |
| exact artifact | wrong/foreign digest and commit-only identity | mismatch / does not apply |
| findings cannot vanish | approving review + new Critical and approving review + new High | gate remains under analysis and names the finding |
| conflicts fail closed | contradictory accepted reviews | most-blocking/human-decision path |
| credentials never enter | three-level secret and secret attachment | rejected before ingestion; value absent from output |
| prose is not a secret | password discussion and public fingerprint without a value | otherwise-valid record remains valid |
| cuts are historical | evidence added after cut | excluded and named; earlier bytes unchanged |
| seals matter | edited entry, resealed current ledger, and altered cut | verification/pin/seal failure |
| authorization is external | internal `AUTHORIZED` JSON | refused with missing floor |
| one favorable gate is insufficient | satisfied security gate with four other sources absent | `EVIDENCE_PENDING` / `REQUIRES_MORE_EVIDENCE` |
| fixtures are terminal | marked favorable wrapper through real Phase 9 code | rejected; no floor contribution |
| history is cut-relative | authority valid before and revoked after cut | historical state reconstructs from immutable cut inputs |

## 22. Time, expiry, and revocation

No wall-clock call determines evidence semantics. AST checks reject
`datetime.now`, `date.today`, `time.time`, and `utcnow` calls in the Phase 16
engine or verifier. All comparisons use record fields, operator-supplied
receipt dates, or an explicit cut `asOf`.

The Phase 9 receipt date, Phase 11 review dates, Phase 13 governance dates,
and Phase 14 evaluation/ordering dates now require an exact, valid
`YYYY-MM-DD` calendar date. Impossible dates such as `2026-02-30`, suffixes
such as `2026-08-19-later`, ambiguous values, missing required dates, and
unparseable values fail closed. The matrix/tests execute future observations,
valid pre-expiry and expired risk states, assignment expiry, revocation before
and after a cut, approval ordering, revision ordering, and mandatory `asOf`
when any expiring record is present.

## 23. Immutability guarantees

Before every matrix execution, the runner snapshots by bytes all Phase 14 real
immutable inputs plus the Phase 15 status, matrix, committed cuts, and Phase 16
status/matrices/pins. Every byte is compared afterward. The release tests add
class-level byte walls around the same real ledger, intake files, graph,
security/Alpha registers, authority records, candidate status, receipt/status
views, and cuts.

The invariant is byte identity, never “the ledger must remain empty.” A future
legitimate append through Phase 9 changes the accepted starting bytes and the
derived current-real row; fixture demonstrations must still return those new
bytes unchanged.

The frozen artifact identity, historical Phase 4–7 evidence, CUT-001, original
intake entries, seals, and revision history remain immutable. Generated live
views must re-derive exactly or verification fails.

## 24. Inherited defects discovered

Two defect families were exposed by executing Phase 16 branches that earlier
phases did not cover completely:

1. **Date boundaries accepted prefixes rather than exact calendar dates.**
   Phase 9 accepted any `receivedOn` beginning like a date; Phase 11's schema
   patterns were unanchored and its verifier compared strings without proving
   a valid date; Phase 13/14 truncated values to ten characters before
   `fromisoformat`. A suffixed timestamp could therefore masquerade as a date,
   and an impossible date could pass some validation layers or crash later.
   The owning files now perform anchored pattern checks and calendar parsing,
   with regressions in the Phase 9, 11, 13, 14, and Phase 16 suites.
2. **An approving review could outrun a new unresolved non-Critical.** Phase
   11's gate considered open Criticals and two reconciliation classes, but did
   not include a `NEW_FINDING` row still `UNDER_REVIEW` unless it was Critical.
   A new High under an approving assessment could therefore produce a
   favorable gate. Phase 11 now treats every new under-review row as
   unresolved and names it using its internal or reviewer-source ID. The owner
   regression and Phase 16 reconciliation tests execute both Critical and
   non-Critical branches.

Both repairs live at their owning phases in operations commit `06b67f25`; the
regressions live in tests commit `fccc39ab`. The real zero-evidence register,
status, ledger, and historical cut re-derived byte-identically, so no
historical conclusion changed.

## 25. Validation on Windows

Certification environment: Microsoft Windows NT `10.0.26200.0`, Python
`3.14.5`, certification commit `9c4f06d3`, clean worktree after all runs.

| Run | Result |
| --- | --- |
| Explicit discovery | release 729; portability 205; both loader error lists `[]` |
| Full release suite | 729 tests, **OK**, skipped=1, 13.209s |
| Full portability suite | 205 tests, **OK**, skipped=21, 112.815s |
| Both standing immutability guards | 13 tests, **OK** after the required refusal/declaration sequence |
| Phase 9–16 verification chain | all 11 commands exit 0 |
| Phase 16 matrix/status re-derivation | byte-identical; 25/25 `AS_EXPECTED` |
| Real ledger and CUT-001 around re-derivation | hashes unchanged |

Windows release skip, exactly:

- `tests.release.test_script_executability.ScriptExecutability.test_direct_path_interpreters_resolve_on_posix_hosts` — `interpreter paths are a POSIX question; skipped, not passed`.

Windows portability skips, exactly:

- `DisplayPathTests.test_a_symlink_is_described_by_its_target` — symlink
  creation unavailable (`WinError 1314`, required privilege not held).
- `DisplayPathTests.test_posix_runner_temp_displays_absolute` — `POSIX temporary-directory layout`.
- These ten `AssertGateSemanticsTests` were skipped with `bash unavailable on
  this host`: `test_a_crash_is_not_accepted_as_a_refusal`,
  `test_a_gate_that_approves_when_refusal_was_expected_fails`,
  `test_a_gate_that_refuses_with_exit_two_is_accepted`,
  `test_a_missing_file_is_not_accepted_as_a_refusal`,
  `test_a_nonsense_expectation_is_rejected`,
  `test_a_python_traceback_is_not_accepted_as_a_refusal`,
  `test_an_unusual_exit_status_is_not_accepted_as_a_refusal`,
  `test_evaluated_accepts_either_verdict_but_not_a_crash`,
  `test_every_script_a_workflow_asserts_on_exists`, and
  `test_expecting_a_pass_reports_a_refusal_distinctly`.
- `OneFailureDoesNotImplicateTheOthersTests.test_a_broken_workflow_fails_only_workflow_yaml` — `PyYAML unavailable`.
- These four `AbsentOsReleaseTests` were skipped with `bash unavailable on
  this host`: `test_a_missing_os_release_reports_unknown`,
  `test_a_missing_version_id_does_not_emit_a_trailing_separator`,
  `test_a_present_os_release_reports_id_and_version`, and
  `test_quotes_around_the_values_are_stripped`.
- The three parameterized cases of
  `AbsentOsReleaseTests.test_the_record_remains_parseable_json_in_every_case`
  (`replacement=None`, Fedora 44, and Arch) — `bash unavailable on this host`.
- `ShellCheckPassesTests.test_shellcheck_accepts_every_shell_script` —
  `shellcheck unavailable on this host`.

These are 21 reported skips, not passes. No Phase 16 test skipped.

## 26. Validation on Fedora reference target

Certification ran at the same commit in the established ext4 checkout
`/home/bunny/bunny-os-ref`:

| Environment field | Value |
| --- | --- |
| Distribution | Fedora release 44 (Forty Four) |
| WSL | WSL2, kernel `6.18.33.2-microsoft-standard-WSL2` |
| User | `uid=1000(bunny) gid=1000(bunny)` |
| Filesystem | `/dev/sdd`, `ext4`, mounted at `/` |
| Python | 3.14.3 |
| Commit | `9c4f06d3413980499b89af27f6796297d3f06a0b`, detached, clean |

| Run | Result |
| --- | --- |
| Explicit discovery | release 729; portability 205; both loader error lists `[]` |
| Full release suite | 729 tests, **OK**, skipped=1, 8.500s |
| Full portability suite | 205 tests, **OK**, skipped=1, 62.613s |
| Both standing immutability guards | 13 tests, **OK**, 4.760s |
| Phase 9–16 verification chain | all 11 commands exit 0 |
| Phase 16 matrix/status re-derivation | byte-identical; 25/25 `AS_EXPECTED` |
| Real ledger and CUT-001 around re-derivation | hashes unchanged |

Fedora skips, exactly:

- Release:
  `tests.release.test_candidate_readiness.UnresolvedUnknownBlocksACandidate.test_the_committed_state_blocks_on_the_vulnerability_gate`
  — `run scripts/release.py gate --kind qualification-candidate first`.
- Portability:
  `tests.portability.test_display_path.DisplayPathTests.test_windows_temporary_path_displays_absolute`
  — `Windows temporary-path form`.

These are two environment/prerequisite skips, not passes. No Phase 16 test
skipped. Windows and Fedora agree on every generated hash listed in section 20.

## 27. Discovery verification

The baseline at Phase 15 was 639 release tests and 205 portability tests.
Phase 16 discovers 729 release tests and the same 205 portability tests:

| Contribution | Tests |
| --- | ---: |
| `test_phase16_intake_operations.py` | 44 |
| `test_phase16_gate_execution.py` | 40 |
| New owner-level regressions in Phase 9/11/13 modules | 6 |
| Net release-suite increase | **90** |

The Phase 14 date controls were strengthened in place and do not increase the
count. Both new module names are walked from a fresh `unittest.TestLoader`
inside the suite, and both platform certifications separately reported
`loader.errors == []`; an import failure cannot silently shrink discovery.

## 28. Immutability guard demonstration

The required sequence was preserved at tests commit `fccc39ab`, before any
Phase 16 declaration:

- `tests.release.test_frozen_evidence`: 9 run, exactly one failure;
- `tests.companion.test_three_d_preservation`: 4 run, exactly one failure;
- both failures were the added-file control; no byte mismatch, deletion, or
  unrelated failure occurred; and
- each failure identified the same 20 committed paths:

```text
qualification/phase16/CONTRACT.md
qualification/phase16/CONTRACT_PINS.json
qualification/phase16/EVIDENCE_CUT_POLICY.md
qualification/phase16/FAILURE_AND_RECOVERY.md
qualification/phase16/FAILURE_RECOVERY_MATRIX.json
qualification/phase16/IDENTITY_CEREMONY.md
qualification/phase16/INTAKE_EXECUTION.md
qualification/phase16/INTAKE_STATUS.json
qualification/phase16/MATRIX.json
qualification/phase16/README.md
qualification/phase16/RECONCILIATION_AND_GATE.md
qualification/phase16/REVIEWER_HANDOFF.md
qualification/phase16/SECURITY_REVIEW_RECEIPT.md
qualification/phase16/STATE_MODEL.md
qualification/phase16/fixtures/review-blocked.json
qualification/phase16/fixtures/review-new-critical.json
qualification/phase16/fixtures/review-unsupported-shape.json
qualification/phase16/fixtures/review-valid.json
qualification/phase16/tools/security_review_intake_ops.py
qualification/phase16/tools/verify_phase16.py
```

Only afterward did guard commit `9c4f06d3` add
`qualification/phase16/` to each maintained “phases after the record” tuple.
Neither historical `EXEMPT_PREFIXES` collection changed. The rerun passed all
13 tests on Windows and Fedora. The refusal state (`fccc39ab`) and declaration
state (`9c4f06d3`) remain distinct commits.

## 29. Exact resulting release state

The six answers at certification are:

```text
OPERATIONAL READINESS: intakePathReady=true; 25/25 scenarios AS_EXPECTED
RECEIPT — BOUNDARY:   AWAITING_SUBMISSION (0 security-review intakes)
RECEIPT — WORKFLOW:   AWAITING_SUBMISSION
SECURITY ASSESSMENT:  no accepted real submission; no assessment exists
SECURITY GATE:        AWAITING_EXTERNAL_EVIDENCE
AUTHORIZATION:        EVIDENCE_PENDING; floorSatisfied=false
CANDIDATE DECISION:   REQUIRES_MORE_EVIDENCE
```

The authorization floor explicitly names all five missing sources:
`security-review`, `hardware`, `signing`, `second-approval`, and
`alpha-feedback`. The artifact is not authorized. “Intake ready” describes
the machinery only and does not upgrade any other line.

## 30. Limitations

1. No real independent reviewer was engaged and no real submission exists.
2. A matching stated observation proves contract coherence, not reviewer
   honesty or organizational independence; those remain human credibility
   judgments.
3. The preflight scanner is deliberately heuristic. A false positive requires
   a masked revision; real secret exposure requires separate incident handling.
4. Only the security-review receipt has the Phase 16 boundary view. The other
   four external floor sources retain their standing Phase 9/14 routes.
5. The real graph has no successor, so transfer behavior is proven only by
   marked scratch demonstrations.
6. CUT-001 represents the historical zero-evidence state. A future real
   submission needs a new, explicit cut; Phase 16 does not create one merely
   because the operator exists.
7. Platform-conditional skips are listed in sections 25 and 26. They do not
   hide a Phase 16 skip or failure.

## 31. What this phase did not prove

Phase 16 did not prove that the artifact is secure, free of Critical/High
findings, production-signed, independently approved, hardware-qualified,
Alpha-sufficient, or authorized. It did not prove that a future submission is
truthful, complete, artifact-bound, non-conflicting, or favorable. It did not
assign a reviewer, security owner, release authority, key authority, second
approver, or hardware owner. It did not resolve a real conflict, accept a real
risk, create a successor, transfer evidence, or ship a new product artifact.

Passing tests prove the repository's refusal and derivation machinery under
the tested inputs. They are not external evidence about `e906a48793d7`.

## 32. Next deterministic action

The next action is external and human: deliver a freshly prepared, pinned
handoff to a genuine independent reviewer. The reviewer must compute the
artifact identity from the bytes actually reviewed and submit the original
record and attachments without repository-side repair.

When a submission arrives:

1. preserve its original bytes;
2. run `inspect` and `validate` read-only;
3. invoke `receive` with the explicit receipt date and submitter;
4. preserve any rejection, incompleteness, mismatch, or credential refusal;
5. use a revision rather than editing an earlier record when correction is
   required;
6. bind through Phase 10 and reconcile through Phase 11;
7. make the next uniquely labelled explicit evidence cut with `--as-of` when
   required;
8. assemble read-only through Phase 14/13; and
9. run `sync-status` and report every resulting state without editorial
   upgrading.

Until that happens, the correct action is to preserve
`AWAITING_SUBMISSION`, not simulate progress in the real ledger.

## 33. Evidence inventory

Phase 16 committed 20 files before guard declaration:

| Class | Inventory |
| --- | --- |
| Contracts/guidance | `README.md`, `CONTRACT.md`, `SECURITY_REVIEW_RECEIPT.md`, `REVIEWER_HANDOFF.md`, `IDENTITY_CEREMONY.md`, `INTAKE_EXECUTION.md`, `RECONCILIATION_AND_GATE.md`, `EVIDENCE_CUT_POLICY.md`, `FAILURE_AND_RECOVERY.md`, `STATE_MODEL.md` |
| Derived/pinned views | `CONTRACT_PINS.json`, `MATRIX.json`, `FAILURE_RECOVERY_MATRIX.json`, `INTAKE_STATUS.json` |
| Fixtures | `review-valid.json`, `review-blocked.json`, `review-new-critical.json`, `review-unsupported-shape.json` |
| Tools | `tools/security_review_intake_ops.py`, `tools/verify_phase16.py` |

Primary file identities at certification:

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `CONTRACT_PINS.json` | 1,960 | `6effcb7748e47854c5f2855687525e5d081aa77c2c217a73efb107a07bd00f72` |
| `security_review_intake_ops.py` | 124,223 | `440532e1ee0e7c77570e8d551101c16c2a226c1d50d9aae5c2c37b7a9fc75669` |
| `verify_phase16.py` | 2,804 | `680295d80791664492cc47d0fff0e04145cd73d22e9d763daa464e429eaf0bbe` |
| `test_phase16_intake_operations.py` | 28,336 | `f27005b7bf710f2ce45ddd8f078126cd97db828874657f9f1b29624af4718274` |
| `test_phase16_gate_execution.py` | 28,136 | `a0a60109eb046a0ecc5f6af9f5c009bc1afdee2330a1fd2595ad172205f64dc9` |

`CONTRACT_PINS.json` records byte size and SHA-256 for ten Phase 11/15 handoff
inputs; verification refuses missing, extra, or drifted pins. The two generated
matrix hashes, status hash, ledger hash, cut hash, and register/status hashes
are recorded in sections 13, 16, 17, and 20.

The required commit sequence is preserved:

| Commit | Contents |
| --- | --- |
| `06b67f25ed971b8e19774315caf0547b08af7124` | `operations(phase16)`: contracts, handoff, ceremony, operator, fixtures, generated views, verifier, and owning-engine repairs |
| `fccc39ab8ceebdeb15548a4c7bf98bcfa6c247b1` | `tests(phase16)`: 84 dedicated tests plus owner regressions; undeclared guard-refusal state |
| `9c4f06d3413980499b89af27f6796297d3f06a0b` | `guards(phase16)`: deliberate declaration after both refusals; certification commit |
| this report-only commit | `report(phase16)`: this document |

The central result is therefore narrow and evidence-backed: **a real
independent security review can enter through one immutable boundary and travel
through validation, binding, reconciliation, sealed evidence cutting, and
release assembly without any repository-local shortcut turning readiness into
approval.**
