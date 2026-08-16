# Encryption qualification report

Date: 2026-08-16T04:03:01Z  
Candidate commit: `79bb99ddb39d8a5dbc279629f43b23346fb0e5e8`  
Result: **NOT QUALIFIED** — 2 of 9 scenarios resolved, 1 failing, 6 not run.

Nine scenarios covering LUKS password unlock, recovery key, incorrect password, missing recovery key, TPM fallback, Secure Boot interaction, and update, rollback and recovery media access against an encrypted installation.

## Scenarios

| Scenario | Outcome | Method | Evidence |
|---|---|---|---|
| `recovery-key` | NOT_RUN | source-inspection | — |
| `missing-recovery-key` | NOT_RUN | source-inspection | — |
| `secure-boot-interaction` | NOT_RUN | source-inspection | — |
| `update-after-encryption` | NOT_RUN | source-inspection | — |
| `rollback-after-encryption` | NOT_RUN | source-inspection | — |
| `recovery-media-access` | NOT_RUN | source-inspection | — |
| `luks-password-unlock` | FAIL | virtual-machine | `qualification/installed-system/evidence/ISQ-20260801-encrypted-first-boot-001/record.json` |
| `incorrect-password` | PASS | virtual-machine | `qualification/installed-system/evidence/ISQ-20260801-encrypted-wrong-credential-001/record.json` |
| `tpm-fallback` | PASS | virtual-machine | `qualification/installed-system/evidence/ISQ-20260801-tpm-absent-002/record.json` |

## Why these scenarios have not run

Encrypted installation and passphrase first-boot now carry evidence (installation/encrypted-uefi-installation; qualification/installer-journeys/evidence/first-boot). The remaining NOT_RUN scenarios need scenario work of their own: recovery keys are not yet offered by the setup surface, and update/rollback-after-encryption depend on the update and rollback matrices, which are blocked above.

## Unresolved

Each of these is blocking. `NOT_RUN` is not a soft state:

- `recovery-key`
- `missing-recovery-key`
- `secure-boot-interaction`
- `update-after-encryption`
- `rollback-after-encryption`
- `recovery-media-access`

## Standing note

`encryption-failure` and `key-leakage` are non-waivable blockers, and the `Encryption` evidence category is one of six that `release/evidence.py` refuses to let anyone waive.

## Related

- `QUALIFICATION_CANDIDATE_READINESS_REPORT.md` — the `encryption-matrix` prerequisite

## How to regenerate

```text
python scripts/release.py test-matrix --name encryption
python scripts/write_qualification_reports.py
```

This report is generated from `operations/data/qualification-matrices.json`. Edit the
data, not the report: a report that disagrees with the evidence record is exactly what
the evidence model exists to prevent.
