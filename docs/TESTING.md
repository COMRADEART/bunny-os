# Testing

## Host gate

```text
make audit
make validate
make test
make test-security
make test-broker
make test-shell
make test-launcher
make test-search
make test-workspace
make test-panel
make test-notifications
make test-approvals
make test-settings
make test-terminal
make test-accessibility
make test-desktop-security
make performance-baseline
make gate-phase-2
make gate
```

The suite covers strict broker requests, invalid/injection-shaped methods/params, stale/replayed requests, rate limiting, denied Polkit mutation, metadata-only audit logs, update validity/bad key/wrong arch/rollback sequence/disk/interruption, capability honesty, privacy defaults, firewall, service hardening, package/profile linkage, and absent private keys.

On Linux, validation additionally runs ShellCheck and `systemd-analyze verify`. Fedora CI compiles the SELinux prototype. Record `systemd-analyze security` scores for every unit in `TEST_REPORT.md`; do not substitute a static directive check for the score.

## Artifact and VM gate

Build/inspect commands are in `docs/BUILDING.md`. For QEMU/KVM use UEFI q35, 4 vCPU, 6–8 GiB RAM, 64 GiB virtio disk, virtio network and GPU. Validate normal/recovery/previous deployment, root deployment evidence, expected files/modes/services, no secrets/world-writable system paths, GDM/Wayland, networking/audio/suspend if supported, first boot, placeholder/verified Bunny behavior, broker read/denial/mutation, update stage, power cycle, health success/failure, rollback, recovery menu, and support export. Capture serial, journal, `bootc status --json`, sockets, firewall, listeners, SELinux AVCs, and checksums.

Negative update fixtures: bad signature, revoked/unknown key, wrong repo/digest/channel/arch/contract/Bunny range, expired/old sequence, insufficient disk, interrupted registry, bootc failure, unsigned image, and health failure. Privacy fixture: 10-minute packet capture with update disabled and no user apps; expected outbound Bunny OS traffic is zero.

VMware/VirtualBox use 4 vCPU, 8 GiB RAM, 64 GiB disk, UEFI, NAT, default virtual GPU/audio; record as separate results. Physical hardware follows `docs/HARDWARE_SUPPORT.md`. VM success cannot promote physical status.

## Phase 2 desktop gate

Static coverage includes session/safe-mode wiring, GNOME 50 extension metadata and syntax, fixed panel actions, typed intent routing, malicious desktop entries/URL handlers, private approved-location search, deterministic index removal, workspace persistence/archival/no-delete behavior, settings validation/local/offline modes, lock-screen notification redaction, scoped approvals, command parsing/classification, visible focus, programmatic labels, and user-unit resource hardening.

On Fedora 44 additionally run `glib-compile-schemas --strict`, `desktop-file-validate`, `systemd-analyze verify`, `gnome-extensions pack`, a nested `dbus-run-session gnome-shell --devkit --wayland` extension load, Orca keyboard flows, 200%/high-contrast/reduced-motion visual checks, and `tests/vm/PHASE_2.md`.

`FULL_GATE=1 make gate-phase-2` builds developer, shell, shell-test, and recovery images; inspects contents; generates SBOM/security/licence evidence; and runs normal/shell VM smoke. Interactive session/portal/multi-monitor/accessibility scenarios still require recorded manual evidence.
