# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Phase 10: the same proposal, approved, and the work actually happens.

The positive path matters as much as the negative one. A permission system that
denies everything is trivially secure and useless, and a test suite that only
proves denials would not notice if the approved path had stopped working.

What is asserted here is the part the bridge is responsible for: an admitted
proposal, once approved, reaches the capsule path, produces an exported
artefact, and leaves the input alone. The *pixels* are ``bunny-image-tool``'s
business and are exercised by the capsule suites against the real program; this
suite uses the coordinator's default :class:`~companion.capsule_bridge.
RecordingTool`, which performs the export path without asserting anything about
a third-party application's rendering. The heavy slice runs the real tool where
one is installed.

No security check is relaxed to make this pass. The only difference from
``test_denied_action.py`` is the answer the surface gives.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import unittest

from companion.capsule_bridge import CapsuleTaskCoordinator
from companion.models.proposal import admit_proposal
from tests.capsule_support import World


class ApprovedAction(unittest.TestCase):
    """User: "Resize holiday.png to 50%." Model: image.resize. User: yes."""

    def setUp(self) -> None:
        self.world = World.build()
        self.addCleanup(self.world.close)
        self.coordinator = CapsuleTaskCoordinator(
            runtime=self.world.runtime, registry=self.world.registry
        )
        self.original = b"\x89PNG\r\n\x1a\n" + b"holiday-pixels" * 64
        self.picture = self.world.file("Pictures/holiday.png", self.original)
        self.digest_before = hashlib.sha256(self.original).hexdigest()
        self.destination = self.world.home / "Pictures"

    def _run(self, task_id: str = "task-approved"):  # type: ignore[no-untyped-def]
        proposal = admit_proposal({"operation": "image.resize", "parameters": {"width": 512}})
        self.assertTrue(proposal.admitted)
        self.assertEqual(proposal.operation_id, "image.resize")
        self.world.answer(("files", "allow", "once"))
        return self.coordinator.run(
            task_id=task_id,
            capability="resize-image",
            entry_id="bunny-image-tool",
            inputs=[self.picture],
            destination=self.destination,
            request_text="Resize holiday.png to 50%.",
        )

    def test_the_task_succeeds(self) -> None:
        result = self._run()
        self.assertTrue(result.succeeded, result.workspace.as_record())

    def test_an_output_is_produced(self) -> None:
        self._run("task-approved-output")
        produced = sorted(
            path.name for path in self.destination.iterdir() if path.name != "holiday.png"
        )
        self.assertTrue(produced, "an approved task produced no artefact")

    def test_the_original_is_unchanged(self) -> None:
        self._run("task-approved-original")
        self.assertTrue(self.picture.is_file(), "the input was removed")
        self.assertEqual(hashlib.sha256(self.picture.read_bytes()).hexdigest(),
                         self.digest_before)

    def test_the_output_is_a_new_file_beside_the_original(self) -> None:
        self._run("task-approved-new")
        produced = [path for path in self.destination.iterdir() if path.name != "holiday.png"]
        self.assertEqual(len(produced), 1, [path.name for path in produced])
        self.assertNotEqual(produced[0].resolve(), self.picture.resolve())

    def test_the_permission_was_actually_asked_for(self) -> None:
        """Approved does not mean unasked. The prompt is part of the path."""
        self._run("task-approved-asked")
        self.assertTrue(self.world.surface.asked, "no permission prompt was raised")
        categories = {prompt.category for prompt in self.world.surface.asked}
        self.assertIn("files", categories)

    def test_the_workspace_records_what_happened(self) -> None:
        result = self._run("task-approved-record")
        record = result.workspace.as_record()
        self.assertIn("steps", record)
        self.assertTrue(record["steps"], "the workspace recorded no steps")

    def test_the_capability_was_resolved_through_the_catalogue(self) -> None:
        """The application comes from the catalogue, never from the proposal.

        The model said ``image.resize`` — a capability. Which program provides
        it is the catalogue's answer, and the workspace records the application
        id that was actually resolved. A proposal cannot name a program.
        """
        result = self._run("task-approved-capability")
        self.assertTrue(result.succeeded)
        record = result.workspace.as_record()
        self.assertEqual(record["applicationId"], "art.comrade.BunnyImageTool")
        self.assertTrue(record["authorisedFiles"], "no file was authorised")
        self.assertEqual(
            [Path(item).name for item in record["authorisedFiles"]], ["holiday.png"],
            "exactly the file the user named was authorised, and nothing else",
        )

    def test_only_the_named_file_was_authorised(self) -> None:
        """The neighbouring file is not swept in because it shares a folder."""
        other = self.world.file("Pictures/private.png", b"not part of this task")
        result = self._run("task-approved-scope")
        authorised = [Path(item).name for item in result.workspace.as_record()["authorisedFiles"]]
        self.assertNotIn("private.png", authorised)
        self.assertEqual(other.read_bytes(), b"not part of this task")

    def test_a_second_identical_proposal_still_requires_its_own_grant(self) -> None:
        """A once-scoped grant is once. The model does not accumulate authority."""
        self._run("task-approved-first")
        # No new answer is scripted, so the second run has nothing to consume.
        proposal = admit_proposal({"operation": "image.resize", "parameters": {"width": 512}})
        self.assertTrue(proposal.admitted)
        second = self.coordinator.run(
            task_id="task-approved-second",
            capability="resize-image",
            entry_id="bunny-image-tool",
            inputs=[self.picture],
            destination=self.destination,
            request_text="Resize holiday.png to 50%.",
        )
        self.assertFalse(second.succeeded,
                         "a once-scoped approval must not carry into a second task")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
