# Bunny OS Phase 7 report

## Result: source complete and tested; every pilot, OEM, enterprise, and hosted-sync gate remains blocked

- Date: 2026-07-29
- Baseline commit: `0691e0646db4d0cdd9a2ecadc3aca6dde3350287`
- Feature branch: `feature/oem-enterprise-and-sync`
- Stable Bunny OS version: **none.** `operations/data/stable-qualification.json` records `candidateVersion: null` and `STABLE_RELEASE_GO_NO_GO.md` records `NO-GO`.
- Phase 7 disposition: OEM, enterprise, and sync **design, schemas, validators, tests, and documentation** are complete. **No pilot may begin, no device may be manufactured, no fleet may be deployed, and no hosted sync service may launch.**

## What changed since the preflight stop

This report previously recorded a decision to implement nothing, on the grounds that the stable-release entry gate was unmet. That gate is still unmet and nothing below claims otherwise. The disposition has been revised for *source scope only*, matching how Phases 3 and 5 were actually delivered in this repository: design, schemas, validators, tests, and documentation land ahead of runtime evidence, and the gates that would authorise deployment fail closed rather than being softened.

Phase 3 shipped installer source with no Anaconda executor. Phase 5 shipped stable-qualification tooling while recording `NO-GO`. Phase 7 follows the same pattern.

## Architecture

```text
Bunny OS Device
  +-- enterprise/identity.py       locally generated, rotatable device identity
  +-- enterprise/attestation.py    optional, 8 software-state facts, nothing else
  +-- enterprise/enrolment.py      typed, single-use, replay-protected enrolment
  +-- enterprise/policy.py         15 typed operations, 12 safety invariants
  +-- enterprise/conflict.py       fixed 5-layer precedence with explanations
  +-- enterprise/remote.py         closed 14-operation boundary, 5 wipe scopes
  +-- enterprise/fleet.py          groups, rings, operational update states
  +-- enterprise/catalogue.py      organisation catalogue, signature mandatory
  +-- enterprise/health.py         10 categorical fields, nothing behavioural
  +-- enterprise/audit.py          per-organisation hash chain
  +-- enterprise/roles.py          7 roles, step-up auth, no user-content view
  +-- enterprise/tenancy.py        required tenant scope, 11 resource families
  +-- enterprise/airgap.py         signed offline bundles, monotonic sequence
  +-- enterprise/kiosk.py          restricted profiles that cannot weaken security
  +-- enterprise/decommission.py   6 scenarios with required action sets
  +-- enterprise/pilot.py          ordered pilots, operational criteria only
  +-- sync/                        optional end-to-end encrypted sync client
  +-- oem/                         OEM profiles, overlays, factory finalisation

Separate trust domains, deliberately not in this repository:
  bunny-fleet-server, bunny-enrolment-service, bunny-enterprise-console
```

Management and sync are separate trust domains. An organisation controlling device policy gains no access to private synced content: memory exposure is a safety invariant that cannot be expressed as a policy at any enforcement level, and sync content is encrypted under keys neither an organisation nor an operator holds.

## Required architecture fields

| Field | Value |
|---|---|
| OEM architecture | Four programme levels; signed closed profiles; overlay destination and content allowlists; `bunny-oem` CLI |
| OEM profile schema version | 1 (`schemas/oem-profile.schema.json`) |
| Factory provisioning workflow | 11 stages; 22-check finalisation; `bunny-oem finalize` refuses handoff on residual state; executor absent, exits 78 |
| Device identity design | Locally generated 128-bit installation id plus TPM-backed or software-protected key; no hardware identifier as remote identity |
| Attestation design | Optional; exactly 8 software-state facts by exact-set equality; user content refused by name |
| Enrolment protocol version | 1 (`schemas/enrolment-message.schema.json`); 5 message types, 9 resumable states, 9 mandatory disclosures |
| Policy schema version | 1 (`schemas/device-policy.schema.json`); 15 domains, 15 typed operations, 12 safety invariants |
| Remote administration boundary | Closed 14 operations; no generic shell; shell-shaped names refused explicitly |
| Fleet update architecture | 5 rings layered above the existing 3-value channel; signature verification not configurable |
| Application deployment model | Organisation catalogue over project catalogue; signature `const: true`; permission ceiling per package format |
| Multi-tenant architecture | Required tenant scope, wildcard refused, per-organisation audit chains, 8 evidenced controls |
| Encrypted sync design | On-device AEAD before upload; versioned envelope; associated data binds object and version |
| Key hierarchy | Recovery secret → user root key → device wrapping keys and per-collection keys; HKDF-SHA256 with per-purpose labels |
| Pairing and recovery | Locally recomputed authenticator defeats server key substitution; 4 recovery methods, none server-only |
| Deletion semantics | 6 scopes with disclosed retention bounds; no instantaneous-deletion claim |
| Air-gapped management | 6-stage signed workflow; monotonic sequence; `fleet-` key namespace; no unsigned path |

