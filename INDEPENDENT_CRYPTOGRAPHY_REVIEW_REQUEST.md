<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Independent cryptography review request

**Status: prepared and not sent. No reviewer has been identified and no completion
date exists.**

The request itself is `reviews/cryptography/REQUEST.md`.

## What is being asked for

A review of the **designed, implemented, and never operated** encrypted
synchronisation subsystem: the envelope format, the key hierarchy, device pairing,
account recovery, deletion semantics, device revocation, and the release signing
design.

Not a review of a service. There is no service.

## Why this review and no other route

`gate-sync-pilot` lists `independentCryptographicReview` as a requirement and it is
unmet. **The sync pilot cannot proceed on any other basis**, regardless of how the
stable release goes, and it has six other unmet requirements besides.

The project contains `ENCRYPTED_SYNC_SECURITY_REVIEW.md` and
`ENCRYPTED_SYNC_PRIVACY_REVIEW.md`. Both are internal. `release/reviews.py` rejects
any reviewer whose name or organisation matches a project principal, so neither can
be recorded as independent — which is correct, and is why this request exists.

## What the request contains

| Section | Substance |
|---|---|
| Exact scope | 7 items in scope, 4 explicitly out including disk encryption's primitives |
| Commit | evidence baseline `80df25b09f65…` |
| Artifacts | `sync/`, the wire schema, 7 design documents, 2 test suites, 3 internal reviews marked as belief rather than evidence |
| Threat model | 6 adversaries, honest-but-curious and actively malicious server separated, 2 exclusions |
| Questions | 10, from envelope soundness to whether recovery is a backdoor |
| Expected report format | record conforming to `independent-review-record.schema.json`, signed |
| Severity model | 5 levels defined against plaintext exposure and forgeability |
| Expected independence statement | 3 things in the reviewer's own words |
| Confidentiality | 90-day embargo; no user data exists |
| Prohibited claims | 5, including "zero-knowledge" as a bare conclusion and any claim about an operated service |

## The three questions most worth the reviewer's time

1. **Is account recovery a backdoor?** Does the recovery path give the server, or
   anyone holding the recovery secret alone, access to content?
2. **Can the server roll back or suppress?** Serve a stale version, roll back a
   collection, suppress a deletion, or substitute a device key — and is there a
   construction that would let a client detect it?
3. **Is deletion cryptographic or nominal?** If a key is destroyed, is the
   ciphertext genuinely unrecoverable, and do the disclosed retention bounds
   describe what actually happens?

## What it would unblock

| Unblocked | Currently |
|---|---|
| `independentCryptographicReview` on `gate-sync-pilot` | unmet |
| Confidence in the signing role separation and the rotation-overlap rule | internal assessment only |

It does **not** unblock `gate-sync-pilot`, which additionally requires an operated
sync service, a key-recovery drill, a deletion drill, a service privacy review, a
data-residency disclosure, a named incident-response owner, **and** a passing stable
gate.

## The best time to have a bad answer

The subsystem is not deployed and has no users. A `fail` or `conditional`
conclusion costs nothing now and would cost a great deal after a launch. The
project's recommendation remains to operate no Phase 7 capability, and a negative
review would confirm rather than disrupt that.

## Intake

As for the security review: place the report in `reviews/cryptography/`, record the
signed `IndependentReviewRecord`, run `validate-independent-reviews`. The digest is
recomputed from the file and an unsigned record is rejected.
