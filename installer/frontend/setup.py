# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Bunny setup surface: the graphical installer a person actually uses.

## What this is and is not

It is a renderer. Every screen it draws is a :class:`installer.setup_view.Screen`
record built by code that reads the real authorities, and every value it styles
with comes from a resolved design-system theme. It decides two things and no
others: which screen is current, and what the person typed.

It is **not** the installer. §2 divides the responsibilities and this file is on
the presentation side of that line without exception:

* it never writes to a disk;
* it never decides whether a storage plan is safe;
* it cannot make the destructive confirmation pass — the phrase a person types
  is checked by `storage.safety.assert_confirmed` in the backend, against a
  phrase the backend re-derives from the disk it is about to erase, and a
  surface that wanted to skip that would have to send a string it cannot
  compute;
* it holds a password and a passphrase in memory for as long as it takes to
  hand them to the backend over a protected channel, and puts neither in a
  screen record, a log line, a setup-state document, or a protocol payload.

## Why the Companion is drawn in a box that is allowed to fail

§26: if the visual Companion crashes during installation, the installer must
remain usable. :class:`_CompanionView` is therefore the only widget in this file
whose construction is wrapped, and the fallback is not an empty space — it is the
same sentence in text, which is what the ``text-only`` Companion mode shows by
design. A person whose Companion died gets the experience of a person who chose
to turn the character off, which is a supported experience rather than a
degraded one.

That is also why the Companion is never asked a question. It has no signal into
the flow: `_advance` reads the screen record and the collected choices, and there
is no path by which a character that stopped drawing could stop the install.

## Accessibility is not a mode this file switches into

§8 requires accessibility settings to apply immediately, before the rest of
setup. There is no separate accessible rendering: the same widgets carry the
accessible names, the same announcement string is attached to every page as its
accessible description, and changing the text size re-renders the stylesheet for
every screen including the one already on screen. §9's "the Companion character
cannot be required to understand the installer" holds because the character
carries no information that is not also in :attr:`Screen.announcement`.

## Running it

    bunny-installer gui                     the real thing
    bunny-installer gui --screen storage    one screen, for looking at
    bunny-installer gui --self-check        no window; dumps the tree as JSON

``--self-check`` exists because the previous phase learned that a suite can go
green while the drawn surface is wrong. It builds every screen, walks the widget
tree, and reports what an assistive technology would find: the roles, the
accessible names, and which controls have none. It needs a display but no
installer backend, so it runs on any workstation with GTK.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Callable, Mapping, Sequence

from installer.setup_state import Choices
from installer.setup_view import Action, Field, Screen, Warning
from installer import setup_view
from installer.theme_css import ThemeUnavailable, render_gtk_css, resolve

__all__ = ["SetupApplication", "build_flow", "run"]


def _gtk():
    """Import GTK, or say plainly why setup cannot draw.

    Separated so that the flow construction below is importable and testable
    without a display, which is what lets `tests/installer/test_setup_surface.py`
    check the screen order and the field wiring on a machine with no GTK at all.
    """
    import gi  # type: ignore

    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk  # type: ignore

    return Gtk


# --------------------------------------------------------------------- flow


def build_flow(choices: Choices, *, context: Mapping[str, Any] | None = None
               ) -> tuple[tuple[str, Callable[[], Screen]], ...]:
    """The §4 journey, as a sequence of screen builders.

    Builders rather than screens, because a screen is a snapshot: the storage
    screen must be rebuilt after a probe, the review screen after every choice,
    and the confirmation screen names a disk that was not known when the flow
    started. Rebuilding on entry is the only arrangement in which the screen a
    person reads is the state the installer is in.

    Accessibility is second and not last. §8 is explicit that it must not be
    behind the rest of setup, and the person who most needs it is the person
    least able to read the language list to get there.
    """
    facts = dict(context or {})
    disks = facts.get("disks", ())
    findings = facts.get("findings", {})
    selected = facts.get("selectedDisk")
    app_choices = facts.get("appChoices", ())

    def review() -> Screen:
        identity = facts.get("selectedDiskIdentity", "no disk selected")
        return setup_view.review_screen(
            summary=choices.summary_rows(disk_identity=identity, erases=True),
            disk=selected,
            encrypted=choices.encryption_enabled,
        )

    return (
        ("welcome", setup_view.welcome_screen),
        ("accessibility", lambda: setup_view.accessibility_screen(current={
            "textScale": choices.text_scale,
            "highContrast": choices.high_contrast,
            "reducedMotion": choices.reduced_motion,
            "screenReader": choices.screen_reader,
            "captions": choices.captions,
            "companionTextOnly": choices.companion_mode == "text-only",
        })),
        ("language_region", lambda: setup_view.language_screen(
            detected=facts.get("detectedLocale"))),
        ("keyboard", lambda: setup_view.keyboard_screen(layout=choices.keyboard_layout)),
        ("network", lambda: setup_view.network_screen(
            connected=bool(facts.get("networkConnected")),
            networks=facts.get("networks", ()))),
        ("storage", lambda: setup_view.storage_screen(
            disks=disks, selected=selected, findings=findings)),
        ("encryption", lambda: setup_view.encryption_screen(
            offered=choices.encryption_enabled)),
        ("account", lambda: setup_view.account_screen(
            display_name=choices.display_name,
            username=choices.username,
            device_name=choices.device_name,
            errors=facts.get("accountErrors", ()))),
        ("privacy", lambda: setup_view.privacy_screen(values=choices.privacy)),
        ("appearance", lambda: setup_view.appearance_screen(
            scheme=choices.colour_scheme, accent=choices.accent)),
        ("companion_behaviour", lambda: setup_view.companion_screen(
            mode=choices.companion_mode,
            voice=choices.companion_voice,
            captions=choices.companion_captions,
            at_login=choices.companion_at_login)),
        ("applications", lambda: setup_view.apps_screen(
            activities=choices.activities, choices=app_choices)),
        ("review", review),
        # The confirmation is not in the linear flow. It is reached from review
        # and only ever with a disk in hand, which is why it takes one.
    )


