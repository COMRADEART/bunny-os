# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import ast
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "build/scripts/install-root.py"


def install_routes() -> tuple[dict, ...]:
    tree = ast.parse(INSTALLER.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            if "INSTALL_ROUTES" in names:
                return ast.literal_eval(node.value)
    raise AssertionError("install-root.py does not declare INSTALL_ROUTES")


class CompanionInstalledImageTests(unittest.TestCase):
    def test_companion_code_has_a_read_only_install_route(self) -> None:
        route = next(item for item in install_routes() if item["id"] == "companion-code")
        self.assertEqual(route["destination"], "/usr/lib/bunny-os/python/companion")
        self.assertEqual(route["mode"], 0o444)
        self.assertTrue(list(ROOT.glob(route["sourceGlob"])))
        self.assertIn("__pycache__", route["exclude"])

    def test_build_context_and_installer_include_the_runtime(self) -> None:
        containerfile = (ROOT / "build/Containerfile").read_text(encoding="utf-8")
        installer = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("COPY companion /tmp/bunny-os/companion", containerfile)
        self.assertIn("/usr/libexec/bunny-companion-service", installer)
        self.assertIn("/usr/share/bunny-shell/companion", installer)
        self.assertIn('"bunny-companion.service"', installer)

    def test_user_service_is_private_bounded_and_local_only(self) -> None:
        unit = (ROOT / "systemd/user/bunny-companion.service").read_text(encoding="utf-8")
        for directive in (
            "ExecStart=/usr/libexec/bunny-companion-service",
            "RuntimeDirectoryMode=0700",
            "StateDirectoryMode=0700",
            "UMask=0077",
            "NoNewPrivileges=yes",
            "ProtectSystem=strict",
            "RestrictAddressFamilies=AF_UNIX",
            "MemoryMax=128M",
        ):
            with self.subTest(directive=directive):
                self.assertIn(directive, unit)
        self.assertNotIn("AF_INET", unit)

    def test_shell_entry_points_asset_desktop_and_activation_exist(self) -> None:
        required = (
            "services/bunny-companion/bunny_companion_service.py",
            "shell/services/bin/bunny-companion",
            "shell/services/bin/bunny-approvals",
            "shell/assets/companion/default-bunny.svg",
            "shell/components/applications/art.comrade.BunnyCompanion.desktop",
        )
        for relative in required:
            with self.subTest(path=relative):
                self.assertTrue((ROOT / relative).is_file())
        preset = (ROOT / "config/systemd/60-bunny-os-user.preset").read_text(encoding="utf-8")
        target = (ROOT / "systemd/user/bunny-shell.target").read_text(encoding="utf-8")
        self.assertIn("enable bunny-companion.service", preset)
        self.assertIn("Wants=bunny-companion.service", target)

    def test_companion_sources_contain_no_embedded_credential_values(self) -> None:
        credential = re.compile(
            r"(?i)(api[_-]?key|access[_-]?token|password|secret)\s*[=:]\s*['\"][A-Za-z0-9_\-]{12,}"
        )
        for path in sorted((ROOT / "companion").glob("*.py")):
            with self.subTest(path=path.name):
                self.assertIsNone(credential.search(path.read_text(encoding="utf-8")))

    def test_no_companion_runtime_state_is_committed(self) -> None:
        forbidden = {"companion.sqlite3", "approvals.json", "runtime.sock"}
        found = {path.name for path in ROOT.rglob("*") if path.is_file() and path.name in forbidden}
        self.assertEqual(found, set())


if __name__ == "__main__":
    unittest.main()
