<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Qualification candidate readiness report

Date: 2026-07-30
Candidate commit: `79bb99ddb39d8a5dbc279629f43b23346fb0e5e8`
HEAD: `80df25b09f6578276d18c8a82f15c47dd8959740`
Result: **2 of 14 prerequisites satisfied. No artifact may be labelled
release-qualified.**

```text
$ python scripts/release.py gate --kind qualification-candidate
qualification candidate gate: BLOCKED
```

Machine-readable: `build/out/qualification/qualification-candidate.json`.
Dashboard: `build/out/qualification/stable-evidence-dashboard.md`.

## What a blocking candidate gate does and does not forbid

It **does not** forbid building an artifact. A candidate is a thing that may be
built and examined, and examining one is how the remaining evidence gets produced.

It **does** forbid calling one release-qualified.

That distinction is why this is a separate gate from `stable-release` rather than a
stage of it, and `evaluate_candidate_gate` states it in its own output.

## The fourteen prerequisites

| # | Prerequisite | State | Owner | Next action |
|---|---|---|---|---|
| 1 | Licence gate passed | **PASS** | engineering | — |
| 2 | Vulnerability gate passed | `PENDING_EXTERNAL_REVIEW` | independent-reviewer | commission the review; `reviews/security/REQUEST.md` |
| 3 | Independent reproducibility passed | `BLOCKED` | ci-infrastructure | dispatch `.github/workflows/independent-builder.yml` |
| 4 | Development signing drill passed | **PASS** | engineering | — |
| 5 | Independent recovery media passed | `NOT_RUN` | engineering | build a signed recovery ISO |
| 6 | Installation matrix passed | `NOT_RUN` | engineering | build a live installer ISO |
| 7 | Encryption matrix passed | `NOT_RUN` | engineering | complete an installation |
| 8 | Update matrix passed | `NOT_RUN` | operated-release | publish a signed update manifest |
| 9 | Rollback matrix passed | `NOT_RUN` | operated-release | keep a previous release |
| 10 | Physical hardware evidence passed | `PENDING_HARDWARE` | physical-hardware | acquire one x86-64 UEFI machine with Secure Boot and TPM 2.0 |
| 11 | Accessibility evidence passed | `PENDING_EXTERNAL_REVIEW` | independent-reviewer | commission the review |
| 12 | Independent reviews passed | `PENDING_EXTERNAL_REVIEW` | independent-reviewer | four identified external reviewers |
| 13 | Second production signer available | `BLOCKED` | second-authorised-signer | identify a second signer and hold a key ceremony |
| 14 | Protected approvals complete | `PENDING_OWNER` | owner-decision | the owner must decide; this is not an engineering task |

## The eight states, and why there are eight

Only `PASS` satisfies anything. The other seven all mean "not satisfied", and they
mean it for seven different reasons with seven different resolutions.

| State | Meaning | Count |
|---|---|---|
| `PASS` | measured, current, and bound to this commit | 2 |
| `FAIL` | measured and negative | 0 |
| `BLOCKED` | cannot be measured yet; a dependency is unmet | 2 |
| `NOT_RUN` | nobody has run it | 5 |
| `STALE` | it passed, but at another commit or too long ago | 0 |
| `PENDING_EXTERNAL_REVIEW` | needs an identified external party | 3 |
| `PENDING_OWNER` | needs a decision that is not an engineering decision | 1 |
| `PENDING_HARDWARE` | needs a physical device | 1 |

Collapsing these into one number is how a project spends a month retrying something
that needed a purchase order. **There is deliberately no aggregate percentage** — a
completion figure reads as nearly done when the missing part contains every blocker
that needs a third party, and a test asserts the dashboard contains no `%`.

## Fail-closed, in two specific ways

**An absent observation is not an error.** A prerequisite with no recorded
observation takes its declared `absentState`, and none of the fourteen absent states
is `PASS`. Adding a prerequisite therefore cannot accidentally make a candidate pass.

**A passing check with stale evidence is not a pass.** Staleness and wrong-commit are
applied *after* the observed state:

- evidence generated from a commit other than the candidate becomes `STALE`, with
  the reason recorded in the row;
- evidence older than 90 days becomes `STALE`, with the age recorded.

Both are silent failures otherwise: the check passed, once, somewhere.

## The prerequisite that was described as costing a button

This section previously read:

> Of the fourteen, this is the only one that needs nothing but a workflow
> dispatch.

That was wrong, and the way it was wrong is worth recording. The workflow was
committed, carefully written, and had never been executed. Dispatching it took
five attempts, and each failure was a real defect that could only be found by
running it:

1. The pinned base image digest no longer existed. `fedora-bootc:44` is rebuilt
   daily and old digests are garbage collected. The local Fedora builder still
   built against it, because podman had the layers cached — **the defect was
   invisible from the machine that had it.**
2. `crun` refused the OCI runtime spec version Ubuntu's podman writes.
3. Podman fell back to the `vfs` storage driver: 2m24s per `COPY`, 32 minutes
   spent copying directories before failing for another reason.
4. The storage driver could not be changed under the runner's pre-initialised
   container store.
5. The runner ran out of disk during SBOM generation and reported `cancelled`
   with an empty log.

None of these is exotic. All five are ordinary properties of a hosted Ubuntu
runner, and none was visible by reading the workflow. "The workflow is committed"
and "the workflow works" are different claims, and only the second is evidence.

The general lesson for the other thirteen prerequisites: an unexecuted mechanism
is not a satisfied prerequisite that happens to be waiting. It is an untested
one. The five `NOT_RUN` rows below should be read with that in mind.

## The five `NOT_RUN` rows are three actions

| Action | Closes |
|---|---|
| Build a live installer ISO | 6, and makes 7 reachable |
| Build a signed recovery ISO | 5 |
| Publish a signed update manifest and keep a previous release | 8, 9 |

All three are engineering on the Fedora builder and none needs money.

## What no amount of further work in this repository moves

Rows 2, 10, 11, 12, 13 and 14 — six of the fourteen. They need an external reviewer,
a device, a second person, or an owner's decision. Misfiling any of them as an
engineering task is how a project talks itself into self-reviewing, so each row
carries an owner and a test asserts that no third-party row's next action says "run
the check".

## Relationship to the other gates

| Gate | State | Reads this |
|---|---|---|
| `source` | **PASS** | no |
| `qualification-candidate` | **BLOCKED** | yes — these fourteen |
| `stable-release` | **NO-GO** | no — its own ten requirements |
| `oem-pilot` | **BLOCKED** | no — the stable gate plus six of its own |
| `enterprise-pilot` | **BLOCKED** | no — the stable gate plus six of its own |
| `sync-pilot` | **BLOCKED** | no — the stable gate plus seven of its own |

Deliberately not nested. A passing candidate gate contributes nothing to a pilot,
and a passing source gate contributes nothing to either.

## Regenerating

```text
make gate-qualification-candidate
make qualification-candidate-readiness
make stable-evidence-report

python scripts/release.py gate --kind qualification-candidate
```

The dashboard is generated from the same evaluation as the evidence report, so the
two cannot disagree. A report saying `BLOCKED` beside a dashboard saying `PASS` is
exactly the failure the evidence model exists to prevent.
