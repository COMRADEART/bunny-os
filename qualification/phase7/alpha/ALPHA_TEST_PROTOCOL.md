# Alpha test protocol

The structured protocol the brief's §11 requires. It exists so Alpha feedback
arrives as evidence rather than as impressions, and so every report binds to
the artifact that produced it. **No Alpha tester exists today**; this
protocol's existence changes readiness, not the Alpha validation gate, which
stays NOT_RUN until a human tester runs it.

## 0. Artifact binding — before anything else

The tester records, from the installation medium they were given:

    ISO file name:
    ISO sha256 (as computed on the tester's machine):

The expected value for the current cohort is
`823d50caba35afe72452768affd5f6fa0ac8cfc13c164f0e1bc909fa887ab421`
(artifact `e906a48793d7`). **A report whose digest does not match names a
different artifact and must say which.** If a new build supersedes this
cohort, this file gains a new cohort table; feedback never floats free of an
artifact identity.

## 1. Journeys

Each journey below is run in order, each step marked one of
`COMPLETED / FAILED / SKIPPED(reason)`. A journey stops at its first FAILED
step; what happened next is free-text.

### J1 — First boot
1. Boot the installation medium; install to the machine's disk.
2. Reboot into the installed system; unlock encryption if configured.
3. Log in.
4. Complete onboarding.
5. Desktop ready: panel visible, Companion visible, no error dialogs.

### J2 — Companion renderer modes
1. Companion visible in the default (pre-rendered) mode.
2. Switch to 2D animated mode; the character animates.
3. Switch to 3D mode **where the machine supports it**; record GPU/driver.
4. Force a fallback (3D on unsupported hardware): the fallback is announced,
   not silent.
5. Reboot; the chosen mode persisted.

### J3 — Voice
1. First voice use asks for microphone permission.
2. Grant; speak a request; recognition transcribes it.
3. A response is produced (spoken or shown).
4. Interrupt the response mid-way; it stops.
5. Cancel a request; the cancellation is confirmed on screen.
6. Deny microphone permission (Settings → revoke): voice input refuses
   cleanly and says why.

### J4 — Trust
1. Trigger an action that needs a permission (e.g. Companion desktop action).
2. The Trust prompt explains: application, resource, reason, scope.
3. Allow. The action proceeds. **Verify the actual outcome**, not the dialog.
4. Trigger a second permissioned action.
5. Deny. The action does not proceed. **Verify the actual refusal.**
6. Both decisions are visible afterwards in the Trust records.

### J5 — Reboot persistence
1. Change: Companion mode, Companion scale/position, one voice setting, one
   permission decision, locale if offered.
2. Reboot.
3. Every change from step 1 is still in effect. List any that is not.

## 2. Evidence separation (§12)

Two channels, never merged:

**MEASURED** — collected by the system or the tester's tools: crash records,
journey step outcomes, latency figures where the UI shows them, CPU/memory
observations, screenshots. A number belongs here only if something measured
it.

**USER-REPORTED** — the tester's judgement: confusing, useful, distracting,
slow, trustworthy, polished. Free text, tied to the journey step it arose in.
*A user-reported "slow" is not converted into a latency figure; it is kept as
what it is.*

## 3. Defect triage (§13)

Every issue gets exactly one classification:

    RELEASE BLOCKER | SECURITY | DATA LOSS | PRIVACY | FUNCTIONAL |
    ACCESSIBILITY | PERFORMANCE | UX | COSMETIC | HARNESS | ENVIRONMENT

and records: artifact (from §0), reproduction steps, evidence
(screenshot/log/journal excerpt), severity, owner, disposition. The
machine-readable shape is `qualification/phase6/alpha/triage-schema.json`,
which this protocol adopts unchanged.

A report that cannot immediately be reproduced is **not closed for that
reason**; its reproduction confidence is recorded separately
(`REPRODUCED / INTERMITTENT / NOT_YET_REPRODUCED`) from its disposition.

## 4. What this protocol does not do

It does not convert completed journeys into a release approval — Alpha
feedback informs the release decision and is not itself one. It does not
substitute for the accessibility matrix, the security review, or hardware
qualification, each of which has its own gate and owner.
