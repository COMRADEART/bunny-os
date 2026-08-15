from __future__ import annotations

import unittest

from tests.support import ROOT


class PanelTests(unittest.TestCase):
    def test_panel_does_not_claim_secure_state(self) -> None:
        source = (ROOT / "shell/components/gnome-shell-extension/extension.js").read_text(encoding="utf-8")
        self.assertIn("status unavailable · security unknown", source)
        self.assertNotIn("status not yet verified", source)
        self.assertNotIn("Secure ✓", source)

    def test_only_fixed_actions_are_spawned(self) -> None:
        source = (ROOT / "shell/components/gnome-shell-extension/extension.js").read_text(encoding="utf-8")
        self.assertIn("FIXED_ACTIONS", source)
        self.assertNotIn("sh -c", source)


if __name__ == "__main__":
    unittest.main()
