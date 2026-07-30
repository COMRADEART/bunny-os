<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Qualification evidence closure report

Date: 2026-07-30
Branch: `feature/qualification-evidence-closure`
Base commit: `80df25b09f6578276d18c8a82f15c47dd8959740`

## Result

**Every technically automatable evidence task is complete. Nothing that needs a
hosted runner, a device, a second person or a third party has been produced, and
none of it is claimed.**

```text
Source gate:               PASS
Qualification candidate:   BLOCKED   (2 of 14 prerequisites satisfied)
Stable release:            NO-GO
OEM pilot:                 BLOCKED
Enterprise pilot:          BLOCKED
Encrypted-sync pilot:      BLOCKED
```

That is the outcome the brief describes as honest and acceptable, and it is the
one reached.

## What changed, and what it cost to be accurate

Three results are worse-looking than the previous phase's and are more accurate.
They are listed first because a report that leads with its improvements and
buries its regressions is the thing this project's evidence model exists to
prevent.

### 1. Reproducibility went from "three of four claims established" to `INCONCLUSIVE`

The previous comparison asked three questions — archive digest, file contents,
package manifest — and answered them well. This phase asks **seventeen**, and
sixteen of them were never collected:

```text
outcome: INCONCLUSIVE
  MATCH          1: rawArchive
  NOT_COLLECTED  16: bootConfiguration, desktopEntries, extendedAttributes,
                     fileDigests, filesystemTree, initramfs, kernel,
                     normalisedArchive, ociLayers, ownership, packageInventory,
                     permissions, sbom, schemas, selinuxLabels, systemdUnits
```

Nothing regressed. `NOT_COLLECTED` is a third state alongside `MATCH` and
`DIFFER`, and it is the load-bearing one: a dimension nobody measured cannot
contribute to a `REPRODUCIBLE` verdict. The previous phase's summaries — 83
archive members with 0 differing, 6076 package entries identical — are real and
are retained in `operations/data/build-comparison.json` as prior measurements.
They are not promoted to dimension comparisons, because what was committed is a
summary and a five-entry sample, and comparing a summary against itself
establishes nothing.

This is the difference between a comparison and a formality.

### 2. The stable evidence record had invalidated itself, and now cannot

`stable-evidence-report` reported **0 passing categories and 20 missing** at the
start of this phase, where the previous report said 2 passing and 18 blocking.
Every one of the twenty records failed with:

```text
generated from commit 79bb99ddb39d but the candidate is 80df25b09f65;
evidence does not transfer between commits
```

The commit-binding rule was correct and the caller was wrong. Evidence was being
compared against `HEAD`, so **committing the record changed `HEAD` and invalidated
the record in the same act**. Two categories that genuinely passed reported as
stale for no reason but being written down.

The fix is a declared candidate commit. `operations/data/release-evidence.json`
now carries `candidateCommit` — the commit that was built and measured — and the
gate compares against that. Wrong-commit evidence still blocks, and is tested.
Whether the candidate is still `HEAD` is reported separately, because qualifying
an older commit is legitimate for a release candidate and must be visible:

```text
candidate commit: 79bb99ddb39d, HEAD: 80df25b09f65
  Evidence is bound to the candidate commit, not to HEAD. A candidate behind HEAD
  is legitimate — a release candidate qualifies one commit — but the tree has
  moved since the evidence was measured and a rebuild is needed before
  publication.
```

The record now reports its true position again: **20 records, 18 blocking, Build
and Licence passing.**

### 3. The candidate gate reports 2 of 14, where nothing reported a candidate position before

There was no candidate readiness measurement. There is now, and it is 2 of 14.

## The per-CVE reachability framework

The previous phase narrowed 59 findings to one question about 24. This phase
built the apparatus that question needs and used it, and the answer is still
`Unknown` for all 24 — which is the honest result and was the expected one.

### What was measured that had not been

