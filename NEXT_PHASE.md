# Next work after the Phase 1 implementation pass

Do not start a custom shell, compositor, visual redesign, installer experience, app store, or consumer release.

## Next work — 2026-07-30

**Do not begin Phase 8. Do not begin an OEM, enterprise or encrypted-sync pilot.**

The qualification evidence closure completed every technically automatable evidence
task. What remains is ordered below by cost, and the cheapest item is genuinely
cheap.

### 1. Dispatch the hosted builder — one workflow run

`.github/workflows/independent-builder.yml` is committed and has never run. It is the
only one of the fourteen candidate prerequisites that needs nothing but a button.

Before dispatching, verify `BUNNY_ARCHIVE_ONLY=1` on the Fedora/KVM builder:

```sh
BUNNY_ARCHIVE_ONLY=1 \
BUNNY_BASE_IMAGE=quay.io/fedora/fedora-bootc:44@sha256:fb71f099f40360b5e1e2e78e845ccf4f0f80fbe1b09de721d8954cddb89ee9c4 \
  bash build/scripts/build-image.sh beta
```

Then, on the builder, collect the local half and dispatch the hosted half:

```sh
make collect-builder-record BUNNY_BUILDER_ID=local-fedora
# dispatch the workflow against this commit and the pinned digest
make verify-builder-independence
make compare-independent-builds
```

The comparison then needs the sixteen uncollected dimensions gathered from both
builders. That is one build on each side, not more analysis.

### 2. Build a live ISO and a signed recovery ISO — engineering

Unblocks the installation, encryption and recovery matrices in a VM, three evidence
categories, three candidate prerequisites, and the `recovery-media-failure` blocker
code. It also makes five of the seven **critical** accessibility flows reachable
without hardware, which is the single largest reduction in this project's
accessibility risk available for free.

### 3. Publish a signed update manifest and keep a previous release — engineering

Unblocks update, rollback, migration and data preservation.

### 4. Resolve the CVE carrier attribution — engineering

Mount the beta deployment and run:

```sh
make analyse-cve-symbols BUNNY_SYSROOT=/mnt/beta
```

This does **not** answer question 7. It resolves which of the four ostree objects is
which installed binary, confirms or refutes the `toolbox` attribution for
`GO-2026-5970`, and collects build IDs, stripped state and dynamic dependencies —
removing that work from the reviewer's scope and lowering what the review costs.

### 5. Drive the eleven post-install accessibility flows — engineering

Flows 7–17 need an installed system and Orca on GNOME 50, not hardware. Doing this
before commissioning the review means the reviewer finds the residue rather than the
obvious failures.

### 6. Commission the four independent reviews — needs a third party and money

All four requests are ready to send:

| Request | Unblocks |
|---|---|
| `reviews/security/REQUEST.md` | the only route to dispositioning any Critical finding |
| `reviews/cryptography/REQUEST.md` | `gate-sync-pilot` outright |
| `reviews/accessibility/REQUEST.md` | the `Accessibility` category and approval |
| `reviews/legal/REQUEST.md` | OEM distribution; the anti-tivoisation question |

### 7. Acquire one x86-64 UEFI machine — needs hardware

With Secure Boot and TPM 2.0. Blocks two evidence categories that nothing else
satisfies, the OEM pilot, and two accessibility flows.

### 8. Find a second production signer — needs a person

`docs/SECOND_SIGNER_ONBOARDING.md` is the material they would need; twelve of its
fifteen readiness items are done. Four of seven signing roles cannot be provisioned
at all without them.

### 9. Owner decisions

The nine protected approvals; whether to fund the reviews; whether to acquire
hardware; and which Phase 7 capabilities to operate, if any. **Operating none remains
a legitimate answer and is still the recommendation.**

### What not to do next

- Do not change the base image. `docs/adr/ADR-027-base-image-security-decision.md`
  evaluated three options across fifteen dimensions; none improves the vulnerability
  position and two make everything else worse.
- Do not add a feature. No OEM, enterprise, fleet, encrypted-sync or consumer
  feature belongs in the next pass.
- Do not weaken a gate. Four of the six are expected to keep blocking, and that is
  the correct result while the evidence is absent.

The immediate next milestone is **Phase 1 validation closure**:

