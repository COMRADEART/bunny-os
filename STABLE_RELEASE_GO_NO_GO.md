# Bunny OS stable release go/no-go

Date: 2026-07-29  
Proposed stable version: unknown  
Release candidate: none  
Proposed date: none  
Candidate soak duration: 0 completed hours  
Recommendation: **NO-GO**

Supported architectures: none qualified; source target x86-64 UEFI only. Supported installation modes and hardware tiers: none qualified. Installation, encryption, Secure Boot, update, rollback, recovery, migration, multi-user, local-only, Bunny-disabled, application, hardware, power, performance, privacy runtime, accessibility runtime, security runtime, soak, signing, reproducibility, SBOM, provenance, license, and malware results are absent or blocked.

Open issue counts and accepted risks are unknown because no public-beta operations dataset exists. Known source blockers are not accepted for stable release. Maintenance readiness is incomplete and all nine approvals are pending.

Stable publication is prohibited. `GO` is allowed only after every automated requirement passes, every approval is recorded, no stable blocker exists, and the report is regenerated for an immutable signed candidate.

Update 2026-08-01 (TPM boot-reset investigation): the software-TPM boot
finding that previously read "resets at GRUB" is root-caused (CONFIRMED,
harness-side; `TPM_GRUB_RESET_ROOT_CAUSE.md`) and the software-TPM
regression matrix passes under the `tpmq-1` authority. This closes one
measured VM finding and changes nothing above: physical TPM, Secure Boot,
encryption, hardware, reviews and signing are untouched, and the
recommendation remains **NO-GO**.
