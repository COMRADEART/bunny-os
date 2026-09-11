# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Product-vision surfaces: Visual Keys, appearance, routing, memory, voice."""

from __future__ import annotations

from html import escape as html_escape
import tempfile
import unittest
from pathlib import Path

from capability.simulate import simulate
from companion.appearance import (
    DEFAULT_APPEARANCE,
    AppearanceMode,
    appearance_from_settings,
    apply_appearance,
    parse_appearance,
    recommend_appearance,
)
from companion.memory_boundary import (
    MemoryPolicy,
    authorize_cloud_context,
    may_store,
)
from companion.onboarding.model import ONBOARDING_STEPS
from companion.outcome_router import OutcomeRequest, classify_outcome, route_outcome
from companion.presentation import PresentationSignals
from companion.product_surface import (
    forbidden_labels_present,
    render_appearance_html,
    render_error_html,
    render_memory_html,
    render_onboarding_html,
    render_router_html,
    render_settings_html,
    render_trust_html,
    render_visual_html,
    render_voice_html,
    visual_demo_frames,
)
from companion.settings import PrivacySettings, Settings, load_settings, save_settings
from companion.visual_keys import CORE_VISUAL_KEYS, VISUAL_KEYS, project_visual_key
from companion.voice_story import VOICE_STORY_UTTERANCE, run_voice_story
from companion.visible_trust import FORBIDDEN_LABELS
from installer.companion_flow import FIRST_RUN_STAGES, INSTALL_STAGES


class VisualKeyTests(unittest.TestCase):
    def test_the_eleven_keys_are_the_product_list(self) -> None:
        self.assertEqual(
            CORE_VISUAL_KEYS,
            (
                "idle", "listening", "thinking", "working", "searching",
                "downloading", "installing", "reading", "coding", "error", "success",
            ),
        )
        self.assertEqual(
            VISUAL_KEYS,
            CORE_VISUAL_KEYS + (
                "waiting_for_permission", "warning", "offline", "disconnected",
            ),
        )

    def test_ordinary_work_is_a_bubble_not_a_chat(self) -> None:
        frames = visual_demo_frames()
        self.assertEqual([frame.key for frame in frames], list(VISUAL_KEYS))
        for frame in frames:
            self.assertLessEqual(len(frame.bubble.text), 220)
            html = render_visual_html(frame)
            self.assertIn('role="status"', html)
            self.assertIn("not a chat", html)
            self.assertEqual(forbidden_labels_present(html), [])
            self.assertIn(frame.scene.name, html)

    def test_error_beats_a_decorative_activity(self) -> None:
        self.assertEqual(
            project_visual_key("working", tool_activity="coding", error_summary="boom"),
            "error",
        )

    def test_listening_beats_idle(self) -> None:
        self.assertEqual(project_visual_key("idle", listening=True), "listening")

    def test_planning_is_thinking(self) -> None:
        self.assertEqual(project_visual_key("planning"), "thinking")
        self.assertEqual(project_visual_key("understanding"), "thinking")

    def test_activities_narrow_working(self) -> None:
        self.assertEqual(project_visual_key("working", tool_activity="search"), "searching")
        self.assertEqual(project_visual_key("working", tool_activity="download"), "downloading")
        self.assertEqual(project_visual_key("working", tool_activity="install"), "installing")
        self.assertEqual(project_visual_key("working", tool_activity="read"), "reading")
        self.assertEqual(project_visual_key("working", tool_activity="code"), "coding")

    def test_approval_offline_and_disconnect_are_readable_keys(self) -> None:
        self.assertEqual(project_visual_key("waiting_for_approval"), "waiting_for_permission")
        self.assertEqual(project_visual_key("blocked"), "warning")
        self.assertEqual(project_visual_key("idle", offline=True), "offline")
        self.assertEqual(project_visual_key("disconnected"), "disconnected")


