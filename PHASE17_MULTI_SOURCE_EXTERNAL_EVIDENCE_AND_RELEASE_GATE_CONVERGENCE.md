# Phase 17 — multi-source external evidence and release-gate convergence

## 1. Executive status

**PHASE 17 — EXTERNAL FLOOR OPERATIONS READY**

Phase 17 is implemented and verified. All five external authorization-floor
sources have an explicit operational route through the one Phase 9 immutable
intake boundary, retain source-specific semantics, and converge into one
deterministic floor and candidate view. The implementation can receive,
validate, preserve, bind, evaluate, cut, assemble, and refuse. It creates no
reviewer, machine result, production signature, approval, tester experience,
authority assignment, sufficiency policy, or release authorization.

Real external evidence remains zero. The five-source floor is 0/5. The final
candidate result is `REQUIRES_MORE_EVIDENCE`, not release authorization.

The guard certification commit is `4f173c4d994388f71bb3a971af1f60a377842281`.
The deliberately undeclared refusal commit is
`feff1527`.

## 2. Subject artifact

| Field | Derived value |
| --- | --- |
| Artifact | `e906a48793d7` |
| Relationship | `ROOT` |
| Image digest | `sha256:c87a6616008ce34f97840f63814e08fdb33574b52202fbb4841b7f5aa7f8562d` |
| Source commit | `e906a48793d74544b39c14cc3e35e0654f5311e2` |
| Frozen | yes |
| Changed by Phase 17 | no |
| Signing state | `UNSIGNED` |

No artifact was rebuilt, replaced, relabelled, mutated, or signed. Repository
HEAD was never used as the release-artifact identity.

## 3. Starting state

Phase 17 started from the completed Phase 16 branch tip `98656cf0`, whose
ancestry contains the supplied Phase 16 certification commit `9c4f06d3`.
The live Phase 9 ledger had zero entries and SHA-256
`b24ef74023cbd1d949053b8c9f842243c4e7d8818cb5b4dfcec1ab1fc0c1624b`.
Phase 16 reported `AWAITING_SUBMISSION`; Phase 11 reported
`AWAITING_EXTERNAL_EVIDENCE`; Phase 13 reported `EVIDENCE_PENDING`; and the
candidate decision was `REQUIRES_MORE_EVIDENCE`.

Those conclusions are unchanged.

## 4. Objective

The objective was to generalize the Phase 16 security-review operational
standard across security review, hardware validation, production signing,
second approval, and Alpha feedback, while keeping the artifact frozen and
making this equation executable:

```text
release floor = security review
             AND hardware validation
             AND production signing
             AND second approval
             AND Alpha sufficiency
```

One source cannot compensate for another. Operational pipelines do not count
as satisfied gates.

## 5. Existing engines

Phase 17 composes rather than forks the established owners:

| Owner | Reused responsibility |
| --- | --- |
| Phase 9 | immutable intake, revisions, seals, credential hygiene |
| Phase 10 | artifact graph and evidence applicability |
| Phase 11 | security reconciliation and security gate |
| Phase 12 | Alpha reports, triage, findings, program evidence |
| Phase 13 | authorities, separation, policies, risk, authorization, expiry/revocation |
| Phase 14 | router, dimensional hardware view, ordering, cuts, decision assembly, conflicts |
| Phase 15 | security-review execution carrier |
| Phase 16 | security receipt, validation, binding, reconciliation, and gate execution |

Phase 17 adds convergence and operator composition, not replacement engines.

## 6. Source registry

`qualification/phase17/SOURCE_REGISTRY.json` is closed over exactly five
sources. `genericFallback` is `null`, and unknown sources are refused rather
than routed to `generic-external-evidence`.

| Source | Canonical class | Primary owner semantics | Sufficiency form |
| --- | --- | --- | --- |
| `security-review` | `SECURITY_REVIEW` | Phase 16 receipt → Phase 11 gate → Phase 13 risk | reconciliation |
| `hardware` | `HARDWARE_VALIDATION` | Phase 8 protocol + Phase 14 dimensional evaluation | dimensional |
| `signing` | `PRODUCTION_SIGNING` | Phase 9 binding + Phase 13 key authority + verification proof | cryptographic binary |
| `second-approval` | `SECOND_APPROVAL` | Phase 13 separation/authority + Phase 14 ordering | binary with ordering |
| `alpha-feedback` | `ALPHA_TESTER_REPORT` | Phase 12 evidence + Phase 13 active owner policy | dimensional |

