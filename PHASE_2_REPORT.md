# Bunny OS Phase 2 report

Date: 2026-07-28  
Baseline commit: `8fc27253e448cfe0cbe267231f816012f831ebf0`  
Feature branch: `feature/bunny-shell`  
Outcome: source implementation and host validation pass; image/VM/hardware validation blocked

## Architecture and integration mechanism

Bunny Shell is a GNOME 50 extension plus GTK4 user surfaces, versioned per-user models, desktop/Nautilus entries, and bounded systemd user units on Fedora 44 GNOME/Mutter Wayland. It does not replace the compositor, display/input stack, notifications, settings daemons, file manager, terminal, portals, logind, or accessibility stack. GDM definitions add Bunny and Bunny Safe Shell while retaining base GNOME.

Session components are `bunny-shell@bunny-os.org`, `bunny-shell.target`, `bunny-shell-status.service`, `bunny-search-index.timer/service`, Bunny Launcher, Workspaces, Settings, Terminal proposal, command, project, task, plan, and approval surfaces. The normal session starts only the user target; Safe Shell stops it and the extension is a no-op.

## Launcher and workspace

Launcher results use typed intent schema 1 and distinguish application, approved file/folder metadata, workspace, Bunny request, system action, setting, task, and plan routes. Installed desktop entries undergo bounded strict parsing; shell/privilege wrappers, unsafe paths/field codes/URL handlers, and shell metacharacters are rejected. System actions are typed broker method proposals with confirmation; Bunny prompts cannot directly invoke the broker.

Workspace schema 1 stores private per-user metadata with atomic transactions. Create, rename, duplicate, archive, restore, project attach/detach, and Bunny thread attach are implemented. Credential-shaped metadata is rejected, and metadata removal never manipulates project files. Runtime GNOME window movement remains unqualified.

## Search privacy

Search defaults to zero locations, indexes metadata only, rejects the whole home/root/parent directories, skips symlinks and exclusions, caps 20,000 entries, never uploads, and purges removed/deleted paths deterministically. Encryption is reported unknown without evidence. Search failure cannot prevent application launching, Files, or direct workspaces.

## Terminal and settings

GNOME Terminal and the user's shell remain. Bunny command proposals are shown with cwd, environment changes, parsed risk class, approval/checkpoint/sandbox requirements, dry-run hint, editability, and `executesAutomatically=false`. Unknown, shell-wrapped, command-substitution, destructive, system, network, write, and read-only cases are covered.

Bunny Settings links stable GNOME modules and owns schema-1 Bunny preferences. Each setting has type/default/validation/reset/owner/scope. Resets back up state. Raw credential fields are absent. Local-only and offline modes disable cloud failover without breaking loopback; telemetry and clipboard history default off. OS update/recovery remain separate Phase 1 broker operations.

## Visual identity and accessibility

Original evergreen/mint tokens, System/Light/Dark/High Contrast CSS, five SVG icons, scalable 4K light and 5K ultrawide dark wallpapers, visible focus, reduced motion/transparency, system fonts, and provenance are included. No third-party OS branding or restricted font is copied.

AT-SPI, Orca, and mousetweaks are image packages. Static tests cover accessible labels, keyboard activation, visible focus, text scale, and reduced motion. No real Orca/login/magnifier/switch-device session ran, so WCAG 2.2 AA remains a target rather than a conformance claim.

## Security and degraded modes

The shell has no root service, network listener, generic command backend, provider credentials, Bunny database access, or direct permission grant. Bunny summaries are bounded, private, same-user, schema-validated, and read-only. Approvals forbid an unbounded grant; lock-screen notifications hide body/actions and sensitive titles. Systemd applies no-new-privileges, filesystem protection, address-family limits, restart limits, memory/task caps, and timeouts.

Bunny unavailable: conventional launcher/apps, Files, Terminal, Settings, workspaces, updates, recovery remain. Broker unavailable: privileged actions unavailable with no fallback. Search unavailable: apps/Files/direct workspaces remain. Safe Shell preserves user data and conventional repair access.

## Performance results

