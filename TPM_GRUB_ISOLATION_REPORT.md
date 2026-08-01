<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# TPM GRUB isolation report

What GRUB actually is on the qualified disk, what it does in the failing
and passing boots, and why it is exonerated. Extraction is read-only from
the pinned artifact (digest asserted first) by
`qualification/tpm/scripts/extract_boot_chain.sh`; the full manifest is
`build/out/tpm/boot-chain/boot-chain-manifest.txt`.

## The EFI executable sequence

Fresh-variable boots take the removable path; the sequence and hashes:

| Stage | File | SHA-256 |
| --- | --- | --- |
| firmware | OVMF (`OVMF_CODE_4M.qcow2`) | `6551948da24a02553476c1c1edccb0bb92a57dce9d722d7b396ac14547e6d9af` |
| 1 | `EFI/BOOT/BOOTX64.EFI` (shim 16.1) | `571ea56b855dcf73bec6acb63c5ded44c2a191138bca0d8cfa5aa93f60f46fff` |
| 2 (no valid OS boot entry) | `EFI/BOOT/fbx64.efi` (shim fallback) | `ea9b772575900eeb526faef865ac18ecd2130711e4e9e42c974fb5d31f69927c` |
| — with TPM | **cold reset here; GRUB never runs** | |
| — without TPM / after restoration | `EFI/fedora/shimx64.efi` (== BOOTX64.EFI byte-identical) | `571ea56b…` |
| 3 | `EFI/fedora/grubx64.efi` (GRUB 2.12, Fedora build) | `17b01e21459a592a097c1b4ffd6f69bf394e8713800721c0911d7713cf7d7773` |
| aux | `EFI/fedora/mmx64.efi` (MokManager) | `f8af592759c8ab33b69c4b0e772da5a8e2aa6d09c7dbd5e24c62c89fa5fdbd05` |

Restoration data: `EFI/fedora/BOOTX64.CSV` (`282a3b28…`), UTF-16, one row —
`shimx64.efi,Fedora,,This is the boot entry for Fedora`.

## GRUB configuration and environment

| Item | Value |
| --- | --- |
| ESP stub `EFI/fedora/grub.cfg` | `713311575e97fe8dadac271459455ea1a23df5b11189f7ab3c2d836c37dc01ce` — pure prefix discovery: `search --label boot`/`bootuuid.cfg`, then `configfile $prefix/grub.cfg`; no TPM commands |
| `EFI/fedora/bootuuid.cfg` | `c63b748c3c70f4ac3bf98c70e110fcaffccf663166dd8e92c60163bbb00db744` |
| Boot partition `grub2/grub.cfg` | `4ce37c9435a99e716d02a842715ee6e74eb596cff9da45f56a4e3cf541a5aa56` — BLS-driven (`blscfg`), bootupd-managed |
| `grub2/grubenv` | `f64122858064885ef0733e42c6a3d2d3fd642671f714db0d974b880c0f087430` |
| GRUB platform / prefix | x86_64-efi; prefix resolved by label/UUID search as above |
| TPM-related content in `grubx64.efi` | the Fedora build's `tpm` verifier (`grub_tpm_measure`, `grub_tpm2_log_event`, `commands/efi/tpm.c`, `tpm_fail_fatal`) is compiled in |
| cryptodisk/LUKS modules | present in the build (`cryptodisk`, `luks`, `luks2` strings); not exercised by these unencrypted boots |
| shim-lock | present (`shim_lock` in the build) |
| measured-boot commands in configuration | none — measurement is the built-in verifier, no explicit `tpm` module loads or config commands exist |

## Why GRUB is exonerated

1. **GRUB never ran in a failing boot.** Every failing serial transcript
   ends inside `fbx64.efi`'s dialog, before any GRUB output. There is no
   last-successful-GRUB-command to record, because there was no first one.
2. **The dialog strings do not exist in GRUB.** The UTF-16LE string pass
   locates "Boot Option Restoration" / "Press any key to stop system
   reset" / "Reset System" in `fbx64.efi` only; `grubx64.efi` contains
   none of them in either encoding.
3. **When GRUB does run with the TPM attached, it completes.** Across
   thirty-plus TPM-attached boots — the continuation run, the
   reused-variable cells, the state-combination cells and the regression
   cells — GRUB loads the BLS entry and the system reaches
   `graphical.target` with the TPM present and enumerated. No GRUB TPM
   error string (`tpm_fail_fatal`, `TPM unavailable`, `Cannot open TPM
   protocol`, `unknown TPM error`) appears in any transcript.

   Stated precisely, because the difference matters: this shows GRUB's TPM
   path does not *fail*. It does not independently prove measurements were
   written, because no PCR values were read back before and after. That
   check would need an in-guest agent this pass deliberately did not add,
   and no product feature consumes a measurement today, so no claim here
   rests on it.

Command-by-command GRUB stepping and module-by-module load tests were
therefore unnecessary: the failing boots never reach GRUB (nothing to
step), and the passing boots exercise the whole GRUB TPM path end-to-end
25+ times. Disabling TPM measurement in GRUB was never tested as a fix,
because the evidence shows GRUB's measurement is not involved in the reset.

## Diagnostic path variants

| Path | Result |
| --- | --- |
| OVMF → BOOTX64.EFI (shim) → fbx64.efi, TPM present | reset (the finding) |
| OVMF → BOOTX64.EFI (shim) → fbx64.efi, no TPM | direct chainload, full boot |
| OVMF → NVRAM "Fedora" entry → shimx64.efi → grubx64.efi (restored variables), TPM present | full boot, 0 resets |
| OVMF → firmware only, TPM present | stable, no reset |
