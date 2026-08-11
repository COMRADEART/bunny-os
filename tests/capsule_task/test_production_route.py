# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The route from a Companion task to a confined process, asserted end to end.

This file exists because of a specific defect: ``companion/capsule_bridge.py``
was complete, correct, qualified on a Linux host and inside a booted guest — and
had no caller. Every property the qualification measured was a property of a
path the product never took. Nothing failed, which is what made it survive.

So the tests here are not about whether a capsule confines. That is measured by
``scripts/capsules/`` against a real kernel, and repeating it with fixtures would
be a weaker copy of a stronger test. These are about whether the *route* exists
and stays connected:

* a plan naming an operation reaches the capsule support and nothing else;
* the person is asked before the file is exposed, not after;
* the act executed is the act approved, compared field by field;
* the answer cannot be spent twice, on another file, or by the renderer;
* a failure is a failure, and never "completed".

The route-existence test is deliberately behavioural rather than a grep. A grep
for ``capsule_bridge`` would have passed on the day the import existed and the
call did not, and it would pass again the day somebody replaces the call with a
stub. What cannot pass is a launch that did not happen.
"""

from __future__ import annotations

from pathlib import Path
import unittest

from capsules.runtime import RecordingExecutor
from companion.approvals import ApprovalRequirement
from companion.capsule_task_bridge import (
    CAPSULE_TOOL_IDS,
    ApprovedActSurface,
    CapsuleSupport,
    CapsuleToolContext,
    capsule_tool_declarations,
    register_capsule_tools,
)
from companion.capsule_tasks import FAILURE_CODES, OPERATIONS
from companion.executor import PlannedOperation
from companion.task import CompanionTask
from companion.tools import ToolBroker

from tests.capsule_support import World, unconfined_probe


class _Plan:
    """The two attributes the bridge reads off a plan. Nothing else is used."""

    plan_id = "plan-1"
    fingerprint = "fp-1"


def _task(task_id: str = "task-1", request: str = "Resize this to 1024 pixels wide.") -> CompanionTask:
    return CompanionTask.create(
        task_id=task_id,
        session_id="session-1",
        request=request,
        classification="personal",
        now=0.0,
    )


def _operation(width: int = 1024) -> PlannedOperation:
    return PlannedOperation(name="resize", tool="image.resize", arguments={"width": width})


class RouteFixture(unittest.TestCase):
    """A world with a real support object over a recording executor.

    The executor records rather than starts: this suite runs on every developer
    machine including ones with no user namespaces, and a suite that needed a
    kernel feature would silently stop testing the route on the machines where
    it does not exist. What it records is the *argument vector*, which is the
    thing that proves a launch was asked for and what it was asked to run.
    """

    def setUp(self) -> None:
        self.world = World.build()
        self.addCleanup(self.world.close)
        self.source = self.world.file("Pictures/holiday.png", b"\x89PNG\r\n\x1a\n" + b"x" * 64)
        self.destination = self.world.home / "Pictures"
        self.support = CapsuleSupport(
            runtime=self.world.runtime,
            registry=self.world.registry,
            store=self.world.store,
            audit=self.world.audit,
            gate=self.world.gate,
            destination=self.destination,
        )
        self.task = _task()
        self.plan = _Plan()
        self.support.bind_inputs(self.task.task_id, [self.source])

    def prepare(self, operation: PlannedOperation | None = None) -> ApprovalRequirement:
        return self.support.requirement_for(self.task, self.plan, operation or _operation())

    def approved_context(self, operation: PlannedOperation | None = None) -> CapsuleToolContext:
        operation = operation or _operation()
        self.prepare(operation)
        return self.support.context_for(self.task, self.plan, operation)


class TheRouteExists(RouteFixture):
    def test_the_operation_is_a_registered_tool(self) -> None:
        broker = ToolBroker()
        added = register_capsule_tools(broker, self.support)
        self.assertEqual(added, CAPSULE_TOOL_IDS)
        self.assertIn("image.resize", broker.tools)

    def test_a_registered_declaration_asks_the_user_first(self) -> None:
        """``interrupts_user`` is what makes the runtime raise an approval. A
        declaration without it would run the operation with no question."""
        for declaration in capsule_tool_declarations():
            with self.subTest(tool=declaration.tool_id):
                self.assertTrue(declaration.sensitive, declaration.tool_id)
                self.assertTrue(declaration.requires_context, declaration.tool_id)

    def test_invoking_the_tool_reaches_a_real_capsule_launch(self) -> None:
        """The whole point. A launch was asked for, with the operation's own
        argument vector, naming the program from the catalogue manifest."""
        broker = ToolBroker()
        register_capsule_tools(broker, self.support)
        context = self.approved_context()
        broker.invoke(
            "image.resize", {"width": 1024}, caller="runtime", context=context,
            classification="personal",
        )
        launches = self.world.executor.launches
        self.assertTrue(launches, "no launch was ever asked for; the route is not connected")
        vector = launches[-1]
        self.assertIn("/usr/libexec/bunny-image-tool", vector)
        self.assertIn("resize", vector)
        self.assertIn("--width", vector)
        self.assertIn("1024", vector)

    def test_the_launch_names_the_sandbox_output_path_and_not_the_users(self) -> None:
        """The program is told where to write *inside* the capsule. A vector
        naming the user's own directory would be a program with write access to
        it, which is the thing the export boundary exists to avoid."""
        broker = ToolBroker()
        register_capsule_tools(broker, self.support)
        broker.invoke(
            "image.resize", {"width": 1024}, caller="runtime",
            context=self.approved_context(), classification="personal",
        )
        vector = self.world.executor.launches[-1]
        output = vector[vector.index("--output") + 1]
        self.assertTrue(output.startswith("/run/bunny/app/exports/"), output)
        self.assertNotIn(str(self.destination), " ".join(vector))

    def test_the_runtime_dispatches_the_tool_to_this_support(self) -> None:
        """The other half of the route: the runtime must find the support that
        owns the tool, or the context above is built by nobody."""
        from companion.runtime import CompanionRuntime

        # The dispatch is a pure function of the two support slots, so it is
        # called against an object carrying only those. Building a whole runtime
        # would need an event store this suite has no business creating, and
        # would test the store rather than the lookup.
        stub = type("Stub", (), {
            "desktop": None,
            "capsules": self.support,
            "_tool_supports": CompanionRuntime._tool_supports,
            "_tool_support": CompanionRuntime._tool_support,
        })()
        self.assertEqual(stub._tool_supports(), (self.support,))
        self.assertIs(stub._tool_support("image.resize"), self.support)
        self.assertIsNone(stub._tool_support("text.count_words"))

    def test_the_service_enables_capsules_by_default(self) -> None:
        """A route that ships turned off is a route that does not ship."""
        import tempfile

        from companion.service import RELEASE_ORDER, ServiceOptions

        options = ServiceOptions(root=Path(tempfile.mkdtemp()))
        self.assertTrue(options.capsules_enabled)
        self.assertIn("capsules", RELEASE_ORDER)
        self.assertLess(
            RELEASE_ORDER.index("capsules"), RELEASE_ORDER.index("task-worker"),
            "a capsule that outlives the worker join makes the join wait out the "
            "operation timeout the release would have cut short",
        )


class TheUserIsAskedFirst(RouteFixture):
    def test_the_requirement_names_the_file_and_the_application(self) -> None:
        requirement = self.prepare()
        self.assertEqual(requirement.action, "launch_application")
        self.assertIn("holiday.png", requirement.reason)
        self.assertIn("Bunny Image Tool", requirement.reason)
        self.assertFalse(requirement.leaves_device)
        self.assertTrue(requirement.alternatives)

    def test_the_reason_names_no_mechanism(self) -> None:
        """§49. A person is told what will happen, not how it is enforced."""
        reason = self.prepare().reason.lower()
        for word in ("bwrap", "bubblewrap", "namespace", "seccomp", "cgroup", "systemd", "eperm"):
            self.assertNotIn(word, reason)

    def test_nothing_launches_without_a_context(self) -> None:
        """An invocation with no authority facts is refused before anything."""
        outcome = self.support.invoke("image.resize", {"width": 1024}, context=None)
        self.assertFalse(outcome.ok)
        self.assertEqual(self.world.executor.launches, [])

    def test_nothing_launches_without_an_approval(self) -> None:
        context = self.approved_context()
        unapproved = CapsuleToolContext(
            session_id=context.session_id,
            task_id=context.task_id,
            lifecycle_epoch=context.lifecycle_epoch,
            plan_id=context.plan_id,
            plan_fingerprint=context.plan_fingerprint,
            operation_id=context.operation_id,
            classification=context.classification,
            approval_reference="",
            approved_binding=None,
        )
        outcome = self.support.invoke("image.resize", {"width": 1024}, context=unapproved)
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.value["failure"]["code"], "PERMISSION_DENIED")
        self.assertEqual(self.world.executor.launches, [])

    def test_an_operation_that_was_never_prepared_cannot_run(self) -> None:
        """A context forged with a plausible reference still finds no prepared
        act, because preparation is what happens when the question is asked."""
        forged = CapsuleToolContext(
            session_id="session-1", task_id="task-1", lifecycle_epoch=1,
            plan_id="plan-1", plan_fingerprint="fp-1", operation_id="resize",
            classification="personal",
            approval_reference="task-1:image.resize:holiday-resized.png",
            approved_binding={"kind": "capsule-task"},
        )
        outcome = self.support.invoke("image.resize", {"width": 1024}, context=forged)
        self.assertFalse(outcome.ok)
        self.assertEqual(self.world.executor.launches, [])


class TheApprovedActIsTheExecutedAct(RouteFixture):
    def test_a_changed_binding_is_refused(self) -> None:
        context = self.approved_context()
        tampered = CapsuleToolContext(
            session_id=context.session_id, task_id=context.task_id,
            lifecycle_epoch=context.lifecycle_epoch, plan_id=context.plan_id,
            plan_fingerprint=context.plan_fingerprint, operation_id=context.operation_id,
            classification=context.classification,
            approval_reference=context.approval_reference,
            approved_binding={**dict(context.approved_binding), "parameters": {"width": 4096}},
        )
        outcome = self.support.invoke("image.resize", {"width": 4096}, context=tampered)
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.value["failure"]["code"], "SECURITY_POLICY_BLOCKED")
        self.assertEqual(self.world.executor.launches, [])

    def test_a_file_swapped_after_approval_is_refused(self) -> None:
        """§11's substitution check. The binding carries the digest of the bytes
        the person was shown, and it is compared immediately before launch."""
        context = self.approved_context()
        self.source.write_bytes(b"\x89PNG\r\n\x1a\n" + b"different" * 16)
        outcome = self.support.invoke("image.resize", {"width": 1024}, context=context)
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.value["failure"]["code"], "SECURITY_POLICY_BLOCKED")
        self.assertEqual(self.world.executor.launches, [])

    def test_a_file_removed_after_approval_is_refused(self) -> None:
        context = self.approved_context()
        self.source.unlink()
        outcome = self.support.invoke("image.resize", {"width": 1024}, context=context)
        self.assertFalse(outcome.ok)
        self.assertEqual(self.world.executor.launches, [])

    def test_the_binding_changes_when_the_width_changes(self) -> None:
        """Two different acts must not share a fingerprint, or one approval
        would authorise the other.

        The preparation cache is keyed on (task, plan fingerprint, operation
        name) and *not* on the arguments, which is only safe because a plan's
        fingerprint covers its operations' arguments. That dependency is
        asserted directly below; here the two plans are given the different
        fingerprints a real replan would produce.
        """
        first = self.prepare(_operation(1024))
        other_plan = type("P", (), {"plan_id": "plan-2", "fingerprint": "fp-2"})
        second = self.support.requirement_for(self.task, other_plan, _operation(512))
        self.assertNotEqual(first.fingerprint, second.fingerprint)

    def test_a_plan_fingerprint_covers_its_operations_arguments(self) -> None:
        """The property the preparation cache rests on. If a plan's fingerprint
        stopped covering arguments, two different widths would share a cache key
        and the second would silently execute the first's prepared act."""
        from companion.executor import plan_fingerprint

        self.assertNotEqual(
            plan_fingerprint([_operation(1024)], "resize"),
            plan_fingerprint([_operation(512)], "resize"),
        )


