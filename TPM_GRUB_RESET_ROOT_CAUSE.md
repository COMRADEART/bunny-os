<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Root cause: the "TPM GRUB reset"

## Statement

The reset that blocked TPM qualification is **shim's boot-option
restoration reboot**: a deliberate, one-time, spec-intended cold reset
issued by `\EFI\BOOT\fbx64.efi` (shim 16.1's fallback binary) after it
recreates the operating system's NVRAM boot entries — taken **only when a
TPM is exposed by firmware**, so that the restored entry boots with cleanly
measured PCRs instead of PCRs polluted by the restoration pass itself.

GRUB never ran in any failing boot. The name "TPM GRUB reset" survives in
this document's title only because that is what the symptom was called when
the investigation was commissioned.

The qualified artifact is not defective. The defect was in the
qualification harness, which (a) gave every run a fresh OVMF variable
store, forcing the restoration path on every single boot, and (b) passed
`-no-reboot` to QEMU, which converts the designed single reboot into a
terminated virtual machine. Fix classification: **Path A, harness-only**
(see `TPM_QUALIFICATION_REPORT.md`). No byte of the artifact changes.

## Confidence

```text
CONFIRMED
```

Every link in the causal chain is independently measured, and the chain has
no unobserved segment:

1. **The reset is guest-requested, not a fault.** QMP records
   `SHUTDOWN {"guest": true, "reason": "guest-reset"}`; the QEMU debug log
   (`-d cpu_reset,guest_errors`) shows no guest error and no triple fault;
   the resetting component prints its intent ("Reset System") before the
   event. (`TPMQ-20260801-crb-fresh-stop-001`, `TPMQ-20260801-tis-fresh-stop-001`)
2. **The dialog belongs to fbx64.efi and to nothing else.** A UTF-16LE
   string pass over every executable on the ESP finds "Boot Option
   Restoration", "Press any key to stop system reset" and "Reset System"
   in `EFI/BOOT/fbx64.efi` alone — not in shim proper, not in GRUB, not in
   mmx64.efi — together with the `FB_NO_REBOOT` variable name and the
   symbol `fallback_should_prefer_reset`. (boot-chain manifest;
   `extract_boot_chain.sh`)
3. **The source of shim 16.1 says exactly this.** `fallback.c` draws the
   5-second "Boot Option Restoration" countdown, prints "Reset System",
   and calls `RT->ResetSystem(EfiResetCold, …)` — on the branch taken when
   `fallback_should_prefer_reset()` succeeds, and that function
   (`tpm.c:438`) returns success precisely when the firmware exposes a
   TCG/TCG2 protocol, i.e. when a TPM is attached. `FB_NO_REBOOT=1` or an
   operator keypress selects direct boot instead. (fallback.c sha256
   `19f90462ce03…`, fetched from rhboot/shim tag 16.1)
4. **The trigger is the fresh variable store, and it is consumed by
   design.** The restoration writes the "Fedora" boot entry before
   resetting: reusing the variable store from a reset run boots with zero
   resets, straight to `graphical.target`
   (`TPMQ-20260801-crb-reuse-vars-001`; regression cells `crb-reused-cold`
   and `tis-reused-cold`, 5/5 each, 0 resets).
5. **Allowed to continue, the "failure" completes by itself.** With the
   reboot permitted, one reset occurs and the same cold boot proceeds
   restoration → reset → GRUB → kernel → initramfs → multi-user →
   graphical → health check. (`TPMQ-20260801-crb-fresh-continue-001`;
   regression cells `crb-fresh-cold` and `tis-fresh-cold`, 5/5 each,
   exactly 1 reset per boot)

## Required findings

| Question | Measured answer |
| --- | --- |
| Observed reset classification | `BOOTLOADER_REBOOT_COMMAND` — guest-requested cold reset from a loaded boot-chain executable, announced on the console before the QMP event |
| Minimal reproduction | qualified QCOW2 overlay + fresh copy of `OVMF_VARS_4M.qcow2` + swtpm TPM 2.0 on either interface + cold boot; reset ~7 s after firmware handoff |
| No-TPM control | same disk, same fresh variables: no restoration dialog, direct boot to `graphical.target` (`no-tpm-cold` 5/5) |
| CRB result | restoration dialog → 1 reset; with continuation, full boot (`crb-fresh-cold` 5/5, 1 reset each) |
| TIS result | identical to CRB (`tis-fresh-cold` 5/5, 1 reset each) — the interface model is irrelevant, only TPM presence matters |
| Fresh vs reused OVMF variables | fresh → exactly 1 reset; reused post-restoration → 0 resets (`crb-reused-cold`, `tis-reused-cold` 5/5 each) |
| Fresh vs reused TPM state | no effect in either direction; the branch tests protocol presence, not TPM contents |
| Firmware-only control | OVMF + swtpm with no disk: stable for the whole window, no reset (`fw-only-crb`, `fw-only-tis`) |
| Known-good-disk control | stock Fedora Cloud 44 disk (`Fedora-Cloud-Base-Generic-44-1.7.x86_64.qcow2`, sha256 `28680fe5b371a5a82ebf43a31926e086a168e59949d03969c5093e7071f90b7f`), same harness, diagnostic cells `fedora-*` — see `TPM_BOOT_REGRESSION_REPORT.md` for the measured counts |
| Last confirmed boot-chain stage in failing runs | `fbx64.efi` executing after `BdsDxe: starting Boot0002`; GRUB never entered |
| Component that issues the reset | `EFI/BOOT/fbx64.efi`, sha256 `ea9b772575900eeb526faef865ac18ecd2130711e4e9e42c974fb5d31f69927c`, from `shim-x64-16.1-5.x86_64` |

## Alternative hypotheses, rejected

* **A GRUB TPM-module defect.** GRUB never executed in any failing boot —
  the failing serial transcripts end before any GRUB output — and when GRUB
  does run (continuation, reused-variables, no-TPM), it boots the system
  with the TPM attached and its `tpm` verifier active. Rejected by the
  transcripts and the continuation runs.
* **An OVMF TCG2 defect or incapable firmware build.** The firmware-only
  control is stable with the TPM attached; and the reset branch is *taken
  because* OVMF exposes a working TCG2 protocol — a firmware that failed to
  expose it would have booted directly. Rejected by the firmware-only
  control and the mechanism itself.
* **A swtpm/libtpms fault or state corruption.** Both interfaces behave
  identically, swtpm logs show clean command traffic, fresh and reused TPM
  state behave identically, and the TPM keeps working through the completed
  boots. Rejected by the paired state cells.
* **A QEMU device-model or KVM fault.** No `guest_errors`, no triple
  fault, no KVM host-log faults; the reset is an orderly guest request; the
  same wiring completes full boots. Rejected by the traces.
* **Artifact corruption or a Bunny image defect.** The no-TPM control boots
  the identical bytes, and the TPM boots complete once the designed reboot
  is permitted. Rejected by those controls alone; the separately sourced
  Fedora disk is a corroborating diagnostic whose measured counts are in
  `TPM_BOOT_REGRESSION_REPORT.md`, not a load-bearing part of this
  rejection.

## Why the symptom was misattributed to GRUB

The failing screen is a full-screen blue dialog with a countdown; on the
graphical console it resembles a bootloader screen, and the earlier pass
recorded "resets at GRUB" from that resemblance. The serial evidence never
supported it. Two of this pass's adversarial checks exist so that this
specific mistake cannot recur: a reset claim without a QMP event in its
classification basis is refused, and "reached GRUB" can never be recorded
as boot success.

## Evidence

```text
qualification/tpm/evidence/TPMQ-20260801-crb-fresh-stop-001/   classification run (CRB)
qualification/tpm/evidence/TPMQ-20260801-tis-fresh-stop-001/   classification run (TIS)
qualification/tpm/evidence/TPMQ-20260801-crb-fresh-continue-001/  continuation proof
qualification/tpm/evidence/TPMQ-20260801-crb-reuse-vars-001/   variable-store consumption proof
qualification/tpm/evidence/TPMQ-20260801-fw-only-crb-002/      firmware-only control
qualification/tpm/evidence/swtpm-capabilities/                 TPM identity and PCR allocation
qualification/tpm/evidence/matrix-summary.json                 full occurrence counts
build/out/tpm/boot-chain/boot-chain-manifest.txt               ESP hashes and string ownership
docs/TPM_GRUB_RESET_BASELINE.md                                frozen starting state
```

The prior pass's `ISQ-20260801-tpm-present-001/-002` records remain in the
tree as invalidated harness evidence: their serial transcripts were correct,
their `-no-reboot` interpretation was not. They are superseded by the
`tpmq-1` scenario authority and must not be re-imported as TPM results.
