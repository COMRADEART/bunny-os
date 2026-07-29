# Bunny OS desktop baseline audit

Date: 2026-07-28  
Baseline commit: `8fc27253e448cfe0cbe267231f816012f831ebf0`  
Feature branch: `feature/bunny-shell`

## Current foundation

| Area | Phase 1 baseline | Phase 2 decision |
|---|---|---|
| Desktop | GNOME on Fedora 44 | retain as the stable desktop foundation |
| Compositor | Mutter, Wayland default; XWayland compatibility | retain; no compositor or input-stack fork |
| Panel and overview | GNOME Shell top bar, overview, quick settings, app grid | retain and add the bounded `bunny-shell@bunny-os.org` extension |
| Launcher | GNOME application search plus `.desktop` entries | retain app launching; add typed Bunny Launcher domains |
| Notifications | GNOME Shell and freedesktop notification service | retain daemon; project privacy-filtered Bunny summaries |
| Settings | GNOME Control Center and settings daemons | deep-link stable modules; own only Bunny/update/recovery modules |
| Session | GDM, `gnome-session`, logind, systemd user manager | add selectable Bunny and Bunny Safe Shell wrappers; retain GNOME session |
| Accessibility | AT-SPI, Orca, GNOME keyboard/accessibility settings | retain and package; apply WCAG 2.2 AA targets to Bunny surfaces |
| Extensions | system and per-user GNOME Shell extensions | one image-owned extension, GNOME 50 compatibility pin, safe-mode no-op |
| Theme | Adwaita/libadwaita, system light/dark/high contrast | retain fallback; add original Bunny tokens, CSS, icons, wallpapers |
| Files/terminal | Nautilus and GNOME Terminal | integrate; never replace conventional access |
| Portals | XDG Desktop Portal GNOME backend | sole Bunny path for file, screenshot, screen-share, camera/microphone grants |

Fedora 44 currently packages GNOME Shell 50. The extension is therefore pinned to Shell 50 and uses the post-GNOME-45 ES module API. GNOME documentation confirms machine-wide extensions live under `/usr/share/gnome-shell/extensions`, custom sessions are exposed through a session desktop entry plus `gnome-session`, and existing keyboard navigation/lock/notification shortcuts remain accessibility-critical. Sources: [Fedora GNOME Shell package](https://packages.fedoraproject.org/pkgs/gnome-shell/gnome-shell/fedora-44.html), [GNOME custom sessions](https://help.gnome.org/system-admin-guide/session-custom.html), [GNOME extensions](https://help.gnome.org/system-admin-guide/extensions.html), [GNOME keyboard shortcuts](https://help.gnome.org/gnome-help/shell-keyboard-shortcuts.html).

## Current Bunny integration

Phase 1 registers `art.comrade.Bunny.desktop`, the `bunny:` URI scheme, a private user service, XDG portals, and the contract-1.0.0 root broker. The installed Bunny payload is still an explicit non-functional 0.2.0 placeholder. Bunny Desktop/Core lifecycle, authenticated app-server state, and real task/plan/approval actions cannot be runtime-validated until a signed upstream Linux artifact exists.

Phase 2 adds user-owned workspace/search/settings state, strict server-authoritative Bunny summary projection, GNOME session choices, Bunny panel entry points, typed launcher routing, safe desktop-entry parsing, command proposal classification, settings/status surfaces, Nautilus context actions, and degraded modes. It adds no root service and no generic privileged executor.

## Missing functionality and evidence

- No image or VM was available on this Windows host; GDM selection, Wayland launch, extension load, multi-monitor behavior, lock/suspend, and portal dialogs remain unobserved.
- The upstream Bunny artifact is absent, so task/plan/approval actions are read-only unavailable-state surfaces rather than end-to-end Core calls.
- GNOME notification grouping and quick-setting device toggles remain GNOME-owned; Bunny adds entry points and policy status, not replacements.
- Optional tiling uses future reviewed GNOME mechanisms; Phase 2 ships conventional floating/snap/workspace behavior.
- Hardware camera, microphone, battery, Bluetooth, touchpad, HiDPI, GPU, external displays, and screen reader execution are untested.

## Replacement risks

Replacing Mutter would duplicate display, input, scaling, GPU, XWayland, lock-screen, accessibility, and portal security work. Replacing GNOME Settings, Nautilus, Terminal, notifications, or AT-SPI would create similar compatibility and privilege risks. Those components stay authoritative. Extension compatibility is narrower but failure-isolated: safe shell disables Bunny behavior, the base GNOME session remains selectable, and a crashed user service cannot prevent login.

## Integration opportunities

The stable seams are GNOME Shell extensions, freedesktop desktop entries/notifications, GNOME Settings panel URIs, Nautilus extensions, systemd user units, AT-SPI, logind, XDG portals, the existing Bunny URI/app-server contract, and the Phase 1 broker. Runtime qualification should focus on these seams instead of new desktop infrastructure.
