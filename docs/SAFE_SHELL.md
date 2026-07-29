# Bunny Safe Shell

GDM exposes `Bunny (Safe Shell)` alongside Bunny and the retained base GNOME session. The wrapper marks `BUNNY_SHELL_MODE=safe`, stops `bunny-shell.target`, and starts the distribution GNOME session. The system Bunny extension checks the mode and adds no panel/keybindings. Bunny status/search services, Bunny Desktop autostart, and custom animations are absent; user data and projects are untouched.

Safe Shell retains Files, GNOME Terminal, GNOME Settings, logs, display repair, extension management, updates, recovery, and manual administration. It uses the default GNOME theme and does not require Bunny Core, provider access, plugins, models, or network.

Repair sequence:

```text
systemctl --user status bunny-shell-status.service
journalctl --user -u bunny-shell-status.service
gnome-extensions list
bunny-os doctor
bunny-search status
```

Repeated extension crashes should be repaired or the extension disabled from Safe Shell; no remote extension installation is automatic. GDM selection and end-to-end safe-mode behavior remain VM gates.
