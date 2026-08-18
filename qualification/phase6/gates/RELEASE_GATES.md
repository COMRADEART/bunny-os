# Phase 6 release-gate matrix

**Subject artifact: `e906a48793d7`**, image digest
`sha256:c87a6616008ce34f97840f63814e08fdb33574b52202fbb4841b7f5aa7f8562d`.

Every row states a result, the artifact it binds to, the evidence, and whether
it blocks. Result values are §20's, and only §20's: `PASS`, `FAIL`, `BLOCKED`,
`NOT_RUN`, `NOT_SUPPORTED`, `CONDITIONAL`.

Nothing in this file was edited after a result was known in order to improve how
it reads. The ten blocking conditions were committed at `97aaf208`, before any
Phase 6 measurement ran.

---

## 1. Two questions, still kept apart

Phase 5 established this and it holds. **"Did the qualified journey pass?"** and
**"Is the matrix complete?"** are different questions, and a single column
merging them would be true of neither.

`python scripts/release.py gate --kind qualification-candidate` answers the
second. Its output is **byte-identical** before and after every Phase 6 change:

    qualification candidate gate: BLOCKED
      ok      PASS                     Licence gate passed
      BLOCKED PENDING_EXTERNAL_REVIEW  Vulnerability gate passed
      ok      PASS                     Independent reproducibility passed
      ok      PASS                     Development signing drill passed
      BLOCKED NOT_RUN                  Independent recovery media passed
      BLOCKED NOT_RUN                  Installation matrix passed
      BLOCKED NOT_RUN                  Encryption matrix passed
      BLOCKED NOT_RUN                  Update matrix passed
      BLOCKED NOT_RUN                  Rollback matrix passed
      BLOCKED PENDING_HARDWARE         Physical hardware evidence passed
      BLOCKED PENDING_EXTERNAL_REVIEW  Accessibility evidence passed
      BLOCKED PENDING_EXTERNAL_REVIEW  Independent reviews passed
      BLOCKED BLOCKED                  Second production signer available
      BLOCKED PENDING_OWNER            Protected approvals complete

That the tool did not move is the point. Phase 6 took a product decision that
changes what the release must demonstrate; it did not relabel anything the tool
counts.

---

## 2. The matrix

| Gate | Result | Artifact | Evidence | Blocking? |
| --- | --- | --- | --- | --- |
| Installation | **PASS** | `e906a487` | encrypted install from the RC's own ISO, `findings: []` | no |
| Encryption | **PASS** | `e906a487` | two encrypted boots | no |
| First boot | **PASS** | `e906a487` | `g1`, wizard at step 1 of 10 | no |
| Login / session | **PASS** | `e906a487` | real greeter, typed password, `g1` + `g10` | no |
| Voice | **PASS** | `e906a487` | `voice-phase3-b`, exit 0, 19 stages | no |
| Trust | **PASS** | `e906a487` | `g12` / `g13`, both directions, re-graded under the extracted grader | no |
| Persistence | **PASS** | `e906a487` | `g2`→`g3`→`g4`, two reboots | no |
| Companion | **PASS** | `e906a487` | modes survive two reboots | no |
| Shutdown | **PASS** | `e906a487` | clean ACPI on every boot of the chain | no |
| Reference suite | **PASS** (CLEAN) | tree, not artifact | 8 full runs × 5 988 tests, 0 unexplained failures | no |
| Rollback — product | **PASS** | `e501218f` → `e906a487` | `bootc rollback` + reboot; deployment identified from the kernel's own `ostree=`; all five user-state markers survive | no |
| Rollback — matrix | **NOT_RUN** | — | 0 PASS of 5; the harness now exits 5 NOT_RUN honestly | **yes** |
| **Update** | **NOT_SUPPORTED** | `e906a487` | approved unsupported-update policy + 18/18 refusal checks with a failing negative control | no — see §3 |
| Update — matrix | **NOT_RUN** | — | 1 PASS of 13, unchanged and unwaived | no — see §3 |
| Security findings | **BLOCKED** | `e906a487` | 80 advisories, 8 Critical, all `PENDING_REVIEW`; exposure measured per Critical | **yes** |
| Independent security review | **NOT_RUN** | — | no reviewer; package prepared and self-checking | **yes** |
| Physical hardware | **NOT_RUN** | `e906a487` bound | no machine; three journeys with expectations written first | **yes** |
| Production signing | **NOT_RUN** | `e906a487` | **no signature file exists anywhere**; no production key | **yes** |
| Second signer / approvals | **NOT_RUN** | — | one person | **yes** |
| Alpha user validation | **NOT_RUN** | `e906a487` bound | 0 testers, 0 records | **yes** |
| Artifact identity | **CONDITIONAL** | `e906a487` | all digests re-verified; `repeatedBuildComparisonPerformed: false`; upstream base tag has moved | **yes** — condition 10 |
| Licence | **PASS** | — | 7 of 7 requirements | no |
| Independent reproducibility | **PASS** | other commits | three-builder result belongs to the commits measured for it | no |
| Development signing drill | **PASS** | constructed inputs | 9/9 | no |
| Independent recovery media | **NOT_RUN** | — | no signed recovery ISO | **yes** |
| Accessibility evidence | **FAIL** | — | 0 PASS / 12 NOT_RUN / **2 FAIL** | **yes** |

