# Commissioning request — independent security review

This is the canonical commissioning package for the independent security
review of the frozen Alpha candidate. It supersedes the *location* language
in `qualification/phase8/security-review/PACKAGE.md` (which predates the
Phase 9 intake boundary and names `operations/data/independent-reviews.json`
as the landing path); per `qualification/phase9/INTAKE_GOVERNANCE.md`, the
Phase 8 files are historical and are not edited to say so. The Phase 8
technical package — `review-package.json` and its deterministic builder —
remains the finding baseline and is carried into this package unmodified,
pinned by digest in `FINDINGS_BASELINE.json`.

## What is being requested

An **independent security review** of exact bytes: artifact
`e906a48793d7`, image digest
`sha256:c87a6616008ce34f97840f63814e08fdb33574b52202fbb4841b7f5aa7f8562d`,
built from commit `e906a48793d74544b39c14cc3e35e0654f5311e2`, **UNSIGNED**,
frozen since Phase 4 and re-verified from bytes on 2026-08-18.

Do not trust this repository's claim about what you were given.
`ARTIFACT_IDENTITY.json` lists the five digests and how to recompute each
one; **independently verify the digest of the bytes in your hands before
reviewing anything**, and record the digest you computed in your
submission (`independently_computed_digest`). If your bytes do not hash
into that set, stop and say so — that is blocking condition 6, and a
review of other bytes satisfies nothing here.

## What is in this package

| File | Purpose |
| --- | --- |
| `REQUEST.md` | this commissioning request |
| `REVIEW_SCOPE.md` | the frozen review questions (version `SCOPE-1`) |
| `ARTIFACT_IDENTITY.json` | the identity you must independently verify |
| `FINDINGS_BASELINE.json` | the 44 Critical/High baseline findings, with stable internal identifiers, pinned to the Phase 8 package by sha256 |
| `REVIEWER_INSTRUCTIONS.md` | how to review, how to submit |
| `SUBMISSION_SCHEMA.json` | the machine-readable submission contract |
| `VERIFY_SUBMISSION.py` | validates your `record.json` against the contract before you send it |

## Who may review

Anyone **independent** of this repository's release decision: you did not
build the artifact, and you are not the release decision authority (unless
a recorded policy explicitly permits that overlap, which none currently
does). You may use a pseudonymous identifier such as `REVIEWER-001` if
identity handling happens outside the repository; the submission must
still carry your independence declaration. See `REVIEWER_INSTRUCTIONS.md`
§2 and `qualification/phase9/INTAKE_GOVERNANCE.md` — the tooling verifies
that a declaration exists, and a human records whether it is credible;
independence is never manufactured by automation.

## How the submission enters the record

There is exactly one door: the Phase 9 intake
(`qualification/phase9/tools/intake.py register`, source
`security-review`). You produce one machine-readable `record.json`
(contract: `SUBMISSION_SCHEMA.json`; validator: `VERIFY_SUBMISSION.py`)
plus any attachments, and hand them to the project operator, who registers
them. Registration is append-only and sealed; your submission is preserved
verbatim whether it is accepted or not, and a correction is a new revision
beside the original, never an overwrite.

Phase 11 tooling (`qualification/phase11/tools/security_review_ops.py`)
prepares, validates, reconciles, and derives — it appends nothing to the
intake, and nothing in this repository can convert your silence, or its
own analysis, into your approval.

## What happens to your findings

Accepted evidence is reconciled against `FINDINGS_BASELINE.json`
(CONFIRMED / NOT_APPLICABLE / NEW_FINDING / SEVERITY_CHANGED /
SCOPE_CHANGED / EVIDENCE_CONFLICT / REQUIRES_FURTHER_ANALYSIS), and the
derived register `qualification/phase11/security-findings.json` records
every finding's state and disposition. The baseline is historical evidence
and is never silently replaced. If your review requires product changes,
the frozen artifact is not modified: a successor artifact is built,
recorded in the artifact graph, and starts REQUALIFICATION_REQUIRED with
no inherited PASS. If your review requires no product change, nothing is
rebuilt.

## Your outcome

Exactly one of `APPROVED` / `APPROVED_WITH_CONDITIONS` / `BLOCKED` /
`MORE_EVIDENCE_REQUIRED`, bound to the digest you independently computed.
For every condition or blocker: the exact finding, severity, affected
component, evidence, and recommended disposition. Until a submission is
registered and accepted, this gate is NOT_RUN — absence of a review blocks
the release; it never approves it.
