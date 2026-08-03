from __future__ import annotations

import json
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

from tests.support import ROOT


V2 = ROOT / "visual-v2"
SHELL = ROOT / "shell/bunny-desktop-v2"


class VisualV2ArchitectureTests(unittest.TestCase):
    def test_branch_policy_is_explicitly_non_release(self) -> None:
        policy = json.loads((V2 / "branch-policy.json").read_text(encoding="utf-8"))
        self.assertEqual(policy["branch"], "visual/bunny-desktop-v2-dual-mode")
        self.assertFalse(policy["defaultSessionChanged"])
        self.assertFalse(policy["qualificationTargetsChanged"])
        self.assertFalse(policy["releaseGatesChanged"])
        self.assertFalse(policy["productionKeysAllowed"])
        self.assertFalse(policy["publishableImage"])

    def test_preview_session_is_additive_and_not_default(self) -> None:
        desktop = (ROOT / "sessions/bunny-desktop-preview.desktop").read_text(encoding="utf-8")
        mode = json.loads((ROOT / "sessions/bunny-desktop-preview.json").read_text(encoding="utf-8"))
        self.assertIn("Name=Bunny Desktop Preview", desktop)
        self.assertIn("X-Bunny-Default-Session=false", desktop)
        self.assertEqual(mode["parentMode"], "user")
        self.assertEqual(mode["enabledExtensions"], ["bunny-desktop-v2@bunny-os.org"])
        self.assertFalse((ROOT / "sessions/gnome.desktop").exists())

    def test_v2_schema_is_independent_closed_and_defaults_to_regular(self) -> None:
        tree = ET.parse(SHELL / "schemas/org.bunnyos.desktop.visual-v2.gschema.xml")
        schema = tree.getroot().find("schema")
        self.assertEqual(schema.attrib["id"], "org.bunnyos.desktop.visual-v2")
        keys = {element.attrib["name"]: element for element in schema.findall("key")}
        self.assertEqual(keys["visual-mode"].findtext("default"), "'regular'")
        choices = {item.attrib["value"] for item in keys["visual-mode"].find("choices")}
        self.assertEqual(choices, {"regular", "character"})
        for name in ("layout-mode", "character-enabled", "reduced-motion", "panel-transparency", "toggle-visual-mode"):
            self.assertIn(name, keys)

    def test_mode_switch_is_live_and_shared_actions_are_mode_independent(self) -> None:
        controller = (SHELL / "controllers/modeController.js").read_text(encoding="utf-8")
        actions = (SHELL / "services/actionRegistry.js").read_text(encoding="utf-8")
        self.assertIn("setVisualMode(mode)", controller)
        self.assertIn("component.applyPresentation", controller)
        self.assertNotIn("gnome-session", controller)
        self.assertNotIn("visualMode === 'character' ? commandActions", actions)
        for label in ("Switch to Character Mode", "Switch to Regular Mode", "Open Approval Center"):
            self.assertIn(label, actions)

    def test_extension_is_preview_scoped(self) -> None:
        extension = (SHELL / "extension.js").read_text(encoding="utf-8")
        launcher = (ROOT / "sessions/bunny-desktop-preview-session").read_text(encoding="utf-8")
        self.assertIn("BUNNY_VISUAL_V2_PREVIEW", extension)
        self.assertIn("BUNNY_VISUAL_V2_PREVIEW=1", launcher)
        self.assertIn("exec gnome-session --session=bunny-desktop-preview", launcher)


if __name__ == "__main__":
    unittest.main()
