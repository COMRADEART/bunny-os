# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Phase 4 — every account lands in the Bunny session, not just the first.

The installer's AccountsService write (installer/backend/anaconda.py,
_place_handoff) reaches exactly one account: the one the kickstart creates.
An account added later through the Users panel, created by gnome-initial-setup
on an OEM device, or made with useradd used to land in stock GNOME — the
Phase 3 P0 wearing a different user. The mechanism for those is
accounts-daemon's user templates, applied when the daemon first builds a
record for an account that has none.

These are the static half: the templates ship, name the session that ships,
and sit in the directory accounts-daemon actually searches under the name it
actually loads. The behavioural half was measured on the builder
(accountsservice 23.13.9/fc44): a template named ``standard.template`` is
silently ignored — the daemon loads the bare account-type name — and a
template only reaches accounts the daemon itself creates (CreateUser), never
one that already exists. The installed-machine check that a freshly created
account lands in the Bunny session is the remaining evidence.

Each test names the way the fix could be faked and rejects it: a template
that ships but names a session that does not, a template installed under a
name or directory the daemon never reads, a template on a profile with no
session.
"""

from __future__ import annotations

import configparser
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]

if str(ROOT / "build/scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "build/scripts"))

TEMPLATE_SOURCES = {
    "standard": ROOT / "config/accountsservice/standard.template",
    "administrator": ROOT / "config/accountsservice/administrator.template",
}

#: The daemon's vendor search directory. /etc/accountsservice/user-templates
#: is the admin override half of the pair; image content belongs in /usr/share,
#: and on a bootc system /etc is machine-local state besides.
INSTALLED_DIR = "/usr/share/accountsservice/user-templates"


def install_routes():
    from install_routes import INSTALL_ROUTES

    return INSTALL_ROUTES


def route_by_destination(destination: str):
    matches = [r for r in install_routes() if r.destination == destination]
    if len(matches) != 1:
        raise AssertionError(
            f"expected exactly one route to {destination}, found {len(matches)}")
    return matches[0]


class TemplateContentTests(unittest.TestCase):
    """What the templates say, checked against what actually ships."""

    def session_names_that_ship(self) -> set[str]:
        """The session ids GDM can offer, from the wayland-session routes."""
        names = set()
        for route in install_routes():
            if route.destination.startswith("/usr/share/wayland-sessions/"):
                names.add(Path(route.destination).stem)
        return names

    def test_both_account_types_have_a_template(self) -> None:
        for account_type, source in TEMPLATE_SOURCES.items():
            self.assertTrue(
                source.is_file(),
                f"no {account_type} template at {source}; an account of that "
                "type created after installation lands in stock GNOME")

    def test_templates_name_a_session_that_ships(self) -> None:
        shipped = self.session_names_that_ship()
        self.assertIn("bunny", shipped,
                      "the bunny wayland session is not routed at all")
        for account_type, source in TEMPLATE_SOURCES.items():
            parser = configparser.ConfigParser()
            parser.read_string(source.read_text(encoding="utf-8"))
            self.assertIn("User", parser,
                          f"{account_type}.template has no [User] group; "
                          "accounts-daemon reads the record keys from there")
            session = parser["User"].get("Session", "")
            self.assertIn(
                session, shipped,
                f"{account_type}.template seeds Session={session!r}, which "
                "no wayland-session route installs — a preference that "
                "silently becomes stock GNOME")
            self.assertEqual(
                parser["User"].get("XSession", ""), session,
                "the XSession fallback must name the same session")
            self.assertEqual(
                parser["User"].get("SystemAccount", ""), "false",
                "a template that marks accounts as system accounts hides "
                "them from the greeter entirely")

    def test_templates_agree_with_the_installer_record(self) -> None:
        """The installer writes the first account's record directly; the
        template covers every later one. The two must seed the same session,
        or the first user and the second live in different desktops."""
        anaconda = (ROOT / "installer/backend/anaconda.py").read_text(encoding="utf-8")
        self.assertIn("Session=bunny", anaconda,
                      "the installer no longer writes Session=bunny; if the "
                      "record mechanism moved, move the templates with it")
        for source in TEMPLATE_SOURCES.values():
            parser = configparser.ConfigParser()
            parser.read_string(source.read_text(encoding="utf-8"))
            self.assertEqual(parser["User"].get("Session"), "bunny")


class TemplateRouteTests(unittest.TestCase):
    """Where the templates land, checked against the daemon's search path."""

    def test_templates_are_routed_to_the_vendor_directory(self) -> None:
        """Installed as the bare account-type name. `standard.template` is
        the natural spelling and the daemon silently ignores it — measured,
        which is why this asserts the destination byte for byte."""
        for account_type in TEMPLATE_SOURCES:
            route = route_by_destination(f"{INSTALLED_DIR}/{account_type}")
            self.assertEqual(
                route.source, f"config/accountsservice/{account_type}.template")
            self.assertEqual(route.kind, "file")
            self.assertEqual(route.mode, 0o644)

    def test_no_route_installs_a_template_under_the_ignored_name(self) -> None:
        wrong = [r.destination for r in install_routes()
                 if r.destination.startswith(INSTALLED_DIR)
                 and r.destination.endswith(".template")]
        self.assertEqual(
            wrong, [],
            "accounts-daemon loads the bare account-type name; a *.template "
            "destination ships a file the daemon never reads")

    def test_no_template_route_targets_the_admin_override(self) -> None:
        wrong = [r.destination for r in install_routes()
                 if r.destination.startswith("/etc/accountsservice/")]
        self.assertEqual(
            wrong, [],
            "/etc/accountsservice is the administrator's override half of "
            "the search path; image content belongs in /usr/share")

    def test_template_profiles_match_the_session_they_name(self) -> None:
        session_route = route_by_destination(
            "/usr/share/wayland-sessions/bunny.desktop")
        for account_type in TEMPLATE_SOURCES:
            template_route = route_by_destination(
                f"{INSTALLED_DIR}/{account_type}")
            self.assertEqual(
                template_route.profiles, session_route.profiles,
                "a template on a profile without the session it names seeds "
                "a session GDM cannot start")


if __name__ == "__main__":
    unittest.main()
