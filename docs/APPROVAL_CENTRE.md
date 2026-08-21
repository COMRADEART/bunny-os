# Bunny approval centre

The approval centre is a view and handoff surface for Bunny Core and Bunny Companion approval requests. A request must identify action, requesting task, capability, exact resource scope, reversibility, checkpoint availability, system privilege need, affected paths, network/provider destination where applicable, expiry, cost, resource impact, alternatives, and risk. Phase 2 validates bounded identifiers and forbids an `alwaysAllowEverything` field.

The first authoritative visual surface is implemented by the Bunny Companion runtime. Its actions are Approve, Deny, and Cancel task. Each response echoes the original request id, plan id, transition id, local/remote destination, and provider destination; the runtime rejects expiration, superseded plans, replay, or any changed field. High-risk actions still require strong confirmation inside the authoritative Bunny flow. The shell cache cannot grant a capability, write Bunny databases, call a plugin, or bypass the broker. An unanswered request authorizes nothing.

Broker mutations are a separate layer: after Bunny permission, the request still needs an exact contract-1.0.0 method, authenticated Unix peer identity, active user session, and operation-specific Polkit authorization. There is no generic root action.
