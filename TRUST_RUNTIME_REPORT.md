# Trust Layer at Runtime

**What this is** How the permission layer behaved when it was actually run, rather
than how it is specified. Every number here comes from a suite that executed the
production code path; the source description lives in
`COMPANION_CAPSULES_TRUST_REPORT.md` §6–§9.

**Suite commit** `524107e50b2e` (guest), `a2f195019f4e` (host application-task run)
**Verdict** The gate is fail-closed on all six failure paths that were exercised,
and the grant lifecycle behaves as specified — after three defects were fixed.

---

## 1. The rule the layer is built on

*An unanswered question is a denial.* It is inherited verbatim from
`capability/apply/approval.py`, which has stated it since the capability phase for
Bunny's own privileged operations. The trust gate applies it to third-party
applications without restating it in different words, which is why `unanswered`
appears in the fail-closed table below as a first-class reason rather than a
timeout.

## 2. Fail-closed: six paths, six reasons

Each row denied, wrote no grant, and produced its own distinct reason. The reason
matters as much as the denial: a layer that denies everything with one message
cannot be debugged, and cannot tell a user why.

| Path | Verdict | Reason recorded |
|---|---|---|
| The approval expired | deny | `expired` |
| The category was never declared by the application | deny | `not-declared` |
| An approval token was replayed | deny | `replayed` |
| The grant store was corrupt | deny | `store-unreadable` |
| The consent surface itself failed | deny | `surface-failed` |
| Nobody answered | deny | `unanswered` |

The corrupt-store case carries the parse error with it:

```
/…/trust/grants.json is not readable JSON:
Expecting property name enclosed in double quotes: line 1 column 3 (char 2)
```

That is deliberate. A store that cannot be read is not an empty store — treating it
as empty would silently drop every standing grant a user had made, and treating it
as fatal-but-silent would look like the application had simply stopped working.

**The replay pair is the sharpest of the six.** `replaySetup` shows the same
approval succeeding once with reason `user-allowed`; `replayedApproval` shows the
second use denied with `replayed`. Without the setup row, "replay is denied" could
be satisfied by an approval that never worked at all.

### 2.1 The seventh path: the resource changed after approval

This one does not fit the table, because it does not deny — it *refuses to bind*:

```
grant     ihWioXF8c8Cknf8P        (a real, valid grant)
boundAnyway  []
refusals  [{grantId: ihWioXF8c8Cknf8P, reason: "that file is no longer an ordinary file"}]
```

The user approved a file. Between the approval and the launch, the path stopped
being an ordinary file. The grant is still valid — the person did consent — but the
thing they consented to is not the thing that would be mounted, so nothing is
mounted. `boundAnyway` is empty and is asserted empty; it exists so that "we
refused" cannot be confused with "we refused *and also* bound it".

## 3. The grant lifecycle

Measured in one run, in order, on a live store:

| Step | Result |
|---|---|
| No grant | denied |
| Granted | readable |
| A neighbouring file under the same grant | denied |
| After revocation | denied |
| Allow-once | left **no** grant behind |
| A standing grant, second use | reused **without being rewritten** |
| A standing grant, after a restart | survived |

Two of these rows are defect regressions.

**Allow-once leaving no grant** is the fix for a defect where the whole allow-once
path could not work at all. The trust layer never persists `once` — correctly — but
the capsule plan was built *from persisted grants*, so an allow-once approval
produced a plan with no bind, and the application launched and found nothing. The
route now uses a `session` grant and stops the capsule when the operation ends,
which produces the same user-visible lifetime through a mechanism that exists.

**"Reused without being rewritten"** is not a performance claim. A layer that
rewrites the store on every read has a write on the authorisation path, and a
corrupted write there loses standing grants at the moment they are being honoured.

### 3.1 The session grant outliving its task

The most instructive defect in this phase passed every unit test before and after
the fix, and was found only by the guest regression.

`reconcile()` stops a capsule whose work is finished. The drop of session grants
was in `stop()`. But `stop()` returns early for a capsule that is *already*
stopped — and `reconcile()` is what had stopped it. So the drop never ran, and a
grant scoped to one task survived into the next.

