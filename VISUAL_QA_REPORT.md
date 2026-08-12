# Visual QA — the Bunny desktop as photographed

**What this is** Findings from *looking at* the booted desktop at 1920×1080,
rather than from asserting about it. Every item below is visible in a screenshot
taken by QMP `screendump` from a running guest; none was found by a test.

**Screens** `journey-03-typed.png`, `journey-04-no-approval.png`
(`build/out/shell/desktop-story/journey-granted/screens/`)
**Image** `1b58edf31003`, profile `shell`, llvmpipe

---

## 1. Why this document exists

Two of the most expensive defects in this project were on screen the whole time
and invisible to the suite:

- A character whose working pose was a shrug, past assertions about coverage and
  frames differing.
- **"⚠ Assistant offline — open Settings"** on a desktop whose runtime was
  active — which turned out to be the visible end of a P0 that made the
  assistant unstartable (`VISUAL_SLICE_REPORT.md` §3.3).

Nine text-only diagnostics had not found the second. One photograph did, in
seconds. That is the whole argument for this report existing.

## 2. What is right

Worth stating, because a defect list reads as though nothing works.

| Element | State |
|---|---|
| Character | Full figure, correct proportions, head narrower than shoulders, upright working pose — not a shrug |
| Greeting | "Still up, Bunny" at 04:06, time-appropriate rather than a fixed string |
| Storage | `5.9/12.0 GB` — the composefs `statfs` fix holds; not the old `14.2 MB / 14.2 MB` |
| Temperature | *Unavailable*, in italics — an honest absence rather than a fabricated `0°C` |
| Network | `0 B/s` up and down on an idle guest, correct |
| Layout | Nothing overlaps, nothing is clipped by the screen edge, the dock is centred and clear of the character |
| Input | The typed request renders in full inside the entry, with a visible focus ring |

## 3. Findings

### 3.1 Five of eight Quick Access labels are ellipsised — **P2**

The grid reads:

```
Files      Terminal    Bunny       Bunny App…
Bunny Co…  Bunny Dia…  Bunny Lau…  Bunny Sett…
```

Five of the eight cannot be identified, and four of those share the prefix
"Bunny " — so the truncation removes exactly the part that distinguishes them.
"Bunny Co…" could be Bunny Command or Bunny Companion, both of which exist as
shipped commands.

This is not a font-size problem: the tile is wide enough for "Terminal" and the
labels are one line. The candidates were a second line for the label, a smaller
label font in this grid only, or dropping the redundant "Bunny " prefix inside a
Bunny OS launcher — the last costs no space at all and is what was done.

**Fixed and observed.** The same grid on the rebuilt image reads
`Files · Terminal · Bunny · Approvals` / `Companion · Diagnostics · Launcher ·
Settings` — eight tiles, none ellipsised. The full application name still goes
to the accessible name, so a screen reader hears "Bunny Companion".

### 3.2 The suggestion panel floats unanchored — **P3**

The panel carrying "Open Terminal" / "Browse my files" sits in the middle-right
of the screen, level with the character's head, with no visual connection to the
character or to the assistant card below it. It reads as a menu belonging to
nothing.

The assistant card has a clear owner and a clear anchor; this does not. Either it
should point at the character the way the speech bubble does, or it belongs
inside the assistant card.

### 3.3 The Network & Power card is mostly empty — **P3**

Roughly half the card is a blank plot area with a single flat line and one marker.
On an idle machine there is nothing to draw, which is honest, but the result is a
card whose largest element carries no information. A sparkline that collapses to
its label when there is no traffic would use the space or give it back.

### 3.4 The System card's CPU ring reads 2%, then 0% — **not a defect**

Recorded so it is not re-reported: the two screenshots are 14 minutes apart and
the ring differs. That is a live gauge behaving correctly, and the small purple
dot on the ring is the current value marker.

### 3.5 "Assistant offline — open Settings" — **P0, fixed, see §1**

Full diagnosis in `VISUAL_SLICE_REPORT.md` §3.3. Two things about how it
*presented* are worth keeping here:

- The message named an action ("open Settings") that would not have helped. There
  was nothing to configure; the program could not be executed.
- The assistant card simultaneously showed **"Thinking…"**. The desktop was
  telling the user two contradictory things at once — that the assistant was off,
  and that it was working — and neither was true.

A surface that reports availability and a surface that reports activity should
not be able to disagree. They currently derive from different state
(`AssistantService._available` and an optimistic local status string), and
nothing reconciles them.

## 4. What was not assessed

- **Any resolution but 1920×1080.** The layout suite covers more; this does not.
- **Hardware rendering.** Everything here is llvmpipe. Blur, shadow and any
  GPU-dependent effect may differ.
- **Motion.** Screenshots are stills. Nothing here says whether a transition is
  smooth, or whether reduced-motion is honoured — that belongs to the
  accessibility run.
- **Any screen but the home view.** Files, Apps, Settings and the Store were not
  reached in these runs.

## 5. Priorities

| # | Finding | Priority | State |
|---|---|---|---|
| 3.5 | The desktop cannot start its assistant | **P0** | **Fixed and observed** — the suggestion panel now offers real prompts, and a request completes end to end |
| 3.5 | Availability and activity can contradict each other | P2 | Open |
| 3.1 | Five of eight launcher labels unreadable | P2 | **Fixed and observed** |
| 3.2 | Suggestion panel unanchored | P3 | Open |
| 3.3 | Network card mostly empty | P3 | Open |