Windows host-only medians/p95/max: intent routing 0.0008/0.0011/0.0155 ms; one-entry metadata search 0.1918/0.4146/0.5367 ms; workspace read 0.2713/0.5558/0.7190 ms; settings read 0.0351/0.0443/0.2009 ms. These are not graphical, VM, 20k-index, idle-resource, CPU, GPU, or login measurements.

## Validation results

- Phase 1 preflight: validate PASS; 33 tests PASS with one Linux-only skip; 6 security tests PASS; 13 broker tests PASS with one Linux-only skip; 24-check original verifier PASS; checkout info/version PASS.
- After Phase 2: validate PASS (21 JSON documents, 9 schemas, 82 Python files, 6 desktop entries, 8 XML/SVG assets, GNOME extension JavaScript syntax); 92 tests PASS with one Linux-only skip; desktop-security/security-directory target 13 PASS.
- Repository-native `gate-phase-2` PASS in static mode using MSYS2 Make and `PYTHON=python`; all component targets passed.
- ShellCheck, installed-form systemd verification/security, schema meta-validation, GLib schema compilation, desktop-file validation, nested GNOME, SELinux runtime, image inspection, SBOM, vulnerability/license scan, VM, and hardware did not run here.

Exact commands run:

```text
python scripts/task.py validate
python scripts/task.py test
python scripts/task.py test-security
python scripts/task.py test-broker
powershell -NoProfile -ExecutionPolicy Bypass -File .\docs\phase-1\verify.ps1
python tools\bunny-os\bin\bunny-os-info --json
python tools\bunny-os\bin\bunny-os version --json
python scripts/task.py test-desktop-security
python scripts/performance-baseline.py
C:\msys64\usr\bin\make.exe PYTHON=python gate-phase-2
C:\msys64\usr\bin\bash.exe -n build/scripts/build-image.sh build/scripts/inspect-image.sh build/scripts/vm-smoke.sh build/scripts/vm-shell-smoke.sh build/scripts/sbom.sh build/scripts/security-scan.sh scripts/greenboot-bunny-health.sh
```

Required Linux builder commands not run:

```text
make validate
make test
make test-security
make test-broker
make test-shell
make test-launcher
make test-search
make test-settings
make test-terminal
make test-accessibility
make test-desktop-security
make build-developer-image
make build-shell-image
make build-shell-test-image
make build-recovery-image
make inspect-image
make inspect-shell-image
make vm-smoke
make vm-shell-smoke
make sbom
make shell-sbom
make shell-security-scan
make shell-license-scan
FULL_GATE=1 make gate
FULL_GATE=1 make gate-phase-2
```

## VM, hardware, and artifacts

No developer/shell/shell-test/recovery OCI, QCOW2, checksum, SBOM, or scan artifact was produced. The artifact Make targets were invoked and failed closed: Bash was not on the PowerShell/Make PATH, and the licence scan had no generated SPDX input. Direct MSYS2 Bash syntax validation passed for seven scripts. Podman/image-builder/QEMU/Syft/Grype inputs remain absent. No QEMU/KVM, VirtualBox, VMware, or hardware test ran. Graphical login, shell selection, launcher/panel/terminal/settings, approvals/tasks/workspaces, safe shell, suspend/lock/logout/reboot, multi-monitor, touchpad, Wi-Fi, Bluetooth, audio, microphone, camera, battery, HiDPI, GPU, Secure Boot, and recovery remain untested.

## Blockers and Phase 3 recommendation

Blockers are the inherited Phase 1 image/security/runtime gaps, missing signed Bunny Linux artifact, absent Fedora/KVM builder, unqualified GNOME 50 extension/session, and absent accessibility/performance/VM/hardware evidence. Phase 2 is not release-complete against the definition of done because its image has not booted and VM/accessibility gates have not passed.

Recommendation: do not begin Phase 3. First run the full Phase 1/2 builder gate, qualify GNOME/Bunny integration and degraded/safe sessions, fix discovered defects, archive artifacts/SBOM/logs, and complete accessibility/performance/multi-monitor/hardware evidence. Stop before installer, app store, provisioning, manufacturing, distribution, or stable release work.
