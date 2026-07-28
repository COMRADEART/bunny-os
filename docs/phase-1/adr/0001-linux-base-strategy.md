# ADR 0001 — Linux base strategy

**Status:** Accepted, amended · **Date:** 2026-07-26 · **Spec:** §20.1–20.2

## Context
Phase 0 §18 already rejected package-archive derivatives and decided the *pattern*: an image-based atomic variant on an existing base, with Flathub as the app layer. The base itself was deferred to Phase 1/2. The Phase 1 brief re-poses the full option set (Ubuntu Minimal, Debian, derivatives); that is conflict C-2 (§2.4), and this ADR evaluates only within the settled pattern.

## Decision
- **Preview target:** Fedora Workstation 44, x86-64, systemd, SELinux, cgroup v2, user namespaces enabled. Ship as the package plus a self-contained tarball—explicitly not as a Flatpak. Fedora 45 remains non-blocking development CI until GA and full requalification.
- **Second Linux tuple:** Ubuntu 26.04 LTS, x86-64, only after a separate AppArmor profile/packaging milestone and a full tuple rerun. Fedora results do not qualify Ubuntu.
- **Bunny OS experiment:** one non-public bootc base stream only. Public images and an NVIDIA stream are deferred until the operational gates in §33 and P17/P18/P25 pass.

## Alternatives
- *Debian or Ubuntu package-archive derivative* — rejected by Phase 0 on derivative maintenance economics.
- *openSUSE Aeon / MicroOS* — genuinely attractive for its image/rollback model. Rejected for the first experiment because the selected Fedora bootc path minimizes variance. Current bootc already exposes a TPM2-LUKS installation path; Bunny validates it rather than copying a custom FDE design (§20.1, P25).
- *NixOS* — excellent reproducibility, but the app-layer story and contributor pool do not fit a one-maintainer project.
- *Waiting for a bootc-native Fedora Silverblue* — rejected: it lands late 2026 at the earliest, while building on `fedora-bootc` base images directly is available now.

## Consequences
Bunny does not maintain a public OS image in the preview. A later image program maintains an image layer, not a distribution, inherits Flathub, begins x86-64, and gates ARM64 separately (ADR 0017). CI and signing operations then become load-bearing and require more than one release-authorized maintainer.

## Risks
Fedora's bootc coordinating body dissolves after F45; if a permanent SIG does not materialise, base-image maintenance ownership is unclear. The Universal Blue economic model depends on free *public* container hosting; a private or paid channel re-prices materially (§20.3, R-7).

## Validation required
P17, P18, and P25. Any signing/freshness failure defers public distribution; documenting a hole is not completion.

## Phase 0 principles satisfied
C15 (own the narrow waist, rent the base), C6 (transactional rollback), D2 (no kernel fork), §18 platform sequence, §20 scope boundaries.
