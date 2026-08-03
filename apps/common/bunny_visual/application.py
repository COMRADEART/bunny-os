"""GTK 4 and libadwaita applications for Bunny Visual Phase V1."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .runtime import decision_available, diagnostic_facts, load_state, submit_decision


SECTIONS = (
    "Appearance", "Desktop", "Layouts", "Assistant", "Privacy", "Approvals",
    "Providers", "Applications", "Notifications", "Accessibility", "Updates",
    "Recovery", "Diagnostics", "About Bunny OS",
)


def _libraries() -> tuple[Any, Any, Any, Any, Any]:
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, Gdk, Gio, GLib, Gtk
    except (ImportError, ValueError) as exc:
        raise RuntimeError("GTK 4, libadwaita, and PyGObject are required") from exc
    return Adw, Gdk, Gio, GLib, Gtk


class VisualApplication:
    def __init__(self, surface: str) -> None:
        self.Adw, self.Gdk, self.Gio, self.GLib, self.Gtk = _libraries()
        self.surface = surface
        suffix = "".join(part.title() for part in surface.split("-"))
        self.app = self.Adw.Application(application_id=f"org.bunnyos.VisualV1.{suffix}")
        self.app.connect("activate", self._activate)
        self.state = load_state()

    def _label(self, text: str, css: str | None = None, *, selectable: bool = False) -> Any:
        label = self.Gtk.Label(label=text, xalign=0, wrap=True, selectable=selectable)
        if css:
            label.add_css_class(css)
        return label

    def _box(self, spacing: int = 12) -> Any:
        return self.Gtk.Box(orientation=self.Gtk.Orientation.VERTICAL, spacing=spacing)

    def _card(self) -> Any:
        card = self._box(8)
        card.add_css_class("bunny-card")
        return card

    def _row(self, title: str, description: str) -> Any:
        row = self.Adw.ActionRow(title=title, subtitle=description)
        row.update_property([self.Gtk.AccessibleProperty.LABEL], [f"{title}. {description}"])
        return row

    def _activate(self, app: Any) -> None:
        window = self.Adw.ApplicationWindow(application=app, title=self._title())
        window.set_default_size(1040, 760)
        window.add_css_class("bunny-window")
        toolbar = self.Adw.ToolbarView()
        header = self.Adw.HeaderBar()
        header.set_title_widget(self._label(self._title(), "title-3"))
        toolbar.add_top_bar(header)
        content = self._content()
        if self.state["mockMode"]:
            wrapper = self._box(8)
            banner = self._label("VISUAL MOCK DATA · not observed system state", "bunny-mock-banner")
            banner.update_property([self.Gtk.AccessibleProperty.LABEL], ["Visual mock data. Not observed system state."])
            wrapper.append(banner)
            wrapper.append(content)
            content = wrapper
        scroller = self.Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scroller.set_policy(self.Gtk.PolicyType.NEVER, self.Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(content)
        toolbar.set_content(scroller)
        window.set_content(toolbar)
        self._load_css()
        window.present()

    def _load_css(self) -> None:
        provider = self.Gtk.CssProvider()
        css = Path(__file__).with_name("style.css")
        provider.load_from_path(str(css))
        self.Gtk.StyleContext.add_provider_for_display(
            self.Gdk.Display.get_default(), provider, self.Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def _title(self) -> str:
        return {
            "command-center": "Bunny Control Center",
            "approval-center": "Approval Center",
            "assistant": "Bunny Assistant",
            "diagnostics": "Bunny Diagnostics",
            "welcome": "Welcome to Bunny OS",
        }.get(self.surface, "Bunny Desktop")

    def _content(self) -> Any:
        builder = {
            "command-center": self._command_center,
            "approval-center": self._approval_center,
            "assistant": self._assistant,
            "diagnostics": self._diagnostics,
            "welcome": self._welcome_placeholder,
        }.get(self.surface)
        if builder is None:
            raise ValueError(f"unknown Bunny visual surface: {self.surface}")
        content = builder()
        content.set_margin_top(24); content.set_margin_bottom(24)
        content.set_margin_start(24); content.set_margin_end(24)
        return content

    def _command_center(self) -> Any:
        split = self.Gtk.Paned(orientation=self.Gtk.Orientation.HORIZONTAL, wide_handle=True)
        navigation = self.Gtk.ListBox(selection_mode=self.Gtk.SelectionMode.SINGLE)
        navigation.set_size_request(260, -1)
        stack = self.Gtk.Stack(transition_type=self.Gtk.StackTransitionType.CROSSFADE)
        stack.set_hexpand(True)
        for section in SECTIONS:
            row = self.Gtk.ListBoxRow()
            row.section = section
            row.set_child(self._label(section))
            navigation.append(row)
            page = self._box(12)
            page.append(self._label(section, "title-1"))
            if section == "Appearance":
                page.append(self._row("Theme", "Light, dark, or system; previewed without changing GNOME globally"))
                page.append(self._row("Accent", "Bunny Violet with semantic focus and status colors"))
                page.append(self._row("Wallpaper", "Six original Bunny families with light and dark variants"))
                page.append(self._row("Text and motion", "Text scale, contrast, animation level, and reduced motion"))
            elif section == "Layouts":
                for name, description in (("Normal", "Full Bunny frame"), ("CompactLayout", "Intentional dense component variants"), ("FocusMode", "Minimal chrome with critical-state exceptions")):
                    page.append(self._row(name, description))
            elif section in {"Updates", "Recovery", "Applications"}:
                page.append(self._row("Open system settings", "GNOME remains authoritative where Bunny adds no distinct behavior"))
            elif section == "About Bunny OS":
                page.append(self._label("Bunny Desktop Visual Phase V1", "title-2"))
                page.append(self._label("VISUAL PROTOTYPE ONLY · NOT RELEASE QUALIFIED · DO NOT MERGE"))
            else:
                page.append(self._row(f"{section} overview", "Observed settings and state; unavailable values are never inferred"))
            stack.add_titled(page, section.casefold().replace(" ", "-"), section)
        navigation.connect("row-selected", lambda _list, row: stack.set_visible_child_name(row.section.casefold().replace(" ", "-")) if row else None)
        navigation.select_row(navigation.get_row_at_index(0))
        split.set_start_child(navigation)
        split.set_end_child(stack)
        return split

    def _approval_center(self) -> Any:
        root = self._box(16)
        root.append(self._label("Requests remain pending until the Bunny backend reports a decision.", "dim-label"))
        approvals = self.state["approvals"]
        if not approvals:
            root.append(self._label("No approval requests observed.", "title-2"))
            return root
        for approval in approvals:
            card = self._card()
            severity = approval["severity"].casefold()
            card.add_css_class("bunny-critical" if severity == "critical" else "bunny-privileged" if severity in {"privileged", "sensitive"} else "bunny-standard")
            card.append(self._label(f"⚠ {severity.upper()} APPROVAL", "title-3"))
            for label, key in (
                ("Requesting component", "component"), ("Requested operation", "operation"),
                ("Affected resources", "resources"), ("Privilege level", "privilege"),
                ("Network impact", "networkImpact"), ("Data impact", "dataImpact"),
                ("Reversibility", "reversibility"), ("Reason", "reason"), ("Expiration", "expiration"),
            ):
                value = approval[key]
                card.append(self._label(f"{label}: {', '.join(value) if isinstance(value, list) else value}"))
            actions = self.Gtk.Box(orientation=self.Gtk.Orientation.HORIZONTAL, spacing=12, halign=self.Gtk.Align.END)
            status = self._label("Decision adapter available" if decision_available() else "Decision adapter unavailable; controls are disabled")
            inspect = self.Gtk.Button(label="Inspect details")
            deny = self.Gtk.Button(label="Deny")
            approve = self.Gtk.Button(label="Approve")
            approve.add_css_class("suggested-action")
            for button, decision in ((deny, "deny"), (approve, "approve")):
                button.set_sensitive(decision_available())
                button.update_property([self.Gtk.AccessibleProperty.LABEL], [f"{button.get_label()} request {approval['id']}"])
                button.connect("clicked", lambda _button, value=decision, item=approval, label=status: self._submit(item["id"], value, label))
            actions.append(inspect); actions.append(deny); actions.append(approve)
            card.append(status); card.append(actions)
            if severity == "critical":
                inspect.grab_focus()
            root.append(card)
        return root

    def _submit(self, request_id: str, decision: str, status: Any) -> None:
        try:
            submit_decision(request_id, decision)
            status.set_label("Decision submitted; waiting for an observed backend result.")
        except (OSError, RuntimeError, ValueError) as exc:
            status.set_label(f"Decision not submitted: {exc}")

    def _assistant(self) -> Any:
        root = self._box(16)
        provider = self.state["provider"]
        root.append(self._label(f"Provider state: {provider}", "bunny-state"))
        for title, key, empty in (
            ("Current task", "tasks", "No current task observed"),
            ("Conversation", "conversation", "No conversation observed"),
            ("Plan", "plan", "No plan observed"),
            ("Tool activity", "toolActivity", "No tool activity observed"),
            ("Approval requests", "approvals", "No approval requests observed"),
            ("Result history", "results", "No results observed"),
        ):
            group = self.Adw.PreferencesGroup(title=title)
            items = self.state[key]
            if not items:
                group.add(self._row(empty, "Unavailable state is not inferred"))
            for item in items:
                label = str(item.get("text") or item.get("title") or item.get("operation") or "Untitled")
                state = str(item.get("state") or item.get("severity") or "state unavailable")
                role = str(item.get("role") or item.get("name") or key)
                row = self._row(f"{role}: {label}", state)
                row.add_css_class(f"bunny-role-{role.casefold().replace(' ', '-')}")
                row.add_css_class(f"bunny-action-{state.casefold().replace(' ', '-')}")
                group.add(row)
            root.append(group)
        return root

    def _diagnostics(self) -> Any:
        root = self._box(16)
        root.append(self._label("Observed facts", "title-1"))
        root.append(self._label("Likely impacts and recommendations are labelled separately; no root cause is guessed."))
        for fact in diagnostic_facts(self.state):
            card = self._card()
            card.append(self._label(f"{fact['severity'].upper()} · {fact['fact']}", "title-3"))
            card.append(self._label(f"Likely impact: {fact['impact']}"))
            card.append(self._label(f"Recommended action: {fact['action']}"))
            evidence = self._label(f"Supporting evidence: {fact['evidence']}", "bunny-mono", selectable=True)
            card.append(evidence)
            root.append(card)
        return root

    def _welcome_placeholder(self) -> Any:
        root = self._box(12)
        root.append(self._label("Welcome is completed in the identity and demo stage.", "title-2"))
        return root

    def run(self) -> int:
        return int(self.app.run(None))


def run_surface(surface: str) -> int:
    return VisualApplication(surface).run()