## Exact validation commands and results

**`make` is not available on this Windows host.** As `README.md` already establishes, the repository-native entry point is `python scripts/task.py` on any development host, and `make` targets are for the documented Fedora 44 image-builder host. Every command below was executed directly. The Makefile targets that wrap them were written and their recipe syntax checked, but the `make` targets themselves were **not executed**, so their wiring is unverified by execution.

Run on Windows 11, Python 3.14.6, with `jsonschema` installed.

```text
python scripts/task.py validate            57 JSON documents, 32 schemas, 196 Python files  PASS
python scripts/task.py test                557 tests  PASS (1 skipped)
python scripts/task.py test-installer      60 tests   PASS
python scripts/task.py test-phase5         74 tests   PASS
python scripts/task.py phase7-audit        47 documents, 18 demonstrations, 11 schemas  PASS
python scripts/phase7.py baseline          14 mandatory fields  PASS
python scripts/task.py test-oem                    41  PASS
python scripts/task.py test-factory                21  PASS
python scripts/task.py test-device-identity        25  PASS
python scripts/task.py test-enrolment              30  PASS
python scripts/task.py test-policy                 39  PASS
python scripts/task.py test-fleet                  81  PASS
python scripts/task.py test-multitenancy           23  PASS
python scripts/task.py test-sync                   72  PASS
python scripts/task.py test-sync-crypto            27  PASS
python scripts/task.py test-device-revocation      91  PASS
python scripts/task.py test-remote-wipe            81  PASS
python scripts/task.py test-airgap                 19  PASS
python scripts/task.py test-kiosk                  21  PASS
python scripts/task.py test-decommission           19  PASS
python scripts/task.py test-pilot                  19  PASS
python scripts/phase7.py source-gate               PASS
python oem/bin/bunny-oem validate-profile ...      PASS  (the build-oem-image inputs)
python oem/bin/bunny-oem validate-overlay ...      PASS
python scripts/phase7.py fleet-simulation --devices 500   6-step arithmetic; simulation only
python scripts/phase7.py pilot-readiness           exit 2, NO-GO, 8 unmet gates
python scripts/phase7.py pilot-gate --kind oem            exit 2, BLOCKED, 4 unmet gates
python scripts/phase7.py pilot-gate --kind enterprise     exit 2, BLOCKED
python scripts/phase7.py pilot-gate --kind sync           exit 2, BLOCKED
```

`gate-phase-7-source` was verified by running all 19 of its constituent commands in order; every one passed. The composed `make` target was not run.

Targets that cannot run on this host at all, for the reasons `KNOWN_LIMITATIONS.md` already records — no Podman, no unified `image-builder`, no Linux systemd, no QEMU/KVM:

```text
make build-oem-image            (FULL_GATE=1 image leg only; input validation ran and passed)
make gate-phase-7               inherits gate-stable-release, which fails closed
make gate-oem-pilot             wraps pilot-gate --kind oem, which returns 2
make gate-enterprise-pilot      wraps pilot-gate --kind enterprise, which returns 2
make gate-sync-pilot            wraps pilot-gate --kind sync, which returns 2
make reproducible-build-check   fails closed by design; needs two independent builders
make sbom / security-scan       need syft, grype, and an OCI archive
make malware-scan               fails closed by design
```

Phase 1–6 source suites named in the brief — `test-broker`, `test-shell`, `test-encryption`, `test-update-security`, `test-rollbacks`, `test-recovery`, `test-migrations`, `test-multi-user`, `test-bunny-disabled`, `test-local-only`, `test-privacy-regressions`, `test-accessibility-regressions` — all pass and are included in the 557-test main suite or the 74-test operations suite.

Phase 1–6 commands named in the brief that cannot run on this host remain unavailable for the reasons `KNOWN_LIMITATIONS.md` already records: no Podman, no unified `image-builder`, no Linux systemd, no QEMU/KVM. `make test-broker`, `test-shell`, `test-encryption`, `test-update-security`, `test-rollbacks`, `test-recovery`, `test-migrations`, `test-multi-user`, `test-bunny-disabled`, `test-local-only`, `test-privacy-regressions`, and `test-accessibility-regressions` all pass as source tests and are included in `make gate-phase-5`.

454 Phase 7 tests were added.

## A defect fixed while wiring the suite

`python scripts/task.py test` discovered with `-s tests` and no `-t`, which placed `tests/` on `sys.path`. Once `tests/sync/` and `tests/oem/` existed they shadowed the real `sync/` and `oem/` packages and five test modules failed to import. The top-level directory is now the repository root. This also brought two previously undiscovered tests in `tests/recovery` into the main suite; both pass.

