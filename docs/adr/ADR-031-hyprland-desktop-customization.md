# ADR-031: Hyprland as Bunny desktop customization compositor

- Status: accepted for source scaffolding; runtime qualification pending
- Date: 2026-11-07
- Supersedes (partially): ADR-004 Phase 1 “no custom compositor” constraint for the *primary customization surface*; GNOME/Mutter remains for Safe Shell and the transitional GNOME session

## Context

Phase 1 and Phase 2 selected GNOME/Mutter and an image-owned GNOME Shell extension so Bunny could ship a desktop without owning a compositor. Product preference now requires Hyprland for desktop customization (project preferences, 2026-11-07). Replacing Mutter wholesale would put display-stack, accessibility, and GDM qualification at risk; leaving the preference unimplemented would leave no customization layer.

## Decision

1. **Primary Bunny session (`bunny`)** launches Hyprland with image-owned configs under `shell/components/hyprland/`, installed to `/usr/share/bunny-shell/hyprland`.
2. **Transitional dual-path**: `bunny-gnome` keeps the existing GNOME Shell extension session; `bunny-safe` remains plain GNOME without Bunny services.
3. **GDM** remains the greeter. AccountsService templates continue to seed `Session=bunny`, which now means Hyprland.
4. **Packages** are declared in `build/packages/hyprland.txt` and included in desktop-bearing profiles. Hermetic builds must re-resolve `package-lock.json` and refresh the retained snapshot before claiming an installable image.
5. **Fallback**: if `/usr/bin/Hyprland` is missing at session start, `bunny-hyprland-session` execs the GNOME Bunny wrapper so login still works on an incomplete image.

## Consequences

- Desktop customization (gaps, borders, animations, keybinds, wallpaper, status bar) is edited in Hyprland config, not only in the GNOME extension.
- The GNOME extension remains available for qualification and for users who choose Bunny (GNOME).
- Portal backend for the Hyprland session is `xdg-desktop-portal-hyprland` (with GTK portal for file dialogs).
- Theme tokens, product keybinds, and companion layer-shell integration are follow-on decisions; this ADR only establishes the compositor customization path.
- ADR-004’s accessibility/portals requirements still apply: screen capture and synthetic input stay portal-mediated.
