# Independent security reviewer handoff

This handoff asks for an independent observation and assessment. It does not
ask you to approve a release and does not treat repository claims as proof.

## 1. Artifact under review

The repository expects frozen artifact identifier `e906a48793d7` with
relationship `ROOT` and signing state `UNSIGNED`. The expected image digest is
`sha256:c87a6616008ce34f97840f63814e08fdb33574b52202fbb4841b7f5aa7f8562d`.
Expected ISO, qcow2, OCI archive, and raw-image hashes are listed in
`ARTIFACT_IDENTITY.json` in the prepared handoff package.

The repository's expected digest is not evidence of your observation. Compute
the artifact identity yourself, from the bytes you actually reviewed, and
record how you computed it.

Stop on mismatch. A matching commit, branch, filename, or product version does
not substitute for an artifact digest.

## 2. Independent identity procedure

Hash the exact delivered form before review. For a file, use a sha256 utility.
For the OCI image identity, independently inspect the digest of the archive or
of a digest-pinned load. Record all three of:

- `independently_computed_digest` — your measured value;
- `digest_basis` — `image`, `iso`, `qcow2`, `ociTar`, or `raw`;
- `digest_computation` — the command or method you used.

Do not copy an expected digest into the observation field. A matching value
without the measurement basis and method is retained as
`OBSERVED_UNVERIFIED`, not `VERIFIED`.

## 3. Package and scope

The prepared package contains the Phase 11 request, `REVIEW_SCOPE.md`
(`SCOPE-1`), known limitations, acquisition context, the pinned 44-finding
baseline, reviewer instructions, submission schema and validator, privacy
policy, identity record, and marked examples. `PHASE16_HANDOFF_MANIFEST.json`
pins every byte. Verify those pins before relying on the package.

Answer the eight frozen scope questions in `REVIEW_SCOPE.md`. The baseline is a
starting set, not a ceiling. The unresolved starting point includes eight
Critical and thirty-six High baseline rows; silence about any row leaves it at
its prior state.

## 4. Reporting a baseline reassessment

Add a `findings[]` row using your own stable `reviewer_finding_id` and set
`baseline_advisory` to the public CVE/GHSA identifier. State severity,
affected component, applicability, evidence, rationale, and recommended
disposition. Do not use or guess the repository's internal `SEC-BL-NNN` IDs.

## 5. Reporting a new finding

Add the same complete finding structure and set `baseline_advisory` to `null`.
New findings remain first-class under your identifier. A new Critical remains
blocking until the standing lifecycle has a valid disposition.

## 6. No newly discovered findings

An empty `findings` array is permitted when that is your conclusion, but it
does not close the baseline. State the overall assessment explicitly; silence
is never interpreted as favorable.

## 7. Attachments

Name supporting files in `attachmentDigests` with a sha256 for each exact
file, then submit those files alongside `record.json`. Filenames must be
unique. Intake recomputes each claimed digest. A mismatch or missing attachment
is preserved as a refusal, not repaired.

## 8. What not to submit

Do not include private keys, passwords, passphrases, bearer tokens, API keys,
session tokens/cookies, client secrets, or live credentials in any nested JSON
field or attachment. Redact or replace secrets with non-secret descriptions.
Public key fingerprints are acceptable when they reveal no private material.
Ordinary prose discussing password handling is acceptable; a credential value
is not.

Do not submit the marked examples: they carry `TEST_FIXTURE_ONLY` and real
intake rejects them. Do not add a release `decision`, claim `AUTHORIZED`, or
claim authority you do not hold. Your review assessment and the release
authority decision are different records owned by different boundaries.

## 9. Submission and corrections

Submit the original bytes, all named attachments, your stable reviewer
identifier, and an explicit receipt date to the designated operator. The
operator first runs `inspect`, then `validate`, and only `receive` can carry the
unchanged paths into Phase 9 intake.

If correction is needed, send a complete new package and name the intake ID it
revises. Do not ask for the original to be edited or removed. The original
stays sealed; the new entry derives the earlier one as `SUPERSEDED` only when
the standing revision rules allow it.

Acceptance into the intake means only that your submission crossed the
evidence boundary intact. It is not agreement, not a security approval, and
not a release authorization.

Acceptance also does not mean findings are closed, the Phase 11 gate is
satisfied, the Phase 13 authorization floor is complete, or the candidate may
ship. Those conclusions are independently derived and may remain blocking.
