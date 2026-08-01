<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# TPM boot-reset investigation baseline

This is the measured starting state of the investigation into the reset that
occurs when the qualified Bunny OS disk is booted with a software TPM 2.0
attached. Every value below was collected on 2026-08-01 from the builder that
runs the qualification VMs (Fedora WSL2, `FedoraLinux-44`), or from the
committed evidence of the BrlAPI requalification pass.

One correction to the inherited symptom description is itself a baseline
fact, because it changes where the investigation must look:

> **The committed failing serial logs never show GRUB.** Both recorded
> `tpm-present` failures (`ISQ-20260801-tpm-present-001`, `-002`) contain, in
> full: OVMF's `BdsDxe: loading Boot0002 "UEFI Misc Device"`, then a
> full-screen dialog titled **"Boot Option Restoration"**, the line
> **"Press any key to stop system reset"**, a five-second countdown, and the
> line **"Reset System"**. The no-TPM control logs
> (`ISQ-20260801-tpm-absent-001`, `-002`) contain no such dialog and proceed
> from the same `Boot0002` line directly to `GRUB version 2.12`.
> The phrase "resets at GRUB" in earlier reports described the last screen an
> observer attributed to GRUB, not anything the serial evidence shows GRUB
> doing. The reset happens **before GRUB ever runs** in the failing boots.

## Artifact authority

| Item | Value |
| --- | --- |
| Archive target commit (Commit G) | `b9c317d35b85aa082904ecd40c4a54c81aded99a` |
| Raw OCI archive digest | `29e54aaf9dd1ecc60e263fed3e6e06226115b76033b3965bdcd062441bcc2f30` |
| QCOW2 artifact | `bunny-os-b9c317d35b85.qcow2` |
| QCOW2 SHA-256 (re-verified on disk 2026-08-01T20:18Z) | `0b7dd90d86f11c713246a0fd36e63b5d7dddcccad45de710239e5add28fab217` |
| Raw disk SHA-256 (re-verified on disk 2026-08-01T20:18Z) | `161cbb07ceaca38de331e2445f94ba0b737fa9f4c91567eaffb116a732ca9852` |
| Installer toolchain digest | `5ea15dda4031b33844004a862a46c32c7fcebcf1086df1487d648952b0b56c80` (`build/installer/toolchain.lock.json`) |
| Installed-system delta target (Commit I) | `3bbb0c54d3cd2027b0db97228929a0aacca49b01` |
| Installed-system evidence (Commit J) | `5e9e279ac29db89b8bb9b78ef98980e5622f29aa` |

## Virtualisation stack

| Item | Value |
| --- | --- |
| QEMU | `QEMU emulator version 10.2.2 (qemu-10.2.2-1.fc44)`, package `qemu-system-x86-core-10.2.2-1.fc44.x86_64` |
| QEMU binary SHA-256 | `27cd395848940fc6482256d85096fc64bc4fe3f3e909824d51c202f8314cd9e9` (`/usr/sbin/qemu-system-x86_64`) |
| Machine type used by prior evidence | `q35,accel=kvm` (alias; resolves to `pc-q35-10.2` in this QEMU) |
| Machine type pinned for this investigation | `pc-q35-10.2` |
| Acceleration | KVM (`/dev/kvm` present; nested under WSL2 kernel `6.18.33.2-microsoft-standard-WSL2`) |
| CPU model | `-cpu host` on Intel(R) Core(TM) Ultra 9 185H |
| OVMF package | `edk2-ovmf-20260508-6.fc44.noarch` |
| OVMF code image | `/usr/share/edk2/ovmf/OVMF_CODE_4M.qcow2`, SHA-256 `6551948da24a02553476c1c1edccb0bb92a57dce9d722d7b396ac14547e6d9af` |
| OVMF variable template | `/usr/share/edk2/ovmf/OVMF_VARS_4M.qcow2`, SHA-256 `035317bb2923a13c1dc57373d608521cc3a486f1e3119016727d54baccc6e8bb` |
| OVMF secboot code image (unused by prior TPM evidence) | SHA-256 `377708ac44c12b22e28840e8e879fdfff5f42dcc8de0be9c91508881f72854a2` |
| swtpm | `0.10.1`, package `swtpm-0.10.1-3.fc44.x86_64`, binary SHA-256 `32c411b8d1b269ca6b5ae922e84459dec5669dc96ca17bb5cf8119f830ab7ce0` |
| libtpms | `libtpms-0.10.2-3.fc44.x86_64` |
| TPM backend | `swtpm socket --tpm2 --ctrl type=unixio` (TPM 2.0; fresh state directory per run) |
| TPM device model in recorded failures | `tpm-crb` (both recorded runs) |
| TPM device model in unrecorded observation | `tpm-tis` (one observation noted in `run_scenario.py` comments; no committed record) |
| Secure Boot state | disabled (non-secboot `OVMF_CODE_4M.qcow2`; no keys enrolled) |
| SMM state | not enabled (no `smm=on` machine option; firmware build does not require SMM) |

