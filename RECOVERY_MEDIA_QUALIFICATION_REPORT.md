# Recovery media qualification report

Date: 2026-08-01T14:31:13Z  
Candidate commit: `79bb99ddb39d8a5dbc279629f43b23346fb0e5e8`  
Result: **NOT QUALIFIED** — 0 of 11 scenarios resolved, 0 failing, 11 not run.

Recovery media must boot independently of the installed deployment, verify its own signature, and reach the installed system's data only with valid credentials. No claim here may rest on source inspection: `release/matrix.py` refuses a source-inspection pass in this matrix, because a recovery tool that has never booted is a hypothesis.

## Scenarios

| Scenario | Outcome | Method | Evidence |
|---|---|---|---|
| `boots-independently` | NOT_RUN | source-inspection | — |
| `verifies-own-signature` | NOT_RUN | source-inspection | — |
| `encrypted-access-requires-credentials` | NOT_RUN | source-inspection | — |
| `mounts-user-data-read-only-by-default` | NOT_RUN | source-inspection | — |
| `inspects-deployments` | NOT_RUN | source-inspection | — |
| `selects-previous-deployment` | NOT_RUN | source-inspection | — |
| `repairs-boot-entries` | NOT_RUN | source-inspection | — |
| `disables-bunny` | NOT_RUN | source-inspection | — |
| `disables-plugins` | NOT_RUN | source-inspection | — |
| `enters-safe-graphics` | NOT_RUN | source-inspection | — |
| `exports-redacted-diagnostics` | NOT_RUN | source-inspection | — |

## Why these scenarios have not run

vm-recovery-test.sh exits 3: BUNNY_RECOVERY_ISO must name an existing recovery image. A recovery OCI archive and QCOW2 were built; no signed recovery ISO exists.

## Unresolved

Each of these is blocking. `NOT_RUN` is not a soft state:

- `boots-independently`
- `verifies-own-signature`
- `encrypted-access-requires-credentials`
- `mounts-user-data-read-only-by-default`
- `inspects-deployments`
- `selects-previous-deployment`
- `repairs-boot-entries`
- `disables-bunny`
- `disables-plugins`
- `enters-safe-graphics`
- `exports-redacted-diagnostics`

## Standing note

`recovery-media-failure` is one of the five open stable-release blocker codes, and it stays open.

## Related

- `QUALIFICATION_CANDIDATE_READINESS_REPORT.md` — the `independent-recovery-media` prerequisite

## How to regenerate

```text
python scripts/release.py test-matrix --name recovery-media
python scripts/write_qualification_reports.py
```

This report is generated from `operations/data/qualification-matrices.json`. Edit the
data, not the report: a report that disagrees with the evidence record is exactly what
the evidence model exists to prevent.
