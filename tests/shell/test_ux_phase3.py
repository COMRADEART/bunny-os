# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""UX Phase 3: Settings IA, Bunny settings, AI & Models, onboarding, lock.

Host-testable models and copy. Live GNOME is not claimed. Not IMAGE. Not BOOT.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from bunny_shell.bunny_settings import (
    PERSONALITY_FORBIDDEN,
    PROACTIVITY_CHOICES,
    ai_models_module,
    bunny_companion_module,
    bunny_settings_pages,
    normalise_personality,
    personality_may_not_route,
    settings_privacy_module,
)
from bunny_shell.control_center import ADVANCED_TITLE, CONVERSATION_SUMMARY_UNWIRED, MODEL_UNKNOWN
from bunny_shell.lock_screen import (
    COMPANION_CORNER,
    LOCK_PASSWORD_NAME,
    build_lock_screen,
    build_login_screen,
)
from bunny_shell.settings import DEFINITIONS, SECTIONS, SettingsStore
from bunny_shell.settings_ia import (
    SIDEBAR_SECTION_TITLES,
    build_settings_ia,
    resolve_section,
)
from bunny_shell.trust_copy import (
    CLOUD_MEMORY_IS_OFF,
    CLOUD_MEMORY_STAYS_OFF,
    NETWORK_ALLOWLIST_NOTE,
    NO_ONLINE_MODELS_IS_LOCAL_ONLY,
)
from companion.onboarding.model import ONBOARDING_ESSENTIAL_IDS, ONBOARDING_STEPS, OnboardingModel
from companion.settings import CharacterSettings, Settings
from companion.user_copy import NO_ONLINE_MODELS_IS_LOCAL_ONLY as USER_NO_ONLINE
from installer.companion_flow import FIRST_RUN_STAGES
from tests.support import ROOT

LIB = ROOT / "shell/components/gnome-shell-extension/lib"
FROZEN = (
    "qualification/phase7/immutability/frozen-evidence.json",
    "qualification/design/story-manifest.json",
)


def run_node(script: str) -> object:
    with tempfile.TemporaryDirectory() as directory:
        probe = Path(directory) / "probe.mjs"
        probe.write_text(script, encoding="utf-8")
        result = subprocess.run(
            [shutil.which("node"), str(probe)],
            capture_output=True, text=True, encoding="utf-8",
            check=False, cwd=str(ROOT))
    if result.returncode != 0:
        raise AssertionError(f"node failed: {result.stderr.strip()}")
    return json.loads(result.stdout.strip().splitlines()[-1])


class NodeBackedTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not shutil.which("node"):
            raise unittest.SkipTest("node is unavailable on this host")


class SettingsIATests(NodeBackedTestCase):
    def test_you_group_is_open_and_device_starts_collapsed(self) -> None:
        ia = build_settings_ia()
        groups = {group["id"]: group for group in ia["groups"]}
        self.assertFalse(groups["you"]["collapsed"])
        self.assertTrue(groups["device"]["collapsed"])
        self.assertTrue(groups["system"]["collapsed"])
        self.assertEqual(
            [item["title"] for item in groups["you"]["items"]],
            ["Bunny", "AI & Models", "Privacy", "Accessibility"],
        )
        self.assertFalse(ia["companionRequired"])
        self.assertFalse(ia["chatbot"])

    def test_voice_and_ai_alias_opens_ai_models(self) -> None:
        self.assertEqual(resolve_section("Voice & AI").id, "ai-models")
        self.assertEqual(resolve_section("Local Models").id, "ai-models")
        self.assertEqual(resolve_section("Memory").id, "privacy")
        self.assertIn("AI & Models", SECTIONS)
        self.assertEqual(SECTIONS, SIDEBAR_SECTION_TITLES)

    def test_javascript_sidebar_matches_python(self) -> None:
        js = run_node(
            f"import {{buildSettingsIA, resolveSection}} from '{(LIB / 'settingsIa.js').as_uri()}';\n"
            "const ia = buildSettingsIA({selected: 'Voice & AI'});\n"
            "console.log(JSON.stringify({ia, resolved: resolveSection('Memory').id}));\n"
        )
        py = build_settings_ia(selected="Voice & AI")
        self.assertEqual(js["ia"]["selected"], py["selected"])
        self.assertEqual(js["ia"]["selectedTitle"], "AI & Models")
        self.assertEqual(js["resolved"], "privacy")
        self.assertEqual(js["ia"]["groups"][0]["collapsed"], False)
        self.assertEqual(js["ia"]["groups"][1]["collapsed"], True)