# ------------------------------------------------------------------ widgets


class _CompanionView:
    """The character, and the text that stands in for it.

    §26. The character is constructed inside a try/except and the fallback is the
    text-only presentation, which is a shipped mode rather than an error state.
    :attr:`failed` records that the fallback is in use so the surface can say so
    once, in words, rather than silently looking different.
    """

    def __init__(self, Gtk, *, mode: str = "full") -> None:
        self.Gtk = Gtk
        self.mode = mode
        self.failed = False
        self.box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.box.add_css_class("bunny-setup-companion")
        self.figure = None
        if mode not in {"text-only", "off"}:
            try:
                self.figure = Gtk.DrawingArea()
                self.figure.add_css_class("bunny-setup-figure")
                self.figure.set_content_width(96)
                self.figure.set_content_height(96)
                # Decorative: the sentence beside it carries the meaning, so an
                # assistive technology should skip it rather than announce a
                # picture of a rabbit before every screen.
                self.figure.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
                self.box.append(self.figure)
            except Exception:                      # pragma: no cover - defence
                self.figure = None
                self.failed = True
        self.says = Gtk.Label(xalign=0.0)
        self.says.set_wrap(True)
        self.says.add_css_class("bunny-setup-says")
        self.box.append(self.says)

    def set_says(self, text: str) -> None:
        self.says.set_text(text)


