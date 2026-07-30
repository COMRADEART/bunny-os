# Public beta privacy review

Date: 2026-07-29. Result: **the privacy design is ready; the beta is not.**

Unusually for this project, privacy is the area in the best shape. That is worth stating precisely rather than letting it be lost among the blockers.

## What a beta would collect

Nothing automatically. There is no telemetry, no upload endpoint, no advertising identifier, no persistent tracking id, and no background reporting. `telemetryEnabled` is pinned to `false` in the settings schema and `diagnosticsPolicy` has exactly one legal value, `local-only`.

A participant who chooses to report a problem produces:

| Data | Handling |
|---|---|
| A written report | Redacted before storage by `operations/redaction.py` |
| A crash record | Exactly seven fields: component, version, architecture, stack signature, driver, kernel, deployment version. No persistent user id. Exact-set equality, so an eighth field is a rejection |
| A diagnostic bundle | Local, opt-in, mode 0600, owned by the requesting user, 14-day expiry. No upload endpoint is enabled |

## Redaction, verified

`operations/redaction.py` deterministically removes email addresses, IPv4 addresses, MAC addresses, token-shaped strings, home directory paths, hostnames, phone numbers, Wi-Fi SSIDs and recovery-key-shaped values, and refuses content and secret keys outright rather than redacting them. `tests/operations/test_redaction.py` covers this and runs in every gate.

The refusal behaviour matters more than the substitution behaviour: prompts, memories, documents and clipboard content are not scrubbed and stored, they are rejected.

## Findings

**Blocker — no participants, so no consent flow has been exercised.** The design says a beta participant is told what a report contains before sending it. That text has never been shown to anyone.

**Major — the diagnostic-safety second stage has never run.** `docs/DIAGNOSTIC_SAFETY.md` requires automated redaction checks *and* trained human review of a sample bundle in an isolated environment. No sample bundle has been manually inspected, because none exists.

**Major — no network capture on an installed system.** `NETWORK_PRIVACY_TEST_REPORT.md` records a quiet capture against a booted image, but not against an installed system doing real work over time.

**Accepted — no cross-user exposure path was found in source.** Per-user XDG state, per-user Secret Service items, and `assert_private_file` ownership and mode checks. Not verified on an installed multi-user system.

## What was not reviewed

Any real participant data, because none has ever been received. No independent privacy assessment has been commissioned.
