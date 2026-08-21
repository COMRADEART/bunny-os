# Alpha sufficiency threshold architecture

Phase 12 left one item deliberately unresolved: every sufficiency
threshold was null, because the owner had not decided any, and the
machinery refused to guess. Phase 13 gives that decision a mechanism
without making it.

## The lifecycle

```
SUFFICIENCY_POLICY_UNDEFINED      (zero policies — the current state)
        ↓  owner records a policy (record policy)
SUFFICIENCY_POLICY_PROPOSED       (a policy exists; none is active)
        ↓  owner records an ACTIVE policy
SUFFICIENCY_POLICY_ACTIVE         (one standing active, artifact-applicable policy)
        ↓  every sync
SUFFICIENCY_EVALUATED             (a determination derived against the active policy)
```

The refusal the lifecycle enforces:

```
READY_FOR_TESTERS  →  SUFFICIENT        REFUSED
```

without an active, artifact-applicable policy. One hundred accepted
tester reports against zero defined thresholds is still
`SUFFICIENCY_UNDETERMINED` — volume is not a policy.

## The dimensions

Every policy must decide all eleven, explicitly:

`minimumAcceptedTesterReports`, `minimumDistinctTesters`,
`minimumDistinctMachineIdentities`,
`minimumSuccessfulInstallationReports`, `minimumCompletedCoreJourneys`,
`minimumEvidencePeriodDays`, `maximumUnresolvedBlockerFindings`,
`maximumUnresolvedCriticalFindings`, `performanceEvidenceRequired`,
`accessibilityEvidenceRequired`, `minimumDistinctHardwareMachines`.

An ACTIVE policy with a null dimension is invalid: null means the owner
has not decided, and an undecided policy cannot be active. **No
production value is invented anywhere in this repository** — the initial
registry is empty, and the fixture policy used by the dry runs is marked
`TEST_FIXTURE_ONLY` and refused everywhere real records are read.

## Versioning and immutability

A policy is a sealed record `SUFFICIENCY-POLICY-NNN` with
`artifact_digest`, `effective_at`, `authority`, and `supersedes`.

- Activation requires the authority to be an **assigned**
  `AUTH-ALPHA-PROGRAM` identity.
- An activated policy is immutable: its seal covers every field, and a
  changed byte is an `IMMUTABILITY FAIL` on every subsequent run.
- A later threshold is a **new** record whose `supersedes` names its
  predecessor. The old policy, the old evidence, and the old evaluation
  all remain in place; a threshold change never silently reclassifies
  historical evidence.
- At most one ACTIVE policy may stand unsuperseded, and it binds to
  exact artifact bytes — a policy for other bytes activates nothing
  here.

## Where the measures come from

`release_authority_ops.py` derives the measured values from committed,
reproducible inputs only: the Phase 12 register (reports, testers,
machines, journeys, findings, performance and accessibility evidence),
the Phase 11 register (unresolved criticals downstream of review), and
the Phase 9 ledger (evidence period from `receivedOn`, hardware machines
from gate-eligible accepted hardware intakes). Zero is measured as zero.
Nothing is estimated, and the determination vocabulary is Phase 12's,
unchanged: `SUFFICIENCY_UNDETERMINED`, `INSUFFICIENT_EVIDENCE`,
`SUFFICIENT_WITH_UNRESOLVED_BLOCKERS`, `SUFFICIENT`.

## Relation to Phase 12

`qualification/phase12/sufficiency-policy.json` (all thresholds null)
remains the Phase 12 evaluation authority and is untouched. This
registry is the versioned activation layer above it; when the owner
records real thresholds here, Phase 12's register keeps reporting its
own determination and Phase 13's evaluation gates authorization. The two
never disagree silently: both fail toward UNDETERMINED.