Every row records intake, binding, authority, expiry, revocation, conflict,
revision, whole-source, and required-status rules.

## 7. One-door evidence boundary

`receive` delegates the original path, attachment list, receipt date,
submitter, source, and revision pointer directly to Phase 9 `register`.
Phase 17 does not append to or dump `LEDGER.json`, create intake IDs, compute
ledger seals, or copy accepted evidence into a real intake directory.

AST enforcement proves:

- the only Phase 9 `register` call is inside `receive`;
- `receive` contains no write/copy operation;
- neither Phase 17 module opens append mode;
- no Phase 17 function calls a clock; and
- no Phase 17 ledger-dump path exists.

Fixture wrappers are terminally refused before this route.

## 8. Security-review source

The security row consumes Phase 16/11 state. A favorable reviewer assessment
does not contribute unless the Phase 11 gate is `SATISFIED`, applicable
Critical findings are resolved, conflicts are absent, and relevant accepted
risks stand at the cut.

Executed controls covered no review, blocking review, favorable scratch
review, unresolved Critical, conflicting review, expired risk, and wrong
artifact. The real result remains `AWAITING_EXTERNAL_EVIDENCE`.

## 9. Hardware source

Hardware stays per-machine and per-dimension. The evaluator retains separate
statuses for installation, encrypted boot, login, desktop, networking, Wi-Fi,
audio output, microphone, pre-rendered, 2D, native 3D, fallback 3D, voice,
Trust, reboot, persistence, and shutdown.

Submissions additionally require `HW-NNN`, operator pseudonym, machine ID,
installation-medium identity, independently observed artifact digest,
CPU/RAM/GPU/storage/firmware/Secure Boot/network facts, companion modes,
journeys, and evidence-backed `PASS` rows. One boot never becomes
`HARDWARE_PASS`. A finite machine set never becomes `SUPPORTED ON PCS`.

Passing installation with failing microphone remains exactly that. Native 3D
`NOT_SUPPORTED` plus fallback `PASS` remains two results; native 3D `FAIL` is
not rewritten to `NOT_SUPPORTED`. Contradictory graphics results across
machines remain attached to their machines and are never averaged.

## 10. Signing source

Phase 17 did not sign the subject artifact. Production signing contribution
requires:

- category `PRODUCTION ARTIFACT SIGNED`;
- submitted and independently recomputed digests equal to one another and the
  exact artifact;
- signer identity and standing `AUTH-KEY` authority;
- signing and verification methods;
- signature identifier and signature/verification artifact reference;
- a fully valid timezone-qualified timestamp or exact date; and
- verification result exactly `PASS`.

Wrong artifact, failed verification, missing recomputation, unauthorized,
expired/revoked authority, malformed time, and fixture submission all fail
closed. `SIGNING_DRILL` is structurally non-contributing. The real graph remains
`UNSIGNED`.

## 11. Second-approval source

The operational record names approver ID, authority role, independently
recomputed artifact digest, `APPROVED`/`REJECTED`/`CONDITIONAL`, timestamp,
relevant evidence cut, and conditions. Phase 9 retains backward readability
for the earlier two-approver record while accepting the new independent action
without rewriting it.

Only unconditional `APPROVED` by standing `AUTH-SECOND-APPROVER` after signing
and against the relevant cut can contribute. Tests refused pre-signing,
wrong-artifact, stale-cut, conditional, rejected, expired-risk, revoked
authority, signer overlap, and release-authority overlap cases. An authoritative
identity mapping detects differently spelled IDs belonging to the same person.

## 12. Alpha source

Alpha evidence remains owned by Phase 12. User reports, measured evidence,
reproduction evidence, hardware, accessibility, performance, and security
observations remain distinct. Unbound user evidence is retained as useful but
cannot contribute to an artifact-specific floor.

The real Phase 12 policy has all thresholds undefined, and the real Phase 13
policy registry has zero records. Therefore zero reports derive
`NO_EVIDENCE / SUFFICIENCY_UNDETERMINED`, and a 100-report scratch control with
no active policy also remains `SUFFICIENCY_UNDETERMINED`. Only an active,
artifact-applicable owner policy, `SUFFICIENT` evaluation, and no blocking
Alpha finding can contribute.

