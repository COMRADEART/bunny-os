# Bunny OS Phase 1 test report

Date: 2026-07-28  
Host: Windows, Python 3; no Linux systemd/container/KVM runtime

## Current test position — 2026-07-30 (CI portability repair)

Host: Windows 11, Python 3.14.6, plus Fedora Linux 44 on WSL2 for the checks
Windows cannot run. `shellcheck`, `podman`, `syft`, `grype` and `image-builder`
are unavailable on the Windows host and their checks report `SKIP` there; they
were run under Fedora and are recorded separately below.

| Command | Result |
|---|---|
| `python scripts/task.py validate` | **PASS** — 13 validators, 277 JSON documents, 35 schemas, 310 Python files, 25 shell scripts |
| `python scripts/task.py test` | **PASS** — **1,347 tests**, 4 skipped (was 1,150) |
| `python scripts/task.py test-installer` | **PASS** — 60 tests |
| `python scripts/task.py test-phase5` | **PASS** — 105 tests |
| `python scripts/task.py test-release-closure` | **PASS** — **707 tests** across 12 suites (was 510 across 11) |
| `python scripts/task.py phase7-audit` | **PASS** — 47 documents, 18 demonstrations, 11 schemas |
| `python scripts/phase7.py source-gate` | **PASS** |
| `python scripts/release.py validate-repository` | **exit 0** — 11 validators pass, 2 skip on this host |
| `python scripts/reachability.py verify-findings` | **exit 0** — 25 records, only `generatedAt` differs |

**1,512 distinct tests pass, 4 skipped**: 1,347 under `tests/`, plus 60 installer
and 105 phase-5 tests discovered separately. `test-release-closure` re-runs twelve
of the `tests/` directories — 707 tests — so it is a subset of the 1,347 rather
than an addition to it.

### The twelfth suite: `tests/portability`

197 tests added this pass, covering the defects that let CI report something
other than the truth.

| File | Tests | Covers |
|---|---|---|
| `test_display_path.py` | 13 | output inside the repository, in `/tmp`, in a Windows temporary directory, at a relative path, through a resolved symlink; a security-sensitive path still refused; record content unaffected by where it is written |
| `test_shellcheck_portability.py` | 11 | no `SC1091` suppression, no severity floor, nothing sources `/etc/os-release`, the `unknown` fallback, quoted values, the record stays parseable JSON |
| `test_commit_context.py` | 21 | local branch, detached exact commit, PR synthetic merge, PR head, evidence after candidate, wrong candidate, missing candidate, evidence bound to a merge ref |
| `test_cve_regeneration.py` | 27 | the one permitted difference; a changed carrier object, package, advisory, disposition or commit each fail; reorder tolerance; a nested change; the structured diff |
| `test_repository_validation.py` | 18 | all ten required validators reported; one failure does not implicate the other nine; session entries versus launchers; the machine-readable output |
| `test_gate_exit_codes.py` | 15 | a refusal accepted, an approval rejected, and a crash, traceback, missing file or odd status never mistaken for a refusal |
| `test_archive_only.py` | 21 | both protected gates refuse an archive-only artifact; the provenance writer refuses a record its artifacts contradict; an undeclared mode is unknown, not full |
| `test_hosted_import.py` | 31 | missing and reused run ids, source and base mismatch, a record edited in one place, a shared administrator boundary, an unsigned production claim |
| `test_dimension_collector.py` | 26 | all seventeen dimensions read from an OCI archive, whiteout semantics, setuid bits, capabilities, and an absent SELinux set reported as not-collected rather than matching |
| `test_comparison_assembly.py` | 15 | the reduced comparison form preserves equality exactly — one changed member among 20,000 is caught and named |

### One transient failure, observed once and not reproduced

`python scripts/task.py test` reported `FAILED (failures=1, errors=1, skipped=4)`
on one run. The output of that run was not retained, so which two tests failed is
not known. Eight subsequent runs of the same command, and a direct
`unittest discover` over the same tree, all reported `OK (skipped=4)` — nine
clean runs against one failure.

