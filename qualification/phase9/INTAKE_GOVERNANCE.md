# Phase 9 external-evidence intake governance

Phase 8 made the release question askable; Phase 9 is the boundary where
answers arrive. The flow is fixed: **receive → validate → bind → triage →
remediate if necessary → re-qualify affected artifacts → make an Alpha
release decision.** This file governs the first three steps; `TRIAGE.md`
beside it governs the rest.

## What Phase 9 may and may not do

Phase 9 does **not** create independent security reviews, physical hardware
results, production signatures, second approvals, or Alpha tester feedback.
Those come from their actual owners, whose input packages have been ready
since Phase 8 (`qualification/phase8/`). Phase 9 may validate submitted
evidence, verify provenance and artifact binding, reject malformed evidence,
triage findings, reproduce defects, fix defects, build and qualify a new
artifact when required, and prepare the final Alpha release decision.

Absence of evidence remains **NOT_RUN**. It is never PASS, APPROVED, or
NO ISSUES FOUND. Internal automation validates evidence; it may not
impersonate its source.

## Subject artifact

Every gate binds to **`e906a48793d7`**, image
`sha256:c87a6616008ce34f97840f63814e08fdb33574b52202fbb4841b7f5aa7f8562d`,
ISO `823d50caba35afe72452768affd5f6fa0ac8cfc13c164f0e1bc909fa887ab421`,
qcow2 `497add9a77db2db02bf2541e85b04b0e285c1833d2c8220d193d0d413a6ce867`,
OCI archive `205a77f1b6cdf33915bce3afceb0914d6af25f97b434cf2128aec04d199b43dd`,
raw `a6ee06dcbc0ed3aa22c9ea07c339882eb97c7f16ce906b654c9a1e1119849d46`,
source commit `e906a48793d74544b39c14cc3e35e0654f5311e2`. Frozen; UNSIGNED.
No PASS transfers to any other artifact, and a valid-looking document about
some other artifact satisfies nothing here — the default is **no transfer**,
and any artifact relationship that would justify one must be explicit,
recorded, and decided by a person.

## Intake structure

    qualification/phase9/intake/
        LEDGER.json          the append-only registry (see below)
        security-review/     independent security review submissions
        hardware/            physical hardware run submissions
        signing/             production signing records
        second-approval/     second-approver records
        alpha-feedback/      Alpha tester reports

One submission = one machine-readable `record.json` plus any number of
attachments (logs, transcripts, photographs, detached signatures). Each
registered submission lands in `intake/<source>/<INTAKE-ID>/` and is never
edited afterwards.

## Intake identifiers

Submissions receive `INTAKE-001`, `INTAKE-002`, … in arrival order across
all sources. A corrected resubmission never overwrites the original: it
receives `INTAKE-001-R1`, `INTAKE-001-R2`, … and both are preserved. The
stored entries are immutable; **SUPERSEDED is derived**, never written back —
an entry is reported SUPERSEDED exactly when a later revision of its chain
exists, and its stored record (including its original status and reasons)
stays byte-identical forever.

## The approved append mechanism

`qualification/phase9/tools/intake.py register` is the only way evidence
enters the ledger. It assigns the ID, ingests the files, pins every ingested
byte by size and sha256, runs the mechanical validation below, and appends a
**sealed** entry: the seal is the sha256 of the canonical JSON of the entry
without its seal field. A hand edit to any entry — a status flip, a reworded
reason — breaks its seal; a hand edit to any ingested file breaks its pin;
an unregistered file dropped into `intake/` is an orphan. All three fail
`intake.py verify` and the guard test (`tests/release/test_phase9_intake.py`),
whose negative controls execute those failure branches on every run. The
tool refuses to append to a ledger whose existing seals do not verify.

The tool takes no timestamps from the clock: `--received-on` is stated by
the operator and recorded verbatim, and the commit that lands the entry is
the tamper-evident time.

## Validation before triage

No submitted evidence enters the release decision automatically. Six
questions, answered per submission and stored in its entry:

| Question | What the tool checks mechanically |
| --- | --- |
| Identity | the source-specific identity field is present and non-empty (reviewer; operator + `HW-NNN`; signer identity and authority; two distinct approvers; `T-NNN`) |
| Artifact binding | every digest the record names, normalized, against the subject artifact's five digests |
| Timestamp | the record dates its own action, ISO 8601 |
| Completeness | the required fields for that workstream's record shape |
| Integrity | any digest the record claims for an attachment, recomputed from the ingested bytes |
| Scope | the record answers the question assigned to that workstream, in the allowed vocabulary |

The tool validates what is mechanically checkable and records the rest for
human validation: it can verify that a reviewer is named, not that the name
is real or independent; identity and authority verification is the
operator's judgment, recorded in the triage notes, never manufactured by
automation.

## Evidence status

Every entry receives exactly one stored status:

    ACCEPTED             valid evidence; enters triage
    REJECTED             never valid for this gate (wrong category, key
                         hygiene violation, one person approving twice)
    INCOMPLETE           required fields absent; usable once supplied
    ARTIFACT_MISMATCH    binds to bytes that are not the subject artifact
    UNVERIFIABLE         a claimed digest or record cannot be checked
    SUPERSEDED           (derived only) a later revision exists

Rejected evidence is preserved, never deleted. Every non-ACCEPTED entry
records why, and what would make it usable (`usableIf`).

ACCEPTED means *enters triage* — it is not a gate PASS. A gate row moves
only on a **gate-eligible** entry: `status == ACCEPTED` and binding to the
subject artifact. An Alpha report whose tester cannot establish the digest
is preserved as `USER_EVIDENCE_UNBOUND` — accepted as user evidence, unable
to satisfy or block an artifact-specific gate until reproduction binds it.

## Key hygiene

Private key material never enters qualification evidence. `register` scans
every submitted byte for private-key markers before ingesting anything; on a
hit it ingests **nothing**, appends a REJECTED entry with an empty file
list, and the event itself is the record. This is the one case where
"preserve the evidence" yields — to the absolute rule from
`qualification/phase8/signing/SIGNING_READINESS.md`.

## Digest verification basis

For signing and approval records the submitted digest is compared against
the recorded frozen identity (recomputed from bytes 2026-08-18,
`qualification/phase7/baseline/freeze.log`). When the retained archive is at
hand, verification against recomputed bytes is the stronger basis and is
recorded as such in the entry (`verificationBasis`: `recorded-identity` or
`recomputed-bytes`). A signing command's own success message is neither.

## Phase boundaries

Phase 4–8 trees are historical. No incoming evidence lands in them — not in
`qualification/phase8/alpha/reports/`, not as rows in
`qualification/phase8/hardware-matrix.json`. Those Phase 8 documents remain
as committed; the landing path they name is superseded by this intake
boundary, and the Phase 8 files are not edited to say so. Accepted hardware
rows, review results, and tester findings are recorded under
`qualification/phase9/` citing their intake IDs.
