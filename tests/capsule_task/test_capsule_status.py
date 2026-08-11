# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The two layers of §16, and the one thing they must never do: disagree.

The plain layer is what a person reads; the technical panel is what an advanced
user checks it against. Both come from one plan, so the tests here are mostly
about the cases where a friendly sentence would be *comfortable* and wrong —
a network class nothing filters on, a permission nothing enforces, a limit the
host ignores.
"""

from __future__ import annotations

import unittest

import trust
from companion.capsule_status import NETWORK_PHRASES, capsule_status

from tests.capsule_support import World, manifest_for, unconfined_probe


class PlainLayerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.world = World.build()
        self.addCleanup(self.world.close)
        self.capsule = self.world.install(
            manifest_for(required=("files",), optional=("gpu", "network", "clipboard"),
                         network_ceiling="internet")
        )

    def status(self):  # type: ignore[no-untyped-def]
        capsule = self.world.runtime.open("org.example.PhotoEditor")
        return capsule_status(capsule, self.world.runtime.build_plan(capsule))

    def labels(self):  # type: ignore[no-untyped-def]
        return dict(self.status().plain)

    def test_a_capsule_with_no_grants_says_none_of_your_files(self) -> None:
        self.assertEqual(self.labels()["Access"], "None of your files")

    def test_one_granted_file_is_named(self) -> None:
        picture = self.world.file("Pictures/cat.png")
        self.world.answer(("files", "allow", "always"))
        self.world.request(
            self.capsule, category="files", resource=trust.path_resource(picture), purpose="read"
        )
        self.assertEqual(self.labels()["Access"], "This file only: cat.png")

    def test_several_grants_are_counted_rather_than_listed(self) -> None:
        self.world.answer(*[("files", "allow", "always")] * 3)
        for name in ("a.png", "b.png", "c.png"):
            self.world.request(
                self.capsule, category="files",
                resource=trust.path_resource(self.world.file(f"Pictures/{name}")), purpose="read",
            )
        self.assertEqual(self.labels()["Access"], "Only 3 files you chose")

    def test_no_network_reads_as_off(self) -> None:
        self.assertEqual(self.labels()["Network"], "Off")

    def test_a_granted_network_reads_as_on(self) -> None:
        self.world.answer(("network", "allow", "always"))
        self.world.request(
            self.capsule, category="network", resource=trust.network_resource("internet")
        )
        self.assertEqual(self.labels()["Network"], "On")

    def test_the_gpu_appears_only_when_granted(self) -> None:
        self.assertEqual(self.labels()["Devices"], "None")
        self.world.answer(("gpu", "allow", "always"))
        self.world.request(self.capsule, category="gpu")
        self.assertEqual(self.labels()["Devices"], "Graphics card")

    def test_the_headline_is_in_the_companions_voice(self) -> None:
        self.assertIn("protected space", self.status().headline)


class HonestyTests(unittest.TestCase):
    """Where a comfortable sentence would be a false one."""

    def setUp(self) -> None:
        self.world = World.build()
        self.addCleanup(self.world.close)

    def test_an_unenforced_permission_becomes_a_caveat_not_a_silence(self) -> None:
        capsule = self.world.install(manifest_for(optional=("clipboard",)))
        self.world.answer(("clipboard", "allow", "session"))
        self.world.request(capsule, category="clipboard")
        world_capsule = self.world.runtime.open("org.example.PhotoEditor")
        status = capsule_status(world_capsule, self.world.runtime.build_plan(world_capsule))
        self.assertTrue(any("Clipboard" in caveat for caveat in status.caveats))
        self.assertTrue(any("cannot stop" in caveat for caveat in status.caveats))

    def test_an_unfilterable_network_class_never_reads_as_a_boundary(self) -> None:
        """The sentence this test exists to prevent is 'Network: example.com only'
        for a class this build does not filter on."""
        capsule = self.world.install(
            manifest_for(optional=("network",), network_ceiling="allowlisted",
                         network_domains=("example.com",))
        )
        self.world.answer(("network", "allow", "always"))
        self.world.request(
            capsule, category="network",
            resource=trust.network_resource("allowlisted", allowlist=("example.com",)),
        )
        reopened = self.world.runtime.open("org.example.PhotoEditor")
        plan = self.world.runtime.build_plan(reopened)
        status = capsule_status(reopened, plan)
        self.assertFalse(plan.network_enforced)
        self.assertEqual(dict(status.plain)["Network"], "On")
        self.assertNotIn("example.com", dict(status.plain)["Network"])
        self.assertTrue(any("cannot restrict it" in caveat for caveat in status.caveats))

    def test_a_non_confining_plan_says_so_in_the_plain_layer(self) -> None:
        world = World.build(probe=unconfined_probe())
        self.addCleanup(world.close)
        world.install(manifest_for())
        capsule = world.runtime.open("org.example.PhotoEditor")
        plan = world.runtime.build_plan(capsule, allow_unconfined=True)
        status = capsule_status(capsule, plan)
        self.assertEqual(dict(status.plain)["Private app data"], "Not isolated")
        self.assertTrue(any("not in a protected space" in caveat for caveat in status.caveats))


class TechnicalPanelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.world = World.build()
        self.addCleanup(self.world.close)
        self.world.install(manifest_for())

    def status(self):  # type: ignore[no-untyped-def]
        capsule = self.world.runtime.open("org.example.PhotoEditor")
        return capsule_status(capsule, self.world.runtime.build_plan(capsule))

    def test_the_panel_carries_the_mechanism(self) -> None:
        technical = self.status().technical
        for key in ("backend", "namespaces", "mounts", "devices", "network",
                    "environmentKeys", "resourceLimits", "unitName"):
            self.assertIn(key, technical)

    def test_the_plain_network_line_is_derived_from_the_same_plan(self) -> None:
        """The whole point: the friendly line cannot contradict the panel."""
        status = self.status()
        self.assertEqual(
            dict(status.plain)["Network"], NETWORK_PHRASES[status.technical["network"]["class"]]
        )

    def test_the_access_line_counts_the_mounts_the_panel_lists(self) -> None:
        picture = self.world.file("Pictures/cat.png")
        self.world.answer(("files", "allow", "always"))
        self.world.request(
            self.world.runtime.open("org.example.PhotoEditor"), category="files",
            resource=trust.path_resource(picture), purpose="read",
        )
        status = self.status()
        grants = [mount for mount in status.technical["mounts"] if mount["origin"] == "grant"]
        self.assertEqual(len(grants), 1)
        self.assertIn("cat.png", dict(status.plain)["Access"])

    def test_the_panel_shows_no_more_than_the_plan_does(self) -> None:
        """A panel that invented a field would be a second description of the
        sandbox, and the two would eventually disagree."""
        capsule = self.world.runtime.open("org.example.PhotoEditor")
        plan = self.world.runtime.build_plan(capsule)
        status = capsule_status(capsule, plan)
        self.assertEqual(status.technical["backend"], plan.backend)
        self.assertEqual(status.technical["namespaces"], list(plan.unshare))
        self.assertEqual(len(status.technical["mounts"]), len(plan.binds))
        self.assertEqual(status.technical["devices"], list(plan.devices))


if __name__ == "__main__":
    unittest.main()
