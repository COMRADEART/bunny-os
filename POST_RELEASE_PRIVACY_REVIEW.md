# Post-release privacy review

Date: 2026-07-29. Status: **not applicable; no release has been published and no user data has ever been received.**

## Current position

Zero devices in the field. Zero diagnostic bundles received. Zero crash reports received. Zero feedback reports ingested — `operations/data/issue-ledger.json` holds zero issues and records `observationPeriod: "unknown"`.

There is no upload endpoint, no telemetry, and no advertising identifier, so there is no passive collection to review either.

## What this review will examine, once there is a release

| Area | Question it must answer |
|---|---|
| Actual collection | What data actually reached the project, as opposed to what the design permits |
| Redaction in practice | Whether the deterministic redactor held against real reports, and what it missed |
| Diagnostic bundles | Whether any bundle contained something it should not, verified by human inspection |
| Network behaviour | Whether any device made a connection the documentation does not explain |
| Cross-user exposure | Whether any multi-user installation leaked between accounts |
| Retention | Whether the 14-day and 30-day expiries actually fired |
| Deletion requests | How many were received and whether they were honoured within the stated bound |
| Default drift | Whether any update silently changed a privacy default |

The last row is the one a project is least likely to catch in itself.

## What is ready

The intake path, and it is the strongest part of the system. Redaction is deterministic and regression-tested. Crash reports are limited to seven fields by exact-set equality with no persistent user identifier. Diagnostic export is local, opt-in and mode 0600 with no upload endpoint. Content and secret fields are refused outright rather than scrubbed.

If a release shipped tomorrow, user data would be handled correctly. That is a design claim verified by tests, not an operational claim verified by experience.

## The gap that will not close by itself

`docs/DIAGNOSTIC_SAFETY.md` requires two stages: automated redaction checks over fixtures, and trained human review of a sample bundle in an isolated environment. The first is implemented and runs in the gate. **The second has never been performed, because no sample bundle has ever existed.**

That gap cannot be closed by more automated testing. It requires a real bundle from a real system and a person to look at it.

## Independence

No independent privacy assessment has been commissioned. This would be a self-review.
