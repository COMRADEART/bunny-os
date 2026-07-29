from __future__ import annotations

import unittest

from operations.modes import MODE_REQUIREMENTS, evaluate_mode


class ModeTests(unittest.TestCase):
    def test_multi_user_requires_no_cross_user_exposure(self) -> None:
        evidence = {key: True for key in MODE_REQUIREMENTS["multi-user"]}
        evidence["noCrossUserExposure"] = False
        self.assertFalse(evaluate_mode("multi-user", evidence)["qualified"])

    def test_local_only_requires_offline_recovery(self) -> None:
        evidence = {key: True for key in MODE_REQUIREMENTS["local-only"]}
        evidence.pop("offlineRecovery")
        self.assertIn("offlineRecovery", evaluate_mode("local-only", evidence)["missingEvidence"])

    def test_bunny_disabled_requires_conventional_desktop(self) -> None:
        evidence = {key: True for key in MODE_REQUIREMENTS["bunny-disabled"]}
        self.assertTrue(evaluate_mode("bunny-disabled", evidence)["qualified"])

    def test_unknown_mode_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            evaluate_mode("cloud-required", {})


if __name__ == "__main__":
    unittest.main()
