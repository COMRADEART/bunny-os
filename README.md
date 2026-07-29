# Bunny OS

Bunny OS is an independently branded, Linux-based operating-system layer for the existing Bunny platform. Linux remains the kernel, systemd remains the lifecycle authority, and Fedora supplies the maintained hardware/userspace base. Bunny is an application and system-intelligence layer; it is not a kernel, init system, driver stack, or generic root facility.

Phase 1 selected Fedora 44 bootc, GNOME on Wayland, SELinux, firewalld, a versioned local integration contract, a narrowly scoped privileged broker, signed-manifest update scaffolding, conventional recovery, and unified OSBuild `image-builder` QCOW2 definitions. Phase 2 layers Bunny Shell on GNOME 50: selectable normal/safe sessions, a typed launcher, project workspaces, private desktop search, task/plan/approval projections, Bunny-aware command proposals, settings/privacy surfaces, original visual identity, and bounded user services.

The current checkout has source definitions and passing host gates, but this Windows host has no Podman, unified `image-builder`, Linux systemd, or QEMU/KVM. No Phase 1 or Phase 2 disk artifact, graphical boot, VM interaction, or hardware result is claimed. The signed upstream Bunny Linux artifact also remains unavailable, so Bunny/Core end-to-end surfaces correctly degrade to unavailable.

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

On any development host run `python scripts/task.py phase7-audit` and the `test-*` commands directly; all pass. On a host with `make`, `gate-phase-7-source` composes them. `gate-phase-7`, `gate-oem-pilot`, `gate-enterprise-pilot`, and `gate-sync-pilot` all fail closed, because no stable release exists. No pilot may begin, no device may be manufactured, no fleet may be deployed, and no hosted sync service may launch. Start with `docs/PHASE_7_BASELINE.md`, `PHASE_7_REPORT.md`, and `demos/07-oem-enterprise-sync/`.
