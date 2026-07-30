<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Qualification evidence baseline

Recorded before any code changed on `feature/qualification-evidence-closure`.

- Branch cut from: `feature/release-blocker-closure`
- Base commit: `80df25b09f6578276d18c8a82f15c47dd8959740`
- Working tree at cut: **clean**
- Date: 2026-07-30

Every number in this document was produced by running a command on this host.
Where a command could not run here, that is stated rather than substituted.

## Preflight measurements

| Command | Exit | Result |
|---|---|---|
| `python scripts/task.py validate` | 0 | 73 JSON documents, 32 schemas, 275 Python files. `systemd-analyze` and `shellcheck` skipped — unavailable on this host. |
| `python scripts/task.py test` | 0 | 892 tests, 1 skipped |
| `python scripts/task.py test-installer` | 0 | 60 tests |
| `python scripts/task.py test-phase5` | 0 | 105 tests |
| `python scripts/task.py test-release-closure` | 0 | 252 tests across 9 suites (a subset of the 892; `test` discovers the same directories) |
| `python scripts/task.py phase7-audit` | 0 | 47 documents, 18 demonstrations, 11 schemas |
| `python scripts/phase7.py source-gate` | 0 | PASS |
| `python scripts/release.py licence-gate` | 0 | **PASS** — 7 of 7 requirements |
| `python scripts/release.py package-minimisation-check` | 0 | **PASS** — 1 removal, 15 retentions, 5 profiles |
| `python scripts/release.py development-signing-drill` | 0 | **PASS** — 9/9 |
| `python scripts/release.py stable-evidence-report` | 2 | **BLOCKED** — see below |
| `python scripts/release.py gate --kind stable-release` | 2 | **NO-GO** — 2 satisfied, 10 unmet |

`make` is not installed on this host. Every `make` target named in the brief has
an equivalent `python scripts/release.py` entry point, and the equivalents were
used. The Makefile targets are still added, and are what a Linux builder runs.

### A measurement the previous phase did not anticipate

`stable-evidence-report` now reports **0 passing categories, not 2**, and 20
missing categories rather than 18. Nothing regressed. Every record in
`operations/data/release-evidence.json` was generated from commit
`79bb99ddb39d`, and the candidate commit is now `80df25b09f65`:

```text
generated from commit 79bb99ddb39d but the candidate is 80df25b09f65;
evidence does not transfer between commits
```

The commit-binding rule is correct and is doing exactly what it was written to
do. The consequence, which was not previously written down, is that **every
commit invalidates the entire evidence record**, so regenerating the record is a
mandatory step of any phase that commits anything. That is recorded here as a
property of the model, and the regeneration is part of this phase's work.

## Current gate state at the baseline

```text
Source gate:            PASS
Stable release:         NO-GO
OEM pilot:              BLOCKED
Enterprise pilot:       BLOCKED
Encrypted-sync pilot:   BLOCKED
```

Blocked commands at the baseline: `vulnerability-position`,
`reproducibility-compare`, `validate-hardware-evidence`,
`validate-independent-reviews`, `stable-evidence-report`, `gate-stable-release`,
`gate-oem-pilot`, `gate-enterprise-pilot`, `gate-sync-pilot`.

## Vulnerability position at the baseline

Unchanged from the previous phase, and re-read from the committed record rather
than retyped:

| Scanned | Fixable | Critical | High | Medium |
|---|---|---|---|---|
| `fedora-bootc:44` base alone | 59 | 8 | 28 | 23 |
| Bunny OS beta profile | 59 | 8 | 28 | 23 |

Deduplicated to unique (advisory, package) pairs: 37 findings recorded, of which
**24 are Critical or High** and all 24 are dispositioned `Unknown`.

Base image: `quay.io/fedora/fedora-bootc:44@sha256:fb71f099f40360b5e1e2e78e845ccf4f0f80fbe1b09de721d8954cddb89ee9c4`

