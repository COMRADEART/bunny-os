"""GTK 4 views for the Bunny shell components.

BUNNY WAYLAND SHELL EXPERIMENT — NOT RELEASE QUALIFIED — DO NOT USE AS THE
DEFAULT SESSION.

Each builder turns a model from this package into widgets. Models carry the
policy; these functions carry only presentation, so a rule such as "a privacy
indicator is always visible" is enforced in the model and merely rendered here.
"""

from __future__ import annotations

import datetime as _datetime

from .chrome import DockModel, Region, TopBarModel
from .model import ShellState
from .notifications import NotificationCenter
from .palette import CommandPalette
from .quicksettings import QuickSettings, UNAVAILABLE_LABEL
from .runtime import apply_layer_shell, spec


STYLE = """
window.bunny-chrome { background-color: rgba(14,16,22,0.94); color: #e9ecf5; }
.bunny-topbar { padding: 0 12px; font-size: 12px; }
.bunny-dock { padding: 6px 12px; }
.bunny-dock button { min-width: 44px; min-height: 44px; margin: 0 3px; }
.bunny-indicator { color: #ffcf6b; font-weight: bold; }
.bunny-unavailable { color: #9aa3b8; font-style: italic; }
.bunny-behavior { color: #9fb4ff; font-size: 11px; }
.bunny-notice { color: #ff9d6b; font-size: 11px; font-weight: bold; }
.bunny-running { border-bottom: 2px solid #ffcf6b; }
"""


def _gtk():
    import gi

    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk

    return Gtk


def install_style() -> None:
    Gtk = _gtk()
    from gi.repository import Gdk

    provider = Gtk.CssProvider()
    provider.load_from_data(STYLE.encode("utf-8"))
    display = Gdk.Display.get_default()
    if display is not None:
        Gtk.StyleContext.add_provider_for_display(
            display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )


def notice_label():
    """The banner every running surface must show."""

    Gtk = _gtk()
    label = Gtk.Label(label="BUNNY WAYLAND SHELL EXPERIMENT · NOT RELEASE QUALIFIED")
    label.add_css_class("bunny-notice")
    label.set_tooltip_text(
        "BUNNY WAYLAND SHELL EXPERIMENT\nNOT RELEASE QUALIFIED\nDO NOT USE AS THE DEFAULT SESSION"
    )
    return label


def build_top_bar(state: ShellState):
    Gtk = _gtk()
    model = TopBarModel(state)
    root = Gtk.CenterBox()
    root.add_css_class("bunny-topbar")

    def region_box(region: Region):
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        for item in model.visible_items(region):
            if item.key == "time":
                label = Gtk.Label(label=_datetime.datetime.now().strftime("%H:%M"))
            elif item.key == "date":
                label = Gtk.Label(label=_datetime.datetime.now().strftime("%a %d %b"))
            elif item.key == "focus-mode":
                if not state.focus_mode:
                    continue
                label = Gtk.Label(label="FocusMode")
            elif item.key == "activity":
                label = Gtk.Label(label=f"Workspace {state.active_workspace + 1}")
            else:
                label = Gtk.Label(label=item.label)
            if item.privacy:
                label.add_css_class("bunny-indicator")
            if not item.privacy and item.backend.value == "unavailable":
                label.add_css_class("bunny-unavailable")
            # Every element is named for assistive technology. The top bar is
            # the surface a screen reader hits first.
            label.set_tooltip_text(item.label)
            label.update_property([Gtk.AccessibleProperty.LABEL], [item.label])
            box.append(label)
        return box

    root.set_start_widget(region_box(Region.LEFT))
    root.set_center_widget(region_box(Region.CENTER))
    root.set_end_widget(region_box(Region.RIGHT))
    return root


