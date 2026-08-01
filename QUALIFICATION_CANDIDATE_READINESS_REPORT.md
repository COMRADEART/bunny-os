<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Qualification candidate readiness report

Date: 2026-07-30
Candidate commit: `79bb99ddb39d8a5dbc279629f43b23346fb0e5e8` (scan-derived evidence)
Qualification target commit: `9ea5459bdaf122f8c5999683b2c8961555826954` (both builders)
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
| 3 | Independent reproducibility passed | `BLOCKED` | ci-infrastructure | measured 2026-07-30, twice. Attempt 1: `NON_REPRODUCIBLE`, 15 files. Attempt 2: 13 of 15 fixed, 2 remained. Attempt 3 measured *why* rather than assuming — the two databases differed in content, not encoding, and the causes were an unfrozen build clock and an unpinned mtime. Fixed and re-measured; see `LOCAL_HERMETIC_REPEATABILITY_REPORT.md`. Still `BLOCKED` regardless of that result: the retained inputs are not published, so no independent builder can obtain them. One token scope — `gh auth refresh -h github.com -s write:packages,read:packages` |
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
committed, carefully written, and had never been executed. Reaching a build that
completed took seven dispatches, and each failure was a real defect that could
only be found by running it:

1. The pinned base image digest no longer existed. `fedora-bootc:44` is rebuilt
   daily and old digests are garbage collected. The local Fedora builder still
   built against it, because podman had the layers cached — **the defect was
   invisible from the machine that had it.**
2. `crun` refused the OCI runtime spec version Ubuntu's podman writes.
3. Podman fell back to the `vfs` storage driver: 2m24s per `COPY`, 32 minutes
   spent copying directories before failing for another reason.
4. The storage driver could not be changed under the runner's pre-initialised
   container store.
5. The SBOM step was killed with an empty log and `cancelled`. Diagnosed as disk
   exhaustion, which was wrong: the next run entered that step with 28 GB free
   and died anyway. The constraint is memory — 7.8 GiB on the runner against a
   1.85 GB archive holding 164,962 entries.
6. A `[storage]` section replaces podman's defaults wholesale, so `runroot` has
   to be written even when the intent is to keep it.
7. The verify job used a flat artifact layout that `upload-artifact` never
   produces; the build job had already succeeded.

None of these is exotic. All seven are ordinary properties of a hosted Ubuntu
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

## 2026-07-30 addendum: after the hosted builder ran

`independent-reproducibility` is still `BLOCKED`, and the reason changed.

Before: no hosted builder record existed, so no pair existed, so no comparison
was possible. Sixteen of seventeen dimensions were `NOT_COLLECTED`.

After: a hosted builder record exists (`hosted-ci-30566412012`, GitHub-hosted
`ubuntu-24.04`), a local schema-2 record exists, the pair is declared, and
sixteen of seventeen dimensions were collected from both. The comparison reports
`NON_REPRODUCIBLE`:

* **11 dimensions match**, including the file tree (164,356 paths), permissions,
  ownership, the package inventory (6,076 packages) and the kernel.
* **5 differ**, driven by fifteen files out of 104,247 — all build-environment
  state: a random `brlapi.key`, seven fontconfig caches, the rpm and dnf
  databases, two `countme` counters.
* **1 is not collectable** from an archive-only build: a bootc image carries no
  SELinux xattrs in its layers.

The pair is additionally not certified independent, because `skopeo`, `python3`
and `image-builder` differ between the builders.

**Prerequisite count: unchanged at 2 of 14.** `licence-gate` and
`development-signing-drill` pass; the other twelve block.

What this addendum adds to the report above is not a changed count but a changed
kind of evidence. `independent-reproducibility` used to be an absence. It is now
a measurement, with fifteen named files and a dependency-ordered list of what
would move it, in `INDEPENDENT_REPRODUCIBILITY_REPORT.md`.

## Addendum — 2026-08-01, the TPM boot-reset investigation

The software-TPM boot reset that had been carried as a measured product
`FAIL` is root-caused and closed: it was shim `fbx64.efi`'s designed
one-time boot-option-restoration reboot, taken because a TPM is present,
recorded as a dead guest by a harness running QEMU with `-no-reboot`
(`TPM_GRUB_RESET_ROOT_CAUSE.md`, confidence `CONFIRMED`). GRUB never ran in
any failing boot.

**Prerequisite count: this addendum does not change it, and does not predict
it.** Software-TPM boot is not one of the fourteen prerequisites. The count
is whatever `python scripts/release.py gate --kind qualification-candidate`
calculates from the evidence in the tree; nothing here was written to move
it, and no evidence was relabelled to make it move. Specifically:

* No artifact byte changed. The fix is Path A, harness-only, so the archive
  authority (Commits G/H/I/J) and every digest bound to it are untouched.
* Prerequisite 10, `physical-hardware`, is unchanged at `PENDING_HARDWARE`.
  Every record this pass produced is `qemu-kvm` or `qemu-tcg` evidence, and
  the importer emits `physicalTpm: NOT_RUN` unconditionally — no
  software-TPM record can move a hardware claim, by construction rather
  than by convention.
* Prerequisite 7, `encryption-matrix`, is unchanged at `NOT_RUN`. Its
  `tpm-fallback` row still has nothing to rest on: no TPM feature exists in
  the product to test.

What this addendum adds is the same kind of change the reproducibility
addendum above describes — not a moved count, but a changed kind of
evidence. A blocking symptom that was a measured failure of unknown cause is
now a measured, classified, reproduced-and-explained behaviour with a
mechanism, a source citation, and a regression matrix behind it.
