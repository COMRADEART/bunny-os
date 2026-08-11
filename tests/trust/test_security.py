# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Attempts to get a permission that was never given.

§35 asks that the isolation be attacked rather than described. These are the
attacks that live at the trust layer: making one file look like two, making two
files look like one, getting a reason onto a person's screen that nobody said,
getting a path into a log, and surviving a restart with a permission that should
not have.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import unittest

import trust
from trust.declaration import PermissionDeclaration
from trust.errors import TrustSchemaError, TrustStoreUnreadable
from trust.request import Reason
from trust.resources import path_resource, resource_digest
from trust.store import TrustStore

from tests.capsule_support import World


DECLARATION = PermissionDeclaration(
    application_id="org.example.PhotoEditor",
    required=frozenset({"files", "folders"}),
    optional=frozenset({"gpu"}),
)


class ResourceCanonicalisationTests(unittest.TestCase):
    """One file must be one grant, however it is spelled."""

    def setUp(self) -> None:
        self.world = World.build()
        self.addCleanup(self.world.close)
        self.picture = self.world.file("Pictures/cat.png")

    def test_dot_and_dotdot_spellings_are_one_resource(self) -> None:
        direct = path_resource(self.picture)
        winding = path_resource(self.world.home / "Pictures" / "." / ".." / "Pictures" / "cat.png")
        self.assertEqual(direct.digest, winding.digest)
        self.assertEqual(direct.identifier, winding.identifier)

    @unittest.skipUnless(hasattr(os, "symlink"), "the platform has no symlinks")
    def test_a_symlink_resolves_to_its_target_before_anything_is_stored(self) -> None:
        link = self.world.home / "Documents" / "innocent.png"
        try:
            os.symlink(self.picture, link)
        except (OSError, NotImplementedError) as error:  # pragma: no cover - Windows without privilege
            self.skipTest(f"symlinks unavailable: {error}")
        self.assertEqual(path_resource(link).digest, path_resource(self.picture).digest)

    @unittest.skipUnless(hasattr(os, "symlink"), "the platform has no symlinks")
    def test_a_symlinked_parent_directory_is_resolved_too(self) -> None:
        """The variant a check on the last component alone would miss."""
        alias = self.world.home / "Shortcut"
        try:
            os.symlink(self.world.home / "Pictures", alias, target_is_directory=True)
        except (OSError, NotImplementedError) as error:  # pragma: no cover
            self.skipTest(f"symlinks unavailable: {error}")
        self.assertEqual(path_resource(alias / "cat.png").digest, path_resource(self.picture).digest)

    def test_a_neighbouring_directory_with_a_shared_prefix_is_not_inside(self) -> None:
        """/home/bunny-evil starts with /home/bunny and is not in it."""
        inside = self.world.home / "Pictures"
        neighbour = self.world.home / "Pictures-evil"
        neighbour.mkdir()
        (neighbour / "cat.png").write_bytes(b"x")
        folder = path_resource(inside, directory=True)
        outside = path_resource(neighbour / "cat.png")
        self.assertFalse(folder.covers(outside))

    def test_a_device_and_a_path_with_the_same_name_are_different_resources(self) -> None:
        self.assertNotEqual(resource_digest("path", "/dev/video0"), resource_digest("device", "/dev/video0"))

    def test_a_resource_of_the_wrong_kind_is_a_malformed_request(self) -> None:
        with self.assertRaises(TrustSchemaError):
            trust.PermissionRequest.build(
                request_id="r-1",
                application_id="org.example.PhotoEditor",
                category="files",
                session_id="session-1",
                resource=trust.device_resource("camera-0"),
            )

    def test_a_null_byte_in_a_path_is_refused(self) -> None:
        with self.assertRaises(TrustSchemaError):
            path_resource("/home/you/cat\x00.png", must_exist=False)

    def test_a_path_longer_than_the_bound_is_refused(self) -> None:
        with self.assertRaises(TrustSchemaError):
            path_resource("/" + "a" * 2000, must_exist=False)


