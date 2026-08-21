# The Visual Vertical Slice

**What this is** The image-editing journey — a person asks, is asked for
permission, answers on screen, and gets a file — driven through the shell's own
Trust surface in a booted guest, plus its denied and failing variants.

**Status** All three slices — **granted, denied and failing** — now run through
the graphical Trust surface with the permission question **answered on screen**
by a pointer press at the button's own accessibility extents. Nothing calls
`resolve_approval`; the harness has no code path that could. Getting there took
four defects, three of which were found by looking at a photograph of the
desktop.

---

## 1. What the slice has to prove

Not "a capsule can resize an image" — the guest qualification proves that in
214.4 ms without a screen. The slice exists to prove the part a person meets:

1. The request is typed into the desktop, not injected.
2. The permission question **appears on screen**.
3. The answer is given by **pressing the button**, not by a protocol call.
4. The result is a real file, and the original is untouched.
5. Denied means nothing happens; failing means the desktop says so.

Point 3 is the one that has held this phase open. A run in which the approval is
resolved programmatically proves the runtime and proves nothing about the
surface — the GTK window is a client, not a security authority — so a slice that
answers its own question is not the slice.

## 2. The slices

### 2.1 Through the desktop, answered by pressing a button

The claim §30 exists for. Image `fa161b49182b`, driver `complete`.

**granted** — the prompt rendered, the driver found *Allow this Bunny action* in
the accessibility tree after 234 nodes and pressed it at (1679, 650) with a
virtio-tablet event:

```
journey-result   files ["holiday-resized.png"], pixels [100, 50],
                 sourceDigest 5de7c234… unchanged, ok=true
statesAfterApproval  ["idle", "success", "idle"]
```

and the desktop said, in its own words:

> Done. I made Pictures/holiday-resized.png at 100 pixels wide. Your original
> wasn't changed.

**denied** — the same prompt, *Deny this Bunny action* pressed instead, and the
desktop said:

> the request was declined

Nothing was written. A refusal that a person made, on screen.

**failing** — the same prompt, *Allow* pressed, and a corrupt image behind it.
The person permitted the work; the work could not be done. The desktop said, in
three steps:

> Resize this to 100 pixels wide.
> I could not do that.
> **the task failed**

and put the character into a state that cannot be mistaken for the other two: a
red ground glow, an alert mark beside the head, and a worried pose, against the
upright resting pose of success. This is the row §10 of the brief was written
for — *"a failed operation must never produce a completed task"* — arriving on a
person's screen in words they did not have to be technical to read.

None of the three slices weakened the boundary to get there: the capsule still
ran with `--unshare-net`, still read one granted file, and still wrote only into
its own exports directory.

### 2.1.1 Two things the brief asks for that the slice does not show

Stated rather than glossed, because both are visible absences in the pictures
above and a reader would reasonably assume they were covered.

**There is no application choice.** The brief's journey is "request, *app
choice*, Trust prompt, …". This image registers exactly one application for
`image.resize`, so there is nothing to choose between and no chooser is drawn.
That is honest for this build and it means the choosing surface — and the
question of what happens when two applications both declare a capability — is
unexercised, not merely unshown.

**Trust history is not reached.** `trust/audit.py` exists and
`capsule_task_bridge.py` writes to it, and the desktop has an **Approvals**
tile in Quick Access. The journey never opens it, so "the person can see what
they have permitted" is implemented and unobserved. The capsule status surface
(`companion/capsule_status.py`, 14 tests) is in the same position.

Both belong to the next phase's visual work rather than to this report's claims.

### 2.2 Through the protocol, for comparison

The same three slices with the approval resolved by a protocol client. These
established the runtime long before the surface worked, and they remain the
finer-grained record — they carry timings and grant state the graphical run does
not.

| Slice | Decision | Final state | Elapsed | Result |
|---|---|---|---|---|
| granted | granted | `completed` | 1.108 s | `Pictures/holiday-resized.png`, original unchanged, 0 grants left |
| denied | denied | — | — | nothing written |
| failing | granted, corrupt input | `failed` | 1.123 s | `operation_failed`: "The app stopped before it finished." |

Each record carries the readiness block (all eight conditions), the approval as
the user would read it, the fixture digest, the neighbour's digest, and the
grants remaining afterwards.

The **failing** slice is the one worth dwelling on. It is the same journey with a
corrupt image, and its value is that `finalState` is `failed` rather than
`completed`. That distinction did not exist until this phase: `TaskResult` had no
failure channel and the runtime asked nobody, so an operation that could not run
produced a completed task with an empty result. The fix combines two verdicts
pessimistically at the shared runtime layer, and the desktop's own words —
"The app stopped before it finished." — come from the same place.

**Evidence level: VM runtime validated for the runtime; not validated for the
surface.** The approval in all three was resolved by a protocol client.

