# SPDX-License-Identifier: GPL-3.0-or-later
"""The capability-plan ceiling and the desktop window policy.

The presentation ladder itself — every degradation rule, the
implemented-presentations filter and the recovery hysteresis — is qualified
in ``test_three_d_ladder`` against the live renderer selection. This file
covers the two contracts that suite does not reach, both of which arrived
from the companion presentation prototype and are expressed here against this
build's types:

* a capability execution plan is an *authorization ceiling* on what may be
  drawn, no matter what the machine could support;
* ``window_directive`` turns a phase into a window shape, and the one phase
  that may take focus is an outstanding approval.
"""

from __future__ import annotations

import unittest

from companion.model import CompanionPhase
from companion.presentation import (
    CapabilityPresentationPlan,
    DesktopContext,
    MonitorGeometry,
    PresentationSignals,
    WindowPreferences,
    select_presentation,
    window_directive,
)

MIB = 1024 * 1024
GIB = 1024 * MIB


def plan(kind: str = "full-3d", action: str = "start_local") -> CapabilityPresentationPlan:
    return CapabilityPresentationPlan(
        plan_id="plan-test",
        service_id="bunny.companion",
        action=action,
        implementation_id=kind,
        presentation_ceiling=kind,
    )


def capable_signals(**changes) -> PresentationSignals:
    values = {
        "available_memory_bytes": 8 * GIB,
        "gpu_available": True,
        "display_available": True,
        "audio_output_available": True,
    }
    values.update(changes)
    return PresentationSignals(**values)


def execution_plan_document(service_id: str = "bunny.companion", **decision_changes) -> dict:
    decision = {
        "serviceId": service_id,
        "action": "start_local",
        "implementationId": "full-3d",
        "requiresApproval": False,
        "reasons": [{"code": "gpu-ready"}, {"code": "memory-available"}],
    }
    decision.update(decision_changes)
    return {
        "identity": {"planId": "plan-doc-1"},
        "decisions": [
            {"serviceId": "bunny.other", "action": "reject"},
            decision,
        ],
    }


class PlanParsingTests(unittest.TestCase):
    def test_the_service_decision_is_read_from_the_plan(self) -> None:
        parsed = CapabilityPresentationPlan.from_execution_plan(execution_plan_document())
        self.assertEqual(parsed.plan_id, "plan-doc-1")
        self.assertEqual(parsed.service_id, "bunny.companion")
        self.assertEqual(parsed.action, "start_local")
        self.assertEqual(parsed.presentation_ceiling, "full-3d")
        self.assertEqual(parsed.reasons, ("gpu-ready", "memory-available"))
        self.assertFalse(parsed.requires_approval)

    def test_an_unknown_implementation_degrades_to_text(self) -> None:
        parsed = CapabilityPresentationPlan.from_execution_plan(
            execution_plan_document(implementationId="hologram")
        )
        self.assertEqual(parsed.presentation_ceiling, "text-only")

    def test_a_plan_without_decisions_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            CapabilityPresentationPlan.from_execution_plan({"identity": {"planId": "x"}})

    def test_a_plan_without_this_service_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            CapabilityPresentationPlan.from_execution_plan(
                {"identity": {"planId": "x"}, "decisions": [{"serviceId": "bunny.other"}]}
            )

    def test_an_unknown_ceiling_is_refused_at_construction(self) -> None:
        with self.assertRaises(ValueError):
            plan(kind="hologram")


class PlanCeilingTests(unittest.TestCase):
    def test_a_capable_machine_under_a_full_plan_draws_the_full_rung(self) -> None:
        result = select_presentation(capable_signals(), plan=plan("full-3d"))
        self.assertEqual(result.implementation, "full-3d")

    def test_the_plan_caps_whatever_the_machine_could_support(self) -> None:
        result = select_presentation(capable_signals(), plan=plan("static-image"))
        self.assertEqual(result.implementation, "static-image")
        self.assertTrue(any("permits at most static-image" in reason for reason in result.reasons))

    def test_a_text_only_plan_holds_even_on_a_workstation(self) -> None:
        result = select_presentation(capable_signals(), plan=plan("text-only"))
        self.assertEqual(result.implementation, "text-only")

    def test_a_plan_without_a_start_action_authorizes_no_rendering(self) -> None:
        result = select_presentation(capable_signals(), plan=plan("full-3d", action="reject"))
        self.assertEqual(result.implementation, "text-only")
        self.assertTrue(any("only task text remains" in reason for reason in result.reasons))

    def test_the_ceiling_never_upgrades_a_weaker_machine(self) -> None:
        result = select_presentation(
            capable_signals(gpu_available=False),
            plan=plan("full-3d"),
        )
        self.assertEqual(result.implementation, "animated-2d")


class WindowPolicyTests(unittest.TestCase):
    def context(self, fullscreen: bool = False) -> DesktopContext:
        return DesktopContext(
            monitors=(
                MonitorGeometry("left", 0, 0, 1920, 1080),
                MonitorGeometry("right", 1920, 0, 2560, 1440),
            ),
            active_monitor_id="right",
            fullscreen_application=fullscreen,
        )

    def test_working_companion_does_not_take_focus(self) -> None:
        result = window_directive("working", WindowPreferences(), self.context())
        self.assertEqual(result.placement, "docked")
        self.assertFalse(result.accept_focus)
        self.assertEqual(result.monitor_id, "right")

    def test_approval_panel_accepts_focus(self) -> None:
        result = window_directive("waiting_for_approval", WindowPreferences(), self.context())
        self.assertEqual(result.placement, "task-panel")
        self.assertTrue(result.accept_focus)

    def test_fullscreen_compacts_and_suppresses_notification(self) -> None:
        result = window_directive("working", WindowPreferences(), self.context(fullscreen=True))
        self.assertEqual(result.placement, "compact")
        self.assertTrue(result.suppress_notification)

    def test_fullscreen_can_hide_passive_window(self) -> None:
        result = window_directive(
            "working",
            WindowPreferences(hide_during_fullscreen=True),
            self.context(fullscreen=True),
        )
        self.assertFalse(result.visible)

    def test_an_approval_is_never_hidden_by_fullscreen(self) -> None:
        result = window_directive(
            "waiting_for_approval",
            WindowPreferences(hide_during_fullscreen=True),
            self.context(fullscreen=True),
        )
        self.assertTrue(result.visible)
        self.assertFalse(result.compact_for_fullscreen)

    def test_phase_names_are_the_stream_vocabulary(self) -> None:
        # The directive takes the event-stream's phase names, not the enum, so
        # a caller holding a projected state needs no translation layer.
        from_enum = window_directive(CompanionPhase.WORKING.value, WindowPreferences(), self.context())
        self.assertEqual(from_enum.placement, "docked")


if __name__ == "__main__":
    unittest.main()
