# Phase 1 release limitations

This root report mirrors the maintained detail in `docs/KNOWN_LIMITATIONS.md`.

## Added by the first-login correction pass — 2026-08-02

### The archive digest is a function of the commit built

`build/scripts/install-root.py` writes `sourceCommit` into
`/usr/lib/bunny-os/release.json`, so two builds of two different commits cannot
be byte-identical however tightly the inputs are pinned. Measured here: a local
pair built before the target commit existed agreed with each other
(`36736f36…`) and disagreed with both hosted builds, which agreed with each
other (`38ab0343…`); rebuilding the local pair at the target commit made all
three identical.

This constrains how any reproducibility pass must be sequenced: **the target
commit has to exist before any build that will be compared against a hosted
one.** It also means a reproducibility target cannot bind the digest of an
archive built from itself — the same self-reference the epoch lock already
avoids by naming a parent commit.

Not a defect in the image, and not a limitation of the corrections. It is a
property of the build that was not previously written down, and it cost a
rebuild and a set of installation artifacts to rediscover.

### The NSS window is wider than chronyd

`chronyd` was the unit measured failing, and it is the unit this pass corrects.
The mechanism, however, is not chronyd-specific: `/etc/nsswitch.conf` is a
symlink to `/etc/authselect/nsswitch.conf`, `authselect apply-changes` rewrites
that file on first boot, and for the width of that rewrite **no account
provided by `/usr/lib/passwd` through the `altfiles` source resolves**. Any
unit with a `User=` satisfied that way, spawning inside the window, is subject
to the same race.

A systematic sweep of units resolving `altfiles`-provided accounts is **not
part of this pass**. Until it is done, the correction should be read as closing
the one measured occurrence, not the class.

### Disk-image byte reproducibility is still not claimed

Root-filesystem reproducibility is established evidence. The generated qcow2
and raw images are not byte-reproducible and the artifact record names why:
partition GUIDs, filesystem UUIDs and the ESP volume id are unique per
generation.

## Current limitations — 2026-07-30

The list below is the accumulated per-phase detail. These are the limitations that
matter today.

### Not releasable

`gate-stable-release` reports **NO-GO** and `gate-qualification-candidate` reports
**BLOCKED** with 2 of 14 prerequisites satisfied. All three pilot gates report
`BLOCKED`. Nothing in this repository may be described as release-qualified.

### The vulnerability position is unchanged and blocks

**59 fixable findings: 8 Critical, 28 High, 23 Medium.** Deduplicated to 24 unique
Critical/High pairs, all dispositioned `Unknown`.

Every one comes from the digest-pinned `fedora-bootc:44` base. The beta profile adds
none of its own. Three things were tried and none helped: the base was rebuilt by
Fedora on 2026-07-29 — a genuinely new digest — without the counts moving;
`dnf check-update podman skopeo` returns nothing; and the packages cannot be removed
because `bootc` requires podman and skopeo and `rpm-ostree` requires skopeo.

Nine of the ten bounded reachability questions are answered with measured evidence.
The tenth — *is the vulnerable code path compiled into the installed binary and
active or invocable?* — is not, and needs per-CVE symbol analysis plus the advisory's
own description of the vulnerable function. **An independent security review is the
only route by which any Critical becomes non-blocking.**

### Same-host builds are not independent builds

Two isolated workspaces on one host produce byte-identical archives. That is
same-host repeatability and **not** independent-builder reproducibility: a defect in
the shared kernel, storage or clock reproduces in both builds and the comparison
cannot detect it.

*Closed 2026-08-01 for the archive stage:* three builders under two
administrator boundaries produced identical archives at target 619065e, and
`verify-builder-independence` passes on both local+hosted pairs. The
statement above remains true about same-host pairs and is kept because the
distinction is the reason the hosted runs exist.

### The BrlAPI key was never minted on an installed system

Measured 2026-08-01 from the journal of an installed first boot: the archive
qualified at 619065e reaches `graphical.target` in 9.6 seconds and starts
GDM, and `bunny-brlapi-key.service` does not run at all. The unit ships with
`WantedBy=sysinit.target`, nothing enabled it, and systemd disables what no
preset names — so `/etc/brlapi.key` is absent on the installed system and
BRLTTY has no authorisation key for the whole session.

This is the second half of one accessibility defect. The first half — the
unit's `ExecStart` naming a program the build never installed — was visible
to CI and is fixed. The second half was visible only by booting an installed
system and reading its journal, which is what this workstream exists to do.

