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

Update 2026-08-02 (first-login and chronyd product corrections): still
**NO-GO**, and the count is unchanged at **3 of 14** prerequisites.

Two confirmed product defects were corrected in the immutable image and the
full rebuild-and-requalify chain was run:

    Archive reproducibility   PASS  4 builds of Commit O, one digest, 17/17
    First-login (dsq-2)       PASS  60/60 boots, 20/20 second logins
    Software-TPM (tpmq-2)     PASS  35/35 boots across 7 cells
    BrlAPI (isq-2)            PASS  3/3 installs, 3 distinct keys

The gate ladder, by exact exit code:

    task.py validate / test / test-installer / test-phase5     0 0 0 0
    phase7.py source-gate                                      0
    reproducibility-gate                                       0
    tpm-qualification-gate (tpmq-1 / tpmq-2)                   0 / 0
    display-stack-matrix (dsq-1)                               0
    display-stack-evidence-gate                                0
    display-stack-reliability-gate                             2
    first-login-evidence-gate / reliability-gate (dsq-2)       0 / 0
    brlapi-installed-evidence-gate                             0
    gate-qualification-candidate                               2
    gate-stable-release                                        2
    gate-oem-pilot / enterprise-pilot / sync-pilot             2 / 2 / 2

`display-stack-reliability-gate` exits 2 by design: it reads dsq-1's evidence,
which measured the superseded b9c317d archive on which bunny-first-boot failed
60 of 60. That verdict is a statement about an archive this pass replaced and
must not change. The corrected archive's verdict is the dsq-2 gate, which
exits 0.

The eleven blocking prerequisites are unchanged and were never in this pass's
scope: vulnerability review, independent recovery media, the installation,
encryption, update and rollback matrices, physical hardware, accessibility
evidence, independent reviews, the second production signer, and protected
approvals. The candidate gate does not read the display-stack or first-login
categories at all, so correcting these defects could not have moved the count —
stated in advance, not discovered afterwards.

The gate additionally refuses the artifacts present: the builds in
`build/out/beta` are archive-only, which produced an OCI archive and no disk
image. An archive-only build is evidence for reproducibility comparison only.

Nothing in this repository may be described as release-qualified.
