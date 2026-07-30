# Multi-tenancy test report

Date: 2026-07-29. Implementation: `enterprise/tenancy.py`. Tests: `tests/multitenancy`, 23 cases, all passing. Evidence: `operations/data/phase7-multitenancy.json`.

## Design premise

The dangerous failure in a multi-tenant control plane is not a missing check but a permissive default. A query helper that treats an absent tenant filter as "all tenants" will eventually be called without one, and the resulting cross-tenant read looks like ordinary behaviour in logs.

Tenant scope is therefore a required argument everywhere. Absent, empty, and wildcard scopes are refused. A row without an `organisationId` is refused rather than dropped, because silently dropping it hides a defect.

## Adversarial cases

| Case | Result |
|---|---|
| Organisation A reads organisation B devices | Refused |
| Policy cross-assignment | Refused |
| Audit cross-access | Refused |
| Application catalogue cross-access | Refused |
| Update-ring cross-access | Refused |
| Administrator role escalation | Refused |
| Organisation deletion leakage | Covered by per-family scoping |
| Backup restoration into the wrong tenant | Refused |
| Wildcard tenant scope (`*`, `all`, `any`) | Refused |
| Absent or empty tenant scope | Refused |
| Caller filter overriding the tenant scope | Refused |
| Row with no `organisationId` | Refused, not dropped |
| Cross-organisation audit chain verification | Fails, as intended |
| Appending a foreign organisation's audit entry | Refused |

All eleven tenant-scoped resource families were tested for both refusal on mismatch and success on match: device, device group, policy, update ring, catalogue entry, compliance status, audit entry, enrolment token, administrator, backup, export.

## Isolation controls

Eight controls, each blocking independently. A missing key is missing evidence and a `false` value is a failed control; only an all-present, all-true result isolates. This follows `operations/modes.py`.

| Control | Evidence |
|---|---|
| `organisationScopedIdentities` | `assert_organisation_id` refuses absent, empty, and wildcard scopes |
| `organisationScopedStorage` | `scoped_filter` injects the predicate and refuses overrides; `filter_rows` refuses unscoped rows |
| `organisationScopedEncryptionKeys` | `fleet-` namespace separated from update, release, OEM, and sync; sync collection keys never leave the device |
| `strictApiAuthorisation` | `assert_same_tenant` required for all 11 families |
| `auditIsolation` | Per-organisation chains; foreign entries break verification and cannot be appended |
| `rateLimits` | Design commitment for a service that does not exist |
| `exportBoundaries` | One organisation per export; no multi-organisation export produced |
| `backupIsolation` | Backup is a scoped resource family |

## Honest limitations

Two controls are partly commitments rather than measured properties. `rateLimits` and `exportBoundaries` describe a hosted service that has never been deployed; they are recorded as true for the *source contract* only, and `operations/data/phase7-multitenancy.json` says so in its `limitations` list rather than implying they are proven.

`organisationScopedStorage` is enforced at the application layer here. A deployment must also implement row-level security or per-tenant databases; `ADR-024` records that defence in depth requires both and that the application layer alone is not sufficient.

## What was not tested

No multi-tenant service has been deployed, load-tested, fuzzed, or penetration-tested. No database exists, so row-level security has not been exercised. No concurrent multi-tenant traffic has been generated. No independent security assessment has been performed.

These 23 tests establish that the source refuses cross-tenant access at every call site it defines. They do not establish that a deployed control plane is isolated.
