# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""§33's scenario, end to end, minus the parts that need a screen.

The required vertical slice is: a person asks for something, Bunny offers a
commercial and a free option, the person chooses, the application opens in its
persistent capsule, Bunny asks for only the file that was named, the work
happens, the result is exported, the original is untouched, and the person can
afterwards see exactly what was used.

Everything in that sentence except "sees" is a value this suite can check. What
it cannot check is that a person looking at a screen understands it; that is the
VM and accessibility work, and the reports keep the two apart.
"""

from __future__ import annotations

import json
from pathlib import Path
import unittest

import catalog
from companion.capsule_bridge import (
    STEP_LABELS,
    CapsuleTaskCoordinator,
    RecordingTool,
    TaskWorkspace,
)
from companion.capsule_settings import application_settings, capsule_overview

from tests.capsule_support import World


class VerticalSliceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.world = World.build()
        self.addCleanup(self.world.close)
        self.tool = RecordingTool()
        self.coordinator = CapsuleTaskCoordinator(
            runtime=self.world.runtime,
            registry=self.world.registry,
            tool=self.tool,
            machine=catalog.MachineFacts(
                memory_bytes=16 * 1024**3, free_disk_bytes=200 * 1024**3, has_gpu=True, online=True
            ),
        )
        self.picture = self.world.file("Pictures/cat.png", b"ORIGINAL-PNG")

    def run_task(self, **kwargs):  # type: ignore[no-untyped-def]
        kwargs.setdefault("task_id", "task-1")
        kwargs.setdefault("capability", "remove-background")
        kwargs.setdefault("entry_id", "gimp")
        kwargs.setdefault("inputs", [self.picture])
        kwargs.setdefault("destination", self.world.home / "Pictures")
        kwargs.setdefault("request_text", "remove the background from this image")
        return self.coordinator.run(**kwargs)

    # -- the choice --------------------------------------------------------

    def test_the_person_is_offered_both_a_commercial_and_a_free_option(self) -> None:
        choices = self.coordinator.choices("remove-background")
        kinds = {choice.kind for choice in choices.choices}
        self.assertIn("commercial", kinds)
        self.assertIn("open-source", kinds)

    def test_an_installed_application_appears_as_installed_in_the_next_choice(self) -> None:
        self.world.answer(("files", "allow", "once"))
        self.run_task()
        again = self.coordinator.choices("remove-background")
        gimp = next(choice for choice in again.choices if choice.entry.entry_id == "gimp")
        self.assertTrue(gimp.installed)

    # -- the run -----------------------------------------------------------

    def test_the_whole_slice_completes(self) -> None:
        self.world.answer(("files", "allow", "once"))
        result = self.run_task()
        self.assertTrue(result.succeeded, result.failure)
        self.assertEqual(len(result.exports), 1)
        self.assertTrue(Path(result.exports[0].destination).exists())

    def test_only_the_named_file_is_asked_about(self) -> None:
        """§9: a graphics application does not get the whole Pictures folder
        because one image was opened."""
        self.world.answer(("files", "allow", "once"))
        result = self.run_task()
        self.assertEqual([decision.category for decision in result.decisions], ["files"])
        self.assertEqual(result.workspace.authorised_files, ("Pictures/cat.png",))

    def test_the_permission_asked_for_is_read_not_write(self) -> None:
        self.world.answer(("files", "allow", "once"))
        result = self.run_task()
        self.assertEqual(result.decisions[0].purpose, "read")

    def test_the_original_is_untouched_and_the_sentence_says_so(self) -> None:
        self.world.answer(("files", "allow", "once"))
        result = self.run_task()
        self.assertEqual(self.picture.read_bytes(), b"ORIGINAL-PNG")
        self.assertIn("Your original file wasn't changed", result.workspace.summary)

    def test_the_completion_sentence_names_where_the_result_went(self) -> None:
        self.world.answer(("files", "allow", "once"))
        result = self.run_task()
        self.assertIn(result.exports[0].display, result.workspace.summary)

    def test_the_application_ran_inside_its_own_capsule(self) -> None:
        self.world.answer(("files", "allow", "once"))
        result = self.run_task()
        self.assertIsNotNone(result.launch)
        self.assertEqual(result.launch.plan.identity.application_id, "org.gimp.GIMP")
        self.assertTrue(result.launch.plan.confining)

    def test_the_tool_only_ever_sees_the_sandbox_path(self) -> None:
        """The tool is handed /run/bunny/files/<digest>/cat.png, never the user's
        real path — so an application cannot learn the account name or the folder
        layout from the argument it is given."""
        self.world.answer(("files", "allow", "once"))
        self.run_task()
        _capability, inputs = self.tool.calls[0]
        self.assertTrue(inputs[0].startswith("/run/bunny/files/"))
        self.assertNotIn(str(self.world.home), inputs[0])

    def test_a_second_run_reuses_the_same_capsule(self) -> None:
        self.world.answer(("files", "allow", "always"))
        first = self.run_task()
        self.assertEqual(first.decisions[0].reason_code, "user-allowed")
        second = self.run_task(task_id="task-2")
        self.assertTrue(second.succeeded, second.failure)
        capsules_now = self.world.runtime.list()
        self.assertEqual(len([c for c in capsules_now if c.identity.application_id == "org.gimp.GIMP"]), 1)
        self.assertEqual(second.decisions[0].reason_code, "granted-previously")

    # -- refusals stop the task -------------------------------------------

    def test_a_refused_permission_stops_the_task_before_the_work(self) -> None:
        result = self.run_task()  # nothing scripted; the surface answers nothing
        self.assertEqual(result.state, "failed")
        self.assertEqual(self.tool.calls, [])
        self.assertEqual(
            [step.key for step in result.workspace.steps], ["choose", "install", "permission"]
        )
        self.assertEqual(result.workspace.steps[-1].state, "refused")

    def test_a_denied_permission_produces_no_export(self) -> None:
        self.world.answer(("files", "deny", "once"))
        result = self.run_task()
        self.assertEqual(result.exports, ())
        self.assertFalse(any(self.world.home.joinpath("Pictures").glob("*bunny*")))

    def test_an_application_with_no_linux_build_is_refused_with_its_own_words(self) -> None:
        result = self.run_task(entry_id="adobe-photoshop")
        self.assertEqual(result.state, "failed")
        self.assertIn("Linux", result.failure)

    def test_an_application_that_does_not_do_the_capability_is_refused(self) -> None:
        result = self.run_task(entry_id="evince")
        self.assertEqual(result.state, "failed")
        self.assertIn("does not do that", result.failure)

    def test_a_tool_that_raises_becomes_a_task_failure_not_a_traceback(self) -> None:
        class Exploding:
            def run(self, capsule, *, capability, inputs, output_directory):  # noqa: ANN001
                raise RuntimeError("the application crashed")

        self.coordinator.tool = Exploding()
        self.world.answer(("files", "allow", "once"))
        result = self.run_task()
        self.assertEqual(result.state, "failed")
        self.assertIn("could not finish", result.failure)


class WorkspaceProjectionTests(unittest.TestCase):
    """§16 and §17: what the panel carries, and what it must not."""

    def setUp(self) -> None:
        self.world = World.build()
        self.addCleanup(self.world.close)
        self.coordinator = CapsuleTaskCoordinator(runtime=self.world.runtime, registry=self.world.registry)
        self.picture = self.world.file("Pictures/cat.png", b"ORIGINAL")
        self.world.answer(("files", "allow", "once"))
        self.result = self.coordinator.run(
            task_id="task-1",
            capability="remove-background",
            entry_id="gimp",
            inputs=[self.picture],
            destination=self.world.home / "Pictures",
            request_text="remove the background",
        )

    def test_the_workspace_has_no_field_for_reasoning(self) -> None:
        fields = set(TaskWorkspace.__dataclass_fields__)
        for forbidden in ("reasoning", "thoughts", "chain_of_thought", "rationale", "deliberation", "plan_text"):
            self.assertNotIn(forbidden, fields)

    def test_every_step_label_comes_from_the_fixed_vocabulary(self) -> None:
        labels = set(STEP_LABELS.values())
        for step in self.result.workspace.steps:
            self.assertIn(step.label, labels)

    def test_the_workspace_matches_its_schema_shape(self) -> None:
        schema = json.loads(
            (Path(__file__).resolve().parents[2] / "schemas/capsule-task-workspace.schema.json").read_text(
                encoding="utf-8"
            )
        )
        record = dict(self.result.workspace.as_record())
        allowed = set(schema["properties"])
        self.assertEqual(set(record) - allowed, set())
        for required in schema["required"]:
            self.assertIn(required, record)

    def test_a_completed_task_offers_the_result_and_not_a_cancel(self) -> None:
        self.assertIn("view_result", self.result.workspace.actions)
        self.assertNotIn("cancel", self.result.workspace.actions)

    def test_pause_is_never_offered(self) -> None:
        """§16 permits Pause only when technically possible. For work inside a
        third-party application it is not, and offering one that behaved like a
        cancel would be worse than not offering it."""
        from companion.capsule_bridge import WORKSPACE_ACTIONS, _actions_for

        for state in ("preparing", "working", "waiting_for_you", "completed", "failed", "cancelled"):
            self.assertNotIn("pause", _actions_for(state))
        self.assertNotIn("pause", WORKSPACE_ACTIONS)

    def test_the_permission_list_shows_what_was_decided(self) -> None:
        entry = self.result.workspace.permissions[0]
        self.assertEqual(entry["category"], "files")
        self.assertEqual(entry["verdict"], "allow")
        self.assertEqual(entry["scope"], "once")


class SettingsProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.world = World.build()
        self.addCleanup(self.world.close)
        self.coordinator = CapsuleTaskCoordinator(runtime=self.world.runtime, registry=self.world.registry)
        self.picture = self.world.file("Pictures/cat.png")
        self.world.answer(("files", "allow", "always"))
        self.coordinator.run(
            task_id="task-1",
            capability="remove-background",
            entry_id="gimp",
            inputs=[self.picture],
            destination=self.world.home / "Pictures",
        )

    def test_settings_shows_what_the_application_can_reach(self) -> None:
        capsule = self.world.runtime.open("org.gimp.GIMP")
        page = application_settings(self.world.runtime, capsule, audit=self.world.audit, registry=self.world.registry)
        self.assertEqual(len(page.reachable_paths), 1)
        self.assertTrue(page.reachable_paths[0].endswith("cat.png"))

    def test_settings_distinguishes_granted_from_never_asked(self) -> None:
        capsule = self.world.runtime.open("org.gimp.GIMP")
        page = application_settings(self.world.runtime, capsule, audit=self.world.audit)
        standing = {row.category: row.standing for row in page.permissions}
        self.assertEqual(standing["files"], "granted")
        self.assertEqual(standing["notifications"], "not-asked")

    def test_every_permission_row_says_whether_it_is_enforced(self) -> None:
        capsule = self.world.runtime.open("org.gimp.GIMP")
        page = application_settings(self.world.runtime, capsule, audit=self.world.audit)
        for row in page.permissions:
            self.assertIsInstance(row.enforced, bool)
            self.assertTrue(row.enforcement)

    def test_the_revoke_note_says_when_the_withdrawal_takes_effect(self) -> None:
        capsule = self.world.runtime.open("org.gimp.GIMP")
        page = application_settings(self.world.runtime, capsule, audit=self.world.audit)
        files_row = next(row for row in page.permissions if row.category == "files")
        self.assertEqual(files_row.revocation, "next-launch")
        self.assertIn("next time", files_row.revoke_note)

    def test_the_activity_view_says_what_was_used(self) -> None:
        capsule = self.world.runtime.open("org.gimp.GIMP")
        page = application_settings(self.world.runtime, capsule, audit=self.world.audit)
        self.assertTrue(page.activity)
        self.assertTrue(any(entry.kind == "use" for entry in page.activity))

    def test_the_overview_lists_the_installed_capsules(self) -> None:
        overview = capsule_overview(self.world.runtime, audit=self.world.audit, registry=self.world.registry)
        ids = {application["applicationId"] for application in overview["applications"]}
        self.assertIn("org.gimp.GIMP", ids)
        self.assertEqual(overview["broken"], [])

    def test_a_running_capsule_blocks_maintenance_with_a_reason(self) -> None:
        capsule = self.world.runtime.open("org.gimp.GIMP")
        capsule.state.state = "running"
        page = application_settings(self.world.runtime, capsule, audit=self.world.audit)
        self.assertEqual(page.actions["reset"]["available"], "false")
        self.assertIn("Stop", page.actions["reset"]["blockedReason"])


if __name__ == "__main__":
    unittest.main()
