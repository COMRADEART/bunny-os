# Phase 7 — Track A engineering gate matrix

Committed with every row `NOT_RUN`, before any Phase 7 measurement. Rows move
only with evidence, and each row names the artifact its evidence binds to —
a row without an artifact is a row about the repository, and says so.

Track A is complete only when (brief §9): rollback harness = PASS, recovery
journey = PASS or explicitly NOT_SUPPORTED with an approved disposition, and
both accessibility FAILs are resolved. The immutability and executability
gates are Track A obligations with the same standard.

| Gate | Status | Artifact | Evidence |
| --- | --- | --- | --- |
| Rollback harness proves the booted deployment | NOT_RUN | — | — |
| Rollback user-state preservation vs prior expectation | NOT_RUN | — | — |
| Recovery media journey | NOT_RUN | — | — |
| Accessibility FAIL: `high-contrast` | **FAIL** (carried from `b09f523`) | `b09f523` | `qualification/capsules/evidence/a11y-b09f523/accessibility.json` |
| Accessibility FAIL: `text-scaling` | **FAIL** (carried from `b09f523`) | `b09f523` | `qualification/capsules/evidence/a11y-b09f523/accessibility.json` |
| Evidence immutability covers phases 4–6 | **PASS** | repository at record commit `7db5962b` | `qualification/phase7/immutability/frozen-evidence.json` — 5424 files pinned across 24 trees; enforced by `tests/release/test_frozen_evidence.py` |
| Evidence immutability negative control | **PASS** | repository | `qualification/phase7/immutability/negative-control.log` — modify one historical file → FAIL, stage one file into a frozen tree → FAIL, restore → PASS; constructed-tree controls run on every suite execution |
| Script executability gate | NOT_RUN | — | — |
| Script executability negative control | NOT_RUN | — | — |

The two accessibility rows start as the FAILs they are — carried, not reset.
`NOT_RUN` would erase the only outright FAILs in the project, which is the
downgrade the brief's §7 forbids.
