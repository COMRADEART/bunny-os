# Phase 7 baseline

| | |
| --- | --- |
| Phase 6 head | `62b8b130` — PHASE 6 — EXTERNAL GATES BLOCKED |
| Reference certification at that head | 2 runs × 6030 tests, zero failures |
| Subject artifact | `e906a48793d7` — READY, Alpha Release Candidate only, **UNSIGNED** |
| Subject build commit | `e906a48793d74544b39c14cc3e35e0654f5311e2` |
| Subject image | `sha256:c87a6616008ce34f97840f63814e08fdb33574b52202fbb4841b7f5aa7f8562d` |
| Subject qcow2 | `497add9a77db2db02bf2541e85b04b0e285c1833d2c8220d193d0d413a6ce867` |
| Subject ISO | `823d50caba35afe72452768affd5f6fa0ac8cfc13c164f0e1bc909fa887ab421` |
| Counterpart (N+1) | `e501218f2fe0` — qcow2 `b4dd95f3cb3f7d4b4419c120e04e4375f4a176f0fd0a0ee5f2c91ba5de99dcef` |
| Archive | `/root/bunny-build-archive/beta-phase4-rc-e906a48793d7-20260818T014208Z` on the qualification host |

These identities are **carried from Phase 6 §19**, where they were re-verified
from the bytes on 2026-08-18 (`qualification/phase6/baseline/freeze.log`).
Phase 7 re-verifies from the bytes before binding any new evidence to them;
that verification writes `freeze.log` beside this file. Until it exists, no
Phase 7 row may cite an artifact digest.

Historical evidence remains historical evidence: nothing in Phase 7 rewrites a
Phase ≤6 record. Corrections, if any, are correction records under
`qualification/phase7/`.