## Security findings

`PHASE_7_SECURITY_REVIEW.md` records twelve separate assessments. No unresolved Blocker or Critical issue exists **in Phase 7 source**. Three real defects were found and fixed during implementation, each caught by a test rather than by inspection:

- The OEM signing-key namespace collision check was unreachable. Every valid key id begins with `oem-`, and the check compared the whole id against release prefixes, so it could never fire. It now compares the suffix, and `oem-bunny-os-release` is refused.
- `_require_package_list` was registered directly as a policy-domain validator despite taking two arguments, so every application allowlist or blocklist policy raised `TypeError` instead of validating.
- Two privacy refusals were preempted by a generic unknown-field check, so attempting to report user activity in a fleet update state, or to pass a provider credential in policy, produced "unknown field" instead of the specific privacy or credential refusal. The specific checks now run first.

Inherited, unresolved, and blocking: the five stable-release blocker codes, 31 missing evidence or approval entries, and 59 fixable vulnerability findings in the beta image dependency set including 8 Critical and 28 High, with no waiver.

## Privacy findings

`PHASE_7_PRIVACY_REVIEW.md` documents exactly what an organisation administrator can see: ten categorical fields, no free text, no counts, no durations. Sync metadata visible to an operator is documented rather than minimised away, and the design is explicitly not described as zero knowledge — `assert_no_zero_knowledge_claim` refuses text that would.

No behavioural analytics, advertising identifiers, engagement tracking, or data brokerage were added. Fleet groups cannot carry behavioural attributes, and pilots cannot adopt success criteria that measure people.

## OEM, fleet, and sync test results

| Area | Tests | Result |
|---|---|---|
| OEM profiles, overlays, qualification | 41 | PASS |
| Factory finalisation | 21 | PASS |
| Device identity and attestation | 25 | PASS |
| Enrolment | 30 | PASS |
| Policy and conflict | 39 | PASS |
| Fleet, remote boundary, roles, catalogue, audit | 81 | PASS |
| Multi-tenant isolation | 23 | PASS |
| Sync envelope, keys, conflict, deletion, migration | 72 | PASS |
| Sync cryptography boundary and pairing | 27 | PASS |
| Sync account recovery | 19 | PASS |
| Decommissioning | 19 | PASS |
| Air-gapped management | 19 | PASS |
| Kiosk and shared devices | 21 | PASS |
| Pilot readiness | 19 | PASS |

## Pilot readiness

**NO-GO.** Eight of eleven entry gates are unmet: stable release published, signed stable artifacts, reproducible build evidence, post-release security review, post-release privacy review, independent sync cryptography review, OEM recovery validation, and support capacity. See `PILOT_READINESS_REPORT.md`.

## Operational costs

Not estimated. No service has been operated, no infrastructure provisioned, and no cost incurred. The only verified quantities in this report are test, document, and schema counts. A cost model for a service that does not exist would be invented, so none is given.

## Maintenance requirements

One maintainer, no funded support rota, no second release signer, no hardware laboratory, no contracted security or accessibility auditor. The Phase 7 surface exceeds that capacity. A pilot requires additional maintainers or a reduced scope. See `SUSTAINABILITY_REPORT.md`.

## Remaining blockers

1. No published, signed stable release; five blocker codes and 31 missing evidence entries.
2. 59 fixable vulnerability findings including 8 Critical and 28 High, with no waiver.
3. No reproducibility evidence; a second independent builder comparison has never run.
4. `PHASE_4_REPORT.md`, `STABLE_PUBLICATION_REPORT.md`, `POST_RELEASE_SECURITY_REVIEW.md`, `POST_RELEASE_PRIVACY_REVIEW.md`, `POST_RELEASE_ACCESSIBILITY_REVIEW.md`, `STABLE_SUPPORT_MATRIX.md`, and `SECURITY_POLICY.md` do not exist.
5. The policy agent has no privileged transport. `auth.py` refuses UIDs below 1000 and requires an active logind session; a headless agent has neither.
6. The settings layer has no organisation scope, so resolved policy cannot yet be enforced on a running desktop.
7. No reviewed sync cryptography backend is installed and no independent cryptographic review has been commissioned.
8. No fleet server, enrolment service, or console exists. Nothing has been deployed, load-tested, or penetration-tested.
9. No physical hardware has been qualified, no recovery media booted, and no OEM image built.
10. Support capacity is unconfirmed.

## Recommendation for controlled pilots

Do not begin any pilot. Do not manufacture devices, deploy fleets, or launch a hosted sync service.

