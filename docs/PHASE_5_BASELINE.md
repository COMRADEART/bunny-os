# Phase 5 stable-qualification baseline

Date: 2026-07-29  
Baseline commit: `2b2d2d08873873d469b16c64aa87516e94edb513`  
Feature branch: `feature/stable-qualification`

## Public-beta evidence inventory

| Required field | Verified value |
|---|---|
| Current beta version | unknown; no Phase 4 report, public-beta manifest, or image exists |
| Beta duration | unknown |
| Number of releases | unknown; no release ledger or signed beta artifact was supplied |
| Number of beta installations | unknown |
| Open issues by severity | Blocker unknown; Critical unknown; High unknown; Medium unknown; Low unknown; Enhancement unknown |
| Installation failures | unknown; no installer execution records |
| Boot failures | unknown; no boot records |
| Update failures | unknown; no beta update records |
| Rollback failures | unknown; no rollback records |
| Recovery failures | unknown; no independently booted recovery records |
| Crash categories | unknown; no crash summaries supplied |
| Hardware coverage | zero physically validated models in repository evidence; all named hardware remains untested |
| Unsupported hardware | legacy BIOS and ARM64 are explicitly unsupported by the current x86-64 UEFI source design; proprietary NVIDIA remains unqualified |
| Security findings | inherited image, signing, installer-adapter, recovery, update, SELinux, Secure Boot, and runtime blockers remain open |
| Privacy findings | source defaults are privacy-preserving; network, bundle, crash-upload, and cross-user runtime tests are not run |
| Accessibility findings | static source checks pass; installer, recovery, login, screen-reader, scaling, contrast, and physical assistive workflows are untested |
| Performance regressions | unknown; only deterministic host microbenchmarks exist |
| Documentation gaps | Phase 4/public-beta evidence, release-specific recovery instructions, tested hardware list, and verified stable requirements are absent |

## Preflight result

Phase 1–3 static gates and the original 24-check architecture verifier pass. `gate-phase-4` and `gate-public-beta` did not exist at baseline. The required Phase 4/public-beta reports are absent. `build/out` contains no public-beta media; a build attempt stopped on missing Podman and an install-VM attempt stopped on missing QEMU. Therefore clean, encrypted, offline, upgrade, rollback, recovery, Bunny-disabled, local-only, multi-user, application, and diagnostic-export executions were not available.

## Stable-release blockers

There is no qualified public-beta input, stable candidate, signed artifact, checksum set, SBOM, provenance, reproducible-build comparison, migration evidence, tested rollback, independent recovery media, physical hardware evidence, multi-day soak, runtime accessibility evidence, or protected approval. Stable publication is prohibited. The current recommendation is `NO-GO`.