The failing run overlapped with a 71 MB write to the same disk from the
dimension collector in WSL, and several of these suites spawn subprocesses that
read and write under `build/out/`, so I/O contention is the plausible
explanation. It is not the established one: no evidence was captured.

Recorded rather than omitted, because a suite whose job is to fail closed is
exactly the kind that must not be quietly flaky. The lesson taken is to retain
the output of every run of this suite, not only the ones expected to fail.

### Checks that Windows cannot run, run under Fedora Linux 44 (WSL2)

| Check | Result |
|---|---|
| `shellcheck` over all 25 shell scripts | **PASS** — 0 findings, no suppression, ShellCheck 0.11.0 |
| `podman run fedora:44 ci-verify-units.sh` | **PASS** — 18 units verified in installed form, 1 skipped by record |
| `podman run fedora:44 ci-validate-desktop.sh` | **PASS** — 7 launchers and 2 session entries |
| `BUNNY_ARCHIVE_ONLY=1 build-image.sh beta` | **PASS** — OCI archive built and normalised, no qcow2, no raw, no ISO |
| Both protected gates against the archive-only artifact | **exit 2** — refused, naming what the build did not do |
| 17-dimension collection from the archive | 16 collected, `selinuxLabels` not collected |

### GitHub Actions

All 22 jobs across the three source workflows pass on `ubuntu-24.04`, and every
protected gate is verified as *refusing* rather than merely non-zero:

```text
source gate: passed as expected (exit 0)
reachability regeneration: passed as expected (exit 0)
qualification candidate gate: correctly refused (exit 2)
stable release gate: correctly refused (exit 2)
oem-pilot gate: correctly refused (exit 2)
enterprise-pilot gate: correctly refused (exit 2)
sync-pilot gate: correctly refused (exit 2)
signing roles: correctly refused (exit 2)
builder independence: correctly refused (exit 2)
hardware evidence validation: correctly refused (exit 2)
per-CVE disposition: correctly refused (exit 2)
CVE acquisition: correctly refused (exit 2)
symbol analysis: correctly refused (exit 2)
```

## Phase 1 test report (2026-07-28)

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

## Release blocker closure suites, 2026-07-30

Nine suites, 252 tests, all passing.

| Suite | Tests | Covers |
|---|---|---|
| `tests/security/` | 52 | vulnerability dispositions, the ten-question reachability review, plus the inherited security tests |
| `tests/licensing/` | 20 | licence decision, the seven-requirement gate, the repository's actual licence layout |
| `tests/reproducibility/` | 29 | four separated claims, independence dimensions, four comparison levels |
| `tests/signing/` | 29 | seven roles, namespace separation, key lifecycle, rotation overlap, the drill |
| `tests/recovery/` | 38 | recovery-media matrix and its runtime-only enforcement |
| `tests/release/` | 24 | the evidence model and its four forgery checks |
| `tests/hardware_evidence/` | 25 | redaction scanning and claim substantiation |
| `tests/accessibility_evidence/` | 12 | fourteen workflows, static-evidence refusal |
| `tests/pilot_gates/` | 23 | four separated gates and the CI closure assertion |

Run with `python scripts/task.py test-release-closure` or
`make test-release-closure`.

### The fourteen mandated adversarial cases

All are tested and all are refused.

| Case | Suite |
|---|---|
| forged evidence record | `tests/release/` - missing artifact, substituted content, and no-digest variants |
| stale evidence | `tests/release/` |
| evidence from the wrong commit | `tests/release/` |
| development key used as a production key | `tests/signing/` |
| wrong signing-role key | `tests/signing/` |
| unsigned licence approval | `tests/licensing/` |
| vulnerability severity reduction without review | `tests/security/` |
| fake physical-hardware report | `tests/hardware_evidence/` |
| self-review marked independent | `tests/release/` |
| same-host builds marked independent | `tests/reproducibility/` |
| recovery report without boot evidence | `tests/recovery/` |
| pilot approval without stable release | `tests/pilot_gates/` |
| OEM approval without hardware | `tests/pilot_gates/` |
| sync approval without cryptographic review | `tests/pilot_gates/` |