## Boot chain inside the qualified image

| Item | Value |
| --- | --- |
| GRUB | `grub2-efi-x64-2.12-60.fc44.x86_64`, `grub2-common-2.12-60.fc44.noarch` |
| shim | `shim-x64-16.1-5.x86_64` |
| Kernel | `kernel-7.1.5-201.fc44.x86_64` |
| Bootloader management | bootupd `0.2.35-1.fc44`, bootupd-managed GRUB2 with BLS entries |
| Partitioning | GPT: ESP + boot + root (image-builder bootc default, ext4) |
| Firmware boot path in all recorded runs | `Boot0002 "UEFI Misc Device"` — the removable-media path of the virtio disk, because every run starts from a fresh copy of the OVMF variable template, which contains no OS boot entry |

Package identities were read from the qualified container image
(`podman run` of the loaded `bunny-os-beta` image, whose root filesystem is
the qualified archive's by construction). The EFI executables on the ESP of
the disk artifact are hashed during Stage 5 of the investigation, not here.

## Reproduction state at baseline

| Cell | Count | Result |
| --- | --- | --- |
| TPM CRB attached, fresh OVMF vars, fresh TPM state, cold boot | 2 recorded (`ISQ-20260801-tpm-present-001`, `-002`) | 2/2 reset after "Boot Option Restoration"; GRUB never reached |
| TPM TIS attached | 1 unrecorded observation | reset/blank after firmware handoff; needs recorded reproduction |
| No TPM (control), same disk, fresh OVMF vars, cold boot | 2 recorded (`ISQ-20260801-tpm-absent-001`, `-002`) | 2/2 PASS to `graphical.target`; no restoration dialog; GRUB reached directly |

Prior-evidence caveats this investigation must repair, all inherited from the
installed-system harness (`run_scenario.py`):

* `-no-reboot` was set, so the first guest-initiated reset terminated QEMU;
  nothing after the first reset was ever observed.
* swtpm stdout/stderr were discarded (`--log file=` was captured, at level 1).
* No QMP event stream was captured; there is no machine classification of the
  reset, only the serial text.
* The QEMU machine type was the floating `q35` alias.

## Working hypothesis at baseline (unproven)

The dialog text matches the boot-option-restoration behaviour of shim's
`fallback.efi` (shim 16.1 is in the image): when a disk is booted through the
removable path and NVRAM lacks the OS boot entry, fallback recreates the
entries from `BOOTX64.CSV`; with a TPM present it then deliberately resets
the platform so the restored entry boots with cleanly-measured PCRs, and
without a TPM it chainloads directly. This fits every recorded observation —
including the no-TPM control's silent direct boot — but it is a hypothesis.
Stages 3–5 must (a) classify the reset from QMP events rather than screen
text, (b) prove which executable issues the reset, and (c) show what a boot
that is allowed to continue past the reset actually does.

## Investigation authority

`qualification/tpm/evidence-context.json` binds every evidence record of this
investigation to the digests above. A record naming any other disk, firmware
image, emulator build or scenario version is stale and must be refused by the
importer and the gates.
