# Phase 7 — Track B external gate matrix

Committed with every row in its true starting state, before any Phase 7 work.
These gates need people, hardware or authority outside this repository; the
matrix exists so that *which owner is blocking progress* stays visible instead
of dissolving into one merged status (brief §22).

The subject artifact is `e906a48793d7`
(image `sha256:c87a6616008ce34f97840f63814e08fdb33574b52202fbb4841b7f5aa7f8562d`).
Evidence for any row below must identify it, or the new artifact that
supersedes it under the §21 policy.

| Gate | Status | Owner needed | Readiness (what Phase 7 added) |
| --- | --- | --- | --- |
| Independent security review | NOT_RUN | external reviewer, no project principal | `qualification/phase7/security/REVIEW_PACKAGE_ADDENDUM.md` — the 18 Go High findings answered per binary on the subject artifact; six rows split podman/skopeo |
| Critical/High finding dispositions | BLOCKED on review | external reviewer | version half complete for all Go Highs; 3 pseudo-version rows named as the reviewer's commit-level question |
| Physical hardware qualification | NOT_RUN | a physical x86-64 UEFI machine | three `expectation.json` under `qualification/phase6/hardware/` still await one |
| Production signing | NOT_RUN | key authority | zero `.sig` files exist; measured in Phase 6, unchanged |
| Second signer / approval | NOT_RUN | a second person | — |
| Alpha validation | NOT_RUN | Alpha testers | `qualification/phase7/alpha/ALPHA_TEST_PROTOCOL.md` — five journeys, digest binding, measured/user-reported separation, triage classes |

What Phase 7 can move here is **readiness**: a review package an external
party can reproduce, an Alpha protocol a tester can execute, and signing
records a signer can complete. Readiness is recorded in this tree; it does not
change a row's status. Only the owner named above can do that.
