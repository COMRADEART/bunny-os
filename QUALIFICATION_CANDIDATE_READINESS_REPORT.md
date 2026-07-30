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

## The one prerequisite that costs a button

`independent-reproducibility` reports `BLOCKED` with the dependency *"hosted CI run
of .github/workflows/independent-builder.yml"*.

The workflow is committed and has never been dispatched. It checks out an exact SHA,
pins the base digest, pins syft and grype, disables the pip cache, asserts an empty
output tree, records eleven environment facts, emits a schema-2 builder record with
a real `workflowRunId`, emits provenance with a 90-day expiry, uploads the archive,
SBOM, package inventory, manifests and logs, and verifies the bundle on a *second*
runner.

One prerequisite step remains: `BUNNY_ARCHIVE_ONLY=1` was added to
`build/scripts/build-image.sh` this phase so a hosted Ubuntu runner can build
without `image-builder`, and that change has not been exercised on a Fedora host.

Of the fourteen, this is the only one that needs nothing but a workflow dispatch.

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
