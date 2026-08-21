<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Phase 8 — External release decision matrix

The subject artifact for every row: **`e906a48793d7`**, image
`sha256:c87a6616008ce34f97840f63814e08fdb33574b52202fbb4841b7f5aa7f8562d`,
ISO `823d50caba35afe72452768affd5f6fa0ac8cfc13c164f0e1bc909fa887ab421`,
source commit `e906a48793d74544b39c14cc3e35e0654f5311e2`. Frozen; UNSIGNED.

Rows move only on evidence produced by the named decision authority. A row
that has not been acted on reads NOT_RUN, and NOT_RUN authorizes nothing.

| Gate | Owner | Status | Artifact | Evidence | Decision authority |
|---|---|---|---|---|---|
| Independent security review | external reviewer (none exists) | **NOT_RUN** | `e906a48793d7` | package ready: `qualification/phase8/security-review/` | the reviewer, and only the reviewer |
| Critical/High disposition | external reviewer + accountable owner | **NOT_RUN** — all 80 findings REQUIRES_REVIEW; 3 Go rows UNKNOWN (pseudo-versions) | `e906a48793d7` | `qualification/phase8/security-review/review-package.json` | reviewer proposes; accountable owner accepts |
| Physical hardware qualification | machine operator (no machine exists) | **NOT_RUN** | `e906a48793d7` ISO `823d50ca…` | protocol: `qualification/phase8/hardware/PROTOCOL.md`; matrix: `qualification/phase8/hardware-matrix.json` (zero machines) | the operator's records, per machine ID |
| Production signing | key authority (none exists) | **NOT_RUN** — artifact UNSIGNED; zero `.sig` files (measured Phase 6, unchanged) | `e906a48793d7` | `qualification/phase8/signing/SIGNING_READINESS.md` | the key authority |
| Signature verification | an independent verifier (not the signer) | **NOT_RUN** — nothing to verify | `e906a48793d7` | verification procedure in SIGNING_READINESS.md §4 | the verifier |
| Second signer | a second person (none exists) | **NOT_RUN** | `e906a48793d7` | `qualification/phase8/signing/APPROVALS.md` | the second approver |
| Alpha tester validation | enrolled testers (zero) | **NOT_RUN** | `e906a48793d7` ISO | ops: `qualification/phase8/alpha/OPERATIONS.md`; reports dir empty | each tester's bound report |
| Alpha release blocker triage | governance (workstream F) | **NOT_RUN** — no findings exist to triage | `e906a48793d7` | conditions: `qualification/phase8/conditions/` (committed before testing) | the release decision authority |
| Artifact identity | repository + evidence chain | **PASS** | `e906a48793d7` | all five digests recomputed from bytes 2026-08-18 (`qualification/phase7/baseline/freeze.log`); artifact frozen, no rebuild | mechanical — the bytes decide |
| Internal engineering certification | Phase 7 (closed) | **PASS** (closed gate, not reopened) | repository `e65e3df0` | 2 × 6072 tests, zero failures, ext4 as `bunny` (`qualification/phase7/certification/`) | closed per Phase 8 §2; reopens only on regression or artifact change |

**Current §19 status: PHASE 8 — EXTERNAL VALIDATION IN PROGRESS.**
Two rows are PASS and both are internal; every external row awaits its owner.
Nothing here may be averaged into "release ready".
