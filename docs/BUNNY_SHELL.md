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

## Components

- `bunny-shell@bunny-os.org`: fixed top-panel entry points and keyboard bindings.
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
