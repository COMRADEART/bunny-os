from __future__ import annotations

import unittest

from tests.support import ROOT


class RecoveryTests(unittest.TestCase):
    def test_generator_and_broker_agree_on_exact_marker(self) -> None:
        backend = (ROOT / "services/bunny-system-broker/src/bunny_system_broker/backend.py").read_text(encoding="utf-8")
        generator = (ROOT / "scripts/bunny-recovery-generator.py").read_text(encoding="utf-8")
        for field in ("schemaVersion", "mode", "scheduledAt", "scheduledByUid"):
            self.assertIn(f'"{field}"', backend)
            self.assertIn(f'"{field}"', generator)

    def test_recovery_mutations_require_literal_confirmation(self) -> None:
        source = (ROOT / "scripts/bunny-recovery.py").read_text(encoding="utf-8")
        self.assertIn('== "YES"', source)
        self.assertNotIn("rm -rf", source)


if __name__ == "__main__":
    unittest.main()