class TheConsentSurfaceCannotBeAbused(unittest.TestCase):
    """:class:`ApprovedActSurface` is the adapter between two authorities. It is
    also the only place a Trust ``allow`` is produced without a person present,
    so every way it could produce one wrongly is a test."""

    def _prompt(self, application_id="art.comrade.BunnyImageTool", category="files", resource="Pictures/holiday.png"):
        return type("P", (), {
            "application_id": application_id, "category": category, "resource_display": resource,
        })()

    def _ticket(self):
        return type("T", (), {"ticket_id": "ticket-1"})()

    def _surface(self, **overrides):
        base = dict(
            application_id="art.comrade.BunnyImageTool",
            category="files",
            resource_display="Pictures/holiday.png",
            verdict="allow",
        )
        base.update(overrides)
        return ApprovedActSurface(**base)

    def test_it_answers_the_question_it_was_built_for(self) -> None:
        answer = self._surface().ask(self._prompt(), self._ticket())
        self.assertIsNotNone(answer)
        self.assertEqual(answer.verdict, "allow")

    def test_it_answers_only_once(self) -> None:
        surface = self._surface()
        self.assertIsNotNone(surface.ask(self._prompt(), self._ticket()))
        self.assertIsNone(surface.ask(self._prompt(), self._ticket()))

    def test_it_refuses_another_file(self) -> None:
        surface = self._surface()
        self.assertIsNone(surface.ask(self._prompt(resource="Pictures/other.png"), self._ticket()))

    def test_it_refuses_another_application(self) -> None:
        surface = self._surface()
        self.assertIsNone(surface.ask(self._prompt(application_id="org.gimp.GIMP"), self._ticket()))

    def test_it_refuses_another_category(self) -> None:
        """The person allowed a file. An application asking for the camera on
        the strength of that answer gets nothing."""
        surface = self._surface()
        self.assertIsNone(surface.ask(self._prompt(category="camera"), self._ticket()))

    def test_a_denial_cannot_become_an_allow(self) -> None:
        surface = self._surface(verdict="deny")
        self.assertIsNone(surface.ask(self._prompt(), self._ticket()))

    def test_every_question_it_was_shown_is_recorded(self) -> None:
        surface = self._surface()
        surface.ask(self._prompt(), self._ticket())
        surface.ask(self._prompt(category="camera"), self._ticket())
        self.assertEqual([item["matched"] for item in surface.seen], [True, False])


