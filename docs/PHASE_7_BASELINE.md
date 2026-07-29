# Bunny OS Phase 7 baseline

Date: 2026-07-29  
Baseline commit: `0691e0646db4d0cdd9a2ecadc3aca6dde3350287`  
Feature branch: `feature/oem-enterprise-and-sync`  
Entry decision: **NO-GO for pilots, manufacturing, deployment, and hosted services** — see the addendum at the end of this document for the revised implementation disposition.

> **Addendum, 2026-07-29.** This baseline was first written as a preflight stop that
> declined to implement Phase 7 at all. That disposition has been revised for the
> *source* scope only, matching how Phases 3 and 5 were delivered: design, schemas,
> validators, tests, and documentation land ahead of runtime evidence, and the gates
> that would authorise deployment fail closed. Phase 7 source now exists under
> `oem/`, `enterprise/`, and `sync/`. Every finding, gap, risk, and blocker recorded
> below remains accurate and unresolved, and every pilot, OEM, enterprise, and
> hosted-sync gate remains blocked. See `PHASE_7_REPORT.md`.

## Preflight disposition

The Phase 7 brief requires a completed stable release, healthy signed artifacts,
working updates/rollback/recovery, reproducibility, and no unresolved Blocker or
Critical issue before implementation. This checkout does not meet those entry
conditions:

- `PHASE_4_REPORT.md` and all nine Phase 4/public-beta preflight records are absent.
- `PHASE_5_REPORT.md` and `STABLE_RELEASE_GO_NO_GO.md` record `NO-GO`.
- `PHASE_6_REPORT.md` records that Phase 6 stopped at mandatory preflight; it did
  not publish or operate a stable release.
- `make gate-stable-release` ran the inherited static suites successfully, then
  failed closed because `build/out/stable-rc/STABLE-CANDIDATE.json` is absent.
- The direct protected decision reports five blockers:
  `unresolved-blocker`, `unsigned-artifact`, `missing-checksum`,
  `untested-release-rollback`, and `recovery-media-failure`.
- The evidence record has 31 missing or pending evidence/approval entries.
- There is no stable artifact directory or configured stable public key.
- The requested stable publication, post-release security/privacy/accessibility,
  stable support matrix, licence compliance, and reproducible-build reports are
  absent because their prerequisite work did not occur.

Unknown evidence remains blocking under `docs/STABLE_RELEASE_BLOCKERS.md`. Source
tests are not substituted for installed-system, artifact, physical-hardware, or
operated-service evidence.

## Stable version

No stable Bunny OS version, stable candidate, stable tag, release date, support
start date, maintenance window, security-only window, or end-of-life date has
been approved. The Bunny payload remains an explicitly non-functional `0.2.0`
placeholder rather than a signed qualified Linux artifact.

## Supported architectures

No architecture is qualified for stable support. Fedora 44 x86-64 UEFI is the
source design target. Legacy BIOS and ARM64 are unsupported by the current
design; neither the design target nor any alternative has release-grade runtime
evidence.

## Current hardware tiers

The physical evidence database contains zero submissions. There are no Stable
recommended or Stable supported devices. All unlisted hardware is Untested;
proprietary NVIDIA is unqualified, and VM definitions have not produced a booted
release artifact.

## OEM readiness

`docs/OEM_MODE.md` is plan-level scaffolding only. The repository has no OEM
profile schema or trust root, signed profile validator, controlled overlay
builder, factory executor, `bunny-oem finalize` implementation, factory cleanup
evidence, qualification kit, partner process, OEM recovery validation, or
branding/licensing approval. No OEM image is approved.

## Device identity readiness

There is no device identity service, device certificate lifecycle, TPM-backed
identity implementation, enrolment identity, rotation history, or attestation
protocol. Existing hardware probes intentionally redact serials, but that does
not establish the required privacy-preserving remote identity.

## Multi-device data model

Current state is per-Linux-user, local XDG data with no shared-model default and
no account requirement. There is no versioned multi-device object model,
selective-sync state, version vector, tombstone model, deterministic conflict
resolver, pairing record, device revocation record, backup/migration envelope,
or deletion propagation protocol.

## Enterprise-management gaps

There is no typed enrolment protocol, device policy agent, policy schema,
conflict engine, remote-administration API, ownership-aware wipe workflow, fleet
group/update-ring controller, organisation application catalogue, compliance
evidence schema, append-only audit service, role-based console, enterprise
authentication integration, tenant data plane, offline bundle workflow, kiosk
profile, shared-laboratory session policy, or decommissioning service. The
existing local broker remains narrow and does not expose a generic root shell.

## Cloud-service gaps

There is no fleet control plane, enrolment service, enterprise console, encrypted
sync service, account service, object store, metadata coordinator, region
selection, service backup, availability target, incident rotation, abuse-control
system, billing system, or operated cloud environment. These are optional by
design; Bunny OS must continue to work without an account or cloud connection.

## Privacy risks

- Device and enrolment identifiers could become persistent tracking identifiers
  unless purpose, rotation, retention, export, and deletion are constrained.
- Fleet health and audit schemas could drift into user content or behavioural
  analytics without strict allowlists and adversarial tests.
- Attestation, update, sync, and audit metadata can reveal device/account/group
  relationships even when content is encrypted.
- An organisation administrator could cross the declared personal-data boundary,
  especially on personally owned devices or during wipe/decommission operations.
- Pairing, recovery, support access, backups, and diagnostic exports can create
  secondary plaintext or metadata paths.
- Multi-tenant mistakes could expose device or organisation records across
  customers.

No privacy certification or zero-knowledge claim is made.

