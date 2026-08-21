# Bunny-owned visual surfaces — inventory and reuse map

**What this is** Every user-facing surface Bunny OS owns, what renders it, and
what this phase does with it. Written before any visual code was edited, because
§3 of the brief asks for the inventory first and because the last four phases
each found that the surface which looked least interesting was the one hiding the
defect.

**Method** `git ls-files` for what exists, `grep` for what imports it, and
`build/scripts/install_routes.py` for what reaches the image. A surface is only
listed as live if something installs it *and* something loads it — that
distinction turns out to matter, and is the largest finding here.

---

## 1. Five findings that shape the phase

### 1.1 There are two Bunny palettes, and they do not resemble each other

| | Source | Accent | Background |
|---|---|---|---|
| GTK surfaces | `shell/themes/tokens.json` | mint `#88E7C4` / evergreen `#087F5B` | `#111815` / `#F5F7F4` |
| Desktop shell | `.../gnome-shell-extension/lib/tokens.js` | violet `#8B5CF6` | `#080B12` |

`docs/DESIGN_SYSTEM.md` §"Two palettes, and why" already records this and says
the fix — one source compiled into both at build time — "is worth doing and is
not done yet". It is the §1 requirement of this phase, so it is now done rather
than recorded.

### 1.2 The richer of the two token files has no runtime consumer

`shell/themes/tokens.json` is schema version 2 and carries exactly what this
phase asks for: `elevation` (flat/raised/floating/modal), `focus` (2 px ring,
2 px offset, never removed), `scrim` (solid at high contrast), `companion.phase`
(one entry per presentation phase), `risk` (marker shape as well as colour),
`standing` (`unenforced` as a badge that coexists with `granted`), and
`contrast` thresholds.

It is installed to `/usr/share/bunny-shell/themes` and **nothing reads it**. The
only consumers are `tests/accessibility/test_accessibility.py` and
`tests/shell/test_companion_surfaces.py`. The same is true of
`shell/themes/bunny-light.css`, `bunny-dark.css` and `bunny-high-contrast.css` —
nine lines each, shipped, never loaded.

The `theme` setting (`system` / `bunny-light` / `bunny-dark` / `high-contrast`)
is stored, validated, and rendered back to the user as a sentence in Settings.
Nothing applies it.

### 1.3 `trustPrompt.js` is a good component with no caller

`lib/trustPrompt.js` builds a drawable model from `trust.explain.TrustPrompt`,
with body ordering, deny-focused defaults, risk tokens by *name* rather than
colour, and `highContrast` / `largeText` / `screenReader` options. It is exactly
the §18 component.

Nothing in the extension imports it. The Trust prompt that was answered on screen
in the previous phase is `.bunny-assistant-approval` in
`lib/assistant/panel.js` — a strip inside the assistant card that displays

```js
this._approvalLabel.text = String(approval?.reason ?? 'Allow Bunny to perform this action?');
```

and two buttons. One string. `companion.presentation.ApprovalPresentation`
already projects `action`, `destination`, `destinationDetail`, `providerId`,
`dataClassification`, `estimatedCostUnits`, `alternatives` and `safeDefault`;
the drawn surface uses one of the nine.

### 1.4 The text-scaling failure has a specific cause, and it is not the stylesheet

`desktopShell.js` believes it honours text scaling:

```js
_textScale() {
    const match = /(\d+(?:\.\d+)?)\s*$/.exec(St.Settings.get().font_name ?? '');
    ...  // points / 11
}
```

`St.Settings.font_name` comes from `org.gnome.desktop.interface font-name`, which
is `Cantarell 11` before and after `text-scaling-factor` is changed — GNOME
applies text scaling through Xft DPI for GTK clients and never rewrites that key.
So `_textScale()` returns `1` at every scale, the layout solver is told nothing
changed, and the measured result was 0.09 % of the screen against a 0.15 % noise
floor.

