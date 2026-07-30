<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Independent security review request

**Status: prepared and not sent. No reviewer has been identified and no completion
date exists.**

The request itself is `reviews/security/REQUEST.md`. This page records its state
and what it would unblock, so the two do not drift.

## What is being asked for

A per-CVE determination of whether **24 Critical and High vulnerability findings**
are reachable in a Bunny OS deployment, plus a review of the privileged broker, the
update trust chain, the installer secret channel, the SELinux domains, and the
Phase 7 boundaries.

The vulnerability question is the priority and the rest is secondary to it.

## Why this review and no other route

**This is the only route by which any Critical finding can become non-blocking.**
Both `release/vulnerability.py` and `release/cve.py` reject a non-blocking Critical
disposition that does not reference a completed independent review, at parse time.
`reviews/security/REQUEST.md` states the same thing to the reviewer.

The alternative — Fedora rebuilding podman, skopeo and bootc against patched Go
modules — makes the question moot but is not something the project can cause. A
base rebuild was observed on 2026-07-29 without the counts moving, so "wait for
Fedora" is no longer a plan with a date attached. See
`docs/adr/ADR-027-base-image-security-decision.md`.

## What the request contains

| Section | Substance |
|---|---|
| Exact scope | 6 items in scope, 4 explicitly out |
| Commit | evidence baseline `80df25b09f65…`; the reviewer records the commit they are given |
| Artifacts | 24 bundles × 9 files, the raw grype scan, four evidence files, six design documents |
| Threat model | 5 adversaries, and 2 explicitly excluded |
| Questions | 8, ordered by consequence, with the per-advisory sub-questions in each bundle |
| Expected report format | Markdown or PDF plus a record conforming to `independent-review-record.schema.json` |
| Severity model | 5 levels, with an instruction not to downgrade for base-image origin |
| Expected independence statement | 4 things the reviewer must state in their own words |
| Confidentiality | 90-day embargo or until remediated, whichever is sooner |
| Prohibited claims | 6, including "certified" and any conclusion drawn from a symbol table alone |

## The three questions most worth the reviewer's time

1. **Is the vulnerable code path compiled into the installed binary, and active or
   invocable?** Per advisory. Nine of the ten bounded questions are already
   answered with measured evidence; this is the tenth.
2. **Which of the three installed Go binaries carries each module?** The scan
   records four ostree object digests, not paths. The project has recorded
   `unknown` rather than guess.
3. **Is `GO-2026-5970`'s carrier the removed `toolbox` binary?** If so, that
   advisory has no installed executable to invoke and its analysis differs from the
   other 23.

## What it would unblock

| Unblocked | Currently |
|---|---|
| The `vulnerability-gate` candidate prerequisite | `PENDING_EXTERNAL_REVIEW` — 24 advisories `Unknown` |
| The `Vulnerability` evidence category | `FAIL` |
| `vulnerability-position` on the stable gate | `BLOCKED` |
| Any disposition of any Critical finding | impossible without it |

It does **not** unblock the stable gate. Nine other requirements are unmet.

## Intake

On delivery:

1. Place the report in `reviews/security/`.
2. Record the reviewer's signed `IndependentReviewRecord` in
   `operations/data/independent-reviews.json` under `records`.
3. Run `python scripts/release.py validate-independent-reviews`.

Intake recomputes `reportDigest` from the file, rejects an unsigned record, rejects
a scope commit other than the candidate commit, and rejects any reviewer whose name
or organisation matches a project principal.

## Cost

Not estimated. Per-CVE symbol and call-graph analysis of two stripped Go binaries
totalling 71 MB is specialist work and the project has no basis for a figure.
Whether to fund it is an owner decision, recorded as such in
`docs/QUALIFICATION_EVIDENCE_BASELINE.md`.
