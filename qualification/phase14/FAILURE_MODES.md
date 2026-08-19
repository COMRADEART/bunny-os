<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Failure Modes

The failure modes this phase exists to make structural, each with the
mechanism that closes it and the scenario or guard that executes the
refusal on every run.

| Failure mode | Structural answer | Executed by |
| --- | --- | --- |
| Unknown evidence becomes "generic evidence" | classification refuses zero-match records | PH14-A2 |
| A record shaped like two things is routed as one of them | ambiguity refuses | PH14-A3 |
| A fixture is processed as evidence | fixture check first, terminal; Phase 9 rejects the marker; validators refuse | PH14-A4, guard suite |
| Evidence for other bytes moves this artifact's gate | binding recomputed; `DOES_NOT_APPLY` / `ARTIFACT_MISMATCH` | PH14-A5, C4, D2, E4, F2, G2, G10, H4 |
| A decision quietly absorbs evidence that arrived after it | the cut detects and names post-cut intakes | PH14-B2 |
| A later decision rewrites an earlier one | supersession points; it never edits; same-cut supersession refuses | PH14-B8 |
| Expiry evaluated by silence | `--as-of` mandatory once an expiring record exists; every expiry evaluation without it raises | PH14-B7, I7 |
| An expired or revoked authority keeps acting | standing-assignments filtering per cut | PH14-G8, G9, I1 |
| A conflict resolves toward the favorable reading | most-blocking effective; `REQUIRES_HUMAN_DECISION`; a favorable resolution raises | PH14-C1, C7 |
| "More PASS than FAIL" | does not exist anywhere; per-machine, per-dimension forever | PH14-C2, F6 |
| A finite machine set becomes "SUPPORTED ON PCS" | `hardware_claims` raises; aggregate claim structurally `null` | PH14-F6 |
| An unreproduced severe issue evaporates | `NOT_REPRODUCED` is about attempts; the finding and report stay | PH14-C3, E6 |
| Intake acceptance mistaken for contract validity | contract layers validated on top; contributes nothing until revised | PH14-D3 |
| Silence dispositions a finding | unaddressed baseline rows keep their prior state; closure needs bound evidence | PH14-D8, Phase 11 |
| Volume substitutes for policy | 100 reports without an active policy stay `SUFFICIENCY_UNDETERMINED` | PH14-E1 |
| A fixture policy leaks a real threshold | the real registry is checked `SUFFICIENCY_POLICY_UNDEFINED` inside the same scenario | PH14-E3 |
| Similar reports merge on their own | dedup is a recorded, reversible decision | PH14-E5 |
| A user success becomes hardware support | `USER_REPORTED` / `HARDWARE_OBSERVED`, never a protocol PASS | PH14-E7, F5 |
| A drill satisfies the signing gate | `REJECTED` at the boundary, rechecked at authorization | PH14-A7, G4 |
| One person approves twice / signer approves | `REJECTED`; `CONFLICT` without a recorded overlap decision | PH14-G5, G6 |
| An approval predates what it approves | ordering flags `REQUIRES_HUMAN_DECISION` | PH14-G7 |
| Future-dated or ambiguous time is read favorably | time screening fails closed | PH14-I4, I5, I6 |
| The repository manufactures `AUTHORIZED` | five-source floor + assigned authority + validated record; internal JSON refused with the absent floor named | PH14-C6, H2–H7 |
| A successor inherits a decision | authorization never crosses an artifact edge; evidence transfers only by recorded decision | PH14-H10 |
| A rehearsal touches reality | every real input byte-compared before and after; a changed byte aborts | `run_rehearsals`, both test suites |
| The demonstration record drifts from the machinery | `MATRIX.json` is derived by re-executing every scenario; `verify` refuses drift | `matrix_problems` |