The 8 Critical findings are 7 `golang.org/x/crypto` v0.46.0 advisories and 1
`google.golang.org/grpc` v1.72.2 advisory. Carrier binaries: `/usr/sbin/podman`,
`/usr/sbin/skopeo`, `/usr/sbin/bootc`.

Nine of ten reachability questions are answered with measured evidence. The
tenth — *is the vulnerable code path compiled into the installed binary and
active or invocable?* — is not, and `Unknown` blocks.

## Classification of every unmet requirement

The eight classes are exclusive. A requirement is classified by **who can
produce the evidence**, not by how much work it is. A third-party requirement is
never classified as an engineering task, because misclassifying it is how a
project talks itself into self-reviewing.

### Automatable in repository

Evidence that can be produced by running code on any machine with a checkout.

| # | Requirement | Deliverable this phase |
|---|---|---|
| A1 | Builder identity model with meaningful trust boundaries | `release/reproducibility.py` schema v2: `builderType`, `administratorBoundary`, `workflowRunId`, `kernelVersion`, `cloudProvider`, timestamps |
| A2 | Independent-builder evidence pair rules | Four accepted pairings; anything else refused |
| A3 | Adversarial rejection of forged builder evidence | Reused run IDs, same host under two environment IDs, copied records, mutable tags, missing boundary |
| A4 | Deterministic artifact normalization | Non-semantic archive properties only; raw **and** normalized digests emitted |
| A5 | Eighteen-dimension artifact comparison | `build/out/qualification/reproducibility-comparison.json` |
| A6 | Per-CVE analysis schema and pipeline | `security/reachability/`, 40-field finding schema |
| A7 | Fedora source and debuginfo acquisition manifests | Manifest + checksum records; no RPMs committed |
| A8 | ELF and symbol analysis tooling | `scripts/reachability/analyse-symbols.py`, absent-symbol discipline |
| A9 | Vulnerable-path mapping records | Per-CVE, with `Unknown` retained where mapping is not confident |
| A10 | Five reachability proof classes with required evidence | `release/reachability.py` proof-class validation |
| A11 | Per-advisory security review bundles | Nine files per unresolved Critical/High advisory |
| A12 | Vulnerability gate per-finding disposition rule | Scanner score cannot substitute |
| A13 | Signed independent-review record schema | `IndependentReviewRecord`, self-review wall retained |
| A14 | Four bounded review-request packages | `reviews/*/REQUEST.md` |
| A15 | Physical-hardware evidence collector | `bunny-os qualification collect`, allow-list fields only |
| A16 | Guided hardware test runner, 22 tests | `NOT_RUN` cannot become `PASS` |
| A17 | Hardware evidence signature model | Integrity, not certification; the word "certified" is refused |
| A18 | Accessibility evidence harness, 17 flows | Static results cannot satisfy installed-flow evidence |
| A19 | Two-person development signing drill | Separate keys, key IDs, logs, disagreement refusal |
| A20 | Machine-readable candidate prerequisites | 14 prerequisites, fail-closed |
| A21 | Evidence dashboard with eight states | No aggregate percentage |
| A22 | Six separated gates | `gate-source` … `gate-sync-pilot` |
| A23 | Evidence record regeneration at the current commit | `scripts/build_evidence_record.py` |
| A24 | CI protection assertions | Ten properties CI must prove remain true |

### Requires CI infrastructure

Evidence that needs a hosted runner. The repository can prepare the workflow; it
cannot execute it.

| # | Requirement | State after this phase |
|---|---|---|
| B1 | A hosted independent build of an exact commit | Workflow authored and committed. **Not executed.** Executing it requires a push to a GitHub remote and a run of the workflow. |
| B2 | Hosted builder record with a real `workflowRunId` | Collector emits it; no run has produced one |
| B3 | Hosted artifacts, SBOM, package manifest, provenance, logs | Upload steps authored; nothing uploaded |
| B4 | Verification of downloaded CI artifacts | Verifier implemented; no artifacts to verify |