The scan records each finding's carrier as an **ostree object digest**, not an
installed path, because `fedora-bootc` ships an object store. Reading those
digests out of the committed scan produced a fact nobody had extracted:

**all 24 Critical and High findings are carried by exactly four distinct objects.**

| Carrier object | Blocking advisories | Modules |
|---|---|---|
| `…8fbfb47329…` | **15** | x/crypto, selinux, fulcio, docker, x/net |
| `…8cc9b0248b…` | **7** | buildkit, podman/v5, grpc, otel |
| `…755cc7cfe2…` | **1** | x/text |
| `…eacf5a37b7…` | **1** | linux-kernel |

That is a materially better starting point for a reviewer than 24 independent
questions: it is four binaries to identify and two Go binaries to analyse.

### A finding that changes one advisory's analysis

The single-advisory carrier `…755cc7cfe2…` is the object the previous phase
identified as **`toolbox`** — which package minimisation removed. `rpm -q toolbox`
reports not installed and `/usr/bin/toolbox` is absent from the minimised image;
the object survives in a lower base layer because `dnf remove` cannot remove an
object from a layer's store.

If that attribution is confirmed, `GO-2026-5970` (`golang.org/x/text`) has **no
installed executable to invoke**, and its invocation analysis differs from the
other 23. It remains `Unknown` because the attribution is not confirmed and
question 7 is unanswered either way. It is recorded as the second question in
`reviews/security/REQUEST.md`.

This is also, incidentally, the first concrete security consequence anyone has
found for the package minimisation the previous phase performed — and it is a
change in *analysis*, not in the scan count. The scan count still has not moved,
and no claim is made that minimisation reduced risk.

### What was deliberately not produced

| Field | Value | Why not measured |
|---|---|---|
| `vulnerableFunctionOrSubsystem` | `unknown` | naming a function without the advisory's own description of it is a guess dressed as evidence |
| `elfBuildId` | `unknown` | requires the binary |
| `strippedState` | `unknown` | requires the binary |
| `exportedSymbols` | `[]` | requires the binary |
| `sourceRpmReference`, `debuginfoReference` | `unknown` | requires acquisition from Fedora infrastructure |
| carrier binary | `unknown`, with three candidates named | requires `ostree ls` inside a mounted deployment |

`analyse-cve-symbols` exits 2 on this host and says why: the binaries are not
present and four of the seven ELF tools are absent. That is the state of the
analysis, not a failure of the tooling.

### The rule that does the most work

`release/cve.py` refuses a `Not present` conclusion whose only support is a symbol
observation, for **every** combination of stripped state and language — including
an unstripped C binary, because a file-static or inlined function is absent from
that symbol table too. `classify_symbol_evidence` returns
`sufficientForNotPresent: False` in all twelve cases the test suite enumerates.

For Go specifically the refusal is stronger and states why: the compiler inlines
across package boundaries and the linker rewrites call graphs, so neither the
presence nor the absence of a module-level name settles whether the vulnerable
instructions were emitted.

## Deliverables

