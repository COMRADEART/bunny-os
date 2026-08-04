# SPDX-License-Identifier: GPL-3.0-or-later
"""GTK4 presentation layer for Bunny-owned desktop surfaces.

All launch targets are fixed or validated desktop IDs.  The UI intentionally
does not expose a generic command backend.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from typing import Any

from .core_state import read_snapshot, shell_status
from .launcher import LauncherState, application_search, route_intent
from .project import project_status
from .search import SearchIndex
from .settings import SECTIONS, SettingsStore
from .workspaces import WorkspaceStore


GNOME_PANELS = {
    "Network": "network", "Bluetooth": "bluetooth", "Displays": "display", "Sound": "sound",
    "Power": "power", "Keyboard": "keyboard", "Mouse and Touchpad": "mouse", "Appearance": "background",
    "Applications": "applications", "Notifications": "notifications", "Privacy": "privacy", "Users": "user-accounts",
    "Date and Time": "datetime", "Storage": "info-overview", "Accessibility": "universal-access",
    "System Information": "info-overview",
}


def _gtk() -> tuple[Any, Any, Any]:
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        from gi.repository import Gio, GLib, Gtk
    except (ImportError, ValueError) as exc:
        raise RuntimeError("GTK4/PyGObject is required for Bunny Shell graphical surfaces") from exc
    return Gio, GLib, Gtk


def _fixed_spawn(argv: list[str]) -> None:
    allowed = {
        "/usr/bin/gnome-control-center", "/usr/bin/nautilus", "/usr/bin/gnome-terminal",
        "/usr/bin/bunny-launcher", "/usr/bin/bunny-settings", "/usr/bin/bunny-workspace",
        "/usr/bin/bunny-approvals", "/usr/bin/bunny-tasks", "/usr/bin/bunny-plans",
        "/usr/bin/bunny-terminal", "/usr/bin/bunny-os", "/usr/bin/bunny-companion",
    }
    if not argv or argv[0] not in allowed:
        raise ValueError("unapproved desktop launch target")
    subprocess.Popen(argv, close_fds=True, start_new_session=True)


def launch_terminal() -> int:
    _fixed_spawn(["/usr/bin/gnome-terminal"])
    return 0


class BunnyApplication:
    def __init__(self, surface: str, section: str | None = None) -> None:
        Gio, GLib, Gtk = _gtk()
        self.Gio, self.GLib, self.Gtk = Gio, GLib, Gtk
        self.surface = surface
        self.section = section
        self.app = Gtk.Application(application_id=f"art.comrade.BunnyShell.{surface.title().replace('-', '')}")
        self.app.connect("activate", self._activate)

    def _label(self, text: str, css: str | None = None) -> Any:
        label = self.Gtk.Label(label=text, xalign=0, wrap=True, selectable=False)
        if css:
            label.add_css_class(css)
        return label

    def _button(self, label: str, callback: Any) -> Any:
        button = self.Gtk.Button(label=label)
        button.update_property([self.Gtk.AccessibleProperty.LABEL], [label])
        button.connect("clicked", callback)
        return button

    def _activate(self, app: Any) -> None:
        window = self.Gtk.ApplicationWindow(application=app, title=f"Bunny {self.surface.title()}")
        window.set_default_size(980, 680)
        header = self.Gtk.HeaderBar()
        header.set_title_widget(self._label("Bunny OS", "title-3"))
        window.set_titlebar(header)
        root = self.Gtk.Box(orientation=self.Gtk.Orientation.VERTICAL, spacing=16)
        root.set_margin_top(20); root.set_margin_bottom(20); root.set_margin_start(24); root.set_margin_end(24)
        builders = {
            "launcher": self._launcher,
            "settings": self._settings,
            "workspaces": self._workspaces,
            "approvals": lambda: self._core_list("approvals", "Approval centre"),
            "tasks": lambda: self._core_list("tasks", "Task activity"),
            "plans": lambda: self._core_list("plans", "Plans"),
            "project": self._project,
            "privacy": self._privacy,
            "notifications": lambda: self._core_list("notifications", "Notification centre"),
            "quick-settings": self._quick_settings,
            "command": self._command,
        }
        content = builders.get(self.surface, self._command)()
        root.append(content)
        window.set_child(root)
        window.present()

    def _launcher(self) -> Any:
        box = self.Gtk.Box(orientation=self.Gtk.Orientation.VERTICAL, spacing=12)
        box.append(self._label("Launcher", "title-1"))
        box.append(self._label("Applications, approved files, workspaces, settings, tasks, plans, and Bunny commands"))
        search = self.Gtk.SearchEntry(placeholder_text="Search or ask Bunny…")
        search.update_property([self.Gtk.AccessibleProperty.DESCRIPTION], ["Search Bunny OS launcher domains"])
        results = self.Gtk.ListBox(selection_mode=self.Gtk.SelectionMode.SINGLE)
        launcher_state = LauncherState()

        def refresh(_entry: Any) -> None:
            while child := results.get_first_child():
                results.remove(child)
            query = search.get_text()
            intent = route_intent(query)
            intent_row = self.Gtk.ListBoxRow()
            intent_row.set_child(self._label(f"{intent.type.replace('_', ' ').title()}  ·  {intent.confidence:.0%}"))
            results.append(intent_row)
            applications = application_search(query, 50)
            state = launcher_state.get()
            priority = {desktop_id: index for index, desktop_id in enumerate([*state["pinned"], *state["recent"]])}
            applications.sort(key=lambda item: (priority.get(item["desktop_id"], 1000), item["name"].casefold()))
            for application in applications[:12]:
                row = self.Gtk.ListBoxRow()
                row.desktop_id = application["desktop_id"]
                marker = "Pinned · " if application["desktop_id"] in state["pinned"] else "Recent · " if application["desktop_id"] in state["recent"] else "Application · "
                row.set_child(self._label(f"{marker}{application['name']}\n{application['comment']}"))
                results.append(row)

        def activate(_list: Any, row: Any) -> None:
            desktop_id = getattr(row, "desktop_id", None)
            if desktop_id:
                info = self.Gio.DesktopAppInfo.new(desktop_id)
                if info:
                    info.launch([], None)
                    launcher_state.record_launch(desktop_id)

        search.connect("search-changed", refresh)
        results.connect("row-activated", activate)
        box.append(search)
        scroller = self.Gtk.ScrolledWindow(vexpand=True)
        scroller.set_child(results)
        box.append(scroller)
        refresh(search)
        return box

    def _settings(self) -> Any:
        split = self.Gtk.Paned(orientation=self.Gtk.Orientation.HORIZONTAL, wide_handle=True)
        navigation = self.Gtk.ListBox(selection_mode=self.Gtk.SelectionMode.SINGLE)
        detail = self.Gtk.Box(orientation=self.Gtk.Orientation.VERTICAL, spacing=12)
        detail.set_margin_start(24)
        settings = SettingsStore().get_all()

        def select(_list: Any, row: Any) -> None:
            while child := detail.get_first_child():
                detail.remove(child)
            name = row.section_name
            detail.append(self._label(name, "title-1"))
            if name in GNOME_PANELS:
                detail.append(self._label("This stable system section is provided by GNOME Settings."))
                detail.append(self._button("Open GNOME Settings", lambda _b: _fixed_spawn(["/usr/bin/gnome-control-center", GNOME_PANELS[name]])))
                if name == "Appearance":
                    detail.append(self._label(f"Bunny surface theme: {settings['theme']} · Reduced motion: {settings['reducedMotion']} · Reduced transparency: {settings['reducedTransparency']}"))
            elif name == "Updates":
                detail.append(self._label("OS image updates remain separate from Bunny application updates and require broker authorization."))
                detail.append(self._button("Inspect OS update status", lambda _b: _fixed_spawn(["/usr/bin/gnome-terminal", "--", "/usr/bin/bunny-os", "update", "status"])))
            elif name == "Recovery":
                detail.append(self._label("Recovery, previous deployments, safe graphics, and diagnostics remain available without Bunny Core."))
                detail.append(self._button("Inspect recovery status", lambda _b: _fixed_spawn(["/usr/bin/gnome-terminal", "--", "/usr/bin/bunny-os", "recovery", "status"])))
            else:
                for key, value in settings.items():
                    if isinstance(value, bool):
                        row_box = self.Gtk.Box(orientation=self.Gtk.Orientation.HORIZONTAL, spacing=12)
                        row_box.append(self._label(key))
                        toggle = self.Gtk.Switch(active=value, hexpand=False)
                        toggle.update_property([self.Gtk.AccessibleProperty.LABEL], [key])
                        toggle.connect("notify::active", lambda control, _property, setting=key: SettingsStore().set(setting, control.get_active()))
                        row_box.append(toggle)
                        detail.append(row_box)
                    else:
                        detail.append(self._label(f"{key}: {json.dumps(value)}"))
        selected_row = None
        for section in SECTIONS:
            row = self.Gtk.ListBoxRow()
            row.section_name = section
            row.set_child(self._label(section))
            navigation.append(row)
            if section.casefold() == (self.section or "Bunny").replace("bunny-", "").casefold():
                selected_row = row
        navigation.connect("row-selected", select)
        split.set_start_child(navigation)
        split.set_end_child(detail)
        navigation.select_row(selected_row or navigation.get_row_at_index(0))
        return split

    def _workspaces(self) -> Any:
        box = self.Gtk.Box(orientation=self.Gtk.Orientation.VERTICAL, spacing=12)
        box.append(self._label("Workspaces", "title-1"))
        box.append(self._label("Removing workspace metadata never deletes project files."))
        for workspace in WorkspaceStore().list(include_archived=True):
            state = "Archived" if workspace.get("archivedAt") else "Active"
            project = workspace.get("projectPath", "No project attached")
            box.append(self._label(f"{workspace['name']} · {state}\n{project}"))
        if not WorkspaceStore().list(include_archived=True):
            box.append(self._label("No workspaces yet. Create one with bunny-workspace create NAME."))
        return box

    def _core_list(self, key: str, title: str) -> Any:
        box = self.Gtk.Box(orientation=self.Gtk.Orientation.VERTICAL, spacing=12)
        box.append(self._label(title, "title-1"))
        try:
            snapshot = read_snapshot()
        except (OSError, PermissionError, ValueError, json.JSONDecodeError):
            snapshot = None
        if not snapshot:
            box.append(self._label("Bunny Core is unavailable. Conventional desktop functions remain available."))
            return box
        items = snapshot[key]
        if not items:
            box.append(self._label(f"No {key}."))
        for item in items:
            visible = item.get("title") or item.get("action") or item.get("objective") or item.get("id")
            box.append(self._label(str(visible)))
        if key == "approvals":
            box.append(self._label("Approval decisions are sent to Bunny Core. This shell cache cannot grant permissions."))
        return box

    def _command(self) -> Any:
        box = self.Gtk.Box(orientation=self.Gtk.Orientation.VERTICAL, spacing=12)
        box.append(self._label("Bunny command surface", "title-1"))
        status = shell_status()
        box.append(self._label(f"Bunny: {status['bunny']} · Broker: {status['broker']} · Security evidence: {status['securitySummary']}"))
        mode = self.Gtk.DropDown.new_from_strings(["Ask", "Command", "Plan", "Explain", "System"])
        prompt = self.Gtk.Entry(placeholder_text="What would you like to do?")
        box.append(mode); box.append(prompt)
        box.append(self._label("Only user-visible plans, action summaries, permissions, outputs, and errors appear here. Hidden reasoning is never exposed."))
        return box

    def _project(self) -> Any:
        box = self.Gtk.Box(orientation=self.Gtk.Orientation.VERTICAL, spacing=12)
        box.append(self._label("Project dashboard", "title-1"))
        active = [item for item in WorkspaceStore().list() if item.get("projectPath")]
        if not active:
            box.append(self._label("Attach a project directory to a workspace to inspect it. Project scripts are never run on open."))
            return box
        for workspace in active:
            try:
                status = project_status(workspace["projectPath"])
                box.append(self._label(f"{workspace['name']}\n{status['projectRoot']}\nBranch: {status['branch']} · Changed: {status['changedFileCount']}"))
            except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
                box.append(self._label(f"{workspace['name']}\n{workspace['projectPath']}\nGit status unavailable: {exc}"))
        return box

    def _privacy(self) -> Any:
        box = self.Gtk.Box(orientation=self.Gtk.Orientation.VERTICAL, spacing=12)
        box.append(self._label("Privacy dashboard", "title-1"))
        settings = SettingsStore().get_all()
        search = SearchIndex().status()
        status = shell_status()
        for label, value in (
            ("Bunny", status["bunny"]), ("Local-only AI", settings["localOnlyMode"]),
            ("Offline", settings["offlineMode"]), ("Telemetry", "Enabled" if settings["telemetryEnabled"] else "Disabled"),
            ("Clipboard history", settings["clipboardHistory"]), ("Approved search locations", search["approvedLocationCount"]),
            ("Broker", status["broker"]), ("Security evidence", status["securitySummary"]),
        ):
            box.append(self._label(f"{label}: {value}"))
        box.append(self._button("Open GNOME device privacy", lambda _b: _fixed_spawn(["/usr/bin/gnome-control-center", "privacy"])))
        return box

    def _quick_settings(self) -> Any:
        box = self.Gtk.Box(orientation=self.Gtk.Orientation.VERTICAL, spacing=12)
        box.append(self._label("Quick settings", "title-1"))
        box.append(self._label("GNOME remains authoritative for devices. Bunny modes use typed user settings."))
        for label, panel in (("Wi-Fi", "wifi"), ("Bluetooth", "bluetooth"), ("Audio and microphone", "sound"), ("Displays and brightness", "display"), ("Power", "power"), ("Accessibility", "universal-access")):
            box.append(self._button(label, lambda _b, value=panel: _fixed_spawn(["/usr/bin/gnome-control-center", value])))
        box.append(self._button("Local-only, offline, updates, and privacy", lambda _b: _fixed_spawn(["/usr/bin/bunny-settings", "--section", "Bunny"])))
        box.append(self._button("Pause or inspect Bunny tasks", lambda _b: _fixed_spawn(["/usr/bin/bunny-tasks"])))
        return box

    def run(self) -> int:
        return int(self.app.run(None))


def run_surface(surface: str, section: str | None = None) -> int:
    return BunnyApplication(surface, section).run()
