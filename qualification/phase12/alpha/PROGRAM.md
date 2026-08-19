# Bunny OS Alpha tester program

This is the canonical package for the Alpha tester workflow. It
operationalizes the Phase 8 program design
(`qualification/phase8/alpha/OPERATIONS.md`) against the evidence
boundaries built in Phases 9–11; the Phase 8 and Phase 7 sources it reuses
are pinned by sha256 in `PHASE8_PINS.json`, and the tooling fails closed if
any pinned source changes. The Phase 8 files themselves are historical and
are not edited; the landing path they name
(`qualification/phase8/alpha/reports/`) was superseded by the Phase 9
intake, per `qualification/phase9/INTAKE_GOVERNANCE.md`.

## What the program is

Real people run the exact frozen artifact `e906a48793d7` on their own
machines and report what actually happened — successes, failures, bugs,
confusion, delight. Their experience is evidence. It is preserved
verbatim, bound to the digest they themselves observed, classified without
being rewritten, and reconciled into a derived finding register. It is
never inflated: one successful installation is one successful observed
installation, not "supported on PCs"; a report nobody could reproduce
remains valid user evidence, not an invalid one; and zero reports are
recorded as zero, never as favorable silence.

## The package

| File | For |
| --- | --- |
| `PROGRAM.md` | this overview |
| `TESTER_SCOPE.md` | what this Alpha is qualified on — where the edge of the map is |
| `TESTER_LIMITATIONS.md` | the practical consequences, translated for the person running it |
| `GETTING_STARTED.md` | enrolment, artifact verification, the journeys |
| `ARTIFACT_VERIFICATION.md` | how to independently identify what you are running |
| `REPORTING.md` | how to write and submit a report |
| `TESTER_REPORT_SCHEMA.json` | the machine-readable report contract |
| `VERIFY_TESTER_REPORT.py` | checks your report against the contract before you send it |
| `REPRODUCTION_PROTOCOL.md` | what the project does with a report it tries to reproduce |
| `TRIAGE_POLICY.md` | how reports become findings, and what never happens to them |
| `PRIVACY_POLICY.md` | what the program refuses to collect, and the credential scan |
| `ARTIFACT_IDENTITY.json` | the digests, with recomputation instructions |
| `PHASE8_PINS.json` | sha256 pins of the reused Phase 7/8 sources |

## The boundaries (fixed before any tester exists)

* **One evidence door.** Reports enter through the Phase 9 intake
  (`qualification/phase9/tools/intake.py register --source
  alpha-feedback`), are sealed and pinned, and are never edited or
  overwritten afterwards — a correction is a new revision beside the
  original.
* **Digest-bound or honestly unbound.** A report carrying the digest the
  tester observed binds to the artifact; a report without one is preserved
  as `USER_EVIDENCE_UNBOUND` — visible, investigable, and unable to move
  any artifact-specific gate until a revision binds it.
* **User evidence is not measurement.** "The desktop felt slow" is
  USER_REPORTED; it becomes MEASURED or REPRODUCED only when someone
  measures or reproduces it. Neither direction is ever inferred.
* **Installation is not qualification.** Success reports accumulate as
  observed evidence; PASS in the hardware matrix still requires the
  committed protocol (`qualification/phase8/hardware/PROTOCOL.md`).
* **Nothing closes on convenience.** "We could not reproduce it" records a
  reproduction attempt; it closes nothing. Negative feedback is preserved
  with the same machinery as positive.
* **No consensus synthesis.** Testers are never merged into one synthetic
  voice; every derived finding names its source reports.
* **Privacy floor.** Testers are `T-NNN`; no real name, email, IP,
  address, government identity, or hardware serial enters evidence, and
  submissions are scanned for likely credentials before a byte is
  ingested (`PRIVACY_POLICY.md`).

## Current program state

Derived, never asserted: `qualification/phase12/alpha-findings.json`
carries the program state, the evidence counts, and the sufficiency
determination, recomputed from the intake ledger and the committed policy
on every sync. Zero enrolled testers and zero reports derive
`READY_FOR_TESTERS` — the program is open, and silence advances nothing.
