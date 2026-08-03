from __future__ import annotations

import json
import unittest
import xml.etree.ElementTree as ET

from tests.support import ROOT


EXTENSION = ROOT / "shell/bunny-shell-extension"


class DesktopFrameTests(unittest.TestCase):
    def test_extension_is_preview_scoped(self) -> None:
        metadata = json.loads((EXTENSION / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["uuid"], "bunny-desktop-v1@bunny-os.org")
        source = (EXTENSION / "extension.js").read_text(encoding="utf-8")
        self.assertIn("BUNNY_VISUAL_PREVIEW", source)
        self.assertIn("refused to start outside", source)

    def test_frame_components_are_present(self) -> None:
        for component in ("topBar.js", "dock.js", "overview.js", "quickSettings.js", "notificationCenter.js"):
            self.assertTrue((EXTENSION / "components" / component).is_file(), component)

    def test_state_updates_are_event_driven(self) -> None:
        source = (EXTENSION / "services/state.js").read_text(encoding="utf-8")
        self.assertIn("monitor_file", source)
        self.assertNotIn("timeout_add", source)
        self.assertNotIn("fetch(", source)

    def test_dock_supports_keyboard_overflow_drag_and_monitors(self) -> None:
        source = (EXTENSION / "components/dock.js").read_text(encoding="utf-8")
        for feature in ("can_focus: true", "MAX_VISIBLE_APPS", "makeDraggable", "acceptDrop", "monitors-changed"):
            self.assertIn(feature, source)

    def test_schema_defines_preview_modes_and_shortcuts(self) -> None:
        tree = ET.parse(EXTENSION / "schemas/org.bunnyos.desktop.visual-v1.gschema.xml")
        keys = {element.attrib["name"] for element in tree.findall(".//key")}
        self.assertTrue({"layout-mode", "theme", "dock-auto-hide", "open-command-palette"}.issubset(keys))

    def test_notifications_retain_truthful_action_states(self) -> None:
        source = (EXTENSION / "components/notificationCenter.js").read_text(encoding="utf-8")
        for state in ("proposal", "waiting for approval", "running", "completed", "failed", "rolled back"):
            self.assertIn(state, source)


if __name__ == "__main__":
    unittest.main()
