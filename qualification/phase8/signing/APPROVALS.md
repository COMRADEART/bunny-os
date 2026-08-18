# Release approvals — the second-signer record

**Current state: no approval exists.** The project has one principal; a
second signer does not exist. This file defines the record so that when a
second person exists, their approval is captured in a form that actually
binds — and so that until then, the absence is visible.

## What a valid approval record contains

Both approvals in one record, each independently naming the artifact:

    artifactDigest        stated by EACH approver, recomputed by each from
                          the bytes — the second approver does not inherit
                          the first's digest, they verify it
    firstApprover         name, role, date, decision
    secondApprover        name, role, date, decision — a different person
    decision              APPROVE / REJECT, per approver
    scope                 what exactly is approved (e.g. "distribute this
                          ISO to the controlled Alpha cohort")

## What is not an approval

* A successful CI run. CI is a machine following instructions; it holds no
  release authority.
* Approval of a branch, a commit, or "the current state" — the requirement
  is approval of **exact artifact bytes**, and a record that names anything
  else does not satisfy it.
* One person approving twice, in any combination of hats.

## Record location

`qualification/phase8/signing/approval-record.json`, absent until real. Its
absence is the measured state of the second-signer gate: **NOT_RUN**.