def build_dock(state: ShellState, model: DockModel):
    Gtk = _gtk()
    root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
    root.add_css_class("bunny-dock")
    root.set_halign(Gtk.Align.CENTER)
    for item in model.visible():
        button = Gtk.Button(label=item.name[:2].upper())
        indicator = "  ▪▪" if item.multiple_windows else ("  ▪" if item.running else "")
        accessible = f"{item.name}{' (running)' if item.running else ''}"
        button.set_tooltip_text(f"{item.name}{indicator}")
        button.update_property([Gtk.AccessibleProperty.LABEL], [accessible])
        if item.running:
            button.add_css_class("bunny-running")
        root.append(button)
    if model.overflow():
        more = Gtk.Button(label="…")
        more.set_tooltip_text(f"{len(model.overflow())} more")
        more.update_property([Gtk.AccessibleProperty.LABEL], ["More applications"])
        root.append(more)
    return root


def build_command_palette(palette: CommandPalette):
    Gtk = _gtk()
    root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    root.set_margin_top(12)
    root.set_margin_bottom(12)
    root.set_margin_start(12)
    root.set_margin_end(12)
    root.append(notice_label())

    entry = Gtk.SearchEntry()
    entry.set_placeholder_text("Search applications, windows, settings")
    root.append(entry)

    listbox = Gtk.ListBox()
    listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
    scroller = Gtk.ScrolledWindow()
    scroller.set_child(listbox)
    scroller.set_vexpand(True)
    root.append(scroller)

    def render(query: str) -> None:
        while (row := listbox.get_first_child()) is not None:
            listbox.remove(row)
        for result in palette.search(query):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            title = Gtk.Label(label=result.title, xalign=0)
            title.set_hexpand(True)
            # Every result states what it will do. This is a requirement, not a
            # nicety: "Approval required" is how the user knows a result is not
            # simply going to happen.
            behavior = Gtk.Label(label=result.behavior.value)
            behavior.add_css_class("bunny-behavior")
            row.append(title)
            row.append(behavior)
            row.update_property(
                [Gtk.AccessibleProperty.LABEL],
                [f"{result.title}. {result.subtitle}. {result.behavior.value}."],
            )
            listbox.append(row)

    entry.connect("search-changed", lambda widget: render(widget.get_text()))
    return root


def build_quick_settings(settings: QuickSettings):
    Gtk = _gtk()
    root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    for margin in ("top", "bottom", "start", "end"):
        getattr(root, f"set_margin_{margin}")(12)
    root.append(notice_label())

    for toggle in settings.toggles.values():
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        label = Gtk.Label(label=toggle.label, xalign=0)
        label.set_hexpand(True)
        row.append(label)
        if toggle.available:
            switch = Gtk.Switch()
            switch.set_active(toggle.value)
            switch.update_property([Gtk.AccessibleProperty.LABEL], [toggle.label])
            row.append(switch)
        else:
            # No switch at all for an unbacked control. A disabled switch still
            # looks like something that could be turned on.
            status = Gtk.Label(label=UNAVAILABLE_LABEL)
            status.add_css_class("bunny-unavailable")
            row.append(status)
        row.update_property(
            [Gtk.AccessibleProperty.LABEL], [f"{toggle.label}. {toggle.status_text()}."]
        )
        root.append(row)
    return root


def build_notification_center(center: NotificationCenter):
    Gtk = _gtk()
    root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    for margin in ("top", "bottom", "start", "end"):
        getattr(root, f"set_margin_{margin}")(12)
    root.append(notice_label())

    header = Gtk.Label(label="Notifications", xalign=0)
    root.append(header)

    groups = center.groups()
    if not groups:
        empty = Gtk.Label(label="No notifications")
        empty.add_css_class("bunny-unavailable")
        root.append(empty)
    for group_key, items in groups.items():
        summary = Gtk.Label(label=f"{group_key} ({len(items)})", xalign=0)
        root.append(summary)
        for notification in items:
            text = notification.summary
            if notification.action_state is not None:
                text = f"{text} — {notification.action_state.value}"
            row = Gtk.Label(label=text, xalign=0)
            row.update_property([Gtk.AccessibleProperty.LABEL], [text])
            root.append(row)
    return root


