from __future__ import annotations

import unittest

from operations.crash import aggregate_crashes, normalize_crash


def crash() -> dict[str, str]:
    return {"component":"Bunny Shell","version":"beta.1","architecture":"x86_64","stackSignature":"sig-1","driver":"virtio","kernel":"unknown","deploymentVersion":"unknown"}


class CrashTests(unittest.TestCase):
    def test_approved_metadata_is_accepted(self) -> None:
        self.assertEqual(normalize_crash(crash())["stackSignature"], "sig-1")

    def test_persistent_user_id_is_rejected(self) -> None:
        value = crash()
        value["userId"] = "tracking-id"
        with self.assertRaises(ValueError):
            normalize_crash(value)

    def test_prompt_is_rejected(self) -> None:
        value = crash()
        value["prompt"] = "private"
        with self.assertRaises(ValueError):
            normalize_crash(value)

    def test_aggregation_has_no_user_profile(self) -> None:
        values = aggregate_crashes([crash(), crash()])
        self.assertEqual(values[0]["count"], 2)
        self.assertNotIn("userId", values[0])


if __name__ == "__main__":
    unittest.main()
