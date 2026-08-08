# Bunny OS

Bunny OS is an independently branded, Linux-based operating-system layer for the existing Bunny platform. Linux remains the kernel, systemd remains the lifecycle authority, and Fedora supplies the maintained hardware/userspace base. Bunny is an application and system-intelligence layer; it is not a kernel, init system, driver stack, or generic root facility.

Phase 1 selected Fedora 44 bootc, GNOME on Wayland, SELinux, firewalld, a versioned local integration contract, a narrowly scoped privileged broker, signed-manifest update scaffolding, conventional recovery, and unified OSBuild `image-builder` QCOW2 definitions. Phase 2 layers Bunny Shell on GNOME 50: selectable normal/safe sessions, a typed launcher, project workspaces, private desktop search, task/plan/approval projections, Bunny-aware command proposals, settings/privacy surfaces, original visual identity, and bounded user services.

The current checkout has source definitions and passing host gates, but this Windows host has no Podman, unified `image-builder`, Linux systemd, or QEMU/KVM. No Phase 1 or Phase 2 disk artifact, graphical boot, VM interaction, or hardware result is claimed. The signed upstream Bunny Linux artifact also remains unavailable, so Bunny/Core end-to-end surfaces correctly degrade to unavailable.

## Release state — 2026-08-08

**Bunny OS is not releasable and no pilot may begin.** Read this before anything
else in this repository.

```text
Source gate:               PASS at 85dead7 (Fedora 44 reference host)
Qualification candidate:   BLOCKED   (3 of 14 prerequisites satisfied)
Stable release:            NO-GO
OEM pilot:                 BLOCKED
Enterprise pilot:          BLOCKED
Encrypted-sync pilot:      BLOCKED
```

The source gate result binds to commit `85dead7`, measured by
`python scripts/release.py gate --kind source` on the Fedora 44 reference host
as unprivileged user `bunny` from an ext4 checkout — exit code 0, all six
requirements satisfied. It is not a claim about any later commit.

Two earlier statements it replaces. The previous `PASS` was the assertion added
in `9dc7e33` with no `gate-source.json` committed beside it, so nothing bound it
to a tree. And a Windows run of the same gate cannot stand in for this one:
ShellCheck is absent there, so that validator skips and a real fail-open defect
in `build/scripts/vm-alpha-story.sh` was invisible. Run it as `root` and an
eighth test fails that should not — a read-only directory is writable for root —
so the account is part of the measurement too.

| Closed | State |
|---|---|
| Licensing | **complete** — GPL-3.0-or-later for the OS layer, Apache-2.0 for the client packages; root and eight per-directory licences, 127 SPDX headers, a clean 6,077-record scan, 7 of 7 gate requirements |
| Package minimisation | **complete** — `toolbox` removed from four consumer profiles with a fail-closed protected-package check. **It changed no scan number**, and no claim is made that it reduced security risk |
| Development signing drill | **PASS — 9/9** against real 1.85 GB and 1.33 GB artifacts, including four refusals |
| Two-person development signing drill | **PASS — 9/9** with two separate Ed25519 keys, including two refusals |
| Independent reproducibility | **established at the archive stage, 2026-08-01.** Three builders across two administrator boundaries — local Fedora WSL, hosted `H1` run `30714175121`, hosted `H2` run `30714176083` — built candidate `b9c317d` and presented the same bytes: raw `29e54aaf…`, normalised `68c12c71…`, 17 of 17 dimensions MATCH on all three pairwise comparisons. `verify-builder-independence` returns PASS from real environment evidence. **Scope: archive-only.** `BUNNY_ARCHIVE_ONLY=1`, so no disk image was built and this is not a candidate build; `appliedSelinuxContexts` stays NOT_COLLECTED and belongs to installed-system qualification |

| Open | State |
|---|---|
| Vulnerability position | **59 fixable, 8 Critical, 28 High, 23 Medium — unchanged.** All 24 unique Critical/High findings are dispositioned `Unknown`, which blocks. Every one comes from the digest-pinned Fedora bootc base, and a base rebuild on 2026-07-29 did not move the counts |
| Physical hardware | **zero reports.** No physical machine has ever run Bunny OS |
| Accessibility | **0 of 17 runtime flows driven.** Static tests pass and are explicitly not sufficient |
| Independent reviews | **four requests ready to send, zero commissioned, zero delivered** |
| Production signing | **no production key of any role exists.** Four of seven roles need two signers; there is one |
| Protected approvals | **nine pending** |

Start here:

- `QUALIFICATION_EVIDENCE_CLOSURE_REPORT.md` — what the most recent pass built, and what it deliberately did not claim
- `QUALIFICATION_CANDIDATE_READINESS_REPORT.md` — the fourteen prerequisites, each with an owner
- `docs/QUALIFICATION_EVIDENCE_BASELINE.md` — every unmet requirement classified by who can produce the evidence
- `docs/STABLE_RELEASE_BLOCKERS.md` — what blocks a stable release
- `KNOWN_LIMITATIONS.md` — what this repository does not do

## Quick start

On any development host:

```text
python scripts/task.py audit
python scripts/task.py validate
python scripts/task.py test
python scripts/task.py test-shell
python scripts/task.py test-desktop-security
```

