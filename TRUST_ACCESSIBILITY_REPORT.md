# Accessibility of the Bunny Desktop and the Trust Prompt

**What this is** An assistive-technology pass against a *booted* Bunny OS
session: names, keyboard reach, actions, reduced motion, text scaling, high
contrast and the shipped screen reader. Not a source review.

**Image** `b09f523dcd71`, profile `shell`, 1920×1080, llvmpipe
**Harness** `desktop-drive.py --accessibility` → AT-SPI + gsettings + QMP `screendump`
**Verdict** Two defects that make the desktop unusable for people who need
larger text or higher contrast, and one that made a security question
unannounceable. The third is fixed.

> This document is **not** `ACCESSIBILITY_QUALIFICATION_REPORT.md`. That one is
> generated from `operations/data/qualification-matrices.json` and must not be
> hand-edited. This is the phase's own runtime pass, and where it resolves a
> scenario in that matrix it does so by editing the data.

---

## 1. Method, and why each check is shaped this way

Every preference is **set, read back, and photographed**. The read-back is not
ceremony: `gsettings set` succeeds against a key the running shell never reads,
so a report that recorded only the write would say the desktop honours a
preference it ignores.

The tree is walked **at the default first**, and that walk is the negative
control for the walks after it. Without it, "0 unnamed controls" cannot be told
from "the walk returned nothing" — a failure this harness has produced before.

The Trust prompt is measured **while it is on screen**, because that is the only
moment its keyboard reachability exists to be measured. It cannot be asked about
before the question appears or after it is gone.

## 2. Findings

### 2.0 How "nothing changed" was measured

"The screenshots look identical" is an eyeball claim, so it was replaced with a
pixel count — and, by luck of the run's own design, with a control.

The pass restores every preference at the end and photographs the result. That
final shot is taken at **the same settings as the baseline**, minutes later, so
whatever differs between those two is drift from the live CPU and network gauges
and nothing else. That is the noise floor.

| Comparison against the baseline | Pixels differing | Share of screen |
|---|---:|---:|
| `a11y-05-restored` — **same settings, the control** | 3,118 | 0.15 % |
| `a11y-02-reduced-motion` | 860 | 0.04 % |
| `a11y-03-large-text` (`text-scaling-factor` 1.5) | **1,948** | **0.09 %** |
| `a11y-04-high-contrast` | 3,693 | 0.18 % |

Setting the text scale to 1.5 changed **less of the screen than leaving the
settings alone did**. High contrast changed about as much as the gauges did on
their own. At 1920×1080 with 43 distinct type styles on screen, honouring either
preference would have redrawn essentially every glyph — several percent at
minimum, not a tenth of one.

So the finding is not "it looked the same to me". It is that the change
attributable to the preference is **smaller than the drift from two clocks
ticking**.

### 2.1 The desktop ignores `text-scaling-factor` — **P1**

Set to `1.5`, read back as `1.5`, and the screen changed by 0.09 % — below the
0.15 % noise floor established by the control above. No label, no heading and no
button text is larger anywhere.

The cause is structural and exact:

```
font-size declarations in shell/components/gnome-shell-extension/stylesheet.css : 43
    of those in absolute pixels                                                 : 43
    of those in relative units (em / rem / pt)                                  :  0
```

There is nothing for a scale factor to multiply. A person who needs larger text
sets the system preference, and the Bunny desktop — the surface they spend all
their time in — does not change.

### 2.2 The desktop ignores high contrast — **P1**

Set `org.gnome.desktop.a11y.interface high-contrast` to `true`. The screen
changed by 0.18 %, against a 0.15 % noise floor — indistinguishable from the
gauges ticking.

```
colour literals in the stylesheet          : 143
    derived from the theme (-st-, var(), currentColor) : 0
```

`lib/assistant/trustPrompt.js` line 44 states that the prompt "does not hardcode
colours, so the stylesheet and the high-contrast theme decide the values". The
stylesheet decides them. The theme decides nothing, because there is no path by
which it could. **The module documents a property its own stylesheet defeats** —
which is worse than not claiming it, because it is the kind of statement a
reviewer would take at face value.

### 2.3 A permission question appeared without taking focus — **P1, fixed**

`showApproval` made both buttons `can_focus = true` and then focused neither. The
text entry kept the focus it took when the panel opened.

So a keyboard user had to guess that a question had appeared and then Tab to find
it, and a screen reader announced nothing at all — because nothing had changed
focus. For an ordinary control that is an inconvenience. For the surface that
decides whether an application may read someone's files, it is the difference
between being asked and being bypassed.

Fixed: the prompt now takes focus when it becomes visible, and lands on the
button matching the request's own `safeDefault` — **Deny unless it says
otherwise**. The trust layer's oldest rule is that an unanswered question is a
denial, so the button under the finger, the one a reflexive Return presses, has
to agree with it.

### 2.4 The screen reader is installed

`orca-50.2-1.fc44` at `/usr/bin/orca`, with `at-spi2-core 2.60.6` and
`at-spi2-atk 2.60.6`. `brltty` is **not** installed, so braille is unavailable —
consistent with `BRLAPI_REQUALIFICATION_REPORT.md`.

What is claimed here is deliberately modest: Orca is present and runs far enough
to report its own version. Capturing what it *speaks* needs an audio path and a
speech engine, neither qualified here, and the surfaces expose the names and
roles it would read. That is not the same as a blind user completing the journey,
and this report does not say it is.

## 3. What the desktop does right

- **39 accessible names** across 14 modules; the Trust prompt's two buttons carry
  `Allow this Bunny action` and `Deny this Bunny action`, which is how the
  graphical driver finds them without a test hook.
- **The full application name goes to the accessible name** even where the label
  is shortened to fit a 55px tile — drawn short, spoken in full.
- **Reduced motion is honoured in code**: `companionPresence.js` pins the motion
  budget to 0, `taskWorkspace.js` likewise, and `desktopShell.js` tracks
  `notify::enable-animations`. Motion cannot be judged from stills, so this is
  reported as implemented and observed-in-source, not as validated.

## 4. Evidence level

| Claim | Level |
|---|---|
| `text-scaling-factor` has no effect | **VM runtime validated** — set, read back, photographed, and 0.09 % against a 0.15 % control |
| `high-contrast` has no effect | **VM runtime validated** — 0.18 % against the same control |
| The stylesheet cannot respond to either | **Tested** — 43/43 absolute, 143/0 hardcoded |
| The Trust prompt takes focus, safe default | **Tested**; not yet observed on screen |
| Orca is installed and starts | **VM runtime validated** |
| Reduced motion is honoured | **Implemented**; stills cannot show it |
| A screen-reader user can complete the journey | **Not established** |
| Braille | **Not available** — `brltty` is not installed |

## 5. What this costs to fix

§2.1 and §2.2 are one piece of work and it is not small: relative type
throughout, theme-derived colour throughout, and every layout re-validated at
each supported resolution — the layout suite currently asserts pixel positions
that assume fixed type.

It is the largest accessibility gap in the desktop, and it is recorded in
`KNOWN_LIMITATIONS.md` rather than being left in a report nobody reads before
planning the next phase.
