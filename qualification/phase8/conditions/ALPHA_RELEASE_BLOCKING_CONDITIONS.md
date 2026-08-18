# Phase 8 Alpha-release blocking conditions

**Written before any Alpha testing, before any external review, and before
any Phase 8 result was known.** §15: *"Before Alpha testing begins, write the
blocking conditions"* and *"Do not weaken these conditions after feedback
arrives."* This file is committed ahead of the work so the diff shows whether
any of it moved.

The question these conditions gate is §21's, exactly:

> Is there sufficient independent evidence and authorized approval to
> distribute **this exact artifact** — `e906a48793d7`, image
> `sha256:c87a6616008ce34f97840f63814e08fdb33574b52202fbb4841b7f5aa7f8562d` —
> as a controlled Alpha?

`ALPHA RELEASE AUTHORIZED` requires every condition below to be false, on
evidence. Anything else is `EXTERNAL VALIDATION IN PROGRESS` (gates awaiting
their owners) or `ALPHA RELEASE BLOCKED` (a condition is true).

## The ten

### 1. Security review returns BLOCKED

**Blocks while:** a completed independent security review of the subject
artifact exists with result `BLOCKED`, or no completed review exists at all —
absence of a review is not approval and authorizes nothing.

### 2. A Critical issue lacks an accepted disposition

**Blocks while:** any Critical finding bound to the subject artifact carries
disposition `UNKNOWN` or `REQUIRES_REVIEW`, or an `AFFECTED` Critical lacks a
named accountable acceptance. The conservative module-granularity count is
the one argued against.

### 3. A confirmed data-loss defect exists

**Blocks while:** any defect with category `DATA_LOSS` and reproduction
confidence `CONFIRMED` is open against the subject artifact. `LIKELY` and
`REPORTED` data-loss findings do not authorize by being unconfirmed: they
must be triaged to a terminal confidence before authorization.

### 4. A confirmed privacy breach exists

**Blocks while:** any `PRIVACY` defect at `CONFIRMED` is open — same
triage-to-terminal rule as condition 3.

### 5. A confirmed release-blocking accessibility defect exists

**Blocks while:** any `ACCESSIBILITY` defect classified `RELEASE_BLOCKER` at
`CONFIRMED` is open. The 12 NOT_RUN accessibility scenarios are a scope
limitation (declared in the Alpha limitations document), not a defect — but a
defect found *within* the declared scope blocks.

### 6. The artifact identity cannot be verified

**Blocks while:** the bytes a tester or reviewer receives do not hash to the
recorded digests, or a report arrives bound to "latest build" rather than a
digest. Every acceptance of evidence starts by checking this condition.

### 7. Required signing policy is unmet

**Blocks while:** the release policy in force for a *distributed* Alpha
requires a signed artifact and no verified signature of the exact artifact
bytes exists. A signing drill does not satisfy this. If governance instead
explicitly accepts unsigned distribution for the controlled Alpha cohort,
that acceptance is an exception and carries the §15 exception record (owner,
risk, exact artifact, expiration) — it is never the silent default.

### 8. Required second approval is absent

**Blocks while:** the release policy requires a second approver and no
record exists in which a second person independently names the same artifact
digest. CI green is not a second signer; approval of a branch is not
approval of bytes.

### 9. A hardware failure affects the declared supported hardware set

**Blocks while:** the Alpha scope document declares a hardware configuration
supported and that configuration carries a FAIL on a required journey
dimension. Undeclared hardware cannot block — and cannot be claimed.

### 10. Alpha testing finds an unresolved release blocker

**Blocks while:** any finding classified `RELEASE_BLOCKER` (or `SECURITY` at
Critical severity) from Alpha testing is open without an accepted
disposition.

## Exceptions

Any exception records: the condition, a named owner with the authority, the
explicit risk accepted, the exact artifact digest, and an expiration or
review event. **No exception has been recorded.** This section exists so the
absence is visible rather than implied.

## What these conditions imply today

No independent reviewer, no physical machine, no signing authority, no
second person, and no Alpha tester has acted yet. Conditions 1, 2, 7 and 8
are therefore true right now (reviews and approvals absent), and conditions
3–5, 9 and 10 are undetermined for lack of any testing evidence. Stated in
advance: the strongest status Phase 8 can hold until real external actions
produce evidence is **EXTERNAL VALIDATION IN PROGRESS**.
