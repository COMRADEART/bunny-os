<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# TPM reset classification report

What "reset" turned out to mean, decided from instrumentation rather than
from a screen. Scenario authority: `tpmq-1`
(`qualification/tpm/evidence-context.json`, Commit K). The instrument is
`qualification/tpm/scripts/run_tpm_experiment.py`; every run captures the
QMP event stream with host timestamps (`qmp-events.jsonl`), the QEMU debug
log (`-D`, `-d cpu_reset,guest_errors`, `int` on request with out-of-git
retention), the serial transcript, swtpm's log/stdout/stderr, screendumps at
each boot-chain stage and after any terminal event, the host kernel log
tail, and before/after digests of every writable input.

## The classification

```text
BOOTLOADER_REBOOT_COMMAND
```

For the reproduction cell (qualified disk, fresh OVMF variables, swtpm
attached, cold boot, `-no-reboot -no-shutdown`), on both TPM interfaces:

```text
QMP:    SHUTDOWN {"guest": true, "reason": "guest-reset"}   (~7 s after handoff)
        STOP                                                 (VM frozen post-event)
serial: BdsDxe: starting Boot0002 "UEFI Misc Device"
        "Boot Option Restoration" dialog
        "Press any key to stop system reset"
        five-second countdown
        "Reset System"
debug:  no guest_errors, no triple fault
host:   no KVM faults
```

The classification is mechanical: a guest-requested reset (QMP reason
`guest-reset`), issued after a boot option was started, by a component that
printed its intent on the console before resetting. The issuing binary is
identified by the executable-isolation evidence
(`TPM_GRUB_ISOLATION_REPORT.md`), not by the event stream: it is
`EFI/BOOT/fbx64.efi`, shim 16.1's fallback, whose source takes exactly this
path when a TPM is present (`TPM_GRUB_RESET_ROOT_CAUSE.md`).

Classifications that were considered and are excluded by the same evidence:

| Candidate | Excluded by |
| --- | --- |
| `FIRMWARE_REQUESTED_RESET` | a boot option was started before the reset; the firmware-only control never resets |
| `GUEST_TRIPLE_FAULT` | no fault in `-d cpu_reset,guest_errors`; orderly QMP `guest-reset` with printed intent |
| `WATCHDOG_RESET` | no QMP WATCHDOG event; no watchdog device attached |
| `QEMU_DEVICE_RESET` | no host-initiated RESET reason in any reproduction run |
| `HOST_TERMINATED` | QEMU alive and frozen after the event (`-no-shutdown`), post-event screendump taken |
| `HARNESS_TIMEOUT` | the event precedes the deadline by minutes |
| `UNKNOWN` | nothing about the event is unexplained |

## Classification runs

| Run | Interface | Result |
| --- | --- | --- |
| `TPMQ-20260801-crb-fresh-stop-001` | tpm-crb | 1 guest reset, classified as above |
| `TPMQ-20260801-tis-fresh-stop-001` | tpm-tis | 1 guest reset, identical signature |
| `crb-fresh-repro-stop` cell (3 runs) | tpm-crb | reproduction under the frozen matrix |
| `tis-fresh-repro-stop` cell (3 runs) | tpm-tis | reproduction under the frozen matrix |

The full occurrence counts for every cell live in
`qualification/tpm/evidence/matrix-summary.json` and
`TPM_BOOT_REGRESSION_REPORT.md`.

## What the prior evidence got wrong, and the guard against recurrence

The prior harness (`run_scenario.py`, scenario set `isq-1`) ran with
`-no-reboot` and no QMP event capture. Under `-no-reboot`, a guest reset
terminates QEMU: the one deliberate reboot in the boot design was recorded
as a dead guest, and the graphical dialog was misread as GRUB. The
`ISQ-20260801-tpm-present-*` records stay in the tree as invalidated
harness evidence under their original ids.

Two adversarial checks now make that mistake structurally unrecordable
(`tests/tpm/test_adversarial.py`): a reset claim whose classification basis
quotes no QMP event is refused, and `HOST_TERMINATED`/`HARNESS_TIMEOUT`
records claiming guest resets are refused.
