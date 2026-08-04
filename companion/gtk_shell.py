# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Restartable GTK4 companion, task panel, captions, and Approval Centre."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .model import CompanionPhase, Placement
from .presentation import DesktopContext, MonitorGeometry, WindowPreferences, window_directive
from .protocol import CompanionClient, CompanionClientError


def _asset_path() -> Path:
    installed = Path("/usr/share/bunny-shell/companion/default-bunny.svg")
    if installed.is_file():
        return installed
    return Path(__file__).resolve().parents[1] / "shell/assets/companion/default-bunny.svg"


@dataclass
class CompanionViewModel:
    client: CompanionClient
    active_task_id: str | None = None
    snapshot: Mapping[str, Any] | None = None
    connection_error: str | None = None

    def connect(self) -> None:
        self.client.health()
        tasks = self.client.call("tasks").get("tasks", [])
        if self.active_task_id is None and isinstance(tasks, list) and tasks:
            active = [item for item in tasks if isinstance(item, Mapping) and item.get("currentPhase") not in {"completed", "failed", "cancelled"}]
            selected = (active or tasks)[-1]
            if isinstance(selected, Mapping):
                self.active_task_id = str(selected.get("taskId"))
        self.refresh()

    def submit(self, request: str) -> Mapping[str, Any]:
        self.snapshot = self.client.submit(request)
        task = self.snapshot.get("task") if isinstance(self.snapshot, Mapping) else None
        if isinstance(task, Mapping):
            self.active_task_id = str(task.get("taskId"))
        self.connection_error = None
        return self.snapshot

    def refresh(self) -> Mapping[str, Any] | None:
        if self.active_task_id is None:
            self.snapshot = None
            return None
        try:
            self.snapshot = self.client.snapshot(self.active_task_id)
            self.connection_error = None
        except (CompanionClientError, OSError) as exc:
            self.connection_error = str(exc)
        return self.snapshot

    @property
    def state(self) -> Mapping[str, Any]:
        value = self.snapshot.get("state") if isinstance(self.snapshot, Mapping) else None
        return value if isinstance(value, Mapping) else {}

    @property
    def task(self) -> Mapping[str, Any]:
        value = self.snapshot.get("task") if isinstance(self.snapshot, Mapping) else None
        return value if isinstance(value, Mapping) else {}

    @property
    def approvals(self) -> list[Mapping[str, Any]]:
        values = self.snapshot.get("approvals") if isinstance(self.snapshot, Mapping) else None
        return [item for item in values if isinstance(item, Mapping)] if isinstance(values, list) else []

    @property
    def events(self) -> list[Mapping[str, Any]]:
        values = self.snapshot.get("events") if isinstance(self.snapshot, Mapping) else None
        return [item for item in values if isinstance(item, Mapping)] if isinstance(values, list) else []

    @property
    def reviewer_observations(self) -> list[Mapping[str, Any]]:
        return [
            event.get("payload", {})
            for event in self.events
            if event.get("eventType") == "reviewer_observation" and isinstance(event.get("payload"), Mapping)
        ]

    @property
    def caption(self) -> str:
        for event in reversed(self.events):
            if event.get("eventType") in {"speech_started", "speech_completed", "task_completed"}:
                payload = event.get("payload")
                if isinstance(payload, Mapping):
                    value = payload.get("caption") or payload.get("resultSummary")
                    if isinstance(value, str):
                        return value
        return str(self.state.get("statusText", "Bunny is ready."))

    def resolve(self, approval: Mapping[str, Any], decision: str) -> Mapping[str, Any]:
        if self.active_task_id is None:
            raise ValueError("there is no active task")
        self.snapshot = self.client.resolve_approval(self.active_task_id, approval, decision)
        return self.snapshot

    def cancel(self) -> Mapping[str, Any]:
        if self.active_task_id is None:
            raise ValueError("there is no active task")
        self.snapshot = self.client.cancel(self.active_task_id)
        return self.snapshot


def _gtk() -> tuple[Any, Any, Any, Any]:
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        from gi.repository import Gdk, Gio, GLib, Gtk
    except (ImportError, ValueError) as exc:
        raise RuntimeError("GTK4/PyGObject is required for the Bunny Companion visual shell") from exc
    return Gdk, Gio, GLib, Gtk


