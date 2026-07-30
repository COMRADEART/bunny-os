# SPDX-License-Identifier: GPL-3.0-or-later
"""Nautilus menu provider using explicit selections and Bunny URI handoff."""

try:
    from gi.repository import GObject, Nautilus
except (ImportError, ValueError):
    GObject = object
    Nautilus = None


if Nautilus is not None:
    class BunnyMenuProvider(GObject.GObject, Nautilus.MenuProvider):
        ACTIONS = (
            ("Ask", "Ask Bunny about this file"),
            ("Summarise", "Summarise with Bunny"),
            ("Workspace", "Open in Bunny workspace"),
            ("Provenance", "Show provenance"),
            ("Checkpoint", "Create checkpoint before changes"),
        )

        def get_file_items(self, files):
            if not files or len(files) > 20:
                return []
            uris = [item.get_uri() for item in files]
            if any(not uri.startswith("file://") for uri in uris):
                return []
            items = []
            for suffix, label in self.ACTIONS:
                item = Nautilus.MenuItem(name=f"Bunny::{suffix}", label=label, tip="Open an explicit Bunny request; no file is uploaded automatically")
                item.connect("activate", self._activate, suffix.casefold(), uris)
                items.append(item)
            return items

        @staticmethod
        def _activate(_item, action, uris):
            # Gio's URI handler hands the explicit selection to Bunny Desktop;
            # Bunny permissions and provider disclosure remain authoritative.
            from gi.repository import Gio, GLib
            escaped = GLib.uri_escape_string("\n".join(uris), None, True)
            Gio.AppInfo.launch_default_for_uri(f"bunny://files/{action}?selection={escaped}", None)
