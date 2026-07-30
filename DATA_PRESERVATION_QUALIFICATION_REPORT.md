# Data preservation qualification report

Date: 2026-07-29  
Source commit: `79bb99ddb39d8a5dbc279629f43b23346fb0e5e8`  
Result: **NOT QUALIFIED** — 0 of 10 scenarios resolved, 0 failing, 10 not run.

Ten classes of user state that must survive an update or a rollback: `/home`, the Bunny database, Bunny memory, provider aliases, local models, plugins, workspaces, applications, settings and checkpoints.

## Scenarios

| Scenario | Outcome | Method | Evidence |
|---|---|---|---|
| `home` | NOT_RUN | source-inspection | — |
| `bunny-database` | NOT_RUN | source-inspection | — |
| `bunny-memory` | NOT_RUN | source-inspection | — |
| `provider-aliases` | NOT_RUN | source-inspection | — |
| `local-models` | NOT_RUN | source-inspection | — |
| `plugins` | NOT_RUN | source-inspection | — |
| `workspaces` | NOT_RUN | source-inspection | — |
| `applications` | NOT_RUN | source-inspection | — |
| `settings` | NOT_RUN | source-inspection | — |
| `checkpoints` | NOT_RUN | source-inspection | — |

## Why these scenarios have not run

Preservation is measured across an update or rollback. Both are blocked above, so nothing has been preserved or lost yet.

## Unresolved

Each of these is blocking. `NOT_RUN` is not a soft state:

- `home`
- `bunny-database`
- `bunny-memory`
- `provider-aliases`
- `local-models`
- `plugins`
- `workspaces`
- `applications`
- `settings`
- `checkpoints`

## Standing note

Preservation is measured across an update or a rollback. Both are blocked, so nothing has been preserved or lost yet.

## How to regenerate

```text
python scripts/release.py test-matrix --name preservation
python scripts/write_qualification_reports.py
```

This report is generated from `operations/data/qualification-matrices.json`. Edit the
data, not the report: a report that disagrees with the evidence record is exactly what
the evidence model exists to prevent.