## 13. Source readiness vs satisfaction

Every floor row exposes separately:

```text
source_operational_ready
source_evidence_received
source_evidence_valid
source_artifact_bound
source_sufficient
source_contributes_to_floor
```

The real dashboard therefore truthfully shows five operationally ready sources
and zero satisfied sources. Readiness is machinery, not evidence.

## 14. Five-source floor

`qualification/phase17/FLOOR_STATUS.json` carries exactly the five required
rows. Each row records evidence IDs, validation, binding, effective/sufficiency
status, expiry, revocation, conflict, contribution, and reason.

The real floor derives 0/5 from the live ledger. No row is favorable because
its operator is ready.

## 15. Floor convergence

The convergence control executed 0/5, 1/5, 2/5, 3/5, 4/5, and 5/5. Zero
through four always make authorization impossible. Five mechanically proven
owner-engine results can satisfy the floor, but Phase 13 must still validate
the independent release-authority decision. An internal JSON with five `PASS`
claims, no evidence IDs, and no owner-engine provenance is refused.

No code counts votes or averages sources.

## 16. Cross-source conflicts

The global policy preserves all source meaning and chooses a human-decision or
more-blocking path:

- hardware microphone `PASS` on one machine does not erase Alpha microphone
  failures elsewhere;
- valid signing cannot overrule blocked security;
- second approval cannot overrule an Alpha release blocker; and
- a later cut observes a risk that expired after an earlier approval.

Conflicts are named and block convergence. The latest favorable record is not
preferred merely because it is favorable or recent.

## 17. Artifact applicability

All binding calls Phase 10 over the active artifact graph. Wrong-artifact
evidence derives `DOES_NOT_APPLY`; a source commit, branch name, or nearby
digest is not a substitute. Transfers require an explicit Phase 10 decision
over an explicit graph relationship.

## 18. Unbound evidence

An Alpha report without a digest remains unbound user evidence and does not
contribute. Hardware observations without verified artifact or machine/medium
identity likewise remain observational, not qualification. Useful unfavorable
or unbound evidence is not discarded merely because it cannot satisfy a gate.

## 19. Evidence cuts

A Phase 17 cut seals references to the Phase 14 cut, Phase 9 ledger, Phase 10
graph, Phase 11/16 security state, Phase 12 Alpha state, Phase 13 authorities,
risks and policies, source registry, source evaluations, evidence IDs, and
explicit `asOf`. It creates no second ledger and copies no evidence bytes.

Same inputs, cut ID, and `asOf` reproduced byte-identical cut bytes. Seal
tampering was refused. Post-cut evidence for each of the five sources was named
and excluded from the historical assembly. No real Phase 17 cut exists yet;
the committed cut count is zero.

## 20. Time semantics

All qualification time is operator/evidence supplied. No `now()`, `today()`,
UTC-now, or time-source call exists in Phase 17. Exact validation rejects date
prefixes, suffixes, impossible dates, incomplete dates, and full timestamps
without a timezone. The whole timestamp is parsed before a calendar component
is used for ordering.

## 21. Expiry

Hardware policy, authority assignment, accepted risk, signing authority, Alpha
policy, and authorization expiry are evaluated at explicit cuts. Where an
expiring input exists, silence cannot keep it standing. Expired hardware
policy, key authority, approver authority, and accepted risk controls all
removed contribution at later cuts.

## 22. Revocation

Assignment and authorization revocations are derived without editing originals.
Key and second-approver revocation controls removed contribution at the later
cut. Historical cuts remain bound to the records and explicit date that were
available then.

## 23. Revisions

Phase 9 revision IDs preserve original entries and bytes; effective status may
use a valid later revision. The implementation does not select an implicit
latest file. The matrix and owner suites retain security, hardware, signing,
approval, and Alpha revision behavior, while earlier cuts keep their original
intake ID lists and ledger hash.

## 24. Successor handling

A scratch `ROOT A -> REMEDIATES -> successor B` graph proved parent evidence
does not apply automatically to B. B begins evidence-pending and unsigned, with
no inherited authorization, signing, Alpha sufficiency, security result, or
hardware qualification. Phase 10 applicability must decide any evidence reuse;
authorization itself never transfers.