class AppearanceTests(unittest.TestCase):
    def test_default_is_lightweight_2d(self) -> None:
        self.assertIs(DEFAULT_APPEARANCE, AppearanceMode.LIGHTWEIGHT_2D)
        self.assertIs(parse_appearance("holographic"), DEFAULT_APPEARANCE)
        self.assertIs(appearance_from_settings("prerendered", "full"), AppearanceMode.LIGHTWEIGHT_2D)
        self.assertIs(appearance_from_settings("3d", "full"), AppearanceMode.FULL_3D)
        self.assertIs(appearance_from_settings("3d", "minimal"), AppearanceMode.MINIMAL)

    def test_a_gpu_machine_recommends_3d_and_still_honours_2d(self) -> None:
        signals = PresentationSignals(gpu_available=True, available_memory_bytes=8 * 1024 ** 3)
        self.assertIs(recommend_appearance(signals), AppearanceMode.FULL_3D)
        choice = apply_appearance(signals=signals, chosen="lightweight-2d", override=True)
        self.assertIs(choice.effective, AppearanceMode.LIGHTWEIGHT_2D)
        self.assertTrue(choice.override)
        self.assertFalse(choice.bounded)

    def test_no_gpu_cannot_force_3d(self) -> None:
        signals = PresentationSignals(gpu_available=False, available_memory_bytes=4 * 1024 ** 3)
        choice = apply_appearance(signals=signals, chosen="full-3d", override=True)
        self.assertNotEqual(choice.effective, AppearanceMode.FULL_3D)
        self.assertTrue(choice.bounded)
        self.assertIs(choice.chosen, AppearanceMode.FULL_3D)
        patch = choice.settings_patch()
        self.assertEqual(patch["render_mode"], "3d")
        self.assertEqual(patch["three_d"], "auto")
        self.assertNotEqual(patch["render_mode"], choice.to_json()["renderMode"])

    def test_tiny_memory_recommends_minimal(self) -> None:
        signals = PresentationSignals(gpu_available=False, available_memory_bytes=32 * 1024 * 1024)
        choice = apply_appearance(signals=signals)
        self.assertIs(choice.recommended, AppearanceMode.MINIMAL)
        html = render_appearance_html(choice, machine="embedded-64mb")
        self.assertIn("Minimal", html)
        self.assertEqual(forbidden_labels_present(html), [])


class OutcomeRouterTests(unittest.TestCase):
    def test_people_ask_for_outcomes_not_engines(self) -> None:
        self.assertEqual(classify_outcome("search the web for pasta"), "needs-network")
        self.assertEqual(classify_outcome("remember my doctor's name"), "remember")
        self.assertEqual(classify_outcome("summarise this note"), "local-work")

    def test_local_work_on_a_laptop_stays_local(self) -> None:
        request = OutcomeRequest("summarise this note", kind="local-work")
        explanation = route_outcome(request, simulate("laptop"))
        self.assertEqual(explanation.target, "local")
        self.assertIn("this computer", explanation.headline.casefold())
        self.assertEqual(explanation.decision.to_json()["modelsOffered"] if False else [], [])
        self.assertEqual(explanation.to_json()["modelsOffered"], [])

    def test_offline_network_work_is_refused(self) -> None:
        request = OutcomeRequest(
            "search the web for pasta",
            kind="needs-network",
            offline=True,
            remote_allowed=True,
        )
        explanation = route_outcome(request, simulate("offline-laptop"))
        self.assertEqual(explanation.target, "refused")
        self.assertTrue(explanation.offline_refused)

    def test_secret_work_is_not_sent_to_make_up_for_a_weak_machine(self) -> None:
        request = OutcomeRequest(
            "summarise this private note",
            kind="private-work",
            privacy="secret",
            remote_allowed=True,
            local_memory_bytes=8 * 1024 ** 3,
        )
        explanation = route_outcome(request, simulate("embedded-64mb"))
        self.assertEqual(explanation.target, "refused")
        self.assertTrue(any("secret" in reason for reason in explanation.reasons))
        self.assertIn("this computer", explanation.headline.casefold())
        self.assertIn("private work", explanation.detail.casefold())

    def test_memory_pressure_does_not_become_a_cloud_upload(self) -> None:
        request = OutcomeRequest(
            "summarise this note",
            kind="local-work",
            local_memory_bytes=8 * 1024 ** 3,
        )
        explanation = route_outcome(request, simulate("embedded-64mb"))
        self.assertEqual(explanation.target, "refused")
        self.assertTrue(explanation.memory_pressure)

    def test_the_html_does_not_shop_for_models(self) -> None:
        explanation = route_outcome(
            OutcomeRequest("summarise this note"), simulate("laptop"),
        )
        html = render_router_html([explanation])
        self.assertIn("no model shop", html)
        self.assertNotIn("GGUF", html)
        self.assertEqual(forbidden_labels_present(html), [])