Both halves are now fixed in source: the program is installed, and the
service is enabled both by preset and by the explicit `systemctl enable`
list. **The fix post-dates the qualified archive**, so every installed-system
record in this pass correctly reports `brlapi-key-service-ran` as `FAIL`, and
the per-installation state comparison correctly reports the key absent. The
next re-qualification carries the fix; nothing here claims it does.

### LUKS2 unlock is prohibitively slow in the qualification VM

Measured across three runs of one encrypted installation. The refusal path is
sound: a wrong passphrase is consumed and rejected, the console reprompts,
nothing mounts and nothing leaks — that scenario passes. The correct
passphrase is also consumed and *not* rejected, which is how a correct
passphrase looks; what follows is the problem. One run completed, reaching
`multi-user.target` and finishing the Bunny health check about twenty
minutes into the boot. Two later runs produced no further console output at
all and were still unfinished at a forty-five-minute deadline.

The likely cause is recorded rather than assumed: LUKS2 defaults to argon2id
with a memory and time cost that `cryptsetup` benchmarks on the machine
formatting the volume. That machine is a fast, many-cored builder; the
qualification VM is neither, and the derivation appears to run for tens of
minutes there.

If that reading is right, it is not only a test-environment artifact. A disk
encrypted on a fast machine and unlocked on a slower one is a real user
situation, and "the passphrase works but the machine appears dead for twenty
minutes" is indistinguishable from a failure to anyone using it. Confirming
or refuting that on real hardware is precisely what physical qualification is
for.

Recorded outcome: encrypted unlock is **not qualified**. One success is not
reproducibility, and a suspected harness interaction is not a pass.

### First boot with a TPM and empty NVRAM performs one automatic reboot

Superseded finding: the 2026-08-01 record that "the image does not boot with
a TPM 2.0 attached" (`ISQ-20260801-tpm-present-*`) was a harness
misinterpretation, and its serial evidence never showed GRUB. The
investigation (`TPM_GRUB_RESET_ROOT_CAUSE.md`, confidence CONFIRMED)
established what actually happens: when the disk is booted through the
removable path with no OS boot entry in NVRAM — which is every first boot of
the QCOW2/raw image in a fresh VM — shim's `fbx64.efi` restores the boot
entries from `BOOTX64.CSV` and then, **because a TPM is present**,
deliberately cold-resets once so the restored entry boots with cleanly
measured PCRs. The second boot proceeds normally. Without a TPM, fallback
chainloads directly and no reset occurs. The prior harness ran QEMU with
`-no-reboot`, which turned the designed single reboot into a dead guest.

Measured under the `tpmq-1` matrix (`TPM_BOOT_REGRESSION_REPORT.md`): with
the reboot permitted, TPM-attached cold boots complete 5/5 on both
`tpm-crb` and `tpm-tis` with exactly one restoration reset each; with an
already-restored variable store, 5/5 with zero resets; the no-TPM control
5/5 with zero resets.

What remains a real limitation:

* A user's first boot of the shipped disk image on a TPM-equipped machine
  with empty NVRAM shows a five-second "Boot Option Restoration" countdown
  and reboots once before the OS appears. The mechanism is upstream shim
  16.1's — the reset is in the distribution's `fallback.c`, on the branch
  taken when firmware exposes a TPM — and a stock Fedora Cloud 44 disk under
  the same harness does exactly the same thing, 3/3 with a TPM and 3/3
  without a reset when there is none. Not a Bunny defect, but user-visible
  and undocumented until now.
* All of this is software-TPM (swtpm/QEMU/OVMF) evidence. Whether a
  discrete hardware TPM behaves the same is exactly what physical
  qualification exists to answer and remains `NOT_RUN`.
* No TPM feature is claimed by the product today — there is no TPM
  enrolment, no measured-boot policy and no sealed key. The encryption
  matrix's `tpm-fallback` row still cannot rest on any of this.

### No physical machine has ever run Bunny OS

Zero hardware reports, zero collections. The `Hardware` and `Secure Boot` evidence
categories block, and the OEM pilot cannot begin without a device even if every
other blocker closed tomorrow.

### Zero runtime accessibility evidence

0 of 17 flows driven. Seven of them are `critical` — each is required to own or
recover the machine. Static accessibility tests pass and are **explicitly not
sufficient**; the tooling refuses a source-inspection pass and refuses a `PASS` with
no recorded steps.

Two flows — installer screen reader and keyboard-only installation — additionally
need an installer ISO that has not been built.

### No independent review of any kind exists

Four bounded requests are ready to send. Zero commissioned, zero delivered. The
repository contains a great deal of internal security and privacy review and
`release/reviews.py` refuses to record any of it as independent, which is correct.