## Security risks

- The inherited boot, installer, encryption, update, rollback, recovery,
  signing, supply-chain, multi-user, and runtime security evidence is incomplete.
- OEM overlays and factory environments add malicious package, credential
  residue, key substitution, firmware, and supply-chain risks.
- Enrolment tokens, management certificates, policy bundles, update rings,
  remote actions, and recovery workflows add replay, downgrade, escalation, and
  unauthorised wipe risks.
- A fleet service adds cross-tenant access, role escalation, audit tampering,
  identity-provider compromise, and control-plane availability risks.
- Encrypted sync adds pairing substitution, compromised-device access, key
  recovery abuse, server rollback, ciphertext corruption, and metadata leakage
  risks.

No Phase 7 security boundary has been implemented or assessed.

## Legal and licensing risks

There is no release `LICENSE_COMPLIANCE_REPORT.md`, `THIRD_PARTY_NOTICES.md`,
trademark report, or formal OEM branding/certification programme. OEM firmware,
drivers, cryptographic libraries, identity integrations, server dependencies,
console code, hosted-service terms, data-processing terms, export controls, and
regional retention claims require review before a pilot. Modified images must
not claim official or certified status without a defined process and repeatable
evidence.

## Operational capacity

No stable maintenance staffing, signing-key continuity, supported release
duration, incident/on-call rotation, hardware lab, fleet service operation,
sync-service operation, support SLA, disaster-recovery drill, or post-release
review process has been demonstrated. The repository intentionally makes no
customer-count, deployment-scale, demand, or revenue claim.

## Estimated maintenance burden

A numeric estimate would be invented because staffing, deployment scale,
availability targets, regions, hardware families, and service architecture are
not approved. At minimum, Phase 7 would add separate ongoing responsibilities
for OS/security maintenance, offline signing and key ceremonies, OEM profile and
hardware qualification, factory incident response, device/policy protocol
compatibility, fleet service and tenant isolation, identity-provider
integrations, encrypted-sync cryptography and storage, backup/deletion requests,
accessibility, documentation, application curation, privacy review, abuse
response, support, and disaster recovery. This burden is presently unstaffed and
unbounded.

## Phase 7 blockers

1. Close the full Phase 1–3 artifact, VM, installed-system, accessibility,
   privacy, security, and physical-hardware evidence gaps.
2. Complete and operate Phase 4/public beta with its required reports.
3. Produce a new immutable stable candidate with signed ISO/raw/QCOW2 and
   independently bootable recovery media, checksums, SBOM, package inventory,
   provenance, release notes, third-party notices, and known issues.
4. Pass two-builder reproducibility, licence, malware, supply-chain, Secure Boot,
   LUKS, install, update, rollback, recovery, migration, multi-user, local-only,
   Bunny-disabled, privacy, accessibility, hardware, and soak gates.
5. Provide a signed functional Bunny Linux artifact and qualify its lifecycle.
6. Close all five protected blocker codes and all 31 missing evidence/approval
   entries; obtain the nine protected approvals.
7. Change the evidence-backed stable decision to `GO`, publish and operate the
   stable release, then complete the required post-release reviews.
8. Re-run `gate-stable-release` successfully from a clean protected checkout.

Only after these blockers close may the Phase 7 OEM, enterprise, fleet, or sync
implementation begin. Controlled pilots, manufacturing, broad enterprise
deployment, and hosted-sync publication remain prohibited.

## Local blocker remediation after preflight

The stop decision did not prevent repairing inherited defects that were safe to
exercise locally. A Fedora 44 WSL/KVM builder exposed and verified fixes for
current image-builder multi-format invocation, bootc/OSTree disk inspection,
the Bunny health-service writable-state boundary, strict VM health-marker
enforcement, and SPDX declared-license handling.

A disposable validation revision produced developer and beta QCOW2 images and
a beta raw disk. Structural checks, bootc-aware inspection, and developer/beta
QEMU/KVM health boots passed. The beta SPDX contained 6,077 records; the
release-mode license policy reported 306 explicitly provenance-covered
`NOASSERTION` records, zero unresolved licenses, and zero prohibited markers.

The beta vulnerability gate remains failed with 59 fixable matches: 8 Critical,
28 High, and 23 Medium. The High/Critical records are associated with the Fedora
kernel or embedded dependencies in bootc-required Podman, Skopeo, and Toolbox.
No suppression or release waiver was created. These results improve the local
baseline but do not supply a signed stable candidate, public-beta operation,
independent recovery media, installed-system matrix, reproducibility,
physical-hardware evidence, or protected approvals. Entry remains `NO-GO`.

## Commands executed

```text
C:\msys64\usr\bin\make.exe -s PYTHON=python gate-stable-release
python scripts/phase5.py phase4-preflight
python scripts/phase5.py stable-gate --evidence operations/data/stable-qualification.json
C:\msys64\usr\bin\make.exe -s PYTHON=python verify-stable-rc
python -m unittest discover -s tests -t .
python scripts/task.py audit
python scripts/task.py validate
bash build/scripts/build-image.sh developer
bash build/scripts/build-image.sh beta
bash build/scripts/inspect-image.sh developer
bash build/scripts/inspect-image.sh beta
bash build/scripts/sbom.sh beta
python3 build/scripts/license-scan.py build/out/beta/sbom/bunny-os.spdx.json --release
bash build/scripts/security-scan.sh beta
bash build/scripts/vm-smoke.sh developer
bash build/scripts/vm-smoke.sh beta
```

The four entry checks failed closed for the documented missing prerequisites.
The later local image checks have the bounded results above and are not stable
release evidence.
