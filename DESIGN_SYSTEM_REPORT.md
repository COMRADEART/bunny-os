# The Design System and Accessibility Foundation

**What this is** The phase that made the Bunny desktop respond to the two
accessibility settings it had been measured ignoring, and turned the permission
prompt that was proved on screen last phase into a component that carries the
facts behind it.

**Where it starts** `qualification/capsules/evidence/a11y-b09f523/accessibility.json`:

> text-scaling-factor 1.5 changed 0.09 % of the screen and high contrast changed
> 0.18 %, against a 0.15 % noise floor measured from a screenshot taken at the
> *same* settings as the baseline. The desktop honours neither: all 43 font
> sizes are absolute pixels and all 151 colour literals are hardcoded.

Two of those three numbers are below the noise floor. The desktop was not
partially honouring the settings; it was not consulting them.

---

## 1. What was actually wrong

The stylesheet was the visible half and not the whole of it. Five findings, each
of which is a thing that existed and did nothing.

### 1.1 The text scale was read from a key that never changes

```js
_textScale() {
    const match = /(\d+(?:\.\d+)?)\s*$/.exec(St.Settings.get().font_name ?? '');
    ...  // points / 11
}
```

`St.Settings.font_name` comes from `org.gnome.desktop.interface font-name`, which
is `Cantarell 11` before and after `text-scaling-factor` is changed — GNOME
applies text scaling through Xft DPI for GTK clients and never rewrites that key.
So this returned `1` at 125 %, at 150 % and at 200 %. The layout solver was told
nothing had changed and faithfully redrew the same desktop.

The 43 absolute pixel font sizes were the second half: even with the scale read
correctly, none of them would have grown.

### 1.2 High contrast was not partially honoured; it was not consulted

No code in the repository read `high-contrast` from
`org.gnome.desktop.a11y.interface` or `St.Settings.high_contrast`. There was one
palette in `stylesheet.css` and no code path that could have selected another.
The 0.18 % that changed was GNOME restyling its own message tray behind the Bunny
desktop.

### 1.3 There were two Bunny palettes and they shared no colour

| | Source | Accent | Loaded by |
|---|---|---|---|
| GTK surfaces | `shell/themes/tokens.json` | mint `#88E7C4` | nothing |
| Desktop shell | `lib/tokens.js` | violet `#8B5CF6` | the desktop |

`shell/themes/tokens.json` was schema version 2 and carried precisely what this
phase needed — `elevation`, `focus`, `scrim`, `companion.phase`, `risk`,
`standing`, contrast thresholds. It was installed to
`/usr/share/bunny-shell/themes` and its only consumers were two test files. So
were `bunny-light.css`, `bunny-dark.css` and `bunny-high-contrast.css`, nine
lines each. `docs/DESIGN_SYSTEM.md` recorded the split and said resolving it "is
worth doing and is not done yet".

The `theme` setting — `system` / `bunny-light` / `bunny-dark` / `high-contrast` —
was stored, validated, and rendered back to the user as a sentence in Settings.
Nothing applied it.

### 1.4 Both halves of the Trust component existed and were not connected

`companion.capsule_task_bridge.CapsuleSupport.prompt_for()` built the structured
permission prompt — application identity, resource, expected effect, file access,
network, private app data. **It had no caller anywhere in the repository.**

`shell/.../lib/trustPrompt.js` turned that structure into a drawable model, with
body ordering, deny-focused defaults and risk tokens by name. **It had no caller
either**, outside its own tests.

What shipped was `.bunny-assistant-approval`: a strip inside the assistant card
displaying one string.

```js
this._approvalLabel.text = String(approval?.reason ?? 'Allow Bunny to perform this action?');
```

`capsule_task_bridge` concatenated three sentences into `reason` *because* the
surface could only hold one. `ApprovalPresentation` projected nine fields; the
drawn surface used one of them.

### 1.5 A contrast figure in the documentation does not reproduce

