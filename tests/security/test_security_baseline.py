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

    def test_start_limits_are_unit_directives(self) -> None:
        for relative in (
            "systemd/bunny-system-broker.service",
            "systemd/user/bunny-desktop.service",
            "systemd/user/bunny-shell-status.service",
        ):
            value = (ROOT / relative).read_text(encoding="utf-8")
            unit, service = value.split("[Service]", 1)
            self.assertIn("StartLimitIntervalSec=", unit, relative)
            self.assertIn("StartLimitBurst=", unit, relative)
            self.assertNotIn("StartLimitIntervalSec=", service, relative)
            self.assertNotIn("StartLimitBurst=", service, relative)

    def test_bunny_desktop_uses_a_supported_executable_condition(self) -> None:
        value = (ROOT / "systemd/user/bunny-desktop.service").read_text(encoding="utf-8")
        self.assertIn("ConditionFileIsExecutable=/opt/bunny/current/bunny-desktop", value)
        self.assertNotIn("ConditionPathIsExecutable", value)

    def test_app_server_not_exposed(self) -> None:
        # Directives only. The comment that explains why `disable sshd.socket`
        # is there has to be able to say that sshd was found LISTENING on
        # 0.0.0.0:22 — that measurement is the reason the line below it exists.
        # Matching raw file text made documenting a closed exposure trip the
        # test that verifies exposures are closed, so the only way to a green
        # gate was to delete the explanation. Everything from `#` to end of line
        # is dropped; a binding that shares its line with a trailing comment is
        # still matched, because the part before the `#` survives.
        directives = []
        for root in (ROOT / "services", ROOT / "systemd", ROOT / "config"):
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                    directives.append(line.partition("#")[0])
        self.assertNotRegex("\n".join(directives), r"0\.0\.0\.0:[0-9]+")

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

    def test_health_check_can_write_every_required_state_boundary(self) -> None:
        unit = (ROOT / "systemd/bunny-health-check.service").read_text(encoding="utf-8")
        self.assertIn("ReadWritePaths=/var/lib/bunny-os/health /var/lib/bunny", unit)

    def test_vm_gate_requires_successful_bunny_health_check(self) -> None:
        script = (ROOT / "build/scripts/vm-smoke.sh").read_text(encoding="utf-8")
        self.assertIn("Finished .*Bunny OS boot health check", script)
        self.assertIn("health check did not finish successfully", script)
        self.assertIn("Graphical Interface|Multi-User System|GNOME Display Manager", script)
        self.assertNotIn("GNOME Display Manager|Bunny OS", script)


if __name__ == "__main__":
    unittest.main()

