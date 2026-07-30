# Installation qualification report

Date: 2026-07-29  
Source commit: `79bb99ddb39d8a5dbc279629f43b23346fb0e5e8`  
Result: **NOT QUALIFIED** — 0 of 12 scenarios resolved, 0 failing, 12 not run.

Twelve disposable-disk installation scenarios, from an empty UEFI disk through interrupted installation and bootloader failure. Every scenario is destructive by nature and is run against disposable virtual disks.

## Scenarios

| Scenario | Outcome | Method | Evidence |
|---|---|---|---|
| `empty-uefi-disk` | NOT_RUN | source-inspection | — |
| `encrypted-uefi-installation` | NOT_RUN | source-inspection | — |
| `unencrypted-installation` | NOT_RUN | source-inspection | — |
| `offline-installation` | NOT_RUN | source-inspection | — |
| `multiple-disks` | NOT_RUN | source-inspection | — |
| `nvme-like-virtual-disk` | NOT_RUN | source-inspection | — |
| `sata-like-virtual-disk` | NOT_RUN | source-inspection | — |
| `existing-linux-replacement` | NOT_RUN | source-inspection | — |
| `supported-free-space-installation` | NOT_RUN | source-inspection | — |
| `interrupted-installation` | NOT_RUN | source-inspection | — |
| `bootloader-failure` | NOT_RUN | source-inspection | — |
| `recovery-installation` | NOT_RUN | source-inspection | — |

## Why these scenarios have not run

The installation harness (build/scripts/vm-install-smoke.sh) launches an interactive Anaconda session and requires an operator; it cannot be driven headlessly. No live ISO has been built either.

## Unresolved

Each of these is blocking. `NOT_RUN` is not a soft state:

- `empty-uefi-disk`
- `encrypted-uefi-installation`
- `unencrypted-installation`
- `offline-installation`
- `multiple-disks`
- `nvme-like-virtual-disk`
- `sata-like-virtual-disk`
- `existing-linux-replacement`
- `supported-free-space-installation`
- `interrupted-installation`
- `bootloader-failure`
- `recovery-installation`

## Standing note

No disk has been written. The installer source, its safety checks and its refusals are covered by 60 source tests that all pass; none of that is an installation.

## How to regenerate

```text
python scripts/release.py test-matrix --name installation
python scripts/write_qualification_reports.py
```

This report is generated from `operations/data/qualification-matrices.json`. Edit the
data, not the report: a report that disagrees with the evidence record is exactly what
the evidence model exists to prevent.