1. provision trusted Fedora 44/KVM builder with digest-pinned base and unified image-builder;
2. run compose/inspection/SBOM/vulnerability/license/two-build gates and fix real package/tool differences;
3. boot QEMU/KVM and qualify services, first boot, network/listeners/privacy, health/update/rollback/recovery;
4. enforce and test OCI signature policy plus update key ceremony;
5. qualify SELinux domains and systemd security scores;
6. obtain signed upstream Bunny 0.2.0 Linux artifacts and run lifecycle/protocol/rollback tests;
7. run VMware/VirtualBox then named physical/Secure Boot/LUKS/GPU matrices.

Upstream Bunny requirement: publish a signed x86-64 Linux Tauri release directory containing Bunny Desktop, `bunny-core`, `ccgrep`, protocol v3 schema/provenance, SHA-256/modes/source commit, updater signature, SBOM, and clean install/update/rollback evidence. No Bunny repository edit was made in this phase.

## Phase 2 validation closure

Phase 2 source has now been implemented on `feature/bunny-shell`, but the inherited Phase 1 blockers prevented the required boot preflight and the Phase 2 image/VM/accessibility definition of done. The next milestone remains validation closure:

1. run `FULL_GATE=1 make gate-phase-2` on the pinned Fedora 44/KVM builder;
2. fix real package, GLib schema, systemd, GNOME 50 extension, GDM session, portal, and SELinux findings;
3. boot developer/shell/shell-test/recovery images and execute both VM matrices;
4. install the signed Bunny artifact and qualify authenticated task/plan/approval/provider/degraded flows;
5. execute Orca, keyboard, contrast/scale/motion, multi-monitor, suspend/resume, performance, privacy-egress, VMware/VirtualBox, and physical hardware tests;
6. archive image provenance, checksums, SBOM, vulnerability/licence reports, VM logs, and exact configurations.

Do not start Phase 3, an installer, app store, device provisioning/manufacturing, consumer distribution, or stable release work until these rows pass.

## Phase 3 validation closure

Phase 3 source work now exists on `feature/installer-and-beta-image`, but the inherited image blockers and absent Anaconda adapter prevent completion. Do not begin Phase 4. The next milestone is evidence closure:

1. close Phase 1/2 builder, signed Bunny, registry, SELinux, GNOME, accessibility and VM blockers;
2. pin/qualify Fedora 44 Anaconda Web UI, Blivet, cryptsetup, bootc and unified image-builder packages;
3. implement and externally review the narrow authenticated Anaconda adapter and protected secret channel;
4. build, sign, inspect and archive beta QCOW2/raw, live ISO, recovery, manifests, SBOMs, provenance and scans;
5. pass disposable-disk empty/encrypted/free-space/manual/failure/power-loss suites and prove no secret leakage;
6. pass UEFI/Secure Boot positive/negative, LUKS password/recovery and optional TPM fallback;
7. install Phase 2 then upgrade/rollback/recovery with user, Bunny, workspace, plugin, application and model preservation;
8. run Orca/keyboard/contrast/scale/motion/localisation and multi-user isolation;
9. run VMware/VirtualBox then named physical Intel/AMD/NVIDIA/NVMe/Wi-Fi/HiDPI matrices;
10. re-review Blocker/High findings and publish a beta candidate only when no Blocker remains.

Stable release, OEM partnerships/manufacturing, public store operation, cloud services and fleet management remain prohibited.

## Phase 5 qualification closure

Phase 5 operations/source work now exists, but it did not cure the absent Phase 4/public-beta baseline. Do not begin Phase 6 or publish stable. The next action is evidence closure:

1. complete Phases 1–3 image/runtime blockers and a production installer adapter;
2. implement/validate Phase 4 and operate signed public-beta releases with privacy-safe issue/failure exports;
3. reproduce confirmed defects, add regression tests, and issue immutable signed beta updates;
4. produce a clean signed stable RC with SBOM, provenance, license/malware/reproducibility evidence;
5. pass repeated install/encryption/update/rollback/recovery/migration/data-preservation matrices;
6. pass multi-user, Bunny-disabled, local-only, listener/traffic, diagnostic, security/privacy/accessibility gates;
7. qualify named kernels/drivers and physical hardware tiers, then complete power/pressure and multi-day soak;
8. obtain all protected approvals and regenerate reports from evidence;
9. publish only if `gate-stable-release` passes and the go/no-go report changes to `GO`.

OEM manufacturing, custom firmware, enterprise fleet management, paid cloud services, mandatory accounts, advertising, data monetisation, and stable publication remain prohibited.

