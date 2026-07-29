# Phase 1 release limitations

This root report mirrors the maintained detail in `docs/KNOWN_LIMITATIONS.md`.

- Image definitions exist, but no OCI/QCOW2/recovery artifact was built or booted here.
- No VM, physical hardware, Secure Boot, TPM, LUKS2, GPU, suspend, audio, Wi-Fi, Bluetooth, or multi-display test ran.
- Bunny is an honest non-functional 0.2.0 placeholder pending a signed upstream Linux release.
- Update keys/registry signature enforcement/release signing/repository snapshots are absent; automatic updates are off.
- Repeated-build reproducibility and generated SBOM/license/vulnerability evidence are absent.
- SELinux prototype is not installed pending AVC qualification.
- Recovery safe graphics is an unqualified one-shot BLS prototype; full restore/backup restore and a custom installer are not implemented.
- Fedora 44 is short-lived and must be rebased before its changeable May 2027 EOL.
- x86-64/UEFI only; NVIDIA proprietary, ARM64, remote access, shared models and consumer UX are out of scope.

## Phase 2

- Bunny Shell source and the 92-test host suite pass, but no shell/developer/recovery image was built or booted on this host.
- GNOME 50 extension/session, GTK surfaces, GDM selection, portals, suspend/lock, multi-monitor, accessibility runtime, VM, and hardware remain untested.
- The upstream Bunny placeholder prevents end-to-end tasks, plans, approvals, provider activity, and authenticated Core-summary validation.
- Host performance results are deterministic Python-only microbenchmarks; graphical and idle-resource targets are unmeasured.
- Phase 2 is source-implemented but not validation-complete or releasable.

These are release blockers or explicit Phase 1 boundaries, not passing results.

## Phase 3

- Anaconda/bootc live and beta definitions, typed planning, first run, applications, and 60 host tests exist; the production Anaconda adapter is absent and disk writes fail closed.
- No Phase 1/2 artifact existed at preflight, and no Phase 3 ISO/raw/QCOW2/recovery artifact was built or booted.
- No real disk discovery, partition/format/encryption, UEFI entry, LUKS unlock, Secure Boot/TPM, clean install, upgrade, rollback, recovery, UI/accessibility runtime, or physical hardware test ran.
- Dual boot supports source planning into already-unallocated free space only. Resize, BitLocker, encrypted Linux, RAID/multipath/LVM reuse, FileVault, and unknown sectors are unsupported.
- Proprietary NVIDIA, legacy BIOS, ARM64, production OEM/unattended flow, stable channel, cloud accounts, and application-store operation remain out of scope.
- Media manifest/signing hooks exist but no signed manifest is embedded/proven in an ISO; no SBOM or supply-chain result exists.

Phase 3 is source-implemented in part but not definition-of-done complete and not beta releasable.

## Phase 5

- Phase 4/public-beta reports, issue exports, images, update metadata, observations, hardware submissions, crash summaries, and failure records are absent.
- Phase 5 source tooling/tests/docs exist, but no real beta issue was reproduced or fixed and no reliability rate can be calculated.
- No stable candidate, signed artifact, migration, rollback, recovery, multi-user, local-only, Bunny-disabled, privacy traffic, manual diagnostic, accessibility runtime, hardware, kernel/driver, power/boot, pressure, or multi-day soak qualification exists.
- Support duration, stable date, default kernel, hardware list, application catalogue, and downgrade promise are intentionally uncommitted.
- The stable-candidate and stable-release gates fail closed; `STABLE_RELEASE_GO_NO_GO.md` is `NO-GO`. Nothing is published.

## Phase 6

- Phase 6 stopped at mandatory preflight because Phase 5 remains `NO-GO`; `docs/PHASE_6_BASELINE.md` records the decision.
- No approved stable version, candidate, source tag, soak, signed artifact, checksum, public key, SBOM, provenance, license report, reproducible-build comparison, protected approval, or publication exists.
- No stable branch, mirror, download, announcement, update rollout, security advisory, maintenance release, support commitment, key ceremony, post-release review, or EOL action was created.
- The public GitHub tracker currently has zero open issues, but no qualified beta/runtime population exists; unknown evidence and the five protected qualification blocker codes remain blocking.
- Every stable hardware tier, supported install/upgrade path, maintenance cadence, security-only window, and EOL date remains uncommitted.

## Phase 7

- Phase 7 stopped at mandatory preflight because there is no completed stable
  release and the protected stable gate remains `NO-GO`.
- No OEM profile, factory finalisation, device identity, attestation, enrolment,
  policy agent, fleet service, console, tenant isolation, encrypted sync,
  pairing, recovery, air-gap, kiosk, or decommission implementation exists.
- No Phase 7 component, adversarial, reliability, hardware-qualification, or
  pilot test ran; no production, pilot, service, support, demand, or cost claim
  is supported.
- OEM manufacturing, enterprise rollout, and hosted sync launch remain
  prohibited. See `docs/PHASE_7_BASELINE.md`.
- Local developer and beta OCI/QCOW2 builds now compose, inspect, and boot under
  QEMU/KVM, and beta raw composition plus release-mode license scanning pass.
  These are unsigned disposable validation artifacts, not stable evidence.
- The current beta vulnerability gate fails on fixable Critical/High findings
  in Fedora's kernel and bootc-required Podman/Skopeo/Toolbox dependency set.
  No release waiver exists.

## Phase 7 limitations

Phase 7 delivered OEM, enterprise-management, and encrypted-sync **source, schemas, validators, tests, and documentation**. It delivered no running system. The following are open and are the reason every pilot gate fails.

- **No fleet server, enrolment service, or enterprise console exists.** They are separate trust domains outside this repository. Nothing has been deployed, load-tested, failed over, or penetration-tested.
- **The policy agent has no privileged transport.** `services/bunny-system-broker/src/bunny_system_broker/auth.py` refuses UIDs below 1000 and `authorize_polkit` requires an active logind session; a headless agent has neither. A separate socket with its own peer-credential rule is required and is not implemented.
- **The settings layer has no organisation scope.** All 22 settings in `shell/services/bunny_shell/settings.py` are user-scoped with no override or locked-setting mechanism, so resolved policy cannot yet change a running desktop.
- **Factory finalisation evaluates a supplied record, not a device.** A factory submitting a dishonest record would seal a device that still holds credentials. This becomes Critical the moment a real provisioning line runs. `bunny-oem provision` and `seal` exit 78.
- **No reviewed sync cryptography backend is installed** and no independent cryptographic review has been commissioned. `sync/crypto.py` refuses every operation rather than degrading.
- **No hardware has been qualified.** Zero models, zero repeat runs, zero sustained-load campaigns, no recovery media booted, no OEM image built.
- **No OEM signing key infrastructure exists.** No key ceremony, no offline storage procedure, no rotation rehearsal, and only one potential release signer.
- **Sync metadata is genuinely revealing.** Account identity, device count, object sizes, upload times, and version counts are visible to an operator. The design is not zero knowledge and is not described as such.
- **Audit chains have no off-device anchoring.** An attacker with write access from entry N can rewrite the chain from N forward.
- **No root `LICENSE` file and no trademark policy exist.** Both block OEM and enterprise distribution. See `LICENSE_COMPLIANCE_REPORT.md`.
- **Support capacity is one maintainer**, which is smaller than the Phase 7 surface. See `SUSTAINABILITY_REPORT.md`.
- Fleet simulation is arithmetic over synthetic counts and is never production-readiness evidence.

All inherited limitations above remain unchanged, including the stable-release `NO-GO`, the five blocker codes, the 31 missing evidence entries, and the 59 fixable vulnerability findings.
