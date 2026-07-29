# Multi-monitor and gestures

Mutter remains authoritative for monitor discovery, hotplug, primary display, rotation, scaling, mixed DPI, fullscreen, lock screen, and per-user display configuration. Bunny Shell adds no display configuration database and opens GNOME Displays for changes.

The launcher appears on the currently focused GNOME shell monitor according to the extension/shell placement available in GNOME 50. Bunny workspace metadata may remember a monitor number as a hint, but hotplug can invalidate it; Mutter state wins. Window movement between workspaces/monitors uses GNOME APIs only after runtime qualification.

Test matrix: connect/disconnect, primary switch, 100/125/150/200% scale, mixed DPI, portrait rotation, panel/launcher placement, full screen, lock/unlock, suspend/resume, workspace behavior, and virtual-GPU hotplug. None was executed on this host. Touchpad overview/workspace gestures remain GNOME behavior; launcher/notifications have keyboard and mouse alternatives.
