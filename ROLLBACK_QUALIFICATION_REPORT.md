# Rollback qualification report

Date: 2026-08-18T16:22:03Z  
Candidate commit: `79bb99ddb39d8a5dbc279629f43b23346fb0e5e8`  
Result: **NOT QUALIFIED** — 0 of 5 scenarios resolved, 0 failing, 5 not run.

Manual, automatic and recovery-assisted rollback, plus rollback after encryption and rollback with user data preserved.

## Scenarios

| Scenario | Outcome | Method | Evidence |
|---|---|---|---|
| `manual-rollback` | NOT_RUN | source-inspection | — |
| `automatic-rollback-recommendation` | NOT_RUN | source-inspection | — |
| `recovery-assisted-rollback` | NOT_RUN | source-inspection | — |
| `rollback-after-encryption` | NOT_RUN | source-inspection | — |
| `rollback-preserves-user-data` | NOT_RUN | source-inspection | — |

## Why these scenarios have not run

vm-rollback-test.sh exits 3: BUNNY_PREVIOUS_BETA_DISK must name an existing QCOW2. There is no previous release to roll back to.

## Unresolved

Each of these is blocking. `NOT_RUN` is not a soft state:

- `manual-rollback`
- `automatic-rollback-recommendation`
- `recovery-assisted-rollback`
- `rollback-after-encryption`
- `rollback-preserves-user-data`

## Standing note

`untested-release-rollback` and `rollback-failure` are open blocker codes.

## Related

- `QUALIFICATION_CANDIDATE_READINESS_REPORT.md` — the `rollback-matrix` prerequisite

## How to regenerate

```text
python scripts/release.py test-matrix --name rollback
python scripts/write_qualification_reports.py
```

This report is generated from `operations/data/qualification-matrices.json`. Edit the
data, not the report: a report that disagrees with the evidence record is exactly what
the evidence model exists to prevent.
