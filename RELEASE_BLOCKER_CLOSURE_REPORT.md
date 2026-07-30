# Release blocker closure report

Date: 2026-07-30  
Branch: `feature/release-blocker-closure`  
Base commit: `79bb99ddb39d8a5dbc279629f43b23346fb0e5e8`

## Result

**Two blockers closed. Several measured and narrowed. `gate-stable-release`
still reports `NO-GO`, and all three pilot gates still report `BLOCKED`.**

The definition of done for this phase is not met, and could not have been met
from this machine. Six of the remaining blockers need a device, a third party,
a second person, or a decision that is not an engineering decision. That is
stated up front because the rest of this report is detail.

## What closed

### 1. Licensing

The project had no root `LICENSE`. It now has one, plus canonical texts, eight
per-directory files, 127 SPDX headers, a clean 6077-record licence scan, and a
trademark draft. `make licence-gate` passes all seven requirements.

This needed the owner to decide, and they did: GPL-3.0-or-later for the OS
layer, Apache-2.0 for the client packages. See `LICENCE_DECISION_REPORT.md`.

The licence texts were taken from the builder's `/usr/share/licenses/`, each
corroborated by three independent packages shipping byte-identical copies,
rather than transcribed from memory.

### 2. Package minimisation

`toolbox` removed from four consumer profiles, with a fail-closed protected-package
check that verifies recovery, accessibility, firmware, installer and security
packages survive the removal. Build log: `removed toolbox; 28 protected packages
intact`.

**It changed no scan number**, which is the honest result and precisely why
"reduce the scan count" is a prohibited motive. See `docs/PACKAGE_MINIMISATION.md`.

## What was measured rather than assumed

### The base image was rebuilt during this phase, and it did not help

`quay.io/fedora/fedora-bootc:44` now resolves to `sha256:fb71f099…`, created
2026-07-29T11:06:05Z. The previous analysis recorded `sha256:5cd90a82…`. Fedora
genuinely rebuilt the base — and the counts are identical: 59 fixable, 8
Critical, 28 High, 23 Medium.

That single fact reframes the vulnerability blocker. "Wait for Fedora" is no
longer a plan with an expected date attached; a rebuild has now been observed to
land without moving the position. `docs/adr/ADR-027-base-image-security-decision.md`
records the decision to retain the base anyway, with four precisely checkable
conditions that would reopen it.

### The reachability review answered nine of ten questions

`SECURITY_REACHABILITY_REVIEW.md` establishes, with evidence from the built
image: podman/skopeo/bootc are installed at `/usr/sbin`, mode 0755, no setuid;
**no podman or bootc unit is enabled**; `podman.socket` is a unix socket and is
not in `sockets.target.wants`; nothing in Bunny invokes a container runtime;
SELinux is enforcing; and **the packages cannot be removed** because `bootc`
requires podman and skopeo and `rpm-ostree` requires skopeo.

The tenth question — is the vulnerable code path compiled in and active — is
unresolved, because answering it means per-CVE symbol analysis of a 45 MB
stripped Go binary. All 24 findings are therefore `Unknown`, which blocks.

Nine answers is not nothing. It turned "59 findings, unclear exposure" into one
specific question about 24 findings, assigned to the party who can answer it.

### Two isolated workspaces produce byte-identical output, and that is not reproducibility

Archives `b5c0c502…` from both, 83 members, 0 differing, 6076 matching package
entries. Same-host repeatability, filesystem-content and archive-byte
reproducibility are all established.

`independent-builder` is refused, because the two builders differ only in
`environmentId`. `release/reproducibility.py` requires a strong dimension —
different machine, cloud runner, or administrator — on the grounds that a defect
in a shared kernel, storage or clock reproduces identically in both builds and
the comparison cannot detect it.

That refusal is tested (`same-host builds marked independent`) and it is the
mistake this repository made before.

### An SBOM difference that was not a build difference

