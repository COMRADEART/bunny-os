# Reviewer instructions

You are reviewing exact bytes, not a repository. Everything below serves
four properties: your review is bound to the artifact you actually held,
your independence is declared and recorded, your findings survive intake
byte-for-byte whatever they say, and nothing in this project can turn your
silence into approval.

## 1. Verify the artifact yourself

Obtain the artifact bytes (the project operator provides the retained
archive: ISO, qcow2, OCI archive, raw, or the image). Compute the digest
of what you were given — `ARTIFACT_IDENTITY.json` says how per form — and
compare it against the five digests listed there.

* Match: record that digest in `independently_computed_digest`, and which
  form in `digest_basis`.
* No match: **stop reviewing**. Submit with `overall_assessment:
  "MORE_EVIDENCE_REQUIRED"`, state the digest you computed, or simply
  refuse and tell the operator. Reviewing other bytes helps nobody.

Do not take this repository's word for identity — the field exists so the
record shows you didn't.

## 2. Declare independence

Fill `independence.declaration` in your own words: you had no role in
producing this artifact and no interest in its approval. Disclose any
relationship in `relationship_to_project`. You may identify as a stable
pseudonym (`REVIEWER-001` style) if identity handling happens outside the
repository — the project records the identifier and the operator records,
as a human judgment, whether the identity and independence claims are
credible. If you are also the release decision authority, say so; that
overlap is refused unless a recorded policy permits it, and none does.

## 3. Review under the frozen scope

`REVIEW_SCOPE.md`, version `SCOPE-1` — eight questions, frozen before any
response existed. Answer them against `FINDINGS_BASELINE.json` (the 44
Critical/High baseline). You may add findings beyond the baseline at any
time; the project may not remove questions.

For each finding you report:

* `baseline_advisory`: the GHSA/CVE identifier of the baseline row you are
  addressing, or `null` for a new finding. Use your own
  `reviewer_finding_id` scheme — the project's internal identifiers are
  never required of you; the project maintains the mapping.
* `applicability` with `evidence` and `rationale`: what you ran, what you
  read, why it establishes the conclusion. A bare "not exploitable" is
  held at REQUIRES_FURTHER_ANALYSIS rather than accepted — if you claim
  NOT_APPLICABLE, show the analysis.
* `recommended_disposition`: your recommendation. Dispositions are decided
  on the project side under the committed policy (a confirmed Critical
  admits only FIX_BEFORE_ALPHA, ACCEPTED_RISK with a named authority and
  expiry, or NOT_APPLICABLE with establishing evidence).

Attach anything load-bearing (logs, scan output, analysis notes) and pin
each attachment in `attachmentDigests` — the intake recomputes those
digests from the ingested bytes and refuses a mismatch. Never include
private key material; the intake rejects the whole submission unread.

## 4. Produce and check the record

One `record.json` per the contract (`SUBMISSION_SCHEMA.json`). Then:

    python3 VERIFY_SUBMISSION.py record.json

Fix everything it lists. Passing is a precondition of usefulness, not
acceptance: acceptance happens at the Phase 9 intake, which re-validates
mechanically and seals what it ingests.

## 5. Submit

Hand `record.json` plus attachments to the project operator, who registers
them (`qualification/phase9/tools/intake.py register --source
security-review`). You receive an intake ID. Your submission is preserved
verbatim — accepted, rejected, or incomplete — and a correction is a new
revision beside the original, never an overwrite. If another independent
reviewer disagrees with you, both submissions stand; the project records
the conflict and resolves it explicitly, never by averaging and never by
picking the friendlier answer.

## 6. What your outcome moves

`APPROVED` / `APPROVED_WITH_CONDITIONS` / `BLOCKED` /
`MORE_EVIDENCE_REQUIRED`. Your accepted evidence is reconciled against the
baseline, drives the security finding register
(`qualification/phase11/security-findings.json`), and recomputes the
release blocking conditions. It never edits history: the baseline stays,
your submission stays, and if your findings require product changes the
frozen artifact is not patched — a successor artifact is built and starts
its qualification from zero.
