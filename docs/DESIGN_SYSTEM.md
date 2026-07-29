# Bunny OS design system

The design language is calm, compact, and operational: a deep evergreen base, mint action color, neutral warm surfaces, blue keyboard focus, amber caution, and red danger. Status is never encoded by color alone; every badge includes text/icon semantics.

Tokens live in `shell/themes/tokens.json`. Spacing is 4/8/12/20/32 px; controls use 10 px radii, surfaces 18 px, and hero surfaces 28 px. The system UI font and system monospace font are used so Bunny distributes no restricted font file. Motion is 100 ms for acknowledgement and 180 ms for navigation, falling to zero in reduced-motion mode. Reduced transparency uses opaque surfaces.

Themes are System, Bunny Light, Bunny Dark, and High Contrast. GNOME/Adwaita remains the fallback and supplies mature widget behavior. Bunny CSS defines backgrounds, text, action, and visible focus without overriding platform widget semantics. High Contrast uses black/white/cyan/yellow with three-pixel focus outlines.

Launcher results use kind label, primary name, secondary context, and an explicit consequence/permission indicator. Approval UI reserves the strongest emphasis for exact scope and risk. Notifications avoid prompt/file previews on lock. Keyboard focus order follows visual reading order, and all essential gesture actions have keyboard/mouse equivalents.
