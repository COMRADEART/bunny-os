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

Phase 7 delivered OEM, enterprise-management, and encrypted-sync **source, schemas, validators, tests, and documentation**. Four capabilities deferred at the time have since been implemented and are struck through below. The rest remain open and are why every pilot gate still fails.

- **No fleet server, enrolment service, or enterprise console exists.** They are separate trust domains outside this repository. Nothing has been deployed, load-tested, failed over, or penetration-tested.
- ~~The policy agent has no privileged transport.~~ **Closed.** A second socket at `/run/bunny/policy.sock`, mode 0600, with `require_policy_identity` as a sibling of the untouched `require_local_user`, its own method table, and its own rate limiter. What remains unproven is delivery: no policy has reached a running device because no control plane exists to send one.
- ~~The settings layer has no organisation scope.~~ **Closed.** A root-owned overlay at `/etc/bunny-os/managed-settings.json`, an allowlist of manageable settings, `SettingLockedError` on a locked write, and `reset()` returning the organisation value rather than the default.
- ~~Factory finalisation evaluates a supplied record, not a device.~~ **Largely closed.** `bunny-oem inspect --root` settles 17 of 22 checks by inspecting a filesystem tree. Five need firmware state, booted media, or a burn-in campaign and report `UNKNOWN`, so an offline probe alone still never seals a device; `merge_attestation` supplies those from a signed live record and refuses to override an inspected result. `provision` and `seal` still exit 78: nothing writes to a real device.
- **No independent cryptographic review has been commissioned.** A working backend now exists (`sync/backends/reference.py`, AES-256-GCM with bound associated data, HKDF-SHA256, RFC 3394 key wrap) and is covered by round-trip and tamper tests, but a design reviewed only by its author is not a reviewed design. XChaCha20-Poly1305 is refused rather than substituted because the available library cannot provide it. When the backend is absent, every operation still raises rather than degrading.
- **No hardware has been qualified.** Zero models, zero repeat runs, zero sustained-load campaigns, no recovery media booted, no OEM image built.
- **No OEM signing key infrastructure exists.** No key ceremony, no offline storage procedure, no rotation rehearsal, and only one potential release signer.
- **Sync metadata is genuinely revealing.** Account identity, device count, object sizes, upload times, and version counts are visible to an operator. The design is not zero knowledge and is not described as such.
- **Audit chains have no off-device anchoring.** An attacker with write access from entry N can rewrite the chain from N forward.
- **No root `LICENSE` file exists.** This blocks OEM and enterprise distribution independently of every other gate and is a project decision, not an engineering one. A draft trademark policy now exists at `docs/TRADEMARK_POLICY.md` but has had no legal review.
- **Support capacity is one maintainer**, which is smaller than the Phase 7 surface. See `SUSTAINABILITY_REPORT.md`.
- Fleet simulation is arithmetic over synthetic counts and is never production-readiness evidence.

All inherited limitations above remain unchanged, including the stable-release `NO-GO`, the five blocker codes, the 31 missing evidence entries, and the 59 fixable vulnerability findings.

## Maturity ladder, 2026-07-30

These five states are distinct and this repository is at the first. Every
document listed below reports the same position; if any of them disagrees, that
document is wrong.

| State | Meaning | Bunny OS |
|---|---|---|
| **Source implemented** | Design, schemas, validators, tests and documentation exist and pass | **yes** — Phases 1–7 |
| **Runtime validated** | The software has been built and observed doing the thing on real or virtual hardware | **partial** — images build from a digest-pinned base and boot under KVM; installation, encryption, update, rollback and recovery matrices have not run |
| **Release qualified** | `gate-stable-release` reports `GO` against a complete evidence record | **no** — 2 of 20 evidence categories pass |
| **Pilot approved** | A pilot gate reports `GO` and a controlled pilot has separate approval | **no** — all three gates `BLOCKED` |
| **Production operated** | A service or fleet is actually being run and supported | **no** — nothing is operated, and operating nothing remains a legitimate outcome |

Agreeing documents: `README.md`, `NEXT_PHASE.md`, `docs/PHASE_7_BASELINE.md`,
`PHASE_7_REPORT.md`, `KNOWN_LIMITATIONS.md`, `PILOT_READINESS_REPORT.md`.

Current authority for the closure position: `RELEASE_BLOCKER_CLOSURE_REPORT.md`
and `STABLE_EVIDENCE_REPORT.md`.

## Release blocker closure limitations, 2026-07-30

Each is a limitation of the *evidence* rather than of the design, and each names
what would remove it.

| Limitation | Consequence | Removed by |
|---|---|---|
| 8 Critical and 28 High fixable findings inherited from the base image, all dispositioned `Unknown` | `gate-stable-release` blocks on `vulnerability-position` | Fedora rebuilding the container stack, or an independent security review answering reachability per CVE |
| The "is the vulnerable code path active" question could not be answered | 24 findings stay `Unknown` rather than reaching a disposition | per-CVE symbol analysis of stripped Go binaries, by a reviewer |
| Package removal does not remove bytes from the base's ostree object store | minimisation cannot reduce image size, SBOM contents or scan counts on this base | a base rebuilt without the package |
| Archive-derived and SBOM-derived scan counts disagree, 59 against 84 | two numbers exist for one image; the archive scan is authoritative | investigating syft's cataloguing of ostree objects |
| Only one builder machine exists | `independent-builder` reproducibility cannot be established | a CI runner, a second machine, or a second administrator |
| No production signing key of any role | the `Signing` evidence row records `FAIL` | a key ceremony, which needs a second person for four of the seven roles |
| No live ISO and no signed recovery ISO | installation, encryption and recovery matrices cannot run even in a VM | building them |
| No published update manifest and no previous release | update, rollback, migration and preservation matrices cannot run | publishing one and keeping the other |
| No physical machine, ever | `Hardware` and `Secure Boot` categories block; the OEM pilot blocks | one x86-64 UEFI machine |
| No independent review of any kind | four evidence positions rest on self-assessment | commissioning them |
| Accessibility evidence is entirely static | 14 essential workflows unverified; this is the limitation that risks harming a user rather than merely leaving a box unticked | driving them with assistive technology |
| `tests/hardware_evidence/`, `tests/accessibility_evidence/` and `tests/pilot_gates/` use underscores where the brief writes hyphens | directory names differ from the brief | nothing - a hyphenated directory is not an importable Python package, so `unittest discover` would skip it and the tests would silently never run |
