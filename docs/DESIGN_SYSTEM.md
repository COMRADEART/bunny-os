# Bunny OS design system

The design language is calm, compact, and operational: a deep evergreen base, mint action color, neutral warm surfaces, blue keyboard focus, amber caution, and red danger. Status is never encoded by color alone; every badge includes text/icon semantics.

## Two palettes, and why

The GTK surfaces (`bunny-launcher`, `bunny-settings`, `bunny-approvals` and the rest) use the evergreen and mint palette described above, from `shell/themes/tokens.json`. The **desktop shell** — top bar, sidebar, dock, dashboard, character — uses a dark violet palette from `shell/components/gnome-shell-extension/lib/tokens.js`: background `#080B12`, panels `rgba(17,21,32,0.72)`, accent `#8B5CF6` with `#A78BFA` for text and focus, and the standard green/amber/red for success, warning and error.

They are separate files because they are separate rendering stacks: St's stylesheet language has no custom properties and cannot read a JSON token file, so a shared source would have to be compiled into both at build time. That is worth doing and is not done yet — until it is, the two are kept in step by review, and this paragraph is the record that they are two.

Two departures from the specified palette, both for contrast: secondary text is `#B4BAC6` rather than `#A9AFBC`, which measures 4.36:1 on the panel and misses WCAG AA; and `#8B5CF6` is used for fills only, because at 3.4:1 it cannot carry body text. `tests/shell/test_desktop_shell.py` fails a token that is defined and never used, and fails any interactive class without a `:focus` rule.

Tokens live in `shell/themes/tokens.json`. Spacing is 4/8/12/20/32 px; controls use 10 px radii, surfaces 18 px, and hero surfaces 28 px. The system UI font and system monospace font are used so Bunny distributes no restricted font file. Motion is 100 ms for acknowledgement and 180 ms for navigation, falling to zero in reduced-motion mode. Reduced transparency uses opaque surfaces.

Themes are System, Bunny Light, Bunny Dark, and High Contrast. GNOME/Adwaita remains the fallback and supplies mature widget behavior. Bunny CSS defines backgrounds, text, action, and visible focus without overriding platform widget semantics. High Contrast uses black/white/cyan/yellow with three-pixel focus outlines.

Launcher results use kind label, primary name, secondary context, and an explicit consequence/permission indicator. Approval UI reserves the strongest emphasis for exact scope and risk. Notifications avoid prompt/file previews on lock. Keyboard focus order follows visual reading order, and all essential gesture actions have keyboard/mouse equivalents.
