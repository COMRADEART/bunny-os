# ADR-004: Desktop environment

- Status: accepted for development image; **primary customization compositor updated by ADR-031 (2026-11-07)**
- Date: 2026-07-28

Use Wayland with XWayland for legacy applications. Phase 1 selected GNOME/Mutter for mature accessibility, portals, notifications, power/session integration, multi-user GDM, broad Fedora hardware testing, and an established Fedora Atomic desktop precedent.

**Update (ADR-031):** the primary Bunny session customizes the desktop through **Hyprland**. GNOME/Mutter remains for Bunny Safe Shell, the transitional Bunny (GNOME) session, and shared GTK/portal surfaces. GDM remains the greeter.

KDE Plasma remains a viable later profile but is not the customization path. X11 is not the default. Screen capture, file picking, remote desktop, and input automation must go through portals or another visible OS permission surface. Accessibility APIs remain available and may not be disabled merely as a hardening shortcut.