No real successor was built or recorded.

## 25. Secret hygiene

The matrix exercised bearer material in a reviewer package, a password in a
hardware log, private-key material in signing input, a credential assignment in
approval input, and an API/session token in Alpha input. Phase 9 detected and
quarantined/rejected the class before unsafe publication, without echoing the
matched value. Public signatures, fingerprints, certificates, and public keys
are not confused with private-key material.

## 26. Fixture demonstrations

All Phase 17 fixture wrappers carry `fixtureClass: TEST_FIXTURE_ONLY`. They
cover favorable/blocking security, passing/mixed hardware, production-shaped
signing, signing drill, independent/duplicate-role approval, Alpha report and
active fixture policy, full favorable, expired, wrong-artifact, conflict, and
insufficient universes.

Only unmarked inner shapes are exercised through production functions in
scratch or in-memory universes. Every wrapper is refused by real evaluation and
Phase 9 intake. The real immutable input set is byte-compared around the whole
scenario run.

## 27. Negative controls

Executed controls include:

| Control | Result |
| --- | --- |
| approving review + unresolved Critical | no security contribution |
| installation `PASS` + microphone `FAIL` | dimensional result, no global pass |
| signing drill | no signing contribution |
| signer = second approver | separation refusal |
| many Alpha reports + undefined policy | `SUFFICIENCY_UNDETERMINED` |
| wrong digest | no contribution |
| expired source | no later contribution |
| revoked authority | no contribution |
| favorable + blocking evidence | conflict/human-decision path |
| marked fixture to real path | rejected |
| 4/5 sources | authorization impossible |
| internal five-PASS JSON | refused as unproven |

## 28. Failure/recovery matrix

`MATRIX.json` contains 70 substantive executable scenarios. Every row carries
the required route, source, class, artifact, intake, validation, binding,
source evaluation, floor, cut, candidate, fixture/real, expected/observed, and
input-hash fields. All 70 observed outcomes equal expectations.

`FAILURE_RECOVERY_MATRIX.json` contains one matching recovery row per scenario.
The prescribed divergence path is stop, reproduce, patch the owning phase, add
an owner regression, re-derive historical outputs, and report conclusion
changes.

Generated identities on both validation targets:

| File | SHA-256 |
| --- | --- |
| Phase 9 ledger | `b24ef74023cbd1d949053b8c9f842243c4e7d8818cb5b4dfcec1ab1fc0c1624b` |
| Phase 17 matrix | `27f1d8318b2adb3421febf706bc38e092fdf63a1a65a899a48600ce5c2fc7309` |
| Failure/recovery matrix | `dd4db4cd98bc059eb44146e95a17b0860a507deeb62ef71aeb587705effd73f7` |
| Floor status | `1e5c5c707823f4657c2a091f212398b2857e169d707c0179f84d2c31576227c3` |
| Operations dashboard | `0a0fd345fc27c2e286f31a070ab33ac7fcb1be9e2e89fc3e39e1e98394ba9da7` |

## 29. Inherited defects found

Phase 17 proved two owner-level gaps before fixing them:

1. Phase 9 validated an evidence action date by prefix, so
   `2026-08-19junk` could pass the timestamp question even though receipt dates
   were exact. Phase 9 now validates exact possible calendar dates and permits
   full timestamps only when fully valid and timezone-qualified.
2. The Phase 9/14 second-approval intake/router recognized only the earlier
   two-approver shape, not the required independent second-authority action;
   Phase 14 also accepted date-only ordering but could not validate a full
   signing/approval timestamp. The owning engines now accept both record
   generations, route the new shape, and validate the full timestamp before
   comparison.

Owner regressions were added to Phase 9 and Phase 14, followed by Phase 17
integration regressions. No fix was hidden in the convergence wrapper.

## 30. Historical conclusions changed or unchanged

Historical conclusions are unchanged. The real ledger has zero entries, so no
previous evidence record depended on the corrected date or approval branches.
Phase 9, Phase 14, Phase 16, and Phase 17 verifiers all re-derived clean, and
the earlier matrices/status files remained unchanged. The correction narrows
future acceptance; it does not retroactively reclassify real evidence.

## 31. Test discovery

