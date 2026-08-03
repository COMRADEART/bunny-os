# Bunny Desktop V2 architecture

> VISUAL PROTOTYPE ONLY · NOT RELEASE QUALIFIED · DO NOT MERGE INTO MAIN

Bunny Desktop Preview is an additive GNOME session on Wayland. Its session file
starts the upstream GNOME components and enables only the V2 extension. The
existing GNOME session files are neither modified nor shadowed.

```text
GNOME / Wayland
  └─ bunny-desktop-v2@bunny-os.org
       ├─ shared state and fixed-action services
       ├─ top bar, dock, palette, and right panel
       ├─ ModeController (regular | character)
       └─ GTK 4 / libadwaita companion applications
```

The `ModeController` subscribes to GSettings changes and applies an immutable
presentation snapshot to registered components. It is event-driven: there is
no polling loop, background animation, compositor replacement, or shell
restart. Both visual modes use one shared action registry and the existing
approval adapter boundary.

The preview launcher requires `BUNNY_VISUAL_V2_PREVIEW=1`. Packaging excludes
mock fixtures and refuses to run when `BUNNY_VISUAL_MOCK_MODE=1`.

