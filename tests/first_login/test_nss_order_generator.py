# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Boot generator for the chronyd-class NSS altfiles race. Runtime: NOT_RUN here."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
GENERATOR = ROOT / "scripts/bunny-nss-order-generator.py"


def _load():
    spec = importlib.util.spec_from_file_location(
        "bunny_nss_order_generator", GENERATOR,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


generator = _load()


class NssOrderGeneratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "root"
        system = self.root / "usr/lib/systemd/system"
        system.mkdir(parents=True)
        (self.root / "etc").mkdir()
        (self.root / "usr/lib").mkdir(parents=True, exist_ok=True)
        (self.root / "etc/passwd").write_text(
            "root:x:0:0:root:/root:/bin/bash\n", encoding="utf-8",
        )
        (self.root / "usr/lib/passwd").write_text(
            "chrony:x:994:992::/var/lib/chrony:/usr/sbin/nologin\n",
            encoding="utf-8",
        )
        self.system = system
        saved = os.environ.get("BUNNY_NSS_ROOT")

        def restore() -> None:
            if saved is None:
                os.environ.pop("BUNNY_NSS_ROOT", None)
            else:
                os.environ["BUNNY_NSS_ROOT"] = saved

        self.addCleanup(restore)

    def _unit(self, name: str, user: str) -> None:
        (self.system / name).write_text(
            f"[Service]\nExecStart=/usr/bin/true\nUser={user}\n",
            encoding="utf-8",
        )

    def test_writes_dropin_for_altfiles_user_without_ordering(self) -> None:
        self._unit("chronyd.service", "chrony")
        dest = Path(self.tmp.name) / "out"
        os.environ["BUNNY_NSS_ROOT"] = str(self.root)
        self.assertEqual(0, generator.main([str(dest)]))
        dropin = dest / "chronyd.service.d" / "50-bunny-nss-order.conf"
        text = dropin.read_text(encoding="utf-8")
        self.assertIn("Wants=nss-user-lookup.target", text)
        self.assertIn("After=nss-user-lookup.target", text)
        self.assertIn("After=authselect-apply-changes.service", text)
        self.assertNotRegex(text, r"(?m)^Requires=")
        self.assertNotRegex(text, r"(?m)^Before=")

    def test_skips_when_chronyd_already_has_the_repo_dropin(self) -> None:
        self._unit("chronyd.service", "chrony")
        drop = self.system / "chronyd.service.d"
        drop.mkdir()
        (drop / "50-bunny-nss-order.conf").write_text(generator.DROPIN, encoding="utf-8")
        dest = Path(self.tmp.name) / "out"
        os.environ["BUNNY_NSS_ROOT"] = str(self.root)
        self.assertEqual(0, generator.main([str(dest)]))
        self.assertFalse((dest / "chronyd.service.d").exists())

    def test_does_not_overlay_root_units(self) -> None:
        self._unit("bunny-health-check.service", "root")
        dest = Path(self.tmp.name) / "out"
        os.environ["BUNNY_NSS_ROOT"] = str(self.root)
        self.assertEqual(0, generator.main([str(dest)]))
        self.assertEqual(list(dest.glob("*.service.d")), [])

    def test_no_usr_lib_passwd_is_a_noop(self) -> None:
        (self.root / "usr/lib/passwd").unlink()
        self._unit("chronyd.service", "chrony")
        dest = Path(self.tmp.name) / "out"
        os.environ["BUNNY_NSS_ROOT"] = str(self.root)
        self.assertEqual(0, generator.main([str(dest)]))
        self.assertFalse((dest / "chronyd.service.d").exists())


    def test_the_installer_ships_the_system_generator(self) -> None:
        routes = (ROOT / "build/scripts/install_routes.py").read_text(encoding="utf-8")
        self.assertIn("bunny-nss-order-generator", routes)
        self.assertIn(
            "/usr/lib/systemd/system-generators/bunny-nss-order-generator",
            routes,
        )


if __name__ == "__main__":
    unittest.main()
