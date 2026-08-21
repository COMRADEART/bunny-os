# Phase 7 recovery qualification

**The defined journey: PASS.** For the first time in this project, a machine
that could not boot was brought back by a separately built recovery medium,
with every step measured. This qualifies exactly what
`RECOVERY_DEFINITION.md` defined beforehand, and nothing wider.

## The journey, as measured

| Step | Evidence |
| --- | --- |
| Machine cannot boot normally | the subject disk (`e906a48793d7` qcow2, sha `497add9a…`) with its BLS entry's kernel/initrd paths pointing at a nonexistent checksum dir reached **no boot target in 300 s** (`evidence/broken-boot.log`); the `options`/`ostree=` line untouched, so the repair could not crib from the corruption |
| Recovery media boots | the recovery qcow2 booted independently with the broken disk attached; the driver only runs once the recovery target is up (`evidence/recovery-session.log`) |
| User can inspect the installation | deployment `1804c600…` enumerated from the broken disk's own `/ostree`, with origin and os-release read |
| Recovery action taken | the BLS entry repaired **by deriving** the real kernel dir (`default-dd339603…`) from the broken disk's boot partition — nothing was stashed at breakage time, so nothing could be copied back |
| Outcome verified | the repaired disk boots to a healthy target on its own deployment, identified from the kernel's `ostree=` argument (`evidence/repaired-boot.log`) |

Graded fail-closed by `verdict.py` (`evidence/verdict.json`); the grader's ten
constructed-journey controls — including *a broken disk that boots anyway is
FAIL* — run in the certified suite
(`tests/release/test_recovery_verdict.py`).

## The medium's identity (§6)

| | |
| --- | --- |
| Role | recovery medium — its own artifact, not the installation ISO assumed sideways |
| Build commit | `b812e48e` |
| Creation method | `build/scripts/build-image.sh recovery` (podman + image-builder) |
| qcow2 sha256 | `40dd7d2d1bf6b69ca6199013641b08bbb04a53e94ad12f5c6496c99eb5a3e648` |
| Instrumented overlay sha256 | `ae2dfc92d8a51d5f…` — the driver-unit overlay actually booted; derivation script committed (`recover.sh`) |
| Boot environment | qemu q35 UEFI (OVMF), virtio disks, KVM |
| Signature | **NONE** — production signing is an external gate; this is engineering evidence for the journey, not release evidence for the medium |

## What is explicitly not claimed

* **Not disaster recovery.** No re-image, no restore-from-backup.
* **Not encrypted-installation recovery.** The subject disk is unencrypted;
  recovery of a LUKS installation needs the user's credential by design.
* **The interactive console was not driven.** `bunny-recovery` reads tty1 and
  demands a typed `YES`; the journey drove the documented operator steps via
  an injected unit and the record says so. The `recovery-ui` accessibility
  scenario stays NOT_RUN.
* **The 11-scenario recovery-media matrix does not flip.** Its rows
  (signature verification, encrypted access, safe graphics, diagnostics
  export…) are distinct claims, most still NOT_RUN; one journey does not
  complete a matrix. The `boots-independently` property is demonstrated
  here but the matrix row is left to a run of `vm-recovery-test.sh` under
  its own signature policy, which no unsigned medium can satisfy.

## Reproduce

`build-image.sh recovery` → `break-disk.sh` → `recover.sh` →
`verify-disk.sh` → `verdict.py`. Each refuses out-of-order execution.
