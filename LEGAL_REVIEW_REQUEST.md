<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Legal review request

**Status: prepared and not sent. No reviewer has been identified and no completion
date exists.**

The request itself is `reviews/legal/REQUEST.md`.

## What is being asked for

An opinion on outbound licence compatibility, the GPL-3.0 anti-tivoisation
question, the Apache-2.0 / GPL-3.0 boundary, the trademark position, third-party
notices, and the base image's redistribution terms.

## The state this request exists in

The licence **gate passes**: seven mechanical requirements are met, there is a root
`LICENSE`, eight per-directory declarations, 127 SPDX headers, and a clean
6,077-record scan.

What has not happened is a lawyer reading any of it.

## Why this review and no other route

Two questions are load-bearing, and one gates a programme:

> **Do the GPL-3.0 anti-tivoisation terms conflict with shipping Secure Boot with a
> vendor-controlled key on OEM hardware?**

The licence gate passes without an answer. **No OEM agreement should be signed with
it outstanding**, and that is recorded in `INDEPENDENT_REVIEW_STATUS.md` and in the
OEM pilot's `brandingAndLicensingApproval` requirement.

> **Is "Bunny OS" registrable and defensible?**

`docs/TRADEMARK_POLICY_DRAFT.md` is a draft written by an engineer. The project has
no basis for an opinion on it.

## What the request contains

| Section | Substance |
|---|---|
| Exact scope | 6 items in scope, 4 explicitly out including privacy law and patent clearance |
| Commit | evidence baseline `80df25b09f65…` |
| Artifacts | the root and eight per-directory licences, the owner's recorded decision, the 6,077-record scan, the policy file, both trademark documents, and the Secure Boot and OEM models the anti-tivoisation question bears on |
| Threat model | 5 ways the project could be legally wrong, framed as failure modes rather than adversaries |
| Questions | 8, ordered by consequence |
| Expected report format | a written opinion plus a signed record; jurisdiction named where it matters |
| Severity model | 5 levels, from "cannot lawfully distribute" to a drafting improvement |
| Expected independence statement | 3 things, plus a request to disclose any conflict |
| Confidentiality | the opinion is the project's to publish or withhold; privileged parts may be marked |
| Prohibited claims | 5, including a bare "the licensing is fine" that does not address the anti-tivoisation question |

## What it would unblock

| Unblocked | Currently |
|---|---|
| The `legal` independent review | package prepared, zero commissioned |
| `brandingAndLicensingApproval` on `gate-oem-pilot` | unmet |
| Confidence in the outbound position against 6,077 inbound licences | mechanically checked against a policy file, which is not a legal opinion |
| Publishing a trademark policy rather than a draft | draft only |

It does **not** unblock `gate-oem-pilot`, which additionally requires a qualified
hardware model, OEM recovery validation, a signed OEM profile, factory finalisation
on real hardware, a named support owner, **and** a passing stable gate.

## The likely outcome

A `conditional` conclusion naming the anti-tivoisation question as the condition
would be a useful and unsurprising result. The project would rather record an
unsettled question than a confident answer that is wrong, and has said so in the
request.

## Intake

Place the opinion in `reviews/legal/`, record the signed
`IndependentReviewRecord`, and run `python scripts/release.py
validate-independent-reviews`. If any part of the opinion should remain privileged,
mark it: the project will honour that and publish the rest.