### Two defects the tests found in the code under test

Both were found by writing the test first and watching it fail for the wrong
reason.

1. **The serial-number heuristic matched RFC 3339 timestamps.** Every hardware
   report was rejected for carrying `2026-07-29T00` as an "asset tag". Fixed by
   exempting timestamp-shaped values and time fields.
2. **An absent qualification matrix reported `ok`.** An empty matrices document
   has no incomplete matrices, so the stable gate counted the requirement as
   satisfied. Fixed so an absent matrix blocks.

### Whole-repository totals

| Command | Tests | Result |
|---|---|---|
| `python scripts/task.py test` | 892 | PASS, 1 skipped |
| `python scripts/task.py test-installer` | 60 | PASS |
| `python scripts/task.py test-phase5` | 105 | PASS |
| `python scripts/task.py test-release-closure` | 252 | PASS |

## 2026-07-30 — SQLite determinism and comparison-mode tests

`tests/reproducibility/test_sqlite_determinism.py`, 24 cases. Every fixture is
built rather than recorded, so each one reproduces its defect exactly and a test
that stops failing is a test whose defect actually went away. Physical variance
is produced through SQLite's own behaviour — insertion order, page size, WAL
residue — rather than by editing bytes, because a hand-edited page proves the
parser wrong and nothing about the finaliser.

| Rejects | Case |
|---|---|
| logical equality treated as byte equality | identical rows, different physical layout, `LOGICALLY_IDENTICAL` and different digests |
| a mismatched SQLite version | finalisation refuses with both versions named |
| a changed schema hidden by canonicalisation | `schemaMatch` false, verdict `LOGICALLY_DIFFERENT` |
| a changed row hidden by canonicalisation | one row differs, survives VACUUM, is reported |
| content changed by finalisation | logical digest compared either side; a move is fatal |
| a corrupted database passing finalisation | refuses on both the malformed-image and failed-integrity paths |
| WAL or SHM residue | removed, and the database leaves WAL mode |
| a transaction living only in the WAL | checkpointed into the database, not deleted with the residue |
| non-idempotent finalisation | second run byte-identical |
| an unexpected schema | a missing required table refuses by name |
| an unsupported table type | a virtual table refuses, with the reason |
| a missing transaction history | refuses rather than finalising half |
| insertion-order variance | classified, not missed |
| page-size variance | header comparison reports it |
| freelist variance | measured |
| different content at identical size | caught by rows, not by size |
| type flattening | `NULL` and the empty string do not compare equal |
| a qualification comparison missing the SBOM | exit 2 |
| a qualification comparison missing normalisation | exit 2 |
| a qualification comparison missing the intended SELinux manifest | exit 2 |
| a diagnostic collection promoted to qualification | exit 2 |
| a complete qualification join | succeeds, `REPRODUCIBLE` |

### Two defects the tests found in the code under test

Again by writing the test first and watching it fail for the wrong reason.

1. **`selinuxLabels` could never be satisfied.** The dimension was left as the two
   nulls the archives honestly report, so a *complete* archive comparison still
   came out `NOT_COLLECTED` on it and therefore `INCONCLUSIVE` — a verdict no
   archive build could ever escape, for a subcheck that belongs to
   installed-system qualification. The dimension now carries the archive-stage
   subcheck; the composite still keeps the applied subcheck outstanding.
2. **The mtime sweep excluded `/run`.** Measured inside the retained base, `/run`
   is not a mount and is ordinary image content. Excluding it left exactly one
   entry in the artifact with a wall-clock mtime.

A third failure was a bad test rather than a bad guarantee: 64 zero bytes in a
`-wal` is a header SQLite discards, so the expected refusal never came. It was
replaced with the guarantee that matters — a transaction living only in the WAL
must end up in the database.

### Totals

| Command | Tests | Result |
|---|---|---|
| `python scripts/task.py test` | 1,431 | PASS, 8 skipped |
| `python scripts/task.py test-installer` | 60 | PASS |
| `python -m unittest discover -s tests/reproducibility -t .` | 115 | PASS |