The fix moved the drop into `reconcile()` itself. The lesson recorded for the next
phase: **cleanup that lives in the function you call is not cleanup that ran** —
if a guard can short-circuit the caller, the cleanup belongs on the path that
takes the decision, not on the path that reports it.

## 4. What the user is actually asked

The approval text is generated, not templated per call site, and the guest run
recorded exactly what a person would read:

> Bunny Image Tool wants to open Pictures/holiday.png. It will save a copy as
> holiday-resized.png. Your original file will not be changed. It runs in its
> protected space with no network access.

Four properties are asserted about that sentence, because each is a way a
permission prompt can lie:

| Property | Value | Why it is checked |
|---|---|---|
| `namesTheFile` | true | "An application wants file access" is not consent |
| `leavesDevice` | false | Stated because the user cannot otherwise know |
| `action` | `launch_application` | The prompt names what will happen, not a category |
| `destination` | `art.comrade.BunnyImageTool` | The prompt names *who*, by identity |

And the network line is not decorative: the same run recorded `class none,
enforced true, shown "Off"`. The word the user reads is derived from the class that
was enforced, so the prompt cannot say "Off" about a capsule that has a network.

## 4.1 Three clocks watch a permission question, and only one may end it

This is written down because not knowing it cost this phase three cycles.

| Clock | Where | Length | While a question is unanswered |
|---|---|---|---|
| Consent wait | `companion/service.py`, `DEFAULT_CONSENT_WAIT_SECONDS` | 300 s | **Runs, and must.** Silence is denial; a question nobody answers has to expire |
| Bridge deadline | `bunny-shell-assistant`, `DEADLINE_SECONDS` | 180 s | **Suspended.** An approval is not a slow answer |
| Desktop watchdog | `assistant.js`, `WATCHDOG_MS` | 200 s | **Suspended.** Same reason, one layer up |

Only the first is the trust layer's. It is the one that implements the rule in
§1, and shortening or suspending it would turn "an unanswered question is a
denial" into "an unanswered question waits for ever".

The other two exist to stop a *stuck runtime* hanging the desktop, and both were
wrong in the same way: each measured "time since the request" and neither knew
that a question on screen is the system working. The desktop showed *"the runtime
did not finish within the deadline"* and later *"The assistant did not answer in
time"* where a permission question should have been — twice replacing a question
with a complaint about the person taking too long to answer it.

Both are now suspended while an approval is pending and **rearmed** when the
phase leaves `waiting_for_approval`, on a full budget for the work that follows
rather than the remainder of the time somebody spent reading. Suspending, not
extending: extending only moves the number, and removing lets a genuinely stuck
request sit behind a thinking animation for ever.

The rule this leaves, for anything added later: **a clock that can end a task may
not run while a person is being asked, unless it is the consent expiry itself.**

## 5. The single-use approved surface

`ApprovedActSurface` in `companion/capsule_task_bridge.py` is bound to one
application, one category and one resource, and is consumed on use. It contains no
branch that produces an allow without a decision — which is a structural property,
checked by reading it, not a behaviour that a test could establish by sampling.

This is the piece that keeps §2's replay row honest at the layer above the store.

## 6. Evidence level

**Host runtime validated** and **VM runtime validated** for everything in §2 and §3:
these ran on a real kernel with SELinux enforcing, as `bunny`, in a booted image.

**Not established here**: that a person can see and answer the question on screen.
That claim belongs to `VISUAL_SLICE_REPORT.md`; it is made by a run in which the
approval is submitted by pressing a button in the graphical Trust surface, and by
nothing else. Until that run exists, everything in this document describes a layer
that is correct and unobserved by a user.

## 7. Evidence

- `qualification/capsules/evidence/guest-524107e50b2e/failclosed.json`
- `qualification/capsules/evidence/guest-524107e50b2e/filegrant.json`
- `qualification/capsules/evidence/guest-524107e50b2e/apptask.json`
- `qualification/capsules/evidence/host-a2f195019f4e-apptask/apptask.json`