`docs/DESIGN_SYSTEM.md` justified moving secondary text from `#A9AFBC` to
`#B4BAC6` because the first "measures 4.36:1 on the primary panel and misses
WCAG AA". It measures **8.51:1**, and no plausible Bunny backdrop produces 4.36 —
the closest candidate, the panel over the wallpaper gradient, gives 8.28.

The contrast module reproduces the three standard WCAG worked examples exactly
(`#767676` on white = 4.54:1, `#777777` = 4.48:1, `#595959` = 7:1), so the
arithmetic is not in question. The hand-computed figure was wrong by about a
factor of two. The colour it argued for is fine and stays.

---

## 2. What was built

One token source, `lib/design/tokens.js`. Four themes. The stylesheet is output.

```
tokens.js ──▶ theme.js ──▶ stylesheet.js ──▶ CSS string
   │          (resolve       (render, St-safe)      │
   │           per settings)                        ▼
   │                                       themeManager.js
   │                                       (write, load, unload)
   └──▶ render_design_assets.mjs ──▶ stylesheet.css   (shipped default/fallback)
                                └──▶ shell/themes/tokens.json (Python consumers)
```

St's stylesheet language has no custom properties, no `calc()`, no media queries
and no `var()`. That is why the stylesheet is a function rather than a file:
everything those features would have done happens in JavaScript before a single
declaration is written, and what St receives is a flat sheet of literals.

`themeManager.js` watches four settings across three schemas —
`text-scaling-factor` and `color-scheme` on `org.gnome.desktop.interface`,
`high-contrast` on `org.gnome.desktop.a11y.interface`, and `enable-animations`
through `St.Settings` — renders a sheet, writes it to the runtime directory,
loads it, and only then unloads the shipped one. Every failure path leaves the
shipped sheet in place and names itself in `degraded`.

### 2.1 Static evidence

Measured by `tests/shell/test_design_system.py`, all under node against the real
modules.

| Claim | Before | After |
|---|---|---|
| `font-size` declarations | 43 | 75 |
| …that are absolute pixels | 43 of 43 | 0 of 75 |
| …unchanged between 100 % and 150 % | 43 of 43 | 0 of 75 |
| Size at 200 % ÷ size at 100 % | 1.00 | 2.00, every declaration |
| Colour literals in the stylesheet | 151, none theme-derived | every one from a semantic role |
| Themes | 1 | 4 (light, dark, high-contrast light, high-contrast dark) |
| Colour roles per theme | — | 24, complete in all four |
| Contrast pairs checked | 0 | 88, all passing WCAG AA |
| Narrowest text margin | not measured | 4.88:1 (AA is 4.5:1) |
| Reactive classes with a `:focus` rule | asserted for 12 | measured for 27, in all four themes |

### 2.2 What the contrast gate found while the palette was being written

Five real problems, none of which was noticed by eye:

| Pair | Measured | Fix |
|---|---|---|
| white on accent `#8B5CF6` (dark) | 4.23:1 | accent → `#7C3AED` |
| `borderStrong` on the panel (dark) | 1.72:1 | alpha 0.18 → 0.36 |
| `borderStrong` on the panel (light) | 1.87:1 | alpha 0.28 → 0.52 |
| `blocked` at high contrast (dark) | 9.25:1, *worse* than the ordinary theme's 9.9:1 | `#FF8A8A` → `#FFAFAF` |
| `blocked`/selection at high contrast (light) | 7.38:1 and 11.54:1, both worse than ordinary | `#B00000` → `#8B0000`, selection `#002060` |

The last two are the ones worth keeping: enabling high contrast would have
*downgraded* the contrast of exactly the state that says a permission was
refused. The gate now asserts that no pair gets worse when the setting is enabled
and that the tightest pair clears WCAG AAA.

### 2.3 What the layout solver found

At 150 % on a 1920×1080 screen the desktop dropped the assistant card — which is
the card the permission question appears in. Cards were dropped by position
(last in the column first) and the assistant was last.

