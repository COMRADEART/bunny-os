# Bunny OS Phase 1 implementation report

Date: 2026-07-28  
Branch: `feature/os-foundation`  
Baseline: `8fc27253e448cfe0cbe267231f816012f831ebf0`

## Current implementation state — 2026-07-30

Branch: `feature/qualification-evidence-closure`
Base commit: `80df25b09f6578276d18c8a82f15c47dd8959740`

```text
Source gate:               PASS
Qualification candidate:   BLOCKED   (2 of 14)
Stable release:            NO-GO
OEM / enterprise / sync:   BLOCKED
```

### Delivered by the qualification evidence closure

| Area | Deliverable |
|---|---|
| Independent builder | `.github/workflows/independent-builder.yml` (4 jobs) — **prepared, not executed** |
| Builder identity | `release/builders.py` — schema 2 records an administrator *boundary*, not an identifier, and has no `workspace` field |
| Independence rules | 4 accepted pairings, 8 adversarial rejections |
| Normalisation | `release/normalisation.py` — 8 normalisable properties, 7 protected and enforced, raw **and** normalised digests |
| Comparison | `release/comparison.py` — 17 dimensions, 3 states, 4 outcomes; `NOT_COLLECTED` cannot support a pass |
| Provenance | `release/provenance.py` — every claim recomputed from bytes or held locally; verification must run in a different environment from the build |
| Per-CVE analysis | `release/cve.py`, `security/reachability/` — 29-field record, 12-field mapping, 5 proof classes with per-class evidence requirements |
| Acquisition | `release/acquisition.py` — Fedora hosts only, exact NEVRA matching, nothing committed |
| Symbol analysis | `scripts/reachability.py` — and a refusal to treat an absent symbol as absent code |
| Review bundles | 24 advisories × 9 files, self-contained |
| Review intake | `IndependentReviewRecord` — signed, digest-verified, commit-bound, self-review refused |
| Review requests | 4 × `reviews/*/REQUEST.md`, 10 sections each |
| Hardware collector | `bunny-os qualification collect` — 17-field allow-list, 12 excluded categories, 21 guided tests |
| Hardware signatures | 3 roles; the word "certified" refused in code |
| Accessibility | `release/accessibility.py` — 17 flows, 7 critical, static results refused |
| Second signer | `docs/SECOND_SIGNER_ONBOARDING.md`, `docs/TWO_PERSON_RELEASE_APPROVAL.md` |
| Two-person drill | `scripts/two_person_drill.py` — **PASS 9/9** with two real Ed25519 keys |
| Candidate readiness | `release/candidate.py` — 14 prerequisites, fail-closed, 8-state dashboard, no percentage |
| Gates | 6 separated: source, qualification-candidate, stable-release, and three pilots |
| CI protection | `.github/workflows/qualification-evidence.yml` — 10 named protections |
| Tests | 510 qualification tests across 11 suites, up from 252 across 9 |
| Build | `BUNNY_ARCHIVE_ONLY=1` in `build/scripts/build-image.sh`, so a hosted runner can be a real second builder |

### Two defects fixed in existing code

1. **The evidence record invalidated itself.** Evidence was compared against `HEAD`,
   so committing the record changed `HEAD` and invalidated it in the same act — all
   twenty records failed at `80df25b`, including two that genuinely passed.
   `operations/data/release-evidence.json` now declares a `candidateCommit` and the
   gate compares against that. Wrong-commit evidence still blocks.
2. **The generated qualification reports were labelled with `HEAD`** rather than the
   commit their scenarios were measured at, so each claimed to describe a tree it was
   not taken from. `scripts/write_qualification_reports.py` now reads the candidate
   commit.

### What was deliberately not built

No new OEM, enterprise, fleet, encrypted-sync or consumer feature. No Phase 8 work.
No pilot. No gate weakened.

See `QUALIFICATION_EVIDENCE_CLOSURE_REPORT.md`.

---

## Phase 1 delivery (2026-07-28)

## Delivered