class BunnySettingsTests(NodeBackedTestCase):
    def test_bunny_page_covers_the_phase3_rows(self) -> None:
        module = bunny_companion_module()
        ids = [row.id for row in module.rows]
        for needed in (
            "character", "personality", "voiceEnabled", "animationIntensity",
            "dock", "scale", "interaction", "proactivity", "memory", "aiMode", "privacy",
        ):
            self.assertIn(needed, ids)
        self.assertFalse(module.companion_required)
        self.assertIn(NO_ONLINE_MODELS_IS_LOCAL_ONLY, module.warnings)

    def test_personality_cannot_be_a_vendor_and_does_not_route(self) -> None:
        self.assertEqual(normalise_personality("Claude"), "bunny")
        self.assertEqual(normalise_personality("openai"), "bunny")
        self.assertTrue(personality_may_not_route("focused"))
        self.assertIn("claude", PERSONALITY_FORBIDDEN)
        with self.assertRaises(Exception):
            CharacterSettings(personality="claude")
        self.assertEqual(CharacterSettings(personality="playful").personality, "playful")
        self.assertEqual(Settings().character.proactivity, "off")
        self.assertEqual(set(PROACTIVITY_CHOICES), {"off", "gentle"})

    def test_ai_models_reuses_p2_contract(self) -> None:
        automatic = ai_models_module()
        self.assertEqual(automatic.title, "AI & Models")
        mode = next(row for row in automatic.rows if row.id == "aiMode")
        self.assertEqual(mode.value, "Automatic")
        self.assertEqual(automatic.advanced_title, ADVANCED_TITLE)
        advanced = {row.id: row.value for row in automatic.advanced}
        self.assertEqual(advanced["modelId"], MODEL_UNKNOWN)
        self.assertEqual(advanced["adapter"], MODEL_UNKNOWN)
        self.assertEqual(advanced["throughput"], "Not measured")
        self.assertEqual(advanced["gpu"], "Unknown")
        self.assertEqual(advanced["vram"], "Unknown")
        self.assertEqual(advanced["npu"], "Unknown")
        self.assertEqual(advanced["whyThisModel"], "Not available")
        local = ai_models_module({"localOnlyMode": True})
        self.assertEqual(next(row for row in local.rows if row.id == "aiMode").value, "Local only")
        self.assertIn(NO_ONLINE_MODELS_IS_LOCAL_ONLY, local.warnings)
        privacy = settings_privacy_module(cloud_context="none")
        labels = [row.label for row in privacy.rows]
        self.assertIn("Cloud memory", labels)
        self.assertIn("Online for this request", labels)
        self.assertNotEqual(CLOUD_MEMORY_IS_OFF, CLOUD_MEMORY_STAYS_OFF)
        advanced_privacy = {row.id: row.value for row in privacy.advanced}
        self.assertEqual(advanced_privacy["cloudContextSession"], "Off")
        self.assertEqual(advanced_privacy["cloudContextDurable"], "Off")
        self.assertEqual(advanced_privacy["conversationSummary"], CONVERSATION_SUMMARY_UNWIRED)

    def test_javascript_bunny_and_ai_pages_match(self) -> None:
        js = run_node(
            f"import {{buildBunnyCompanionModule, buildAiModelsModule, "
            f"normalisePersonality, PERSONALITY_FORBIDDEN}} "
            f"from '{(LIB / 'bunnySettings.js').as_uri()}';\n"
            "console.log(JSON.stringify({"
            "bunny: buildBunnyCompanionModule({personality: 'claude'}),"
            "ai: buildAiModelsModule({localOnlyMode: true}),"
            "personality: normalisePersonality('gpt'),"
            "forbidden: PERSONALITY_FORBIDDEN}));\n"
        )
        self.assertEqual(js["personality"], "bunny")
        self.assertIn("claude", js["forbidden"])
        self.assertIn(NO_ONLINE_MODELS_IS_LOCAL_ONLY, js["bunny"]["warnings"])
        ai_row = next(item for item in js["ai"]["rows"] if item["id"] == "aiMode")
        self.assertEqual(ai_row["value"], "Local only")
        model = next(item for item in js["ai"]["advanced"] if item["id"] == "modelId")
        self.assertEqual(model["value"], "Unknown")