Drops now follow importance: `PROTECTED_CARDS` names the assistant, discretionary
cards are shed first, and the surviving cards keep reading order. The Trust
surface is present in all twenty resolution × scale combinations measured
(1366×768, 1280×800, 1920×1080, 2560×1440, 3840×2160 at 100/125/150/200 %), with
no overlapping pairs and nothing off-screen.

### 2.4 The Trust component

`ApprovalRequirement` now carries `prompt`; `capsule_task_bridge` fills it from
`prompt_for()`; `ApprovalPresentation` carries it to the surface; `buildApproval`
turns it into the model; `TrustComponent` draws it.

The prompt is **display-only and outside the consent binding**, for the reason
`destination_detail` already was: binding a rendering would mean rewording a
sentence invalidates an answer somebody already gave, while swapping the provider
behind it might not. `test_two_prompts_with_different_wording_bind_identically`
holds that.

Its fields are an allowlist (`PROMPT_FIELDS`) bounded and markup-escaped before
they leave the runtime, because several originate in an application's own
manifest and are drawn in a security dialog. A requester cannot add a field, and
a field cannot become long enough to push the buttons off screen.

What the prompt shows now, from the runtime rather than from wording:

```
GNU Image Manipulation Program            ← identity
org.gimp.GIMP
GNU Image Manipulation Program wants to open holiday.png
It will save a copy as holiday-resized.png. Your original file will not be changed.
Shared with the application: holiday.png
  ✓ Files: holiday.png only              ← each row a glyph, a word and a colour
  ⃠ Network: Off
  ✓ App data: Isolated
                            [ Allow ] [ Deny ]
Details ▸  Request · Operation · Task · Plan · Destination · Data
```

The accessible names the booted-guest slices press — `Allow this Bunny action`
and `Deny this Bunny action` — are unchanged, and a test asserts the harness and
the component still agree on them.

The component is generic: seven future categories (camera, microphone, network,
screen capture, USB, Bluetooth, background execution) each draw a complete
question in the tests, and neither the component nor the projection contains the
words `resize`, `holiday` or `.png` outside their comments.

---

## 3. Runtime qualification

*This section is filled from the booted guest and is the part that decides the
phase. Nothing above substitutes for it: §9 of the brief is explicit that
automated contrast is not an accessibility result, and the last two phases each
found a defect that every text diagnostic had passed and one photograph caught.*

### 3.1 The design system loads on a real desktop

The first thing worth knowing, because it was the one genuine unknown: whether
`St.Theme.load_stylesheet` on a file written at runtime works in GNOME Shell 50,
and whether unloading the shipped sheet afterwards leaves the desktop styled
rather than bare.

It does. Photographed at 1920×1080 on the image built from `ae4c24a`: top bar,
sidebar, both card columns, character, dock and the assistant card all render
from the generated stylesheet, and the request typed into the assistant entry
shows the focus ring. At default settings the desktop is indistinguishable from
the one before this phase, which is the correct result — the default theme is
the same theme.

### 3.2 A regression this phase introduced, found by looking

Quick Access reads:

```
Files      Terminal    Bunny       Approvals
Companion  Diagnosti…  Launcher    Settings
```

**"Diagnosti…" is ellipsised.** The two smallest type sizes (9 px) were folded
upward into the `caption` role at 10 px — deliberately, because 9 px is below
what the rest of the desktop asks anyone to read — while the quick tile stayed
55 px wide. That is enough to re-break the defect `VISUAL_QA_REPORT.md` §3.1
fixed by dropping the "Bunny " prefix from these labels.

The arithmetic: the tile gives the label about 47 px of text width, and
"Diagnostics" at 10 px needs about 60. Three ways out, none free — a wider tile
drops the grid from four across to three, a two-line label makes the tile taller
and the card with it, and a smaller label reinstates the size that was removed on
purpose. It is a P2 and it is not fixed here, because fixing a visual defect
without being able to photograph the result is how this one arrived.

Both the tile width and the label size are theme values now, so whichever way it
goes it is one change in `design/tokens.js` rather than a hunt through a
stylesheet.

