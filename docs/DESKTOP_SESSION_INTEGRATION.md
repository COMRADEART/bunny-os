# Desktop-session integration

GNOME/GDM provides multi-user sessions, lock/logout, power events, themes, notifications, accessibility and portal brokers. `art.comrade.Bunny.desktop` registers the launcher and `bunny:` URL handler. Tauri uses XDG Desktop Portal/native dialogs in the owning session. Autostart is off until that user enables `bunny-desktop.service`; one user's service has no access to another user's runtime directory, portal grants, notifications, Secret Service, or Bunny XDG state.

Suspend/resume, lock/logout, tray behavior and power events must be exercised with the actual signed Tauri Linux artifact. Screen capture and input injection are not implicit desktop integration features and require visible OS-mediated authorization.

## Phase 2 session choices

`/usr/share/wayland-sessions/bunny.desktop` starts the ordinary GNOME session after exporting `BUNNY_SHELL_MODE=normal` and starting `bunny-shell.target`. The image-owned GNOME 50 extension adds only fixed Bunny entry points. `/usr/share/wayland-sessions/bunny-safe.desktop` exports safe mode, stops the Bunny target, and the extension becomes a no-op. Base GNOME remains installed and selectable.

The shell uses user-owned XDG config/state/cache/runtime paths and systemd user isolation. It cannot access another user's state or portals. GDM login, multi-account isolation, logout, lock, suspend/resume, extension crash recovery, and Safe Shell are specified but remain VM tests.
