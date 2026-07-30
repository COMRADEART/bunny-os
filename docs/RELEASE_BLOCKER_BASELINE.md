# Release blocker baseline

Recorded before any code changed on `feature/release-blocker-closure`, and
updated with the measurements taken during the phase. Every number here was
produced by running something, not by reading a previous report.

## Source commit

`79bb99ddb39d8a5dbc279629f43b23346fb0e5e8` on `feature/oem-enterprise-and-sync`,
the tip of the Phase 7 work. `main` is at `8fc2725` (Phase 1 architecture); the
Phase 7 source lives on the feature branch, so the closure branch was cut from
the feature tip rather than from `main` to avoid discarding 30 commits.

Branch created: `feature/release-blocker-closure`.

## Current image base and digest

```text
quay.io/fedora/fedora-bootc:44@sha256:fb71f099f40360b5e1e2e78e845ccf4f0f80fbe1b09de721d8954cddb89ee9c4
```

Created 2026-07-29T11:06:05Z. This is **not** the digest the previous analysis
recorded (`sha256:5cd90a82…`): Fedora rebuilt and republished the base during
this phase. The rebuild did not change the vulnerability position.

Beta image built from that pinned digest:
`4ef248b2384d5d6a7c847dc9f7fa16e252963587c5d629debb2544bbf91dd703`
(archive, pre-minimisation); `b5c0c502e22b936aa170c58f2240b777235da4c15eb715a4309ee2b859bf87d8`
(archive, post-minimisation, reproduced identically in two workspaces).

## Current vulnerability counts

Measured with grype 0.116.1 against archives built from the pinned digest.

| Scanned | Fixable | Critical | High | Medium |
|---|---|---|---|---|
| `fedora-bootc:44` base alone | 59 | 8 | 28 | 23 |
| Bunny OS beta profile (consumer-facing) | 59 | 8 | 28 | 23 |
| Bunny OS beta, after minimisation | 59 | 8 | 28 | 23 |
| Bunny OS developer profile | 95 | 19 | 43 | 33 |

The beta profile adds **nothing** to the base. All 59 are inherited. The
developer profile's extra 36 come from `build/packages/developer.txt`, which
already documents those packages as absent from consumer images.

Deduplicated to unique (advisory, package) pairs, the blocking set is **24**.

## Vulnerable package names

Critical, all in Go modules vendored into the container stack:

- `golang.org/x/crypto` v0.46.0 — 7 Critical advisories, fixed in 0.52.0
- `google.golang.org/grpc` v1.72.2 — 1 Critical, fixed in 1.79.3

High:

- `github.com/containers/podman/v5`, `github.com/sigstore/fulcio`,
  `golang.org/x/net`, `golang.org/x/text`, `golang.org/x/crypto`,
  `google.golang.org/grpc`, `github.com/docker/docker`,
  `go.opentelemetry.io/otel`, `github.com/moby/buildkit`,
  `github.com/opencontainers/selinux`, and one `linux-kernel` classifier match.

Carrier binaries, measured inside the built image: `/usr/sbin/podman`
(45,220,848 B), `/usr/sbin/skopeo` (26,035,008 B), `/usr/sbin/bootc`
(17,397,824 B). All mode 0755 root:root, no setuid.

## Current licence state

**Resolved during this phase.** Previously there was no root `LICENSE` and
`docs/LICENSING.md` recorded the decision as blocked on the owner.

The owner selected the split model on 2026-07-29: GPL-3.0-or-later for
`services/`, `installer/`, `shell/`, `build/`; Apache-2.0 for `oem/`,
`enterprise/`, `sync/`, `schemas/`. `LICENSE`, `LICENSES/`, eight per-directory
`LICENSE` files and 127 SPDX headers are in place. `make licence-gate` passes
all seven requirements.

Outstanding: outbound compatibility has not been reviewed by counsel, and
`docs/TRADEMARK_POLICY_DRAFT.md` is a draft. Both sit in `reviews/legal/`.

## Signing-key state

No production key of any role exists. No key ceremony has been held. There is
one potential signer, so the two-person approval that four of the seven roles
require cannot currently be satisfied.

Seven roles are defined with disjoint namespaces. Five development keys exist
outside the repository under `~/.bunny-dev-keys/drill/`, all carrying the
reserved `dev-` prefix, and `release.signing.require_production_key` refuses
every one of them. Three roles — `oemProfile`, `fleetPolicy`,
`syncServiceIdentity` — have no key of any class.

The development signing drill passes 9 of 9 checks against real 1.85 GB and
1.33 GB artifacts.

## Reproducibility state

Four claims, kept separate:

| Claim | State |
|---|---|
| Same-host repeatability | **Established.** Two isolated workspaces, byte-identical archives. |
| Filesystem-content reproducibility | **Established.** 83 archive members, 0 differing. |
| Archive-byte reproducibility | **Established.** Both archives `b5c0c502…`. |
| Independent-builder reproducibility | **Not established.** One machine. |

The two builders differed only in `environmentId`. `release/reproducibility.py`
refuses the independent-builder claim on that basis, because a defect in the
shared kernel, storage or clock would reproduce in both builds and the
comparison could not detect it.

