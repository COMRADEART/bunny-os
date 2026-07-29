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