- Fedora 44 bootc/GNOME/Wayland/SELinux/firewalld architecture and four accepted OS ADRs.
- Independent contract 1.0.0 JSON Schema, update-manifest schema, and Bunny artifact schema.
- AF_UNIX/SO_PEERCRED broker with exact methods/params, Polkit, logind binding, nonce replay/rate controls, timeouts/cancellation, fixed subprocesses, bounded output, safe errors, and metadata audit.
- Conventional `bunny-os` CLI and local-only `bunny-os-info` with evidence states rather than support inference.
- Hardened system/user units, tmpfiles, sysctl, firewall zone, privacy-first first boot, offline health, and recovery target/profile.
- Signed Ed25519 manifest verification, revocation, expiry/channel/arch/contract/Bunny/repository/digest/space/sequence gates, atomic state, and bootc staging/rollback scaffolding.
- OCI Containerfile, explicit package/profile manifests, unified `image-builder` wrappers, image inspection/QEMU smoke scripts, provenance/checksums, SPDX/CycloneDX generation, vulnerability/license scans.
- Explicit upstream Bunny 0.2.0 placeholder and fail-closed release-directory hash/mode/path verifier. No Bunny source was copied or changed.
- Host tests, self-hosted privileged image CI gate, SELinux compile job, ten source diagrams, and demonstration package.

## Important implementation constraint

The original documents named the standalone `bootc-image-builder`; upstream OSBuild has merged/archived it. Phase 1 therefore uses unified `image-builder` and retains `bootc` in the installed system. This is a verified constraint update, not an architecture change.

## Not delivered as a result

No bootable artifact was produced on this host and no VM or hardware boot was observed. The repository contains the build system and bootable-image definition; `IMAGE_BUILD_REPORT.md` and `VM_TEST_REPORT.md` correctly record blocked execution. Phase 1 cannot be called release-complete against the user's definition of done until those gates run.

## Phase 2 implementation update

Branch `feature/bunny-shell` adds the GNOME 50 Bunny/Safe session definitions, image-owned extension, GTK launcher/settings/workspace/project/task/plan/approval/command surfaces, private metadata search, pinned/recent launcher state, workspace/settings/Core-summary/intent/terminal schemas, command parser/classifier, local/offline policy evaluation, private opt-in clipboard handling, bounded Git status, Nautilus actions, original themes/icons/wallpapers, bounded systemd user units, shell/shell-test image profiles, Phase 2 make targets, 59 new host tests, ADR-005 through ADR-009, user/developer documentation, and the demonstration package.

The implementation preserves GNOME/Mutter, Files, Terminal, Settings, notifications, portals, AT-SPI, base GNOME, and the Phase 1 broker. It adds no root or generic execution path. Source/host gates pass; image, GNOME, VM, Bunny Core, accessibility runtime, and hardware validation are not delivered on this host. See `PHASE_2_REPORT.md`.

## Phase 3 implementation update

Branch `feature/installer-and-beta-image` adds the installation baseline audit, ADR-010 through ADR-015, typed protocol/schema, serial-redacted fixed disk probe, target safety/confirmation, erase/encrypted/free-space/manual plan validation, primary-user policy, LUKS2/TPM/recovery-key policy, authenticated simulation-only backend, staged progress/cancellation model, redacted audit, media signature/checksum verification, hardware/driver detection and classification, resumable GTK first run, Flatpak/native permission policy, Fedora Anaconda Web UI/bootc live and beta profiles, offline package sets, boot menu, ephemeral live identity, no-automount configuration, media manifest/signing hooks, QEMU disposable-disk launch definitions, 19 installer guides, demonstration package, and 60 Phase 3 host tests.

The implementation deliberately contains no Bunny raw-disk executor. `install.start` fails before writes unless a reviewed Anaconda adapter is supplied. No Phase 1/2 image existed, so no live/beta artifact, install, LUKS, Secure Boot, VM, upgrade, rollback, recovery, UI runtime, or hardware result is delivered. See `PHASE_3_REPORT.md`.

## Phase 5 implementation update

