# ADR-005: Bunny Shell architecture

- Status: accepted for implementation; runtime qualification pending
- Date: 2026-07-28

## Decision

Build Bunny Shell as a selectable GNOME 50/Mutter Wayland session using an image-owned GNOME Shell extension, GTK4 user surfaces, fixed desktop entries, and bounded systemd user services. Retain GDM, GNOME Shell/Mutter, Control Center, Nautilus, Terminal, notifications, portals, logind, and AT-SPI. Retain base GNOME and add Bunny Safe Shell.

The shell consumes Bunny Core's authenticated server-authoritative projection and Phase 1 broker methods. It owns no root path, generic command service, provider secrets, Bunny database, compositor, notification daemon, settings daemon, file manager, terminal emulator, or accessibility stack.

## Consequences

This minimizes high-risk display/session invention and preserves conventional Linux access. GNOME extension compatibility is a release gate tied to Fedora 44's GNOME 50. A broken Bunny component degrades to GNOME rather than blocking login. A custom compositor is rejected.