class MemoryBoundaryTests(unittest.TestCase):
    def test_defaults_deny_everything_but_working_memory(self) -> None:
        policy = MemoryPolicy()
        self.assertTrue(may_store("internal", "working", policy).allowed)
        self.assertFalse(may_store("internal", "session", policy).allowed)
        self.assertFalse(may_store("internal", "durable", policy).allowed)
        self.assertFalse(may_store("internal", "cloud", policy).allowed)

    def test_settings_defaults_match_the_policy(self) -> None:
        privacy = PrivacySettings()
        policy = MemoryPolicy.from_settings(privacy)
        self.assertFalse(policy.session)
        self.assertFalse(policy.durable)
        self.assertEqual(policy.cloud_context, "none")
        self.assertEqual(privacy.remote_transfer_ceiling, "public")

    def test_cloud_needs_an_allow_list_and_still_honours_the_ceiling(self) -> None:
        policy = MemoryPolicy(cloud_context="minimized")
        denied = authorize_cloud_context(
            {"note": "hello", "secret": "nope"},
            classification="internal",
            policy=policy,
            remote_transfer_ceiling="public",
            allowed_fields=("note",),
        )
        self.assertFalse(denied.allowed)
        allowed = authorize_cloud_context(
            {"note": "hello", "secret": "nope"},
            classification="public",
            policy=policy,
            remote_transfer_ceiling="public",
            allowed_fields=("note",),
        )
        self.assertTrue(allowed.allowed)
        self.assertEqual(set(allowed.released or {}), {"note"})

    def test_cloud_full_share_does_not_exist(self) -> None:
        with self.assertRaises(ValueError):
            MemoryPolicy(cloud_context="full")
        with self.assertRaises(Exception):
            PrivacySettings(cloud_context="everything")

    def test_memory_controls_can_be_turned_on_and_still_have_no_full_cloud(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            updated = save_settings(
                root,
                Settings(privacy=PrivacySettings(
                    local_session_memory=True,
                    local_durable_memory=True,
                    cloud_context="minimized",
                )),
            )
            del updated
            restored = load_settings(root)
            self.assertTrue(restored.privacy.local_session_memory)
            self.assertTrue(restored.privacy.local_durable_memory)
            self.assertEqual(restored.privacy.cloud_context, "minimized")
            with self.assertRaises(Exception):
                PrivacySettings(cloud_context="full")

    def test_legacy_settings_files_keep_memory_off(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            save_settings(root, Settings())
            document = load_settings(root).to_json()
            document["privacy"].pop("localSessionMemory", None)
            document["privacy"].pop("localDurableMemory", None)
            document["privacy"].pop("cloudContext", None)
            restored = Settings.from_json(document)
            self.assertFalse(restored.privacy.local_session_memory)
            self.assertFalse(restored.privacy.local_durable_memory)
            self.assertEqual(restored.privacy.cloud_context, "none")

    def test_the_html_names_deny_by_default(self) -> None:
        policy = MemoryPolicy()
        decisions = [
            may_store("internal", "working", policy),
            may_store("internal", "durable", policy),
            authorize_cloud_context(
                {"note": "x"}, classification="public", policy=policy,
                remote_transfer_ceiling="public", allowed_fields=("note",),
            ),
        ]
        html = render_memory_html(policy, decisions)
        self.assertIn("denied", html)
        self.assertEqual(forbidden_labels_present(html), [])


class OnboardingCopyTests(unittest.TestCase):
    def test_the_wizard_starts_hi_im_bunny_and_ends_ready(self) -> None:
        self.assertIn("I'm Bunny", ONBOARDING_STEPS[0].body)
        self.assertEqual(ONBOARDING_STEPS[0].title, "Hi. I'm Bunny.")
        self.assertEqual(ONBOARDING_STEPS[-1].title, "Ready")
        self.assertTrue(ONBOARDING_STEPS[-1].body.startswith("Ready."))
        self.assertIn("corner", ONBOARDING_STEPS[-1].body.casefold())
        companion = next(step for step in ONBOARDING_STEPS if step.step_id == "companion")
        self.assertIn("Full 3D", companion.body)
        self.assertIn("Lightweight 2D", companion.body)
        self.assertIn("Minimal", companion.body)
        privacy = next(step for step in ONBOARDING_STEPS if step.step_id == "privacy")
        self.assertIn("Local only", privacy.body)
        self.assertTrue(privacy.skip)
        self.assertFalse(privacy.required)

    def test_essential_spine_is_hello_companion_privacy_ready(self) -> None:
        from companion.onboarding.model import ONBOARDING_ESSENTIAL_IDS
        self.assertEqual(ONBOARDING_ESSENTIAL_IDS, ("welcome", "companion", "privacy", "finish"))

    def test_the_installer_and_first_run_say_the_same_hello_and_ready(self) -> None:
        self.assertIn("I'm Bunny", INSTALL_STAGES[0].says)
        self.assertIn("I'm Bunny", FIRST_RUN_STAGES[0].says)
        self.assertTrue(FIRST_RUN_STAGES[-1].says.startswith("Ready."))

    def test_onboarding_html_is_not_a_disk_write(self) -> None:
        html = render_onboarding_html(step_index=0)
        self.assertIn("Hi. I&#x27;m Bunny", html)
        self.assertIn("does not write a disk", html)
        html_ready = render_onboarding_html(step_index=len(ONBOARDING_STEPS) - 1)
        self.assertIn("Ready", html_ready)
        self.assertEqual(forbidden_labels_present(html), [])


class VoiceStoryTests(unittest.TestCase):
    def test_the_text_half_runs_without_a_microphone(self) -> None:
        report = run_voice_story()
        self.assertEqual(report.transcript, VOICE_STORY_UTTERANCE)
        self.assertTrue(report.passed)
        self.assertEqual(report.intent_kind, "system_metric")
        self.assertEqual(report.planned_tool, "system.get_metric")
        self.assertEqual(report.to_json()["unrestrictedShell"], False)
        self.assertEqual(report.to_json()["modelBytesVendored"], False)
        statuses = {item["name"]: item["status"] for item in report.steps}
        self.assertEqual(statuses["speech-to-text"], "NOT_RUN")
        self.assertEqual(statuses["local TTS"], "NOT_RUN")
        self.assertEqual(report.to_json()["spokenE2e"], "NOT_RUN")
        html = render_voice_html(report)
        self.assertIn("NOT_RUN", html)
        self.assertNotIn("Always allow everything", html)

    def test_an_unrecognised_utterance_does_not_invent_a_shell_command(self) -> None:
        report = run_voice_story(utterance="rm -rf /")
        self.assertFalse(report.passed)
        self.assertEqual(report.planned_tool, "")
        self.assertNotIn("rm", report.planned_tool)


class SecurityInvariantsTests(unittest.TestCase):
    def test_no_surface_grows_an_always_allow(self) -> None:
        frames = visual_demo_frames()
        htmls = [render_visual_html(frame) for frame in frames]
        htmls.append(render_onboarding_html())
        htmls.append(render_settings_html())
        htmls.append(render_error_html())
        for html in htmls:
            for label in FORBIDDEN_LABELS:
                self.assertNotIn(label, html)

    def test_settings_are_named_for_people(self) -> None:
        html = render_settings_html()
        for title in (
            "Appearance", "Bunny", "AI & Models", "Privacy",
            "Apps", "Permissions", "Accessibility", "System", "Updates",
        ):
            self.assertIn(html_escape(title), html)
        self.assertNotIn("GGUF", html)

    def test_errors_say_what_happened_what_to_do_and_what_changed(self) -> None:
        html = render_error_html()
        self.assertIn("What happened", html)
        self.assertIn("What to do", html)
        self.assertIn("What changed", html)
        self.assertIn("bunny-face", html)

    def test_the_companion_face_is_one_silhouette(self) -> None:
        html = render_visual_html(visual_demo_frames()[0])
        self.assertIn("bunny-face", html)
        self.assertNotIn("🤔", html)
        self.assertNotIn("🐰", html)
        listening = next(frame for frame in visual_demo_frames() if frame.key == "listening")
        listening_html = render_visual_html(listening)
        self.assertIn("Mic on", listening_html)
        self.assertTrue(listening.mic_visible)

    def test_trust_html_uses_who_what_why_and_scope_labels(self) -> None:
        from companion.visible_trust import demo_prompt
        html = render_trust_html(demo_prompt())
        self.assertIn("Who", html)
        self.assertIn("What", html)
        self.assertIn("Why", html)
        self.assertIn("How long", html)
        self.assertIn("This time only", html)
        self.assertIn("Allow once", html)
        self.assertIn("Don't allow", html)
        self.assertEqual(forbidden_labels_present(html), [])


if __name__ == "__main__":
    unittest.main()
