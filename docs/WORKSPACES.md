# Bunny workspaces

Workspace schema 1 associates a Linux virtual desktop with optional project, Bunny thread, intent, plan, tasks, application-window references, terminal sessions, recent files, permission summaries, sandbox sessions, and checkpoints. The on-disk store is private per-user JSON under the XDG state directory and is updated atomically with a bounded cross-platform transaction lock.

Supported operations are create, list, show, rename, duplicate metadata, archive, restore, attach/detach project, and attach Bunny thread. IDs and thread IDs are validated. Project paths must already be directories. Provider credential, API key, token, password, and secret-shaped fields are rejected recursively.

Archiving or detaching affects metadata only. It never deletes, renames, moves, or edits a project. Window moves and virtual desktop binding will use GNOME Shell APIs after the exact GNOME 50 VM behavior is qualified; the schema already contains stable references without claiming that runtime integration was exercised.

```text
bunny-workspace create "Bunny OS" --project /path/to/bunny-os
bunny-workspace list
bunny-workspace rename <id> "Bunny OS Phase 2"
bunny-workspace archive <id>
bunny-workspace restore <id>
```

The dashboard does not run project scripts on open. Future `Run tests`, checkpoint, and review actions must call Bunny Core and its permission/sandbox APIs.