class TheFailuresAreTyped(RouteFixture):
    def test_a_machine_that_cannot_confine_refuses_and_launches_nothing(self) -> None:
        """§24. No fallback exists, so this is a refusal with a code, and the
        sentence a person reads says Bunny did not run it."""
        world = World.build(probe=unconfined_probe())
        self.addCleanup(world.close)
        source = world.file("Pictures/holiday.png", b"\x89PNG\r\n\x1a\n" + b"x" * 64)
        support = CapsuleSupport(
            runtime=world.runtime, registry=world.registry, store=world.store,
            audit=world.audit, gate=world.gate, destination=world.home / "Pictures",
        )
        support.bind_inputs("task-1", [source])
        task, plan, operation = _task(), _Plan(), _operation()
        support.requirement_for(task, plan, operation)
        outcome = support.invoke(
            "image.resize", {"width": 1024},
            context=support.context_for(task, plan, operation),
        )
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.value["failure"]["code"], "CAPSULE_BACKEND_UNAVAILABLE")
        self.assertIn("didn't run it", outcome.detail)
        self.assertEqual(world.executor.launches, [])

    def test_every_declared_code_has_a_sentence(self) -> None:
        from companion.capsule_tasks import FAILURE_SENTENCES

        self.assertEqual(sorted(FAILURE_SENTENCES), sorted(FAILURE_CODES))
        for code, sentence in FAILURE_SENTENCES.items():
            with self.subTest(code=code):
                self.assertTrue(sentence.endswith("."), code)
                for word in ("bwrap", "namespace", "EPERM", "cgroup", "seccomp"):
                    self.assertNotIn(word, sentence, code)

    def test_an_unknown_operation_is_refused_rather_than_defaulted(self) -> None:
        from companion.capsule_tasks import CapsuleTaskFailure, operation as descriptor_for

        with self.assertRaises(CapsuleTaskFailure) as caught:
            descriptor_for("image.enhance")
        self.assertEqual(caught.exception.code, "SECURITY_POLICY_BLOCKED")

    def test_an_unknown_parameter_is_refused_rather_than_ignored(self) -> None:
        """An ignored parameter is one somebody believes is in effect."""
        from companion.capsule_tasks import CapsuleTaskFailure

        with self.assertRaises(CapsuleTaskFailure):
            OPERATIONS["image.resize"].validate({"width": 1024, "quality": 90})

    def test_a_width_that_is_not_a_bounded_integer_is_refused(self) -> None:
        from companion.capsule_tasks import CapsuleTaskFailure

        for value in ("1024", 1024.0, True, 0, 99999, -1):
            with self.subTest(value=value), self.assertRaises(CapsuleTaskFailure):
                OPERATIONS["image.resize"].validate({"width": value})


if __name__ == "__main__":
    unittest.main()