class BunnyCompanionApplication:
    def __init__(self, socket_path: Path) -> None:
        Gdk, Gio, GLib, Gtk = _gtk()
        self.Gdk, self.Gio, self.GLib, self.Gtk = Gdk, Gio, GLib, Gtk
        self.model = CompanionViewModel(CompanionClient(socket_path, timeout=5.0))
        self.preferences = WindowPreferences()
        self.app = Gtk.Application(
            application_id="art.comrade.BunnyCompanion",
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )
        self.app.connect("activate", self._activate)
        self.window: Any = None
        self.root: Any = None
        self.body: Any = None
        self.status_label: Any = None
        self.caption_label: Any = None
        self.progress: Any = None
        self.privacy_label: Any = None
        self.indicator_label: Any = None
        self.request_entry: Any = None
        self.error_label: Any = None
        self._hidden = False
        self._last_revision = -1

    def _label(self, text: str, css: str | None = None, *, selectable: bool = False) -> Any:
        label = self.Gtk.Label(label=text, xalign=0, wrap=True, selectable=selectable)
        if css:
            label.add_css_class(css)
        return label

    def _button(self, label: str, callback: Any, *, css: str | None = None) -> Any:
        button = self.Gtk.Button(label=label)
        if css:
            button.add_css_class(css)
        button.update_property([self.Gtk.AccessibleProperty.LABEL], [label])
        button.connect("clicked", callback)
        return button

    def _activate(self, app: Any) -> None:
        if self.window is not None:
            self._hidden = False
            self.window.set_visible(True)
            self.window.present()
            return
        self._install_css()
        self.window = self.Gtk.ApplicationWindow(application=app, title="Bunny Companion")
        self.window.set_default_size(440, 620)
        self.window.add_css_class("bunny-companion-window")
        header = self.Gtk.HeaderBar()
        header.set_title_widget(self._label("Bunny Companion", "title-3"))
        header.pack_start(self._button("Compact", lambda _button: self._set_size("compact")))
        header.pack_start(self._button("Dock", lambda _button: self._set_size("docked")))
        header.pack_end(self._button("Hide", lambda _button: self._hide()))
        header.pack_end(self._button("Minimize", lambda _button: self._minimize()))
        self.window.set_titlebar(header)

        scroller = self.Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        self.root = self.Gtk.Box(orientation=self.Gtk.Orientation.VERTICAL, spacing=14)
        self.root.set_margin_top(18)
        self.root.set_margin_bottom(18)
        self.root.set_margin_start(20)
        self.root.set_margin_end(20)
        scroller.set_child(self.root)

        self.body = self.Gtk.Box(orientation=self.Gtk.Orientation.VERTICAL, spacing=12)
        self.root.append(self.body)
        self.status_label = self._label("Connecting to the companion runtime…", "title-2", selectable=True)
        self.status_label.update_property(
            [self.Gtk.AccessibleProperty.DESCRIPTION],
            ["Current Bunny Companion task state"],
        )
        self.body.append(self.status_label)
        self.indicator_label = self._label("● Idle", "bunny-indicator")
        self.body.append(self.indicator_label)
        self.progress = self.Gtk.ProgressBar(show_text=True)
        self.progress.update_property(
            [self.Gtk.AccessibleProperty.LABEL],
            ["Task progress"],
        )
        self.body.append(self.progress)

        asset = _asset_path()
        if asset.is_file():
            picture = self.Gtk.Picture.new_for_filename(str(asset))
            picture.set_size_request(220, 220)
            picture.set_can_shrink(True)
            picture.add_css_class("bunny-character")
            self.body.append(picture)

        bubble = self.Gtk.Box(orientation=self.Gtk.Orientation.VERTICAL, spacing=6)
        bubble.add_css_class("bunny-speech-bubble")
        bubble.append(self._label("Caption", "caption-heading"))
        self.caption_label = self._label("Bunny is ready.", selectable=True)
        bubble.append(self.caption_label)
        self.body.append(bubble)

        self.privacy_label = self._label("Privacy: local · microphone off · no remote provider", selectable=True)
        self.privacy_label.add_css_class("bunny-privacy")
        self.body.append(self.privacy_label)

        request_box = self.Gtk.Box(orientation=self.Gtk.Orientation.HORIZONTAL, spacing=8)
        self.request_entry = self.Gtk.Entry(placeholder_text="Ask Bunny to do a harmless local task")
        self.request_entry.set_hexpand(True)
        self.request_entry.update_property(
            [self.Gtk.AccessibleProperty.DESCRIPTION],
            ["Submit a task to the Bunny Companion runtime"],
        )
        self.request_entry.connect("activate", self._submit)
        request_box.append(self.request_entry)
        request_box.append(self._button("Submit", self._submit, css="suggested-action"))
        self.body.append(request_box)
        self.error_label = self._label("", "error")
        self.body.append(self.error_label)

        self.window.set_child(scroller)
        self.app.set_accels_for_action("window.close", ["<Control>w"])
        self.window.present()
        try:
            self.model.connect()
        except (CompanionClientError, OSError) as exc:
            self.model.connection_error = str(exc)
        self._render(force=True)
        self.GLib.timeout_add(750, self._poll)

    def _install_css(self) -> None:
        provider = self.Gtk.CssProvider()
        provider.load_from_data(b"""
            .bunny-companion-window { background: @window_bg_color; }
            .bunny-character { margin: 8px; }
            .bunny-speech-bubble { background: alpha(@accent_bg_color, .12); border-radius: 18px; padding: 14px; }
            .bunny-privacy { background: alpha(@view_fg_color, .06); border-radius: 10px; padding: 10px; }
            .bunny-indicator { font-weight: 700; }
            .caption-heading { font-size: .82em; font-weight: 700; opacity: .75; }
            .approval-card { border: 1px solid alpha(@view_fg_color, .22); border-radius: 14px; padding: 14px; }
            .review-card { background: alpha(@view_fg_color, .05); border-radius: 10px; padding: 10px; }
        """)
        display = self.Gdk.Display.get_default()
        if display is not None:
            self.Gtk.StyleContext.add_provider_for_display(
                display,
                provider,
                self.Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )

    def _set_size(self, mode: str) -> None:
        if mode == "compact":
            self.window.set_default_size(320, 300)
        else:
            self.window.set_default_size(440, 620)

    def _hide(self) -> None:
        self._hidden = True
        self.window.set_visible(False)

    def _minimize(self) -> None:
        method = getattr(self.window, "minimize", None)
        if callable(method):
            method()
        else:
            self._hide()

    def _submit(self, _widget: Any) -> None:
        request = self.request_entry.get_text().strip()
        if not request:
            return
        try:
            self.model.submit(request)
            self.request_entry.set_text("")
            self.error_label.set_text("")
        except (CompanionClientError, OSError, ValueError) as exc:
            self.error_label.set_text(str(exc))
        self._render(force=True)

    def _resolve(self, approval: Mapping[str, Any], decision: str) -> None:
        try:
            self.model.resolve(approval, decision)
            self.error_label.set_text("")
        except (CompanionClientError, OSError, ValueError) as exc:
            self.error_label.set_text(str(exc))
        self._render(force=True)

    def _cancel(self, _button: Any) -> None:
        try:
            self.model.cancel()
        except (CompanionClientError, OSError, ValueError) as exc:
            self.error_label.set_text(str(exc))
        self._render(force=True)

    def _poll(self) -> bool:
        if self.model.active_task_id is not None:
            self.model.refresh()
        self._render()
        return self.GLib.SOURCE_CONTINUE

    def _clear_dynamic(self) -> None:
        child = self.body.get_first_child()
        fixed = 0
        while child is not None:
            next_child = child.get_next_sibling()
            fixed += 1
            # Everything after error_label is dynamic.  Identity comparison is
            # stable even when the GTK widget hierarchy is rebuilt.
            if child is self.error_label:
                while next_child is not None:
                    following = next_child.get_next_sibling()
                    self.body.remove(next_child)
                    next_child = following
                break
            child = next_child

    def _render(self, *, force: bool = False) -> None:
        state = self.model.state
        revision = int(state.get("stateRevision", -1)) if state else -1
        if not force and revision == self._last_revision and not self.model.connection_error:
            return
        self._last_revision = revision
        if self.model.connection_error:
            self.status_label.set_text("Companion runtime disconnected")
            self.indicator_label.set_text("● Disconnected")
            self.error_label.set_text(self.model.connection_error)
            return
        if not state:
            self.status_label.set_text("Bunny is idle")
            self.indicator_label.set_text("● Ready")
            self.caption_label.set_text("Submit a task when you are ready.")
            self.progress.set_fraction(0.0)
            self.progress.set_text("No active task")
            self._clear_dynamic()
            return
        phase_text = str(state.get("state", "idle"))
        self.status_label.set_text(str(state.get("statusText", "Bunny is working.")))
        self.indicator_label.set_text(self._indicator(phase_text))
        progress = state.get("progress")
        fraction = float(progress) if isinstance(progress, (float, int)) else 0.0
        self.progress.set_fraction(max(0.0, min(1.0, fraction)))
        self.progress.set_text(f"{fraction:.0%}" if progress is not None else phase_text.replace("_", " ").title())
        self.caption_label.set_text(self.model.caption)
        privacy = state.get("privacyIndicator") if isinstance(state.get("privacyIndicator"), Mapping) else {}
        privacy_parts = [str(privacy.get("classification", "internal"))]
        privacy_parts.append("remote provider active" if privacy.get("remoteProviderActive") else "local provider")
        privacy_parts.append("microphone on" if privacy.get("microphoneActive") else "microphone off")
        if privacy.get("audioTransmitted"):
            privacy_parts.append("audio transmitting")
        if privacy.get("systemModificationActive"):
            privacy_parts.append("system modification active")
        self.privacy_label.set_text("Privacy: " + " · ".join(privacy_parts))
        self._clear_dynamic()
        self._append_task_panel()
        for observation in self.model.reviewer_observations:
            self._append_reviewer(observation)
        for approval in self.model.approvals:
            self._append_approval(approval)
        self._apply_window_policy(phase_text)

    @staticmethod
    def _indicator(phase: str) -> str:
        labels = {
            "listening": "● Listening — microphone active",
            "transcribing": "● Transcribing",
            "speaking": "● Speaking",
            "waiting_for_approval": "● Approval required",
            "working": "● Working locally",
            "reviewing": "● Reviewer observing",
            "success": "● Complete",
            "error": "● Error",
            "degraded": "● Degraded presentation",
        }
        return labels.get(phase, "● " + phase.replace("_", " ").title())

    def _append_task_panel(self) -> None:
        task = self.model.task
        panel = self.Gtk.Box(orientation=self.Gtk.Orientation.VERTICAL, spacing=7)
        panel.add_css_class("review-card")
        panel.append(self._label("Task panel", "title-3"))
        executor = task.get("executor") if isinstance(task.get("executor"), Mapping) else {}
        tool_operations = task.get("toolOperations") if isinstance(task.get("toolOperations"), list) else []
        active_tool = next((item for item in reversed(tool_operations) if isinstance(item, Mapping)), {})
        outputs = task.get("outputs") if isinstance(task.get("outputs"), list) else []
        errors = task.get("errors") if isinstance(task.get("errors"), list) else []
        rows = (
            ("Task", task.get("displaySummary", "No task")),
            ("Phase", task.get("currentPhase", "unknown")),
            ("Active agent", executor.get("agentId", "none")),
            ("Current tool", active_tool.get("toolId", "none")),
            ("Progress", f"{float(task.get('progress') or 0):.0%}"),
            ("Result", outputs[-1].get("displaySummary", "pending") if outputs and isinstance(outputs[-1], Mapping) else "pending"),
            ("Errors", errors[-1].get("displayMessage", "none") if errors and isinstance(errors[-1], Mapping) else "none"),
        )
        for name, value in rows:
            panel.append(self._label(f"{name}: {value}", selectable=True))
        if task and task.get("currentPhase") not in {"completed", "failed", "cancelled"}:
            panel.append(self._button("Cancel task", self._cancel))
        self.body.append(panel)

    def _append_reviewer(self, observation: Mapping[str, Any]) -> None:
        card = self.Gtk.Box(orientation=self.Gtk.Orientation.VERTICAL, spacing=5)
        card.add_css_class("review-card")
        card.append(self._label(
            f"Reviewer · {observation.get('severity', 'info')} · {observation.get('category', 'quality')}",
            "title-4",
        ))
        card.append(self._label(str(observation.get("summary", "No summary")), selectable=True))
        card.append(self._label(f"Suggested action: {observation.get('suggestedAction', 'None')}", selectable=True))
        card.append(self._label("Reviewer authority: observation only; no tools or approvals", selectable=True))
        self.body.append(card)

    def _append_approval(self, approval: Mapping[str, Any]) -> None:
        card = self.Gtk.Box(orientation=self.Gtk.Orientation.VERTICAL, spacing=7)
        card.add_css_class("approval-card")
        card.append(self._label("Approval Centre", "title-2"))
        fields = (
            ("Requested action", approval.get("requestedAction")),
            ("Why it is needed", approval.get("whyNeeded")),
            ("Requesting agent", approval.get("requestingAgent")),
            ("Data affected", approval.get("dataAffected")),
            ("Destination", approval.get("destination")),
            ("Provider destination", approval.get("providerDestination") or "none"),
            ("Local or remote", approval.get("locality")),
            ("Cost", approval.get("estimatedCostUnits") if approval.get("estimatedCostUnits") is not None else "free"),
            ("Resource impact", approval.get("resourceImpact")),
            ("Alternatives", "; ".join(str(item) for item in approval.get("alternatives", []))),
            ("Expiration", approval.get("expiration")),
            ("Safe default", "No action if unanswered"),
        )
        for name, value in fields:
            card.append(self._label(f"{name}: {value}", selectable=True))
        actions = self.Gtk.Box(orientation=self.Gtk.Orientation.HORIZONTAL, spacing=8)
        actions.append(self._button("Approve", lambda _button, item=approval: self._resolve(item, "approve"), css="suggested-action"))
        actions.append(self._button("Deny", lambda _button, item=approval: self._resolve(item, "deny"), css="destructive-action"))
        actions.append(self._button("Cancel task", lambda _button, item=approval: self._resolve(item, "cancel_task")))
        card.append(actions)
        self.body.append(card)

    def _apply_window_policy(self, phase_text: str) -> None:
        try:
            phase = CompanionPhase(phase_text)
        except ValueError:
            phase = CompanionPhase.IDLE
        display = self.Gdk.Display.get_default()
        monitors: list[MonitorGeometry] = []
        if display is not None:
            model = display.get_monitors()
            for index in range(model.get_n_items()):
                monitor = model.get_item(index)
                geometry = monitor.get_geometry()
                monitors.append(MonitorGeometry(
                    monitor_id=f"monitor-{index}",
                    x=geometry.x,
                    y=geometry.y,
                    width=geometry.width,
                    height=geometry.height,
                    scale=float(monitor.get_scale_factor()),
                ))
        directive = window_directive(
            phase,
            self.preferences,
            DesktopContext(monitors=tuple(monitors), active_monitor_id="monitor-0" if monitors else None),
        )
        if not self._hidden:
            self.window.set_visible(directive.visible)
        keep_above = getattr(self.window, "set_keep_above", None)
        if callable(keep_above):
            keep_above(directive.always_on_top)
        # GTK4 on Wayland intentionally gives placement to the compositor.  The
        # directive still drives size/docking and is exposed to the shell; no
        # unsupported absolute window movement is claimed here.
        if directive.placement == Placement.COMPACT:
            self.window.set_default_size(320, 300)
        elif directive.placement in {Placement.DOCKED, Placement.TASK_PANEL}:
            self.window.set_default_size(440, 620)
        else:
            self.window.set_default_size(480, 640)

    def run(self) -> int:
        return int(self.app.run(None))


def run(socket_path: Path) -> int:
    return BunnyCompanionApplication(socket_path).run()
