# The Visual Vertical Slice

**What this is** The image-editing journey — a person asks, is asked for
permission, answers on screen, and gets a file — driven through the shell's own
Trust surface in a booted guest, plus its denied and failing variants.

**Status** The journey runs end to end **through the protocol**. Driving it
**through the desktop** found a P0 that made the desktop's assistant unstartable,
and that fix has not yet been observed in a booted image.

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

## 2. What runs today: three slices, through the protocol

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

It has not yet pressed the button, and the reasons form a chain worth recording
because each looked like the previous one's fix had failed.

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
`-text` reproduces verbatim, so the guard meant to prevent the defect is what
made it permanent.

The guard is now on the bytes, checked against what git **stores** rather than
the working tree, over `shell/services/bin` and `installer/bin`. A working-tree
test would pass on Linux, fail on Windows, and say nothing about the image.

### 3.4 What this says about the qualification, honestly

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
| The Trust prompt renders on screen | **Observed** (photographed on a warm session) |
| The prompt is answered by pressing it | **Not established** |
| The desktop can start its assistant at all | **Fixed, not yet observed in an image** |

Per §30 of the brief, the phase remains **INCOMPLETE** while the approval is
answered by anything other than a person pressing the button.

## 7. Evidence

`qualification/capsules/evidence/journey-b38d51000543-{granted,denied}/`,
`journey-0ef5862-failing/` — `journey.json`, `screens/*.ppm`, `serial-tail.log`.
Graphical run screenshots under `build/out/shell/desktop-story/journey-*/screens/`.
