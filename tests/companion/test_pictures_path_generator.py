# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""XDG Pictures generator: extra ReadWritePaths without widening ProtectHome."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
GENERATOR = ROOT / "scripts/bunny-pictures-path-generator.py"


def _load():
    spec = importlib.util.spec_from_file_location(
        "bunny_pictures_path_generator", GENERATOR,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


generator = _load()


class PicturesPathGeneratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "home"
        self.home.mkdir()
        (self.home / "Pictures").mkdir()
        (self.home / "Photos").mkdir()
        self.config = self.home / ".config"
        self.config.mkdir()
        saved = {
            key: os.environ.get(key)
            for key in ("HOME", "XDG_PICTURES_DIR", "XDG_CONFIG_HOME")
        }

        def restore() -> None:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        self.addCleanup(restore)

    def test_default_pictures_does_not_write_a_dropin(self) -> None:
        dest = Path(self.tmp.name) / "gen"
        dest.mkdir()
        os.environ["HOME"] = str(self.home)
        os.environ.pop("XDG_PICTURES_DIR", None)
        os.environ.pop("XDG_CONFIG_HOME", None)
        self.assertEqual(0, generator.main([str(dest)]))
        self.assertFalse((dest / "bunny-companion.service.d").exists())

    def test_relocated_pictures_under_home_writes_readwritepaths(self) -> None:
        dest = Path(self.tmp.name) / "gen"
        photos = self.home / "Photos"
        (self.config / "user-dirs.dirs").write_text(
            f'XDG_PICTURES_DIR="{photos}"\n', encoding="utf-8",
        )
        os.environ["HOME"] = str(self.home)
        os.environ["XDG_CONFIG_HOME"] = str(self.config)
        os.environ.pop("XDG_PICTURES_DIR", None)
        self.assertEqual(0, generator.main([str(dest), str(dest), str(dest)]))
        dropin = dest / "bunny-companion.service.d" / "pictures-xdg.conf"
        text = dropin.read_text(encoding="utf-8")
        self.assertIn("[Service]", text)
        self.assertIn(f"ReadWritePaths=-{photos.resolve()}", text)

    def test_path_outside_home_is_refused(self) -> None:
        dest = Path(self.tmp.name) / "gen"
        dest.mkdir()
        os.environ["HOME"] = str(self.home)
        os.environ["XDG_PICTURES_DIR"] = "/etc"
        self.assertEqual(0, generator.main([str(dest)]))
        self.assertFalse((dest / "bunny-companion.service.d").exists())

    def test_credential_directory_is_refused(self) -> None:
        dest = Path(self.tmp.name) / "gen"
        dest.mkdir()
        ssh = self.home / ".ssh"
        ssh.mkdir()
        os.environ["HOME"] = str(self.home)
        os.environ["XDG_PICTURES_DIR"] = str(ssh)
        self.assertEqual(0, generator.main([str(dest)]))
        self.assertFalse((dest / "bunny-companion.service.d").exists())


    def test_the_installer_ships_the_user_generator(self) -> None:
        routes = (ROOT / "build/scripts/install_routes.py").read_text(encoding="utf-8")
        self.assertIn("bunny-pictures-path-generator", routes)
        self.assertIn(
            "/usr/lib/systemd/user-generators/bunny-pictures-path-generator",
            routes,
        )


if __name__ == "__main__":
    unittest.main()
