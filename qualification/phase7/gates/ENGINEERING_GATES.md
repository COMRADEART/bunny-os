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
| Rollback harness proves the booted deployment | **PASS** | `e906a48793d7` chain (deploy `1804c600` ← `18fd8a7d`) | `qualification/phase7/rollback/ROLLBACK_QUALIFICATION.md`; four identities, three independent booted-identity sources; runs 1–3 (NOT_RUN, NOT_RUN, FAIL) preserved as the harness's own semantics evidence |
| Rollback user-state preservation vs prior expectation | **PASS** | same chain | `expectation.json` committed before boot; 8/8 markers byte-identical, per-deployment /etc switch proven, hostname and locale per rule (`evidence/verdict.json`) |
| Recovery media journey | **PASS** (defined journey; unsigned medium, limits named) | recovery medium `40dd7d2d…` @ `b812e48e` against subject disk `497add9a…` | `qualification/phase7/recovery/RECOVERY_QUALIFICATION.md` — cannot-boot measured → independent boot → inspect → repair-by-derivation → verified reboot; 11-scenario matrix does not flip |
| Accessibility FAIL: `high-contrast` | **PASS** — fixed (design phase, in `7edd3fd` lineage), verified on the subject artifact, regression-tested | `e906a48793d7` | `qualification/phase7/accessibility/evidence/a11y-e906a48793d7/` — 99.6% of the screen changes (14.4× the run's own noise floor); theme-switch tests in the certified suite |
| Accessibility FAIL: `text-scaling` | **PASS** — fixed, verified, regression-tested | `e906a48793d7` | same evidence — 19/60 AT-SPI controls grew, none shrank, at 1.5×; 41.5% of the screen (6.0× noise); stylesheet-scale tests in the certified suite |
| Evidence immutability covers phases 4–6 | **PASS** | repository at record commit `7db5962b` | `qualification/phase7/immutability/frozen-evidence.json` — 5424 files pinned across 24 trees; enforced by `tests/release/test_frozen_evidence.py` |
| Evidence immutability negative control | **PASS** | repository | `qualification/phase7/immutability/negative-control.log` — modify one historical file → FAIL, stage one file into a frozen tree → FAIL, restore → PASS; constructed-tree controls run on every suite execution |
| Script executability gate | **PASS** | repository | `tests/release/test_script_executability.py`; run: `qualification/phase7/executability/gate-run.log`; 20 executables well-formed, 131 `.sh` blobs LF in the index; ten stray exec bits on data files corrected (`MODE_CORRECTIONS.md`) |
| Script executability negative control | **PASS** | constructed blobs | five constructed-blob controls (executable-without-shebang, CRLF shebang, unlisted interpreter, CRLF/mixed shell blob, clean-script pass) run on every suite execution |

The two accessibility rows start as the FAILs they are — carried, not reset.
`NOT_RUN` would erase the only outright FAILs in the project, which is the
downgrade the brief's §7 forbids.
