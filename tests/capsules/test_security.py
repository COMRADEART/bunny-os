# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Attempts to get something out of a capsule, or into one, that should not move.

§35's list, as far as it can be reached without a kernel: path traversal, symlink
attacks, cross-capsule access, environment leakage, an export that overwrites its
own input, a destructive operation aimed outside its own tree, and metadata that
tries to widen what an application may ask for.

Where an item on that list needs a running sandbox — a mount escape, a namespace
escape, a real seccomp bypass — there is no test here, and the reports say so
rather than a weaker test standing in for it.
"""

from __future__ import annotations

import os
from pathlib import Path
import unittest

import trust
from capsules.errors import (
    CapsuleContainmentError,
    CapsuleExportRefused,
    CapsuleIsolationError,
    CapsuleSchemaError,
    CapsuleUnavailable,
)
from capsules.exchange import describe_import, export_artifact
from capsules.isolation import GRANT_TARGET_ROOT
from capsules.layout import CapsuleLayout, is_capsule_private

from tests.capsule_support import World, manifest_for, unconfined_probe


class ExportTraversalTests(unittest.TestCase):
    """A capsule names an artefact, never a path."""

    def setUp(self) -> None:
        self.world = World.build()
        self.addCleanup(self.world.close)
        self.capsule = self.world.install()
        self.artifact = self.capsule.layout.directory("exports") / "result.png"
        self.artifact.write_bytes(b"RESULT")

    def export(self, name: str, **kwargs):  # type: ignore[no-untyped-def]
        kwargs.setdefault("destination_root", self.world.home / "Pictures")
        kwargs.setdefault("home", self.world.home)
        kwargs.setdefault("capsule_root", self.world.runtime.root)
        return export_artifact(self.capsule.layout, name, **kwargs)

    def test_a_traversal_in_the_artefact_name_is_refused(self) -> None:
        for hostile in ("../../etc/passwd", "..", ".", "sub/dir.png", "a\\b.png", ""):
            with self.assertRaises(CapsuleSchemaError, msg=hostile):
                self.export(hostile)

    def test_an_artefact_outside_the_exports_directory_is_refused(self) -> None:
        secret = self.capsule.layout.directory("data") / "private.txt"
        secret.write_bytes(b"private")
        with self.assertRaises(CapsuleSchemaError):
            self.export("../data/private.txt")

    @unittest.skipUnless(hasattr(os, "symlink"), "the platform has no symlinks")
    def test_a_symlinked_artefact_pointing_out_of_the_capsule_is_refused(self) -> None:
        outside = self.world.home / "Documents" / "target.txt"
        outside.write_bytes(b"outside")
        link = self.capsule.layout.directory("exports") / "sneaky.txt"
        try:
            os.symlink(outside, link)
        except (OSError, NotImplementedError) as error:  # pragma: no cover
            self.skipTest(f"symlinks unavailable: {error}")
        with self.assertRaises(CapsuleExportRefused):
            self.export("sneaky.txt")

    def test_a_destination_outside_the_users_own_folders_is_refused(self) -> None:
        for destination in (self.world.base / "etc", Path(self.world.home), self.world.home / ".ssh"):
            destination.mkdir(parents=True, exist_ok=True)
            with self.assertRaises(CapsuleExportRefused, msg=str(destination)):
                self.export("result.png", destination_root=destination)

    def test_a_destination_inside_another_capsule_is_refused(self) -> None:
        other = self.world.install(manifest_for("org.example.Other", display_name="Other"))
        with self.assertRaises(CapsuleExportRefused):
            self.export("result.png", destination_root=other.layout.directory("data"))


class OriginalPreservationTests(unittest.TestCase):
    """§15: the original survives unless overwriting it was asked for."""

    def setUp(self) -> None:
        self.world = World.build()
        self.addCleanup(self.world.close)
        self.capsule = self.world.install()
        self.original = self.world.file("Pictures/cat.png", b"ORIGINAL")

    def stage(self, name: str, content: bytes = b"RESULT") -> None:
        (self.capsule.layout.directory("exports") / name).write_bytes(content)

    def test_an_export_with_the_same_name_does_not_replace_the_input(self) -> None:
        self.stage("cat.png")
        result = export_artifact(
            self.capsule.layout,
            "cat.png",
            destination_root=self.world.home / "Pictures",
            original=self.original,
            home=self.world.home,
            capsule_root=self.world.runtime.root,
        )
        self.assertTrue(result.renamed)
        self.assertTrue(result.original_preserved)
        self.assertEqual(self.original.read_bytes(), b"ORIGINAL")
        self.assertNotEqual(Path(result.destination), self.original)

    def test_an_explicit_overwrite_keeps_a_copy_of_the_original(self) -> None:
        self.stage("cat.png")
        result = export_artifact(
            self.capsule.layout,
            "cat.png",
            destination_root=self.world.home / "Pictures",
            original=self.original,
            overwrite=True,
            home=self.world.home,
            capsule_root=self.world.runtime.root,
        )
        self.assertFalse(result.original_preserved)
        self.assertIsNotNone(result.original_copy)
        self.assertEqual(Path(result.original_copy).read_bytes(), b"ORIGINAL")
        self.assertEqual(self.original.read_bytes(), b"RESULT")

    def test_a_collision_with_an_unrelated_file_numbers_rather_than_replaces(self) -> None:
        existing = self.world.file("Pictures/other.png", b"SOMEBODY-ELSES-WORK")
        self.stage("other.png")
        result = export_artifact(
            self.capsule.layout,
            "other.png",
            destination_root=self.world.home / "Pictures",
            home=self.world.home,
            capsule_root=self.world.runtime.root,
        )
        self.assertTrue(result.renamed)
        self.assertEqual(existing.read_bytes(), b"SOMEBODY-ELSES-WORK")

    def test_the_copy_is_verified_by_digest(self) -> None:
        self.stage("verified.png", b"A" * 4096)
        result = export_artifact(
            self.capsule.layout,
            "verified.png",
            destination_root=self.world.home / "Pictures",
            home=self.world.home,
            capsule_root=self.world.runtime.root,
        )
        import hashlib

        self.assertEqual(result.digest, hashlib.sha256(b"A" * 4096).hexdigest())
        self.assertEqual(Path(result.destination).read_bytes(), b"A" * 4096)


class CrossCapsuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.world = World.build()
        self.addCleanup(self.world.close)
        self.first = self.world.install(manifest_for("org.example.First", display_name="First"))
        self.second = self.world.install(manifest_for("org.example.Second", display_name="Second"))

    def test_two_capsules_have_different_directories(self) -> None:
        self.assertNotEqual(self.first.layout.root, self.second.layout.root)

    def test_a_capsule_directory_is_recognised_as_private_however_it_is_reached(self) -> None:
        self.assertTrue(is_capsule_private(self.first.layout.directory("data"), root=self.world.runtime.root))
        self.assertFalse(is_capsule_private(self.world.home / "Pictures", root=self.world.runtime.root))

    @unittest.skipUnless(hasattr(os, "symlink"), "the platform has no symlinks")
    def test_a_symlink_into_a_capsule_is_still_recognised_as_a_capsule(self) -> None:
        alias = self.world.home / "Documents" / "shortcut"
        try:
            os.symlink(self.first.layout.directory("data"), alias, target_is_directory=True)
        except (OSError, NotImplementedError) as error:  # pragma: no cover
            self.skipTest(f"symlinks unavailable: {error}")
        self.assertTrue(is_capsule_private(alias, root=self.world.runtime.root))

    def test_a_grant_never_carries_between_applications(self) -> None:
        self.world.answer(("gpu", "allow", "always"))
        self.world.request(self.first, category="gpu")
        self.assertEqual(len(self.world.runtime.grants(self.first)), 1)
        self.assertEqual(self.world.runtime.grants(self.second), ())


class DestructiveContainmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.world = World.build()
        self.addCleanup(self.world.close)
        self.capsule = self.world.install()

    def test_destroy_refuses_a_layout_whose_directory_is_not_its_own(self) -> None:
        """A layout assembled by hand, or by string concatenation somewhere, does
        not delete: the name is a digest of the application id."""
        elsewhere = self.world.base / "not-a-capsule"
        elsewhere.mkdir()
        layout = CapsuleLayout(identity=self.capsule.identity, root=elsewhere)
        with self.assertRaises(CapsuleContainmentError):
            layout.destroy()
        self.assertTrue(elsewhere.exists())

    def test_a_directory_name_outside_the_list_cannot_be_removed(self) -> None:
        with self.assertRaises(CapsuleSchemaError):
            self.capsule.layout.directory("../../etc")

    def test_reset_only_touches_the_capsules_own_tree(self) -> None:
        outside = self.world.file("Documents/keep.txt", b"KEEP")
        self.world.runtime.delete_data(self.capsule)
        self.assertTrue(outside.exists())
        self.assertEqual(outside.read_bytes(), b"KEEP")


class ImportDescriptionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.world = World.build()
        self.addCleanup(self.world.close)
        self.capsule = self.world.install()

    def test_the_described_sandbox_path_matches_the_one_the_planner_builds(self) -> None:
        """The prompt tells a person where a file will appear; the planner puts it
        there. Two implementations of that string would eventually disagree."""
        picture = self.world.file("Pictures/cat.png")
        resource = trust.path_resource(picture)
        described = describe_import(resource, writable=False)
        self.world.answer(("files", "allow", "always"))
        self.world.request(self.capsule, category="files", resource=resource, purpose="read")
        plan = self.world.runtime.build_plan(self.world.runtime.open("org.example.PhotoEditor"))
        planned = [bind for bind in plan.binds if bind.origin == "grant"][0]
        self.assertEqual(described.sandbox_path, planned.target)
        self.assertTrue(described.sandbox_path.startswith(GRANT_TARGET_ROOT))

    def test_only_a_path_can_be_imported(self) -> None:
        with self.assertRaises(CapsuleSchemaError):
            describe_import(trust.network_resource("internet"), writable=False)


class NoDowngradeTests(unittest.TestCase):
    """A machine that cannot confine gets no application, not a naked one.

    §22 of the brief in one sentence, and the sentence it exists to forbid is
    "Sandbox failed, opening normally." The route to that sentence is short and
    entirely plausible: ``build_plan`` already takes ``allow_unconfined``, one
    caller already passes it, and a second caller passing it in a hurry is how
    a fail-open ships. So the tests below are about *callers* as much as about
    the planner — an unenforceable plan is refused, the coordinator never asks
    for one, and the executor refuses one even if a plan reached it.
    """

    def setUp(self) -> None:
        self.world = World.build(probe=unconfined_probe())
        self.addCleanup(self.world.close)

    def test_a_machine_without_confinement_refuses_the_plan(self) -> None:
        capsule = self.world.install(manifest_for())
        with self.assertRaises((CapsuleUnavailable, CapsuleIsolationError)):
            self.world.runtime.build_plan(capsule)

    def test_the_refusal_names_the_machine_and_not_the_application(self) -> None:
        """A person told "PhotoEditor failed" looks for a broken application. The
        machine is what is missing, and the message has to say which."""
        capsule = self.world.install(manifest_for())
        try:
            self.world.runtime.build_plan(capsule)
        except (CapsuleUnavailable, CapsuleIsolationError) as error:
            message = str(error).lower()
        else:
            self.fail("an unconfinable machine produced a plan")
        self.assertTrue(
            any(word in message for word in ("namespace", "backend", "confin", "sandbox")),
            message,
        )

    def test_launching_on_such_a_machine_starts_nothing(self) -> None:
        capsule = self.world.install(manifest_for())
        with self.assertRaises((CapsuleUnavailable, CapsuleIsolationError)):
            self.world.runtime.launch(capsule)
        state = self.world.runtime.open("org.example.PhotoEditor").state
        self.assertNotEqual(state.state, "running")
        self.assertIsNone(state.pid)

    def test_the_unconfined_plan_is_marked_and_the_executor_refuses_it(self) -> None:
        """The one caller that may build an unconfined plan builds it to *look at*.
        The executor is the second lock: a plan that reached it without
        confinement is refused there too, so a projection can never become a
        launch by being handed to the wrong function."""
        from capsules.runtime import SubprocessExecutor

        capsule = self.world.install(manifest_for())
        plan = self.world.runtime.build_plan(capsule, allow_unconfined=True)
        self.assertFalse(plan.confining)
        with self.assertRaises(CapsuleIsolationError):
            SubprocessExecutor().start(("/bin/true",), plan)

    def test_no_caller_outside_a_projection_asks_for_an_unconfined_plan(self) -> None:
        """Grepped rather than reasoned about. ``allow_unconfined=True`` is one
        keyword away from a fail-open, and the set of places that pass it is
        small enough to enumerate and important enough to pin."""
        import re

        from tests.support import ROOT

        allowed = {"companion/capsule_settings.py"}
        pattern = re.compile(r"allow_unconfined\s*=\s*True")

        def scan(extra: str = "") -> tuple[list[str], int]:
            found, looked = [], 0
            for path in sorted(ROOT.glob("*/*.py")) + sorted(ROOT.glob("*/*/*.py")):
                relative = path.relative_to(ROOT).as_posix()
                if relative.startswith(("tests/", "capsules/")) or relative in allowed:
                    continue
                looked += 1
                if pattern.search(path.read_text(encoding="utf-8", errors="replace")):
                    found.append(relative)
            if extra and pattern.search(extra):
                found.append("<planted>")
            return found, looked

        offenders, looked = scan()
        self.assertGreater(
            looked, 100,
            "the scan found almost nothing to read, so an empty result is not a result",
        )
        self.assertEqual(
            offenders, [],
            "a new caller asks for a plan with no confinement; if that is "
            "deliberate and read-only, add it to `allowed` with a reason",
        )
        # The check's own control: the pattern must actually match the thing it
        # is looking for, or the clean result above means nothing.
        self.assertEqual(scan("plan = build_plan(c, allow_unconfined=True)")[0], ["<planted>"])
        self.assertEqual(scan("plan = build_plan(c, allow_unconfined = True)")[0], ["<planted>"])


if __name__ == "__main__":
    unittest.main()
