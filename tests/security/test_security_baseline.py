from __future__ import annotations

import re
import unittest

from tests.support import ROOT


class SecurityBaselineTests(unittest.TestCase):
    def test_broker_has_no_shell_or_network_listener(self) -> None:
        sources = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "services/bunny-system-broker").rglob("*.py"))
        self.assertNotIn("shell=True", sources)
        self.assertNotIn("AF_INET", sources)
        self.assertNotRegex(sources, r"\b(eval|exec)\(")

    def test_broker_systemd_hardening(self) -> None:
        unit = (ROOT / "systemd/bunny-system-broker.service").read_text(encoding="utf-8")
        for directive in ("NoNewPrivileges=yes", "ProtectSystem=strict", "ProtectHome=yes", "PrivateTmp=yes", "CapabilityBoundingSet=", "RestrictAddressFamilies=AF_UNIX", "IPAddressDeny=any"):
            self.assertIn(directive, unit)

    def test_app_server_not_exposed(self) -> None:
        all_owned = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for root in (ROOT / "services", ROOT / "systemd", ROOT / "config") for path in root.rglob("*") if path.is_file())
        self.assertNotRegex(all_owned, r"0\.0\.0\.0:[0-9]+")

    def test_privacy_defaults_off(self) -> None:
        source = (ROOT / "scripts/bunny-first-boot.py").read_text(encoding="utf-8")
        for name in ("telemetry", "remoteDiagnostics", "cloudFallback", "screenCapture"):
            self.assertRegex(source, rf'"{name}": False')

    def test_firewall_drops_unsolicited_inbound(self) -> None:
        zone = (ROOT / "config/firewalld/bunny-default.xml").read_text(encoding="utf-8")
        self.assertIn('target="DROP"', zone)
        self.assertNotIn("<port", zone)

    def test_no_world_writable_system_path(self) -> None:
        tmpfiles = (ROOT / "config/tmpfiles/bunny-os.conf").read_text(encoding="utf-8")
        self.assertNotRegex(tmpfiles, r"\s0?777\s")


if __name__ == "__main__":
    unittest.main()

