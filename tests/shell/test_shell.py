from __future__ import annotations

import json
import unittest

from tests.support import ROOT
from bunny_shell.core_state import shell_status


class ShellTests(unittest.TestCase):
    def test_login_sessions_retain_bunny_and_safe_choices(self) -> None:
        self.assertTrue((ROOT / "shell/session/bunny.desktop").is_file())
        self.assertTrue((ROOT / "shell/session/bunny-safe.desktop").is_file())

    def test_safe_shell_stops_bunny_target(self) -> None:
        source = (ROOT / "shell/session/bunny-shell-session.py").read_text(encoding="utf-8")
        self.assertIn('target_action = "stop" if mode == "safe"', source)
        self.assertIn('BUNNY_SHELL_MODE', source)

    def test_bunny_unavailable_does_not_disable_desktop(self) -> None:
        status = shell_status()
        self.assertTrue(status["desktopUsable"])

    def test_extension_targets_gnome_50(self) -> None:
        metadata = json.loads((ROOT / "shell/components/gnome-shell-extension/metadata.json").read_text(encoding="utf-8"))
        self.assertIn("50", metadata["shell-version"])


if __name__ == "__main__":
    unittest.main()
