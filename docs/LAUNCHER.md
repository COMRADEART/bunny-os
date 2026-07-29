# Bunny Launcher

Bunny Launcher combines conventional installed applications with explicit result kinds: Application, File, Folder, Workspace, Bunny command, System action, Setting, Task, Plan, and approved memory metadata. Phase 2 source implements applications, approved file/folder metadata, workspaces, settings, task/plan entry points, and typed Bunny/system intents.

Desktop entries are read from standard XDG application directories with per-user precedence. The parser rejects symlinks, oversized files, shell syntax, shell/privilege wrappers, unsafe absolute executable paths, unsupported field codes, malformed URL handlers, hidden entries, and invalid names/icons. Launch uses `Gio.DesktopAppInfo`, not an interpolated shell command.

Pinned and recent application IDs are private, bounded, persistent launcher state. Pins sort before recent and ordinary results; a successful launch records a recent ID. Categories and application descriptions remain visible, and GNOME Settings → Applications is the management/uninstall link. Workspace-targeted window placement waits for the qualified GNOME workspace API rather than pretending a launch was placed.

Natural-language routing is deterministic for supported phrases. `Check for system updates` becomes `system_action` with `brokerMethod=update.check`, broker permission, and confirmation. `Ask Bunny …` becomes `bunny_request`; it never becomes a broker call. Ambiguous input remains `search`. No language model invokes the broker.

Consequential results open a detail/confirmation or approval flow. They do not execute directly from search. Application launch is non-consequential; system mutation is not.

Default shortcut is `Super+Space`. `Super+A` remains GNOME's application grid, so approvals use `Super+Shift+A`. The editor is the GNOME extension settings schema; a future preferences UI may write only those typed keys.

Repository smoke examples:

```text
python shell/services/bin/bunny-launcher --intent "Open network settings"
python shell/services/bin/bunny-launcher --intent "Check for system updates"
python shell/services/bin/bunny-launcher --query Terminal
bunny-launcher --pin org.gnome.Terminal.desktop
bunny-launcher --state
```