## 3. Driving it through the desktop: what that found

The graphical driver types the request with a virtio-tablet, waits on the
character's state, walks the accessibility tree for a control named
*"Allow this Bunny action"*, and presses it at its own screen coordinates. It
never calls `resolve_approval`.

It now presses the button. Getting it there took four defects, and they are
recorded in order because each one looked, at the time, like the previous fix
having failed — which is why the chain is worth more than the individual bugs.

### 3.1 The deadline that ran while a person was being asked

The desktop showed, where a permission question should have been:

> **the runtime did not finish within the deadline**

`watch()` in the shell's assistant bridge held **one clock for two different
things**. A task in `waiting_for_approval` is not a runtime failing to finish; it
is a question on somebody's screen, which is the system working. The clock is now
**suspended, not extended**, while an approval is unanswered — so a task that
hangs *after* approval still fails, on the time it had left.

Held by three tests that spend real seconds against the real `watch`, because a
structural check ("the source mentions `waiting_since`") would pass against an
implementation that tracked the value and never subtracted it. Negative control
run: the pre-fix bridge fails the first test with exit 5 and the same sentence.

### 3.2 The desktop said the assistant was offline

The next run showed no error — and no prompt. The screenshot showed two things
the JSON did not:

> ⚠ **Assistant offline — open Settings**
> *(and, in the assistant card)* **Thinking…**

on a session whose readiness probe reported `bunny-companion.service` active,
zero restarts, and its socket answering.