The absolute pixel font sizes are the *second* half: even with the scale read
correctly, 43 of 43 `font-size` declarations are `px` and would not have grown.
Both halves have to be fixed for either to show.

### 1.5 High contrast is not partially honoured; it is not consulted

No JavaScript or Python in the repository reads `high-contrast` from
`org.gnome.desktop.a11y.interface`, and no code reads `St.Settings.high_contrast`.
The 0.18 % of the screen that changed when it was enabled is GNOME restyling its
own message tray behind the Bunny desktop. There is one palette in
`stylesheet.css` and no code path that could select another.

---

## 2. Reuse map

`KEEP` — correct as it stands, verify under the new configurations.
`MIGRATE` — sound structure, consumes the design system in this phase.
`REPLACE` — the current implementation is the defect.
`DEFER` — out of scope for this phase, named so it is not forgotten.
`REMOVE` — dead.

### 2.1 The desktop shell — `shell/components/gnome-shell-extension/`

GJS + St. Installed to `/usr/share/gnome-shell/extensions/bunny-shell@bunny-os.org`.
This is where the measured failures live.

| Surface | File | Class | Why |
|---|---|---|---|
| Visual layer | `stylesheet.css`, `lib/tokens.js` | **REPLACE** | 43/43 absolute px, 151 literal colours, one theme. Becomes generated output of the token layer. |
| Trust prompt | `lib/assistant/panel.js` (approval strip) | **REPLACE** | §18: one string where nine projected fields exist. Becomes the Trust component. |
| Trust projection | `lib/trustPrompt.js` | **MIGRATE** | Right shape, no caller. Gains one. |
| Task input / transcript / status | `lib/assistant/panel.js` | **MIGRATE** | Status strings are ad-hoc; §21 wants one task-state component. |
| Speech bubble | `lib/assistant/bubble.js` | MIGRATE | Tokens only. |
| Suggestions | `lib/assistant/suggestions.js` | MIGRATE | Tokens; the unanchored-panel finding (`VISUAL_QA_REPORT.md` §3.2) stays open. |
| Top bar | `lib/topBar.js` | MIGRATE | Tokens + scale-aware metrics. |
| Sidebar, power menu | `lib/sidebar.js` | MIGRATE | Tokens + scale. |
| Dock | `lib/bottomDock.js` | MIGRATE | Tokens + scale. |
| System / Quick Access / Media / Agenda / Monitor cards | `lib/cards/*.js` | MIGRATE | Tokens + reflow. Quick Access tile width must scale or its labels re-ellipsise at 150 %. |
| Notifications | `lib/notificationLayer.js` | MIGRATE | Tokens; severity is currently a 3 px coloured left border — colour alone, fails §19. |
| Task workspace | `lib/taskWorkspace.js` | MIGRATE | Consumes the §21 component. |
| Character | `lib/character/*.js` | KEEP | Cairo, not CSS. Motion budget already routed through `lib/animation.js`. §17 behaviour is checked, not rewritten. |
| Layout solver | `lib/layout.js` | **MIGRATE** | Already takes `scale`; the caller passes a constant 1. Metrics become scale-derived. |
| Motion | `lib/animation.js` | KEEP | Already consults `enable-animations` and collapses to 0. Verified, not changed. |
| Wallpaper | `lib/wallpaperLayer.js` | KEEP | One gradient; becomes token-derived, no behaviour change. |
| Panel indicator | `extension.js` | KEEP | Three status lines in GNOME's own menu; inherits GNOME's theme. |

### 2.2 GTK4 surfaces — `shell/services/bunny_shell/ui.py`

`bunny-launcher`, `bunny-settings`, `bunny-approvals`, `bunny-tasks`,
`bunny-plans`, `bunny-project`, `bunny-command`, `bunny-privacy`,
`bunny-notifications`, `bunny-quick-settings`, `bunny-workspace`.

