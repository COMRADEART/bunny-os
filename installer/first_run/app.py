# SPDX-License-Identifier: GPL-3.0-or-later
"""Resumable GTK first-run presentation."""

from __future__ import annotations

from .state import FirstRunState, STEPS


COPY = {
    "welcome": ("Welcome to Bunny OS", "Everything here can be changed later. Closing this window leaves the desktop usable."),
    "language_region": ("Language and region", "Review language, date, number, and regional formats."),
    "keyboard": ("Keyboard", "Confirm the layout before entering passwords or a disk-unlock passphrase."),
    "privacy": ("Privacy", "Telemetry, remote diagnostics, screen, microphone, camera, and broad indexing start off."),
    "updates": ("Updates", "Review the beta channel and choose whether Bunny OS checks for signed updates."),
    "user_profile": ("User profile", "Review your display name and device name without embedding hardware serial numbers."),
    "bunny_introduction": ("Meet Bunny", "Bunny is optional, cannot bypass permissions, and can be configured later or used locally."),
    "provider_setup": ("Providers", "Cloud providers are optional. Any configured credential is saved through Secret Service."),
    "local_model_setup": ("Local models", "No multi-gigabyte model is downloaded automatically. Hardware estimates are not benchmarks."),
    "search_locations": ("Search locations", "Choose individual folders. The whole home directory is not selected by default."),
    "permissions_overview": ("Permissions", "Review application, portal, Bunny, and plugin permissions. Unsupported enforcement is labelled."),
    "backup_recovery": ("Backup and recovery", "Configure later, select local backup, or choose an external drive. No cloud backup is automatic."),
    "finish": ("Ready", "Open Bunny Shell, check updates, or review diagnostics and known hardware limitations."),
}


def run(state: FirstRunState) -> int:
    try:
        import gi  # type: ignore

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, Gtk  # type: ignore
    except (ImportError, ValueError) as error:
        raise RuntimeError("GTK4/libadwaita is required for first run") from error

    state.load()

    class FirstRunWindow(Adw.ApplicationWindow):
        def __init__(self, application: Adw.Application) -> None:
            super().__init__(application=application, title="Welcome to Bunny OS")
            self.set_default_size(700, 480)
            self.heading = Gtk.Label()
            self.heading.add_css_class("title-1")
            self.detail = Gtk.Label(wrap=True)
            self.detail.set_max_width_chars(62)
            self.progress = Gtk.Label()
            self.back = Gtk.Button(label="Back")
            self.back.connect("clicked", self.on_back)
            self.next = Gtk.Button(label="Next")
            self.next.add_css_class("suggested-action")
            self.next.connect("clicked", self.on_next)
            actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            actions.set_halign(Gtk.Align.END)
            actions.append(self.back)
            actions.append(self.next)
            body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
            for margin in ("top", "bottom", "start", "end"):
                getattr(body, f"set_margin_{margin}")(32)
            body.append(self.heading)
            body.append(self.detail)
            body.append(self.progress)
            body.append(actions)
            self.set_content(body)
            self.connect("close-request", self.on_close)
            self.render()

        def render(self) -> None:
            step = state.value["currentStep"]
            heading, detail = COPY[step]
            index = STEPS.index(step)
            self.heading.set_label(heading)
            self.detail.set_label(detail)
            self.progress.set_label(f"Step {index + 1} of {len(STEPS)}")
            self.back.set_sensitive(index > 0)
            self.next.set_label("Finish" if step == "finish" else "Next")

        def on_back(self, _button: object) -> None:
            index = STEPS.index(state.value["currentStep"])
            if index > 0:
                state.value["currentStep"] = STEPS[index - 1]
                state.save()
                self.render()

        def on_next(self, _button: object) -> None:
            if state.value["currentStep"] == "finish":
                state.finish()
                self.close()
                return
            state.advance()
            state.save()
            self.render()

        def on_close(self, _window: object) -> bool:
            state.save()
            return False

    application = Adw.Application(application_id="art.comrade.BunnyFirstRun")
    application.connect("activate", lambda app: FirstRunWindow(app).present())
    return int(application.run(None))

