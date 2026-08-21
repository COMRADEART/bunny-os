# Phase 17 contract

The subject is the active ROOT artifact in the Phase 10 graph and the subject
of the Phase 9 ledger. The two identities must agree. Repository HEAD is never
substituted for either identity.

Every source is classified by `SOURCE_REGISTRY.json`. Unknown and ambiguous
sources fail closed. Evidence bytes cross exactly one immutable boundary:
Phase 9 intake. Phase 17 may inspect, validate, bind, evaluate, cut references,
assemble, and refuse. It may not append a ledger, copy evidence into intake,
assign an authority, create a policy decision, sign an artifact, or authorize a
release.

All decisions are cut-relative. Calendar text is fully validated before use;
full timestamps require a timezone. No qualification decision reads a clock.
Original records and earlier cuts are immutable; corrections are revisions.

The floor is satisfied only when every source reaches its source-specific
required status, all bindings and authorities stand, no expiry/revocation or
unresolved conflict blocks, and Phase 13 independently permits advancement.