Explicit discovery at guard commit `4f173c4d`:

| Suite | Discovered | Loader errors |
| --- | ---: | --- |
| Release | 852 | `[]` |
| Portability | 205 | `[]` |

The Phase 16 release baseline was 729. Phase 17 added 123 discovered release
tests: 117 in the two dedicated Phase 17 modules and six owning-phase
regressions. Dedicated module counts are 44 operator/floor tests and 73 matrix
tests. Discovery is explicitly asserted by the suite.

## 32. Windows validation

Environment: Windows workspace, Python 3.14.5, guard commit `4f173c4d`.

| Run | Discovered | Run | Passed | Failed | Errored | Skipped | Result |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Release suite | 852 | 852 | 851 | 0 | 0 | 1 | `OK (skipped=1)`, 18.035s |
| Portability suite | 205 | 205 | 184 | 0 | 0 | 21 | `OK (skipped=21)`, 114.579s |
| Standing guards | 13 | 13 | 13 | 0 | 0 | 0 | `OK` |
| Phase 9–17 verifier commands | 13 | 13 | 13 | 0 | 0 | 0 | clean |
| Phase 17 scenarios | 70 | 70 | 70 | 0 | 0 | 0 | all expected |

The one release skip is the POSIX interpreter-path executable check. The 21
portability skips are the same environment/tool skips recorded at Phase 16:
Windows symlink privilege, POSIX-only path form, bash-dependent gate and
OS-release cases, unavailable PyYAML case, and unavailable ShellCheck. They are
skips, not passes; no Phase 17 test skipped.

The standing stable-release gate produced `NO-GO` and named missing physical
hardware, production signing, independent reviews, approvals, evidence,
reproducibility, candidate artifacts, matrices, vulnerability closure, and
blocker closure. Its nonzero refusal is the expected result.

## 33. Fedora validation

The same guard commit was fetched into the clean ext4 checkout
`/home/bunny/bunny-os-ref` and detached there.

| Environment field | Value |
| --- | --- |
| Distribution | Fedora release 44 (Forty Four) |
| WSL | WSL2, kernel `6.18.33.2-microsoft-standard-WSL2` |
| User | `uid=1000(bunny) gid=1000(bunny)` |
| Filesystem | `/dev/sdd`, `ext4`, mounted at `/` |
| Python | 3.14.3 |
| Commit | `4f173c4d994388f71bb3a971af1f60a377842281`, detached, clean |

| Run | Discovered | Run | Passed | Failed | Errored | Skipped | Result |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Release suite | 852 | 852 | 851 | 0 | 0 | 1 | `OK (skipped=1)`, 9.553s |
| Portability suite | 205 | 205 | 204 | 0 | 0 | 1 | `OK (skipped=1)`, 59.407s |
| Standing guards | 13 | 13 | 13 | 0 | 0 | 0 | `OK`, 4.612s |
| Phase 9–17 verifier commands | 13 | 13 | 13 | 0 | 0 | 0 | clean |
| Phase 17 scenarios | 70 | 70 | 70 | 0 | 0 | 0 | all expected |

The release skip is the prerequisite-qualified candidate-readiness assertion;
the portability skip is the Windows temporary-path form. They are skips, not
passes; no Phase 17 test skipped. Fedora reproduced every generated SHA-256 in
section 28 and remained Git-clean. Its stable-release gate also produced
`NO-GO` with the same blockers.

## 34. Guard demonstration

Before declaration, tests commit `feff1527` contained the complete Phase 17
tree and tests. Each standing guard ran its whole module and failed exactly one
added-file assertion:

| Guard | Run | Failures | Failure class |
| --- | ---: | ---: | --- |
| `tests.release.test_frozen_evidence` | 9 | 1 | 26 added Phase 17 paths |
| `tests.companion.test_three_d_preservation` | 4 | 1 | same 26 added paths |

There was no byte mismatch, deletion, or unrelated failure. Guard commit
`4f173c4d` then added only `qualification/phase17/` to each maintained
post-record tuple. Neither historical cut-time exemption changed. The rerun
passed all 13 guard tests on Windows and Fedora. Refusal and declaration are
distinct commits.

## 35. Current real evidence inventory

