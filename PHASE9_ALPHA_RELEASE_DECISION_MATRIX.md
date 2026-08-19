<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Phase 9 — Alpha release decision matrix

The subject artifact for every row: **`e906a48793d7`**, image
`sha256:c87a6616008ce34f97840f63814e08fdb33574b52202fbb4841b7f5aa7f8562d`,
ISO `823d50caba35afe72452768affd5f6fa0ac8cfc13c164f0e1bc909fa887ab421`,
source commit `e906a48793d74544b39c14cc3e35e0654f5311e2`. Frozen; UNSIGNED.

Status vocabulary: PASS / FAIL / NOT_RUN / NOT_SUPPORTED / ACCEPTED_RISK /
MORE_EVIDENCE_REQUIRED. These values are never averaged: a release is a
conjunction of required gates. The **Evidence ID** column names the intake
ID(s) whose gate-eligible ACCEPTED evidence moved the row — `—` means no
evidence has arrived, and `—` moves nothing. The **Blocking** column scores
the pre-committed conditions
(`qualification/phase8/conditions/ALPHA_RELEASE_BLOCKING_CONDITIONS.md`,
fixed at `17a34aa6`): under them, an absent review, signature, or second
approval *blocks*; it never authorizes.

| Gate | Evidence ID | Artifact | Owner | Status | Blocking |
|---|---|---|---|---|---|
| Independent security review | — | `e906a48793d7` | external reviewer (none exists) | **NOT_RUN** | **yes** — condition 1: no completed review exists |
| Critical/High disposition | — | `e906a48793d7` | reviewer proposes; accountable owner accepts | **NOT_RUN** — 41 REQUIRES_REVIEW, 3 UNKNOWN, unchanged | **yes** — condition 2: every Critical lacks an accepted disposition |
| Physical hardware qualification | — | `e906a48793d7` ISO `823d50ca…` | machine operator (no machine exists) | **NOT_RUN** | undetermined — condition 9 has no evidence; zero machines are declared supported |
| Production signing | — | `e906a48793d7` | key authority (none exists) | **NOT_RUN** — artifact UNSIGNED | **yes** — condition 7: no verified signature, no recorded exception |
| Signature verification | — | `e906a48793d7` | an independent verifier (not the signer) | **NOT_RUN** — nothing to verify | **yes** — inside condition 7 |
| Second approval | — | `e906a48793d7` | a second person (none exists) | **NOT_RUN** | **yes** — condition 8: no second person has named the digest |
| Alpha tester validation | — | `e906a48793d7` ISO | enrolled testers (zero) | **NOT_RUN** | undetermined — conditions 3, 4, 5, 10 have no evidence either way |
| Alpha finding triage | — | `e906a48793d7` | release decision authority | **NOT_RUN** — zero findings exist (`qualification/phase9/triage/findings.json`) | undetermined — nothing exists to triage |
| Artifact identity | `qualification/phase7/baseline/freeze.log` | `e906a48793d7` | repository + evidence chain | **PASS** — five digests recomputed from bytes 2026-08-18 | no — condition 6 is false |
| Internal engineering certification | `qualification/phase7/certification/` | repository `e65e3df0` | Phase 7 (closed) | **PASS** (closed gate, not reopened) | no |

**Decision record:** `qualification/phase9/decision/alpha-release-decision.json`
— `final_decision: MORE_EVIDENCE_REQUIRED`. Conditions 1, 2, 7 and 8 are
true today, so the conjunction cannot authorize; nothing external is FAIL,
because no external actor has returned a blocking result.

**Current §21 status: PHASE 9 — EXTERNAL EVIDENCE INTAKE IN PROGRESS.**
Rows move only through `qualification/phase9/tools/intake.py register` and a
human decision — never on absence, and never by averaging.
