# Troubleshooting

```text
systemctl --user status bunny-shell-status.service
journalctl --user -u bunny-shell-status.service
gnome-extensions info bunny-shell@bunny-os.org
bunny-shell status
bunny-search status
bunny-os doctor
```

Use Bunny (Safe Shell) if the extension or session loops. If the broker is down, inspect the system unit from a normal terminal; do not add sudo exceptions or a generic fallback. If search is corrupt, remove/re-add the exact approved location and rebuild; never grant the whole home as a workaround.
