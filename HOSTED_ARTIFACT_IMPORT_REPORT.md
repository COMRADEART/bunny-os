<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Hosted artifact import report

How evidence produced somewhere this repository does not control was checked
before it was allowed to count, and what checking it established.

| | |
| --- | --- |
| Candidate commit | `9ea5459bdaf122f8c5999683b2c8961555826954` |
| Base image | `quay.io/fedora/fedora-bootc:44@sha256:c466de539ec94fe2ea996785b8cda08b274316cd6bf21d5e13bd4d9a7f7aee5b` |
| Import command | `python scripts/release.py import-hosted-builder-evidence` |
| Implementation | `release/hosted.py` |

The evidence was imported through a command, not by editing
`operations/data/builders.json`. That is the point of the command: every field
the hosted record claims about itself is cross-checked against another file in
the same bundle, and hand-editing the JSON skips all of it.

## What is checked, and against what

The bundle is not a single document to be trusted or rejected. It is eight files
that must agree, and each check names the *other* file that would have to be
edited consistently for a claim to survive.

| The record claims | Checked against | Catches |
| --- | --- | --- |
| `workflowRunId` | `runner-environment.txt`, written by the runner before the build | a run id edited into the record |
| `workflowRunId` | `ci-provenance.json` | the same, from the other direction |
| `kernelVersion` | `runner-environment.txt` | a builder claiming a different machine |
| `operatingSystem` | `runner-environment.txt` | the same |
| `runnerEnvironment` | must be `github-hosted` | a self-hosted runner, which shares an administrator with this project |
| `sourceCommit` | the candidate commit, and `ci-provenance.json`, and the build provenance | evidence from another commit |
| `baseImageDigest` | the expected digest, and `ci-provenance.json` | two builders on different bases, which are not comparable |
| `rawDigest` | `artifact-manifest.sha256`, from `sha256sum` | a digest edited into the normalisation record |
| SBOM package count | `package-inventory.txt` | two files describing different builds |
| `archiveOnly` | the build's own `provenance.json` | a full build presented as archive-only, or the reverse |

A run id already present in `builders.json` is refused: a reused run would count
one build twice and cannot establish a second builder.

## What this does not establish

**The bundle is not signed.** These are cross-references. Someone who edits every
file in the bundle consistently is not stopped by them; someone who edits the
builder record to claim a different commit, base, runner or run is.

The import record says so rather than implying otherwise:

```json
"signed": false,
"provenanceClaim": "unsigned",
"note": "Cross-referenced, not signed. This detects a record edited in one place;
         it is not proof against a consistently forged bundle, and the record
         says so rather than implying more than it establishes."
```

`tests/portability/test_hosted_import.py::test_a_consistently_forged_bundle_is_not_claimed_to_be_caught`
asserts this limit directly: a bundle whose record *and* runner report are edited
to agree is accepted, and the test exists so that the acceptance is understood
rather than mistaken for a proof.

A bundle claiming production provenance without a signature is refused outright.

## What an imported record is evidence of

One thing: that a second builder exists under a different administrator, so that
a **pair** exists. Independence is a property of the pair and is decided by
`release/builders.py`, never by either record alone. The import prints this
rather than leaving it to be assumed:

```text
A builder record is not a reproducibility result. Run verify-builder-independence
and compare-independent-builds; independence is decided over a pair.
```

An archive-only record can never be a candidate. Both protected gates refuse such
an artifact by name, and the import refuses a bundle that claims otherwise.

<!-- RESULT -->
