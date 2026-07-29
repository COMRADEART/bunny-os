# Bunny OS Phase 1 test report

Date: 2026-07-28  
Host: Windows, Python 3; no Linux systemd/container/KVM runtime

| Command | Result |
|---|---|
| `python scripts/task.py validate` | PASS: 11 JSON documents parsed; 3 schema headers/local-reference graphs validated; 39 Python files compiled in memory |
| `python scripts/task.py test` | PASS: 33 tests, 1 Linux-only timeout test skipped |
| `python scripts/task.py test-security` | PASS: 6 focused tests (subset of 33) |
| `python scripts/task.py test-broker` | PASS: 13 focused tests, 1 Linux-only timeout test skipped (subset of 33) |
| `powershell -NoProfile -ExecutionPolicy Bypass -File .\docs\phase-1\verify.ps1` | PASS: 24 structural checks |
| JSON Schema meta-validation | SKIP: `jsonschema` not installed; syntax parsed |
| ShellCheck | SKIP: unavailable |
| `systemd-analyze verify/security` | SKIP: unavailable/non-Linux |
| SELinux policy compile | NOT RUN locally; CI job defined |
| MSYS2 Bash `-n` on six shell scripts | PASS |
| `bunny-os-info --json`; `bunny-os version --json` | PASS in checkout fallback mode |
| image inspection/secret/vulnerability/license scan/SBOM | BLOCKED: no image/tooling |
| QEMU/rollback/recovery/privacy egress | BLOCKED: no image/QEMU |
| physical hardware | NOT PERFORMED |

Automated coverage includes valid/malformed/unknown/injection-shaped/stale/replayed broker requests, denied mutation, rate limits, metadata-only audit, update manifest/key/arch/sequence/space/interruption cases, honest capability states, privacy/firewall/systemd source invariants, profile/package linkage, and absent private keys.

Not covered by the passing count: actual SO_PEERCRED/logind/Polkit interaction across Linux users, root backend systemctl/bootc, service startup/shutdown/restart/dependency behavior, systemd score, SELinux enforcement, image permissions/listeners/secrets, boot health, update power interruption, or hardware. Procedures exist in `docs/TESTING.md`.

## Phase 2 host test update

| Command | Result |
|---|---|
| `python scripts/task.py validate` | PASS: 21 JSON documents, 9 schema graphs, 82 Python files, 6 desktop entries, 8 XML/SVG assets, Node syntax check |
| `python scripts/task.py test` | PASS: 92 tests; 1 inherited Linux-only timeout test skipped |
| `python scripts/task.py test-desktop-security` | PASS: 13 security-directory tests |
| `python scripts/performance-baseline.py` | PASS: deterministic host microbenchmarks; not graphical evidence |
| `C:\msys64\usr\bin\make.exe PYTHON=python gate-phase-2` | PASS: complete static Phase 1 + Phase 2 Make gate |
| MSYS2 Bash `-n` on seven shell scripts | PASS |
| ShellCheck/systemd/GLib/desktop-file/nested GNOME | SKIP/BLOCKED: unavailable Windows host |
| image/inspection/SBOM/scan/VM targets | INVOKED, BLOCKED: Bash not on Make PATH/no artifacts; builder tooling absent |
| hardware/accessibility runtime | NOT PERFORMED |

Phase 2 coverage includes malicious desktop entries/URI handlers, deterministic/ambiguous intents, broker confirmation flags, workspace lifecycle/no-delete/secret rejection, approved search roots/exclusions/deletion/purge/no-content, settings type/range/reset/local/offline/defaults, parsed terminal risk/proposal non-execution, approval scope/unbounded denial, lock notification privacy, safe-session wiring, fixed panel actions, accessibility labels/focus/settings, and user-service hardening.

## Phase 3 host test update

| Command | Result |
|---|---|
| `python scripts/task.py validate` | PASS: 27 JSON documents, 13 schemas, 130 Python files, 9 desktop entries, 8 XML/SVG assets |
| existing test component | PASS: 92 tests, one Linux-only skip |
| `python scripts/task.py test-installer` | PASS: 60 Phase 3 tests |
| aggregate repository `test` command | PASS: both suites, 152 total, one skip |
| `C:\msys64\usr\bin\make.exe PYTHON=python gate-phase-3` | PASS static mode |
| seven Phase 3 Bash scripts via MSYS2 `bash -n` | PASS |
| image/disk/Anaconda/LUKS/UEFI/VM/hardware | BLOCKED or NOT RUN |

Artifact targets were invoked through Make (blocked because Bash was not resolved on Make's Windows PATH) and directly through MSYS2 Bash. Direct checks failed closed on missing Podman, QEMU, Phase 1/2/live artifacts, and Syft. No partial image or disk was produced.

Phase 3 tests cover strict protocol and schema boundaries; request staleness/secrets/generic commands; token/cross-session/replay; disk parsing and identifier redaction; installation media, small, read-only, mounted, sector and complex-stack policy; disk-bound confirmations; erase/encrypted/alongside/manual plans; LUKS2/TPM/recovery keys; media signature/hash/path failure with a mocked signature process; live/beta definitions; first-run privacy/resume/search/secret constraints; Flatpak/native permissions/remotes; firmware/NVIDIA policy; and source command invariants. Synthetic metadata is not destructive virtual-disk evidence.