class OnboardingTests(unittest.TestCase):
    def test_cinematic_spine_is_short_and_skippable(self) -> None:
        ids = [step.step_id for step in ONBOARDING_STEPS]
        self.assertEqual(
            ids,
            ["welcome", "name", "timezone", "accessibility", "companion", "voice", "privacy", "finish"],
        )
        self.assertEqual(ONBOARDING_ESSENTIAL_IDS, ("welcome", "companion", "privacy", "finish"))
        required = [step.step_id for step in ONBOARDING_STEPS if step.required]
        self.assertEqual(required, ["welcome", "finish"])
        voice = next(step for step in ONBOARDING_STEPS if step.step_id == "voice")
        self.assertTrue(voice.skip)
        self.assertIn("I'll type", voice.skip)
        privacy = next(step for step in ONBOARDING_STEPS if step.step_id == "privacy")
        self.assertIn("Local only", privacy.body)
        self.assertIn("two different consents", privacy.body.casefold())
        finish = ONBOARDING_STEPS[-1]
        self.assertIn("corner", finish.body.casefold())

    def test_first_run_stages_match_the_intro_not_a_linux_wizard(self) -> None:
        keys = [entry.key for entry in FIRST_RUN_STAGES]
        self.assertEqual(
            keys,
            ["hello", "name", "timezone", "accessibility", "companion", "voice", "privacy", "done"],
        )
        self.assertTrue(FIRST_RUN_STAGES[-1].says.startswith("Ready."))
        self.assertIn("corner", FIRST_RUN_STAGES[-1].says)
        self.assertNotIn("language_region", keys)
        self.assertNotIn("keyboard", keys)
        self.assertNotIn("storage", keys)

    def test_offline_machine_completes_and_old_ids_resume(self) -> None:
        model = OnboardingModel()
        for _ in range(len(ONBOARDING_STEPS) - 1):
            step = model.step
            model.advance(skipped=not step.required and bool(step.skip))
        self.assertEqual(model.step.step_id, "finish")
        model.advance()
        self.assertTrue(model.complete)
        resumed = OnboardingModel()
        resumed.restore(step_id="microphone", answers={"character": "skipped"})
        self.assertEqual(resumed.step.step_id, "voice")
        self.assertEqual(resumed.answers.get("companion"), "skipped")


class LockLoginTests(NodeBackedTestCase):
    def test_lock_and_login_work_without_the_companion(self) -> None:
        lock = build_lock_screen(companion_hidden=True)
        self.assertFalse(lock["companionRequired"])
        self.assertFalse(lock["companionVisible"])
        self.assertTrue(lock["unlockWithoutCompanion"])
        self.assertTrue(lock["usableWithoutCompanion"])
        self.assertFalse(lock["chatbot"])
        self.assertFalse(lock["trustOnLock"])
        self.assertFalse(lock["gdmBranding"])
        self.assertEqual(lock["companionAnchor"], COMPANION_CORNER)
        self.assertEqual(lock["passwordAccessibleName"], LOCK_PASSWORD_NAME)
        self.assertEqual(lock["initialFocus"], "password")
        failed = build_lock_screen(companion_failed=True)
        self.assertTrue(failed["unlockWithoutCompanion"])
        login = build_login_screen(companion_hidden=True)
        self.assertTrue(login["stockGreeter"])
        self.assertTrue(login["usableWithoutCompanion"])
        self.assertFalse(login["chatbot"])

    def test_lock_redacts_sensitive_notices(self) -> None:
        lock = build_lock_screen(notices=(
            {"source": "Mail", "title": "Invoice", "sensitive": True},
            {"source": "Clock", "title": "Meeting", "sensitive": False},
        ))
        titles = [item["title"] for item in lock["notifications"]]
        self.assertIn("Sensitive notification", titles)
        self.assertIn("Meeting", titles)
        self.assertNotIn("Invoice", titles)

    def test_javascript_lock_matches_python(self) -> None:
        js = run_node(
            f"import {{buildLockScreen, buildLoginScreen}} from '{(LIB / 'lockScreen.js').as_uri()}';\n"
            "console.log(JSON.stringify({lock: buildLockScreen({companionHidden: true}),"
            "login: buildLoginScreen({companionFailed: true})}));\n"
        )
        self.assertFalse(js["lock"]["companionVisible"])
        self.assertTrue(js["lock"]["unlockWithoutCompanion"])
        self.assertTrue(js["login"]["usableWithoutCompanion"])
        self.assertEqual(js["lock"]["passwordAccessibleName"], LOCK_PASSWORD_NAME)


