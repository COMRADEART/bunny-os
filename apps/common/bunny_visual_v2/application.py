"""GTK 4/libadwaita surfaces for Bunny Desktop Visual Phase V2."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .design import LAYOUT, SPACING
from .runtime import character_asset, decision_available, diagnostic_facts, load_state, save_welcome_preferences, submit_decision


NOTICE = "VISUAL PROTOTYPE ONLY · NOT RELEASE QUALIFIED · DO NOT MERGE INTO MAIN"
SECTIONS = (
    "Appearance", "Visual Mode", "Desktop", "Layout", "Dock", "Command Palette",
    "Assistant", "Character", "Privacy", "Approvals", "Notifications",
    "Accessibility", "Diagnostics", "About",
)
POSE_DESCRIPTIONS = {
    "idle-neutral": "Bunny is ready to help.",
    "welcome-wave": "Bunny is welcoming you.",
    "explaining": "Bunny is explaining how the system works.",
    "privacy-mode": "Bunny is explaining active privacy controls.",
    "requesting-approval": "Bunny is explaining that approval is required.",
    "error": "Bunny is explaining a confirmed failure.",
    "offline": "Bunny is explaining that the network is offline.",
}


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
        self.app = self.Adw.Application(application_id=f"org.bunnyos.VisualV2.{suffix}")
        self.app.connect("activate", self._activate)
        self.state = load_state()
        self.settings = self.Gio.Settings.new("org.bunnyos.desktop.visual-v2")

    def _label(self, text: str, css: str | None = None, *, selectable: bool = False) -> Any:
        label = self.Gtk.Label(label=text, xalign=0, wrap=True, selectable=selectable)
        if css:
            label.add_css_class(css)
        return label

    def _box(self, spacing: int = SPACING["md"]) -> Any:
        return self.Gtk.Box(orientation=self.Gtk.Orientation.VERTICAL, spacing=spacing)

    def _card(self) -> Any:
        card = self._box(SPACING["sm"])
        card.add_css_class("bunny-card")
        return card

    def _row(self, title: str, description: str) -> Any:
        row = self.Adw.ActionRow(title=title, subtitle=description)
        row.update_property([self.Gtk.AccessibleProperty.LABEL], [f"{title}. {description}"])
        return row

    def _switch_row(self, title: str, description: str, key: str) -> Any:
        row = self._row(title, description)
        toggle = self.Gtk.Switch(valign=self.Gtk.Align.CENTER)
        self.settings.bind(key, toggle, "active", self.Gio.SettingsBindFlags.DEFAULT)
        toggle.update_property([self.Gtk.AccessibleProperty.LABEL], [title])
        row.add_suffix(toggle)
        row.set_activatable_widget(toggle)
        return row

    def _character(self, pose: str) -> Any:
        region = self._box(8)
        region.add_css_class("bunny-character-region")
        region.update_property([self.Gtk.AccessibleProperty.LABEL], [POSE_DESCRIPTIONS.get(pose, "Bunny is providing visual guidance.")])
        picture = self.Gtk.Picture.new_for_filename(str(character_asset(pose)))
        picture.set_can_shrink(True)
        picture.set_content_fit(self.Gtk.ContentFit.CONTAIN)
        picture.set_size_request(-1, int(LAYOUT["characterIllustrationHeight"]))
        picture.set_focusable(False)
        picture.update_state([self.Gtk.AccessibleState.HIDDEN], [True])
        region.append(picture)
        return region

    def _activate(self, app: Any) -> None:
        window = self.Adw.ApplicationWindow(application=app, title=self._title())
        window.set_default_size(int(LAYOUT["applicationWidth"]), int(LAYOUT["applicationHeight"]))
        window.add_css_class("bunny-window")
        toolbar = self.Adw.ToolbarView()
        header = self.Adw.HeaderBar()
        title = self.Gtk.Box(orientation=self.Gtk.Orientation.VERTICAL, spacing=0)
        title.append(self._label(self._title(), "title-3"))
        title.append(self._label(f"{self.settings.get_string('visual-mode').title()} Mode", "caption"))
        header.set_title_widget(title)
        toolbar.add_top_bar(header)
        content = self._content()
        wrapper = self._box(SPACING["sm"])
        if self.state["mockMode"]:
            banner = self._label("VISUAL MOCK DATA · decisions and actions are simulated", "bunny-mock-banner")
            banner.update_property([self.Gtk.AccessibleProperty.LABEL], ["Visual mock data. Decisions and actions are simulated."])
            wrapper.append(banner)
        wrapper.append(content)
        scroller = self.Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scroller.set_policy(self.Gtk.PolicyType.NEVER, self.Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(wrapper)
        toolbar.set_content(scroller)
        window.set_content(toolbar)
        self._load_css()
        window.present()

    def _load_css(self) -> None:
        provider = self.Gtk.CssProvider()
        provider.load_from_path(str(Path(__file__).with_name("style.css")))
        self.Gtk.StyleContext.add_provider_for_display(
            self.Gdk.Display.get_default(), provider, self.Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def _title(self) -> str:
        return {
            "control-center": "Bunny Control Center",
            "approval-center": "Approval Center",
            "assistant": "Bunny Assistant",
            "diagnostics": "Bunny Diagnostics",
            "welcome": "Welcome to Bunny OS",
        }[self.surface]

    def _content(self) -> Any:
        builder: Callable[[], Any] = {
            "control-center": self._control_center,
            "approval-center": self._approval_center,
            "assistant": self._assistant,
            "diagnostics": self._diagnostics,
            "welcome": self._welcome,
        }[self.surface]
        content = builder()
        for setter in (content.set_margin_top, content.set_margin_bottom, content.set_margin_start, content.set_margin_end):
            setter(SPACING["xl"])
        return content

    def _control_center(self) -> Any:
        split = self.Gtk.Paned(orientation=self.Gtk.Orientation.HORIZONTAL, wide_handle=True)
        navigation = self.Gtk.ListBox(selection_mode=self.Gtk.SelectionMode.SINGLE)
        navigation.set_size_request(int(LAYOUT["applicationNavigationWidth"]), -1)
        stack = self.Gtk.Stack(transition_type=self.Gtk.StackTransitionType.CROSSFADE, hexpand=True)
        for section in SECTIONS:
            row = self.Gtk.ListBoxRow()
            row.section = section
            row.set_child(self._label(section))
            navigation.append(row)
            page = self._settings_page(section)
            stack.add_titled(page, section.casefold().replace(" ", "-"), section)
        navigation.connect("row-selected", lambda _box, row: stack.set_visible_child_name(row.section.casefold().replace(" ", "-")) if row else None)
        navigation.select_row(navigation.get_row_at_index(0))
        split.set_start_child(navigation)
        split.set_end_child(stack)
        return split

    def _settings_page(self, section: str) -> Any:
        page = self._box(SPACING["md"])
        page.append(self._label(section, "title-1"))
        if section == "Visual Mode":
            page.append(self._label("Both modes use the same desktop, actions, settings, and security behavior."))
            preview = self._card()
            preview.append(self._label("Regular Mode", "title-3"))
            preview.append(self._label("A clean professional desktop without the visual guide."))
            preview.append(self._label("Character Mode", "title-3"))
            preview.append(self._label("Adds the Bunny guide to selected assistant, onboarding, and guidance surfaces."))
            live = self._label(f"Live preview: {self.settings.get_string('visual-mode').title()} Mode", "bunny-state")
            preview.append(live)
            page.append(preview)
            picker = self.Gtk.DropDown.new_from_strings(["Regular Mode", "Character Mode"])
            picker.set_selected(1 if self.settings.get_string("visual-mode") == "character" else 0)
            picker.update_property([self.Gtk.AccessibleProperty.LABEL], ["Bunny visual mode"])
            def update_mode(control: Any, _property: Any) -> None:
                selected = "character" if control.get_selected() == 1 else "regular"
                self._set_visual_mode(selected)
                live.set_label(f"Live preview: {selected.title()} Mode")
            picker.connect("notify::selected", update_mode)
            page.append(picker)
        elif section == "Character":
            page.append(self._switch_row("Character enabled", "Allowed only in approved surfaces", "character-enabled"))
            page.append(self._switch_row("Reduced character motion", "Removes character entrance effects", "character-reduced-motion"))
            page.append(self._switch_row("Educational appearances", "Explanations, privacy, and approval education", "character-educational-appearances"))
            page.append(self._switch_row("Success appearances", "Only after an observed result", "character-success-appearances"))
            page.append(self._switch_row("Error appearances", "Confirmed failure and offline guidance", "character-error-appearances"))
            page.append(self._switch_row("Onboarding appearances", "Selected first-run steps", "character-onboarding-appearances"))
            scale = self.Gtk.Scale.new_with_range(self.Gtk.Orientation.HORIZONTAL, 0.8, 1.2, 0.05)
            scale.set_value(self.settings.get_double("character-scale"))
            scale.update_property([self.Gtk.AccessibleProperty.LABEL], ["Character scale"])
            scale.connect("value-changed", lambda control: self.settings.set_double("character-scale", control.get_value()))
            page.append(scale)
        elif section == "Layout":
            page.append(self._row("Normal", "Full top bar, adaptive dock, and standard spacing"))
            page.append(self._row("Compact", "Intentional dense variants; not global scaling"))
            page.append(self._row("FocusMode", "Minimal chrome with visible exit and critical exceptions"))
        elif section == "Command Palette":
            page.append(self._row("Super + Space", "Fixed applications, windows, workspaces, settings, diagnostics, approvals, and power-action routing"))
            page.append(self._row("Security", "Arbitrary text is never sent to a shell"))
        elif section == "Appearance":
            page.append(self._row("Color scheme", "Intentional dark, light, and high-contrast presentations"))
            page.append(self._switch_row("Reduced motion", "Removes nonessential desktop and character motion", "reduced-motion"))
            page.append(self._switch_row("High contrast", "Opaque surfaces, strong borders, and visible focus", "high-contrast"))
        elif section == "About":
            page.append(self._label("Bunny Desktop Visual Phase V2", "title-2"))
            page.append(self._label(NOTICE))
        else:
            page.append(self._row(f"{section} overview", "Observed values are shown; unavailable state is never inferred"))
        return page

    def _set_visual_mode(self, mode: str) -> None:
        self.settings.set_string("visual-mode", mode)
        self.settings.set_boolean("character-enabled", mode == "character")

    def _assistant(self) -> Any:
        root = self._box(SPACING["lg"])
        root.append(self._label(f"State: {self.state['assistantState']} · Provider: {self.state['providerState']}", "bunny-state"))
        root.append(self._label("I can help with tasks, explain features, and keep observed system state understandable.", "title-2"))
        if self.state["approvals"]:
            root.append(self._row("Approval required", "Open Approval Center to inspect native controls and consequences"))
        if self.settings.get_string("visual-mode") == "character" and self.settings.get_boolean("character-enabled") and self.state["bunnyEnabled"]:
            pose = "requesting-approval" if self.state["approvals"] else "offline" if self.state["assistantState"] == "Offline" else "error" if self.state["assistantState"] == "Failed" else "idle-neutral"
            root.append(self._character(pose))
        else:
            for title, key, empty in (("Recent activity", "recentActions", "No recent actions"), ("System context", "systemContext", "No additional context"), ("Suggested actions", "suggestions", "No suggestions")):
                group = self.Adw.PreferencesGroup(title=title)
                items = self.state[key]
                if not items:
                    group.add(self._row(empty, "Unavailable state is not inferred"))
                for item in items:
                    group.add(self._row(str(item.get("label", "Observed item")), str(item.get("detail", "State unavailable"))))
                root.append(group)
        composer = self.Gtk.Entry(placeholder_text="Ask Bunny…")
        composer.update_property([self.Gtk.AccessibleProperty.LABEL], ["Ask Bunny"])
        root.append(composer)
        return root

    def _approval_center(self) -> Any:
        root = self._box(SPACING["lg"])
        root.append(self._label("Requests remain pending until the backend reports a decision.", "dim-label"))
        if not self.state["approvals"]:
            root.append(self._label("No approval requests observed.", "title-2"))
            return root
        for approval in self.state["approvals"]:
            card = self._card()
            severity = str(approval.get("severity", "standard")).casefold()
            card.append(self._label(f"{severity.upper()} · APPROVAL REQUIRED", "title-3"))
            fields = (("Requesting application", "application"), ("Operation", "operation"), ("Resources affected", "resources"), ("Privilege level", "privilege"), ("Network impact", "networkImpact"), ("Data impact", "dataImpact"), ("Reversibility", "reversibility"), ("Reason", "reason"), ("Expiration", "expiration"))
            for label, key in fields:
                raw = approval.get(key, "Not reported")
                value = ", ".join(raw) if isinstance(raw, list) else str(raw)
                card.append(self._label(f"{label}: {value}"))
            actions = self.Gtk.Box(orientation=self.Gtk.Orientation.HORIZONTAL, spacing=SPACING["md"], halign=self.Gtk.Align.END)
            status = self._label("Decision adapter available" if decision_available() else "Decision controls unavailable or simulated")
            inspect = self.Gtk.Button(label="Inspect details")
            deny = self.Gtk.Button(label="Deny")
            approve = self.Gtk.Button(label="Approve")
            confirmation = None
            if severity == "critical":
                confirmation = self.Gtk.CheckButton(label="I understand the stated irreversible consequences")
                confirmation.update_property([self.Gtk.AccessibleProperty.LABEL], ["Confirm understanding of irreversible consequences"])
                card.append(confirmation)
                approve.set_sensitive(False)
                confirmation.connect("toggled", lambda control: approve.set_sensitive(control.get_active() and decision_available()))
            else:
                approve.set_sensitive(decision_available())
            deny.set_sensitive(decision_available())
            for button, decision in ((deny, "deny"), (approve, "approve")):
                button.update_property([self.Gtk.AccessibleProperty.LABEL], [f"{button.get_label()} approval request"])
                button.connect("clicked", lambda _button, value=decision, item=approval: self._submit(item.get("id", "unavailable"), value, status))
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

    def _diagnostics(self) -> Any:
        root = self._box(SPACING["lg"])
        root.append(self._label("Observed facts", "title-1"))
        root.append(self._label("Likely impacts and recommendations are labelled separately; no root cause is fabricated."))
        for fact in diagnostic_facts(self.state):
            card = self._card()
            card.append(self._label(f"{fact['severity'].upper()} · {fact['fact']}", "title-3"))
            card.append(self._label(f"Likely impact: {fact['impact']}"))
            card.append(self._label(f"Recommended action: {fact['action']}"))
            card.append(self._label(f"Supporting evidence: {fact['evidence']}", "bunny-mono", selectable=True))
            root.append(card)
        if self.settings.get_string("visual-mode") == "character" and self.state["assistantState"] in {"Offline", "Failed"}:
            root.append(self._character("offline" if self.state["assistantState"] == "Offline" else "error"))
        return root

    def _welcome(self) -> Any:
        root = self._box(SPACING["lg"])
        root.append(self._label("Set up a complete desktop with no account, cloud provider, or internet connection.", "title-2"))
        stack = self.Gtk.Stack(transition_type=self.Gtk.StackTransitionType.SLIDE_LEFT_RIGHT, vexpand=True)
        preferences: dict[str, Any] = {"language": "system", "keyboard": "system", "appearance": "system", "visualMode": "regular", "bunnyEnabled": False, "localOnly": True, "provider": "none", "highContrast": False, "largeText": False, "reducedMotion": False}
        pages: list[Any] = []

        def page(title: str, body: str, pose: str | None = None) -> Any:
            box = self._box(SPACING["lg"])
            box.append(self._label(title, "title-1"))
            box.append(self._label(body))
            box.pose = pose
            pages.append(box)
            stack.add_named(box, f"step-{len(pages) - 1}")
            return box

        language = page("Language", "Choose from installed languages; System default works offline.", "welcome-wave")
        language.append(self.Gtk.DropDown.new_from_strings(["System default", "English", "Español", "Français", "Deutsch"]))
        keyboard = page("Keyboard", "Use the current GNOME keyboard layout or change it later at login.", "explaining")
        keyboard.append(self._row("System keyboard layout", "Additional installed layouts remain available"))
        appearance = page("Appearance", "Light and dark presentations have equal functional support.", "explaining")
        appearance.append(self.Gtk.DropDown.new_from_strings(["Follow system", "Light", "Dark"]))
        mode = page("Regular Mode or Character Mode", "Regular Mode is professional and character-free. Character Mode adds one guide only in approved surfaces.", "welcome-wave")
        mode_picker = self.Gtk.DropDown.new_from_strings(["Regular Mode", "Character Mode"])
        mode_picker.update_property([self.Gtk.AccessibleProperty.LABEL], ["Onboarding visual mode"])
        mode.append(mode_picker)
        access = page("Accessibility", "These choices supplement the accessibility menu at login and in Quick Settings.", "explaining")
        for label, key in (("High contrast", "highContrast"), ("Large text", "largeText"), ("Reduced motion", "reducedMotion")):
            row = self._row(label, "Can be changed at any time")
            toggle = self.Gtk.Switch(valign=self.Gtk.Align.CENTER)
            toggle.connect("notify::active", lambda control, _property, name=key: preferences.update({name: control.get_active()}))
            row.add_suffix(toggle); row.set_activatable_widget(toggle); access.append(row)
        privacy = page("Privacy", "Bunny is optional, telemetry is off, and device activity remains visible.", "privacy-mode")
        bunny = self._row("Enable Bunny", "Off by default")
        bunny_toggle = self.Gtk.Switch(active=False, valign=self.Gtk.Align.CENTER)
        bunny_toggle.connect("notify::active", lambda control, _property: preferences.update(bunnyEnabled=control.get_active()))
        bunny.add_suffix(bunny_toggle); bunny.set_activatable_widget(bunny_toggle); privacy.append(bunny)
        provider = page("Local Only or optional provider", "Local Only is the default. No provider credentials are collected by Welcome.", "privacy-mode")
        provider_picker = self.Gtk.DropDown.new_from_strings(["Local Only · no provider", "Local model", "Set up cloud later"])
        provider_picker.connect("notify::selected", lambda control, _property: preferences.update(provider=["none", "local", "cloud-optional"][control.get_selected()], localOnly=control.get_selected() != 2))
        provider.append(provider_picker)
        approval = page("Approval model", "Sensitive and privileged actions identify resources and consequences before a decision.", "explaining")
        approval.append(self._row("No silent authority", "Critical approvals require explicit confirmation and have no preselected approval"))
        finish = page("Finish", "Only non-secret preferences are saved locally. No network service is enabled.", "welcome-wave")
        status = self._label("")
        finish.append(status)
        save = self.Gtk.Button(label="Finish setup")
        save.add_css_class("suggested-action")
        finish.append(save)

        index = {"value": 0}
        navigation = self.Gtk.Box(orientation=self.Gtk.Orientation.HORIZONTAL, spacing=SPACING["md"], halign=self.Gtk.Align.END)
        back = self.Gtk.Button(label="Back")
        next_button = self.Gtk.Button(label="Next")

        def decorate() -> None:
            for page_widget in pages:
                children = []
                child = page_widget.get_first_child()
                while child is not None:
                    children.append(child)
                    child = child.get_next_sibling()
                for child in children:
                    if child.has_css_class("bunny-character-region"):
                        page_widget.remove(child)
            current = pages[index["value"]]
            if preferences["visualMode"] == "character" and current.pose and self.settings.get_boolean("character-onboarding-appearances"):
                current.insert_child_after(self._character(current.pose), None)

        def show(offset: int) -> None:
            index["value"] = max(0, min(len(pages) - 1, index["value"] + offset))
            stack.set_visible_child_name(f"step-{index['value']}")
            back.set_sensitive(index["value"] > 0)
            next_button.set_sensitive(index["value"] < len(pages) - 1)
            decorate()

        def select_mode(control: Any, _property: Any) -> None:
            selected = "character" if control.get_selected() == 1 else "regular"
            preferences["visualMode"] = selected
            self._set_visual_mode(selected)
            decorate()

        mode_picker.connect("notify::selected", select_mode)
        back.connect("clicked", lambda _button: show(-1))
        next_button.connect("clicked", lambda _button: show(1))
        back.set_sensitive(False)
        navigation.append(back); navigation.append(next_button)

        def persist(_button: Any) -> None:
            try:
                destination = save_welcome_preferences(preferences)
                status.set_label(f"Setup saved locally to {destination}. No network request was made.")
            except (OSError, ValueError) as exc:
                status.set_label(f"Setup was not saved: {exc}")

        save.connect("clicked", persist)
        root.append(stack); root.append(navigation)
        show(0)
        return root

    def run(self) -> int:
        return int(self.app.run(None))


def run_surface(surface: str) -> int:
    return VisualApplication(surface).run()
