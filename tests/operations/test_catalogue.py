from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class CatalogueTests(unittest.TestCase):
    def test_every_application_has_stable_review_fields(self) -> None:
        value = json.loads((ROOT / "operations/data/application-catalogue.json").read_text(encoding="utf-8"))
        required = {"category", "application", "maintenanceOwner", "updateSource", "licence", "securityUpdatePath", "accessibilityStatus", "reason"}
        for application in value["applications"]:
            self.assertEqual(set(application), required)

    def test_unqualified_bunny_is_not_claimed_stable(self) -> None:
        value = json.loads((ROOT / "operations/data/application-catalogue.json").read_text(encoding="utf-8"))
        bunny = next(item for item in value["applications"] if item["category"] == "Bunny Desktop")
        self.assertEqual(bunny["licence"], "unqualified")


if __name__ == "__main__":
    unittest.main()
