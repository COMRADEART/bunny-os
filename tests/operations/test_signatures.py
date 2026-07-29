from __future__ import annotations

import json
from pathlib import Path
import unittest

from operations.signatures import match_signatures, validate_signature


ROOT = Path(__file__).resolve().parents[2]


class SignatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalogue = json.loads((ROOT / "operations/data/failure-signatures.json").read_text(encoding="utf-8"))["signatures"]

    def test_catalogue_has_requested_seed_signatures(self) -> None:
        self.assertEqual(len(self.catalogue), 10)
        for item in self.catalogue:
            validate_signature(item)

    def test_matches_component_and_signature(self) -> None:
        matches = match_signatures({"component": "Updates", "errorSignature": "expired_manifest"}, self.catalogue)
        self.assertEqual(matches, ["FS-0006"])

    def test_wrong_component_does_not_match(self) -> None:
        self.assertEqual(match_signatures({"component": "Audio", "message": "expired_manifest"}, self.catalogue), [])

    def test_unknown_field_is_rejected(self) -> None:
        item = dict(self.catalogue[0], command="rm")
        with self.assertRaises(ValueError):
            validate_signature(item)


if __name__ == "__main__":
    unittest.main()