**245 tests pass and not one of them can see an ellipsis.**

### 3.3 Text scaling and high contrast — the two release blockers

Measured on the image built from `7edd3fd`, at 1920×1080 under llvmpipe. Each
preference is applied on its own and reverted before the next, so no figure is
taken against a desktop another setting has already changed — which the previous
run's figures were.

| Setting | Before (`b09f523`) | Now (`7edd3fd`) | × noise floor | Verdict |
|---|---|---|---|---|
| `text-scaling-factor` 1.25 | not measured | **19.2 %** of the screen | 363 | PASS |
| `text-scaling-factor` 1.5 | 0.09 % — *below noise* | **25.8 %** | 486 | PASS |
| `text-scaling-factor` 2.0 | not measured | **29.7 %** | 560 | PASS |
| high contrast | 0.18 % — *at noise* | **97.1 %** | 1832 | PASS |
| reduced motion | 0.04 % | 0.05 % | 1.0 | see §3.7 |
| noise floor (control) | 0.15 % | 0.053 % | — | — |

High contrast changes 97 % of the screen because the wallpaper goes too. The
first run of this sweep measured 39.6 % — cyan controls and opaque black panels
sitting on the ordinary purple wallpaper, because the wallpaper is GNOME's to
draw and the Bunny scrim over it was only dimming it. At high contrast the scrim
is now an opaque fill in the theme's ground, and the number is what replacing the
largest surface on the screen looks like.

The control is a screenshot taken with every setting restored, so it is what
"nothing changed" looks like on this guest.

Corroborated by control geometry rather than pixels alone. The same named
controls, measured through AT-SPI before and after:

| Control | 100 % | 125 % | 150 % | 200 % |
|---|---|---|---|---|
| `Allow this Bunny action` | 52 | 62 | 73 | **92** |
| `Applications` | 46 | 60 | 65 | 78 |
| `Account: Bunny desktop harness user` | 43 | 54 | 65 | 87 |
| `All apps` | 17 | 21 | 25 | 31 |

Twenty of sixty comparable controls grew at every scale and **none shrank**. The
forty that did not move are GNOME's own; the walk covers the whole session.

And the desktop **reflows** rather than scaling as a bitmap. At 200 % the
sidebar collapses to icons, the discretionary cards are shed, and the assistant
card — the one the permission question appears in — survives, which is what
`PROTECTED_CARDS` was added for. Photographed: the request and "Done. I made
Pictures/holiday-resized.png at 100 pixels wide. Your original wasn't changed."
are both legible at twice the size.

### 3.4 The Trust component, on screen

Photographed at `7edd3fd`. Every element §18 names, from the runtime rather than
from wording composed in the surface:

```
  ◈  Bunny Image Tool                        ← identity: name and id
     art.comrade.BunnyImageTool

  Bunny Image Tool wants to open             ← the fact, wrapped over three
  Pictures/holiday.png                          lines rather than truncated

  It will save a copy as holiday-resized.png.   ← the effect
  Your original file will not be changed.

  Shared with the application:               ← what is disclosed
  Pictures/holiday.png

  ✓  Files: Pictures/holiday.png only        ← each row a glyph, a word and a
  ⃠  Network: Off                                colour; none of the three alone
  ✓  App data: Isolated

     [ Allow ]   [ Deny ]                    ← Deny carries the focus ring
     Details                                 ← the technical panel, collapsed
```

The safe answer holds focus, both controls are fully on screen, and nothing
overflows the card.

And the granted slice still passes through it, with the permission answered by a
pointer press at the button's own accessibility extents:

```
journey-approval    "Allow this Bunny action" found after 268 nodes,
                    role=button, visible, extents 115x52 at (1630, 887)
journey-decision    pressed at (1687, 913)
journey-result      files ["holiday-resized.png"], pixels [100, 50],
                    sourceDigest 5de7c234… unchanged, ok=true
```

Both controls report `focusable: true` and carry their accessible names. §40's
routing is intact.

