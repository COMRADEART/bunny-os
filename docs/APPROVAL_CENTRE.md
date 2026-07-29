# Bunny approval centre

The approval centre is a view and handoff surface for Bunny Core approval requests. A request must identify action, requesting task, capability, exact resource scope, reversibility, checkpoint availability, system privilege need, affected paths, network destination where applicable, expiry, and risk. Phase 2 validates bounded identifiers and forbids an `alwaysAllowEverything` field.

Allowed decisions are Allow once, Allow exact resource, Allow for task, Deny, Inspect details, and Open Bunny. High-risk actions require a strong confirmation inside the authoritative Bunny flow. The shell cache cannot grant a capability, write Bunny databases, call a plugin, or bypass the Phase 1 broker. Expired/stale requests must be rejected by Core even if still visible in a stale shell snapshot.

Broker mutations are a separate layer: after Bunny permission, the request still needs an exact contract-1.0.0 method, authenticated Unix peer identity, active user session, and operation-specific Polkit authorization. There is no generic root action.
