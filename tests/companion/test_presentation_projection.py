# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The projection: every canonical event maps, and nothing else gets through.

These are the §22 projection tests. They run without a display and without a
socket, because the projection is a pure function over events — which is the
property that makes the surface testable at all.
"""

from __future__ import annotations

import json
from pathlib import Path
import unittest

from companion.events import EVENT_TYPES, build_event
from companion.presentation import (
    AccessibilityPreferences,
    EVENT_PHASES,
    IMPLEMENTED_PRESENTATIONS,
    PHASE_PRIORITY,
    PRESENTATION_KINDS,
    PRESENTATION_PHASES,
    PresentationProjector,
    PresentationSignals,
    TASK_STATE_PHASES,
    WindowPreferences,
    DesktopContext,
    escape_markup,
    project_presentation,
    resolve_phase,
    select_presentation,
    window_directive,
)
from companion.states import STATES

from .support import FULL_REQUEST, SIMPLE_REQUEST, CompanionTestCase

SCHEMAS = Path(__file__).resolve().parents[2] / "schemas"

#: §12's priority, verbatim. Kept as a literal so that reordering
#: PHASE_PRIORITY has to break this rather than quietly agree with itself.
SPECIFIED_ORDER = (
    "error", "blocked", "waiting_for_approval", "listening", "speaking",
    "working", "reviewing", "success", "idle",
)


class MappingTests(unittest.TestCase):
    """The tables cover the vocabularies they claim to."""

    def test_every_canonical_event_type_has_a_phase(self) -> None:
        self.assertEqual(set(EVENT_TYPES), set(EVENT_PHASES))

    def test_every_canonical_task_state_has_a_phase(self) -> None:
        self.assertEqual(set(STATES), set(TASK_STATE_PHASES))

    def test_every_mapped_phase_is_a_declared_phase(self) -> None:
        mapped = set(EVENT_PHASES.values()) | set(TASK_STATE_PHASES.values())
        self.assertTrue(mapped - {""} <= set(PRESENTATION_PHASES))

    def test_the_specified_priority_order_survives(self) -> None:
        positions = [PHASE_PRIORITY.index(name) for name in SPECIFIED_ORDER]
        self.assertEqual(positions, sorted(positions))

    def test_every_phase_is_ranked_exactly_once(self) -> None:
        self.assertEqual(sorted(PHASE_PRIORITY), sorted(PRESENTATION_PHASES))

    def test_only_implemented_presentations_can_be_selected(self) -> None:
        """A rung joins this ladder only when a renderer is behind it.

        ``animated-2d`` was absent until :mod:`companion.character.animated_renderer`
        existed. The two 3D rungs were absent for the same reason until
        :mod:`companion.character.three_d.renderer` existed, and this test was
        the line that held them out — so it is the line that now has to say what
        let them in, rather than simply be deleted.

        What let them in is a renderer module *and* a test that draws with it:
        ``tests/companion/test_three_d_render.py`` creates a real GL context,
        uploads the built-in model, draws a frame and reads the pixels back. The
        assertion below is that the module exists; the assertion that it works
        is that file, and it skips rather than passes where no context can be
        made, so it cannot become a rubber stamp on a machine without graphics.
        """
        self.assertTrue(IMPLEMENTED_PRESENTATIONS <= set(PRESENTATION_KINDS))
        self.assertIn("animated-2d", IMPLEMENTED_PRESENTATIONS)
        self.assertIn("lightweight-3d", IMPLEMENTED_PRESENTATIONS)
        self.assertIn("full-3d", IMPLEMENTED_PRESENTATIONS)
        from pathlib import Path as _Path

        character = _Path(__file__).resolve().parents[2] / "companion" / "character"
        renderers = {path.name for path in character.glob("*renderer*.py")}
        self.assertIn("animated_renderer.py", renderers)
        self.assertTrue((character / "three_d" / "renderer.py").is_file())
        self.assertTrue(
            (_Path(__file__).resolve().parent / "test_three_d_render.py").is_file(),
            "the rung is claimed; the test that draws with it must exist",
        )


class PriorityTests(unittest.TestCase):
    def test_an_approval_outranks_work_in_progress(self) -> None:
        self.assertEqual(resolve_phase("working", approvals_pending=True), "waiting_for_approval")

    def test_an_error_outranks_an_approval(self) -> None:
        self.assertEqual(resolve_phase("error", approvals_pending=True), "error")

    def test_listening_outranks_working_and_speaking_outranks_it_too(self) -> None:
        self.assertEqual(resolve_phase("working", listening=True), "listening")
        self.assertEqual(resolve_phase("working", speaking=True), "speaking")
        self.assertEqual(resolve_phase("working", listening=True, speaking=True), "listening")

    def test_success_outranks_idle_and_nothing_outranks_error(self) -> None:
        self.assertEqual(resolve_phase("success"), "success")
        self.assertEqual(
            resolve_phase("error", approvals_pending=True, listening=True, speaking=True), "error"
        )

    def test_an_unknown_base_phase_falls_back_to_idle_rather_than_raising(self) -> None:
        self.assertEqual(resolve_phase("not-a-phase"), "idle")


class ProjectionOverARealRunTests(CompanionTestCase):
    """Folded over a stream a real runtime actually wrote."""

    def _completed(self):
        runtime = self.started(consent=self.granting("interrupt_user_work"))
        session = runtime.create_session("Projection")
        task = runtime.submit_task(session.session_id, FULL_REQUEST)
        finished = runtime.run_task(session.session_id, task.task_id)
        return runtime, session, finished

    def test_a_completed_run_projects_to_success_with_its_result(self) -> None:
        runtime, session, finished = self._completed()
        self.assertEqual(finished.state, "completed")
        events = runtime.events(session.session_id, task_id=finished.task_id)
        state = project_presentation(events)
        self.assertEqual(state.phase, "success")
        self.assertEqual(state.task_id, finished.task_id)
        self.assertEqual(state.active_executor, "local.deterministic")
        self.assertIn("local.test-reviewer", state.reviewers)
        self.assertTrue(state.result_summary)
        self.assertEqual(state.progress, 1.0)
        self.assertEqual(state.approval_state, "granted")
        self.assertEqual(state.approvals, ())

    def test_progress_never_goes_backwards(self) -> None:
        runtime, session, finished = self._completed()
        projector = PresentationProjector()
        seen = []
        for event in runtime.events(session.session_id, task_id=finished.task_id):
            seen.append(projector.apply(event).progress)
        self.assertEqual(seen, sorted(seen))

    def test_a_reviewer_observation_reaches_the_surface(self) -> None:
        runtime, session, finished = self._completed()
        state = project_presentation(runtime.events(session.session_id, task_id=finished.task_id))
        self.assertTrue(state.observations)
        self.assertTrue(any(item.disagreement for item in state.observations))
        # §10: material disagreement stays visible after the executor revises.
        self.assertTrue(any(
            item.disagreement and "validation" in item.summary for item in state.observations
        ))

    def test_an_unanswered_approval_holds_the_surface_at_the_question(self) -> None:
        runtime = self.started()  # the refusing default: nobody answers
        session = runtime.create_session("Refusing")
        task = runtime.submit_task(session.session_id, FULL_REQUEST)
        blocked = runtime.run_task(session.session_id, task.task_id)
        self.assertEqual(blocked.state, "blocked")
        events = runtime.events(session.session_id, task_id=task.task_id)
        # Mid-stream, before the denial, the surface must be showing the
        # question rather than the work.
        requested = [
            index for index, event in enumerate(events)
            if event.event_type == "approval_requested" and not event.payload.get("batch")
        ]
        self.assertTrue(requested)
        partial = project_presentation(events[: requested[0] + 1])
        self.assertEqual(partial.phase, "waiting_for_approval")
        self.assertEqual(partial.approval_state, "pending")
        self.assertEqual(len(partial.approvals), 1)
        self.assertEqual(partial.approvals[0].safe_default, "denied")
        # And afterwards the denial is what is shown, not the work that followed.
        self.assertEqual(project_presentation(events).phase, "blocked")

    def test_the_approval_binding_carries_only_recorded_fields(self) -> None:
        runtime = self.started()
        session = runtime.create_session("Binding")
        task = runtime.submit_task(session.session_id, FULL_REQUEST)
        runtime.run_task(session.session_id, task.task_id)
        events = runtime.events(session.session_id, task_id=task.task_id)
        requested = next(
            event for event in events
            if event.event_type == "approval_requested" and not event.payload.get("batch")
        )
        index = list(events).index(requested)
        state = project_presentation(events[: index + 1])
        binding = state.approvals[0].binding()
        self.assertEqual(sorted(binding), sorted((
            "requestId", "sessionId", "taskId", "planId", "transitionId", "action",
            "destination", "providerId", "dataClassification", "estimatedCostUnits",
            "destinationFingerprint",
        )))
        # Expiry is bound but is not a field the client restates.
        self.assertNotIn("expiresAtMonotonic", binding)
        self.assertNotIn("destinationDetail", binding)
        self.assertEqual(binding["taskId"], task.task_id)
        self.assertEqual(binding["destination"], "local")

    def test_a_cancelled_task_projects_to_cancelled(self) -> None:
        from companion.cancellation import cancel_task

        runtime = self.started()
        session = runtime.create_session("Cancelled")
        task = runtime.submit_task(session.session_id, SIMPLE_REQUEST)
        cancel_task(runtime, session.session_id, task.task_id, cause="user")
        state = project_presentation(runtime.events(session.session_id, task_id=task.task_id))
        self.assertEqual(state.phase, "cancelled")

    def test_replaying_the_redacted_wire_form_reaches_the_same_phase(self) -> None:
        """§7: the client rebuilds from what the runtime supplies."""
        runtime, session, finished = self._completed()
        events = runtime.events(session.session_id, task_id=finished.task_id)
        direct = project_presentation(events)
        wire = PresentationProjector()
        for event in events:
            wire.apply_document(event.view("ui"))
        self.assertEqual(wire.state.phase, direct.phase)
        self.assertEqual(wire.state.base_phase, direct.base_phase)
        self.assertEqual(wire.state.progress, direct.progress)
        self.assertEqual(wire.state.result_summary, direct.result_summary)
        self.assertEqual(wire.state.revision, direct.revision)

    def test_replay_in_pieces_equals_replay_in_one_go(self) -> None:
        runtime, session, finished = self._completed()
        events = list(runtime.events(session.session_id, task_id=finished.task_id))
        whole = project_presentation(events)
        halves = PresentationProjector()
        for event in events[: len(events) // 2]:
            halves.apply(event)
        for event in events[len(events) // 2 :]:
            halves.apply(event)
        self.assertEqual(halves.state.to_json(), whole.to_json())


class RedactionTests(CompanionTestCase):
    def test_a_secret_task_is_withheld_from_the_surface(self) -> None:
        runtime = self.started()
        session = runtime.create_session("Secret")
        task = runtime.submit_task(
            session.session_id, "Count the words in my private note", classification="secret"
        )
        runtime.run_task(session.session_id, task.task_id)
        state = project_presentation(runtime.events(session.session_id, task_id=task.task_id))
        self.assertTrue(state.content_withheld)
        self.assertEqual(state.privacy_classification, "secret")
        rendered = json.dumps(state.to_json())
        self.assertNotIn("private note", rendered)

    def test_a_credential_in_a_payload_never_reaches_the_surface(self) -> None:
        runtime = self.started()
        session = runtime.create_session("Credential")
        task = runtime.submit_task(
            session.session_id,
            "Count the words in this: Bearer abcdefghijklmnopqrstuvwxyz012345",
        )
        runtime.run_task(session.session_id, task.task_id)
        events = list(runtime.events(session.session_id, task_id=task.task_id))
        # Checked at every prefix, not only at the end. By the time a task has
        # completed its status line says "Done."; the window in which the
        # request's own text is on screen is the one that matters, and a check
        # that only looked at the final state would pass without ever having
        # looked at it.
        for count in range(1, len(events) + 1):
            rendered = json.dumps(project_presentation(events[:count]).to_json())
            self.assertNotIn("abcdefghijklmnopqrstuvwxyz012345", rendered)
        after_submission = json.dumps(project_presentation(events[:1]).to_json())
        self.assertIn("[redacted]", after_submission)


class InvalidInputTests(unittest.TestCase):
    """A malformed record cannot move the surface into a state of its choosing."""

    def test_an_event_document_with_an_unknown_type_changes_no_phase(self) -> None:
        projector = PresentationProjector()
        before = projector.state.base_phase
        projector.apply_document({
            "eventType": "definitely_not_an_event",
            "sequence": 1,
            "sessionId": "ses-1",
            "taskId": "task-1",
            "payload": {"to": "completed"},
            "classification": "internal",
            "auditReference": "",
        })
        self.assertEqual(projector.state.base_phase, before)
        self.assertNotEqual(projector.state.phase, "success")

    def test_a_state_change_naming_an_unknown_state_changes_no_phase(self) -> None:
        projector = PresentationProjector()
        projector.apply_document({
            "eventType": "task_state_changed", "sequence": 1,
            "sessionId": "ses-1", "taskId": "task-1",
            "payload": {"from": "created", "to": "president"},
            "classification": "internal", "auditReference": "",
        })
        self.assertEqual(projector.state.base_phase, "idle")

    def test_a_non_object_document_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            PresentationProjector().apply_document("not an object")  # type: ignore[arg-type]

    def test_an_unknown_classification_is_treated_as_withheld(self) -> None:
        projector = PresentationProjector()
        projector.apply_document({
            "eventType": "task_created", "sequence": 1,
            "sessionId": "ses-1", "taskId": "task-1",
            "payload": {"summary": "x"}, "classification": "cosmic", "auditReference": "",
        })
        self.assertTrue(projector.state.content_withheld)

    def test_progress_from_a_hostile_payload_stays_within_bounds(self) -> None:
        projector = PresentationProjector()
        for value in (5.0, -3.0, 1e30):
            projector.apply_document({
                "eventType": "operation_progress", "sequence": 1,
                "sessionId": "ses-1", "taskId": "task-1",
                "payload": {"operationKey": "op-1", "progress": value},
                "classification": "internal", "auditReference": "",
            })
            self.assertLessEqual(projector.state.progress, 1.0)
            self.assertGreaterEqual(projector.state.progress, 0.0)


class MarkupTests(unittest.TestCase):
    def test_markup_in_a_status_line_is_neutralised(self) -> None:
        projector = PresentationProjector()
        projector.apply_document({
            "eventType": "task_created", "sequence": 1,
            "sessionId": "ses-1", "taskId": "task-1",
            "payload": {"summary": "<span foreground='red'>urgent</span> & <b>now</b>"},
            "classification": "internal", "auditReference": "",
        })
        text = projector.state.status_text
        self.assertNotIn("<span", text)
        self.assertNotIn("<b>", text)
        self.assertIn("&lt;span", text)
        self.assertIn("&amp;", text)

    def test_escaping_is_idempotent_in_the_sense_that_matters(self) -> None:
        self.assertNotIn("<", escape_markup("<script>alert(1)</script>"))

    def test_an_apostrophe_survives_to_the_screen(self) -> None:
        """The desktop showed "Your original wasn&#39;t changed." to a person.

        Photographed on a booted guest, at the end of a journey that had just
        worked. Every view in this product uses `set_text`, so nothing ever
        turned the entity back, and this product's voice is full of
        contractions.
        """
        sentence = "Your original wasn't changed."
        self.assertEqual(sentence, escape_markup(sentence))
        self.assertNotIn("&#39;", escape_markup('He said "no" and didn\'t move.'))

    def test_a_quote_still_cannot_smuggle_markup(self) -> None:
        """The reason dropping the quote rules is safe, asserted rather than argued.

        Pango markup opens with `<` and an entity opens with `&`. Both are still
        escaped, so no tag can exist — and a quote only means anything inside a
        tag. This is what makes the readable sentence and the injection
        property compatible.
        """
        hostile = "<span foreground='red' weight=\"bold\">urgent</span>"
        escaped = escape_markup(hostile)
        self.assertNotIn("<", escaped)
        self.assertNotIn(">", escaped)
        self.assertIn("&lt;span", escaped)
        # The quotes survive, and are inert because no tag survives with them.
        self.assertIn("'red'", escaped)
        self.assertIn('"bold"', escaped)


class PresentationSelectionTests(unittest.TestCase):
    """§11: only implementations that exist may be selected."""

    def test_a_capable_machine_is_now_given_the_3d_rung_it_was_always_eligible_for(self) -> None:
        """The same machine, the same signals, and the gap has closed.

        This test asserted ``animated-2d`` for two phases while ``eligible``
        said ``full-3d`` — the honest form of "this build has no renderer for
        what your machine could run". Now that the renderer exists the two are
        equal and ``limitedByImplementation`` is false, which is the same
        property stated the other way round.
        """
        decision = select_presentation(
            PresentationSignals(
                available_memory_bytes=8 * 1024 ** 3, gpu_available=True,
                display_available=True, audio_output_available=True,
            )
        )
        self.assertIn(decision.implementation, IMPLEMENTED_PRESENTATIONS)
        self.assertEqual(decision.implementation, "full-3d")
        self.assertEqual(decision.eligible, "full-3d")
        self.assertFalse(decision.limited_by_implementation)
        self.assertFalse(any("this build implements" in reason for reason in decision.reasons))

    def test_a_machine_with_no_gpu_is_still_not_eligible_for_3d(self) -> None:
        """The renderer existing does not make a software rasteriser a GPU."""
        decision = select_presentation(
            PresentationSignals(
                available_memory_bytes=8 * 1024 ** 3, gpu_available=False,
                display_available=True, audio_output_available=True,
            )
        )
        self.assertEqual(decision.eligible, "animated-2d")
        self.assertEqual(decision.implementation, "animated-2d")
        self.assertTrue(any("3D is not eligible" in reason for reason in decision.reasons))

    def test_a_mid_memory_machine_gets_the_lightweight_rung(self) -> None:
        decision = select_presentation(
            PresentationSignals(
                available_memory_bytes=int(2.5 * 1024 ** 3), gpu_available=True,
                display_available=True, audio_output_available=True,
            )
        )
        self.assertEqual(decision.implementation, "lightweight-3d")

    def test_a_tiny_machine_gets_text_only(self) -> None:
        decision = select_presentation(PresentationSignals(available_memory_bytes=48 * 1024 * 1024))
        self.assertEqual(decision.implementation, "text-only")

    def test_no_display_with_audio_gives_audio_and_without_it_gives_text(self) -> None:
        with_audio = select_presentation(PresentationSignals(
            available_memory_bytes=4 * 1024 ** 3, headless=True, audio_output_available=True,
        ))
        self.assertEqual(with_audio.implementation, "audio-only")
        without = select_presentation(PresentationSignals(
            available_memory_bytes=4 * 1024 ** 3, headless=True, audio_output_available=False,
        ))
        self.assertEqual(without.implementation, "text-only")

    def test_reduced_motion_and_text_preference_only_ever_simplify(self) -> None:
        preferences = AccessibilityPreferences(reduced_motion=True)
        decision = select_presentation(
            PresentationSignals(available_memory_bytes=8 * 1024 ** 3, gpu_available=True),
            preferences,
        )
        self.assertEqual(decision.eligible, "static-image")
        text = select_presentation(
            PresentationSignals(available_memory_bytes=8 * 1024 ** 3, gpu_available=True),
            AccessibilityPreferences(prefer_text_only=True),
        )
        self.assertEqual(text.implementation, "text-only")

    def test_captions_are_produced_in_every_presentation(self) -> None:
        for signals in (
            PresentationSignals(available_memory_bytes=48 * 1024 * 1024),
            PresentationSignals(headless=True, audio_output_available=True),
            PresentationSignals(available_memory_bytes=8 * 1024 ** 3, gpu_available=True),
        ):
            self.assertTrue(select_presentation(signals).captions)

    def test_an_out_of_range_text_scale_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            AccessibilityPreferences(text_scale=9.0)


class WindowPolicyTests(unittest.TestCase):
    def test_only_an_approval_takes_focus(self) -> None:
        for phase in ("working", "reviewing", "success", "idle", "error", "blocked"):
            self.assertFalse(window_directive(phase).accept_focus, phase)
        self.assertTrue(window_directive("waiting_for_approval").accept_focus)

    def test_absolute_placement_is_never_claimed(self) -> None:
        for phase in ("idle", "working", "waiting_for_approval", "success"):
            self.assertFalse(window_directive(phase).absolute_placement_available)

    def test_a_fullscreen_application_compacts_but_an_approval_still_shows(self) -> None:
        context = DesktopContext(fullscreen_application=True)
        self.assertEqual(window_directive("working", None, context).placement, "compact")
        approval = window_directive("waiting_for_approval", None, context)
        self.assertEqual(approval.placement, "task-panel")
        self.assertTrue(approval.visible)

    def test_hide_during_fullscreen_is_honoured_except_for_a_question(self) -> None:
        preferences = WindowPreferences(hide_during_fullscreen=True)
        context = DesktopContext(fullscreen_application=True)
        self.assertFalse(window_directive("working", preferences, context).visible)
        self.assertTrue(window_directive("waiting_for_approval", preferences, context).visible)


class SchemaConformanceTests(CompanionTestCase):
    def setUp(self) -> None:
        super().setUp()
        try:
            import jsonschema  # noqa: F401
        except ImportError:
            self.skipTest("jsonschema is not installed")

    def test_a_projected_state_validates_against_its_schema(self) -> None:
        import jsonschema

        schema = json.loads(
            (SCHEMAS / "companion-presentation-state.schema.json").read_text(encoding="utf-8")
        )
        runtime = self.started(consent=self.granting("interrupt_user_work"))
        session = runtime.create_session("Schema")
        task = runtime.submit_task(session.session_id, FULL_REQUEST)
        runtime.run_task(session.session_id, task.task_id)
        events = list(runtime.events(session.session_id, task_id=task.task_id))
        # Every prefix, so a partially replayed surface is valid too.
        for count in range(1, len(events) + 1):
            jsonschema.validate(project_presentation(events[:count]).to_json(), schema)

    def test_the_schema_names_exactly_what_this_build_implements(self) -> None:
        """The published contract and ``IMPLEMENTED_PRESENTATIONS`` must agree.

        The schema's ``effectivePresentation`` enum was shorter than its
        ``eligiblePresentation`` enum for two phases, on purpose: the first is
        what this build draws and the second is what a machine could support.
        Now that every rung is implemented they are the same list, and this test
        is what stops them drifting apart in either direction.
        """
        schema = json.loads(
            (SCHEMAS / "companion-presentation-state.schema.json").read_text(encoding="utf-8")
        )
        properties = schema["properties"]["recommendation"]["properties"]
        self.assertEqual(
            sorted(properties["implementation"]["enum"]), sorted(IMPLEMENTED_PRESENTATIONS)
        )
        self.assertEqual(properties["eligible"]["enum"], list(PRESENTATION_KINDS))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
