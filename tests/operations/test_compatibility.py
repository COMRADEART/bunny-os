from __future__ import annotations

import json
from pathlib import Path
import unittest

from operations.compatibility import resolve_update, validate_entry


ROOT = Path(__file__).resolve().parents[2]


class CompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.entries = json.loads((ROOT / "operations/data/update-compatibility.json").read_text(encoding="utf-8"))["entries"]

    def test_current_entries_are_structurally_valid(self) -> None:
        for entry in self.entries:
            validate_entry(entry)

    def test_unqualified_beta_to_stable_is_rejected(self) -> None:
        result = resolve_update("latest-public-beta", "stable-rc1", self.entries)
        self.assertFalse(result["allowed"])

    def test_unknown_jump_is_rejected(self) -> None:
        self.assertEqual(resolve_update("ancient", "stable", self.entries)["reason"], "unsupported-release-jump")

    def test_supported_update_requires_rollback(self) -> None:
        entry = dict(self.entries[0], directUpdateSupported=True)
        with self.assertRaises(ValueError):
            validate_entry(entry)

    def test_supported_qualified_entry_is_allowed(self) -> None:
        entry = dict(self.entries[0], directUpdateSupported=True, rollbackStatus="qualified")
        self.assertTrue(resolve_update("latest-public-beta", "stable-rc1", [entry])["allowed"])


if __name__ == "__main__":
    unittest.main()