### Requires second independent machine

| # | Requirement | Why it cannot be produced here |
|---|---|---|
| C1 | Independent-builder reproducibility | Two workspaces on one host share a kernel, container store, clock and operator. A defect in any of them reproduces in both builds and the comparison cannot detect it. |
| C2 | Local-builder half of the local + hosted CI pair | Needs the Fedora/KVM builder to run a build at this commit |

### Requires physical hardware

| # | Requirement | Blocks |
|---|---|---|
| D1 | One x86-64 UEFI machine with Secure Boot and TPM 2.0 | `Hardware` and `Secure Boot` evidence categories, `gate-oem-pilot` |
| D2 | 22 guided hardware tests on that machine | Hardware evidence category |
| D3 | Two boot-time accessibility workflows | Installer screen reader, encryption prompt |
| D4 | Suspend and resume | The most common real-world failure, and unmeasurable in a VM |

### Requires independent reviewer

| # | Requirement | Only route |
|---|---|---|
| E1 | Per-CVE reachability determination for 8 Critical findings | An external security reviewer. `release/vulnerability.py` refuses a non-blocking Critical without a delivered independent review reference. |
| E2 | Per-CVE reachability for 16 High findings | Same |
| E3 | Encrypted-sync cryptography review | `gate-sync-pilot` requires it outright |
| E4 | Accessibility qualification review | The `Accessibility` category and approval |
| E5 | Licensing outbound-compatibility and trademark opinion | OEM distribution and `brandingAndLicensingApproval` |

### Requires second authorised signer

| # | Requirement | Note |
|---|---|---|
| F1 | A second production signer, identified | One potential signer exists |
| F2 | Two-person approval for the four roles that require it | Cannot be provisioned at all with one signer |
| F3 | A production key ceremony | Not held. `docs/PRODUCTION_SIGNING_CEREMONY.md` records the unrun procedure. |

The two-person **development** drill delivered this phase validates the process.
It does not satisfy F1, F2 or F3, and the drill's own report says so.

### Requires owner decision

| # | Requirement | Current recommendation |
|---|---|---|
| G1 | Whether to accept the base-image vulnerability position | ADR-027: retain the base, retain NO-GO |
| G2 | Which Phase 7 capabilities to operate, if any | Operate none |
| G3 | Whether to fund the four independent reviews | Not an engineering decision |
| G4 | Whether to acquire hardware, and which | Secure Boot + TPM 2.0 first |
| G5 | The nine protected release approvals | All nine pending |

### Requires operated release evidence

Evidence that only exists once something has been published and run for a while.

| # | Requirement | Depends on |
|---|---|---|
| H1 | Update matrix | A published signed update manifest |
| H2 | Rollback matrix | A previous release to roll back to |
| H3 | Migration | Two published releases |
| H4 | Soak | An installed candidate and elapsed time |
| H5 | Support capacity | A funded rota and a second signer |
| H6 | Operated-service privacy and residency evidence | A service actually operated — out of scope, and remains so |

## What this phase does not attempt

- No new OEM, enterprise, fleet, encrypted-sync or consumer feature.
- No Phase 8 work.
- No pilot.
- No relaxation of any gate. The six gates are expected to end this phase at
  `PASS / BLOCKED / NO-GO / BLOCKED / BLOCKED / BLOCKED`, and that is the
  honest result.
- No repeat of the completed licensing, package-minimisation,
  development-signing or adversarial evidence-validation work.

## Honesty constraints adopted for this phase

1. A prepared workflow is described as prepared, never as executed.
2. An absent symbol in a stripped binary is not evidence of absent code.
3. `Unknown` remains blocking, and is preferred over a convenient conclusion.
4. A normalized-digest match does not excuse an unexplained raw-content
   difference.
5. `NOT_RUN` is never rewritten to `PASS`.
6. The word "certified" is not used of any hardware result.
7. No reviewer name or completion date is invented.
