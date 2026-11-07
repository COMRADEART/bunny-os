# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Hyprland is the Bunny desktop customization compositor."""

from __future__ import annotations

import configparser
import unittest

from tests.support import ROOT


class HyprlandScaffoldTests(unittest.TestCase):
    def test_hyprland_package_set_exists_and_names_compositor(self) -> None:
        path = ROOT / "build/packages/hyprland.txt"
        self.assertTrue(path.is_file())
        packages = {
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        }
        self.assertIn("hyprland", packages)
        self.assertIn("xdg-desktop-portal-hyprland", packages)
        self.assertIn("waybar", packages)

    def test_desktop_profiles_include_hyprland_package_set(self) -> None:
        import json

        for name in ("desktop", "shell", "shell-test", "developer", "live", "beta"):
            profile = json.loads(
                (ROOT / f"build/profiles/{name}.json").read_text(encoding="utf-8")
            )
            self.assertIn(
                "hyprland",
                profile["packageSets"],
                f"{name} profile must install the hyprland package set",
            )
            self.assertIn("hyprland", profile["desktop"])

    def test_primary_bunny_session_launches_hyprland_wrapper(self) -> None:
        parser = configparser.ConfigParser(interpolation=None, strict=True)
        parser.optionxform = str
        parser.read(ROOT / "shell/session/bunny.desktop", encoding="utf-8")
        entry = parser["Desktop Entry"]
        self.assertEqual(entry.get("Name"), "Bunny")
        self.assertIn("bunny-hyprland-session", entry.get("Exec", ""))
        self.assertIn("Hyprland", entry.get("DesktopNames", ""))

    def test_gnome_and_safe_sessions_remain_selectable(self) -> None:
        self.assertTrue((ROOT / "shell/session/bunny-gnome.desktop").is_file())
        self.assertTrue((ROOT / "shell/session/bunny-safe.desktop").is_file())
        gnome = configparser.ConfigParser(interpolation=None, strict=True)
        gnome.optionxform = str
        gnome.read(ROOT / "shell/session/bunny-gnome.desktop", encoding="utf-8")
        self.assertIn("bunny-shell-session", gnome["Desktop Entry"].get("Exec", ""))

    def test_hyprland_session_wrapper_uses_image_owned_config(self) -> None:
        source = (ROOT / "shell/session/bunny-hyprland-session.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("/usr/share/bunny-shell/hyprland/hyprland.conf", source)
        self.assertIn('BUNNY_DESKTOP_COMPOSITOR"] = "hyprland"', source)
        self.assertIn("bunny-shell.target", source)
        self.assertIn("/usr/libexec/bunny-shell-session", source)

    def test_hyprland_config_tree_is_complete(self) -> None:
        base = ROOT / "shell/components/hyprland"
        for name in (
            "hyprland.conf",
            "look-and-feel.conf",
            "input.conf",
            "keybinds.conf",
            "windowrules.conf",
            "autostart.conf",
            "hyprpaper.conf",
            "waybar/config.jsonc",
            "waybar/style.css",
        ):
            self.assertTrue((base / name).is_file(), f"missing {name}")
        main = (base / "hyprland.conf").read_text(encoding="utf-8")
        self.assertIn("look-and-feel.conf", main)
        self.assertIn("keybinds.conf", main)

    def test_install_routes_ship_hyprland_session_and_config(self) -> None:
        import sys

        scripts = str(ROOT / "build/scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        from install_routes import INSTALL_ROUTES

        destinations = {route.destination: route for route in INSTALL_ROUTES}
        self.assertIn("/usr/libexec/bunny-hyprland-session", destinations)
        self.assertIn("/usr/share/wayland-sessions/bunny.desktop", destinations)
        self.assertIn("/usr/share/wayland-sessions/bunny-gnome.desktop", destinations)
        self.assertIn("/usr/share/bunny-shell/hyprland", destinations)
        hypr = destinations["/usr/share/bunny-shell/hyprland"]
        self.assertEqual(hypr.source, "shell/components/hyprland")
        self.assertEqual(hypr.kind, "tree")


if __name__ == "__main__":
    unittest.main()
