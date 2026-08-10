# Bunny Shell

Bunny Shell is a GNOME 50 desktop experience, not a compositor. GDM offers `Bunny`, the retained base GNOME session, and `Bunny (Safe Shell)`. The Bunny wrapper exports an explicit session mode, starts `bunny-shell.target`, and executes the distribution GNOME session. The safe wrapper stops that target and the image-owned extension becomes a no-op.

## Boundaries

```text
GNOME/Mutter/portals/logind
        |
image-owned GNOME extension and GTK surfaces
        |
bunny-shell-status | bunny-search | bunny-workspace
        |
Bunny Core summary API        Phase 1 broker
(server-authoritative)        (typed privileged methods)
```

The shell runs as the logged-in user. It has no root, provider credential, Bunny database access, arbitrary shell command endpoint, screen capture backend, or direct system mutation. System actions must become contract-1.0.0 broker requests and retain Polkit. Bunny decisions must go to Bunny Core; the shell consumes only the bounded private `core-summary` projection. The Phase 2 source does not fabricate an approval result when Core is absent.

## The Bunny desktop

`bunny-shell@bunny-os.org` draws the desktop itself: a top bar, a left navigation sidebar, a bottom dock, a dashboard of cards, and the Bunny assistant character standing in the centre. It is built from St and Clutter actors inside the compositor process, which is what makes it the desktop rather than a window on one — GNOME's own top bar is hidden while it runs and restored the moment it stops.

Actors go in two layers. Chrome (top bar, sidebar, dock, toasts, search results) is added through `Main.layoutManager.addChrome`, so it sits above windows and hides under a fullscreen window. Desktop content (character, cards, bubbles, contrast scrim) goes into the background group beneath `global.window_group`, so an open window covers it the way it covers a wallpaper.

Modules live under `shell/components/gnome-shell-extension/lib`:

- `desktopShell.js` orchestrates; it imports no `gi` module except the three it needs to place actors.
- `topBar.js`, `sidebar.js`, `bottomDock.js`, `wallpaperLayer.js`, `notificationLayer.js`, `widgets.js`.
- `cards/` — system overview, quick access, media, agenda, network and power.
- `character/` — `state.js` (the ten states), `definition.js` (the figure, as data), `renderer.js` (a Cairo renderer and an image-package renderer behind one interface), `viewport.js`.
- `assistant/` — speech bubble, contextual suggestions, and the persistent input card.
- `services/` — every reading of the system. No component touches `/proc`, DBus or a subprocess directly; `test_desktop_shell.py` fails the build if one starts to.

`layout.js` imports nothing at all, so the geometry is evaluated under `node` in `tests/shell/test_desktop_shell.py` and "no widget overlaps another" is measured at seven resolutions rather than checked once by eye.

Real sources: CPU and memory from `/proc`, storage from `statfs`, temperature from hwmon with a thermal-zone fallback, battery from `/sys/class/power_supply`, throughput from `/proc/net/dev`, connection state from NetworkManager, volume from the session mixer, backlight from gnome-settings-daemon, applications from `Shell.AppSystem`, media from MPRIS, calendar from `org.gnome.Shell.CalendarServer` with a `$XDG_DATA_HOME/bunny/agenda.json` fallback, power actions from the session manager and logind. **A reader that cannot answer returns nothing and the widget prints `Unavailable`.** No metric has a default value.

The assistant reaches the companion runtime through `/usr/bin/bunny-shell-assistant`, which reuses `companion.protocol`. The desktop contains no second implementation of that protocol, and the character's state follows the runtime's own presentation phase.

Two settings govern it: `desktop-enabled` (leave GNOME's desktop in place) and `desktop-blur` (`auto` disables blur where there is no DRM render node, because `Shell.BlurEffect` samples every blurred surface each frame and llvmpipe cannot afford it). If the desktop fails to start, the extension tears down what it built, restores GNOME's panel and leaves the panel indicator running, so a fault costs a feature and not the session.

### The local agenda file

```json
[{"summary": "Algorithms class", "start": "2026-08-09T10:00:00", "allDay": false}]
```

Written to `$XDG_DATA_HOME/bunny/agenda.json`. Used only when the calendar server is unavailable. Events outside today are ignored; an unparseable row is skipped with one log line rather than emptying the list.

## Components

- `bunny-shell@bunny-os.org`: the desktop, plus fixed top-panel entry points and keyboard bindings.
- `bunny-launcher`: applications and typed intent/search surface.
- `bunny-workspace`: versioned project-aware metadata.
- `bunny-search`: metadata-only index for explicit locations.
- `bunny-settings`: GNOME Settings links plus Bunny/update/recovery sections.
- `bunny-terminal`: normal GNOME Terminal and non-executing command proposals.
- `bunny-command`, `bunny-tasks`, `bunny-plans`, `bunny-approvals`, `bunny-project`: GTK surfaces.
- `bunny-shell-status.service`: bounded, restart-limited, truth-preserving availability projection.
- `bunny-search-index.timer`: refreshes only approved locations.

## Failure modes

Without Bunny Core, applications, Files, Terminal, GNOME Settings, workspaces, updates, and recovery remain available. Without the broker, privileged buttons are disabled/unavailable and there is no fallback executor. Without the search index, application launch and direct workspace access remain. Repeated service crashes are bounded by systemd; Safe Shell exposes a plain GNOME repair environment.

## Session operations

Logs are under the user journal: `journalctl --user -u bunny-shell-status.service`. Logout, suspend/resume, lock, multi-user separation, XWayland, and accessibility remain GNOME/logind responsibilities. Runtime claims require the VM matrix in `docs/TESTING.md`.