### No production signing key exists

Not one, of any of the seven roles. Four roles require two-person approval and
**cannot be provisioned at all** with one signer. No key ceremony has been held.

The nine-check and two-person development drills both pass 9/9 and neither
establishes anything about production signing.

### Nothing is operated

No update manifest is published, no previous release exists, no sync service runs,
no fleet is enrolled, no device is manufactured. The update, rollback, migration and
soak evidence categories depend on operated release evidence that does not exist.

### An archive-only build is not a candidate build

`BUNNY_ARCHIVE_ONLY=1` was added to `build/scripts/build-image.sh` so a hosted
Ubuntu runner can be a real second builder. It skips `image-builder` and produces
**no qcow2 and no raw image**. It must never be recorded as a candidate build, and
the change has not yet been exercised on a Fedora host.

### Evidence is bound to a candidate commit, not to HEAD

The candidate commit is `79bb99ddb39d…`; HEAD is `80df25b09f65…`. Qualifying an
older commit is legitimate for a release candidate, and it means **the tree has moved
since the evidence was measured**. A rebuild is required before publication.

### `make` is unavailable on the development host

Every `make` target has an equivalent `python scripts/release.py` entry point.
`systemd-analyze` and `shellcheck` are also unavailable and their checks skip.

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

## CI portability and hosted-build limitations, 2026-07-30

### A pinned base-image digest is not durable

`quay.io/fedora/fedora-bootc:44` is rebuilt daily and old digests are garbage
collected. The digest this project had pinned —
`sha256:fb71f099f40360b5e1e2e78e845ccf4f0f80fbe1b09de721d8954cddb89ee9c4` — was
**unreachable** when the hosted builder tried to pull it:

```text
reading manifest sha256:fb71f099… in quay.io/fedora/fedora-bootc: manifest unknown
```

The local Fedora builder still built against it, because it had the layers in its
local container store. That is the important part: **a build that appears to
reproduce may only be reachable from one machine's cache.** Pinning a digest
records *which* base was used; it does not make that base obtainable later.

Consequence: reproducibility evidence against any `fedora-bootc` digest has a
shelf life measured in days, and an independent builder starting from a clean
environment can only ever verify a base that is still published.

Removed by: mirroring the pinned base into a registry under this project's
control, or a content-addressed local mirror both builders pull from. Until then
every reproducibility comparison is against whatever base was current that week.

### A shipped unit starts a program the build does not install

`systemd/bunny-policy-agent.service` names `/usr/libexec/bunny-policy-agent`.
`build/scripts/install-root.py` copies `systemd/` wholesale, so the unit ships in
every profile; nothing installs the program, and `enterprise/policy.py` is a
library rather than an executable.

The unit is guarded by `ConditionPathExists=/etc/bunny-os/enrolment.json`, no
device has been enrolled, and the enterprise pilot gate is `BLOCKED`, so it does
not run on any system that exists. It is recorded in
`operations/data/unit-program-gaps.json`, and the `systemd unit programs`
repository validator fails any unit whose program is neither shipped nor
recorded.

Removed by: writing the agent, which is Phase 7 enterprise work and a new
product feature, not a portability repair.

### Both builders install from live repositories

`build/scripts/install-packages.py` uses the pinned snapshot repository only when
`BUNNY_RELEASE_BUILD=1`, and that mode requires
`build/repositories/fedora-44-snapshot.repo`, which does not exist. The directory
contains `fedora-44-snapshot.repo.example` and a README, and nothing else.

Both halves of the independent-builder comparison therefore ran with
`BUNNY_RELEASE_BUILD=0` and resolved their package sets against live Fedora
repositories, an hour apart. Fedora publishes continuously: the local build
installed kernel `7.1.5-201.fc44.x86_64` where earlier recorded evidence names
`7.1.5-200.fc44.x86_64`.

Two builders cannot be expected to produce identical images while each resolves
its own package set from a moving repository. The base image being digest-pinned
fixes the starting layer and nothing above it.

Removed by: provisioning and reviewing a real
`build/repositories/fedora-44-snapshot.repo`, which the build already knows how to
use and already validates (HTTPS, `gpgcheck=1`, `repo_gpgcheck=1`, exactly one
section). Until then a reproducibility comparison measures two builds of
different package sets and can only report what it measured.

### SELinux contexts cannot be compared from an archive-only build

A bootc container image carries no `security.selinux` xattrs in its layers —
measured: 164,962 entries, 9 carrying `security.capability`, zero carrying
`security.selinux`. `bootc install` applies contexts on the target from the
policy shipped in the image.

