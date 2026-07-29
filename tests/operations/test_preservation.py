from __future__ import annotations

import unittest

from operations.preservation import DATASETS, compare, validate_manifest


def manifest(seed: str = "a") -> dict[str, str]:
    return {name: "sha256:" + seed * 64 for name in DATASETS}


class PreservationTests(unittest.TestCase):
    def test_equal_manifests_are_preserved(self) -> None:
        self.assertTrue(compare(manifest(), manifest())["preserved"])

    def test_change_is_named_without_content(self) -> None:
        after = manifest()
        after["documents"] = "sha256:" + "b" * 64
        result = compare(manifest(), after)
        self.assertEqual(result["changedDatasets"], ["documents"])
        self.assertFalse(result["contentIncluded"])

    def test_missing_dataset_is_rejected(self) -> None:
        value = manifest()
        value.pop("home")
        with self.assertRaises(ValueError):
            validate_manifest(value)

    def test_raw_content_is_rejected(self) -> None:
        value = manifest()
        value["home"] = "my files"
        with self.assertRaises(ValueError):
            validate_manifest(value)

    def test_all_required_data_classes_are_present(self) -> None:
        self.assertIn("providerCredentialReferences", DATASETS)
        self.assertIn("bunnyMemory", DATASETS)
        self.assertIn("documents", DATASETS)


if __name__ == "__main__":
    unittest.main()
