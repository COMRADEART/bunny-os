# Accessibility qualification report

Date: 2026-08-18T16:22:03Z  
Candidate commit: `79bb99ddb39d8a5dbc279629f43b23346fb0e5e8`  
Result: **NOT QUALIFIED** — 2 of 14 scenarios resolved, 0 failing, 12 not run.

Fourteen essential workflows, from installer keyboard navigation and screen reader through the encryption prompt, first run, login, the Bunny surfaces, update, rollback, recovery, diagnostics export, and the high-contrast, text-scaling and reduced-motion settings.

## Scenarios

| Scenario | Outcome | Method | Evidence |
|---|---|---|---|
| `installer-keyboard-navigation` | NOT_RUN | source-inspection | — |
| `installer-screen-reader` | NOT_RUN | source-inspection | — |
| `encryption-prompt` | NOT_RUN | source-inspection | — |
| `first-run` | NOT_RUN | source-inspection | — |
| `login` | NOT_RUN | source-inspection | — |
| `bunny-launcher` | NOT_RUN | source-inspection | — |
| `bunny-approvals` | NOT_RUN | source-inspection | — |
| `update-ui` | NOT_RUN | source-inspection | — |
| `rollback-ui` | NOT_RUN | source-inspection | — |
| `recovery-ui` | NOT_RUN | source-inspection | — |
| `diagnostics-export` | NOT_RUN | source-inspection | — |
| `high-contrast` | PASS | virtual-machine | `qualification/phase7/accessibility/evidence/a11y-e906a48793d7/accessibility.json` |
| `text-scaling` | PASS | virtual-machine | `qualification/phase7/accessibility/evidence/a11y-e906a48793d7/accessibility.json` |
| `reduced-motion` | NOT_RUN | source-inspection | — |

## Why these scenarios have not run

No assistive-technology session has been driven. release/matrix.py refuses a source-inspection pass in this matrix, so these stay unresolved rather than being recorded from code review.

## Unresolved

Each of these is blocking. `NOT_RUN` is not a soft state:

- `installer-keyboard-navigation`
- `installer-screen-reader`
- `encryption-prompt`
- `first-run`
- `login`
- `bunny-launcher`
- `bunny-approvals`
- `update-ui`
- `rollback-ui`
- `recovery-ui`
- `diagnostics-export`
- `reduced-motion`

## Standing note

Static accessibility tests are explicitly not sufficient. `release/matrix.py` refuses a source-inspection pass in this matrix. This is the gap where being wrong harms a user rather than merely leaving a box unticked: an inaccessible encryption prompt or recovery tool locks someone out of their own machine.

## Related

- `ACCESSIBILITY_EVIDENCE_PLAN.md` — the seventeen-flow runtime evidence model, which supersedes this fourteen-scenario matrix for runtime results
- `operations/data/accessibility-evidence.json` — the runtime record, 17 of 17 `NOT_RUN`
- `reviews/accessibility/REQUEST.md` — the review this matrix cannot substitute for
- `release/accessibility.py` — refuses a `PASS` with no recorded steps

## How to regenerate

```text
python scripts/release.py test-matrix --name accessibility
python scripts/write_qualification_reports.py
```

This report is generated from `operations/data/qualification-matrices.json`. Edit the
data, not the report: a report that disagrees with the evidence record is exactly what
the evidence model exists to prevent.
