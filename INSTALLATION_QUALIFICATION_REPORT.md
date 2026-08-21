# Installation qualification report

Date: 2026-08-18T16:22:03Z  
Candidate commit: `79bb99ddb39d8a5dbc279629f43b23346fb0e5e8`  
Result: **NOT QUALIFIED** — 5 of 12 scenarios resolved, 0 failing, 7 not run.

Twelve disposable-disk installation scenarios, from an empty UEFI disk through interrupted installation and bootloader failure. Every scenario is destructive by nature and is run against disposable virtual disks.

## Scenarios

| Scenario | Outcome | Method | Evidence |
|---|---|---|---|
| `multiple-disks` | NOT_RUN | source-inspection | — |
| `nvme-like-virtual-disk` | NOT_RUN | source-inspection | — |
| `sata-like-virtual-disk` | NOT_RUN | source-inspection | — |
| `supported-free-space-installation` | NOT_RUN | source-inspection | — |
| `interrupted-installation` | NOT_RUN | source-inspection | — |
| `bootloader-failure` | NOT_RUN | source-inspection | — |
| `recovery-installation` | NOT_RUN | source-inspection | — |
| `existing-linux-replacement` | PASS | virtual-machine | `qualification/installed-system/evidence/installs/existing-data-protected.json` |
| `empty-uefi-disk` | PASS | virtual-machine | `qualification/installer-journeys/evidence/journey-a/installed.json` |
| `unencrypted-installation` | PASS | virtual-machine | `qualification/installer-journeys/evidence/journey-c/installed.json` |
| `offline-installation` | PASS | virtual-machine | `qualification/installer-journeys/evidence/journey-c-offline/installed.json` |
| `encrypted-uefi-installation` | PASS | virtual-machine | `qualification/installer-journeys/evidence/journey-a/installed.json` |

## Why these scenarios have not run

The unattended journey harness (build/scripts/vm-install-story.sh) now drives the shipped setup surface end to end and five installation scenarios carry virtual-machine evidence (qualification/installer-journeys/evidence). The remaining NOT_RUN scenarios each need a journey definition of their own (a second disk, an NVMe/SATA controller variant, a mid-install interruption, an induced bootloader failure, a recovery medium) and none has run.

## Unresolved

Each of these is blocking. `NOT_RUN` is not a soft state:

- `multiple-disks`
- `nvme-like-virtual-disk`
- `sata-like-virtual-disk`
- `supported-free-space-installation`
- `interrupted-installation`
- `bootloader-failure`
- `recovery-installation`

## Standing note

No disk has been written. The installer source, its safety checks and its refusals are covered by 60 source tests that all pass; none of that is an installation.

## Related

- `QUALIFICATION_CANDIDATE_READINESS_REPORT.md` — the `installation-matrix` prerequisite

## How to regenerate

```text
python scripts/release.py test-matrix --name installation
python scripts/write_qualification_reports.py
```

This report is generated from `operations/data/qualification-matrices.json`. Edit the
data, not the report: a report that disagrees with the evidence record is exactly what
the evidence model exists to prevent.