Branch `feature/stable-qualification` adds the Phase 5 baseline, strict local feedback ingestion/redaction, component/severity taxonomy, advisory duplicate matching, failure-signature catalogue, monotonic installer transaction journal, update compatibility rejection, content-free preservation comparison, evidence-only hardware tiers, privacy-safe crash aggregation, multi-user/local-only/Bunny-disabled evidence rules, alert-only maintenance checks, complete-candidate validation, per-artifact detached-signature verification, external signing-key enforcement, stable decision engine, no-score dashboard, safe rollback/recovery fixture launchers, schemas, 74 host tests, stable operations/support guides, reports, and the 17-file demonstration package.

The implementation cannot publish, auto-close, lower severity, ingest user content, promote hardware without evidence, or pass stable gates with unknown rows. Phase 4/public-beta artifacts and observations are absent, so no beta defect correction, RC, installation, migration, rollback, recovery, soak, hardware, runtime privacy/accessibility, or stable release is delivered. See `PHASE_5_REPORT.md`.

## Phase 7 preflight update

Branch `feature/oem-enterprise-and-sync` contains only the mandatory evidence
baseline and stop report. It adds no OEM, factory, identity, enrolment, policy,
fleet, console, sync, air-gap, kiosk, or decommission implementation because the
stable entry gate failed closed. See `docs/PHASE_7_BASELINE.md` and
`PHASE_7_REPORT.md`.

## Phase 7 blocker-remediation update

No Phase 7 feature boundary was opened, but locally solvable inherited image
defects were repaired on `feature/oem-enterprise-and-sync`: current
image-builder multi-format invocation, bootc/OSTree filesystem inspection,
health-service writable-state policy, strict VM health-marker enforcement, and
SPDX concluded-versus-declared license handling with provenance-based coverage.
Fedora validation also corrected ignored systemd start-limit placement and the
unsupported Bunny executable-condition name. Regression tests cover each source
change, installed-path unit verification passes, and native ShellCheck is clean.

Real Fedora builds then produced and inspected developer and beta images. The
beta QCOW2/raw compose, `qemu-img` check, libguestfs inspection, SBOM/license
gate, and QEMU/KVM boot-health smoke passed. The vulnerability gate failed on
the current Fedora 44 kernel and bootc-required Podman/Skopeo/Toolbox packages,
so the release and Phase 7 entry decisions remain `NO-GO`.

## Phase 7 implementation

Phase 7 adds OEM, enterprise-management, and optional encrypted-sync source. Three new top-level packages, all Python standard library only:

- `oem/` — signed profile validation, overlay validation, hardware qualification evaluation, 22-check factory finalisation, and the `bunny-oem` CLI.
- `enterprise/` — device identity, attestation, enrolment, typed policy agent, conflict precedence, remote administration boundary, fleet groups and rings, organisation catalogue, fleet health, tamper-evident audit, roles and console authorisation, multi-tenant scoping, air-gapped bundles, kiosk and shared-device profiles, decommissioning, and pilot gating.
- `sync/` — versioned encrypted envelope, key hierarchy, authenticated pairing, deterministic conflict resolution, selective sync, account recovery, deletion semantics, metadata disclosure, backup and migration, and the cryptographic executor boundary.

Eleven new schemas in `schemas/`, each paired with a hand-written validator and rejection tests, following the existing convention. Twenty-five new documents in `docs/`, seven ADRs (`ADR-020` through `ADR-026`), an 18-file demonstration package, and thirteen new root reports.

New commands: `phase7-audit`, `phase-7-baseline`, fourteen `test-*` targets, `fleet-simulation`, `pilot-readiness`, `build-oem-image`, `gate-phase-7-source`, `gate-phase-7`, and the three pilot gates. All wired through `scripts/task.py` and `scripts/phase7.py`.

454 tests were added across fourteen test packages; the main suite is now 557 tests plus 60 installer and 74 operations tests, all passing.

Server components are deliberately absent. The fleet server, enrolment service, and enterprise console are separate trust domains with independent deployment lifecycles and are not in this repository; see `docs/adr/ADR-023-fleet-control-plane.md`. No server code was placed in `services/`, `build/`, or any boot or recovery path.

Executors that would touch real hardware or perform real cryptography report themselves unavailable and exit 78 rather than degrading: `bunny-oem provision`, `seal`, and `build-image`, and every operation in `sync/crypto.py`.