class _ScreenView:
    """One :class:`Screen` record as widgets.

    The mapping is deliberately dull. A ``choice`` field becomes a list of
    radio-like rows, a ``toggle`` a switch with a label, a ``secret`` a password
    entry whose contents are never read except by the caller that submits them.
    Nothing here interprets the record: a screen that shows the wrong thing is a
    bug in the builder, which is testable without a display.
    """

    def __init__(self, Gtk, screen: Screen, *, on_action: Callable[[str], None],
                 on_change: Callable[[str, Any], None]) -> None:
        self.Gtk = Gtk
        self.screen = screen
        self.on_action = on_action
        self.on_change = on_change
        self.entries: dict[str, Any] = {}
        self.unnamed: list[str] = []

        self.root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.root.add_css_class("bunny-setup-column")
        self.root.set_accessible_role(Gtk.AccessibleRole.GROUP)

        # §38: the whole screen as one sentence, attached where an assistive
        # technology reads it on entry. This is the same string the story
        # harness draws and the same string tests/installer asserts on.
        self._describe(self.root, screen.announcement)

        # The role is a *construct* property. `set_accessible_role()` after
        # construction is silently ignored for a GtkLabel — the AT-SPI walk
        # showed this heading arriving as a paragraph while the call sat two
        # lines above, which is the kind of thing only reading the real bus
        # finds.
        heading = Gtk.Label(label=screen.heading, xalign=0.0,
                            accessible_role=Gtk.AccessibleRole.HEADING)
        heading.add_css_class("bunny-setup-heading")
        self.heading = heading

        for warning in screen.warnings:
            self.root.append(self._warning(warning))

        fields = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        fields.add_css_class("bunny-setup-fields")
        for field in screen.fields:
            fields.append(self._field(field))
        self.root.append(fields)

        if screen.progress:
            self.root.append(self._progress(screen.progress))

        self.root.append(self._actions(screen.actions))

        if screen.advanced:
            self.root.append(self._advanced(screen.advanced))

    # -- helpers ---------------------------------------------------------

    def _role(self, widget, name: str) -> None:
        """Give a label a role that is not ``heading``.

        **GTK 4.22 maps a plain ``Gtk.Label`` to the AT-SPI role ``heading``.**
        That was measured on this surface, not assumed: the first AT-SPI walk of
        the accessibility screen returned twenty headings, among them the help
        text under every switch, the word "Normal" beside a radio button, and the
        internal label of the Back button. To Orca's heading navigation that
        screen is twenty destinations, nineteen of which are not headings.

        Two roles fix it and they are not interchangeable:

        ``PRESENTATION``
            Removes the node from the accessibility tree entirely. Correct when
            the text is *already* carried by a control's accessible name — a
            field label whose control is named "High contrast. Stronger borders
            …" is announced twice otherwise, once as a heading and once as a
            switch.
        ``PARAGRAPH``
            Keeps the node and reports as ``comment``. Correct when the text
            stands alone: Bunny's sentence, an ``info`` row, a progress line, a
            line of technical detail. Removing those would take content away
            from the only user who cannot see it.

        The screen heading keeps ``HEADING``, and is then the one heading on the
        screen — which is what makes heading navigation worth having.
        """
        Gtk = self.Gtk
        try:
            widget.set_accessible_role(getattr(Gtk.AccessibleRole, name))
        except Exception:
            self.unnamed.append(f"role:{name}")

    def _label(self, text: str, *, role: str, css: str, wrap: bool = True):
        """A label whose accessible role is set where GTK honours it.

        See :meth:`_role` for why the role matters and the heading above for why
        it has to be a construct property.
        """
        Gtk = self.Gtk
        label = Gtk.Label(label=text, xalign=0.0,
                          accessible_role=getattr(Gtk.AccessibleRole, role))
        label.set_wrap(wrap)
        label.add_css_class(css)
        return label

    def _name(self, widget, text: str) -> None:
        """Give a widget an accessible name, and notice when that fails.

        GTK derives a name from a label for most controls, and does not for a
        control whose label is empty — which is exactly the case the previous
        phase found on a booted guest and could not see any other way. Anything
        this cannot name is recorded in :attr:`unnamed` and reported by
        ``--self-check``, so a missing name is a finding rather than a silence.
        """
        Gtk = self.Gtk
        try:
            widget.update_property([Gtk.AccessibleProperty.LABEL], [text])
        except Exception:
            self.unnamed.append(text or widget.__class__.__name__)

    def _describe(self, widget, text: str) -> None:
        Gtk = self.Gtk
        try:
            widget.update_property([Gtk.AccessibleProperty.DESCRIPTION], [text])
        except Exception:
            self.unnamed.append(f"description:{text[:32]}")

    def _warning(self, warning: Warning):
        Gtk = self.Gtk
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.add_css_class("bunny-setup-warning")
        box.add_css_class(f"bunny-setup-warning-{warning.level}")
        label = Gtk.Label(label=warning.text, xalign=0.0)
        label.set_wrap(True)
        label.add_css_class("bunny-setup-warning-text")
        # The alert is the node an assistive technology announces, so the text
        # goes on the alert. The label then repeats it visually and is removed
        # from the tree, rather than being announced a second time as a heading.
        self._name(box, f"{warning.level}: {warning.text}"
                   if warning.level == "danger" else warning.text)
        self._role(label, "PRESENTATION")
        # §11 and §40: the warning is a live region so that a change of target
        # disk is announced rather than waiting for the next focus move, and it
        # carries its severity in text so colour is never the only signal.
        try:
            box.set_accessible_role(Gtk.AccessibleRole.ALERT)
        except Exception:
            self.unnamed.append("alert-role")
        box.append(label)
        return box

    def _field(self, field: Field):
        Gtk = self.Gtk
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.add_css_class("bunny-setup-field")
        box.add_css_class(f"bunny-setup-field-{field.kind}")

        label = Gtk.Label(label=field.label, xalign=0.0)
        label.set_wrap(True)
        label.add_css_class("bunny-setup-label")
        box.append(label)

        help_label = None
        if field.help:
            help_label = Gtk.Label(label=field.help, xalign=0.0)
            help_label.set_wrap(True)
            help_label.add_css_class("bunny-setup-help")
            box.append(help_label)

        # An `info` row has no control, so its label and help *are* the content
        # and must stay readable. Every other kind puts both into the control's
        # accessible name below, so leaving them in the tree would announce each
        # field twice.
        standalone = field.kind == "info"
        self._role(label, "PARAGRAPH" if standalone else "PRESENTATION")
        if help_label is not None:
            self._role(help_label, "PARAGRAPH" if standalone else "PRESENTATION")

        if field.kind == "info":
            return box

        if field.kind == "toggle":
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            switch = Gtk.Switch()
            switch.add_css_class("bunny-setup-toggle")
            switch.set_active(bool(field.value))
            # The name is the field label plus its help, because a switch has no
            # text of its own and "on" is not a thing a person can act on.
            self._name(switch, f"{field.label}. {field.help}".strip())
            switch.connect("state-set", lambda _w, state, key=field.key:
                           (self.on_change(key, bool(state)), False)[1])
            row.append(switch)
            box.append(row)
            self.entries[field.key] = switch
            return box

        if field.kind in {"text", "secret"}:
            entry = Gtk.Entry()
            entry.add_css_class("bunny-setup-entry")
            if field.kind == "secret":
                entry.set_visibility(False)
                entry.set_input_purpose(Gtk.InputPurpose.PASSWORD)
            elif field.value:
                entry.set_text(str(field.value))
            self._name(entry, f"{field.label}. {field.help}".strip())
            entry.connect("changed", lambda w, key=field.key:
                          self.on_change(key, w.get_text()))
            box.append(entry)
            self.entries[field.key] = entry
            return box

        # choice and multi-choice
        #
        # Plain Gtk.Button, and it is an accessibility decision made twice.
        # On this GTK a CheckButton's accessible carries an Action interface
        # with zero actions, so nothing action-based — the §42 driver, or any
        # assistive tool built on AT-SPI actions — can ever select one:
        # Journey A run 8 retried its full deadline against that. The obvious
        # replacement, a grouped ToggleButton, exposes 'click' but loses its
        # accessible *name* whenever it sits deeper than a window's direct
        # child, and no ordering of label properties, tooltips or deferred
        # re-application brought it back on the real screen — all measured.
        # A plain Button is the one widget whose name and click have worked
        # in this tree on every run. Selection state is the model's: a click
        # reports the choice through on_change, the screen re-renders with
        # the selection applied, and the selected row is marked with a CSS
        # class. The note rides in the accessible description, applied a
        # main-loop cycle later because a construction-time description is
        # dropped on this GTK — also measured.
        options = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        options.add_css_class("bunny-setup-options")

        for option in field.options:
            selected = (option.value in (field.value or [])
                        if field.kind == "multi-choice"
                        else option.value == field.value)
            accessible_name = f"{option.label} — selected" if selected else option.label
            # Built like _actions builds Back and Continue — an explicit
            # PRESENTATION-role label child, never `Gtk.Button(label=...)` —
            # and that is the finding this screen paid nine VM runs for: the
            # internal label child of a constructor-labelled button defeats an
            # explicit accessible name on this GTK, and the derived name never
            # materialises for widgets nested below a window's direct children.
            # Name and note travel in ONE update_property call, because a
            # later call replaces the whole property set; naming a control and
            # then describing it leaves it nameless. All measured.
            button = Gtk.Button()
            caption = Gtk.Label(label=accessible_name, xalign=0.0)
            caption.set_wrap(True)
            self._role(caption, "PRESENTATION")
            button.set_child(caption)
            try:
                if option.note:
                    button.update_property(
                        [Gtk.AccessibleProperty.LABEL, Gtk.AccessibleProperty.DESCRIPTION],
                        [accessible_name, option.note])
                else:
                    button.update_property(
                        [Gtk.AccessibleProperty.LABEL], [accessible_name])
            except Exception:
                self.unnamed.append(accessible_name)
            button.add_css_class("bunny-setup-option")
            if selected:
                button.add_css_class("bunny-setup-option-selected")
            if not option.available:
                button.set_sensitive(False)
                button.add_css_class("bunny-setup-option-unavailable")
            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            row.append(button)
            if option.note:
                note = Gtk.Label(label=option.note, xalign=0.0)
                note.set_wrap(True)
                note.add_css_class("bunny-setup-option-note")
                # Also in the button's accessible description, just above.
                self._role(note, "PRESENTATION")
                row.append(note)
            options.append(row)
            button.connect("clicked", lambda w, key=field.key, value=option.value,
                           multi=(field.kind == "multi-choice"), was=selected:
                           self.on_change(key, (value, not was) if multi else value))
        box.append(options)
        return box

    def _progress(self, rows: Sequence[Mapping[str, Any]]):
        Gtk = self.Gtk
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.add_css_class("bunny-setup-progress")
        for row in rows:
            status = str(row.get("status", "waiting"))
            glyph = {"done": "✓", "active": "◆"}.get(status, "·")
            line = Gtk.Label(label=f"{glyph}  {row.get('label')}", xalign=0.0)
            line.add_css_class("bunny-setup-stage")
            line.add_css_class(f"bunny-setup-stage-{status}")
            # The status is in the name as a word. A glyph and a colour are the
            # two things a screen reader cannot use, and §38 requires progress to
            # be announced.
            self._name(line, f"{row.get('label')}: {status}")
            self._role(line, "PARAGRAPH")
            box.append(line)
        return box

    def _actions(self, actions: Sequence[Action]):
        Gtk = self.Gtk
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.add_css_class("bunny-setup-actions")
        box.set_halign(Gtk.Align.END)
        self.buttons: dict[str, Any] = {}
        for action in actions:
            # Built with an explicit child rather than `Gtk.Button(label=...)`,
            # so the internal label can be taken out of the accessibility tree.
            # GTK's own label child is what made every button contribute a
            # spurious heading alongside its button node.
            button = Gtk.Button()
            caption = Gtk.Label(label=action.label)
            self._role(caption, "PRESENTATION")
            button.set_child(caption)
            button.add_css_class("bunny-setup-action")
            button.add_css_class(f"bunny-setup-action-{action.tone}")
            button.set_sensitive(action.enabled)
            self._name(button, action.accessible_name)
            button.connect("clicked", lambda _w, identifier=action.id:
                           self.on_action(identifier))
            box.append(button)
            self.buttons[action.id] = button
        return box

    def _advanced(self, lines: Sequence[str]):
        Gtk = self.Gtk
        expander = Gtk.Expander(label="Installation details")
        expander.add_css_class("bunny-setup-disclosure")
        # An expander publishes a button node that GTK does not name from its
        # label, so the AT-SPI walk found a nameless control here. §5 offers
        # this as the "installation details" escape hatch and a control an Orca
        # user cannot identify is not an escape hatch.
        self._name(expander, "Installation details, technical information about this step")
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        inner.add_css_class("bunny-setup-advanced")
        for line in lines:
            item = Gtk.Label(label=line, xalign=0.0)
            item.set_wrap(True)
            item.add_css_class("bunny-setup-advanced-line")
            self._role(item, "PARAGRAPH")
            inner.append(item)
        expander.set_child(inner)
        return expander

    # -- introspection ---------------------------------------------------

    def tree(self) -> dict[str, Any]:
        """What an assistive technology would find. Used by ``--self-check``."""
        return {
            "key": self.screen.key,
            "heading": self.screen.heading,
            "announcement": self.screen.announcement,
            "fields": [f"{item.kind}:{item.key}" for item in self.screen.fields],
            "warnings": [f"{item.level}:{item.text[:60]}" for item in self.screen.warnings],
            "actions": [
                {"id": item.id, "label": item.label, "name": item.accessible_name,
                 "enabled": item.enabled}
                for item in self.screen.actions
            ],
            "unnamed": list(self.unnamed),
        }