**KEEP.** 555 lines of plain GTK4 with no custom CSS and no hard-coded colour or
font size anywhere in the file. Every one of these already scales, already
follows light/dark, and already follows high contrast, because Adwaita does.
They are the proof that the platform pipeline works and the desktop shell is the
outlier.

Two things to verify rather than change: the `theme` setting they display is
inert (§1.2), and their accessible names come from `update_property(LABEL)`
already.

### 2.3 Companion window — `companion/gtk_shell.py`

**KEEP.** Its 13-line CSS blob is written against the system palette
(`@window_bg_color`, `alpha(@accent_bg_color, .12)`) and its one font size is
`.82em`. It declares no transition anywhere, which is how it honours
reduced motion by construction. This is the house style the shell should have had.

`MIGRATE` for its four presentation modes (§16), which is model work in
`companion/presentation.py`, not styling.

### 2.4 Trust consent surfaces — `companion/trust_surface.py`

| Surface | Class | Why |
|---|---|---|
| `TextConsentSurface` | **KEEP** | The reference implementation; §31's screen-reader path. |
| `GtkConsentSurface` | MIGRATE | `Adw.MessageDialog` inherits the platform theme correctly, but flattens `prompt_lines()` into one `body` string. §18 wants structure. |
| `AutomationSurface`, `DenyingSurface` | KEEP | Not user-facing. |

### 2.5 Installer and first run

`installer/first_run/app.py`, `installer/first_run/alpha.py`,
`installer/frontend/app.py`, `installer/companion_flow.py`.

**DEFER.** Adw-based, using Adwaita's own `.title-1` classes, so they inherit
scaling and contrast. §1 of the brief is explicit that the installer is not built
in this phase; §49 makes it the next one. They are listed so that "the installer
already exists in some form" is on the record.

### 2.6 Recovery

`companion/recovery.py` produces `RecoveryReport` — text, no widgets. The
graphical recovery entry point is `bunny-companion-recovery`. **DEFER**, with the
note that §23's error taxonomy is where recovery copy should come from.

### 2.7 Application chooser

There is no separate chooser surface. The launcher (`ui.py`) and the Quick Access
card serve that role. **DEFER** — nothing to migrate.

### 2.8 Dead prototypes

`apps/`, `ui/`, `visual/`, `visual-v2/`, `visual-v4/`, `desktop/` (Tauri).

**REMOVE — already removed.** Between them they contain exactly one tracked file
(`ui/.test/app.js`); everything else on disk is `__pycache__` and a Rust
`target/` directory left by `VISUAL_PROTOTYPE_ISOLATION_CLEANUP`. The brief asks
about "any Tauri desktop surfaces still in use": there are none, and
`desktop/src-tauri` has no tracked source.

### 2.9 Token files — `shell/themes/`

**MIGRATE.** `tokens.json` becomes the single source §1.1 asks for, and gains the
consumer it has never had. The three `bunny-*.css` files are **REPLACE**: nine
lines of `@define-color` that no display server has ever loaded, superseded by
generated output.

---

## 3. What the phase does, in migration order

Following §39, and stopping where the evidence stops.

1. One token source (`shell/themes/tokens.json`) extended to carry typography,
   and compiled into both rendering stacks at build time.
2. Typography derived from `text-scaling-factor`, read from the setting that
   changes.
3. Semantic colour, four themes, generated.
4. One focus treatment, generated per theme.
5. Motion tokens, already routed, verified at zero.
6. Trust component (§18/§19).
7. Task status, result, error (§21/§22/§23).
8. Companion modes (§16/§17).
9. Desktop shell surfaces.
10. Settings.

## 4. What this audit does not establish

- **That any of it looks right.** Everything above is structural. §32 and §33
  are screenshots from a booted guest, and nothing here substitutes for them.
- **That the GTK surfaces pass.** "Adwaita handles it" is a strong prior and not
  a measurement; they are in the runtime matrix for that reason.
- **Anything about hardware rendering.** The whole desktop record to date is
  llvmpipe.
