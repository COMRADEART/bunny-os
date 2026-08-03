from __future__ import annotations

from hashlib import sha256
import json
import struct
import unittest

from tests.support import ROOT


SHELL = ROOT / "shell/bunny-desktop-v2"
ASSETS = ROOT / "visual-v2/assets/character/bunny-guide/v1"


class DualModeTests(unittest.TestCase):
    def test_regular_mode_reserves_no_character_space_or_asset(self) -> None:
        assistant = (SHELL / "components/assistantPanel.js").read_text(encoding="utf-8")
        illustration = (SHELL / "components/characterIllustration.js").read_text(encoding="utf-8")
        self.assertIn("this._presentation?.visualMode === 'character'", assistant)
        self.assertIn("Recent activity", assistant)
        self.assertIn("System context", assistant)
        self.assertIn("Suggested actions", assistant)
        self.assertIn("this._loader = null", illustration)
        self.assertIn("this._loader ??= new CharacterAssetLoader", illustration)
        self.assertIn("if (this._character.active)", assistant)

    def test_character_pose_truth_guards_prevent_early_success(self) -> None:
        state = (SHELL / "services/characterState.js").read_text(encoding="utf-8")
        self.assertIn("state.resultConfirmed === true ? 'task-completed' : 'task-running'", state)
        self.assertIn("state.milestoneConfirmed === true ? 'celebrating' : 'task-running'", state)
        self.assertIn("state.approvals.length ? 'requesting-approval' : 'thinking'", state)

    def test_character_is_single_decorative_bounded_and_responsive(self) -> None:
        source = (SHELL / "components/characterIllustration.js").read_text(encoding="utf-8")
        self.assertIn("this.actor.set_child(image)", source)
        self.assertNotIn("this.actor.add_child(image)", source)
        self.assertIn("Atk.Role.REDUNDANT_OBJECT", source)
        self.assertIn("!presentation.compact", source)
        self.assertIn("!presentation.focus", source)
        self.assertIn("characterMaximumPanelRatio", source)
        self.assertIn("descriptionForPose(pose)", source)

    def test_loader_is_lazy_and_cache_is_bounded(self) -> None:
        loader = (SHELL / "services/characterAssetLoader.js").read_text(encoding="utf-8")
        self.assertIn("MAX_CACHE_ENTRIES = 3", loader)
        self.assertIn("while (this._cache.size > MAX_CACHE_ENTRIES)", loader)
        self.assertNotIn("for (const pose of APPROVED_POSES", loader)
        self.assertIn("clear()", loader)

    def test_all_approved_rgba_assets_match_manifest(self) -> None:
        manifest = json.loads((ASSETS / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["states"]), 14)
        self.assertEqual(len({state["slug"] for state in manifest["states"]}), 14)
        for state in manifest["states"]:
            payload = (ASSETS / state["file"]).read_bytes()
            self.assertEqual(sha256(payload).hexdigest(), state["sha256"])
            self.assertEqual(payload[:8], b"\x89PNG\r\n\x1a\n")
            width, height, depth, color_type = struct.unpack(">IIBB", payload[16:26])
            self.assertEqual((width, height, depth, color_type), (1024, 1536, 8, 6))


if __name__ == "__main__":
    unittest.main()