The two SBOMs had different file digests. Investigating rather than assuming
found: a fresh UUID namespace per syft run, a creation timestamp, and a root
entry named after the input file's *path*. 6076 of 6077 package entries matched
exactly; the one that did not was document identity, and its content digest was
identical in both.

The comparison now compares package manifests semantically. Left as it was, the
tool would have reported a reproducibility failure that does not exist.

### Package removal does not remove bytes from a bootc base

`toolbox` is gone from `/usr/bin` and from the rpm database — verified in a
running container — and syft still reports it, located at
`/sysroot/ostree/repo/objects/75/5cc7cf…file` in a base layer. The
`fedora-bootc` base ships an ostree object store, and `dnf remove` cannot remove
an object from a store baked into a lower layer.

Consequences: minimisation on this base cannot shrink the image or the SBOM;
archive-derived and SBOM-derived scan counts disagree (59 vs 84); and every
finding's carrier path is an ostree object, which is why binary presence had to
be established separately.

### The signing path works, including its refusals

Nine of nine drill checks pass against the real 1.85 GB and 1.33 GB artifacts,
including four rejection checks: revoked key, wrong role, corrupted artifact, and
rotation without an overlapping trust period. See
`DEVELOPMENT_SIGNING_DRILL_REPORT.md`.

Every key carries the reserved `dev-` prefix and is refused by
`require_production_key`, so the drill is safe to run in pull-request CI and is.

## What was built

| Workstream | Deliverable |
|---|---|
| 1, 3 | `release/vulnerability.py`, `release/reachability.py`, per-finding disposition with 16 mandatory fields, 10-question bounded review |
| 2 | `docs/adr/ADR-027-base-image-security-decision.md` |
| 4 | `release/minimisation.py`, `build/packages/protected.txt`, fail-closed removal in `install-packages.py` |
| 5, 6 | `release/licensing.py`, the licence gate, `LICENSE`, `LICENSES/`, 8 directory licences, 127 SPDX headers |
| 7 | `release/reproducibility.py`, `scripts/reproducibility/`, four separated claims |
| 8, 9 | `release/signing.py`, 7 roles, `scripts/signing_drill.py`, three signing documents |
| 10 | `release/artifacts.py`, candidate naming discipline, 9 mandatory fields per artifact |
| 11–15 | `release/matrix.py`, 7 matrices, 74 scenarios, runtime-only enforcement for recovery and accessibility |
| 14 | `release/hardware.py`, `hardware/evidence/`, redaction and substantiation checks |
| 16 | `release/reviews.py`, `reviews/`, four prepared packages, self-review wall |
| 17 | `release/evidence.py`, 20 categories, forgery/staleness/wrong-commit/self-review detection |
| 18 | `release/gates.py`, four separated gates |
| 21 | `.github/workflows/release-blocker-closure.yml`, 9 jobs |
| 22 | 9 test suites, 252 tests, all 14 mandated adversarial cases |
| 23 | 24 new `make` targets and `scripts/release.py` |

## Validation

| Command | Result |
|---|---|
| `python scripts/task.py validate` | PASS — 73 JSON documents, 32 schemas, 275 Python files |
| `python scripts/task.py test` | PASS — 892 tests, 1 skipped |
| `python scripts/task.py test-installer` | PASS — 60 tests |
| `python scripts/task.py test-phase5` | PASS — 105 tests |
| `python scripts/task.py test-release-closure` | PASS — 252 tests |
| `python scripts/task.py phase7-audit` | PASS |
| `python scripts/phase7.py source-gate` | PASS |
| `make release-blocker-baseline` | PASS — 19 mandatory sections |
| `make licence-gate` | **PASS** |
| `make package-minimisation-check` | **PASS** |
| `make development-signing-drill` | **PASS** — 9/9 |
| `make vulnerability-position` | BLOCKED — 24 findings |
| `make reproducibility-compare` | BLOCKED — one machine |
| `make validate-hardware-evidence` | BLOCKED — no reports |
| `make validate-independent-reviews` | BLOCKED — none commissioned |
| `make stable-evidence-report` | BLOCKED — 18 of 20 categories |
| `make gate-stable-release` | **NO-GO** |
| `make gate-oem-pilot` | **BLOCKED** |
| `make gate-enterprise-pilot` | **BLOCKED** |
| `make gate-sync-pilot` | **BLOCKED** |

