# Hyprland desktop customization

Bunny OS customizes the desktop through **Hyprland**. GNOME/Mutter remains packaged for **Bunny (Safe Shell)** and the transitional **Bunny (GNOME)** session.

## Layout

| Path | Role |
|---|---|
| `build/packages/hyprland.txt` | Fedora package set for Hyprland and companions |
| `shell/components/hyprland/` | Image-owned config tree |
| `shell/session/bunny-hyprland-session.py` | Session wrapper → `/usr/libexec/bunny-hyprland-session` |
| `shell/session/bunny.desktop` | GDM session id `bunny` (primary) |
| `shell/session/bunny-gnome.desktop` | Transitional GNOME Bunny session |
| `shell/session/bunny-safe.desktop` | Safe Shell (GNOME, Bunny target stopped) |

Installed destination: `/usr/share/bunny-shell/hyprland/`. The wrapper starts Hyprland with `--config /usr/share/bunny-shell/hyprland/hyprland.conf`.

## Modular config

- `hyprland.conf` — entry, monitor, dwindle/master, misc background colour
- `look-and-feel.conf` — gaps, borders, blur, shadows, animations (Bunny dark tokens)
- `input.conf` — keyboard/touchpad
- `keybinds.conf` — baseline Super binds (terminal, wofi, workspaces)
- `windowrules.conf` — float/opacity starters
- `autostart.conf` — portals, hyprpaper, waybar, hypridle
- `hyprpaper.conf` / `waybar/` — wallpaper and status bar chrome

## Session behaviour

1. Export `BUNNY_SHELL_MODE=normal`, `BUNNY_DESKTOP_COMPOSITOR=hyprland`, `XDG_CURRENT_DESKTOP=Bunny:Hyprland`.
2. Start `bunny-shell.target` (blocking; failure is journalled, login continues).
3. `exec Hyprland --config …`, or fall back to `bunny-shell-session` if Hyprland is not installed.

## Build note

Adding the hyprland package set updates `package-lock.json` `namedPackages`. A hermetic image build still needs `make resolve-package-lock` (and snapshot materialisation) so NEVRA entries and RPMs exist for the new names.

## Adaptive Hybrid layouts (M1)

Desktop / Focus / Studio are presentation layouts on the **Hyprland** primary session:

| Piece | Path |
|---|---|
| Geometry + retained task cursor | `shell/services/bunny_shell/adaptive_layout.py` |
| Task rail projection | `shell/services/bunny_shell/task_rail.py` |
| CLI | `bunny-adaptive-layout` (`shell/services/bin/bunny-adaptive-layout`) |
| Keybinds | `shell/components/hyprland/keybinds.conf` |
| Waybar indicator | `custom/bunny-layout` in `waybar/config.jsonc` |
| Contract | `docs/ADAPTIVE_HYBRID_INTERACTION_CONTRACT.md` |

`bunny-adaptive-layout set|cycle --apply` runs `hyprctl keyword` for gaps when available and syncs the GTK task rail (`bunny-task-rail`) for Focus/Studio (hidden on Desktop). Without a live Hyprland session / display that apply step is **NOT_RUN**, not a fake PASS. Absolute window placement is not claimed. See M1R: `docs/M1R_HYPRLAND_LIVE_INTEGRATION.md`.

## Open product decisions

These are intentionally not locked by this scaffolding:

- Final accent/theme (light vs nocturne vs story themes from `shell/themes`)
- Full Trust/companion keybind parity with the historical GNOME extension chrome
- Whether Waybar remains permanent or is replaced by a denser Bunny chrome surface
- Raster wallpaper pipeline (SVG may not load in every hyprpaper build)
- When to retire the transitional `bunny-gnome` session
- Spec text reconciliation: Adaptive Hybrid Spec still names GNOME/Mutter while ADR-031 + preference select Hyprland
