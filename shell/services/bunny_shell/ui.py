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
import sys
from typing import Any

from .core_state import read_snapshot, shell_status
from .launcher import LauncherState, application_search, route_intent
from .project import project_status
from .search import SearchIndex
from .search_state import SearchSnapshot, snapshot_for_query
from .settings import SECTIONS, SettingsStore
from .workspaces import WorkspaceStore


def _make_the_companion_importable() -> None:
    """Put the installed companion on the path, if it is not already there.

    Measured on a booted image, on screen: the Voice page read

        Voice settings are unavailable because Bunny Companion is not
        reachable: No module named 'companion'

    `/usr/bin/bunny-settings` adds `/usr/lib/bunny-shell` so that `bunny_shell`
    imports, and nothing adds `/usr/lib/bunny-os/python`, where `companion`
    lives. So the page could never reach the runtime on an installed system —
    the provider list, the readiness text and the engine selector were all
    unreachable behind one missing path, and the fallback message made it look
    like the *service* was down.

    Only when the import fails first. Prepending unconditionally would put the
    installed tree ahead of a developer's checkout and run the shipped
    companion against edited source, which this repository has paid for before.
    """
    try:
        import companion.protocol  # noqa: F401
        return
    except ImportError:
        pass
    installed = Path("/usr/lib/bunny-os/python")
    if installed.is_dir() and str(installed) not in sys.path:
        sys.path.insert(0, str(installed))


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
        # The status line is the named-state explanation: it says "Searching…",
        # "No results found for …", or the failure reason, so the panel is never
        # an unexplained strip. Its accessible description names the search
        # state so an assistive technology reads the panel's situation even
        # when focus is on the entry.
        status = self.Gtk.Label(xalign=0, wrap=True)
        status.add_css_class("dim-label")
        status.update_property([self.Gtk.AccessibleProperty.DESCRIPTION], ["Launcher search state"])
        launcher_state = LauncherState()
        # File results come from the pre-built metadata index only. The launcher
        # never adds a search location and never reads file contents: it calls
        # ``SearchIndex.query`` which reads the index that the privacy dashboard
        # and ``bunny-search rebuild`` already maintain under the approved-
        # location model. If no index exists or no location is approved, query
        # returns an empty list, so wiring it here adds no new authority.
        search_index = SearchIndex()

        def render(snapshot: SearchSnapshot) -> None:
            while child := results.get_first_child():
                results.remove(child)
            phase = snapshot.phase
            if phase == "ERROR":
                status.set_text(f"Search is unavailable: {snapshot.error}")
                results.append(self._state_row("Search failed. Type again to retry."))
                return
            if phase == "SEARCHING":
                status.set_text("Searching…")
                return
            if phase == "NO_QUERY":
                status.set_text("Type to search applications, approved files, and Bunny commands.")
                return
            if phase == "ZERO_RESULTS":
                status.set_text(f'No results found for "{snapshot.query}".')
            else:
                status.set_text("")
            # RESULTS and ZERO_RESULTS both show the intent row as the
            # ask-Bunny affordance; RESULTS additionally shows the matched
            # application and file rows.
            intent = snapshot.intent
            if intent is not None:
                intent_row = self.Gtk.ListBoxRow()
                intent_row.set_child(self._label(f"{intent.type.replace('_', ' ').title()}  ·  {intent.confidence:.0%}"))
                results.append(intent_row)
            state = launcher_state.get()
            for application in snapshot.applications:
                row = self.Gtk.ListBoxRow()
                row.desktop_id = application["desktop_id"]
                marker = "Pinned · " if application["desktop_id"] in state["pinned"] else "Recent · " if application["desktop_id"] in state["recent"] else "Application · "
                row.set_child(self._label(f"{marker}{application['name']}\n{application['comment']}"))
                results.append(row)
            for entry in snapshot.files:
                row = self.Gtk.ListBoxRow()
                # file_path is recorded for a future open-file action; the
                # current activate handler only launches desktop IDs, so file
                # rows are display-only by design and safe under the approved
                # launch-target rule.
                row.file_path = entry["path"]
                row.set_child(self._label(f"File · {entry['name']}\n{entry['relativePath']}"))
                results.append(row)

        def resolve(query: str) -> None:
            try:
                intent = route_intent(query)
                applications = application_search(query, 50)
                state = launcher_state.get()
                priority = {desktop_id: index for index, desktop_id in enumerate([*state["pinned"], *state["recent"]])}
                applications.sort(key=lambda item: (priority.get(item["desktop_id"], 1000), item["name"].casefold()))
                files = search_index.query(query, 5)
            except (OSError, PermissionError, ValueError) as exc:
                render(snapshot_for_query(query, intent=None, error=str(exc)))
                return
            render(snapshot_for_query(query, intent=intent, applications=applications[:12], files=files))

        def refresh(_entry: Any) -> None:
            query = search.get_text()
            # Render SEARCHING before the work so the indicator paints. The
            # resolve runs on idle so the toolkit gets a frame between the
            # pending snapshot and the results.
            render(snapshot_for_query(query, intent=None, pending=True))

            def _resolve() -> bool:
                resolve(query)
                return False  # run once, then stop
            self.GLib.idle_add(_resolve)

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
        box.append(status)
        scroller = self.Gtk.ScrolledWindow(vexpand=True)
        scroller.set_child(results)
        box.append(scroller)
        # Initial render: an empty query is NO_QUERY, not an unexplained list.
        # No intent is carried because the NO_QUERY panel shows a hint, not an
        # intent row; route_intent("") is not called until the user types.
        render(snapshot_for_query("", intent=None, pending=False))
        return box

    def _state_row(self, text: str) -> Any:
        row = self.Gtk.ListBoxRow()
        row.set_child(self._label(text))
        row.set_selectable(False)
        return row

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
            elif name == "Voice":
                self._voice_settings(detail)
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

    def _voice_settings(self, detail: Any) -> None:
        """The focused voice page, backed by the running companion service."""
        try:
            _make_the_companion_importable()
            from companion.protocol import CompanionClient, default_endpoint_path

            connection = CompanionClient(default_endpoint_path(), timeout=5.0)
            state = dict(connection.call("settings_voice_get", {}))
        except Exception as exc:  # noqa: BLE001 - settings remains a usable page
            detail.append(self._label(
                f"Voice settings are unavailable because Bunny Companion is not reachable: {exc}"))
            detail.append(self._label(
                "Typed input remains available. Start bunny-companion.service and reopen this page."))
            return

        detail.append(self._label(
            "Push-to-talk is explicit and bounded to 30 seconds. Audio and recognition run "
            "outside GNOME Shell, and no model is downloaded automatically."))

        def switch_row(label: str, active: bool) -> Any:
            row = self.Gtk.Box(orientation=self.Gtk.Orientation.HORIZONTAL, spacing=12)
            row.append(self._label(label))
            control = self.Gtk.Switch(active=active, hexpand=False)
            control.update_property([self.Gtk.AccessibleProperty.LABEL], [label])
            row.append(control)
            detail.append(row)
            return control

        def dropdown_row(label: str, labels: list[str], selected: int = 0) -> Any:
            row = self.Gtk.Box(orientation=self.Gtk.Orientation.HORIZONTAL, spacing=12)
            row.append(self._label(label))
            control = self.Gtk.DropDown.new_from_strings(labels)
            control.set_selected(max(0, min(selected, len(labels) - 1)))
            control.update_property([self.Gtk.AccessibleProperty.LABEL], [label])
            row.append(control)
            detail.append(row)
            return control

        voice_input = switch_row("Voice input", bool(state.get("voiceInput", True)))
        speech_responses = switch_row(
            "Speech responses", bool(state.get("speechResponses", True)))

        response_values = ["voice-only", "all", "never"]
        response_labels = ["Voice requests only", "All requests", "Never"]
        response_mode = str(state.get("responseMode") or "voice-only")
        response = dropdown_row(
            "Speak responses for", response_labels,
            response_values.index(response_mode) if response_mode in response_values else 0,
        )

        # Voice output is provider-neutral here. The companion supplies names,
        # readiness, model inventory and voices; this page never imports a
        # Pocket- or Kitten-specific API.
        provider_order = ["pocket", "kitten", "espeak-ng", "speech-dispatcher"]
        provider_fallback_names = {
            "pocket": "Pocket TTS", "kitten": "Kitten TTS",
            "espeak-ng": "eSpeak NG", "speech-dispatcher": "Speech Dispatcher",
        }
        discovered_providers = {
            str(item.get("providerId") or ""): item
            for item in state.get("ttsProviders", []) if isinstance(item, dict)
        }
        provider_values = list(provider_order)
        provider_labels: list[str] = []
        for provider_id in provider_values:
            item = discovered_providers.get(provider_id, {})
            name = str(item.get("displayName") or provider_fallback_names[provider_id])
            provider_status = str(item.get("status") or "NOT_INSTALLED")
            label_status = "Ready" if bool(item.get("ready")) else provider_status.replace("_", " ").title()
            provider_labels.append(f"{name} — {label_status}")
        selected_provider = str(state.get("ttsProviderId") or "pocket")
        engine = dropdown_row(
            "Engine", provider_labels,
            provider_values.index(selected_provider) if selected_provider in provider_values else 0,
        )

        performance_values = ["automatic", "quality", "low-resource"]
        performance_name = str(state.get("performanceMode") or "automatic")
        performance = dropdown_row(
            "Voice performance mode", ["Automatic", "Quality", "Low Resource"],
            performance_values.index(performance_name) if performance_name in performance_values else 0,
        )

        voices = [item for item in state.get("ttsVoices", []) if isinstance(item, dict)]
        selected_tts_voice = str(state.get("ttsVoiceId") or "")
        selected_tts_model = str(state.get("ttsModelId") or "")
        voice_values: list[str] = [""]
        tts_model_values: list[str] = [""]
        voice_row = self.Gtk.Box(orientation=self.Gtk.Orientation.HORIZONTAL, spacing=12)
        voice_row.append(self._label("Voice"))
        voice = self.Gtk.DropDown.new_from_strings(["Provider default"])
        voice_row.append(voice)
        detail.append(voice_row)
        model_row = self.Gtk.Box(orientation=self.Gtk.Orientation.HORIZONTAL, spacing=12)
        model_row.append(self._label("Model"))
        tts_model = self.Gtk.DropDown.new_from_strings(["Provider default"])
        model_row.append(tts_model)
        detail.append(model_row)

        rate_row = self.Gtk.Box(orientation=self.Gtk.Orientation.HORIZONTAL, spacing=12)
        rate_row.append(self._label("Speech speed"))
        rate = self.Gtk.Scale.new_with_range(
            self.Gtk.Orientation.HORIZONTAL, 0.5, 2.0, 0.05)
        rate.set_value(float(state.get("speakingRate") or 1.0))
        rate.set_hexpand(True)
        rate.update_property([self.Gtk.AccessibleProperty.LABEL], ["Speech speed"])
        rate_row.append(rate)
        detail.append(rate_row)
        provider_readiness = self._label("")
        detail.append(provider_readiness)

        def refresh_voice_output(_control: Any = None, _property: Any = None) -> None:
            nonlocal voice_values, tts_model_values
            provider_id = provider_values[engine.get_selected()]
            item = discovered_providers.get(provider_id, {})
            provider_voices = [
                entry for entry in voices if str(entry.get("providerId") or "") == provider_id
            ]
            voice_values = [""] + [str(entry.get("voiceId") or "") for entry in provider_voices]
            voice_labels = ["Provider default"] + [
                str(entry.get("name") or entry.get("voiceId") or "Voice") for entry in provider_voices
            ]
            voice.set_model(self.Gtk.StringList.new(voice_labels))
            voice.set_selected(
                voice_values.index(selected_tts_voice)
                if provider_id == selected_provider and selected_tts_voice in voice_values else 0)

            model_reports = [
                entry for entry in item.get("modelHealth", []) if isinstance(entry, dict)
            ]
            declared_models = [str(value) for value in item.get("models", []) if str(value)]
            tts_model_values = [""] + declared_models
            status_by_model = {
                str(entry.get("modelId") or ""): entry for entry in model_reports
            }
            model_labels = ["Provider default"] + [
                f"{value} — {'Installed' if status_by_model.get(value, {}).get('installed') else 'Not Installed'}"
                for value in declared_models
            ]
            tts_model.set_model(self.Gtk.StringList.new(model_labels))
            tts_model.set_selected(
                tts_model_values.index(selected_tts_model)
                if provider_id == selected_provider and selected_tts_model in tts_model_values else 0)
            model_row.set_visible(provider_id == "kitten")
            # Pocket 2.1 does not expose speech-rate control. Do not present a
            # slider that its provider would silently ignore.
            rate_row.set_visible(provider_id != "pocket")
            detail_text = str(item.get("detail") or "This engine is not installed.")
            provider_readiness.set_text(detail_text)

        engine.connect("notify::selected", refresh_voice_output)
        refresh_voice_output()
        fallback_warning = str(state.get("ttsFallbackWarning") or "")
        if fallback_warning:
            detail.append(self._label(f"Last voice fallback: {fallback_warning}"))

        devices = [item for item in state.get("devices", []) if isinstance(item, dict)]
        device_values = [""] + [str(item.get("deviceId") or "") for item in devices]
        device_labels = ["System default"] + [
            str(item.get("description") or item.get("name") or item.get("deviceId") or "Microphone")
            for item in devices
        ]
        selected_device = str(state.get("deviceId") or "")
        device = dropdown_row(
            "Microphone", device_labels,
            device_values.index(selected_device) if selected_device in device_values else 0,
        )

        recognizers = [item for item in state.get("recognizers", []) if isinstance(item, dict)]
        discovered_models: list[str] = []
        for item in recognizers:
            origin = str(item.get("modelOrigin") or "")
            if origin:
                discovered_models.append(Path(origin).name)
        recognition_model_values = [""] + list(dict.fromkeys(discovered_models))
        model_labels = ["Automatic (smallest installed)"] + list(dict.fromkeys(discovered_models))
        selected_model = str(state.get("modelId") or "")
        if selected_model and selected_model not in recognition_model_values:
            recognition_model_values.append(selected_model)
            model_labels.append(f"{selected_model} (not installed)")
        model = dropdown_row(
            "Speech recognition model", model_labels,
            recognition_model_values.index(selected_model)
            if selected_model in recognition_model_values else 0,
        )
        if not discovered_models:
            readiness = state.get("readiness", {})
            message = (
                str(readiness.get("message") or "")
                if isinstance(readiness, dict) else ""
            )
            detail.append(self._label(
                message or "Voice recognition isn't installed yet. Bunny OS can be repaired "
                "without enabling a cloud speech service."))

        language_values = ["automatic", "en"]
        language_name = str(state.get("language") or "automatic")
        language = dropdown_row(
            "Language", ["Automatic", "English"],
            language_values.index(language_name) if language_name in language_values else 0,
        )
        detail.append(self._label(
            f"Push-to-talk shortcut: {state.get('shortcut') or '<Super><Alt>Space'}"))
        detail.append(self._label("Wake word: Disabled (not available in this milestone)"))

        status = self._label("")
        detail.append(status)

        def save(_button: Any) -> None:
            try:
                answer = connection.call("settings_voice_set", {
                    "voiceInput": voice_input.get_active(),
                    "speechResponses": speech_responses.get_active(),
                    "responseMode": response_values[response.get_selected()],
                    "deviceId": device_values[device.get_selected()],
                    "modelId": recognition_model_values[model.get_selected()],
                    "language": language_values[language.get_selected()],
                    "shortcut": str(state.get("shortcut") or "<Super><Alt>space"),
                    "wakeWord": "disabled",
                    "ttsProviderId": provider_values[engine.get_selected()],
                    "ttsModelId": tts_model_values[tts_model.get_selected()],
                    "ttsVoiceId": voice_values[voice.get_selected()],
                    "speakingRate": rate.get_value(),
                    "performanceMode": performance_values[performance.get_selected()],
                })
                status.set_text(
                    "Saved. Restart Bunny Companion to change the loaded model."
                    if answer.get("restartRequired") else "Saved and applied.")
            except Exception as exc:  # noqa: BLE001 - keep the editor open
                status.set_text(f"Voice settings were not saved: {exc}")

        detail.append(self._button("Save voice settings", save))

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
        box.append(self._button("Voice and AI", lambda _b: _fixed_spawn(["/usr/bin/bunny-settings", "--section", "Voice & AI"])))
        box.append(self._button("Pause or inspect Bunny tasks", lambda _b: _fixed_spawn(["/usr/bin/bunny-tasks"])))
        return box

    def run(self) -> int:
        return int(self.app.run(None))


def run_surface(surface: str, section: str | None = None) -> int:
    return BunnyApplication(surface, section).run()