def build_character(layer, box: tuple[int, int]):
    """The bounded illustration widget.

    Returns None when nothing may be shown, so a caller cannot accidentally
    render an empty placeholder where the character would have been.
    """

    Gtk = _gtk()
    placement = layer.placement
    if placement is None:
        return None

    picture = Gtk.Picture.new_for_filename(str(layer.root / placement.asset))
    # Preserve aspect ratio; never stretch the character.
    picture.set_content_fit(Gtk.ContentFit.CONTAIN)
    picture.set_can_focus(False)
    picture.set_can_target(False)  # never blocks input
    width, height = box
    picture.set_size_request(width, height)
    # The character illustrates the panel's state; the state itself is the
    # accessible text, so a screen reader user loses nothing.
    picture.update_property([Gtk.AccessibleProperty.LABEL], [placement.semantic_description])
    return picture


def build_assistant_panel(assistant, controller, layer):
    Gtk = _gtk()
    root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    for margin in ("top", "bottom", "start", "end"):
        getattr(root, f"set_margin_{margin}")(14)
    root.append(notice_label())

    state_label = Gtk.Label(label=f"Bunny — {assistant.state.value}", xalign=0)
    state_label.update_property(
        [Gtk.AccessibleProperty.LABEL], [f"Assistant state: {assistant.state.value}"]
    )
    root.append(state_label)

    body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    panel_size = (460, 700)
    illustration = build_character(layer, controller.illustration_box(panel_size))
    if illustration is not None:
        body.append(illustration)

    content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    content.set_hexpand(True)
    for line in assistant.transcript[-8:]:
        content.append(Gtk.Label(label=line, xalign=0, wrap=True))
    entry = Gtk.Entry()
    entry.set_placeholder_text("Ask Bunny")
    entry.update_property([Gtk.AccessibleProperty.LABEL], ["Message to Bunny"])
    if assistant.state.value == "Disabled":
        entry.set_sensitive(False)
        content.append(Gtk.Label(label="Bunny is disabled", xalign=0))
    content.append(entry)
    body.append(content)
    root.append(body)
    return root


def build_approval_panel(card, layer, controller):
    Gtk = _gtk()
    root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    for margin in ("top", "bottom", "start", "end"):
        getattr(root, f"set_margin_{margin}")(16)
    root.append(notice_label())

    problems = card.validate()
    if problems:
        # A card that cannot state its blast radius is not shown at all.
        root.append(Gtk.Label(label="This approval cannot be displayed:", xalign=0))
        for problem in problems:
            root.append(Gtk.Label(label=f"• {problem}", xalign=0))
        return root

    body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
    illustration = build_character(layer, controller.illustration_box((640, 420)))
    if illustration is not None:
        body.append(illustration)

    details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    details.set_hexpand(True)
    for label, value in (
        ("Requested by", card.requester),
        ("Operation", card.operation),
        ("Affects", ", ".join(card.affected_resources)),
        ("Privilege", card.privilege.value),
        ("Network", card.network_impact),
        ("Data", card.data_impact),
        ("Reversibility", card.reversibility.value),
        ("Reason", card.reason),
        ("Expires in", f"{card.expiration_seconds}s"),
    ):
        row = Gtk.Label(label=f"{label}: {value}", xalign=0, wrap=True)
        row.update_property([Gtk.AccessibleProperty.LABEL], [f"{label}: {value}"])
        details.append(row)
    body.append(details)
    root.append(body)

    actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    actions.set_halign(Gtk.Align.END)
    for action in ("inspect", "deny", "approve"):
        button = Gtk.Button(label=action.capitalize())
        button.update_property([Gtk.AccessibleProperty.LABEL], [f"{action} {card.operation}"])
        # No default action on any card, and never on a critical one: the
        # approve button must not be reachable by a reflexive Enter.
        button.set_receives_default(False)
        actions.append(button)
    root.append(actions)
    return root


def present(component: str, child, *, application=None):
    """Show a component as its layer surface."""

    Gtk = _gtk()
    window = Gtk.Window(application=application)
    window.add_css_class("bunny-chrome")
    window.set_child(child)
    definition = spec(component)
    window.set_title(f"Bunny {definition.name} (experimental)")
    apply_layer_shell(window, component)
    window.present()
    return window