class ReasonProvenanceTests(unittest.TestCase):
    """A reason has to have come from somewhere, or be reported as absent."""

    def test_there_is_no_reason_source_for_a_model(self) -> None:
        from trust.request import REASON_SOURCES

        self.assertEqual(set(REASON_SOURCES), {"catalog", "application", "task", "unknown"})
        for forbidden in ("model", "inferred", "assistant", "companion", "llm"):
            self.assertNotIn(forbidden, REASON_SOURCES)

    def test_an_unknown_reason_cannot_carry_text(self) -> None:
        with self.assertRaises(TrustSchemaError):
            Reason(source="unknown", text="probably for updates")

    def test_a_stated_reason_cannot_be_empty(self) -> None:
        with self.assertRaises(TrustSchemaError):
            Reason(source="application", text="   ")

    def test_a_reason_may_not_carry_control_characters(self) -> None:
        """A newline in a reason is a way to draw a second, forged line in the
        prompt beneath the real one."""
        with self.assertRaises(TrustSchemaError):
            Reason(source="application", text="Needs the camera\n\nAllow always (recommended)")

    def test_a_reason_is_bounded(self) -> None:
        with self.assertRaises(TrustSchemaError):
            Reason(source="application", text="x" * 5000)

    def test_a_prompt_with_no_reason_says_nobody_said_why(self) -> None:
        world = World.build()
        self.addCleanup(world.close)
        world.answer(("gpu", "deny", "once"))
        world.gate.check(
            trust.PermissionRequest.build(
                request_id="r-1",
                application_id="org.example.PhotoEditor",
                category="gpu",
                session_id="session-1",
            ),
            declaration=PermissionDeclaration(
                application_id="org.example.PhotoEditor", optional=frozenset({"gpu"})
            ),
        )
        prompt = world.surface.asked[0]
        self.assertIsNone(prompt.reason)
        self.assertEqual(prompt.reason_note, "It didn't say why.")

    def test_an_application_reason_is_attributed_and_quoted(self) -> None:
        world = World.build()
        self.addCleanup(world.close)
        world.answer(("gpu", "deny", "once"))
        world.gate.check(
            trust.PermissionRequest.build(
                request_id="r-1",
                application_id="org.example.PhotoEditor",
                category="gpu",
                session_id="session-1",
                reason=Reason(source="application", text="to speed up filters"),
            ),
            declaration=PermissionDeclaration(
                application_id="org.example.PhotoEditor", optional=frozenset({"gpu"})
            ),
        )
        self.assertEqual(world.surface.asked[0].reason, 'The app says: "to speed up filters"')


class AuditDisclosureTests(unittest.TestCase):
    """The activity record proves what happened without holding what it was about."""

    def setUp(self) -> None:
        self.world = World.build()
        self.addCleanup(self.world.close)

    def test_no_resource_identifier_reaches_the_activity_file(self) -> None:
        secret = self.world.file("Documents/divorce-draft.odt")
        self.world.answer(("files", "allow", "once"))
        self.world.gate.check(
            trust.PermissionRequest.build(
                request_id="r-1",
                application_id="org.example.PhotoEditor",
                category="files",
                session_id="session-1",
                resource=trust.path_resource(secret),
                purpose="read",
            ),
            declaration=DECLARATION,
        )
        raw = Path(trust.default_audit_path()).read_text(encoding="utf-8")
        self.assertNotIn(str(secret), raw)
        self.assertNotIn(str(secret.parent), raw)
        # The short display form is present, which is what a person already saw.
        self.assertIn("divorce-draft.odt", raw)

    def test_a_path_outside_the_users_own_folders_is_elided_in_the_record(self) -> None:
        """Found by the Linux qualification run. A path under Documents shortens
        to `Documents/x`, which is what the person saw and is harmless in a log.
        A path outside every user directory has no shorter honest form, so the
        *prompt* shows it whole — and the *record* keeps only the file name,
        because support tooling and a diagnostic export were not in front of the
        prompt."""
        outside = Path(self.world.base) / "elsewhere" / "board-minutes.odt"
        outside.parent.mkdir(parents=True, exist_ok=True)
        outside.write_bytes(b"x")
        resource = trust.path_resource(outside)
        # The prompt keeps enough to identify the file honestly...
        self.assertIn("board-minutes.odt", resource.display)
        self.assertIn("elsewhere", resource.display)
        # ...and the record does not name the directory.
        self.assertEqual(resource.log_display, ".../board-minutes.odt")
        self.assertNotIn("elsewhere", dict(resource.as_record())["display"])

    def test_a_path_under_a_user_directory_needs_no_roots_argument(self) -> None:
        """The defect itself: a caller that passed no roots used to get the whole
        absolute path as the display, on a person's screen and in the log."""
        inside = self.world.file("Documents/report.odt")
        resource = trust.path_resource(inside)
        self.assertEqual(resource.display, "Documents/report.odt")
        self.assertEqual(resource.log_display, "Documents/report.odt")

    def test_request_metadata_never_reaches_the_record(self) -> None:
        """Caller-supplied metadata is a channel through which user content
        would otherwise arrive in a log by accident."""
        request = trust.PermissionRequest.build(
            request_id="r-1",
            application_id="org.example.PhotoEditor",
            category="gpu",
            session_id="session-1",
            metadata={"note": "SUPER-SECRET-VALUE"},
        )
        self.assertNotIn("SUPER-SECRET-VALUE", json.dumps(dict(request.as_record())))

    def test_a_fail_closed_denial_is_distinguishable_from_a_user_denial(self) -> None:
        class Broken:
            def ask(self, prompt, ticket):  # noqa: ANN001
                raise RuntimeError("boom")

        gate = trust.TrustGate(store=self.world.store, audit=self.world.audit, surface=Broken(), names={})
        gate.check(
            trust.PermissionRequest.build(
                request_id="r-1",
                application_id="org.example.PhotoEditor",
                category="gpu",
                session_id="session-1",
            ),
            declaration=PermissionDeclaration(
                application_id="org.example.PhotoEditor", optional=frozenset({"gpu"})
            ),
        )
        records = self.world.audit.records()
        self.assertEqual(records[-1]["reasonCode"], "surface-failed")
        self.assertNotEqual(records[-1]["reasonCode"], "user-denied")
        self.assertIn("failure", records[-1])