| Inventory | Real count |
| --- | ---: |
| Phase 9 ledger entries | 0 |
| Accepted security submissions | 0 |
| Hardware intakes | 0 |
| Signing intakes | 0 |
| Second-approval intakes | 0 |
| Alpha intakes / accepted reports | 0 / 0 |
| Phase 13 authority assignments | 0 |
| Active Phase 13 sufficiency policies | 0 |
| Risk acceptances | 0 |
| Authorizations | 0 |
| Revocations | 0 |
| Phase 17 real cuts | 0 |

Fixture records are excluded from every real count.

## 36. Current floor status

| Source | Operational ready | Real evidence | Effective status | Contributes |
| --- | --- | ---: | --- | --- |
| Security review | yes | 0 | `AWAITING_EXTERNAL_EVIDENCE` | no |
| Hardware | yes | 0 | `NO_EVIDENCE` | no |
| Signing | yes | 0 | `NO_EVIDENCE`; artifact `UNSIGNED` | no |
| Second approval | yes | 0 | `NO_EVIDENCE` | no |
| Alpha feedback | yes | 0 | `NO_EVIDENCE`; policy undefined | no |

Convergence: 0/5, unsatisfied, authorization impossible.

## 37. Candidate decision

| Field | Derived result |
| --- | --- |
| Phase status | `PHASE 17 — EXTERNAL FLOOR OPERATIONS READY` |
| Authorization state | `EVIDENCE_PENDING` |
| Candidate decision | `REQUIRES_MORE_EVIDENCE` |
| Release authorized | no |
| Stable release | no claim |

This is the most favorable result supported by the real evidence universe.

## 38. Limitations

Tests prove the implemented refusal and derivation behavior under the tested
inputs. They do not prove the artifact secure, compatible with PCs, correctly
signed, independently approved, sufficient for Alpha, authorized, or stable.
No ambient-clock monitor exists; expiry is evaluated only when an operator
provides `asOf`. Hardware support policy remains an external owner act, and the
real Alpha sufficiency policy remains undefined.

No Windows-to-Fedora byte difference was observed in generated Phase 17 views.

## 39. What remains external

The repository still cannot manufacture:

- an independent security reviewer and completed review;
- physical machines, operators, and protocol runs;
- a production key authority and valid production signature;
- an independent second approver;
- Alpha testers and their experience;
- assigned governance authorities;
- owner-approved hardware and Alpha policies;
- accepted risks or conflict decisions; or
- a release-authority record.

If remediation evidence eventually requires a product fix, the fix must create
a new artifact and Phase 10 graph edge. The frozen ROOT artifact is not mutated.

## 40. Next deterministic action

Exactly one next action is derived:

**Commission the independent security review using the canonical Phase 11/16
handoff for artifact `e906a48793d7`.**

When real evidence arrives, preserve its bytes, inspect and validate it,
receive it through Phase 9, bind through Phase 10, evaluate through the owning
engine, make an explicit cut, and assemble the candidate decision. Preserve
unfavorable outcomes. Do not convert real evidence into a fixture.

## Commit record

| Commit | Contents |
| --- | --- |
| `8b5715f5` | `operations(phase17)`: owner fixes, registry, contracts, operator, fixtures, generated views, matrix, and verifier |
| `feff1527` | `tests(phase17)`: 123 discovered release-test growth; deliberately undeclared refusal state |
| `4f173c4d` | `guards(phase17)`: measured declaration after both added-file refusals; certification commit |
| this report-only commit | `report(phase17)`: final evidence-backed status |

Primary implementation identities at certification:

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `external_floor_ops.py` | 86,597 | `5ca33f1f615a0a5d6b6a18a6f77ca329dcaa04cb7f653fdcd281e0170fd10bd8` |
| `verify_phase17.py` | 2,134 | `880cab13fc54864c9b3025a4388a8cd077c18628c7b993030d65608a1a43fc53` |
| `test_phase17_external_floor.py` | 20,345 | `df4a2adb3053b2504587aa788f8ee223a8bc353d577aee36baef0142911a8351` |
| `test_phase17_matrix.py` | 2,772 | `46eb5a4929bd42290a8793f94aeb2169160b54c6396140ff65f7cc7235655bed` |

The narrow result is therefore complete: the five external evidence sources
can enter one immutable boundary and converge without semantic collapse, while
zero real evidence still means zero satisfied gates and no release authority.