On the Fedora/KVM builder: beta, developer and recovery images built from the
pinned digest; `inspect-image`, `sbom`, `license-scan`, `security-scan` ran;
`vm-smoke` reached the boot marker.

`vm-rollback-test`, `vm-recovery-test` and `vm-upgrade-test` each exited 3 for a
stated reason — no previous release disk, no recovery ISO, no signed manifest.
Those are recorded as `NOT_RUN`, not as passes.

`vm-install-smoke` and `vm-encrypted-install` are interactive by design and were
not run.

## Definition of done, item by item

| Requirement | State |
|---|---|
| Base-image vulnerability decision documented | **done** — ADR-027 |
| No unresolved Critical without independent evidence | **not met** — 8 Critical, `Unknown` |
| Package minimisation complete | **done** |
| Explicit project licence approved | **done** |
| Root licence and third-party notices exist | **done** |
| Two independent builders produce matching content | **not met** — one machine |
| Production signing roles documented | **done** |
| Development signing drill passes | **done** — 9/9 |
| Stable candidate artifacts built and verified | **not met** — no ISO, no recovery ISO |
| Independent recovery media boots | **not met** |
| Encrypted installation passes | **not met** |
| Updates pass | **not met** |
| Rollback passes | **not met** |
| Recovery passes | **not met** |
| User-data preservation passes | **not met** |
| At least one physical machine qualified | **not met** |
| Essential accessibility workflows tested | **not met** |
| Independent review status documented | **done** — `INDEPENDENT_REVIEW_STATUS.md` |
| Stable evidence record complete | **not met** — 2 of 20 |
| No Blocker or Critical issue remains | **not met** |
| `gate-stable-release` reports GO | **not met** |

Eight of twenty-one done. The gate was not forced, and the twelve unmet items
are unmet in the record as well as in this report.

## What actually remains, and who can do it

**Engineering, on this builder:**

1. Build a live ISO and a signed recovery ISO. That unblocks the installation,
   encryption and recovery matrices in a VM — three evidence categories and one
   of the five blocker codes.
2. Publish a signed update manifest and keep a previous release. That unblocks
   update, rollback, migration and preservation.

**Needs a second machine or a cloud runner:**

3. Independent-builder reproducibility. `collect-builder-record.sh` already reads
   `GITHUB_RUN_ID` into `cloudRunner`, so a CI-hosted build of the same commit
   and base digest would satisfy it without buying anything. **This is the
   cheapest remaining blocker.**

**Needs hardware:**

4. One x86-64 UEFI machine with Secure Boot and TPM 2.0. Blocks two evidence
   categories, the OEM pilot, and two accessibility workflows.

**Needs a third party:**

5. Security architecture review — the only route to dispositioning any Critical.
6. Cryptographic review — blocks the sync pilot outright.
7. Accessibility audit — the gap where being wrong harms a user.
8. Legal opinion — outbound compatibility and anti-tivoisation.

**Needs a second person:**

9. A second release signer. Four of seven signing roles require two-person
   approval and cannot be provisioned at all with one signer.

**Needs an owner decision:**

10. Which Phase 7 capabilities to operate, if any. Operating none remains a
    legitimate answer and is still the recommendation.

## Recommendation

Unchanged. **Do not begin any pilot, manufacture any device, deploy any fleet, or
launch any hosted service.**

The next useful work is items 1, 2 and 3 — all of which are within reach and
none of which requires money. Item 3 in particular converts a permanent-looking
blocker into a CI configuration change.

Do not begin Phase 8.
