# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""GTK4 task-rail window for Hyprland Focus/Studio layouts.

Widgets only. Behaviour and Companion I/O live in ``TaskRailRuntime``.
Absolute Wayland placement is not claimed; Hyprland may float the window via
app_id ``bunny-task-rail``.
"""

from __future__ import annotations

from typing import Any

from .task_rail_runtime import TaskRailRuntime


def build_accessible_tree(model: dict[str, Any]) -> list[dict[str, str]]:
    """Deterministic accessible tree for host tests (no GTK required)."""
    accessible = dict(model.get("accessible") or {})
    rail = dict(model.get("rail") or {})
    nodes = [
        {"role": "window", "name": accessible.get("windowName", "")},
        {"role": "status", "name": accessible.get("statusName", ""), "value": str(rail.get("label") or "")},
        {"role": "list", "name": accessible.get("stagesName", "")},
    ]
    for action in rail.get("actions") or []:
        if not isinstance(action, dict):
            continue
        action_id = str(action.get("id") or "")
        label_key = {
            "open-trust": "openTrust",
            "pause": "pause",
            "cancel": "cancel",
        }.get(action_id)
        name = accessible.get(label_key or "", "") or str(action.get("label") or "")
        nodes.append({"role": "button", "name": name, "actionId": action_id})
    if model.get("collapsed"):
        nodes.append({"role": "button", "name": accessible.get("expand", "")})
    else:
        nodes.append({"role": "button", "name": accessible.get("collapse", "")})
    nodes.append({"role": "button", "name": accessible.get("desktopHint", "")})
    return nodes


def run_task_rail_window(runtime: TaskRailRuntime) -> int:  # pragma: no cover - needs display
    """Open the Focus/Studio task rail. Returns process exit code."""
    try:
        import gi

        gi.require_version("Gtk", "4.0")
        from gi.repository import GLib, Gtk  # type: ignore
    except Exception as exc:  # noqa: BLE001
        print(f"bunny-task-rail: GTK unavailable ({exc})", flush=True)
        return 2

    runtime.connect()
    model = runtime.surface_model()
    if not model["visible"]:
        print(
            "bunny-task-rail: layout is Desktop — rail hidden. "
            "Switch to Focus/Studio with bunny-adaptive-layout.",
            flush=True,
        )
        return 0

    app = Gtk.Application(application_id="bunny-task-rail")

    def on_activate(application: Any) -> None:
        window = Gtk.ApplicationWindow(application=application, title="Bunny task timeline")
        window.set_default_size(360, 640)
        window.set_can_focus(True)
        try:
            window.update_property(
                [Gtk.AccessibleProperty.LABEL],
                [model["accessible"]["windowName"]],
            )
        except Exception:  # noqa: BLE001
            pass

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        root.set_margin_top(12)
        root.set_margin_bottom(12)
        root.set_margin_start(12)
        root.set_margin_end(12)

        status = Gtk.Label(label=str(model["rail"].get("label") or "Ready"), xalign=0)
        status.set_wrap(True)
        try:
            status.update_property(
                [Gtk.AccessibleProperty.LABEL],
                [model["accessible"]["statusName"]],
            )
        except Exception:  # noqa: BLE001
            pass
        root.append(status)

        caption = Gtk.Label(label=str(model["rail"].get("caption") or ""), xalign=0)
        caption.set_wrap(True)
        root.append(caption)

        stages = Gtk.ListBox()
        try:
            stages.update_property(
                [Gtk.AccessibleProperty.LABEL],
                [model["accessible"]["stagesName"]],
            )
        except Exception:  # noqa: BLE001
            pass
        for stage in model["rail"].get("stages") or []:
            row = Gtk.Label(
                label=f"{stage.get('glyph', 'pending')}: {stage.get('name', '')}",
                xalign=0,
            )
            stages.append(row)
        root.append(stages)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        def add_button(label: str, accessible: str, callback: Any) -> None:
            button = Gtk.Button(label=label)
            try:
                button.update_property([Gtk.AccessibleProperty.LABEL], [accessible])
            except Exception:  # noqa: BLE001
                pass
            button.connect("clicked", callback)
            actions.append(button)

        def hide_to_desktop(_button: Any = None) -> None:
            runtime.set_layout("desktop")
            window.close()

        def toggle_collapse(_button: Any = None) -> None:
            runtime.collapsed = not runtime.collapsed
            runtime.refresh()
            window.close()
            # Caller may relaunch; keep process simple for M1R.

        if model["rail"].get("approval"):
            add_button(
                "Open Trust",
                model["accessible"]["openTrust"],
                lambda *_: GLib.spawn_command_line_async("bunny-approvals"),
            )
        add_button("Pause", model["accessible"]["pause"], lambda *_: None)
        add_button("Cancel", model["accessible"]["cancel"], lambda *_: None)
        add_button(
            "Collapse" if not model["collapsed"] else "Expand",
            model["accessible"]["collapse"] if not model["collapsed"] else model["accessible"]["expand"],
            toggle_collapse,
        )
        add_button("Desktop", model["accessible"]["desktopHint"], hide_to_desktop)
        root.append(actions)

        if model.get("connectionError"):
            err = Gtk.Label(label=f"Disconnected: {model['connectionError']}", xalign=0)
            root.append(err)

        # Focus protection: only accept focus when Trust/approval needs it.
        if not model.get("acceptFocus"):
            try:
                window.set_focusable(False)
            except Exception:  # noqa: BLE001
                pass

        key = Gtk.EventControllerKey()

        def on_key(_controller: Any, keyval: int, _keycode: int, _state: int) -> bool:
            from gi.repository import Gdk  # type: ignore

            if keyval == Gdk.KEY_Escape:
                runtime.collapsed = True
                window.close()
                return True
            if keyval in (Gdk.KEY_h, Gdk.KEY_H):
                hide_to_desktop()
                return True
            return False

        key.connect("key-pressed", on_key)
        window.add_controller(key)

        window.set_child(root)
        window.present()

        def poll() -> bool:
            runtime.refresh()
            latest = runtime.surface_model()
            status.set_text(str(latest["rail"].get("label") or "Ready"))
            caption.set_text(str(latest["rail"].get("caption") or ""))
            if not latest["visible"]:
                window.close()
                return False
            return True

        GLib.timeout_add_seconds(2, poll)

    app.connect("activate", on_activate)
    return int(app.run(None) or 0)
