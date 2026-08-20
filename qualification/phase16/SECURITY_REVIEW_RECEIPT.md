# Security-review receipt protocol

Receipt state answers one question: what happened when a particular submission
met the evidence boundary? It says nothing about the truth or favorability of
the review.

```text
AWAITING_SUBMISSION
        |
     RECEIVED
     /  |  \  \
REJECTED INCOMPLETE UNVERIFIABLE DOES_NOT_APPLY
     \      |       /             /
      new or revised RECEIVED only
                    |
                 ACCEPTED
                    |
                SUPERSEDED
```

`RECEIVED` is an observed pre-intake position. Stored Phase 9 statuses derive
the durable receipt view: `ACCEPTED`, `REJECTED`, `INCOMPLETE`, `UNVERIFIABLE`,
or `DOES_NOT_APPLY`; revision lineage derives `SUPERSEDED` without editing the
original.

The transition table is fail-closed and its complete forbidden cross product
is executed by the release suite. In particular:

- `AWAITING_SUBMISSION -> APPROVED` is impossible because `APPROVED` is not in
  the vocabulary;
- `REJECTED -> ACCEPTED` is impossible without a named new/revised receipt;
- `INCOMPLETE` cannot change a Phase 11 gate;
- accepting one receipt cannot authorize or silently replace another;
- a corrected revision preserves the rejected or incomplete original bytes.

Acceptance into intake means only that the package crossed the immutable
boundary and passed Phase 9's intake questions. Phase 11 may still find the
submission contract invalid, findings unresolved, assessments contradictory,
or the gate blocked. Phase 13 may still name every other authorization-floor
member as absent.
