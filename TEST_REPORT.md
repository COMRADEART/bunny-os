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

## Phase 5 host test update

| Command | Result |
|---|---|
| `python scripts/task.py validate` | PASS: 46 JSON documents, 21 schemas, 161 Python files, 9 desktop entries, 8 XML/SVG assets |
| `python scripts/task.py test-phase5` | PASS: 74 Phase 5 operations tests |
| Phase 1–3 static preflight | PASS: 152 prior tests, one inherited Linux-only skip; 24-check verifier |
| `gate-phase-4`; `gate-public-beta` | BLOCKED: Phase 4/public-beta reports absent |
| beta build/install attempts | BLOCKED: no artifact; Podman and QEMU unavailable |
| candidate/release runtime gates | expected BLOCKED until signed evidence and approvals exist |

Final Phase 5 run: 92 inherited tests passed with one Linux-only skip, 60 installer tests passed, and 74 Phase 5 tests passed: 226 distinct passes and one skip. `gate-phase-5` passed as source/operations only. The candidate and stable-release gates blocked on the absent candidate manifest; the direct decision remained `NO-GO`.

Coverage includes import schemas, PII/secret/user-content redaction, deterministic IDs, advisory duplicates, taxonomy, failure matching, journal transitions/irreversibility, update-route rejection, preservation hashes, hardware tiers, crash metadata, multi-user/local-only/Bunny-disabled requirements, maintenance alerts, candidate completeness/signing safeguards, accessibility mandatory status, and NO-GO decisions. It is source evidence, not beta operation or stable qualification.

## Phase 7 preflight update

| Command | Result |
|---|---|
| `make -s PYTHON=python gate-stable-release` | BLOCKED after inherited static suites passed: stable candidate manifest absent |
| `python scripts/phase5.py phase4-preflight` | BLOCKED: nine required Phase 4/public-beta reports absent |
| `python scripts/phase5.py stable-gate --evidence operations/data/stable-qualification.json` | NO-GO: five blocker codes and 31 missing/pending evidence or approvals |
| `make -s PYTHON=python verify-stable-rc` | BLOCKED: stable public key and candidate absent |
| Phase 7 component and pilot gates | NOT CREATED / NOT RUN: mandatory entry gate failed before implementation |

The passing inherited tests remain source/static evidence and do not validate a
stable release, OEM image, factory process, fleet, tenant boundary, or encrypted
sync system.

## Phase 7 blocker-remediation validation

| Check | Result |
|---|---|
| repository audit | PASS: 50 required documents present |
| repository validation | PASS: 46 JSON documents, 21 schema headers, 162 Python files, 9 desktop entries, 8 XML/SVG assets, Node syntax |
| final full Python discovery | PASS: 101 tests, one environment-only skip |
| focused image/security/license regressions | PASS: 17 tests |
| native Fedora ShellCheck validation | PASS: all repository shell scripts |
| installed-path systemd verification | PASS: corrected broker and Bunny user units inside beta image fixture |
| developer OCI/QCOW2 compose and `qemu-img check` | PASS |
| developer bootc-aware libguestfs inspection | PASS |
| developer QEMU/KVM/OVMF boot plus Bunny health service | PASS |
| beta OCI/QCOW2/raw compose | PASS after separate image-type invocation fix |
| beta `qemu-img` and bootc-aware libguestfs inspection | PASS |
| beta QEMU/KVM target plus Bunny health service | PASS |
| beta SPDX release-mode license scan | PASS: 6,077 records, 306 explicitly covered, 0 unresolved, 0 prohibited |
| beta Grype `--fail-on high --only-fixed` | FAIL: 59 findings (8 Critical, 28 High, 23 Medium) |
| live/recovery media, install, update/rollback/recovery, reproducibility, Secure Boot/LUKS/TPM, hardware | NOT RUN / BLOCKED |

The real image results close several implementation defects but do not change
the stable or Phase 7 `NO-GO` decision.

## 2026-07-29 Phase 7 test results

454 Phase 7 tests added, all passing on Windows 11 with Python 3.14.6.

| Suite | Tests | Result |
|---|---|---|
| `tests/oem` — profiles, overlays, qualification | 41 | PASS |
| `tests/factory` — finalisation and handoff refusal | 21 | PASS |
| `tests/identity` — device identity and attestation | 25 | PASS |
| `tests/enrolment` — tokens, messages, disclosure, states | 30 | PASS |
| `tests/policy` — typed domains and conflict precedence | 39 | PASS |
| `tests/fleet` — rings, remote boundary, roles, catalogue, audit | 81 | PASS |
| `tests/multitenancy` — cross-organisation isolation | 23 | PASS |
| `tests/sync` — envelope, keys, conflict, deletion, migration | 72 | PASS |
| `tests/cryptography` — crypto boundary and pairing | 27 | PASS |
| `tests/recovery` — sync account recovery | 19 | PASS |
| `tests/decommission` — retirement and lost-device response | 19 | PASS |
| `tests/airgap` — signed offline bundles | 19 | PASS |
| `tests/kiosk` — restricted and shared devices | 21 | PASS |
| `tests/pilot` — pilot ordering and readiness gating | 19 | PASS |

