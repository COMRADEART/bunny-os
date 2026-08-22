# SPDX-License-Identifier: GPL-3.0-or-later
"""The companion's place in the installed image.

The install set is declared once, in ``build/scripts/install_routes.py``, and
``install-root.py`` is driven by that table — so these tests read the same
route objects the installer copies from. Re-parsing the installer here would
let a test pass while the two sides disagreed, which is precisely the failure
the shared table exists to prevent.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import re
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "build/scripts/install-root.py"
ROUTE_TABLE = ROOT / "build/scripts/install_routes.py"


def load_route_table():
    """Import the declaration both consumers read.

    The module is standard-library-only on purpose — it runs inside a bootc
    container with no repository Python on its path — so importing it here is
    safe as well as honest.
    """
    spec = importlib.util.spec_from_file_location("install_routes_under_test", ROUTE_TABLE)
    module = importlib.util.module_from_spec(spec)
    # Dataclass processing resolves string annotations through sys.modules; an
    # unregistered module makes that lookup return None under Python 3.14.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class CompanionInstalledImageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.table = load_route_table()

    def route(self, identifier: str):
        return next(
            item for item in self.table.INSTALL_ROUTES if item.id == identifier
        )

    def test_companion_code_has_a_read_only_install_route(self) -> None:
        route = self.route("companion-package")
        self.assertEqual(route.destination, "/usr/lib/bunny-os/python/companion")
        self.assertEqual(route.mode, 0o444)
        # A package route installs source and only source: bytecode carries the
        # producing machine's paths and mtimes, and fixtures are
        # untrusted-input-shaped content.
        self.assertIn("__pycache__", route.effective_exclude)
        self.assertEqual(route.effective_suffixes, (".py",))
        copied = list(self.table.route_files(route, ROOT))
        self.assertTrue(copied, "the companion package route selects no file")
        destinations = {destination for _, destination in copied}
        # The whole package travels, voice and character included: this is the
        # coverage whose absence once reported a voice-runtime change as zero
        # build impact.
        self.assertIn("/usr/lib/bunny-os/python/companion/store.py", destinations)
        self.assertTrue(
            any(item.startswith("/usr/lib/bunny-os/python/companion/voice/") for item in destinations),
            "companion/voice/ did not travel with the package route",
        )
        self.assertTrue(
            any(item.startswith("/usr/lib/bunny-os/python/companion/character/") for item in destinations),
            "companion/character/ did not travel with the package route",
        )
        self.assertFalse(any(destination.endswith((".pyc", ".pyo")) for destination in destinations))

    def test_build_context_and_installer_include_the_runtime(self) -> None:
        containerfile = (ROOT / "build/Containerfile").read_text(encoding="utf-8")
        installer = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("COPY companion /tmp/bunny-os/companion", containerfile)
        # Destinations live in the route table, not hardcoded in the installer —
        # that duplication is exactly what the shared table replaced. Assert
        # through the declaration both consumers read.
        destinations = {
            route.id: route.destination for route in self.table.INSTALL_ROUTES
        }
        self.assertEqual(
            destinations["companion-service-executable"],
            "/usr/libexec/bunny-companion-service",
        )
        self.assertEqual(
            destinations["companion-shell-assets"],
            "/usr/share/bunny-shell/companion",
        )
        # The activation list names the unit the preset enables: a companion
        # shipped but never enabled is the defect "a preset is not an enablement".
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
            # Enforcement budgets sized for the resident recogniser plus the
            # isolated TTS worker, not benchmark claims; see the unit comment.
            "MemoryHigh=1536M",
            "MemoryMax=2G",
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