On the documented Fedora 44 image-builder host:

```text
make gate
make build-developer-image
make build-shell-image
make inspect-image
make vm-smoke
make vm-shell-smoke
make sbom
```

Release builds additionally require `BUNNY_RELEASE_BUILD=1`, a digest-pinned `BUNNY_BASE_IMAGE`, reviewed update public keys, and a signed upstream Bunny Linux artifact. See `docs/BUILDING.md`, `docs/KNOWN_LIMITATIONS.md`, and `PHASE_1_REPORT.md` before treating any output as releasable.

## Repository map

- `build/`: OCI image, profiles, package manifests, trust placeholders, image-builder wrappers.
- `capability/`: the capability runtime — hardware discovery, capability scoring, resource budgets, service manifests, and the deterministic policy engine that decides what runs on this machine and why.
- `services/`: local privileged broker and root-only update agent.
- `systemd/`, `config/`, `selinux/`: service, policy, firewall, sysctl, and MAC inputs.
- `tools/bunny-os/`: conventional management CLI and local hardware inventory.
- `schemas/`: OS contract, update manifest, and Bunny artifact schemas.
- `shell/`: Bunny Shell services, schemas, GNOME integration, sessions, themes, icons, and wallpapers.
- `tests/`: host tests plus shell/image/boot/VM fixtures and procedures.
- `demos/01-os-foundation/`: repeatable Phase 1 demonstrations.
- `demos/02-bunny-shell/`: Phase 2 demonstrations and expected degraded/full behavior.
- `docs/phase-1/`: the earlier constitutional/architecture package retained as governing history.

Phase 2 stops before installer development, hardware provisioning, an app store, device manufacturing, consumer distribution, or stable release work. See `PHASE_2_REPORT.md` for remaining runtime blockers.

Phase 3 source now adds an Anaconda/bootc installation architecture, typed non-destructive storage/encryption planning and safety, live/beta image definitions, first-run onboarding, Flatpak/GNOME Software policy, documentation, and host tests. The production Anaconda adapter is intentionally absent and no image, disk write, encrypted boot, VM, or hardware result exists. Run `make gate-phase-3` for static checks and read `PHASE_3_REPORT.md` plus `docs/KNOWN_ISSUES.md` before treating it as installable.

Phase 5 source adds privacy-safe beta feedback/triage, failure signatures, installer transaction journals, stable evidence rules, compatibility/preservation/hardware/candidate gates, maintenance alerts, stable-support documentation, and demonstrations. Phase 4/public-beta inputs are absent, so the stable recommendation is `NO-GO`. Run `make gate-phase-5`; expect `make gate-stable-candidate` and `make gate-stable-release` to remain blocked until complete signed runtime evidence and approvals exist. Start with `docs/PHASE_5_BASELINE.md` and `PHASE_5_REPORT.md`.

Phase 7 source adds OEM profiles and factory finalisation (`oem/`), device identity, enrolment, a typed policy agent, fleet rings, a closed remote-administration boundary, multi-tenant scoping, audit chaining, air-gapped management, kiosk and shared-device profiles, and decommissioning (`enterprise/`), plus an optional end-to-end encrypted sync client (`sync/`). All three packages are standard-library only, and executors that would touch hardware or perform real cryptography report themselves unavailable rather than degrading.

## Capability runtime

`capability/` is the foundation that makes Bunny OS one operating system across
every machine it is installed on. It detects hardware, measures usable resources
inside whatever ceilings are imposed, calculates safe budgets, evaluates service
requirements against them, and produces a deterministic execution plan with a
stated reason for every decision.

**There are no modes.** No Low, Balanced, High or Ultra; no Raspberry Pi edition
and no DGX edition. A 64 MB ARM board and a 512 GB eight-accelerator server run
the same image, the same fourteen service manifests and the same policy engine.
What differs is which implementation of each service was selected and which
features were refused — and both machines answer `bunny-os capability explain`
in the same format. This implements constitutional requirement **C11** from
`docs/phase-1/BUNNY_OS_PHASE_1.md`: *a profile keyed on a product tier fails
review.*

```text
bunny-os capability inspect | scores | budget | plan | status | policy
bunny-os capability explain <service-id>
bunny-os capability plan --simulate embedded-64mb        # any of eleven simulations
```

Start with `docs/CAPABILITY_RUNTIME.md`. `MODE_MIGRATION_REPORT.md` records the
sweep for prior mode implementations — one collapsed hardware label was found
and migrated; no mode system existed. The subsystem produces a plan and does
**not** apply it, the 64 MB target is calculated rather than measured, and no
physical hardware has been exercised; see `KNOWN_LIMITATIONS.md` under
"Capability runtime".

On any development host run `python scripts/task.py phase7-audit` and the `test-*` commands directly; all pass. On a host with `make`, `gate-phase-7-source` composes them. `gate-phase-7`, `gate-oem-pilot`, `gate-enterprise-pilot`, and `gate-sync-pilot` all fail closed, because no stable release exists. No pilot may begin, no device may be manufactured, no fleet may be deployed, and no hosted sync service may launch. Start with `docs/PHASE_7_BASELINE.md`, `PHASE_7_REPORT.md`, and `demos/07-oem-enterprise-sync/`.

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