class HonestyWiringTests(NodeBackedTestCase):
    def test_no_online_models_sentence_is_byte_identical(self) -> None:
        measured = run_node(
            f"import {{NO_ONLINE_MODELS_IS_LOCAL_ONLY}} from '{(LIB / 'trustPrompt.js').as_uri()}';\n"
            "console.log(JSON.stringify({NO_ONLINE_MODELS_IS_LOCAL_ONLY}));\n"
        )
        self.assertEqual(measured["NO_ONLINE_MODELS_IS_LOCAL_ONLY"], NO_ONLINE_MODELS_IS_LOCAL_ONLY)
        self.assertEqual(USER_NO_ONLINE, NO_ONLINE_MODELS_IS_LOCAL_ONLY)
        self.assertIn("Local only", NO_ONLINE_MODELS_IS_LOCAL_ONLY)
        self.assertIn("not Cloud memory off", NO_ONLINE_MODELS_IS_LOCAL_ONLY)

    def test_pages_keep_the_two_consents_apart(self) -> None:
        pages = bunny_settings_pages()
        privacy = pages["privacy"]
        self.assertIn(CLOUD_MEMORY_IS_OFF, privacy.warnings)
        self.assertIn(CLOUD_MEMORY_STAYS_OFF, privacy.warnings)
        self.assertIn(NETWORK_ALLOWLIST_NOTE, privacy.warnings)
        self.assertIn(NO_ONLINE_MODELS_IS_LOCAL_ONLY, pages["ai-models"].warnings)
        ui = (ROOT / "shell/services/bunny_shell/ui.py").read_text(encoding="utf-8")
        self.assertIn("bunny_companion_module", ui)
        self.assertIn("ai_models_module", ui)
        self.assertIn("settings_privacy_module", ui)
        self.assertIn("build_lock_screen", ui)
        self.assertIn("NO_ONLINE_MODELS_IS_LOCAL_ONLY", ui)

    def test_shell_defaults_stay_local_first(self) -> None:
        self.assertEqual(DEFINITIONS["aiMode"]["default"], "automatic")
        self.assertEqual(DEFINITIONS["personality"]["default"], "bunny")
        self.assertEqual(DEFINITIONS["proactivity"]["default"], "off")
        with tempfile.TemporaryDirectory() as directory:
            store = SettingsStore(Path(directory) / "settings.json")
            self.assertEqual(store.get_all()["personality"], "bunny")
            self.assertEqual(store.get_all()["proactivity"], "off")
            store.set("aiMode", "local-only")
            self.assertTrue(store.get_all()["localOnlyMode"])


class FrozenEvidenceTests(unittest.TestCase):
    def test_phase7_frozen_evidence_is_not_retargeted(self) -> None:
        for relative in FROZEN:
            current = (ROOT / relative).read_bytes()
            committed = subprocess.check_output(
                ["git", "show", f"origin/main:{relative}"], cwd=ROOT)
            self.assertEqual(current, committed, f"{relative} must stay pinned to main")


if __name__ == "__main__":
    unittest.main()
