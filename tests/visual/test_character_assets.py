from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import struct
import unittest

from tests.support import ROOT


ASSET_DIR = ROOT / "visual/assets/character/bunny-guide/v1"
EXPECTED_STATES = {
    "idle-neutral",
    "welcome-wave",
    "typing",
    "pointing-at-interface",
    "thinking",
    "explaining",
    "requesting-approval",
    "task-running",
    "task-completed",
    "warning",
    "error",
    "offline",
    "privacy-mode",
    "celebrating",
}


class CharacterAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads((ASSET_DIR / "manifest.json").read_text(encoding="utf-8"))

    def test_manifest_has_the_complete_unique_state_family(self) -> None:
        states = self.manifest["states"]
        slugs = [state["slug"] for state in states]
        self.assertEqual(set(slugs), EXPECTED_STATES)
        self.assertEqual(len(slugs), len(set(slugs)))
        self.assertEqual(self.manifest["rules"]["charactersPerAsset"], 1)
        self.assertFalse(self.manifest["rules"]["generatedTextAllowed"])

    def test_pngs_are_rgba_at_the_canonical_canvas_size_and_match_hashes(self) -> None:
        for state in self.manifest["states"]:
            with self.subTest(state=state["slug"]):
                path = ASSET_DIR / state["file"]
                payload = path.read_bytes()
                self.assertGreater(len(payload), 100_000)
                self.assertEqual(payload[:8], b"\x89PNG\r\n\x1a\n")
                width, height, bit_depth, color_type = struct.unpack(">IIBB", payload[16:26])
                self.assertEqual((width, height), (1024, 1536))
                self.assertEqual(bit_depth, 8)
                self.assertEqual(color_type, 6, "PNG must have RGBA color type")
                self.assertEqual(sha256(payload).hexdigest(), state["sha256"])

    def test_character_contract_keeps_operational_ui_bounded(self) -> None:
        guide = (ROOT / "visual/assets/character/CHARACTER_GUIDE.md").read_text(encoding="utf-8")
        self.assertIn("exactly one full-body character", guide)
        self.assertIn("Do not make the guide a permanent desktop decoration", guide)
        self.assertIn("never substitutes for approval controls", guide)

    def test_character_family_is_staged_by_the_visual_package(self) -> None:
        tool = (ROOT / "visual/tools/visual.py").read_text(encoding="utf-8")
        self.assertIn('visual/assets/character", STAGE / "usr/share/bunny-visual-v1/character', tool)


if __name__ == "__main__":
    unittest.main()