# -------------------------------------------------------------- application


class SetupApplication:
    """The window, the flow, and the theme.

    Constructed with an already-imported Gtk so that the class is testable with
    a stub, which is how the flow order and the accessibility re-render are
    checked without a display.
    """

    def __init__(self, Gtk, *, choices: Choices | None = None,
                 context: Mapping[str, Any] | None = None) -> None:
        self.Gtk = Gtk
        self.choices = choices or Choices()
        self.context = dict(context or {})
        self.flow = build_flow(self.choices, context=self.context)
        self.index = 0
        #: A screen outside the linear flow: the destructive confirmation, the
        #: progress screen, failure, or completion. When set it is what renders,
        #: and the flow index cannot reach back past it.
        self.terminal: Screen | None = None
        #: The `companion.presentation` phase, derived from installer state by
        #: `backend.progress.companion_phase_for` and never chosen here.
        self.companion_phase = "idle"
        self.provider = None
        self.window = None
        self.view: _ScreenView | None = None
        self.companion: _CompanionView | None = None
        self.secrets: dict[str, str] = {}

    # -- theme -----------------------------------------------------------

    def apply_theme(self) -> None:
        """Render the stylesheet for the current accessibility choices.

        Called on construction and after every accessibility change, which is
        §8's "changes must affect the installer immediately" in one method. A
        theme the design system cannot resolve raises rather than falling back:
        a person who chose 200 % text and silently got 100 % has been told a
        lie by the surface that promised otherwise.
        """
        Gtk = self.Gtk
        from gi.repository import Gdk  # type: ignore

        theme = resolve(**self.choices.theme_options())
        css = render_gtk_css(theme)
        if self.provider is None:
            self.provider = Gtk.CssProvider()
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(), self.provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        # GTK 4.12 renamed this; both spellings are live in the field.
        if hasattr(self.provider, "load_from_string"):
            self.provider.load_from_string(css)
        else:                                        # pragma: no cover - old GTK
            self.provider.load_from_data(css.encode("utf-8"))

    def _name_scroller(self, scroller, text: str) -> None:
        """Name the focusable node inside a ScrolledWindow, not the wrapper."""
        Gtk = self.Gtk
        targets = [scroller]
        child = scroller.get_child()
        if child is not None:
            targets.append(child)
        for target in targets:
            try:
                target.update_property([Gtk.AccessibleProperty.LABEL], [text])
            except Exception:
                continue

    # -- flow ------------------------------------------------------------

    def current_screen(self) -> Screen:
        """The screen to draw: the terminal one if setup has left the flow.

        The linear flow ends at Review. Everything after it — the destructive
        confirmation, the progress screen, failure, completion — is *not* a step
        a person walks back and forth through, and modelling it as one would put
        a Back button beside a running installation.

        So those four live in :attr:`terminal`, which the flow index cannot
        reach. Once an install has started there is no index arithmetic that
        returns to the account screen.
        """
        if self.terminal is not None:
            return self.terminal
        return self.flow[self.index][1]()

    def on_change(self, key: str, value: Any) -> None:
        """Record a choice. Secrets go to a separate dict that is never saved."""
        if key in {"password", "passwordAgain", "passphrase", "passphraseAgain", "phrase"}:
            self.secrets[key] = value
            # The confirmation phrase gates its own button, and only that button.
            if key == "phrase":
                self._refresh_confirm_button()
            return
        if key == "targetDisk":
            # The choice this whole surface exists to collect, and until this
            # branch existed nothing collected it: on_change dropped the key,
            # context["selectedDisk"] stayed None from construction, and both
            # "Install Bunny OS" and "confirm" silently returned on their
            # disk-is-None guards. Every widget state was correct and the flow
            # never learned. Found by the §42 driver, which selects a disk the
            # way a person does. The flow is rebuilt because its screen
            # builders capture the facts at build time — an updated context
            # alone leaves review naming "no disk selected".
            chosen = next((disk for disk in self.context.get("disks", ())
                           if getattr(disk, "id", None) == value), None)
            if chosen is not None:
                self.context["selectedDisk"] = chosen
                identity = self.context.get("identityFor")
                if callable(identity):
                    self.context["selectedDiskIdentity"] = identity(chosen)
                self.flow = build_flow(self.choices, context=self.context)
                self.render()
            return
        if key == "enabled":
            # The toggle is the decision, and the passphrase fields exist only
            # inside it. Re-rendering here is what makes switching it on
            # conjure the fields and switching it off remove them — run 18
            # typed a passphrase into fields drawn beside an off toggle, the
            # submit path discarded the secret because the recorded choice
            # said off, and the installation came out unencrypted.
            self.choices.encryption_enabled = bool(value)
            self.render()
            return
        setters = {
            "textScale": lambda v: setattr(self.choices, "text_scale", float(v)),
            "highContrast": lambda v: setattr(self.choices, "high_contrast", bool(v)),
            "reducedMotion": lambda v: setattr(self.choices, "reduced_motion", bool(v)),
            "screenReader": lambda v: setattr(self.choices, "screen_reader", bool(v)),
            "captions": lambda v: setattr(self.choices, "captions", bool(v)),
            "language": lambda v: setattr(self.choices, "language", str(v)),
            "region": lambda v: setattr(self.choices, "region", str(v)),
            "timezone": lambda v: setattr(self.choices, "timezone", str(v)),
            "layout": lambda v: setattr(self.choices, "keyboard_layout", str(v)),
            "displayName": lambda v: setattr(self.choices, "display_name", str(v)),
            "username": lambda v: setattr(self.choices, "username", str(v)),
            "deviceName": lambda v: setattr(self.choices, "device_name", str(v)),
            "scheme": lambda v: setattr(self.choices, "colour_scheme", str(v)),
            "accent": lambda v: setattr(self.choices, "accent", str(v)),
            "wallpaper": lambda v: setattr(self.choices, "wallpaper", str(v)),
            "mode": lambda v: setattr(self.choices, "companion_mode", str(v)),
            "voice": lambda v: setattr(self.choices, "companion_voice", bool(v)),
            "atLogin": lambda v: setattr(self.choices, "companion_at_login", bool(v)),
        }
        if key in setters:
            setters[key](value)
        elif key in self.choices.privacy:
            self.choices.privacy[key] = bool(value)
        elif key == "activities" and isinstance(value, tuple):
            name, on = value
            if on and name not in self.choices.activities:
                self.choices.activities.append(name)
            elif not on and name in self.choices.activities:
                self.choices.activities.remove(name)
        elif key == "applications" and isinstance(value, tuple):
            name, on = value
            if on and name not in self.choices.applications:
                self.choices.applications.append(name)
            elif not on and name in self.choices.applications:
                self.choices.applications.remove(name)

        # An accessibility change re-renders now, on the screen already drawn.
        if key in {"textScale", "highContrast", "reducedMotion"}:
            self.apply_theme()
        if key == "companionTextOnly":
            self.choices.companion_mode = "text-only" if value else "full"
            self.render()

    def _refresh_confirm_button(self) -> None:
        """Enable the destructive button only when the typed phrase matches.

        This is a *convenience*, not a control. The backend re-derives the phrase
        from the disk in the validated plan and compares it in
        `storage.safety.assert_confirmed`; a surface that enabled this button
        wrongly would produce a request the backend refuses. §12's authority sits
        there, and this is only the reason the button looks disabled.
        """
        from installer.storage.safety import confirmation_phrase

        disk = self.context.get("selectedDisk")
        view = self.view
        if disk is None or view is None or not hasattr(view, "buttons"):
            return
        button = view.buttons.get("confirm")
        if button is not None:
            button.set_sensitive(self.secrets.get("phrase", "") == confirmation_phrase(disk))

    def on_action(self, identifier: str) -> None:
        disk = self.context.get("selectedDisk")

        if identifier == "back":
            # Back out of the confirmation, never out of a running install.
            if self.terminal is not None and self.terminal.key == "confirm_erase":
                self.terminal = None
            elif self.terminal is None:
                self.index = max(0, self.index - 1)
            else:
                return
        elif identifier in {"next", "start", "skip"}:
            self.index = min(len(self.flow) - 1, self.index + 1)
        elif identifier == "accessibility":
            self.index = next(i for i, (key, _) in enumerate(self.flow)
                              if key == "accessibility")
        elif identifier == "install":
            # §12: Review does not start an installation. It leads to the one
            # screen whose authority is `user`, and that screen is not passable
            # without the typed phrase.
            if disk is None:
                return
            self.secrets.pop("phrase", None)
            self.terminal = setup_view.confirm_erase_screen(
                disk=disk, encrypted=self.choices.encryption_enabled)
        elif identifier == "confirm":
            if disk is None:
                return
            self.begin_installation()
            return
        elif identifier == "retry":
            # §47: retry returns to Review rather than repeating the write. The
            # plan is re-validated by the backend from there, because the disk
            # may not be in the state the previous plan assumed.
            self.terminal = None
            self.index = next(i for i, (key, _) in enumerate(self.flow) if key == "review")
        elif identifier in {"restart", "quit", "details", "advanced", "tour"}:
            # Handled by the host session, not by the flow.
            return
        else:
            return
        self.render()

    # -- installation ----------------------------------------------------

    def begin_installation(self) -> None:
        """Hand the confirmed plan to the backend and follow what it reports.

        This method contains no storage logic at all, which is the point of §2:
        it submits, and then it renders whatever comes back. The typed phrase is
        sent for the backend to check against the disk in the *validated plan* —
        `storage.safety.assert_confirmed` re-derives it there — so a surface bug
        that enabled the button early produces a refusal rather than an erase.
        """
        from installer.backend.progress import companion_phase_for, progress_rows

        submit = self.context.get("submit")
        if submit is None:
            self.terminal = setup_view.failure_screen(
                headline="This installer cannot write to a disk.",
                explanation="No installation backend is connected, so nothing was "
                            "done. This build can show setup but not perform it.",
                stage_key="Preparing", wrote_to_disk=False)
            self.render()
            return

        def on_state(status: str, stage: str, detail: str, wrote: bool) -> None:
            if status == "failed":
                self.terminal = setup_view.failure_screen(
                    headline=detail or "The installation stopped.",
                    explanation=self.context.get("failureExplanation", ""),
                    stage_key=stage, wrote_to_disk=wrote,
                    diagnostics_path=str(self.context.get("diagnosticsPath", "")))
            elif status == "complete":
                self.terminal = setup_view.complete_screen(name=self.choices.display_name)
            else:
                self.terminal = setup_view.installing_screen(
                    stages=progress_rows(stage), current=None, detail=detail)
                self.companion_phase = companion_phase_for(status, stage)
            self.render()

        self.terminal = setup_view.installing_screen(
            stages=progress_rows("Preparing"), current="prepare",
            detail="Checking the plan")
        self.render()
        submit(confirmation=self.secrets.get("phrase", ""), on_state=on_state)

    # -- rendering -------------------------------------------------------

    def render(self) -> None:
        Gtk = self.Gtk
        screen = self.current_screen()
        self.companion = _CompanionView(Gtk, mode=self.choices.companion_mode)
        self.companion.set_says(screen.says)
        self.view = _ScreenView(Gtk, screen, on_action=self.on_action,
                                on_change=self.on_change)

        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        page.add_css_class("bunny-setup")
        page.append(self.companion.box)
        page.append(self.view.heading)
        page.append(self.view.root)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)
        # GTK makes the scroll viewport focusable so that a keyboard can scroll
        # it — which matters most at 200 % text, where scrolling is how a
        # critical control stays reachable (§39). It is therefore a stop in the
        # tab order, and a stop with nothing to say is a stop an Orca user
        # cannot identify.
        #
        # The name has to go on the *viewport*, not on the ScrolledWindow.
        # GTK wraps a non-scrollable child in a GtkViewport, and it is the
        # viewport that takes focus; naming the outer widget left the inner one
        # nameless on all thirteen screens, which is what the AT-SPI walk kept
        # reporting while the property was plainly being set two lines up.
        # After set_child, necessarily: GTK creates the viewport when the child
        # is set, so naming before it exists names nothing. That off-by-one was
        # invisible from the code — the property call succeeded every time — and
        # only the AT-SPI walk still reporting a nameless scroll pane on all
        # thirteen screens showed it.
        scroller.set_child(page)
        self._name_scroller(scroller, "Setup steps")
        if self.window is not None:
            self.window.set_child(scroller)
            # §37: focus lands on the first control of the new screen rather
            # than staying where the last one was, so keyboard-only navigation
            # never has to hunt for where it is.
            first = next(iter(self.view.entries.values()), None) \
                or next(iter(self.view.buttons.values()), None)
            if first is not None:
                first.grab_focus()

    def build(self, application) -> None:
        Gtk = self.Gtk
        self.window = Gtk.ApplicationWindow(application=application)
        self.window.set_title("Set up Bunny OS")
        self.window.set_default_size(1024, 768)
        self.window.add_css_class("bunny-setup")
        self.apply_theme()
        self.render()
        self.window.present()

    # -- introspection ---------------------------------------------------

    def self_check(self) -> dict[str, Any]:
        """Build every screen and report what an assistive technology finds."""
        screens = []
        for key, builder in self.flow:
            screen = builder()
            view = _ScreenView(self.Gtk, screen,
                               on_action=lambda _i: None, on_change=lambda _k, _v: None)
            record = view.tree()
            record["flowKey"] = key
            screens.append(record)
        return {
            "schemaVersion": 1,
            "screens": screens,
            "unnamedTotal": sum(len(item["unnamed"]) for item in screens),
        }