## Hardware evidence state

None. `operations/data/hardware-evidence.json` contains zero reports. No
physical machine has run Bunny OS. The intake process, redaction checks and
substantiation checks are implemented and the file is empty.

## Recovery evidence state

None. A recovery OCI archive (1.33 GB) and QCOW2 were built.
`build/scripts/vm-recovery-test.sh` exits 3 — `BUNNY_RECOVERY_ISO must name an
existing recovery image` — because no signed recovery ISO exists. All eleven
recovery-media scenarios are `NOT_RUN`, and the matrix refuses to accept a
source-inspection pass.

`recovery-media-failure` remains one of the five open blocker codes.

## Accessibility evidence state

None at runtime. Static accessibility tests pass and are explicitly not
sufficient. Zero of fourteen essential workflows have been driven with assistive
technology. The two boot-time workflows — installer screen reader and encryption
prompt — additionally need hardware or an interactive installer session.

## Security-review state

No independent review of any kind has been commissioned. Four review packages
are prepared under `reviews/` with scope, threat model, design documents, test
results, known limitations, explicit questions and expected deliverables. None
has an identified reviewer.

`release/reviews.py` rejects any reviewer affiliated with the project, so the
existing internal reviews cannot be recorded as independent.

## Stable-gate result

**NO-GO.** `python scripts/release.py gate --kind stable-release` reports two
satisfied requirements and eleven unmet:

```text
ok      licence
ok      package-minimisation
BLOCKED evidence-record, vulnerability-position, independent-builder-reproducibility,
        production-signing, candidate-artifacts, qualification-matrices,
        physical-hardware, independent-reviews, approvals, blockers
```

Nine approvals pending. Five blocker codes open: `missing-checksum`,
`recovery-media-failure`, `unresolved-blocker`, `unsigned-artifact`,
`untested-release-rollback`.

Evidence record: 20 categories, 2 passing (Build, Licence), 18 blocking.

## OEM pilot-gate result

**BLOCKED.** Seven unmet: the stable gate, plus `qualifiedHardwareModel`,
`oemRecoveryValidation`, `signedOemProfile`, `factoryFinalisationOnHardware`,
`brandingAndLicensingApproval`, `namedSupportOwner`.

## Enterprise pilot-gate result

**BLOCKED.** Seven unmet: the stable gate, plus `fleetControlPlaneImplemented`,
`tenantIsolationPenetrationTest`, `enrolmentServiceDeployed`,
`consoleRoleTesting`, `incidentResponseOwner`, `supportCapacity`.

## Sync pilot-gate result

**BLOCKED.** Eight unmet: the stable gate, plus
`independentCryptographicReview`, `operatedSyncService`, `keyRecoveryDrill`,
`deletionDrill`, `servicePrivacyReview`, `dataResidencyDisclosure`,
`incidentResponseOwner`.

## Blockers that can be solved in code

These were solvable and were solved or advanced during this phase:

1. **No root licence or SPDX identifiers.** Done, once the owner decided.
2. **Package minimisation not performed.** Done: `toolbox` removed from four
   consumer profiles with a fail-closed protected-package check.
3. **No evidence model with expiry, commit binding and forgery detection.** Done.
4. **No separated pilot gates.** Done.
5. **No reproducibility comparison tooling.** Done; the comparison runs and
   correctly refuses to overclaim.
6. **No signing drill.** Done, 9 of 9 against real artifacts.
7. **Archive determinism.** Already fixed in the previous phase and re-verified
   here across two workspaces.

Still solvable in code, not done:

8. A live ISO and a signed recovery ISO, which would unblock the installation,
   encryption and recovery matrices in a VM.
9. A signed update manifest and a previous release, which would unblock the
   update and rollback matrices.

## Blockers requiring an owner decision

1. **The licence.** Resolved on 2026-07-29.
2. **The base-image decision.** Open. See
   `docs/adr/ADR-027-base-image-security-decision.md`: wait for Fedora, change
   base, or argue reachability per CVE and waive with independent review. The
   third is the only one the project can act on alone and
   `docs/STABLE_RELEASE_BLOCKERS.md` forbids it for the 8 Criticals.
3. **Which Phase 7 capabilities to operate, if any.** Operating none is a
   legitimate answer and is the current recommendation.

## Blockers requiring hardware

1. At least one x86-64 UEFI physical machine, for the `Hardware` evidence row,
   the `Secure Boot` row, the TPM encryption scenarios, and the two boot-time
   accessibility workflows.
2. A second machine, cloud runner or administrator, for independent-builder
   reproducibility. Nothing about this is solvable on one host.

## Blockers requiring an independent third party

1. **Security architecture review** — the only route by which any of the 8
   Critical findings could become non-blocking.
2. **Encrypted-sync cryptography review** — blocks the sync pilot outright.
3. **Accessibility audit** — the gap where being wrong harms a user rather than
   merely leaving a box unticked.
4. **Licensing and trademark opinion** — outbound compatibility and the
   anti-tivoisation question, which is load-bearing for the OEM programme.
5. **A second release signer**, so signing is not a single point of failure and
   two-person approval becomes possible.
