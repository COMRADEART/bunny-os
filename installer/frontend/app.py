"""Accessible live-session landing surface.

Anaconda Web UI remains the selected graphical installer.  This Bunny-owned
surface deliberately contains no root command launcher; it gives users clear
entry points and exposes degraded status when the installer service is absent.
"""

from __future__ import annotations


def run() -> int:
    try:
        import gi  # type: ignore

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, Gtk  # type: ignore
    except (ImportError, ValueError) as error:
        raise RuntimeError("GTK4/libadwaita is required for the live installer UI") from error

    class LiveWindow(Adw.ApplicationWindow):
        def __init__(self, application: Adw.Application) -> None:
            super().__init__(application=application, title="Bunny OS")
            self.set_default_size(720, 520)
            header = Adw.HeaderBar()
            title = Gtk.Label(label="Try or install Bunny OS")
            title.add_css_class("title-1")
            description = Gtk.Label(label="Installation is offline-capable. Storage changes are shown before they are made.")
            description.set_wrap(True)
            description.set_accessible_role(Gtk.AccessibleRole.DESCRIPTION)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
            box.set_margin_top(24)
            box.set_margin_bottom(24)
            box.set_margin_start(24)
            box.set_margin_end(24)
            box.append(title)
            box.append(description)
            for label, detail in (
                ("Try Bunny OS", "Use the live desktop without writing internal disks."),
                ("Install Bunny OS", "Open the Anaconda installer and review the target and operation plan."),
                ("Recovery tools", "Use Bunny-independent recovery and rollback tools."),
                ("Hardware diagnostics", "Review compatibility evidence and limitations."),
            ):
                button = Gtk.Button(label=label)
                button.set_tooltip_text(detail)
                button.set_hexpand(True)
                button.set_accessible_role(Gtk.AccessibleRole.BUTTON)
                box.append(button)
            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            content.append(header)
            content.append(box)
            self.set_content(content)

    application = Adw.Application(application_id="art.comrade.BunnyInstaller")
    application.connect("activate", lambda app: LiveWindow(app).present())
    return int(application.run(None))

