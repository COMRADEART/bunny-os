# Update qualification report

Date: 2026-08-01T14:31:13Z  
Candidate commit: `79bb99ddb39d8a5dbc279629f43b23346fb0e5e8`  
Result: **NOT QUALIFIED** — 1 of 13 scenarios resolved, 0 failing, 12 not run.

Thirteen scenarios covering the happy path and twelve failure paths, including interrupted download and staging, insufficient disk, invalid signature, expired metadata, wrong architecture, and failures of service health, graphical session and the Bunny contract.

## Scenarios

| Scenario | Outcome | Method | Evidence |
|---|---|---|---|
| `current-to-next-candidate` | NOT_RUN | source-inspection | — |
| `interrupted-download` | NOT_RUN | source-inspection | — |
| `interrupted-staging` | NOT_RUN | source-inspection | — |
| `insufficient-disk` | NOT_RUN | source-inspection | — |
| `expired-metadata` | NOT_RUN | source-inspection | — |
| `wrong-architecture` | NOT_RUN | source-inspection | — |
| `failed-service-health` | NOT_RUN | source-inspection | — |
| `failed-graphical-session` | NOT_RUN | source-inspection | — |
| `failed-bunny-contract` | NOT_RUN | source-inspection | — |
| `automatic-rollback-recommendation` | NOT_RUN | source-inspection | — |
| `manual-rollback` | NOT_RUN | source-inspection | — |
| `recovery-assisted-rollback` | NOT_RUN | source-inspection | — |
| `invalid-signature` | PASS | virtual-machine | `qualification/installed-system/evidence/collections/update-invalid-signature.json` |

## Why these scenarios have not run

vm-upgrade-test.sh exits 3: BUNNY_UPDATE_MANIFEST must name a signed update manifest. No manifest has been published and no registry is reachable.

## Unresolved

Each of these is blocking. `NOT_RUN` is not a soft state:

- `current-to-next-candidate`
- `interrupted-download`
- `interrupted-staging`
- `insufficient-disk`
- `expired-metadata`
- `wrong-architecture`
- `failed-service-health`
- `failed-graphical-session`
- `failed-bunny-contract`
- `automatic-rollback-recommendation`
- `manual-rollback`
- `recovery-assisted-rollback`

## Standing note

A signed manifest and a reachable registry are prerequisites. Neither exists.

## Related

- `QUALIFICATION_CANDIDATE_READINESS_REPORT.md` — the `update-matrix` prerequisite

## How to regenerate

```text
python scripts/release.py test-matrix --name update
python scripts/write_qualification_reports.py
```

This report is generated from `operations/data/qualification-matrices.json`. Edit the
data, not the report: a report that disagrees with the evidence record is exactly what
the evidence model exists to prevent.