| Workstream | Deliverable | State |
|---|---|---|
| 1 | `.github/workflows/independent-builder.yml`, 4 jobs | **prepared, not executed** |
| 2 | `release/builders.py` — schema-2 identity, boundary rather than identifier | complete |
| 3 | 4 accepted pairings, 8 adversarial rejections | complete |
| 4 | `release/normalisation.py` — 8 normalisable properties, 7 protected, raw + normalised digests | complete |
| 5 | `release/comparison.py` — 17 dimensions, 3 states, 4 outcomes | complete |
| 6 | `release/provenance.py` — every claim recomputed or held locally | complete |
| 7 | `release/cve.py`, `security/reachability/`, 29-field analysis + 12-field mapping | complete |
| 8 | `release/acquisition.py`, Fedora-only hosts, per-target plan | plan complete; **no artifact acquired** |
| 9 | `scripts/reachability.py analyse-symbols`, absent-symbol discipline | tooling complete; **nothing collected** |
| 10 | 12-field vulnerable-path mapping, `unknown` retained | complete; all 24 unmapped |
| 11 | 5 proof classes with per-class evidence requirements | complete |
| 12 | 24 review bundles × 9 files | complete |
| 13 | Per-finding disposition; no numeric score anywhere in the model | complete |
| 14 | `IndependentReviewRecord`, signed, digest-verified, commit-bound | complete |
| 15 | 4 × `reviews/*/REQUEST.md`, 10 sections each | complete; **none sent** |
| 16 | `bunny-os qualification collect` — 17-field allow-list, 12 excluded categories | complete; **never run on a device** |
| 17 | 21 guided tests; `NOT_RUN` cannot become `PASS` | complete |
| 18 | 3 signer roles; the word "certified" refused in code | complete |
| 19 | `release/accessibility.py` — 17 flows, 7 critical | complete; **0 flows driven** |
| 20 | `docs/SECOND_SIGNER_ONBOARDING.md`, `docs/TWO_PERSON_RELEASE_APPROVAL.md` | complete; **no second signer** |
| 21 | Two-person development drill | **PASS — 9/9** |
| 22 | 14 machine-readable prerequisites, fail-closed | complete |
| 23 | 8-state dashboard, per-row owner/evidence/commit/age/blocker/next action/dependency, no percentage | complete |
| 24 | 6 separated gates | complete |
| 25 | 13 new reports, 12 updated | complete |
| 26 | `.github/workflows/qualification-evidence.yml`, 10 CI protections | complete |

## Validation

`make` is not installed on this host. Every `make` target has an equivalent
`python scripts/release.py` entry point and the equivalents were used; the
Makefile targets are added and are what a Linux builder runs.

| Command | Exit | Result |
|---|---|---|
| `python scripts/task.py validate` | 0 | 277 JSON documents, 35 schemas, 297 Python files |
| `python scripts/task.py test` | 0 | **1,150 tests**, 1 skipped (was 892) |
| `python scripts/task.py test-installer` | 0 | 60 tests |
| `python scripts/task.py test-phase5` | 0 | 105 tests |
| `python scripts/task.py test-release-closure` | 0 | **510 tests** across 11 suites (was 252 across 9) — a re-run of the eleven directories, which `test` also discovers |
| `python scripts/task.py phase7-audit` | 0 | PASS |
| `python scripts/phase7.py source-gate` | 0 | PASS |
| `licence-gate` | 0 | **PASS** — 7 of 7 |
| `package-minimisation-check` | 0 | **PASS** |
| `development-signing-drill` | 0 | **PASS** — 9/9 |
| `two-person-development-signing-drill` | 0 | **PASS** — 9/9 |
| `qualification-evidence-baseline` | 0 | 8 of 8 classifications present |
| `acquire-cve-sources` | 0 | plan for 4 targets |
| `generate-reachability-packages` | 0 | 24 bundles × 9 files |
| `collect-hardware-evidence` | 0 | 17 fields, 12 exclusions, 21 tests |
| `accessibility-evidence-plan` | 0 | 17 flows |
| `pilot-closure-assertion` | 0 | no gate reports GO |
| `gate --kind source` | 0 | **PASS** |
| `independent-builder-ci-manifest` | 2 | prepared, **not executed** |
| `verify-builder-independence` | 2 | no verified pair |
| `compare-independent-builds` | 2 | `INCONCLUSIVE` |
| `validate-cve-acquisition` | 2 | no manifest |
| `analyse-cve-symbols` | 2 | 0 of 4 targets collected |
| `cve-disposition` | 2 | 24 of 24 `Unknown` |
| `validate-independent-reviews` | 2 | 4 requests ready, 0 delivered |
| `validate-hardware-evidence` | 2 | 0 reports, 0 collections |
| `validate-accessibility-evidence` | 2 | 17 of 17 not run |
| `stable-evidence-report` | 2 | 20 records, 18 blocking |
| `qualification-candidate-readiness` | 2 | 2 of 14 |
| `gate --kind qualification-candidate` | 2 | **BLOCKED** |
| `gate --kind stable-release` | 2 | **NO-GO** |
| `gate --kind oem-pilot` | 2 | **BLOCKED** |
| `gate --kind enterprise-pilot` | 2 | **BLOCKED** |
| `gate --kind sync-pilot` | 2 | **BLOCKED** |

