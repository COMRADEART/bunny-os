from __future__ import annotations

import json
import unittest

from tests.support import ROOT


class VisualArchitectureTests(unittest.TestCase):
    def test_preview_is_a_separate_named_session(self) -> None:
        desktop = (ROOT / "sessions/bunny-visual-preview.desktop").read_text(encoding="utf-8")
        self.assertIn("Name=Bunny Visual Preview", desktop)
        self.assertIn("X-Bunny-Visual-Prototype=true", desktop)
        self.assertNotIn("Default", desktop)

    def test_preview_mode_enables_only_preview_extension(self) -> None:
        mode = json.loads((ROOT / "sessions/bunny-visual-preview.json").read_text(encoding="utf-8"))
        self.assertEqual(mode["parentMode"], "user")
        self.assertEqual(mode["enabledExtensions"], ["bunny-desktop-v1@bunny-os.org"])

    def test_preview_launcher_does_not_mutate_desktop_preferences(self) -> None:
        source = (ROOT / "sessions/bunny-visual-preview-session").read_text(encoding="utf-8")
        for forbidden in ("gsettings set", "dconf write", "AccountsService", "systemctl enable"):
            self.assertNotIn(forbidden, source)
        self.assertIn("--session=bunny-visual-preview", source)

    def test_token_schema_is_versioned_and_closed(self) -> None:
        schema = json.loads((ROOT / "visual/tokens/schema.json").read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["version"]["const"], 1)
        self.assertFalse(schema["additionalProperties"])

    def test_architecture_declares_release_boundary(self) -> None:
        source = (ROOT / "docs/BUNNY_VISUAL_ARCHITECTURE.md").read_text(encoding="utf-8")
        self.assertIn("not release qualified", source.casefold())
        self.assertIn("Missing data is shown as unavailable", source)


if __name__ == "__main__":
    unittest.main()