The Phase 7 design is complete, internally consistent, and covered by 454 tests that verify its refusals as thoroughly as its behaviour. It is not deployable, and the gates enforce that rather than merely describing it. The next useful work is not Phase 8: it is closing the stable-release blockers that every Phase 7 gate depends on. See `NEXT_PHASE.md`.

---

# Addendum, 2026-07-29: deferred capabilities implemented and runtime evidence produced

The report above stands. This addendum records what changed after it was written, and it changes the *evidence* position substantially while changing the *release* position not at all.

## The assumption that was wrong

"No Podman, no image-builder, no QEMU/KVM on this host" was true of the Windows host and false of the machine as a whole. A `FedoraLinux-44` WSL2 distro is a fully working builder: root, systemd, nested KVM, 22 cores, 921 GB free, podman 5.8.4, image-builder 76.0.0, QEMU 10.2.2, syft, grype, guestfs-tools, and a clean ext4 clone of this repository at `/root/bunny-os`.

Most of what was recorded as impossible was simply un-run.

## Four deferred capabilities, now implemented

| Capability | State |
|---|---|
| Policy agent privileged transport | Second socket `/run/bunny/policy.sock`, mode 0600, `LISTEN_FDNAMES`-disambiguated, `require_policy_identity` as a sibling of the untouched `require_local_user`, separate method table and rate limiter, peer-uid plus cgroup unit match |
| Settings organisation scope | Root-owned overlay, allowlist of manageable settings, `SettingLockedError`, `reset()` to the organisation value, `sync` and `enrolment` network kinds with explicit local-only decisions |
| Factory executor | `bunny-oem inspect --root` settles 17 of 22 checks by inspection; 5 report `UNKNOWN` and need signed live attestation, which cannot override an inspected result |
| Sync AEAD backend | AES-256-GCM with bound associated data, HKDF-SHA256, RFC 3394 key wrap, real round-trip and tamper tests; XChaCha20 refused rather than substituted; absent backend still refuses every operation |

## Runtime evidence produced

Real 2.3 GB QCOW2 built from a clean checkout. Image inspection passed. SBOM generated. Licence scan clean over 6,252 packages. Two real KVM boots reaching health markers. A quiet-boot packet capture. A two-build determinism comparison.

The three VM harnesses that previously exited 78 now do real work: `vm-rollback-test` has boot-parity and deployment-rollback modes, `vm-recovery-test` verifies the media signature then boots it independently with the installed disk read-only, and `vm-upgrade-test` runs the shipped manifest validator.

## Three findings worth stating plainly

**A regression I introduced, caught by a real boot.** The two-socket change rejected the descriptor name systemd actually assigns, so the broker crash-looped and the health check failed with it. Every unit test passed. Fixed, regression-tested against the real name, rebuilt, re-verified.

**The build is deterministic; the archive wrapper is not.** Two builds of one commit produced different digests. Every file inside both archives is byte-identical — `podman save` stamps tar mtimes with wall-clock time instead of `SOURCE_DATE_EPOCH`. See `REPRODUCIBLE_BUILD_REPORT.md`. This is still not the two-independent-builder evidence the production gate wants.

**The system is quiet but not silent.** A booted image contacts four Fedora-pool NTP servers before any user action. Not telemetry, but real third-party contact that the privacy model did not disclose. Now disclosed.

## Dual-track qualification

`operations/qualification.py` is untouched and still strict. A parallel development track records what was genuinely run, with checked provenance: claiming physical hardware requires a report in the empty `hardware-evidence.json`, and claiming a production key requires a ceremony that does not exist. Both claims therefore fail.

**8 of 25 rows now produced and passing**, against 3 before, with `security` recorded honestly as FAIL. `make gate-dev-qualification` reports NO-GO and names precisely which rows are missing and why.

## Phase 4 and Phase 6

Fourteen absent documents were written, including `PHASE_4_REPORT.md`, the four `PUBLIC_BETA_*` records, `SECURITY_POLICY.md`, `STABLE_PUBLICATION_REPORT.md`, the three `POST_RELEASE_*` reviews and `STABLE_SUPPORT_MATRIX.md`. Each defines a real process and states that the operation never happened.

`make gate-phase-4` now passes its document check for the first time and stops on evidence instead, which is the honest failure.

## What has not changed

`gate-stable-release` is still NO-GO. All three pilot gates are still BLOCKED. The five blocker codes stand. There is still no physical hardware, no independent review, no production key ceremony, no published release, and no human approvals — and none of those can be produced by running more tests.

The vulnerability position got worse rather than better under measurement: 95 fixable findings on the developer profile, 19 Critical and 43 High.

**Recommendation unchanged: do not begin any pilot, manufacture any device, deploy any fleet, or launch any hosted service.**