### Not run, and why

- **The Fedora/KVM builder targets** (`build-beta-image`, `sbom`,
  `security-scan`, `vm-*`). This pass changed `build/scripts/build-image.sh` —
  adding `BUNNY_ARCHIVE_ONLY=1` so a hosted runner can be a real second builder —
  and that change has not been exercised on a Fedora host. It must be before the
  hosted workflow is dispatched.
- **The hosted CI workflow.** Committed, never dispatched. `executed` in
  `build/out/qualification/independent-builder-ci.json` is derived from whether a
  `hosted-ci` builder record exists, not from the workflow file being present, and
  it is `false`.

## Two bugs the new tests found

Recorded because a phase that reports only intended outcomes is not reporting.

1. **The normaliser introduced variance of its own.** `gzip.GzipFile` infers the
   stored original filename from `fileobj.name` and writes it into the gzip
   header, so two normalised copies written to different paths differed in their
   headers. Caught by normalising one archive to two destinations and comparing.
   Fixed with an explicit `filename=""`.
2. **`WEAK_DIMENSIONS` named a field the schema does not have.** Schema 1 carried
   a `workspace` path — the only dimension the two local builders differed in.
   Schema 2 deliberately has nowhere to put one, and the constant still referenced
   it, raising `AttributeError` on every same-host comparison. Split into
   `WEAK_DIMENSIONS` (record fields) and `INSUFFICIENT_FOR_INDEPENDENCE`
   (documentation, including things with no field).

## Definition of done, item by item

| Requirement | State |
|---|---|
| A hosted independent-builder workflow exists | **done** |
| The hosted build runs against an exact commit | **not met** — prepared, not executed |
| Builder independence verified from real environment evidence | **not met** — no hosted record |
| Local and hosted artifacts compared | **not met** — one builder |
| All Critical and High findings have structured binary-analysis packages | **done** — 24 × 9 files |
| No unsupported reachability conclusion is made | **done** — 24 of 24 `Unknown` |
| Independent-review packages ready | **done** — 4 requests, 10 sections each |
| Hardware-evidence collection tooling ready | **done** |
| Accessibility-evidence tooling ready | **done** |
| Second-signer onboarding material ready | **done** |
| The two-person development signing drill passes | **done** — 9/9 |
| Candidate prerequisites machine-readable | **done** — 14, fail-closed |
| Every gate remains fail-closed | **done** — 6 gates, 4 blocking |
| All current-state documentation accurate | **done** |
| No new product feature introduced | **done** |

Eleven of fifteen. The four unmet all reduce to one act: dispatching the workflow
and recording what comes back.

## What remains, and who can do it

**One CI dispatch, and it is the cheapest remaining blocker:**

1. Verify `BUNNY_ARCHIVE_ONLY=1` on the Fedora builder, then dispatch
   `.github/workflows/independent-builder.yml` against this commit and the pinned
   base digest. Record the hosted builder record and the local one, declare the
   pair, and run `compare-independent-builds`. That closes
   `independent-reproducibility` and is the only prerequisite of the fourteen that
   needs nothing but a button.

**Engineering, on the Fedora builder:**

2. Build a live ISO and a signed recovery ISO. Unblocks the installation,
   encryption and recovery matrices, and one of the five blocker codes.
3. Publish a signed update manifest and keep a previous release. Unblocks update,
   rollback and migration.