The `selinuxLabels` comparison dimension is therefore `NOT_COLLECTED` from an
archive-only build, and the comparison is `INCONCLUSIVE` rather than
`REPRODUCIBLE`. Reporting the two empty sets as a match would claim a comparison
that did not happen.

Removed by: comparing two installed systems, which needs a disk image from each
builder, which needs `image-builder` on both — and `image-builder` is Fedora-only
and unavailable on a hosted Ubuntu runner.

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

## Reproducible build remediation limitations, 2026-07-30

Branch `feature/reproducible-build-remediation`, from
`e7600b08236806f1c9c656d79b074924c40dfb19`. The attempt-1 result is retained and
was not overwritten.

### The retained inputs exist on one machine, which is the defect being fixed

The base image, the builder image and the package snapshot are mirrored,
verified and locked — and they live only in `/var/lib/bunny-retention` on the
Fedora builder. The retention channel chosen for this pass is `ghcr.io`, and the
available GitHub token carries `gist, read:org, repo, workflow`; pushing needs
`write:packages`, which has not been granted.

Until it is, an independent party cannot obtain the inputs, which is precisely
the failure the mirror exists to remove. `gh auth refresh -h github.com -s
write:packages,read:packages` is the whole of the fix.

### The remediation was implemented and unmeasured, and measuring it changed it

*Superseded 2026-07-30 by the SQLite determinism pass. Retained because the
limitation was real and its resolution is the point.*

Every mechanism existed and none had been verified by a two-builder comparison.
When one was run, three of them turned out not to do what they were documented to
do:

* the frozen package transaction was not frozen. `FAKETIME` carried an `@`
  prefix, which is libfaketime's *start-at* mode; `INSTALLTIME` recorded elapsed
  build seconds and fifty of 1,015 packages landed on a different second between
  two builds.
* the minimisation `dnf remove` ran with no clock override at all, so libdnf5
  wrote a live wall clock into its transaction history.
* `usr/share/bunny-os/finalisation.json` had identical content and mtimes 203
  seconds apart. Layer tars carry entry mtimes and no dimension compared them, so
  the archive difference had no file to attribute it to.

See `RPM_DATABASE_DETERMINISM_REPORT.md`. The general lesson is recorded here
because it is not about libfaketime: a decision document records what somebody
intended, and the effect has to be measured in the artifact.

### The input locks were not in the commit

*Found and fixed 2026-07-30.* `base-image-lock.json`, `package-lock.json`,
`package-snapshot-lock.json` and `reproducibility-lock.json` were untracked. The
previous "fresh clone" comparison worked because they had been hand-copied into
each clone; a hosted builder has nothing but the commit, so the pins pinned
nothing a second builder could see. They are committed, and
`local-hermetic-repeatability.sh` refuses to build until they are tracked.

### Two builds shared a container store and a layer cache

*Found and fixed 2026-07-30.* The repeatability driver created a store per build
and never told podman about it. podman keys its build cache on the instruction
and the context digest, and two fresh clones of one commit produce the same
both — so the second build could be served the first one's layers and produce a
byte-identical archive because it *was* the first archive. `--no-cache` is now
always on in the hermetic path and the store is genuinely per-build.

A comparison that can only pass is worse than one that fails, and this one had no
way to report that it had not really run twice.

### `rpm -qi` will report the commit timestamp as the install time

A consequence of ADR-028, accepted deliberately. For an image built once and
installed on many devices there was never a correct per-device install time in
the image, but anyone reading the field as "when this machine installed it" will
be wrong.

### The snapshot repository has `repo_gpgcheck=0`

`repo_gpgcheck` verifies a detached GPG signature over `repomd.xml` that a Fedora
mirror provides and a local snapshot does not. What replaces it: the snapshot
manifest is signed, carries the SHA-256 of `repomd.xml`, and is verified before
the build container starts. `gpgcheck=1` stays on and every RPM's own Fedora
signature is checked at install time against Fedora's key for that release.

This is a real difference from the remote-snapshot path and is recorded rather
than described as equivalent.

### The snapshot signing key is a development key

`dev-snapshot-signing1`, Ed25519, held outside the repository.
`release.signing.require_production_key` refuses the `dev-` prefix, so nothing
signed with it can satisfy a release gate. It establishes that the snapshot has
not changed since it was made and nothing about release authorisation.

### Only the amd64 architecture is retained

The upstream base is a four-architecture index; the mirror holds the amd64
manifest and records the other three by digest without their blobs. An arm64
build would fail at verification rather than silently pull from upstream, which
is correct, and also means this project can currently qualify one architecture.