def _installer_context(choices: Choices) -> dict[str, Any]:
    """Everything the flow needs that comes from outside the surface.

    Storage is probed through the **backend**, never directly. The surface has
    no capability to read a block device and should not acquire one to draw a
    list: the disks it shows are the disks the thing that will erase one can
    see, which is the only list whose absence of an entry means anything.

    A machine with no backend gets an empty context and the screens that say so.
    That is the development case and it is also §26's argument generalised — a
    window explaining why beats a session with nothing in it.
    """
    from installer.frontend.client import InstallerRefused, connect
    from installer.storage.models import DiskInfo, ExistingOS, PartitionInfo
    from installer.storage.safety import assess_target, disk_identity

    client = connect()
    if client is None:
        return {}

    context: dict[str, Any] = {"client": client}
    try:
        context["backend"] = dict(client.initialize())
        probed = client.probe()
    except (InstallerRefused, OSError) as error:
        context["backendError"] = str(error)
        return context

    disks: list[DiskInfo] = []
    for record in probed.get("disks", []):
        disks.append(DiskInfo(
            id=record["id"], devicePath=record["devicePath"],
            sizeBytes=record["sizeBytes"],
            logicalSectorSize=record.get("logicalSectorSize", 512),
            physicalSectorSize=record.get("physicalSectorSize", 512),
            removable=record.get("removable", False),
            readOnly=record.get("readOnly", False),
            model=record.get("model"),
            serialRedacted=record.get("serialRedacted"),
            rotational=record.get("rotational"),
            transport=record.get("transport"),
            partitions=tuple(PartitionInfo(**{
                key: (tuple(value) if key == "mountPoints" else value)
                for key, value in item.items()
            }) for item in record.get("partitions", [])),
            existingOperatingSystems=tuple(
                ExistingOS(**item) for item in record.get("existingOperatingSystems", [])),
            installationMedia=record.get("installationMedia", False),
            storageStack=record.get("storageStack", "plain"),
        ))

    context["disks"] = tuple(disks)
    context["findings"] = {
        disk.id: assess_target(disk, mode="erase_disk") for disk in disks
    }
    # Nothing is preselected. §11 asks for a conservative storage UI, and a
    # preselected disk is one a hurried person confirms without reading.
    context["selectedDisk"] = None
    context["selectedDiskIdentity"] = "no disk selected"
    context["identityFor"] = disk_identity
    return context


