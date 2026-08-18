# Phase 6 blocking conditions

**Written before any Phase 6 qualification was run, and before any Phase 6
result was known.** §19: *"Do not weaken these conditions after seeing
results."*

The point of writing them first is not ceremony. A condition authored after the
results are in is authored by somebody who already knows which conditions would
be inconvenient. This file is committed ahead of the work so that the diff shows
whether any of it moved.

Each condition states the **test**, not the aspiration: what specifically has to
be true, and what evidence decides it.

---

## The ten

### 1. Independent security review unresolved

**Blocking unless:** `operations/data/independent-reviews.json` carries a
completed `security` review whose `artifact` field names the subject artifact's
digest, whose reviewer matches no project principal, and whose result is
`APPROVED` or `APPROVED_WITH_CONDITIONS` with every condition discharged.

**Not sufficient:** a re-scan, a self-review, a review of a different commit, a
review of the tree rather than the artifact.

### 2. Required Critical/High findings lack disposition

**Blocking unless:** every Critical and High finding in the inventory bound to
the subject artifact carries one of `FIXED`, `MITIGATED`, `NOT_APPLICABLE`,
`ACCEPTED_RISK` — and no finding remains `PENDING_REVIEW`.

**Constraints that do not relax:**
* `ACCEPTED_RISK` requires a named accountable approver. Not a role. A person.
* `NOT_APPLICABLE` requires an argument the reviewer can independently check.
  "Bunny does not call it" is not that argument.
* The disposition is argued against the **conservative** (module-granularity)
  finding count, not the function-granularity one.

### 3. Physical hardware qualification not completed

**Blocking unless:** at least one machine has a complete device record made
*before* first boot, and the full §7 journey has run on it end to end from the
subject artifact's installation medium, with the medium's digest verified on the
writing host **and** from the written medium.

**Not sufficient:** a successful live boot. A live boot is a boot result; it is
not an installation result.

**Explicitly not relaxed by:** the absence of a machine. Absence of a machine
makes this condition unmet, not inapplicable.

### 4. Production signing not established

**Blocking unless:** a production key exists under controlled access (hardware
token, offline HSM, or protected signing service), the **artifact** was signed —
not the tree — and the signature verifies against the released artifact's
digest.

**Not sufficient:** the development signing drill, however green.

### 5. Required second approval/signing absent

**Blocking unless:** an approval record exists naming artifact digest, artifact
version, first signer, second reviewer, date and decision, where first and
second are different people.

**Not sufficient:** a passing test run. §13: *"Do not infer approval from a
successful test run."*

### 6. Update trust architecture unresolved where updates are required

**Blocking unless** one of:

* **A** — an update trust architecture is implemented, and the §11 update and
  rollback journeys pass against it; or
* **B** — updates are **explicitly declared unsupported** for this release
  class, by an accountable owner, in a policy that binds to the subject
  artifact, **and the refusal is qualified as intentional behaviour rather than
  assumed** — see condition 7.

**Not sufficient:** an image that happens not to update because it was never
configured. Absence of a feature and refusal of a feature are different claims
and only one of them is testable.

### 7. Update matrix NOT_RUN without an approved unsupported-update policy

**Blocking unless** either the update matrix is complete, or:

1. an approved unsupported-update policy exists, bound to the subject artifact,
   naming an accountable approver and a review condition; **and**
2. the policy names **explicitly, scenario by scenario**, which matrix rows it
   makes `NOT_APPLICABLE` — a blanket waiver is refused; **and**
3. **every refusal path the policy relies on has been exercised at runtime
   against the subject artifact and observed to refuse**, closed, with a
   negative control showing the check can fail.

Point 3 is the load-bearing one. A policy that says "it refuses" and a system
that refuses are two different things, and this project has already found four
harnesses that reported PASS without measuring what they named.

### 8. Rollback evidence does not bind to the intended artifact chain

**Blocking unless:** rollback evidence names the digest it rolled **from** and
the digest it rolled **to**, and both match the intended chain — and the booted
deployment is identified from the running kernel's own `ostree=` argument, not
from the fact that a healthy target was reached.

**Explicitly not relaxed by:** a passing harness. The harness passed three times
without rolling back.

### 9. Alpha testing exposes unresolved release-blocking defects

**Blocking unless:** structured Alpha evaluation has run against the subject
artifact and no finding classified `RELEASE BLOCKER`, `SECURITY`, `DATA LOSS /
CORRUPTION` or `PRIVACY` remains open.

**Not satisfiable by absence.** Zero testers means this condition is unmet, not
vacuously met. §17: never convert *not executed* into *passed by absence of
failure*.

### 10. Artifact identity cannot be independently reproduced or verified

**Blocking unless:** the subject artifact's digests are reproducible from a
recorded provenance chain, its base input is retrievable, and an independent
party can verify the identity from the evidence package alone.

**Current known distance:** `repeatedBuildComparisonPerformed: false` for this
artifact, and the upstream base tag no longer resolves to the digest it was
built from. The retained base copy is what stands between this condition and
being permanently unmeetable.

---

## Exceptions

§19 permits an exception. It does not permit a silent one. Any exception must
record:

| Field | Requirement |
| --- | --- |
| Condition | which of the ten |
| Approver | a named person with the authority |
| Reason | why the condition cannot be met now |
| Risk accepted | what specifically could go wrong |
| Expiration / review condition | the date or event at which it must be revisited |

**No exception has been recorded.** This section exists so that the absence is
visible rather than implied.

---

## What these conditions imply before any work is done

Conditions 1, 3, 4, 5 and 9 depend on people and hardware that do not exist for
this project today. They were unmet when this file was written and no
repository change can move them.

That is stated here, in advance, so that Phase 6's final disposition reads as
the arithmetic of conditions fixed beforehand rather than as a verdict arrived
at once the results were in.
