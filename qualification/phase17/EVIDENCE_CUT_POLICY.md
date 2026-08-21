# Cross-source evidence cut policy

A Phase 17 cut is a sealed reference over the Phase 14 cut plus the Phase 9
ledger, Phase 10 graph, Phase 11/16 security state, Phase 12 Alpha state,
Phase 13 authorities/risks/policies, Phase 17 registry, source evaluations,
evidence IDs, and explicit `asOf`. It is not a ledger and contains no copied
evidence bytes. The same byte inputs and `asOf` produce the same bytes.

Evidence received after a cut is named as post-cut and cannot rewrite the
historical decision. A later cut may include it. Existing cut IDs refuse.
