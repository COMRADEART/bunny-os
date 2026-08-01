<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# TPM firmware control report

Whether OVMF itself, with a TPM attached and no Bunny disk anywhere near
it, is stable. If the firmware reset on its own, the artifact could not be
the cause; if it is stable, the fault (or behaviour) lives in what the disk
brings.

## Configuration

Identical to the qualification runs in every respect except the disk:

```text
OVMF code:      OVMF_CODE_4M.qcow2  6551948da24a…
OVMF variables: fresh copy of OVMF_VARS_4M.qcow2  035317bb2923…
TPM backend:    swtpm 0.10.1 / libtpms 0.10.2, TPM 2.0, fresh state
Machine:        pc-q35-10.2, KVM, -cpu host
Network:        none (the first control run had a NIC, and the firmware
                spent the whole window PXE-booting — noisy but equally
                reset-free; subsequent runs remove the NIC)
Observation:    stop-on-reset instrumentation, stability expectation
```

## Questions and measured answers

| Question | Answer |
| --- | --- |
| Does OVMF initialise the TPM? | Yes. The TCG2 protocol is exposed to the boot chain — measured indirectly but decisively: shim's `fallback_should_prefer_reset()` finds the protocol on this firmware (that is what selects the reset branch in the disk runs), and the guest OS enumerates the TPM without error in every completed boot. |
| Does the blank boot path remain stable? | Yes. With no bootable target the firmware settles (or PXE-loops when a NIC exists) for the entire observation window: no reset, no shutdown, no panic, no watchdog. |
| Does querying the TPM cause a reset? | No. Firmware TPM initialisation and protocol exposure occur in every run; resets occur only when `fbx64.efi` runs from a disk. |
| Does a firmware-only reset ever occur? | No, in any firmware-only run, on either TPM interface. |

## Runs

| Run | Interface | Window | Guest resets | Result |
| --- | --- | --- | --- | --- |
| `TPMQ-20260801-fw-only-crb-001` | tpm-crb | 180 s (NIC present, PXE noise) | 0 | stability confirmed; scored INCONCLUSIVE by a pre-fix result rule, superseded by seq 2 |
| `TPMQ-20260801-fw-only-crb-002` | tpm-crb | 180 s | 0 | PASS |
| `fw-only-crb` matrix cell (3 runs) | tpm-crb | 180 s | 0 | PASS |
| `fw-only-tis` matrix cell (3 runs) | tpm-tis | 180 s | 0 | PASS |

## Conclusion

The firmware layer is exonerated as an autonomous reset source: OVMF with
this swtpm never resets on its own. Combined with the known-good-disk
control (a stock Fedora disk shows the same one-time restoration reset —
`TPM_BOOT_REGRESSION_REPORT.md`), the behaviour is located in the ESP
payload the disk supplies, and specifically in shim's fallback
(`TPM_GRUB_RESET_ROOT_CAUSE.md`). "OVMF TPM boot path" is qualifiable:
the firmware exposes a working TCG2 protocol that the boot chain consumes
correctly through completed boots.
