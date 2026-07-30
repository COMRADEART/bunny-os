# Encryption qualification report

Date: 2026-07-29  
Source commit: `79bb99ddb39d8a5dbc279629f43b23346fb0e5e8`  
Result: **NOT QUALIFIED** — 0 of 9 scenarios resolved, 0 failing, 9 not run.

Nine scenarios covering LUKS password unlock, recovery key, incorrect password, missing recovery key, TPM fallback, Secure Boot interaction, and update, rollback and recovery media access against an encrypted installation.

## Scenarios

| Scenario | Outcome | Method | Evidence |
|---|---|---|---|
| `luks-password-unlock` | NOT_RUN | source-inspection | — |
| `recovery-key` | NOT_RUN | source-inspection | — |
| `incorrect-password` | NOT_RUN | source-inspection | — |
| `missing-recovery-key` | NOT_RUN | source-inspection | — |
| `tpm-fallback` | NOT_RUN | source-inspection | — |
| `secure-boot-interaction` | NOT_RUN | source-inspection | — |
| `update-after-encryption` | NOT_RUN | source-inspection | — |
| `rollback-after-encryption` | NOT_RUN | source-inspection | — |
| `recovery-media-access` | NOT_RUN | source-inspection | — |

## Why these scenarios have not run

Depends on a completed installation. build/scripts/vm-encrypted-install.sh states that encrypted automation needs a reviewed Anaconda test configuration and a protected secret channel, and is interactive-only.

## Unresolved

Each of these is blocking. `NOT_RUN` is not a soft state:

- `luks-password-unlock`
- `recovery-key`
- `incorrect-password`
- `missing-recovery-key`
- `tpm-fallback`
- `secure-boot-interaction`
- `update-after-encryption`
- `rollback-after-encryption`
- `recovery-media-access`

## Standing note

`encryption-failure` and `key-leakage` are non-waivable blockers, and the `Encryption` evidence category is one of six that `release/evidence.py` refuses to let anyone waive.

## How to regenerate

```text
python scripts/release.py test-matrix --name encryption
python scripts/write_qualification_reports.py
```

This report is generated from `operations/data/qualification-matrices.json`. Edit the
data, not the report: a report that disagrees with the evidence record is exactly what
the evidence model exists to prevent.
