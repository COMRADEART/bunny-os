from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from bunny_shell.clipboard import ClipboardHistory
from bunny_shell.settings import SettingsStore


class ClipboardPrivacyTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.settings = SettingsStore(root / "settings.json")
        self.history = ClipboardHistory(root / "clipboard.json", self.settings)

    def test_history_is_disabled_by_default(self) -> None:
        self.assertFalse(self.history.add("hello", "editor"))
        self.assertEqual(self.history.entries(), [])

    def test_password_fields_are_never_stored(self) -> None:
        self.settings.set("clipboardHistory", True)
        self.assertFalse(self.history.add("secret", "browser", password_field=True))

    def test_sensitive_entries_have_short_expiry_and_clear(self) -> None:
        self.settings.set("clipboardHistory", True)
        self.assertTrue(self.history.add("api_key=example", "editor"))
        self.assertTrue(self.history.entries()[0]["sensitive"])
        self.history.clear()
        self.assertEqual(self.history.entries(), [])


if __name__ == "__main__":
    unittest.main()
