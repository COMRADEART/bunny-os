# Bunny OS design system

The design language is calm, compact, and operational: a deep evergreen base, mint action color, neutral warm surfaces, blue keyboard focus, amber caution, and red danger. Status is never encoded by color alone; every badge includes text/icon semantics.

## Two palettes, and why

The GTK surfaces (`bunny-launcher`, `bunny-settings`, `bunny-approvals` and the rest) use the evergreen and mint palette described above, from `shell/themes/tokens.json`. The **desktop shell** — top bar, sidebar, dock, dashboard, character — uses a dark violet palette from `shell/components/gnome-shell-extension/lib/tokens.js`: background `#080B12`, panels `rgba(17,21,32,0.72)`, accent `#8B5CF6` with `#A78BFA` for text and focus, and the standard green/amber/red for success, warning and error.

They are separate files because they are separate rendering stacks: St's stylesheet language has no custom properties and cannot read a JSON token file, so a shared source would have to be compiled into both at build time. That is worth doing and is not done yet — until it is, the two are kept in step by review, and this paragraph is the record that they are two.

Two departures from the specified palette, both for contrast: secondary text is `#B4BAC6` rather than `#A9AFBC`, which measures 4.36:1 on the panel and misses WCAG AA; and `#8B5CF6` is used for fills only, because at 3.4:1 it cannot carry body text. `tests/shell/test_desktop_shell.py` fails a token that is defined and never used, and fails any interactive class without a `:focus` rule.

Tokens live in `shell/themes/tokens.json`. Spacing is 4/8/12/20/32 px; controls use 10 px radii, surfaces 18 px, and hero surfaces 28 px. The system UI font and system monospace font are used so Bunny distributes no restricted font file. Motion is 100 ms for acknowledgement and 180 ms for navigation, falling to zero in reduced-motion mode. Reduced transparency uses opaque surfaces.

## Token schema version 2 — the Companion, Trust and App Capsule surfaces

`shell/themes/tokens.json` is now schema version 2. Every version 1 value is unchanged and `tests/shell/test_companion_surfaces.py` asserts three of them, so an existing surface renders identically; version 2 is purely additive.

What it adds is named for the decision each token carries rather than for how it looks, so a high-contrast or reduced-transparency theme can redefine the value without a surface knowing. `elevation` has four levels of which only `modal` is raised unasked — that is the Trust prompt, the only thing in Bunny OS permitted to interrupt. `focus` is a 2 px ring at 2 px offset on every focusable control in every theme, never removed for aesthetics. `scrim` is *solid* at high contrast rather than lighter, because a light dim leaves a modal indistinguishable from the page behind it. `companion.phase` has one entry per `companion.presentation.PRESENTATION_PHASES` value, tested for completeness so a phase the runtime can produce always has something to draw; only `attention` intensity may pulse, and only when the motion budget is non-zero. `risk` marks high and critical with a *shape* beside the heading as well as a colour, because colour alone fails for a person who cannot distinguish those hues and a permission prompt is the worst place for that failure. `standing` treats `unenforced` as a badge that coexists with `granted`, because "allowed, and not actually restricted" is two facts and one row.

Reduced motion sets the animation budget to zero — zero, not shorter — and deliberately leaves the Companion's fidelity where it was. A person who asked for less movement did not ask for a worse picture. Degradation between fidelity tiers is driven by measurement instead: 3D → lightweight 3D → animated 2D → static → text-only, one tier per measured problem, with no path back up within a single evaluation, because a marginal machine oscillating between tiers looks worse than the lower tier does. The ladder names match `companion.presentation.IMPLEMENTED_PRESENTATIONS` and a test asserts the JavaScript side is a subset of it.

Themes are System, Bunny Light, Bunny Dark, and High Contrast. GNOME/Adwaita remains the fallback and supplies mature widget behavior. Bunny CSS defines backgrounds, text, action, and visible focus without overriding platform widget semantics. High Contrast uses black/white/cyan/yellow with three-pixel focus outlines.

Launcher results use kind label, primary name, secondary context, and an explicit consequence/permission indicator. Approval UI reserves the strongest emphasis for exact scope and risk. Notifications avoid prompt/file previews on lock. Keyboard focus order follows visual reading order, and all essential gesture actions have keyboard/mouse equivalents.
