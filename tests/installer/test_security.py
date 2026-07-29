from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class InstallerSecuritySourceTests(unittest.TestCase):
    def test_backend_has_no_generic_command_operation(self) -> None:
        protocol = (ROOT / "installer/protocol.py").read_text(encoding="utf-8")
        self.assertNotIn('"installer.command', protocol)
        self.assertNotIn("shell=True", (ROOT / "installer/backend/service.py").read_text(encoding="utf-8"))

    def test_disk_probe_uses_fixed_command(self) -> None:
        probe = (ROOT / "installer/storage/probe.py").read_text(encoding="utf-8")
        self.assertIn("LSBLK_COMMAND", probe)
        self.assertNotIn("shell=True", probe)

    def test_schema_contains_no_password_value(self) -> None:
        schema = (ROOT / "schemas/installer-protocol.schema.json").read_text(encoding="utf-8")
        self.assertNotIn('"password"', schema)
        self.assertNotIn('"recoveryKey"', schema)

