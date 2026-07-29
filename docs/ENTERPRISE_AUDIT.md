# Enterprise audit

Schema: `schemas/fleet-audit.schema.json`. Implementation: `enterprise/audit.py`. Tests: `tests/fleet`, `tests/multitenancy`.

## Recorded

Administrator, organisation, operation, target scope, policy version, time, authorisation method, result, failure code, rollback flag, and correlation id. A `failed` result must carry a failure code.

## Four protections, each implemented

- **Unauthorised modification.** Every entry hashes its own canonical content plus the previous entry's hash. Editing an old entry invalidates it and every entry after it. Canonical form is `json.dumps(..., sort_keys=True, separators=(",", ":"))` over the entry with `entryHash` removed, matching the convention `schemas/README.md` already states for update manifests.
- **Silent deletion.** Entries carry a strictly increasing per-organisation sequence, so a removed entry leaves a detectable gap.
- **Cross-organisation access.** Every entry is organisation-scoped and chains verify per organisation. Verifying tenant A's chain under tenant B's scope fails, and appending a foreign organisation's entry is refused.
- **Secret leakage.** Entries are scanned against `SECRET_KEYS` and `EXCLUDED_CONTENT_KEYS` from `operations/redaction.py` before acceptance.

`verify_chain` returns a report naming the first detected problem rather than raising, so an auditor can see how far the chain verified before it broke.

## Retention and export

Default 400 days, maximum 2555. Export is newline-delimited JSON including the hash chain, one organisation per export; a multi-organisation export is not produced. Expiry removes entries from the head and records a signed truncation marker, so expiry stays distinguishable from tampering. Exports never include secrets, user content, prompts, or memory.

## Not evidenced

No audit chain has been operated at scale, and no export has been ingested by a console, because no console exists. The hash chain is verified by host tests over synthetic entries.
