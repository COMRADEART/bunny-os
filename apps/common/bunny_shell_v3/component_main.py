"""Shared entry point for every Bunny shell component.

BUNNY WAYLAND SHELL EXPERIMENT — NOT RELEASE QUALIFIED — DO NOT USE AS THE
DEFAULT SESSION.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

from . import NOTICE_LINES
from .chrome import DockItem, DockModel
from .model import LayoutMode, ShellState, VisualMode
from .notifications import NotificationCenter
from .palette import CommandPalette, default_results
from .quicksettings import QuickSettings
from .runtime import COMPONENTS, spec


#: gtk4-layer-shell must be loaded before libwayland-client, otherwise GTK
#: creates an ordinary xdg-toplevel and the layer-surface calls silently do
#: nothing. Under PyGObject the library is loaded through the typelib, which is
#: always after libwayland, so the only fix is LD_PRELOAD — and LD_PRELOAD has
#: to be set before the process starts. The component therefore re-executes
#: itself once with the variable set.
#: See https://github.com/wmww/gtk4-layer-shell/blob/main/linking.md
_PRELOAD_GUARD = "BUNNY_SHELL_LAYER_SHELL_PRELOADED"


def layer_shell_library() -> str | None:
    from ctypes.util import find_library

    found = find_library("gtk4-layer-shell")
    if found and Path(found).is_absolute():
        return found
    for directory in ("/usr/lib64", "/usr/lib", "/usr/lib/x86_64-linux-gnu"):
        for name in ("libgtk4-layer-shell.so.0", "libgtk4-layer-shell.so"):
            candidate = Path(directory) / name
            if candidate.exists():
                return str(candidate)
    return None


def ensure_layer_shell_preloaded() -> None:
    """Re-execute with LD_PRELOAD set, once, if the library needs it."""

    if os.environ.get(_PRELOAD_GUARD) == "1" or sys.platform != "linux":
        return
    library = layer_shell_library()
    if not library:
        return
    environment = dict(os.environ)
    environment[_PRELOAD_GUARD] = "1"
    existing = environment.get("LD_PRELOAD", "")
    environment["LD_PRELOAD"] = f"{library}:{existing}" if existing else library
    os.execve(sys.executable, [sys.executable, *sys.argv], environment)


def state_from_environment() -> ShellState:
    state = ShellState()
    mode = os.environ.get("BUNNY_SHELL_MODE")
    if mode in (VisualMode.REGULAR.value, VisualMode.CHARACTER.value):
        state.visual_mode = VisualMode(mode)
    if os.environ.get("BUNNY_SHELL_LAYOUT") == "compact":
        state.layout_mode = LayoutMode.COMPACT
    state.reduced_motion = os.environ.get("BUNNY_SHELL_REDUCED_MOTION") == "1"
    state.high_contrast = os.environ.get("BUNNY_SHELL_HIGH_CONTRAST") == "1"
    state.focus_mode = os.environ.get("BUNNY_SHELL_FOCUS_MODE") == "1"
    state.bunny_enabled = os.environ.get("BUNNY_SHELL_BUNNY_ENABLED", "1") == "1"
    state.local_only = os.environ.get("BUNNY_SHELL_LOCAL_ONLY") == "1"
    return state


def describe(component: str) -> dict:
    """Machine-readable description, used by the tests and the harnesses."""

    definition = spec(component)
    return {
        "schemaVersion": 1,
        "notice": list(NOTICE_LINES),
        "component": definition.name,
        "namespace": definition.namespace,
        "layer": definition.layer.value,
        "anchors": [edge.value for edge in definition.anchors],
        "keyboard": definition.keyboard.value,
        "exclusiveZone": definition.exclusive_zone,
        "characterPermitted": definition.character_permitted,
        "authenticationSurface": definition.authentication_surface,
    }


def build_child(component: str, state: ShellState):
    from . import views

    if component == "top-bar":
        return views.build_top_bar(state)
    if component == "dock":
        model = DockModel(state)
        for entry_id, name in _dock_entries():
            model.add(DockItem(entry_id=entry_id, name=name, pinned=True))
        return views.build_dock(state, model)
    if component in ("command-palette", "launcher"):
        palette = CommandPalette(bunny_enabled=state.bunny_enabled)
        for result in default_results():
            palette.register(result)
        return views.build_command_palette(palette)
    if component == "quick-settings":
        return views.build_quick_settings(QuickSettings(state))
    if component == "notification-center":
        return views.build_notification_center(NotificationCenter())
    if component == "overview":
        return views.build_notification_center(NotificationCenter())
    raise KeyError(f"no view registered for component {component}")


def _dock_entries() -> list[tuple[str, str]]:
    """Pinned entries, read from the trusted desktop-entry directories.

    Never constructed from a name: an entry that is not a real desktop file is
    not shown, because a dock item that cannot be resolved to an entry cannot be
    launched safely.
    """

    entries: list[tuple[str, str]] = []
    for directory in (
        Path("/usr/share/applications"),
        Path.home() / ".local/share/applications",
    ):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.desktop"))[:8]:
            name = path.stem
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("Name="):
                    name = line.partition("=")[2].strip()
                    break
            entries.append((path.stem, name))
        if entries:
            break
    return entries


def main(component: str, argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    for line in NOTICE_LINES:
        print(line, file=sys.stderr)

    if component not in COMPONENTS:
        print(f"unknown component {component}", file=sys.stderr)
        return 2

    if "--describe" in argv:
        print(json.dumps(describe(component), indent=2, sort_keys=True))
        return 0

    if os.environ.get("BUNNY_SHELL_EXPERIMENTAL") != "1":
        print(
            f"bunny-{component}: refusing to start: set BUNNY_SHELL_EXPERIMENTAL=1",
            file=sys.stderr,
        )
        return 2

    if not os.environ.get("WAYLAND_DISPLAY"):
        print(f"bunny-{component}: requires a Wayland session", file=sys.stderr)
        return 2

    ensure_layer_shell_preloaded()

    try:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Gtk4LayerShell", "1.0")
        from gi.repository import Gtk
    except (ImportError, ValueError) as error:
        print(f"bunny-{component}: GTK 4 and gtk4-layer-shell are required: {error}", file=sys.stderr)
        return 2

    from . import views

    state = state_from_environment()
    application = Gtk.Application(application_id=f"org.bunnyos.shell.v3.{component.replace('-', '')}")

    def activate(app):
        views.install_style()
        views.present(component, build_child(component, state), application=app)

    application.connect("activate", activate)
    return application.run([])
