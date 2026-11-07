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

## Open product decisions

These are intentionally not locked by this scaffolding:

- Final accent/theme (light vs nocturne vs story themes from `shell/themes`)
- Full keybind map (companion, trust, launcher parity with the GNOME extension)
- Whether Waybar is permanent or replaced by a Bunny chrome surface
- Raster wallpaper pipeline (SVG may not load in every hyprpaper build)
- When to retire the transitional `bunny-gnome` session