## Phase 6 entry remains blocked

The Phase 6 mandatory preflight is recorded in `docs/PHASE_6_BASELINE.md` and `PHASE_6_REPORT.md`. It stopped before branch creation or publication because the authoritative stable decision is `NO-GO`. Do not implement post-release operations or create `release/stable-1` until all of the following are true:

1. complete Phase 4/public-beta operation with traceable issue, reliability, privacy, accessibility, recovery, and hardware evidence;
2. close the five protected qualification blocker codes and every non-waivable stable blocker;
3. create a new immutable RC from a clean protected commit with ISO/raw/QCOW2/recovery media, checksums, detached signatures, SBOM, package manifest, provenance, release notes, and known issues;
4. pass independent signature verification, two-builder reproducibility, license/malware/supply-chain checks, and signing-key rotation/revocation recovery;
5. pass installed clean/encrypted/offline/update/rollback/recovery/migration/multi-user/local-only/Bunny-disabled/privacy/accessibility/hardware/soak matrices;
6. obtain the nine protected approvals and change `STABLE_RELEASE_GO_NO_GO.md` to evidence-backed `GO`;
7. rerun `gate-stable-release` successfully before creating any stable branch, tag, support promise, download, announcement, mirror, or update promotion.

## Phase 7 entry remains blocked

The Phase 7 mandatory preflight is recorded in `docs/PHASE_7_BASELINE.md` and
`PHASE_7_REPORT.md`. That preflight originally stopped before implementation;
**Phase 7 source was subsequently implemented in full** and is covered by 454
tests. This paragraph described the preflight stop and is retained for history —
see "After Phase 7 source" below for the current position.

Complete the Phase 6 closure sequence above, operate the stable
release, finish the named post-release reviews, and rerun
`gate-stable-release` successfully before adding OEM, enterprise-management,
fleet, or encrypted-sync trust boundaries. No pilot, manufacturing, broad fleet
deployment, or hosted-sync launch is authorised by this checkout.

The immediate technical blocker is to consume a reviewed Fedora 44 update or
supported rebase whose bootc-required Podman/Skopeo/Toolbox dependency set
passes the pinned Grype gate, then rebuild from a digest-pinned base. After
that, produce live and independent recovery media and continue the install,
encryption, update/rollback/recovery, reproducibility, accessibility, and
physical-hardware matrices.

Until then, the next milestone is Phase 1–5 validation closure, not a stable release or a Phase 7 lifecycle.

## After Phase 7 source

Phase 7 source is complete: OEM profiles, factory finalisation, device identity, enrolment, a typed policy agent, fleet rings, a remote administration boundary, multi-tenant scoping, encrypted sync, air-gapped management, kiosk and shared-device profiles, decommissioning, and pilot gating — 454 tests, all passing, with every pilot gate deliberately blocked.

**The next milestone is still not Phase 8.** Phase 7 cannot unblock itself: every one of its pilot gates depends on a published, signed stable release that does not exist. Working on more Phase 7 features would add surface to a system that cannot ship.

Ordered work, unchanged in priority from the previous section and extended:

1. Consume a reviewed Fedora 44 update or supported rebase whose bootc-required dependency set passes the pinned Grype gate; rebuild from a digest-pinned base. 8 Critical and 28 High findings currently block everything downstream.
2. Produce live and independent recovery media, then run the install, encryption, update, rollback, and recovery matrices.
3. Produce reproducibility evidence from two independent builders.
4. Close the five stable-release blocker codes and the 31 missing evidence and approval entries.
5. Write the missing records: `PHASE_4_REPORT.md`, `STABLE_PUBLICATION_REPORT.md`, the three `POST_RELEASE_*_REVIEW.md` documents, `STABLE_SUPPORT_MATRIX.md`, and `SECURITY_POLICY.md`.
6. Add a root `LICENSE` file and a reviewed trademark policy. Both block any OEM or enterprise distribution independently of everything above.

Only after a stable release exists do the Phase 7 follow-ups become meaningful:

7. Implement the policy agent's privileged transport and the settings organisation scope, so resolved policy can actually change a running desktop.
8. Implement the factory provisioning executor, so finalisation inspects a device rather than trusting a record.
9. Commission an independent cryptographic review of the sync design and select a reviewed backend.
10. Qualify at least one hardware model end to end, including validated recovery.
11. Decide which Phase 7 capabilities the project will actually operate, and confirm support capacity for exactly those. Operating none of them is a legitimate answer.

