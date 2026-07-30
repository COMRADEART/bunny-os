# Accessibility review package

Review id: `review-accessibility`  
State: **package-prepared**  
Reviewer: **not yet identified**  
Organisation: **not yet identified**  
Source commit: `79bb99ddb39d8a5dbc279629f43b23346fb0e5e8`

This package is prepared and has not been sent. It is not a review, and nothing in this
repository may cite it as one. `release/reviews.py` refuses to record a reviewer
affiliated with the project, so this cannot become a self-review by being filled in.

## Scope

The fourteen essential workflows in the accessibility matrix, from installer keyboard navigation through recovery UI and diagnostics export.

## Threat model

Not applicable. The risk here is exclusion rather than compromise: an inaccessible encryption prompt or recovery tool locks a user out of their own machine.

## Design documents

- `docs/ACCESSIBILITY.md`
- `docs/FIRST_RUN.md`
- `docs/INSTALLATION.md`
- `docs/RECOVERY.md`
- ACCESSIBILITY_REPORT.md
- FIRST_RUN_ACCESSIBILITY_REPORT.md

## Test results

- `tests/accessibility/`
- ACCESSIBILITY_QUALIFICATION_REPORT.md

## Known limitations

Every accessibility result to date is static. No Orca session has been driven through the installer, the encryption prompt, or the recovery tool, and release/matrix.py refuses to accept a source-inspection pass in this matrix for that reason.

## Explicit questions

1. Can a screen-reader user complete an encrypted installation unaided, including entering and confirming a passphrase and recording a recovery key?
2. Is the recovery environment usable without sight, given it runs before a full desktop session exists?
3. Do the Bunny approval dialogs announce what is being approved, or only that approval is requested?
4. Does text scaling above 150% break any essential workflow?
5. Is reduced-motion honoured through the first-run and update flows?

## Expected deliverables

- A written audit identifying the auditor and the assistive technologies used
- A per-workflow pass or fail with reproduction steps
- WCAG-referenced findings where applicable
- An explicit statement on whether an encrypted installation is completable by a screen-reader user

## How this package becomes a completed review

1. Identify an external reviewer and record their name and organisation.
2. Set `state` to `commissioned` in `operations/data/independent-reviews.json`.
3. On delivery, place the report in this directory and set `reportReference` to its path.
4. Set `state` to `delivered`. The gate verifies the file exists before accepting it.

Generated from `operations/data/independent-reviews.json`. Edit that file, not this one.
