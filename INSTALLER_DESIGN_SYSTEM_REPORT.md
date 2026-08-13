# Setup design-system integration report

§55.3 and §24. Whether the setup surface reuses the design system already built,
or merely resembles it.

Commit `efa2dd62`. Evidence: `shell/themes/resolved-themes.json`,
`qualification/installer/setup-states.json`,
`qualification/design/story-manifest.json`.

---

## 1. The obstacle §24 does not mention

§24 asks the installer to reuse the typography tokens, semantic colours, spacing,
radii, focus state, high contrast, reduced motion and light/dark behaviour
already built, and not to introduce installer-only visual conventions.

There is a real obstacle to doing that literally. The design system's renderer,
`lib/design/stylesheet.js`, emits **St** CSS for GNOME Shell. The setup surface
is a **GTK4** application. Both languages are subsets of CSS and they are not the
same subset: St has `spacing` and `icon-size` and GTK4 has neither; GTK4 has
`outline` and box-model `margin` and St's differ.

So the sheet cannot be shared. Three ways to respond, and only one of them is
reuse:

| Approach | What it would mean |
|---|---|
| Hand-write installer CSS from the token *values* | A second palette kept in step by care. This is precisely the arrangement `tokens.js` was created to end — the desktop and `shell/themes/tokens.json` had drifted into two entire palettes sharing no colour. |
| Re-implement `resolveTheme` in Python | A second implementation of arithmetic that must agree exactly, failing silently: an installer whose padding scaled at a slightly different rate looks fine alone and wrong beside the desktop it installs. |
| **One token source, two renderers** | What was built. |

## 2. What was built

```
lib/design/tokens.js          the values, authored once
        │
        ├── lib/design/theme.js  resolveTheme()   the arithmetic, authored once
        │        │
        │        ├── lib/design/stylesheet.js  ──►  St CSS      (GNOME Shell)
        │        │
        │        └── render_design_assets.mjs  ──►  shell/themes/resolved-themes.json
        │                                                │
        │                                                └──►  installer/theme_css.py
        │                                                          ──► GTK4 CSS (setup)
        └── render_design_assets.mjs ──► shell/themes/tokens.json (Python consumers)
```

`installer/theme_css.py` renders GTK4 CSS and **decides nothing**. The claim is
checkable in one grep: there is no colour literal in the file, no font size, no
padding value, no radius. Every number comes out of a resolved theme.

## 3. Why the themes are pre-resolved

The installer is Python and the arithmetic is JavaScript — the clamp, the
half-rate space scaling, the rule that high contrast implies opaque surfaces, the
compositing of translucent colours onto their own background. The existing Python
consumers bridge that by shelling out to node (`tests/shell/test_design_system.py`
does exactly that), which a live installer cannot do because **node is not in the
image**.

So the combinations are enumerated at build time. There are only thirty-two: two
schemes × two contrast settings × four offered text sizes × motion on or off.
That is enumerable because the accessibility screen offers four named sizes
rather than a range — a design decision that turns out to make the whole bridge
possible.

`shell/themes` is already installed as a *tree* route to
`/usr/share/bunny-shell/themes`, so `resolved-themes.json` ships without a new
install route.

**A theme that cannot be resolved raises.** `theme_css.resolve` refuses a text
scale nobody offers rather than falling back, because a person who chose 200 %
and silently got 100 % has been lied to by the surface that offered it.

## 4. What the tokens actually decide

| §24 asks for | Where it comes from | Observed |
|---|---|---|
| typography | `type.{display,title,heading,body,bodySmall,caption,button,mono}` | body 12 → 15 → 18 → 24 px across the four offered sizes |
| semantic colours | `colour.*` roles only; `PALETTE` is not exported | `danger`, `warning`, `success`, `accent`, `selection`, `border`, three surface levels |
| spacing | `space.*`, half-rate scaled | `space.md` 12 → 18 px at 200 % |
| radii | `radius.{control,card,panel,floating,modal}` | scaled with spacing |
| focus state | `focus.{width,offset}` | 2 px normally, **3 px under high contrast** |
| high contrast | `themes.highContrast{Light,Dark}` | light HC is `#FFFFFF` on `#000000` |
| reduced motion | `motion.*`, all zeroed | every `transition` renders `0ms` |
| light/dark | `themes.{light,dark}` | both rendered and drawn |

## 5. Two decisions the integration forced, both improvements

**No control has a fixed height.** The first version of the GTK renderer used a
`metric.controlHeight` that does not exist. Finding that led to a better rule
than the one intended: a `min-height` chosen to look right at 100 % is exactly
what clips its own label at 200 %, because the label scales at the glyph rate and
the box does not. Every control is now sized by its font plus its padding, both
of which already scale. §39 expressed as a stylesheet rule rather than as a test.

**A display minimum had to be declared.** The story harness first measured
button overflow against `metric.cardWidth` — 304 px, the *desktop's* floating
card — and reported 40 findings against a full-window surface. Nothing anywhere
declared how small a screen the installer supports.
`installer/hardware/preflight.py:MINIMUM_SETUP_DISPLAY` now says 1024×768, and
the harness measures against the screen less its padding. That padding shrinks at
200 % while the screen does not, which is the whole of §39: things must wrap,
not grow.

800×600 was rejected as dishonest — at 200 % text a 600 px-tall surface cannot
show a destructive warning and its confirmation control at once, and §39 forbids
hiding destructive-warning text.

## 6. The story harness draws the shipped stylesheet

§35's "renderable without a VM boot" is only worth something if what is drawn is
what ships. `render_setup_states.py` emits the **real GTK CSS**, per
configuration, into the fixtures the story reads — so a panel that looks right in
the story looks right because the same rules produced it, translated for the
browser exactly as the St sheet already was.

Seven configurations are rendered: dark, light, both at 200 %, high contrast in
both schemes, and reduced motion. The story fails loudly if a configuration is
added there without regenerating here, because an unstyled panel that still
"renders" is precisely the silent pass the harness exists to prevent.

## 7. Installer-only conventions, and the one that exists

§24 asks that none be introduced without need. The setup surface adds exactly one
class of rule the desktop does not have: `.bunny-setup-warning-danger`, which is
the only role anywhere that uses the danger colour as a **border** at the focus
width, and the only one with a raised type weight.

That is deliberate and §11 is the need. A destructive consequence must have a
treatment that means exactly one thing wherever it appears, and reusing an
existing card or notification style would make "this will erase your disk" look
like every other panel. The colour still comes from `colour.danger`; only the
composition is new.

`button.bunny-setup-action-danger` is likewise distinct from `-primary`, so the
forward action on an ordinary screen and the destructive action on the
confirmation screen can never be the same shape in the same place.

## 8. What is not established

* The GTK CSS has been **rendered and drawn on a workstation**, not on the
  installer ISO. GTK's own rendering is not in question; what is untested is
  whether the live image's GTK finds the theme file at
  `/usr/share/bunny-shell/themes/resolved-themes.json`.
* **Contrast ratios are measured on the token pairs the components actually
  put together** (`contrast.effectiveRatio`, AA body threshold) — but in the
  browser translation, not on GTK's own compositing.
* Reduced motion is asserted structurally: every transition renders `0ms`. No
  one has watched a reduced-motion install and confirmed nothing depends on
  animation to communicate completion or error, which is what §41 actually asks.
