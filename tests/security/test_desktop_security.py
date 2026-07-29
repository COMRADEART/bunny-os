from __future__ import annotations

import unittest

from tests.support import ROOT


class DesktopSecurityTests(unittest.TestCase):
    def test_shell_has_no_privileged_or_generic_execution_backend(self) -> None:
        sources = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "shell/services/bunny_shell").glob("*.py"))
        self.assertNotIn("shell=True", sources)
        self.assertNotIn("os.system(", sources)
        self.assertNotIn("eval(", sources)

    def test_user_service_resource_limits(self) -> None:
        for name in ("bunny-shell-status.service", "bunny-search-index.service"):
            unit = (ROOT / "systemd/user" / name).read_text(encoding="utf-8")
            for directive in ("NoNewPrivileges=yes", "ProtectSystem=strict", "MemoryMax=", "TasksMax="):
                self.assertIn(directive, unit)

    def test_clipboard_history_and_telemetry_default_off(self) -> None:
        source = (ROOT / "shell/services/bunny_shell/settings.py").read_text(encoding="utf-8")
        self.assertIn('"clipboardHistory": {"default": False', source)
        self.assertIn('"telemetryEnabled": {"default": False', source)

    def test_screen_capture_uses_documented_portal_not_custom_capture(self) -> None:
        docs = (ROOT / "docs/PRIVACY_MODEL.md").read_text(encoding="utf-8")
        self.assertIn("desktop portals", docs)
        source = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in (ROOT / "shell").rglob("*") if path.is_file())
        self.assertNotIn("gnome-screenshot", source)


if __name__ == "__main__":
    unittest.main()
