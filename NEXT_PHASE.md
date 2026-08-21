# Next work after the Phase 1 implementation pass

Do not start a custom shell, compositor, visual redesign, installer experience, app store, or consumer release.

## Next work after the TPM boot-reset investigation — 2026-08-01

**Do not begin Phase 8. Do not begin a pilot. Do not create production keys.**

The "TPM GRUB reset" is closed as a qualification blocker: root cause
CONFIRMED (shim fallback's designed one-time boot-option-restoration reboot,
misread by a `-no-reboot` harness; `TPM_GRUB_RESET_ROOT_CAUSE.md`), harness
corrected under the `tpmq-1` authority, software-TPM regression matrix green
on both interfaces (`TPM_BOOT_REGRESSION_REPORT.md`). The artifact did not
change; Commit G/H/I/J remain the archive authority. Physical TPM remains
`NOT_RUN` — nothing software-TPM can move it.

The next blockers, in the order they were already queued:

1. **gdm/screencast intermittent boot failures** — now separately quantified
   per boot in the TPM matrix records (`failedUnits`), same classification
   discipline as `dispose_failed_units.py`.
2. **Encrypted unlock KDF cost** — unchanged; one success is not
   reproducibility.
3. **Global SELinux** — 12,369 unresolved paths.
4. **Harness login injection, desktop smoke, accessibility flows,
   update/rollback, recovery ISO** — unchanged.
5. **Physical hardware** — one x86-64 UEFI machine with Secure Boot and
   TPM 2.0; now also the only way to answer whether a discrete TPM's
   restoration reboot behaves like swtpm's.

One operational note for whoever boots the shipped image on real hardware
first: with a TPM present and empty NVRAM, the first boot shows a
five-second "Boot Option Restoration" countdown and reboots once. That is
designed shim 16.1 behaviour, not the defect returning. It is in
`KNOWN_LIMITATIONS.md` now; do not re-open the investigation for it.

## Next work after the SQLite determinism pass — 2026-07-30

**Do not begin Phase 8. Do not begin an OEM, enterprise or encrypted-sync pilot.**

One item blocks four workstreams and costs one command from the repository
owner:

```text
gh auth refresh -h github.com -s write:packages,read:packages
```

Without it the retained base, the builder image and the package snapshot exist
on one machine, no independent builder can fetch them, and the reproducibility
gate cannot move regardless of how the local comparison turns out. Every script
for the publication, the cold-pull verification and the three-builder comparison
is written and refuses to run, naming that command.

In order, once it is granted:

1. `make publish-retained-base publish-builder-image publish-package-snapshot`
2. `make verify-published-inputs` — from the machine that published, which
   proves the push worked
3. `make cold-pull-input-test` — from a runner holding none of them, which
   proves they are retrievable, and is the claim that matters
4. `make create-reproducibility-target` — refuses until 1–3 pass and the local
   comparison is `REPRODUCIBLE` in qualification mode
5. `make dispatch-hosted-h1` and `dispatch-hosted-h2`, separate runs
6. `make import-three-builder-evidence compare-three-builds reproducibility-gate`

Everything below this section predates that pass and is retained.

The qualification evidence closure completed every technically automatable evidence
task. What remains is ordered below by cost, and the cheapest item is genuinely
cheap.

### 1. The hosted builder has now been run — and it was not one button

This section previously said the hosted builder "needs nothing but a button". It
took seven dispatches. Five of the failures were real defects in the workflow or
the runner environment, and none was visible by reading the workflow:

| Attempt | Failed on |
| --- | --- |
| 1 | the pinned base digest no longer existed upstream |
| 2 | `crun` refused the OCI spec version Ubuntu's podman writes |
| 3 | the storage driver could not be changed under an initialised store |
| 4 | the SBOM step was killed — first diagnosed as disk, wrongly |
| 5 | a `[storage]` section replaces the defaults, so `runroot` must be set |

See `CI_PORTABILITY_REPAIR_REPORT.md` and `docs/CI_PORTABILITY_BASELINE.md`
(F9–F13) for each.

The first is the one worth carrying forward. `quay.io/fedora/fedora-bootc:44` is
rebuilt daily and old digests are garbage collected, and **the local builder kept
building against the dead digest because it had the layers cached**. A build that
appears to reproduce may only be reachable from one machine's cache.

### 1a. Mirror the base image — the cheapest remaining reproducibility work

Pinning a digest records which base was used. It does not make that base
obtainable, and this project's pinned base became unobtainable within days.