**The accessibility row is the only outright `FAIL` in the project.** Two
scenarios record a defect, not an absence. It is carried unchanged from Phase 5;
Phase 6 did no accessibility work and does not present that as neutral.

---

## 3. Why the update gate reads NOT_SUPPORTED while its matrix reads NOT_RUN

They are answering the two different questions of §1, and both answers are
honest.

**The gate is `NOT_SUPPORTED`** because the product decision is that this release
class ships no update capability — taken by a named accountable owner, bound to
this artifact digest, with an expiry and a review condition, and with the
refusal **measured**: 18 of 18 checks against the artifact's own image, with a
negative control that failed as required.

**The matrix is `NOT_RUN`** because none of its thirteen scenarios was executed,
and `waivedScenarios` is deliberately empty. Marking them `NOT_APPLICABLE` would
have made the matrix complete without anything having been measured. That move
was available, it would have turned a blocking row green, and it was not taken.

Blocking condition 7 is satisfied by the policy, not by the matrix. Checked by
`python scripts/release.py update-support-policy`.

---

## 4. The ten blocking conditions, scored

| # | Condition | Met? | Why |
| ---: | --- | --- | --- |
| 1 | Independent security review resolved | **NO** | no reviewer exists |
| 2 | Critical/High findings dispositioned | **NO** | 44 of 44 remain `PENDING_REVIEW`; the tooling refuses any other value without a completed review |
| 3 | Physical hardware qualification complete | **NO** | no machine |
| 4 | Production signing established | **NO** | no key; and no signature file exists for this artifact |
| 5 | Second approval present | **NO** | one person |
| 6 | Update trust architecture resolved | **YES** | outcome B, declared, bound, owned, expiring, and refusal-qualified |
| 7 | Update matrix backed by an approved policy | **YES** | admissible policy; `update-support-policy` exits 0 |
| 8 | Rollback evidence binds to the artifact chain | **YES** | `e501218f` → `e906a487`, both digests named, booted deployment identified from `ostree=` |
| 9 | No unresolved release-blocking Alpha defects | **NO** | zero testers; unmet, not vacuously met |
| 10 | Artifact identity reproducible and verifiable | **NO** | digests verified and base retained, but `repeatedBuildComparisonPerformed: false` for this artifact |

**Three of ten met. Two of them moved in Phase 6.**

Conditions 1, 3, 4, 5 and 9 were recorded as unmet **in advance**, at
`97aaf208`, before any measurement ran. Not one condition was weakened after a
result was seen, and no exception was recorded.

---

## 5. What Phase 6 moved

| Gate | Before | After | By what |
| --- | --- | --- | --- |
| Update | BLOCKED / design gap | **NOT_SUPPORTED** | a product decision with a measured refusal |
| Condition 7 | unmet | **met** | an admissible policy that waives nothing |
| Condition 8 | unstated | **met** | rollback evidence bound to both digests |
| Security exposure | "not determined for this scan" | **measured per Critical** | version + symbol analysis of the shipped binaries |
| Artifact identity | recorded | **re-verified from the bytes** | the baseline freeze |
| Production signing | "development-signed" | **unsigned — measured** | `find … -name '*.sig'` returns nothing |

Two of these make the position **worse** than the record said it was. The
artifact carries no signature at all, and Phase 5's stated evidence about which
binaries carry the vulnerable `x/crypto` packages was wrong. Both are recorded
in the direction the measurement pointed.

---

## 6. What no repository change can close

| Gate | Why |
| --- | --- |
| Independent security review | It is independent. Intake rejects a reviewer matching a project principal. |
| Physical hardware | There is no machine. |
| Production signing | A production key, held under controlled access, requiring a second person. |
| Second signer / approvals | A decision by a person with the authority. |
| Alpha validation | Users. |

Five gates, five people-or-hardware problems. Engineering can move the rollback
harness, the recovery media and the accessibility failures; it cannot move
these.