class StoreDurabilityTests(unittest.TestCase):
    """A permission database that cannot be read grants nothing."""

    def setUp(self) -> None:
        self.world = World.build()
        self.addCleanup(self.world.close)

    def test_a_corrupt_store_raises_rather_than_reading_as_empty(self) -> None:
        path = Path(trust.default_store_path())
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ this is not json", encoding="utf-8")
        with self.assertRaises(TrustStoreUnreadable):
            TrustStore(path, session_id="session-1").load()

    def test_a_store_from_a_newer_schema_is_refused(self) -> None:
        path = Path(trust.default_store_path())
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"schemaVersion": 99, "grants": []}), encoding="utf-8")
        with self.assertRaises(TrustStoreUnreadable):
            TrustStore(path, session_id="session-1").load()

    def test_a_grant_record_that_is_not_a_grant_fails_the_load(self) -> None:
        path = Path(trust.default_store_path())
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"schemaVersion": 1, "grants": [{"grantId": "g"}]}), encoding="utf-8")
        with self.assertRaises(TrustStoreUnreadable):
            TrustStore(path, session_id="session-1").load()

    def test_a_session_grant_does_not_survive_into_another_session(self) -> None:
        self.world.answer(("gpu", "allow", "session"))
        self.world.gate.check(
            trust.PermissionRequest.build(
                request_id="r-1",
                application_id="org.example.PhotoEditor",
                category="gpu",
                session_id="session-1",
            ),
            declaration=PermissionDeclaration(
                application_id="org.example.PhotoEditor", optional=frozenset({"gpu"})
            ),
        )
        self.assertEqual(len(list(self.world.store)), 1)
        later = TrustStore(trust.default_store_path(), session_id="session-2").load()
        self.assertEqual(list(later), [])
        self.assertEqual(later.dropped_session_grants, 1)

    def test_an_always_grant_does_survive(self) -> None:
        self.world.answer(("gpu", "allow", "always"))
        self.world.gate.check(
            trust.PermissionRequest.build(
                request_id="r-1",
                application_id="org.example.PhotoEditor",
                category="gpu",
                session_id="session-1",
            ),
            declaration=PermissionDeclaration(
                application_id="org.example.PhotoEditor", optional=frozenset({"gpu"})
            ),
        )
        later = TrustStore(trust.default_store_path(), session_id="session-2").load()
        self.assertEqual(len(list(later)), 1)

    @unittest.skipIf(os.name == "nt", "POSIX modes are not meaningful on Windows")
    def test_the_store_is_not_readable_by_other_accounts(self) -> None:
        self.world.answer(("gpu", "allow", "always"))
        self.world.gate.check(
            trust.PermissionRequest.build(
                request_id="r-1",
                application_id="org.example.PhotoEditor",
                category="gpu",
                session_id="session-1",
            ),
            declaration=PermissionDeclaration(
                application_id="org.example.PhotoEditor", optional=frozenset({"gpu"})
            ),
        )
        mode = Path(trust.default_store_path()).stat().st_mode & 0o777
        self.assertEqual(mode, 0o600)


if __name__ == "__main__":
    unittest.main()