def _make_submit(application: "SetupApplication", client) -> Callable[..., None]:
    """The wire from "Erase" to the backend — built only when a backend exists.

    Until this function existed, `_installer_context` supplied everything the
    flow reads except the one callable `begin_installation` needs, so every
    confirmed installation ended at "This installer cannot write to a disk."
    The §42 driver walked all fifteen stages to find that.

    The conversation runs on a worker thread: the backend serves one blocking
    conversation and the install is its response, and a GTK main loop that
    waited on it could not repaint the installing screen a person is watching.
    State lands back on the main loop through ``GLib.idle_add``.
    """
    import secrets as secret_tokens
    import threading

    def submit(*, confirmation: str, on_state) -> None:
        from gi.repository import GLib  # type: ignore

        def deliver(status: str, stage: str, detail: str, wrote: bool) -> None:
            def emit() -> bool:
                on_state(status, stage, detail, wrote)
                return False
            GLib.idle_add(emit)

        disk = application.context.get("selectedDisk")
        choices = application.choices
        password = str(application.secrets.get("password", ""))
        passphrase = (str(application.secrets.get("passphrase", ""))
                      if choices.encryption_enabled else "")
        if disk is None:
            deliver("failed", "Preparing", "No disk is selected.", False)
            return
        if not password:
            deliver("failed", "Preparing", "The account password was never captured.", False)
            return
        if choices.encryption_enabled and not passphrase:
            deliver("failed", "Preparing", "The encryption passphrase was never captured.", False)
            return

        def work() -> None:
            from installer.frontend.client import InstallerRefused
            from installer.storage.planning import automatic_plan

            try:
                plan = automatic_plan(disk, mode="erase_disk",
                                      encryption=choices.encryption_enabled)
                # The planner records more than the plan schema admits.
                plan.pop("operationsAreReversibleAfterWrite", None)
                plan.pop("warnings", None)
                plan["installationId"] = client.installation_id
                password_reference = "installer-secret:" + secret_tokens.token_urlsafe(24)
                plan["user"] = {
                    "username": choices.username,
                    "displayName": choices.display_name,
                    "passwordSecretRef": password_reference,
                    "administrator": True,
                    "autologin": False,
                    "groups": [],
                }
                plan["locale"] = {
                    "language": choices.language,
                    "keyboardLayout": choices.keyboard_layout,
                    "timezone": choices.timezone,
                }
                device_name = (choices.device_name or "").strip()
                plan["network"] = {"hostname": device_name} if device_name else {}
                plan["recovery"] = {}
                plan["applicationProfile"] = {}

                outcome = client.validate(plan)
                if not outcome.get("valid"):
                    deliver("failed", "Validating storage",
                            "; ".join(outcome.get("errors", ())) or "The plan was refused.",
                            False)
                    return

                secret_values = {password_reference: password}
                passphrase_reference = None
                if passphrase:
                    passphrase_reference = ("installer-secret:"
                                            + secret_tokens.token_urlsafe(24))
                    secret_values[passphrase_reference] = passphrase

                result = client.start(
                    acknowledgement=confirmation,
                    second_confirmation=True,
                    recovery_key_confirmed=bool(choices.encryption_enabled),
                    passphrase_secret_ref=passphrase_reference,
                    secret_values=secret_values,
                )
            except InstallerRefused as error:
                deliver("failed", "Preparing", str(error), False)
                return
            except (OSError, ValueError) as error:
                deliver("failed", "Preparing",
                        f"The installer backend could not be reached: {error}", False)
                return

            status = str(result.get("status", ""))
            if status == "complete":
                deliver("complete", "Complete", "", True)
            else:
                deliver("failed", str(result.get("stage", "Preparing")),
                        str(result.get("failure") or result.get("currentOperation")
                            or "The installation stopped."),
                        bool(result.get("destructiveWriteStarted")))

        threading.Thread(target=work, daemon=True, name="bunny-install-submit").start()

    return submit


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bunny-setup", description="Bunny OS setup")
    parser.add_argument("--screen", help="start on one screen, by flow key")
    parser.add_argument("--self-check", action="store_true",
                        help="build every screen, dump the accessibility tree, exit")
    parser.add_argument("--offline", action="store_true",
                        help="do not contact the installer backend; for looking at screens")
    parser.add_argument("--text-scale", type=float, default=1.0)
    parser.add_argument("--high-contrast", action="store_true")
    parser.add_argument("--reduced-motion", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        Gtk = _gtk()
    except (ImportError, ValueError) as error:
        raise RuntimeError("GTK4 is required for the Bunny setup surface") from error

    choices = Choices(
        text_scale=args.text_scale,
        high_contrast=args.high_contrast,
        reduced_motion=args.reduced_motion,
    )
    errors = choices.validate()
    if errors:
        sys.stderr.write("; ".join(errors) + "\n")
        return 2

    context = {} if args.offline else _installer_context(choices)
    application_state = SetupApplication(Gtk, choices=choices, context=context)
    # Wired after construction because the submit closure reads the
    # application's own context and secrets at call time — the disk a person
    # selects and the password they type do not exist yet.
    client = context.get("client")
    if client is not None:
        application_state.context["submit"] = _make_submit(application_state, client)

    if args.self_check:
        sys.stdout.write(json.dumps(application_state.self_check(), indent=1) + "\n")
        return 0

    if args.screen:
        keys = [key for key, _ in application_state.flow]
        if args.screen not in keys:
            sys.stderr.write(f"no such screen: {args.screen}; have {', '.join(keys)}\n")
            return 2
        application_state.index = keys.index(args.screen)

    application = Gtk.Application(application_id="art.comrade.BunnySetup")
    application.connect("activate", application_state.build)
    return int(application.run(None))