The first diagnosis was staleness: `AssistantService.checkHealth` was called once
at startup, and GNOME Shell *is* the session while `bunny-companion.service` is
pulled in by `graphical-session.target` afterwards — so the single check runs
before the socket exists. That is a real defect and it is fixed (both consumers
now share one bounded poller; "still starting" and "not there" are different
facts and only one is worth putting on a person's screen).

**It was not the cause.** The message was live truth.

### 3.3 The P0: a shipped executable that could not be executed

Asked directly of the image:

```
$ /usr/bin/bunny-shell-assistant health
/usr/bin/bunny-shell-assistant: /usr/bin/python3^M: bad interpreter:
No such file or directory
```

The bridge was committed with a **CRLF blob**. It installs to `/usr/bin` mode
0555 and begins `#!/usr/bin/python3`, so the shebang named an interpreter called
`/usr/bin/python3\r`. The desktop reaches the companion only through
`Gio.Subprocess.new([BRIDGE, ...])`, which execs the file directly.

So the desktop could never start its assistant. Every symptom is downstream of
one byte:

| Symptom | Cause |
|---|---|
| "Assistant offline — open Settings" | the spawn threw; `_available = false` |
| "Thinking…" for ever | the shell's optimistic local state, no events ever arrived |
| No permission prompt | the runtime never received the request |
| No deadline error | the bridge never ran, so its clock never ran |

`.gitattributes` names this hazard, for this directory, in a comment that
describes the failure exactly. It marks the path `-text` so git will not
*introduce* CRLF — which is a different guarantee from the bytes being clean.
`-text` reproduces verbatim, so once CRLF bytes are committed the guard is what
keeps them.

**Where the bytes came from, stated plainly:** the shebang was LF at `670381a`
and CRLF at `1b58edf`, which is the deadline fix in §3.1. Editing the file from
the Windows working copy rewrote every line ending, and `-text` then stored that
faithfully. This was a regression introduced *during this phase*, one commit
before the run that exhibited it — not a long-standing defect. It affected
exactly one image generation.

That makes the sequence in §3.1–§3.3 tidier than it looked at the time: the run
that showed the deadline message had a working bridge and a real deadline defect;
fixing the deadline broke the shebang; the next run therefore showed a desktop
that could not start its assistant at all. Two defects, one masking the other,
and the second created by the fix for the first.

The guard is now on the bytes, checked against what git **stores** rather than
the working tree, over `shell/services/bin` and `installer/bin`. A working-tree
test would pass on Linux, fail on Windows, and say nothing about the image.

### 3.4 The fourth clock, and the press

With the bridge able to start, the next run showed the request submitted, the
character thinking — and then, where the permission question should have been:

> **The assistant did not answer in time. It may still be working — the Tasks
> window will show it.**

That is the **desktop's own** watchdog, `WATCHDOG_MS = 200000` in
`assistant.js`. §3.1 had fixed the *bridge's* clock; the desktop keeps a second
one, and it had never heard of approvals either. A person has 200 seconds to read
a sentence about their own files, and then the question is taken away and
replaced with a complaint that they were slow.

Both are now suspended while an approval is unanswered and rearmed when the phase
leaves `waiting_for_approval`. `TRUST_RUNTIME_REPORT.md` §4.1 records all three
clocks that watch a permission question and the one rule that follows: **a clock
that can end a task may not run while a person is being asked, unless it is the
consent expiry itself.**

The harness was also spending minutes cataloguing the whole accessibility tree
before pressing anything — long enough for any of those clocks to win. It now
looks for the two buttons by name with an early exit, and photographs the screen
the moment the shell says it is asking.

**With that, the prompt was pressed.** Recorded by the driver:

```
journey-approval-fast   found=true, button="Allow this Bunny action",
                        nodesVisited=234
journey-approval        visible=true, role=button,
                        extents={x:1662, y:640, width:34, height:20}
journey-decision        pressed="Allow this Bunny action", at={x:1679, y:650}
```

and photographed at `journey-04-trust-prompt`:

> Resize this to 100 pixels wide.
> *Waiting for permission…*
> **Bunny Image Tool wants to open Pictures/holiday.png. It will save a copy as holiday-resized.p…**
> **[Deny]** [Allow]

Three things in that picture were fixes landing at once: the prompt is there at
all (§3.3), it is not a timeout message (§3.4), and **Deny carries the focus
ring** — the safe default took focus, so a screen reader announces the question
and a reflexive Return denies it.

The press is a `virtio-tablet` absolute pointer event at the button's own AT-SPI
extents. The graphical harness contains no call to `resolve_approval` — there is
no path by which it could answer its own question.

### 3.5 Then the success path failed, because it had never run

Immediately after the press:

```
NameError: cannot access free variable 'watch_character'
           where it is not associated with a value in enclosing scope
```

`watch_character` is a closure defined *after* `run_journey`, and Python resolves
a free variable at call time. Every previous run returned early at the
no-approval branch, so **the line that uses it had never executed**. The failure
path had been exercised a dozen times and the success path not once.

Worth stating plainly because it is the same shape as everything else here: the
part of the system nobody had reached was the part that was broken, and reaching
it was the whole difficulty.

### 3.6 What this says about the qualification, honestly

Eleven guest sections passed, the apptask section drove the production route to a
real file, and the readiness probe reported eight green conditions — on an image
whose desktop could not talk to its own runtime.

None of those is wrong. They are all true statements about layers below the one
that was broken. The apptask section builds a `PlannedOperation` and calls the
broker; the readiness probe asks the runtime's socket directly; neither goes
through `/usr/bin/bunny-shell-assistant`, and nothing did until a driver tried to
use the desktop the way a person does.

**The gap was never a missing assertion. It was a missing user.**

## 4. Harness faults met on the way

Nine on the graphical journey, in every case with the product correct and the
instrument lying — the expensive failure mode, because it produces confident
wrong answers rather than errors. They are listed in
`GRAPHICAL_SESSION_REPORT.md` §5.

The one worth repeating here: the walk depth was raised 12→20 on an untested
theory about where the Trust prompt sat, and the run that followed returned *no
controls at all*, because a deeper walk over this tree does not finish inside the
call's timeout. A change made to fix a failure broke a working instrument, and it
was caught only because the previous value was recorded.

## 5. What the harness now does when there is no prompt

There are two ways to have no approval on screen and they need opposite fixes:
the runtime never asked, or it asked and the desktop did not draw it. Everything
the driver measured was on the screen side, so a stall could not distinguish
them.

The no-approval branch now asks the runtime: `task-trace` returns every task the
runtime knows about and the last events of each, and `companion-state` returns
the unit's state, its journal, the shell's own log filtered for the assistant,
and `bunny-shell-assistant health` run as the user. Guessing between those two
possibilities cost three cycles.

## 6. Evidence level

| Claim | Level |
|---|---|
| The runtime completes the journey, granted / denied / failing | **VM runtime validated** |
| A failed operation produces a failed task | **VM runtime validated** |
| The original and the neighbour are untouched | **VM runtime validated** |
| Allow-once leaves no grant behind | **VM runtime validated** |
| The desktop can start its assistant | **VM runtime validated** |
| The Trust prompt renders on screen | **VM runtime validated** |
| **The prompt is answered by pressing it — granted** | **VM runtime validated** |
| **The prompt is answered by pressing it — denied** | **VM runtime validated** |
| **The prompt is answered by pressing it — failing** | **VM runtime validated** |
| The prompt's buttons take focus on the safe default | **Tested**; not measured while on screen |
| An application chooser | **Not applicable yet** — one application is registered |
| Trust history reached by a person | **Not established** |

Per §30 of the brief: the granted and denied slices are now answered by a
pointer press on the Trust surface, and the harness has no code path that could
answer them any other way. The failing slice is the last of the three.

## 7. Evidence

## 7. Evidence

`qualification/capsules/evidence/journey-b38d51000543-{granted,denied}/`,
`journey-0ef5862-failing/` — `journey.json`, `screens/*.ppm`, `serial-tail.log`.
Graphical run screenshots under `build/out/shell/desktop-story/journey-*/screens/`.
