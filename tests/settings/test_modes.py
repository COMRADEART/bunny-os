from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from bunny_shell.policy import evaluate
from bunny_shell.settings import SettingsStore


class ModePolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.settings = SettingsStore(Path(temporary.name) / "settings.json")

    def test_local_only_denies_cloud_but_not_updates_or_loopback(self) -> None:
        self.settings.set("localOnlyMode", True)
        self.assertFalse(evaluate("cloud_provider", settings=self.settings)["allowed"])
        self.assertTrue(evaluate("os_update", settings=self.settings)["allowed"])
        self.assertTrue(evaluate("loopback", settings=self.settings)["allowed"])

    def test_offline_denies_updates_and_external_plugins_but_not_loopback(self) -> None:
        self.settings.set("offlineMode", True)
        self.assertFalse(evaluate("os_update", settings=self.settings)["allowed"])
        self.assertFalse(evaluate("plugin_network", settings=self.settings)["allowed"])
        self.assertTrue(evaluate("plugin_network", plugin_exempt=True, settings=self.settings)["allowed"])
        self.assertTrue(evaluate("loopback", settings=self.settings)["allowed"])

    def test_unknown_action_denies(self) -> None:
        self.assertFalse(evaluate("mystery", settings=self.settings)["allowed"])


if __name__ == "__main__":
    unittest.main()