Aggregate: `python scripts/task.py test` now reports 557 tests PASS (1 skipped), plus 60 installer and 74 operations tests.

Gate results. `make` is unavailable on this Windows host, so each target's underlying command was executed directly and the Makefile wiring is unverified by execution:

| Command executed | Result |
|---|---|
| all 19 `gate-phase-7-source` components, in order | every one PASS |
| `python scripts/task.py phase7-audit` | PASS: 47 documents, 18 demonstrations, 11 schemas |
| `python scripts/phase7.py baseline` | PASS: 14 mandatory fields |
| `python scripts/phase7.py source-gate` | PASS |
| `python scripts/phase7.py fleet-simulation --devices 500` | PASS: 6-step rollout arithmetic, simulation only |
| `python scripts/phase7.py pilot-readiness` | exit 2, NO-GO: 8 of 11 entry gates unmet |
| `python scripts/phase7.py pilot-gate --kind oem` | exit 2, BLOCKED: 4 unmet gates |
| `python scripts/phase7.py pilot-gate --kind enterprise` | exit 2, BLOCKED |
| `python scripts/phase7.py pilot-gate --kind sync` | exit 2, BLOCKED |
| `make gate-phase-7` | not run; inherits `gate-stable-release`, which fails closed |

A test-discovery defect was fixed: `python scripts/task.py test` discovered with `-s tests` and no `-t`, placing `tests/` on `sys.path`, so once `tests/sync` and `tests/oem` existed they shadowed the real packages and five modules failed to import. The top-level directory is now the repository root, which also brought two previously undiscovered `tests/recovery` tests into the main suite; both pass.

These are source tests. They establish that the Phase 7 code refuses what it claims to refuse. They are not artifact, runtime, service, or physical-hardware evidence, and they do not change the stable `NO-GO`.

## 2026-07-29 runtime evidence on the Fedora WSL builder

The Fedora 44 WSL2 distro turned out to be a fully working builder — root, systemd, nested KVM, podman 5.8.4, image-builder 76.0.0, QEMU 10.2.2, syft, grype, guestfs-tools. Most of what was recorded as impossible was un-run.

| Command | Result |
|---|---|
| `scripts/task.py test` on Fedora 44, Python 3.14.3 | 671 pass, matching Windows |
| `shellcheck` over all 19 shell scripts | clean |
| `systemd-analyze verify` on every unit | parses; only uninstalled `/usr/libexec` warnings |
| `build-image.sh developer` | real 2.3 GB QCOW2 plus 2.0 GB OCI archive |
| `inspect-image.sh developer` | PASS: one root filesystem, one bootc state root, one deployment |
| `sbom.sh developer` | 30 MB CycloneDX, 60 MB SPDX, SHA256SUMS |
| `license-scan.py` | 6252 packages, 0 unresolved, no prohibited markers |
| `security-scan.sh developer` | **FAIL**: 95 fixable — 19 Critical, 43 High, 33 Medium |
| `vm-smoke.sh developer` | PASS: boot target reached, health check finished |
| `vm-rollback-test.sh` boot-parity | PASS: two images both boot healthy |
| `vm-network-capture.sh developer` | 4 external destinations, all NTP |
| two-build determinism | digests differ; contents identical, tar mtimes differ |

### A regression that only a real boot could find

The first freshly built image failed `vm-smoke`: `bunny-health-check.service` failed and `bunny-system-broker.service` crash-looped. Both traced to one cause introduced by the new two-socket support — systemd names an inherited descriptor after the socket unit when `FileDescriptorName=` is unset, and the new code rejected any name outside `{broker.sock, policy.sock}`. The broker raised at startup on every boot; the health check requires a responding broker socket, so it failed with it.

Every unit test passed, because they all used our own names. Fixed, a regression test added using the real systemd default name, rebuilt, and re-verified: `Finished bunny-health-check.service`.

This is the clearest argument in the repository for why source tests are not runtime evidence.

### Suite totals

671 main-suite tests (from 101 at the start of Phase 7), plus 60 installer and 105 operations tests. New this session: broker 41, settings 40, factory 58, cryptography 46.
