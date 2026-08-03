# Bunny Visual Preview session isolation

> **VISUAL PROTOTYPE ONLY — DO NOT SET AS DEFAULT**

## Installed entries

- `sessions/bunny-visual-preview.desktop` is installed only as an additional
  Wayland session choice.
- `sessions/bunny-visual-preview.session` defines a separate GNOME session.
- `sessions/bunny-visual-preview.json` defines a GNOME Shell mode inheriting
  from `user` and enabling the preview extension.
- `sessions/bunny-visual-preview-session` sets preview-scoped environment and
  delegates to `gnome-session --session=bunny-visual-preview`.

No file replaces or edits `/usr/share/wayland-sessions/gnome.desktop`, the GNOME
Shell `user` mode, the AccountsService session preference, or GDM configuration.
The preview installer does not call `gsettings set`, `dconf update`, or
`alternatives` to change a user's default.

## Expected chooser

GDM continues to expose its upstream `GNOME` choice and additionally exposes
`Bunny Visual Preview`. The existing Bunny and Bunny Safe entries, when present,
are also independent. Removing the preview package removes only the preview
entry, mode, extension, and applications.

## Failure behavior

If the preview extension cannot start, GNOME Shell remains responsible for the
session. If the preview session cannot start, the user can select GNOME from the
unchanged session chooser. The preview never changes stored authentication or
implements a login mechanism.

## Installation mapping

| Repository source | Package destination |
| --- | --- |
| `sessions/bunny-visual-preview.desktop` | `/usr/share/wayland-sessions/` |
| `sessions/bunny-visual-preview.session` | `/usr/share/gnome-session/sessions/` |
| `sessions/bunny-visual-preview.json` | `/usr/share/gnome-shell/modes/` |
| `sessions/bunny-visual-preview-session` | `/usr/libexec/` |
| `shell/bunny-shell-extension/` | `/usr/share/gnome-shell/extensions/bunny-desktop-v1@bunny-os.org/` |

Packaging and nested preview must stage these paths without modifying the host
desktop session.
