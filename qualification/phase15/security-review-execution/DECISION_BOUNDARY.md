<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# The decision boundary

Four different questions, four different derivations, never collapsed
into one green status. `EXTERNAL_STATUS.json` reports them as four
separate keys, each derived from its own inputs — none is hard-coded,
and the guard suite re-derives each from the live inputs to prove it.

## 1. Operational readiness — *is the pipeline ready to receive?*

Derived from the executed scenario matrix
(`FAILURE_RECOVERY_MATRIX.json`): every failure-and-recovery scenario
re-executes `AS_EXPECTED` against the real engines in scratch
universes. Readiness is a statement about machinery. It is **never**
evidence about the artifact, and the status file says so in place.

## 2. Evidence state — *does real evidence exist?*

Derived from the real Phase 9 ledger: entry count, gate-eligible
accepted count per source, ledger sha256. Zero is reported as zero.
Absence of evidence is never converted into any favorable word.

## 3. Gate state — *is the security requirement satisfied?*

Derived by Phase 11's `derive_security_gate` from accepted,
contract-valid, reconciled evidence and Critical-policy state. With
zero accepted submissions the gate is `AWAITING_EXTERNAL_EVIDENCE` —
which blocks; it never approves. `SATISFIED` is reachable only through
an accepted, approving, artifact-bound external review with every
Critical dispositioned and nothing unresolved. Fixture evidence can
never produce it in the real universe: the marker is refused at the
boundary, at derivation, and by the byte-comparison walls.

## 4. Candidate decision — *can the artifact advance?*

Derived by the Phase 10 candidate machinery and the Phase 13 ladder via
the Phase 14 assembler — Phase 15 asserts no candidate status of its
own. The authorization floor requires all five sources
(security-review, hardware, signing, second-approval, alpha-feedback
sufficiency) plus valid authority records; the only `AUTHORIZED` the
assembler can report is one a validated, sealed external authority
record already made.

## What no role or artifact of this phase can do

* An internal JSON claiming `AUTHORIZED` is refused with the absent
  floor named.
* Fixture-only favorable evidence cannot satisfy any real gate.
* One satisfied gate does not satisfy the five-source floor.
* A reviewer cannot become a signer by role assignment; a signer
  cannot become second approver against the separation policy.
* No reviewer response, no finding, no report, no signing record, no
  second approval, and no policy threshold are each **absence** —
  reported as the blocking state they are, never as a pass.

```text
zero external evidence                    → not AUTHORIZED
many internal tests passing + zero
external evidence                         → still not AUTHORIZED
```

The implementation passing is not evidence that a reviewer approved
the artifact.

## Commands and their boundaries

| Command | May | May not |
| --- | --- | --- |
| `prepare-review` | assemble a handoff package into an operator-named directory, pinned by sha256 | create a review, write inside the repository, invent evidence |
| `receive` | invoke Phase 9 intake on explicit paths | decide the review outcome, pre-process bytes, weaken the boundary |
| `validate` | check a record against the Phase 11 contract and derive the identity-ceremony state | accept anything (validation is not acceptance), mutate the record |
| `reconcile` | derive findings through the Phase 11 engine | invent missing dispositions, close by silence |
| `cut` | seal a derived evidence cut at an explicit boundary | absorb post-cut evidence, rewrite an earlier cut |
| `assemble` | derive the candidate decision through the Phase 14 assembler | manufacture authorization, write any registry |
| `status` / `sync-status` | derive `EXTERNAL_STATUS.json` from live inputs | hand-set any field, collapse the four questions into one |

Every command operates on explicit paths and IDs or refuses ambiguity;
none has "latest automatically" behavior.