Four defects were fixed during implementation, three of them caught by new tests: an unreachable OEM key-namespace check, a policy validator registered with the wrong arity, two privacy refusals preempted by a generic unknown-field check, and a test-discovery configuration in `scripts/task.py` that put `tests/` on `sys.path` so `tests/sync` and `tests/oem` shadowed the real packages.

The Phase 7 source gate passes. `gate-phase-7` and all three pilot gates remain blocked, and the stable release remains `NO-GO`.

## Phase 7 addendum: deferred capabilities implemented, runtime evidence produced

Four capabilities the Phase 7 report deferred are now implemented: the policy agent's privileged transport (a second broker socket with its own identity rule), the settings organisation scope (a root-owned managed overlay), the factory executor (`bunny-oem inspect --root`, settling 17 of 22 checks by inspection), and a working sync AEAD backend (AES-256-GCM, HKDF-SHA256, RFC 3394 key wrap, with XChaCha20 refused rather than substituted).

The three VM harnesses that previously exited 78 now do real work, sharing one boot path factored out of `vm-smoke.sh`.

Real artifacts were produced on the Fedora WSL builder: a 2.3 GB QCOW2, a 2.0 GB OCI archive, a 60 MB SPDX SBOM, a clean licence scan over 6,252 packages, two KVM boots reaching health markers, a quiet-boot packet capture, and a two-build determinism comparison.

A regression introduced by the two-socket work was caught by a real boot rather than by any test: systemd names an inherited descriptor after the socket unit when `FileDescriptorName=` is unset, and the new code rejected it, so the broker crash-looped and the health check failed with it. Fixed, regression-tested against the real name, rebuilt and re-verified.

Suite total is now 671 main-suite tests plus 60 installer and 105 operations tests, passing identically on Windows and Fedora.

## Release blocker closure, 2026-07-30

A `release/` package was added - standard-library only, like `operations/`,
`enterprise/`, `oem/` and `sync/` - implementing the evidence model and the gates
that consume it.

| Module | Responsibility |
|---|---|
| `release/vulnerability.py` | per-finding disposition; refuses a severity reduction or a non-blocking Critical without a completed independent review |
| `release/reachability.py` | the ten-question bounded review; an unanswered question cannot become a negative answer |
| `release/minimisation.py` | package removal with five protected categories refused at parse time |
| `release/licensing.py` | the seven-requirement licence gate; refuses an unattributed approval |
| `release/reproducibility.py` | four separated claims; refuses `independent-builder` without a strong dimension |
| `release/signing.py` | seven roles, disjoint namespaces, the `dev-` wall, rotation overlap |
| `release/artifacts.py` | candidate manifests, nine mandatory fields, naming discipline |
| `release/matrix.py` | seven qualification matrices; recovery and accessibility cannot pass on source inspection |
| `release/hardware.py` | redaction scanning and claim substantiation |
| `release/reviews.py` | review packages and the self-review wall |
| `release/evidence.py` | 20 categories with forgery, staleness, wrong-commit and self-review detection |
| `release/gates.py` | four separated gates |

Entry points: `scripts/release.py` with 14 commands, `scripts/signing_drill.py`,
`scripts/generate_disposition.py`, `scripts/build_evidence_record.py`,
`scripts/write_qualification_reports.py`, and `scripts/reproducibility/`.

24 new `make` targets. A CI workflow with nine jobs, every one of which expects
to fail closed, plus an assertion that no gate reports `GO` without protected
evidence.

Changes outside the new package:

- `build/scripts/install-packages.py` gained profile-driven package removal with
  a post-removal check that every protected package survived.
- `build/packages/protected.txt` added.
- Four consumer profiles gained `removePackages`.
- `LICENSE`, `LICENSES/`, eight directory licences, 127 SPDX headers.
- `scripts/reproducibility/compare-builds.py` compares package manifests
  semantically, excluding syft's path-named document-root entry.

Two behaviours were corrected after tests exposed them: a redaction heuristic
that rejected timestamps, and an absent qualification matrix that reported as
satisfied.

Result: `gate-stable-release` reports `NO-GO` and all three pilot gates report
`BLOCKED` - both now produced by an evidence model that can say precisely which
of twenty categories is missing and why.
