# Bunny OS Phase 1 report

## Identification

- Baseline commit: `8fc27253e448cfe0cbe267231f816012f831ebf0`
- Feature branch: `feature/os-foundation`
- Selected base/version: Fedora Linux 44 `fedora-bootc`, x86-64 UEFI first
- Base support: Fedora schedule currently indicates May 2027 EOL; rebase required before then
- Desktop: GNOME/Mutter, Wayland default, XWayland compatibility
- Image tool: OCI Containerfile + unified OSBuild `image-builder`
- Update/rollback: signed manifest + `bootc switch`; prior deployment + `bootc rollback`
- Recovery: Bunny-independent systemd target and separately composable headless QCOW2 prototype
- Integration contract: 1.0.0, independent of Bunny protocol v3
- Broker: 0.1.0, AF_UNIX/SO_PEERCRED, strict JSON, Polkit per mutation, fixed root backend

## Layout and services

Image-managed `/usr` and `/opt/bunny`; persistent `/etc`, `/var`, `/home`; user Bunny state/models/plugins stay in per-user XDG paths; root-only update/recovery state under `/var/lib/bunny-os`; per-request 0600 support bundles; volatile socket under `/run/bunny`. This is accurately called image-managed, not universally immutable.

System units: broker socket/service, update agent instances/timer, health check, recovery prepare/target/console. User units: first-boot preferences and opt-in Desktop. GNOME Initial Setup owns locale/keyboard/timezone/user/hostname/network. Tauri Desktop owns its Core/app-server sidecars; OS units do not duplicate them.

## Security controls

SELinux enforcing base, deny-inbound firewalld, SSH/telemetry/update timer/Desktop autostart off, loopback app/model policy, AF_UNIX broker, fixed process identity/Polkit/replay/rate/timeout/audit, systemd sandboxing, Ed25519 manifest/revocation/expiry/sequence/repository/digest checks, prior deployment, offline health/recovery, no private keys/credentials/cloud requirement. Production signature policy, disk/Secure Boot, SELinux domains and runtime evidence remain blockers.

## Artifacts and test facts

Image artifacts: **none produced on this host**. Bunny artifact: explicit schema-verified non-functional 0.2.0 placeholder sourced from upstream commit `f27fa63e0406e91149aeacf8437c36b960e09961`. VM tests: **not performed**. Hardware tests: **none**; all named hardware is untested and legacy BIOS unsupported.

Available validation passed: 33 host tests (one Linux-only timeout case skipped), 6 security-focused subset, 13 broker-focused subset (same skip), 11 JSON parses, 3 schema header/local-reference validations, 39 Python in-memory compiles, six Bash syntax checks, checkout-mode CLI/info smoke checks, and the original 24-check architecture verifier. Full JSON Schema meta-validation, systemd/ShellCheck/SELinux/image/SBOM/VM/hardware gates did not run locally.

## Exact commands

Host commands executed:

```text
python scripts/task.py validate
python scripts/task.py test
python scripts/task.py test-security
python scripts/task.py test-broker
powershell -NoProfile -ExecutionPolicy Bypass -File .\docs\phase-1\verify.ps1
C:\msys64\usr\bin\bash.exe -n build/scripts/build-image.sh build/scripts/inspect-image.sh build/scripts/vm-smoke.sh build/scripts/sbom.sh build/scripts/security-scan.sh scripts/greenboot-bunny-health.sh
python tools\bunny-os\bin\bunny-os-info --json
python tools\bunny-os\bin\bunny-os version --json
```

Builder commands to execute:

```text
make audit
make validate
make test
make test-security
make test-broker
make build-developer-image
make build-recovery-image
make inspect-image
make vm-smoke
make sbom
make security-scan
make license-scan
FULL_GATE=1 make gate
```

## Blockers and recommendation

Blockers: unavailable Linux builder/KVM tooling; no image/boot evidence; no signed Bunny Linux artifact; no release base/repository pin; no OS update keys/registry signature policy; no SBOM/scan; no systemd score/SELinux AVC qualification; no Secure Boot/LUKS/VM/hardware tests; no repeated-build comparison.

Recommendation: accept this branch as the Phase 1 implementation foundation only, not as a completed/releasable OS. Keep Phase 2 blocked and run the Phase 1 validation-closure list in `NEXT_PHASE.md`. Stop here; do not begin a Bunny Shell, compositor, installer UX, app store, or consumer release.
