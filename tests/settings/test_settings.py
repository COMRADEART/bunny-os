from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from bunny_shell.settings import DEFINITIONS, SettingsStore


class SettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "settings.json"
        self.settings = SettingsStore(self.path)

    def test_valid_user_setting(self) -> None:
        self.assertTrue(self.settings.set("reducedMotion", True)["reducedMotion"])

    def test_invalid_setting_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.settings.set("textScalePercent", 500)

    def test_local_only_disables_cloud_failover(self) -> None:
        value = self.settings.set("localOnlyMode", True)
        self.assertEqual(value["defaultProviderAlias"], "local")
        self.assertEqual(value["cloudFailoverPolicy"], "never")

    def test_offline_mode_preserves_loopback_design(self) -> None:
        value = self.settings.set("offlineMode", True)
        self.assertTrue(value["offlineMode"])
        self.assertNotIn("disableLoopback", value)

    def test_credential_alias_rejects_raw_secret_shape(self) -> None:
        with self.assertRaises(ValueError):
            self.settings.set("defaultProviderAlias", "sk-live secret value")

    def test_reset_creates_backup(self) -> None:
        self.settings.set("reducedMotion", True)
        self.settings.reset()
        self.assertTrue(list(self.path.parent.glob("settings.backup.*.json")))

    def test_definitions_have_scope_owner_and_default(self) -> None:
        for definition in DEFINITIONS.values():
            self.assertIn("scope", definition)
            self.assertIn("owner", definition)
            self.assertIn("default", definition)


if __name__ == "__main__":
    unittest.main()