4. Mount the beta deployment and run `analyse-cve-symbols --sysroot`. Resolves the
   carrier attribution for all four objects — which does not answer question 7,
   but removes it from the reviewer's scope.

**Needs a third party:** the four reviews. The security one is the only route by
which any Critical becomes non-blocking, and `reviews/security/REQUEST.md` is
ready to send.

**Needs hardware:** one x86-64 UEFI machine with Secure Boot and TPM 2.0.

**Needs a second person:** a second production signer. Four of seven roles cannot
be provisioned at all without one.

**Needs an owner decision:** the nine protected approvals, whether to fund the
reviews, and whether to acquire hardware.

## Recommendation

Unchanged. **Do not begin any pilot, manufacture any device, deploy any fleet, or
launch any hosted service.**

The next useful work is item 1, and it costs a workflow dispatch.

Do not begin Phase 8.

## 2026-07-30 addendum: CI portability repair and hosted execution

The apparatus this report describes has now been *run*, on CI and on a second
builder. Running it changed three things.

### The CI that verified this evidence was itself broken

Eight defects across three workflows, recorded in
`docs/CI_PORTABILITY_BASELINE.md` and repaired in
`CI_PORTABILITY_REPAIR_REPORT.md`. Two of them affected whether the evidence in
this report means what it says:

* **The committed CVE findings could never have regenerated.** The generator
  stamped `git rev-parse HEAD`, so committing the twenty-five records moved
  `HEAD` and invalidated them in the same act. The check that was supposed to
  prove they follow from the committed evidence would have reported the same
  failure for an honest record and a tampered one. They are now bound to
  `candidateCommit`, every differing field is classified before anything is
  excluded, and only `generatedAt` may differ. Documented in
  `docs/CVE_REGENERATION_INVARIANTS.md`.

* **Several CI jobs accepted any non-zero exit as proof a protected gate
  refused.** A traceback exits 1. So does a missing file. Such a job goes green
  when `release.py` stops parsing and reports the stable gate correctly holding.
  All seventeen call sites now assert the exact documented status.

A third defect was latent: pull-request jobs check out a synthetic merge commit
that exists in no branch, and six call sites each resolved a commit independently
as `HEAD`. `release/commits.py` now distinguishes the five commit concepts and
refuses to generate committed evidence for a merge ref.

### The hosted builder had never been run, and it did not work

This report previously described dispatching it as the one prerequisite that
"needs nothing but a button". It took seven dispatches and five real defects,
recorded as F9–F14. The one worth carrying forward: **the base image digest
pinned since Phase 6 had been garbage collected from quay.io**, and the local
builder kept building against it because podman had the layers cached. A build
that appears to reproduce may only be reachable from one machine's cache.

### Independent reproducibility was measured, and it does not pass

Full result in `INDEPENDENT_REPRODUCIBILITY_REPORT.md`:
`NON_REPRODUCIBLE`, 11 dimensions matching, 5 differing, 1 not collected. Fifteen
files differ out of 104,247, all of them build-environment state — a random
`brlapi.key`, seven fontconfig caches, the rpm and dnf databases, two `countme`
counters. The file tree, permissions, ownership, package inventory and kernel
match exactly. The builders are additionally not certified independent because
`skopeo`, `python3` and `image-builder` differ.

### Gate state

Unchanged, and now verified by exact exit code rather than by "non-zero":

```text
Source gate:               PASS      (exit 0)
Qualification candidate:   BLOCKED   (exit 2, 2 of 14 prerequisites)
Stable release:            NO-GO     (exit 2)
OEM / Enterprise / Sync:   BLOCKED   (exit 2)
```

`independent-reproducibility` remains `BLOCKED`. It is no longer blocked for want
of a hosted build — the hosted build exists and its evidence is imported. It is
blocked because the comparison it enabled reported `NON_REPRODUCIBLE` and the
builders are not certified independent. That is a better kind of blocked: the
prerequisite now fails on a measurement rather than on an absence.
