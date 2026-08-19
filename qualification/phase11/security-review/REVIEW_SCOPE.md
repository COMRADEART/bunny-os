# Review scope — frozen before any reviewer response

Version: **SCOPE-1**

This scope was committed before any reviewer submission existed. The
freeze is one-directional: **the repository may not remove or weaken a
question after the review begins; the reviewer may add findings at any
time.** A submission answers this scope by naming `review_scope_version:
"SCOPE-1"`; if a later scope version ever adds questions, earlier versions
remain valid for submissions already in flight, and no question below is
ever deleted from this file — a superseding version appends.

Subject: artifact `e906a48793d7` only. Every question is about those exact
bytes (`ARTIFACT_IDENTITY.json`), not about the repository, a branch, or a
newer build.

## The frozen questions

| # | Question |
| --- | --- |
| SQ-1 | Are the 8 Critical findings applicable? (`FINDINGS_BASELINE.json`, severity Critical) |
| SQ-2 | Are the 36 High findings applicable? (`FINDINGS_BASELINE.json`, severity High) |
| SQ-3 | Are any findings incorrectly classified? (severity or category wrong in the baseline) |
| SQ-4 | Are any findings missing? (issues present in the artifact that the baseline does not list) |
| SQ-5 | Are vulnerable functions actually reachable in the shipped binaries? (the baseline carries symbol-presence per binary for the Criticals; presence is not reachability) |
| SQ-6 | Does package presence imply exploitability? (the project has explicitly not collapsed one into the other; the reviewer's answer is the evidence) |
| SQ-7 | Does the artifact contain an unreviewed attack surface? (anything outside the 44-finding baseline's frame — services, defaults, update posture) |
| SQ-8 | Are any findings release-blocking for the declared Alpha scope? (`qualification/phase8/alpha/RELEASE_SCOPE.md`, `ALPHA_KNOWN_LIMITATIONS.md`; note: an installed Alpha receives no security updates — `UPDATE_TRUST_ARCHITECTURE_DECISION.md`) |

## What the project already measured, and where

* Baseline inventory and per-binary analysis: `FINDINGS_BASELINE.json`
  here, derived from `qualification/phase8/security-review/review-package.json`
  (deterministic builder `build_package.py`; rerun and diff).
* Named-vulnerable-symbol presence per binary for the 8 Criticals:
  `qualification/phase6/security/evidence/symbols.json` + `symbol_probe.py`.
* Exposure probes: `qualification/phase6/security/evidence/exposure.json`.
* The one advisory where the project explicitly offers no view (grpc
  server-side Critical): `qualification/phase6/security/REVIEW_PACKAGE.md` §4.
* A correction to read before trusting older evidence:
  `qualification/phase6/security/PIPEFAIL_CORRECTION.md`.

## What an answer must look like

Findings, with evidence, in the submission contract
(`SUBMISSION_SCHEMA.json`) — per finding: applicability, evidence,
rationale, recommended disposition. "Not exploitable" without supporting
analysis is not sufficient to establish NOT_APPLICABLE, and the register
will hold such an answer at REQUIRES_FURTHER_ANALYSIS rather than closing
anything on it.