### 3.5 All three slices, through the rebuilt component

§45. Each answered by a pointer press at the button's own accessibility extents;
nothing in this harness can call `resolve_approval`.

| Slice | Pressed | Wrote | States after | The desktop said |
|---|---|---|---|---|
| granted | `Allow this Bunny action` | `holiday-resized.png`, 100×50 | idle → success → idle | "Done. I made Pictures/holiday-resized.png at 100 pixels wide. Your original wasn't changed." |
| denied | `Deny this Bunny action` | nothing | idle → warning → idle | — |
| failing | `Allow this Bunny action` | nothing | idle → **error** | "the task failed" |

The granted slice's source digest is unchanged (`5de7c234…`) and the failing
slice ran against the corrupt fixture (`4378dd67…`), allowed it, and failed
honestly rather than reporting a success it did not have.

`qualification/capsules/evidence/slices-7edd3fd/slices.json` records six claims,
all true: every slice put the question on screen, every slice was answered by a
pointer press, granted produced the file and left the source alone, denied wrote
nothing, and failing wrote nothing and said so.

### 3.6 Five defects the photographs found, which the suite did not

**The structured prompt never reached the screen.** The prompt was drawn with a
heading and two buttons and nothing else: no application identity, no resource,
none of "Files: holiday.png only / Network: Off / App data: Isolated". The
runtime carried it correctly the whole way — `prompt_for()` →
`ApprovalRequirement` → `ApprovalRequest` → the event payload →
`ApprovalPresentation.to_json()`, and a local test walks every hop — and
`bunny-shell-assistant` re-serialises the approval line field by field with six
fields listed and `prompt` not among them. The component's degraded path is what
was photographed, working exactly as designed, for a reason that had nothing to
do with the component.

**The prompt ran off the right of the screen.** `.bunny-trust-action` carried a
`min-width` of three times the button font size. Two of those plus padding
exceeded the 304 px card, St grew the panel rather than constraining it, and the
Deny button — the *safe* answer — was clipped by the screen edge. Width now
comes from `x_expand`; the height that makes it a comfortable touch target stays.

**Two labels ellipsised where they should have wrapped.** The prompt's heading
read `Bunny Image Tool want…` — the sentence saying what an application wanted to
do, cut off in the dialog asking whether to allow it — and at 200 % the greeting
read `Good evening, B…`, cutting the person's own name. `St.Label` ellipsizes at
the end by default and a `ClutterText` with both ellipsize and `line_wrap` set
ellipsizes, so setting `line_wrap` alone had done nothing at all.

All three are fixed at `2421199`, with a test for the first — the one no
existing test could have caught, because the projection was right, the component
was right, and the wire between them dropped one key.

Two more from the same photograph, fixed at `381852a` and `7edd3fd`:

**Quick Access read `Diagnosti…` again.** This is the defect
`VISUAL_QA_REPORT.md` §3.1 fixed once, by dropping the "Bunny " prefix, and it
came back because this phase folded the 9 px tile label up into the 10 px caption
role — deliberately, because 9 px is below what the rest of the desktop asks
anyone to read, with a consequence nobody looked for. The labels wrap now.

**High contrast left the wallpaper alone.** See §3.3: 39.6 % of the screen versus
97.1 % once the scrim goes opaque.

Five defects, from one screenshot, against a suite that grew from 245 to 249
passing tests without any of them turning red.

### 3.7 Reduced motion had never been set, and cannot be photographed

Two separate problems, and the first one hid the second.

`gsettings set org.gnome.desktop.a11y.interface reduced-motion true` is refused:
the key is an enum, `no-preference` or `reduce`. Every run of this sweep had
asked for `true`, and the read-back was `'no-preference'` — so every
reduced-motion figure in every accessibility record was measured on a desktop
that had never been asked for reduced motion. Fixed at `4e11ca2`; the read-back
at `7edd3fd` is `'reduce'` and `tookEffect` is true.

