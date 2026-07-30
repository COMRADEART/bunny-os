# ADR-024: Multi-tenant isolation

- Status: accepted as design; no multi-tenant service has been deployed
- Date: 2026-07-29

## Decision

Tenant scope is a required argument everywhere, never an optional filter. `assert_organisation_id` refuses absent, empty, and wildcard scopes; `scoped_filter` injects the tenant predicate and refuses a caller filter that tries to override it; `filter_rows` refuses a row with no `organisationId` rather than treating it as unscoped. Eleven resource families must pass `assert_same_tenant`.

Audit chains are per-organisation. Verifying tenant A's chain under tenant B's scope fails, and appending a foreign organisation's entry to a chain is refused.

Eight isolation controls are recorded as evidence in `operations/data/phase7-multitenancy.json` and evaluated by `evaluate_isolation`, following the `operations/modes.py` pattern where a missing key is missing evidence rather than a pass.

## Why the default matters more than the check

The dangerous failure in a multi-tenant control plane is not a missing check but a permissive default. A query helper that treats an absent tenant filter as "all tenants" will eventually be called without one, and the resulting cross-tenant read looks like normal behaviour in logs. Making the scope a required parameter converts that class of bug from a silent data leak into a crash at the call site.

*Row-level security alone* was rejected as the sole control: it is correct and necessary, but it lives in the database and does not protect exports, backups, caches, or audit verification. The application layer must carry the scope too.

*A shared database with a tenant column and application-side filtering* was rejected as the *only* mechanism for the same reason — defence in depth requires both, and the ADR records the intent that a deployment implement organisation-scoped storage as well.

## Consequences

Eight adversarial cases are tested: cross-tenant device, policy, audit, catalogue, ring, and backup access, administrator role escalation, and unscoped or wildcard queries. They pass at source level.

That is the limit of the claim. No control plane has been deployed, load-tested, or penetration-tested, and `rateLimits` and `exportBoundaries` are recorded as commitments about a service that does not exist. `operations/data/phase7-multitenancy.json` states these limitations rather than implying the controls are proven in production.