Mirror the base into a registry under this project's control, or a
content-addressed local mirror both builders pull from. Until then every
reproducibility comparison is against whatever base was current that week, and
cannot be repeated afterwards.

### 1b. Provision the package snapshot repository

`build/repositories/` contains `fedora-44-snapshot.repo.example` and a README,
and no reviewed `fedora-44-snapshot.repo`. `BUNNY_RELEASE_BUILD=1` therefore
cannot be used, and both halves of the independent comparison resolved their
package sets against live Fedora repositories.

The build already knows how to use a snapshot repository and already validates it
(HTTPS, `gpgcheck=1`, `repo_gpgcheck=1`, exactly one section). What is missing is
the file. Two builders cannot be expected to produce identical images while each
resolves its own package set from a moving repository.

### 1c. Pin the container toolchain across both builders

`verify-builder-independence` refuses the pair because their toolchains differ.
The pairing itself is accepted — a local machine paired with hosted CI, under
distinct administrator boundaries — and source commit and base digest match. What
differs is `podman` (5.8.4 on Fedora, 4.9.3 as Ubuntu 24.04 packages it), and
`podman` is the program that writes the OCI archive.

`syft` already matches at 1.50.0 on both sides because the workflow pins it. The
same treatment is needed for podman, either by installing a pinned podman on the
hosted runner or by running the hosted build inside a Fedora container.

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

## After the reproducible build remediation, 2026-07-30

**Do not begin Phase 8, physical-hardware qualification, independent review,
production signing, or any pilot.** Nothing below changes that.

The supply chain the previous section asked for now exists and has been run:
the base is mirrored and every blob re-hashed, the builder toolchain is pinned by
digest with all eighteen tools classified, and 474 packages are held in an
immutable snapshot whose every signature verifies against Fedora's own keys.

What has **not** happened is the measurement. In order:

1. **Grant `write:packages`.** One credential. Without it the retained inputs
   exist on one machine, which is the defect the mirror exists to remove, and the
   hosted half of the comparison cannot run at all.
2. **Complete two clean local hermetic builds** and compare them. This is the
   gate that must pass before dispatching anything hosted — a warm-cache build
   does not satisfy it and the tooling refuses one.
3. **Create Commit C**, a new qualification target. Commit A cannot be reused:
   the base reference, the builder, the package source, the clock and the
   finalisation stage have all changed.
4. **Dispatch two hosted builds** on separate fresh runners against Commit C,
   then compare H1↔H2, L↔H1 and L↔H2. Two hosted runs of one commit an hour
   apart previously disagreed because the runner image rotated; one hosted
   comparison cannot distinguish reproducibility from a favourable accident.
5. **Import as Commit D**, referencing Commit C, without moving the candidate.

The nine defects found by running this tooling are recorded in
`REPRODUCIBILITY_REMEDIATION_REPORT.md`. Three of them — two garbage version
strings that would have compared equal, a signature field reporting every Fedora
package as unsigned, and a clock override wider than the lock declaring it —
would each have produced evidence that looked correct.

Everything else in this document is unchanged. The vulnerability position, the
absent hardware, the absent reviews, the absent second signer and the absent
production key all still block, and none of them is touched by this work.

## Update 2026-08-02 — first-login corrections complete

The first-login and chronyd product corrections are done and measured. The
stop condition for that pass is reached: Commit O (archive target), Commit P
(three-builder evidence), Commit Q (installed-system target) and Commit R
(installed-system and regression evidence) all exist, and every protected gate
has been recalculated.

**The next workstream is encrypted unlock KDF calibration and reproducibility.**
It has not been started. `KNOWN_LIMITATIONS.md` records the measured position:
LUKS2 defaults to argon2id with a cost `cryptsetup` benchmarks on the machine
that formats the volume, and the qualification VM is far slower than the
builder — one run completed at about twenty minutes into the boot, two later
runs were unfinished at forty-five. If that reading is right it is not only a
test artifact: a disk encrypted on a fast machine and unlocked on a slow one is
a real user situation, and a machine that appears dead for twenty minutes is
indistinguishable from a failure to the person using it.

Carried forward from this pass, and not addressed by it:

* The NSS window is wider than chronyd. Any unit whose `User=` resolves through
  the `altfiles` source during the authselect rewrite is subject to the same
  race. This pass corrected and measured the one unit observed failing; a sweep
  of units resolving `altfiles`-provided accounts is not done.
