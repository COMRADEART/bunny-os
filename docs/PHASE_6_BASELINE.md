# Phase 6 stable-publication baseline

Date: 2026-07-29  
Baseline commit: `d735a59300308394b573a8685f85b26174c236fa`  
Checkout branch: `feature/stable-qualification`  
Phase 6 disposition: **STOPPED AT MANDATORY PREFLIGHT — NO-GO**

## Stable release identity

| Required field | Verified value |
|---|---|
| Proposed stable version | unknown; no version has been approved |
| Release candidate | none; `docs/RELEASE_CANDIDATES.md` says the current candidate is none |
| Candidate source commit | none; the baseline commit identifies only the audited checkout |
| Soak duration | 0 hours; no candidate exists to soak |
| Stable publication date | none |
| Support start/end dates | none; `docs/SUPPORT_POLICY.md` explicitly leaves stable duration uncommitted |
| Maintenance/security-only/EOL dates | none |
| Stable branch or tag | none created; the checkout remains on `feature/stable-qualification` |

## Candidate, signing, and artifact status

| Evidence | Status |
|---|---|
| Clean immutable candidate checkout | BLOCKED: no approved RC version/source identity |
| Stable candidate manifest | ABSENT: `build/out/stable-rc/STABLE-CANDIDATE.json` does not exist |
| ISO, raw, and QCOW2 artifacts | ABSENT |
| Independent recovery ISO | ABSENT |
| Checksums and detached signatures | ABSENT |
| Release public key | ABSENT by design; `build/keys/README.md` contains policy only |
| Signing ceremony and protected approval | NOT RUN |
| Signature verification | BLOCKED: `BUNNY_STABLE_PUBLIC_KEY` is unset and no candidate exists |
| SBOM and package manifest | ABSENT |
| Provenance/attestation | ABSENT |
| Reproducible-build comparison | NOT RUN; `REPRODUCIBLE_BUILD_REPORT.md` is absent |
| License-compliance evidence | NOT RUN; `LICENSE_COMPLIANCE_REPORT.md` is absent |
| Malware scan | NOT RUN |

No private or public production key was generated, imported, rotated, revoked, or exposed during this preflight.

## Issue and risk status

The public GitHub issue query for `COMRADEART/bunny-os` returned zero open issues on 2026-07-29. That is not evidence of zero product defects: there is no qualified beta population, no Phase 4 report, no installed runtime evidence, and no candidate. The protected qualification record independently contains the blocker codes `unresolved-blocker`, `unsigned-artifact`, `missing-checksum`, `untested-release-rollback`, and `recovery-media-failure`.

| Severity | Open public GitHub issues | Qualification meaning |
|---|---:|---|
| Blocker | 0 | Does not clear the explicit `unresolved-blocker` qualification code or unknown runtime evidence |
| Critical | 0 | No installed/runtime evidence exists from which to establish absence |
| High | 0 | No beta or supported-path population exists from which to establish absence |
| Medium | 0 | No beta issue intake was operated |
| Low | 0 | No beta issue intake was operated |
| Enhancement | 0 | No beta issue intake was operated |

Accepted publication risks: **none**. Unknown evidence is blocking under `docs/STABLE_RELEASE_BLOCKERS.md` and has not been converted into accepted risk.

## Support matrix

| Area | Verified status |
|---|---|
| Stable recommended hardware | none |
| Stable supported hardware | none |
| Physical models qualified | zero; all hardware remains Untested |
| Supported architectures | none qualified for stable |
| Design target | Fedora 44, x86-64, UEFI only |
| Explicitly unsupported/unqualified | ARM64 Mode D, legacy BIOS, proprietary NVIDIA, OEM/unattended flows, and every untested device path |
| Supported install modes | none qualified; clean, encrypted, offline, alongside/free-space, and manual flows have no disposable-disk execution evidence |
| Upgrade/migration paths | none qualified |
| Downgrade policy | uncommitted beyond the designed previous-deployment rollback path |

## Mandatory qualification status

| Gate | Status | Blocking evidence |
|---|---|---|
| Phase 1–3 runtime and artifacts | BLOCKED | Static/source checks exist; image, VM, physical, Secure Boot, LUKS, SELinux, and hardware execution evidence is absent |
| Phase 4/public beta | BLOCKED | `PHASE_4_REPORT.md` and public-beta reports/artifacts are absent |
| Phase 5 stable qualification | NO-GO | `STABLE_RELEASE_GO_NO_GO.md` prohibits publication |
| Installation | NOT RUN | No production Anaconda adapter, destructive fixture result, or installed candidate |
| Updates | NOT RUN | No signed candidate update or production registry trust result |
| Rollback | NOT RUN | No installed candidate or release rollback result |
| Recovery | NOT RUN | No independently built and booted recovery ISO |
| Migration/data preservation | NOT RUN | No supported old-version installation or migration execution |
| Security | BLOCKED | Candidate review is blocked; signing, boot-chain, update, isolation, and runtime evidence is absent |
| Privacy | BLOCKED | Packet capture, cross-user runtime, and manual diagnostic-bundle review are absent |
| Accessibility | BLOCKED | Essential installed installer/login/update/rollback/recovery and assistive-technology flows are absent |
| Licensing | BLOCKED | No release SBOM or license-compliance report |
| Reproducibility | BLOCKED | No two-builder artifact comparison |
| Protected approvals | PENDING | Engineering, Release, Security, Privacy, Accessibility, Installer, Hardware, Documentation, and Maintenance are all pending |

## Executable preflight

- `C:\msys64\usr\bin\make.exe -s PYTHON=python gate-phase-5`: PASS as the inherited source/operations gate. It remains explicitly insufficient for candidate or stable approval. Host validation retained environment skips for unavailable JSON Schema, systemd/Fedora, and ShellCheck tooling.
- `C:\msys64\usr\bin\bash.exe build/scripts/build-stable-rc.sh`: exit 1, correctly refusing because no `BUNNY_RC_VERSION` identifies an approved new candidate.
- `python scripts/phase5.py candidate-gate --manifest build/out/stable-rc/STABLE-CANDIDATE.json`: exit 2, candidate manifest absent.
- `C:\msys64\usr\bin\make.exe -s PYTHON=python verify-stable-rc`: exit 2, release public key absent.
- `python scripts/phase5.py stable-gate --evidence operations/data/stable-qualification.json`: exit 2, `NO-GO`; five blocker codes and 31 missing evidence/approval fields.

## Publication blockers

1. The authoritative stable decision is `NO-GO` and stable publication is expressly prohibited.
2. Phase 4/public-beta qualification was never completed; its report and release evidence are absent.
3. There is no approved candidate version, immutable candidate manifest, signed tag, or protected release approval.
4. Stable artifacts, recovery media, checksums, signatures, public trust key, SBOM, package manifest, provenance, license report, malware scan, and reproducibility evidence are absent.
5. Installer, encryption, update, rollback, recovery, migration, multi-user, Bunny-disabled, local-only, privacy, accessibility, network, hardware, and long-duration runtime evidence is absent or blocked.
6. No hardware tier, architecture, install mode, support duration, maintenance cadence, or EOL timeline is approved.

## Preflight decision

Phase 6 may not proceed beyond this baseline. No `release/stable-1` or other stable branch was created; no tag, key, artifact, mirror, download, announcement, update, support promise, advisory, maintenance release, or EOL action was produced. Re-enter Phase 6 only after the Phase 5 evidence record changes to `GO`, the protected stable gate passes against a real signed candidate, and every non-waivable blocker above is closed with reviewable evidence.