Only then does a controlled internal pilot become proposable, and it would still require separate approval.

## Revised ordering after the 2026-07-29 evidence run

Items 7 and 8 of the previous list are done: the policy agent transport, the settings organisation scope, and the factory inspection executor are implemented, and a working sync backend exists. Item 9, the independent cryptographic review, is unchanged because it needs a third party rather than code.

The critical path is now shorter and better understood:

1. **Decide what to do about a vulnerability position you cannot fix.** Measured since: all 59 consumer-facing findings (8 Critical, 28 High) come from `quay.io/fedora/fedora-bootc:44` itself. Rebasing returns the same digest, `dnf check-update` finds no newer podman or skopeo, and the packages are in the base rather than our lists — so none of the three obvious fixes is available. The real choice is between waiting for Fedora to rebuild the container stack, changing the base image (an ADR-001/ADR-002 decision), or arguing reachability per CVE and waiving with review, which `docs/STABLE_RELEASE_BLOCKERS.md` permits only for narrowly scoped High findings and never for 19 Criticals. See `SECURITY_REVIEW.md`.
2. ~~Fix archive determinism.~~ **Done.** `normalise-oci-archive.sh` pins entry order, mtimes, ownership and pax timestamps; the two previously divergent builds now converge on one digest, and skopeo, syft and grype all still read the result. Same-host determinism only — two independent builders remain a production requirement.
3. **Choose a licence.** `docs/LICENSING.md` sets out the options; the recommendation is a split, GPL-3.0-or-later for the OS layer and Apache-2.0 for the Phase 7 client packages. This blocks OEM and enterprise distribution independently of every technical gate and is the one item nobody else can decide.
4. **Get a second builder** so reproducibility can be evidenced properly, and a second release signer so signing is not a single point of failure.
5. **Acquire one physical machine.** Every hardware row, the Secure Boot and TPM rows, and the two boot-time accessibility workflows are blocked on there being no device.
6. **Commission independent security, cryptographic and accessibility reviews.** A self-review is a self-review, and the accessibility gap is the one that risks harm rather than merely missing evidence.

Items 1 and 2 are engineering. Item 3 is a decision. Items 4, 5 and 6 need money or hardware. That is the honest shape of what remains.

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

## After release blocker closure, 2026-07-30

Two blockers closed: **licensing** and **package minimisation**. Everything else
was measured, narrowed, or shown to need something this repository cannot
produce. `gate-stable-release` is still `NO-GO`; all three pilot gates are still
`BLOCKED`. See `RELEASE_BLOCKER_CLOSURE_REPORT.md`.

The critical path is now short, and the items are ordered by cost rather than by
importance - the cheapest one removes a blocker that looked permanent.

1. **Get a second builder from CI.** `scripts/reproducibility/collect-builder-record.sh`
   already reads `GITHUB_RUN_ID` into `cloudRunner`, which is a *strong*
   independence dimension. A CI-hosted build of the same commit and pinned base
   digest satisfies `independent-builder` reproducibility without buying
   anything. **This costs a workflow file.**
2. **Build a live ISO and a signed recovery ISO.** That unblocks the
   installation, encryption and recovery matrices in a VM - three evidence
   categories and the `recovery-media-failure` blocker code.
3. **Publish a signed update manifest and retain a previous release**, which
   unblocks update, rollback, migration and data preservation.
4. **Acquire one x86-64 UEFI machine with Secure Boot and TPM 2.0.** Blocks the
   `Hardware` and `Secure Boot` categories, the OEM pilot, and two accessibility
   workflows. Nothing substitutes for it.
5. **Commission the four independent reviews.** The security one is the only
   route by which any of the 8 Critical findings can become non-blocking, and
   `release/vulnerability.py` enforces that in code.
6. **Recruit a second release signer.** Four of the seven signing roles require
   two-person approval and cannot be provisioned at all with one person.
7. **Decide which Phase 7 capabilities to operate, if any.** Operating none
   remains a legitimate answer and is still the recommendation.

Items 1-3 are engineering and are within reach today. Items 4-6 need money,
hardware or people. Item 7 is the owner's.

Do not begin Phase 8. Do not manufacture hardware, deploy a fleet, or launch a
hosted service.