That did not change the number, and it never could have. **A screenshot is a
still.** A desktop that has stopped animating looks exactly like a desktop that
has finished animating, so the difference from the baseline sits at the noise
floor whether the preference is honoured or not — 0.04 % before, when it was not
being set, and 0.05 % now, when it is. The measurement cannot distinguish the two
states it exists to distinguish, so the record says
`NOT_MEASURABLE_BY_SCREENSHOT` rather than `FAIL`.

What is on the record instead: the setting took effect, `enable-animations` took
effect, and `lib/animation.js` collapses every duration to zero when it has —
which is measured under node, not asserted. Evidence that motion actually stopped
needs a moving-image capture, and this harness does not take one. That gap is
older than this phase (`ecb26959`, "why reduced motion could not have been
measured on this guest") and it is not closed here.

---

## 4. Maturity matrix

`Implemented` — the code exists and is reachable from a real caller.
`Unit tested` — measured under node or by the Python suite.
`VM validated` — observed in the booted guest.
`Hardware` — observed on physical hardware.
`Release qualified` — signed off against the release matrix.

| | Implemented | Unit tested | VM validated | Hardware | Release qualified |
|---|---|---|---|---|---|
| Design tokens | yes | yes | yes | no | no |
| Typography scaling | yes | yes | **yes** — 19–30 % at 125/150/200 % | no | no |
| Light mode | yes | yes | no — never selected on a guest | no | no |
| Dark mode | yes | yes | yes | no | no |
| High contrast | yes | yes | **yes** — 97.1 % | no | no |
| Keyboard | unchanged | yes | partial — focus lands on Deny | no | no |
| AT-SPI | unchanged | yes | partial — 1745 nodes, 551 interactive, 40 unnamed | no | no |
| Screen reader | unchanged | no | no — Orca present, never driven | no | no |
| Reduced motion | yes | yes | setting takes; effect not photographable | no | no |
| Companion full | unchanged | yes | yes | no | no |
| Companion compact | unchanged | yes | no | no | no |
| Companion minimal | not built | no | no | no | no |
| Companion text-only | unchanged | yes | no | no | no |
| Trust component | yes | yes | **yes** — all §18 elements drawn | no | no |
| Task component | model only | yes | no | no | no |
| Result component | model only | yes | no | no | no |
| Error component | model only | yes | no | no | no |
| Protected-space component | model only | yes | no | no | no |

Two rows are worth reading carefully. **Light mode has never been rendered on a
guest** — it is generated, contrast-checked and unit-tested, and no screenshot of
it exists, so it sits in exactly the position the evergreen palette sat in before
this phase. And **40 interactive controls in the accessibility tree are unnamed**,
which is a §30 result this phase measured and did not improve.

"model only" is the honest state for §20–§23: the projections exist and are
tested, the CSS for them is in the generated stylesheet, and nothing draws them
yet.

---

## 5. What this phase did not do

Stated so that the matrix above is not read as a plan.

- **The task, result, error and protected-space components are not drawn.** Their
  models and styles exist; the desktop still shows its own status strings.
- **The Companion's four presentation modes were not refactored.** §16 asked for
  Full / Compact / Minimal / Text-only projecting one task state; the fidelity
  ladder that exists today is `companionPresence.js`, unchanged by this phase.
- **There is no story or component harness.** §37's fast visual development loop
  is not built, so every visual check still costs a boot.
- **There is no visual-regression manifest.** §36.
- **No performance comparison was taken.** §41 asks for Companion idle CPU and
  memory, desktop memory, frame behaviour under llvmpipe and Trust-dialog latency
  before and after; none of those numbers exists for the new theme path.
- **Nothing was seen on hardware.** Every desktop measurement in this project is
  llvmpipe.
- **The Companion still reads high contrast from Bunny's own settings file.**
  `companion.settings.AccessibilityPreferences.high_contrast` is populated from
  Bunny's settings document and from nothing else; no code path reads
  `org.gnome.desktop.a11y.interface high-contrast` on that side. The desktop
  shell now does, and the Companion's GTK window is safe by construction because
  its CSS is written against the system palette — but the *character* renderer
  takes the preference from the file, so a person who enabled high contrast in
  GNOME gets an adapted desktop and an unadapted character. §8 says a
  Bunny-specific preference that ignores the platform one is not a fix; this is
  the last instance of that pattern in the tree and it is still there.

### 5.1 One thing that was found and deliberately not repaired here

`shell/services/bunny_shell/settings.py` still defines `theme` with the values
`system` / `bunny-light` / `bunny-dark` / `high-contrast`, and `ui.py` still
renders it back to the user as a sentence. It is applied by nothing, and after
this phase it is applied by nothing *and* contradicted by something: the desktop
follows `color-scheme` and the a11y preference regardless of what that key says.

Removing a settings key is a migration, and doing it in the same change as the
theme system would have made the migration invisible inside a large diff. It is
named here so the next phase removes it rather than discovering it.

---

## 6. Against §48, item by item

The brief's own condition first: *"If high contrast and text scaling still fail:
PHASE STATUS = INCOMPLETE."* They do not fail. Text scaling moves 19–30 % of the
screen at the three enlarged sizes and high contrast moves 97 %, against a
0.053 % noise floor. **The release blockers are cleared.**

The rest of §48 is not all met, and the phase is not complete against it.

| §48 requirement | State |
|---|---|
| typography responds to system scaling | **met** — 19.2/25.8/29.7 % at 125/150/200 % |
| 200 % text remains usable | **met** — photographed; the desktop reflows |
| high contrast produces a real adaptation | **met** — 97.1 % |
| semantic tokens replace hard-coded colours on core surfaces | **met** for the shell; the GTK surfaces already used the system palette |
| keyboard flow passes | **partial** — focus lands on the safe answer and both controls are focusable; no full traversal was driven |
| AT-SPI flow passes | **partial** — 1745 nodes walked, Trust controls named, roled and focusable; **40 interactive controls are unnamed** |
| Orca can operate the Trust/task flow | **not met** — Orca is installed and its version was read; it was never driven |
| reduced-motion flow passes | **partial** — the setting takes effect for the first time; the effect is not photographable (§3.7) |
| Companion full/compact/minimal/text-only truthful | **not met** — not refactored; minimal not built |
| granted/denied/failed slices still pass | **met** — all three, answered on screen |
| Trust prompt secure against hostile reason content | **partial** — bounded and escaped in the projection, with tests; never driven with a hostile string on a guest |
| no critical surface relies on colour or motion alone | **met** for Trust and security standing; notification severity still carries a coloured border whose text counterpart is styled but not yet drawn |
| core surfaces use the shared design system | **met** for the desktop shell |
| performance has not materially regressed | **not measured** — §41 was not attempted |

**PHASE STATUS: the release blockers are cleared; the phase is incomplete.**
Five of fourteen items are unmet or unmeasured, and the largest are Orca, the
Companion presentation modes, and the performance comparison.

---

## 7. Standing note on what a passing test here means

The static evidence in §2 says the desktop now *computes* different numbers when
a setting changes. It does not say a person can read the result, and it cannot:
the previous phase's most expensive defects were a character whose working pose
was a shrug and an "Assistant offline" message on a desktop whose runtime was
active, and both passed every assertion in the suite.

This phase is the same lesson again, and more expensively. The suite grew from
245 to 249 passing tests while the desktop was, in order: drawing a permission
dialog with none of its facts in it, running the Deny button off the edge of the
screen, ellipsising the sentence that said what an application wanted to do,
cutting the user's own name out of the greeting at 200 %, and painting a
high-contrast theme over a purple wallpaper.

**Five defects. One screenshot. Zero failing tests.**

Every one of them is now covered — the bridge hop by a test, the rest by the fact
that the next run photographs the same surfaces — but the general point stands
and is the reason §36 and §37 are listed in §5 as missing rather than as nice to
have. Until a component can be rendered and looked at without a twenty-minute
boot, looking at it will keep being the last thing anyone does.
