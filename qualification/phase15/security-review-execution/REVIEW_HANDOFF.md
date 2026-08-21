<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Independent security review — reviewer handoff

This is the complete package an independent reviewer needs to review the
frozen Alpha candidate and submit evidence, without requiring any change
to this repository. It composes the Phase 11 commissioning package
(`qualification/phase11/security-review/`) — which remains canonical —
with the operational instructions Phase 15 adds. Nothing here replaces
the Phase 11 files; where this document and a Phase 11 file both speak,
the Phase 11 file governs the contract and this document governs the
operations.

> **A reviewer may submit an unfavorable result. The intake system is
> not designed to convert that result into a favorable status.** A
> `BLOCKED` review blocks. A review that cannot verify the artifact
> stops. Silence blocks. Nothing in this repository can turn any of
> those into approval.

## 1. The review request

`qualification/phase11/security-review/REQUEST.md` is the commissioning
request: an independent security review of exact bytes — artifact
`e906a48793d7`, image digest
`sha256:c87a6616008ce34f97840f63814e08fdb33574b52202fbb4841b7f5aa7f8562d`,
built from commit `e906a48793d74544b39c14cc3e35e0654f5311e2`, UNSIGNED,
frozen since Phase 4.

## 2. Scope

`qualification/phase11/security-review/REVIEW_SCOPE.md`, version
`SCOPE-1`: eight frozen questions (SQ-1..SQ-8). The scope was frozen
before any response existed and the repository may not remove questions.
You may add findings beyond the baseline at any time.

## 3. Artifact identity — verify it yourself

`qualification/phase11/security-review/ARTIFACT_IDENTITY.json` lists the
five digests of the subject artifact and how to recompute each one.

**Do not trust this repository's claim about what you were given.**
Compute the digest of the bytes in your hands and record it in
`independently_computed_digest`, together with which form you measured
(`digest_basis`) and the exact command you used (`digest_computation`).
The repository-side expected digest is never copied into that field for
you — the field exists so the record shows you measured independently.
Phase 15 derives an identity-ceremony state from your record:

| State | Meaning |
| --- | --- |
| `VERIFIED` | your observed digest matches a subject digest, and you stated how you measured it |
| `OBSERVED_UNVERIFIED` | a digest is present but the measurement method is not stated; recorded, insufficient on its own |
| `MISSING` | no independent observation; the submission cannot advance artifact-specific gates |
| `MISMATCH` | you are holding different bytes — stop and report exactly that |

## 4. Obtaining the artifact

The project operator provides the retained archive (ISO, qcow2, OCI
archive, raw, or image), per `REQUEST.md`. If you cannot obtain the
artifact, or the bytes you obtain do not hash into the five-digest set,
or the artifact does not boot in your environment: **that is a
reportable outcome, not a dead end** — see §10.

## 5. Known limitations

* The artifact is UNSIGNED. Signature verification is a separate,
  pending gate; its absence is recorded, not hidden.
* The 44-finding baseline derives from upstream `fedora-bootc:44`
  advisories; rebase and update paths were exhausted before the freeze
  (see `FINDINGS_BASELINE.json` rows for per-finding dispositions).
* The frozen artifact will not be patched in response to findings: a
  finding that requires product change produces a successor artifact
  that starts requalification from zero.

## 6. Baseline findings

`qualification/phase11/security-review/FINDINGS_BASELINE.json`: 8
Critical + 36 High findings, stable identifiers `SEC-BL-001..044`,
pinned by sha256 to the Phase 8 package. Address baseline rows by their
public advisory identifier (`baseline_advisory`); the internal
identifiers are never required of you. A baseline row your submission
does not address stays in its prior state — your silence about a finding
never dispositions it, in either direction.

## 7. Submission schema and validation

* Contract: `qualification/phase11/security-review/SUBMISSION_SCHEMA.json`
* Validator: `python3 qualification/phase11/security-review/VERIFY_SUBMISSION.py record.json`

Run the validator before submitting; exit 0 means the record satisfies
the contract. Passing is not acceptance — acceptance happens at the
Phase 9 intake boundary, which re-validates and seals what it ingests.

Never include credential material (private keys, tokens, passwords) in
the record or any attachment: the intake scans every byte before
ingesting anything and rejects the whole submission unread on a hit.
Pin every attachment in `attachmentDigests` (sha256); the intake
recomputes those digests and refuses a mismatch.

## 8. Submission examples are not evidence

Example submissions in this phase's `fixtures/` directory are marked,
structurally and visibly:

```text
TEST_FIXTURE_ONLY
NOT EXTERNAL EVIDENCE
NOT APPLICABLE TO THE SUBJECT ARTIFACT
```

A record carrying `fixtureClass: "TEST_FIXTURE_ONLY"` is refused by the
intake mechanically, whatever it is named and whoever submits it. Do not
copy an example and edit it into your submission; write your own record
against the schema.

## 9. Privacy expectations

You may identify by a stable pseudonym (`REVIEWER-001` style); identity
handling may occur outside the repository. What the repository records:
your identifier, your independence declaration, your submission bytes
verbatim, and the operator's human judgment about credibility (in
triage, never manufactured by automation). What the repository refuses:
credential material (rejected unread) and unnecessary personal
information. Everything registered is permanent, public evidence —
submit nothing you do not want preserved.

## 10. Every outcome is a valid submission

* **You find nothing new**: submit with your assessment and per-question
  scope answers. An empty findings list is a real result — but note it
  closes nothing by itself; baseline rows need per-finding evidence to
  move.
* **You cannot reproduce a baseline finding**: report the finding with
  `applicability` and the analysis that grounds it. "Not exploitable"
  without analysis is held at `REQUIRES_FURTHER_ANALYSIS`, not accepted.
* **You cannot obtain or boot the artifact**: submit
  `MORE_EVIDENCE_REQUIRED` stating exactly what failed, or tell the
  operator and decline. A review of other bytes satisfies nothing here;
  saying so is a useful, preserved result.
* **You find new problems**: report them with your own
  `reviewer_finding_id`s and `baseline_advisory: null`. New findings are
  first-class: they enter the register, they can block, and they are
  never suppressed to preserve prior readiness language.
* **You conclude unfavorably**: submit `BLOCKED`. It is preserved
  verbatim, it blocks, and no local operation can overrule it.

## 11. How to submit

Hand `record.json` plus attachments to the project operator. The only
door is:

```text
python qualification/phase9/tools/intake.py register \
    --source security-review --record record.json \
    [--attach FILE]... --received-on YYYY-MM-DD \
    --submitted-by <your identifier>
```

You receive an intake ID (`INTAKE-NNN`). Your submission is preserved
byte-for-byte whether it is accepted, rejected, incomplete, or
mismatched.

## 12. How to submit a revision

A correction is a **new revision beside the original, never an
overwrite**: the operator registers it with `--revises INTAKE-NNN`, it
receives `INTAKE-NNN-R1` (then `-R2`, …), and the original entry and its
bytes stay exactly as sealed. Derived views report the original as
SUPERSEDED; the ledger never rewrites it. A revision registered after an
evidence cut does not enter that historical cut — it is included from
the next cut forward.

## 13. What happens to your submission

Received → validated at the Phase 9 boundary (identity, artifact
binding, timestamp, completeness, integrity, scope; credential hygiene
first) → contract-checked against the Phase 11 schema → reconciled
against the baseline → recorded in the derived register with a receipt
state (`RECEIPT_PROTOCOL.md`). If another independent reviewer disagrees
with you, both submissions stand; the conflict is recorded and requires
an explicit human decision — never an average, never the friendlier
answer.
