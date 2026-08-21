# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Phase 9: the model proposes, the user declines, and nothing happens.

This runs against the real trust gate, the real capsule runtime and the real
catalogue — :class:`tests.capsule_support.World` is the same fixture the capsule
suites use, so what is being tested is Bunny's authorization path and not a
model of it. The only thing that is new is where the proposal came from.

The assertions are deliberately about the *filesystem*, not about a return
value. "The result says it failed" is a claim about a data structure; "the
output file does not exist and the original is byte-identical" is a claim about
the machine, and it is the one that matters when the question is whether a
denial held.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import unittest

from companion.capsule_bridge import CapsuleTaskCoordinator
from companion.models.proposal import admit_proposal
from tests.capsule_support import World


class DeniedAction(unittest.TestCase):
    """User: "Resize holiday.png to 50%." Model: image.resize. User: no."""

    def setUp(self) -> None:
        self.world = World.build()
        self.addCleanup(self.world.close)
        self.coordinator = CapsuleTaskCoordinator(
            runtime=self.world.runtime, registry=self.world.registry
        )
        self.original = b"\x89PNG\r\n\x1a\n" + b"holiday-pixels" * 64
        self.picture = self.world.file("Pictures/holiday.png", self.original)
        self.digest_before = hashlib.sha256(self.picture.read_bytes()).hexdigest()

    def _propose(self) -> object:
        """What the model produced, admitted through the bridge's gate."""
        proposal = admit_proposal({"operation": "image.resize", "parameters": {"width": 512}})
        self.assertTrue(proposal.admitted, "the proposal itself is well-formed")
        return proposal

    def test_a_denied_approval_stops_the_task(self) -> None:
        proposal = self._propose()
        # No answer is scripted, so the surface answers nothing — which the gate
        # treats as a denial. This is the honest shape of "the user said no":
        # ScriptedSurface with an empty script fails closed.
        result = self.coordinator.run(
            task_id="task-denied",
            capability="resize-image",
            entry_id="bunny-image-tool",
            inputs=[self.picture],
            destination=self.world.home / "Pictures",
            request_text="Resize holiday.png to 50%.",
        )
        self.assertFalse(result.succeeded, result.workspace.as_record())

    def test_an_explicit_denial_stops_the_task(self) -> None:
        self.world.answer(("files", "deny", "once"))
        proposal = self._propose()
        result = self.coordinator.run(
            task_id="task-denied-explicit",
            capability="resize-image",
            entry_id="bunny-image-tool",
            inputs=[self.picture],
            destination=self.world.home / "Pictures",
            request_text="Resize holiday.png to 50%.",
        )
        self.assertFalse(result.succeeded)

    def test_no_output_file_is_created(self) -> None:
        self.world.answer(("files", "deny", "once"))
        self._propose()
        self.coordinator.run(
            task_id="task-denied-output",
            capability="resize-image",
            entry_id="bunny-image-tool",
            inputs=[self.picture],
            destination=self.world.home / "Pictures",
            request_text="Resize holiday.png to 50%.",
        )
        produced = sorted(
            path.name for path in (self.world.home / "Pictures").iterdir()
            if path.name != "holiday.png"
        )
        self.assertEqual(produced, [], f"a denied task produced {produced}")

    def test_the_original_is_untouched(self) -> None:
        self.world.answer(("files", "deny", "once"))
        self._propose()
        self.coordinator.run(
            task_id="task-denied-original",
            capability="resize-image",
            entry_id="bunny-image-tool",
            inputs=[self.picture],
            destination=self.world.home / "Pictures",
            request_text="Resize holiday.png to 50%.",
        )
        self.assertEqual(hashlib.sha256(self.picture.read_bytes()).hexdigest(),
                         self.digest_before)

    def test_nothing_was_executed(self) -> None:
        self.world.answer(("files", "deny", "once"))
        self._propose()
        self.coordinator.run(
            task_id="task-denied-exec",
            capability="resize-image",
            entry_id="bunny-image-tool",
            inputs=[self.picture],
            destination=self.world.home / "Pictures",
            request_text="Resize holiday.png to 50%.",
        )
        self.assertEqual(self.world.executor.launches, [],
                         "a denied task must not reach the capsule executor")

    def test_the_model_cannot_re_ask_its_way_past_a_denial(self) -> None:
        """A model that proposes again after "no" gets the stored denial.

        The trust layer records a denial at deny scope so the question is not
        re-asked, which means a model that retries is not a model that gets a
        second prompt in front of the user.
        """
        self.world.answer(("files", "deny", "always"))
        for attempt in range(3):
            self._propose()
            result = self.coordinator.run(
                task_id=f"task-retry-{attempt}",
                capability="resize-image",
                entry_id="bunny-image-tool",
                inputs=[self.picture],
                destination=self.world.home / "Pictures",
                request_text="Resize holiday.png to 50%.",
            )
            self.assertFalse(result.succeeded)
        self.assertEqual(self.world.executor.launches, [])

    def test_a_proposal_claiming_approval_never_reaches_the_gate(self) -> None:
        """The earlier refusal: it is stopped before any of this runs."""
        proposal = admit_proposal({
            "operation": "image.resize", "parameters": {"width": 512}, "approved": True,
        })
        self.assertFalse(proposal.admitted)
        self.assertEqual(self.world.surface.asked, [],
                         "a proposal claiming approval must not even produce a prompt")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