* The archive digest is a function of the commit built, because
  `install-root.py` writes `sourceCommit` into `/usr/lib/bunny-os/release.json`.
  Any future reproducibility pass must create the target commit *before* any
  build that will be compared against a hosted one.

## Refreshed 2026-08-03 — after visual prototype removal

Repository HEAD `9c469a6ff8e10c73476e5fd8d19330c88ae4e7c1`. Candidate commit
`79bb99ddb39d8a5dbc279629f43b23346fb0e5e8`. Candidate gate: **BLOCKED, 3 of 14**.
Stable release: **NO-GO**. Pilots: **BLOCKED**.

### Completed in this pass

Visual prototypes V1, V2 and V3 were reverted out of `main` and branch isolation
was restored (PR #17, merge `9c469a6`). `main` now carries no experimental visual
session and no prototype implementation; the three `visual/*` branches are
preserved and all three heads resolve. Main's CI went from failing to green:
`Release blocker closure` and `Qualification evidence closure` both failed at
`da87b23` and both pass at `9c469a6`.

The qualification reports were refreshed from the gate's own output rather than
by hand. The stale `2 of 14` headline is corrected to the gate-computed
`3 of 14`, and `independent-reproducibility` is recorded at its current `PASS`.

### The eleven that block, and who owns them

Nothing below can be closed by writing code alone.

| Owner | Prerequisites | What is actually required |
|---|---|---|
| engineering | `independent-recovery-media`, `installation-matrix`, `encryption-matrix` | build a signed recovery ISO and run real destructive installs against disposable disks |
| operated-release | `update-matrix`, `rollback-matrix` | publish a release first, then measure against it |
| independent-reviewer | `vulnerability-gate`, `accessibility-evidence`, `independent-reviews` | commission genuinely external reviews; reviews created internally cannot be labelled independent |
| physical-hardware | `physical-hardware-evidence` | acquire one x86-64 UEFI machine with Secure Boot and TPM 2.0; VM evidence may never be relabelled as hardware evidence |
| second-authorised-signer | `second-production-signer` | identify a second human signer and hold an approved key ceremony |
| owner-decision | `protected-approvals` | nine approvals: Engineering, Release, Security, Privacy, Accessibility, Installer, Hardware, Documentation, Maintenance |

### Immediate engineering work that is not blocked

1. **Re-measure the stale evidence.** The twenty records attest a file that has
   since changed. Re-run the matrices and record fresh evidence bound to a
   current authority. Do not re-digest.
2. **Extend `-text` protection to `operations/data/**`** in `.gitattributes`, so
   attested bytes round-trip git on a Windows checkout.
3. **Run the source gate on Linux.** One protected mutation test needs symlink
   privilege that a Windows host does not hold; it is `NOT_RUN` there, not `PASS`.
4. **Encrypted unlock KDF qualification** (`feature/encrypted-unlock-kdf-qualification`)
   and **global SELinux closure** (`feature/selinux-installed-classification`)
   are both product-authority work and neither depends on the visual track.

### The visual track

V4 framework closure (Smithay versus libmutter) is specified to require real
Orca, real CJK input, real PipeWire screen sharing, real PAM lock/unlock,
measured GPU rendering and two outputs actually presenting frames.

None of that can be measured on a Windows host, and a prototype that has not been
measured is not a framework verdict. V4 must be executed on Linux hardware with a
working Wayland stack. Until it is, the correct recorded state for every V4
mandatory gate is `NOT_RUN` or `NOT_AVAILABLE` — never `PASS`.

GNOME remains the supported architecture throughout.

## After the Companion / App Capsule / Trust phase — 2026-08-10

Branch `feature/bunny-companion-capsules-trust`, commits `fc1e58a` and `adce2c5`,
branch point `262b06d`. Full report: `COMPANION_CAPSULES_TRUST_REPORT.md`.

**Nothing below changes the release position.** `gate-stable-release` is still
`NO-GO`, all three pilot gates are still `BLOCKED`, the vulnerability position is
untouched, and there is still no hardware, no second signer, no independent
review and no production key. This pass added a consumer experience to a system
that cannot ship; that is worth doing and is not progress towards shipping.

### What exists now that did not

Three packages and their surfaces: `trust/` (seventeen permission categories,
deny-by-default in its strong form, fail-closed everywhere, an audit that holds
digests rather than paths), `capsules/` (one persistent sandbox per installed
application over Flatpak, Bubblewrap and a systemd scope, with an isolation plan
that starts empty and four refusals that raise), and `catalog/` (curated metadata
with nothing that fetches, establishing the permission ceiling and carrying a
curator's paragraph on how each option genuinely differs). Plus the §33 task
slice, the Settings and workspace projections, the text consent surface, the
installer conversation with its authority rule, and three importless shell
modules. 248 tests; suite total 4,856.

### The stop condition for this pass is reached, and the next item is cheap

**1. Run `make test-capsule-phase` on Linux, as `bunny`, from an ext4 checkout.**
Three symlink tests are `NOT_RUN` on a Windows host, and they are among the most
important in `APP_CAPSULE_SECURITY_REVIEW.md` §2.3 — until they run, those rows
are design claims rather than measurements. One command on the Fedora builder.

**2. Start one capsule for real.** `SubprocessExecutor`, one catalogue entry, one
file grant, and the checks in `CAPSULE_VM_VALIDATION_PROCEDURE.md` §3 run from
*inside* the sandbox. This single step is what every remaining claim waits on: it
moves the phase from *tested* to *runtime validated*, and it turns "no bind mount
naming the home directory appears in the plan" into "the home directory is not
there". Run the negative control in the same session; four of the five gate
failures this repository has recorded fired because a property got better, and a
check that passes because the command was wrong looks identical to one that
passes because the sandbox works.

**3. Boot an image, enable Orca, trigger one permission prompt.** The Trust
prompt is the only modal Bunny raises unasked. If it does not raise correctly in
the AT-SPI tree, a screen-reader user meets a silent modal — an application that
appears to hang — which is a worse failure than any this phase fixes.
`TRUST_ACCESSIBILITY_REPORT.md` §4.

Then: wire the shell modules and the Settings page on Linux one at a time; measure
a real cold launch (`CAPSULE_PERFORMANCE_REPORT.md` §5 lists the seven numbers
that are missing); implement clipboard and Bluetooth enforcement or hide them.

None of 1–3 needs money, hardware or a third party.

### What not to do next

- **Do not wire the shell extension from a host that cannot run it.** The three
  modules are complete and nothing imports them, deliberately. Editing
  `extension.js` has cost a boot per mistake, four times.
- **Do not add a permission category.** Seventeen is §11's list. A category that
  nothing enforces is the liability `clipboard` and `bluetooth` already are.
- **Do not add a catalogue entry without a second reader.** An entry is a security
  artefact — it is the permission ceiling — and currently has one author.
- **Do not update the report's "runtime validated" row from anything but a
  completed section of the VM procedure.** The report says nothing has been; that
  sentence is correct until a run says otherwise.

## Update 2026-08-10 — capsule isolation is runtime-observed; the graphical slice is not

`CAPSULE_RUNTIME_QUALIFICATION_REPORT.md` is the record. Evidence at
`qualification/capsules/evidence/37f74c038d41/` (host) and `.../57068ea4b2b5/`
(VM boot).

**What moved.** App Capsule isolation is now HOST RUNTIME VALIDATED rather than
unit tested: real bubblewrap sandboxes, started by the production runtime and
the production executor, measured by a probe that runs inside them and again
outside as a negative control. 17 checks isolated, each one reached by the
control. Cross-application isolation, the file-grant lifecycle, six fail-closed
paths, the crash boundaries and the network classes are all measured rather than
asserted. The image builds, contains the three new packages, and boots to
`graphical.target` with no failed unit.

**What did not move.** Nothing graphical. No login, no session, no Companion on
screen, no Trust prompt drawn, no §15 journey, no accessibility run. The VM
harness boots and greps a serial log; it has no login injection. Those rows are
`NOT_RUN` in the report and must not be read as anything else.

**Eight defects, two of them blockers**, none visible from a Windows host: every
capsule launch failed for want of two environment variables; a capsule whose
process exited stayed `running` forever; a resource display leaked absolute paths
into the audit; a network grant could not resolve a name; the allowlisted network
class is not a boundary; a route the build context could not see reported as
installed; the sandbox root was writable; `MemoryMax` is ignored by this kernel.
All eight are fixed or disclosed at every surface. Three *harness* defects were
also found, each of which would have produced a false PASS.

### Next, in order, and the first three need only time on the existing builder

1. **Install Flatpak on the qualification host and re-run.** One of two backends
   is `NOT_RUN`, and it is the one most applications will use.
2. **Run the qualification inside the booted VM.** SELinux is *enforcing* there
   and Disabled on the WSL host, so this is the first measurement of that layer
   and it converts the isolation result from HOST to VM RUNTIME VALIDATED.
3. **Measure `MemoryMax` on a stock Fedora kernel.** This host accepts the limit
   and ignores it; a plain systemd scope with no capsule behaves identically, so
   the question cannot be answered here.
4. **Get a login into the VM and drive the §15 journey**, using the existing
   desktop route: `desktop-drive.py`, virtio-tablet pointer injection, AT-SPI.
5. **Install Orca and drive the accessibility pass.** The Trust prompt is the
   only modal Bunny raises unasked; a screen-reader user meeting a silent modal
   is worse than anything this phase fixed.
6. **Decide about the allowlisted network class.** Implement per-name filtering
   or remove the class and offer off / local / on. It is a word that currently
   promises more than it does — disclosed, and still present.

### Unchanged

`gate-stable-release` is still `NO-GO`. All three pilot gates are still
`BLOCKED`. The vulnerability position, the absent hardware, the absent
independent reviews, the absent second signer and the absent production key are
all untouched by this pass.

---

## Update 2026-08-10 (later) — the guest answered; the Companion could never have launched anything

Evidence at `qualification/capsules/evidence/guest-d9a36620044d/` (booted guest)
and the host directory for the same run. `CAPSULE_RUNTIME_QUALIFICATION_REPORT.md`
§§9–10 are the record.

**Items 2 and 3 above are done.** The full suite ran inside the booted image as
`bunny` in a real login session, with SELinux **Enforcing** and the targeted
policy at version 35. All eight sections then present returned PASS. `MemoryMax`
is a real boundary on the shipped kernel: the capsule was throttled by
`MemoryHigh` at 209,715,200 bytes against a 268,435,456 ceiling — 2,934 high
events, zero max, zero OOM kills — and the control, same ceiling without
`MemoryHigh`, was killed by the cgroup at 243,269,632. On the WSL host the same
control took 2 GB and nothing stopped it. L-8 is a property of the development
host, not of Bunny OS.

**AVC collection is blind in this image and reports itself so.** `journalctl`
carries no kernel lines, `ausearch` is absent, `kernel.dmesg_restrict` is 1, and
the buffer is empty even to root. The section refuses to report a denial count
rather than reporting zero. Adding `audit` to the *qualification* profile is the
fix and has not been done, because a test profile must not ship.

**Two new blockers, and they are the reason this entry exists.** Every section of
that suite launches a capsule from a login shell. Nothing in the product does —
the Companion does, and the Companion is a systemd user unit with a sandbox of
its own. Asking that question found:

* **L-9.** A capsule was a `systemd-run --user --scope`. A scope is forked by its
  requester and inherits that process's seccomp filter; both Companion units set
  `RestrictNamespaces=yes`; bubblewrap's whole mechanism is `unshare(2)`. **Every
  capsule launch from the Companion failed, always, on every machine.** Fixed by
  asking the manager for a transient *service*, which the manager spawns.
* **L-10.** `ProtectHome=read-only` covers the capsule root and the trust store,
  so the runtime could start a capsule and failed on the first install write.
  Fixed with `ReadWritePaths=` on the runtime unit only — the window is a client,
  and a renderer that can write the trust store can mint its own grants — plus a
  user-tmpfiles rule creating the roots, because a `ReadWritePaths=` path that
  does not exist fails namespace setup with 226/NAMESPACE before `ExecStart`.

Both are guarded by a new `launcher` qualification section that runs four shapes,
the fourth of which rebuilds the pre-fix vector and **must still fail**: every
shape passing is the intended result and is also what a section that had stopped
measuring anything would report.

### Next, in order

1. **Rebuild the image and re-run the guest qualification.** The guest runs the
   packages the image installed and only the harness is injected, so `launcher` —
   and with it both new blockers — is currently HOST RUNTIME VALIDATED only.
2. **Give the Companion a path to a capsule task at all.** `capsule_bridge.py`
   has no caller outside the tests. Until it does, L-9 and L-10 are fixes to a
   route nothing takes, and the §15 journey cannot be driven from the UI.
3. **Then the graphical work**: login, `BUNNY_SESSION_READY`, the Companion
   drawn, the Trust prompt raised on screen, the journey and its failure variant.
   The existing desktop route — `desktop-drive.py`, virtio-tablet pointer
   injection, AT-SPI — is the harness; it does not need to be rebuilt.
4. Flatpak on the qualification host; Orca for the accessibility pass; the
   allowlisted network class decision. All unchanged from the entry above.

### The Phase C stop condition is not met

The phase completes only if a successful graphical vertical slice **and** one
graphical failure slice both run inside the Bunny OS VM. Neither has run. **Phase
status: INCOMPLETE**, and the source tests passing does not change that.

### Found and not touched

`tests/companion/test_neural_tts.py::test_provenance_accounts_for_every_selected_tts_byte`
fails: the bundled voice assets measure 436,604,323 bytes against 436,603,718
recorded in `assets/voice/PROVENANCE.json`, a 605-byte excess. It predates this
phase — `assets/voice` was last touched at `a7ba40f`, before this branch's base —
and it is left alone deliberately. Editing the recorded number to match the files
would be adjusting the record to the artefact without establishing which of the
two is wrong.

---

## Update 2026-08-11 — the guest runs the real route; nothing graphical has run

`GUEST_REBUILD_AND_STORAGE_REPORT.md` and `GUEST_REQUALIFICATION_REPORT.md` are
the record. Evidence at `qualification/capsules/evidence/guest-4c6e101bd354/`
(the run that found a defect) and `.../guest-524107e50b2e/` (the re-run).

**Two images were built.** `0482f4c90f00`, then `39a5c575da9e` after the defect
below. Both from a checkout with all five integration fixes; the second also
ships `/usr/libexec/bunny-session-ready`.

**Eleven of eleven sections pass in the rebuilt guest**, SELinux Enforcing,
targeted policy v35, as `bunny` in a real login session, against the packages
the image installed. `launcher` and `apptask` had never run in a guest before.
The image task produced 100×50 from 400×200 in 214 ms, exit 0, one authorised
file, the neighbour never authorised, network class `none` enforced, original
byte-identical.

**The allow-once regression found a real defect.** `stop()` drops session grants
and returns early for a capsule that `reconcile()` has already stopped — so for
an application that exits by itself, which is every task application, the drop
never ran and "allow once" left a permission behind for the rest of the login.
The drop moved to `reconcile()`. The unit suite passed before and after, so a
test that fails without the fix now exists.

**The storage incident was operations tooling, not the build.** Three
qualification copies of a repository containing tens of gigabytes of generated
images filled the WSL virtual disk. `scripts/check-copy-size.py` now refuses an
order-of-magnitude miss, and `.containerignore`'s coverage is asserted. Note for
whoever hits this next: `fstrim` freed 702 GiB inside the guest and returned
nothing to Windows — the VHDX is not sparse, so it grows and never shrinks.
Compaction needs an elevated environment and is deliberately not automated.

### What has not run, and is the whole of what remains

Nothing graphical. No login, no `BUNNY_SESSION_READY` observed in a booted
session, no Companion drawn, no Trust prompt on screen, no allow-once pressed by
a person, no denial slice, no unsafe-launch slice, no keyboard path, no AT-SPI
run, no screen reader, no reduced-motion or text-only run, and no screenshots.

**Phase status: INCOMPLETE.** The security route is now VM RUNTIME VALIDATED
end to end; the *experience* is not validated at all.

### Next, in order

1. **Drive the graphical harness** — `build/scripts/vm-desktop-story.sh` with
   `desktop-drive.py`, virtio-tablet pointer injection and AT-SPI already exist
   and do not need rebuilding. The readiness probe now ships, so the harness can
   wait on `BUNNY_SESSION_READY` instead of a delay.
2. **The success slice**, then **the denial slice**, then the unsafe-launch
   slice. §34's list is otherwise met.
3. Accessibility: keyboard, AT-SPI names, Orca in a qualification-only profile,
   reduced motion, text-only.
4. A qualification-only profile carrying audit tooling, so AVC evidence stops
   being blind.

---

## Update 2026-08-11 (later) — both journeys run in the booted guest

Evidence at `qualification/capsules/evidence/journey-b38d51000543-{granted,denied}/`.
Image `b38d51000543`, SELinux enforcing, as the logged-in user, against the
Companion service the session started.

**The success slice.** From a spoken request — "Resize this to 100 pixels wide."
— `created → waiting_for_approval → executing → completed`. The permission named
the real file and said the original would not change. Answered in 0.352 s; the
whole journey took 1.1 s. `holiday-resized.png` at **100×50** from a 400×200
original. Original byte-identical. The neighbour in the same directory was never
authorised. No grant survived the task.

**The denial slice.** Same program, one argument apart:
`created → waiting_for_approval → blocked`. No grant, no execution, no output,
original unchanged.

**`BUNNY_SESSION_READY` was observed in both** — all eight conditions true, the
marker on its own line, from the installed probe rather than a harness copy.

### One product defect, found by the fifth image

The Companion could do everything except put the result down:
`OSError: [Errno 30] Read-only file system` on the export.
`bunny-companion.service` has `ProtectHome=read-only`, the state roots had
`ReadWritePaths=` and the *destination* did not. Fixed with one `-`-prefixed
directory; the capsule is unaffected, because an application writes to its own
exports directory and the runtime copies the verified artefact out. Not dynamic:
`ReadWritePaths=` resolves at unit load, so a person whose `XDG_PICTURES_DIR`
points elsewhere still cannot receive a result. A portal is the answer to that.

Five images were needed and each one was missing exactly one link that only a
booted run could show: the launcher shape, the grant lifetime, the input
binding, the readiness probe's socket, and finally the export permission.

### What did not happen, stated plainly

**The Trust prompt was never drawn.** The probe answers over the Companion
protocol — the same path the window uses, so the *route* is genuine — but no GTK
dialog rendered and nothing photographed one. The screenshots also start at
t=120 s while the journey finishes by t=60 s, so both frames show an idle
desktop. They are evidence that the desktop and the Companion character render,
and of nothing else.

So against the brief's list: route, states, permission decision, capsule launch,
scoped file access, output export, audit and both terminal states are VM RUNTIME
VALIDATED. "Trust prompt appears" and "user chooses Allow once" are **NOT** —
they were exercised programmatically.

Also still open:

* **a failed operation produced a `completed` task.** The runtime recorded
  `operation_failed` and an error reference and the state stayed `completed`;
  only the summary text carried the truth. `TaskResult` has no failure channel.
  This is the brief's "failure does not produce completed", it is in shared
  runtime logic, and it is unfixed.
* `"this"` resolves to the most recently modified image, which can offer the
  wrong file. The prompt names it, so the person is the safeguard — by design,
  but thin. Observed for real: one run offered to resize the neighbour.
* no keyboard path, no AT-SPI run, no screen reader, no reduced-motion or
  text-only run, no accessibility evidence of any kind.

**Phase status: INCOMPLETE.** Both journeys run and the security route is
validated end to end in the booted guest; the *visual* half of the vertical
slice is not.

---

## Update 2026-08-11 (later still) — failure semantics fixed and proved

`qualification/capsules/evidence/journey-0ef5862-failing/`.

**A failed operation can no longer become a completed task.** The cause was
structural: `TaskResult` had no failure channel, so an executor could not report
one, and the runtime — which had watched every operation settle — asked nobody.
Both knew and neither could say.

There are now two verdicts and the pessimistic one wins. `TaskResult` carries an
outcome and a structured reason; `CompanionRuntime._observed_outcome` forms its
own from the operation records rather than from any claim about them;
`worst_outcome` combines them. The executor's default of `success` is safe only
because it is not trusted, and a test asserts precisely that: a
default-constructed result over a plan whose operations all failed still
produces a failed task.

The invariants are pure functions, so they are checked on every machine rather
than only where a VM boots — success completes, failure fails, a denial *blocks*
rather than failing (a person saying no is not a malfunction), cancellation is
its own state, and an unknown verdict fails.

**Proved in the booted guest.** A third journey slice, `failing`, is `granted`
with an input the program cannot read — the approval, the capsule and the launch
are unchanged, only the input differs:

```
states   created → waiting_for_approval → executing → failed
error    operation_failed: "The app stopped before it finished."
result   no output file; original byte-identical; no surviving grant
```

Before the fix that exact path produced `completed`.

### Three graphical slices now run

| Slice | States | Result |
|---|---|---|
| granted | → executing → completed | `holiday-resized.png` 100×50 |
| denied | → blocked | none |
| failing | → executing → failed | none |

### What remains, and it is the headline of the phase

**The Trust prompt has still never been drawn.** Approval is answered over the
Companion protocol — the real route, but not the visible one. By the brief's own
rule that is decisive on its own: *if approval is still answered
programmatically, the phase is INCOMPLETE*.

Not started, and each is real work rather than a loose end:

* raising the real GTK Trust surface when a task reaches `waiting_for_approval`,
  and driving it through AT-SPI rather than the protocol;
* state-triggered screenshot capture, so frames are bound to transitions instead
  of to a timer that currently fires an hour of guest-seconds too late;
* the Companion's visible state projection for each terminal path;
* protected-space and Trust-history surfaces on screen;
* every accessibility item — keyboard, AT-SPI names, reduced motion, text-only,
  screen reader;
* the `"this"` resolver's ambiguity rule (ask when more than one plausible file);
* portal-based export, replacing the interim `ReadWritePaths=-%h/Pictures`.

**Phase status: INCOMPLETE.**

### Why the Trust prompt never appeared — diagnosed, not guessed

Worth writing down because it changes the size of the remaining work by an order
of magnitude.

**The Trust surface already exists, in the shell extension.**
`shell/components/gnome-shell-extension/lib/assistant/panel.js` builds an
approval box with `Allow` and `Deny` buttons, both carrying `accessible_name`
(`"Allow this Bunny action"`, `"Deny this Bunny action"`), wired through
`services/assistant.js` to the Companion's `resolve_approval`. Nothing needs to
be built.

**It never showed because of one line.** `lib/desktopShell.js` gates its
`onApproval` handler behind `this._owns(meta)` — the panel shows approvals only
for tasks *it* asked for through `assistant.ask()`. The journey probe submits
through its own `CompanionClient`, so `_owns` is false and the approval is
delivered to nobody.

**And the GTK window is a dead end on purpose.**
`config/systemd/60-bunny-os-user.preset` disables
`bunny-companion-window.service` deliberately: the desktop has an assistant
surface of its own now, and starting the window at login put a second, larger
copy of the same assistant on top of the character. Enabling it to get a dialog
would be undoing a considered decision, not fixing anything.

So the remaining work for a visible Trust prompt is **harness wiring**:
`build/scripts/desktop_interaction.py` already drives the shell's assistant over
AT-SPI and reads its states — the desktop story types "What files are in my
Downloads folder?" and reads the answer back. Extend it to submit the resize
request into the assistant input, wait for the approval box, and press
`Allow`/`Deny` by accessible name. Screenshots then bind naturally to states,
because the driver knows when each one is reached.

That also delivers most of the accessibility items for free: the buttons already
have accessible names, so the AT-SPI run *is* the interaction path rather than a
separate inspection.

### The Trust prompt renders. The shell gives up before it can.

Photographed, twice, and now isolated to one cause.

**It renders.** In a run where the journey was the session's *third* request, the
shell drew it unprompted from the real task:

> Bunny Image Tool wants to open Pictures/holiday.png. It will save a copy as
> holiday-resized.p…  `[Deny]` `[Allow]` — under *"Waiting for permission…"*

So §3 and §4 are satisfied by the product as it stands. The buttons carry
accessible names (`Allow this Bunny action`, `Deny this Bunny action`) and are
wired to `resolve_approval`.

**And it does not, when the session is cold.** With `BUNNY_SESSION_READY`
genuinely satisfied — all eight conditions, marker seen — the same request as
the session's first produces:

> the runtime did not finish within the deadline

The character goes `thinking → warning → idle`. The task is submitted and the
runtime does reach `waiting_for_approval`; the shell assistant's `ask` deadline
simply expires before it gets there, so the question is never put on screen.
Under llvmpipe the first task of a session is slow enough to cross that line and
later ones are not, which is exactly why this looked like an ordering problem
for three cycles.

**This is a product defect, not a harness one.** A permission request that takes
longer than a client's timeout must not become "the runtime did not finish" — the
person is left with a warning where a question should be, and the task sits
waiting for an answer nobody was asked for. The fix belongs in the shell's
assistant service: an approval is not a slow answer, it is a different kind of
answer, and the deadline that bounds one should not bound the other.

Everything downstream is ready for it: `desktop-drive.py --journey
{granted,denied,failing}` waits on the readiness probe, writes the fixture as the
user, types the request, waits on the character state, walks the tree once, and
presses the button by accessible name. It never calls `resolve_approval`.

### Harness faults fixed along the way, recorded because the pattern matters

Nine, and the product was correct every time: `_run` unpacked as a tuple (killing
the probe, so every later answer read `null`); one bad command taking the whole
probe with it; the shortcut not firing with no pointer fallback; a `listening`
check stricter than the path that works; polling the whole accessibility tree
every two seconds until the instrument stalled and reported an empty desktop;
raising the walk depth to 20 on a wrong theory, which broke a working instrument;
keeping only the parsed controls so "0 seen" could not be told from "never ran";
`WAYLAND_DISPLAY` missing from the probe's environment, so the readiness probe
reported no compositor on a desktop that was drawing; and the journey inheriting
a spent assistant.

Three of those were fixed only after a screenshot settled what text-only evidence
could not.
