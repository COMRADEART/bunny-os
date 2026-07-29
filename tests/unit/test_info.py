from __future__ import annotations

import unittest
from unittest import mock

from bunny_os import info


class InfoTests(unittest.TestCase):
    def test_capabilities_keep_protocol_and_contract_independent(self) -> None:
        with mock.patch("bunny_os.info._json", return_value={}):
            value = info.inventory()["contractCapabilities"]
        self.assertEqual(value["contractVersion"], "1.0.0")
        self.assertIn(3, value["bunnyProtocolVersions"])

    def test_model_suitability_is_not_claimed_verified(self) -> None:
        result = info._model_suitability({"totalBytes": 64 * 1024 ** 3}, [{"state": "driver-active"}])
        self.assertFalse(result["verified"])
        self.assertIn("runtime-benchmark-not-run", result["reasons"])


if __name__ == "__main__":
    unittest.main()

