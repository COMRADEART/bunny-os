# ADR-004: Desktop environment

- Status: accepted for development image
- Date: 2026-07-28

Use GNOME/Mutter on Wayland, with XWayland for legacy applications. GNOME has mature accessibility, portals, notifications, power/session integration, multi-user GDM, broad Fedora hardware testing, and an established Fedora Atomic desktop precedent. It is heavier than some alternatives but minimizes Phase 1 integration invention.

KDE Plasma is a viable later profile with strong Wayland and customization, but a second portal/session matrix would dilute foundation validation. COSMIC is promising and now available in Fedora Atomic variants, but has less long-term compatibility history. No new compositor or custom shell is built in this phase.

X11 is not the default. Screen capture, file picking, remote desktop, and input automation must go through portals or another visible OS permission surface. Accessibility APIs remain available and may not be disabled merely as a hardening shortcut.

