# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""UX Phase 2: command surface, Control Center, notifications, Trust honesty.

Host-testable models and copy. Live GNOME is not claimed.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from bunny_shell.command_surface import (
    COMMAND_ACCELERATOR,
    COMMAND_TRIGGERS,
    build_command_surface,
    route_command_answer,
)
from bunny_shell.control_center import CONTROL_CENTER_MODULES, control_center
from bunny_shell.notification_center import (
    QUIET_DEFAULTS,
    build_notification_center,
    should_toast,
)
from bunny_shell.settings import DEFINITIONS, SettingsStore
from bunny_shell.trust_copy import (
    ALLOW_ONCE_LABEL,
    CLOUD_MEMORY_STAYS_OFF,
    DONT_ALLOW_LABEL,
    NETWORK_ALLOWLIST_NOTE,
    NETWORK_FULL_INTERNET,
    NETWORK_OFF,
    network_facing_label,
    remote_dispatch_disclosure,
)
from companion.user_copy import (
    CLOUD_MEMORY_STAYS_OFF as USER_CLOUD_MEMORY,
    NETWORK_ALLOWLIST_NOTE as USER_ALLOWLIST_NOTE,
    NETWORK_FULL_INTERNET as USER_FULL_INTERNET,
    NETWORK_OFF as USER_NETWORK_OFF,
)
from tests.support import ROOT

LIB = ROOT / "shell/components/gnome-shell-extension/lib"
EXTENSION = ROOT / "shell/components/gnome-shell-extension"
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


class HonestyCopyTests(NodeBackedTestCase):
    """Security #47 and #52: the same two sentences everywhere they are shown."""

    def test_javascript_and_python_honesty_strings_are_byte_identical(self) -> None:
        measured = run_node(
            f"import {{NETWORK_ALLOWLIST_NOTE, CLOUD_MEMORY_STAYS_OFF, "
            f"NETWORK_OFF, NETWORK_FULL_INTERNET, ALLOW_ONCE_LABEL, "
            f"DONT_ALLOW_LABEL}} from '{(LIB / 'trustPrompt.js').as_uri()}';\n"
            "console.log(JSON.stringify({"
            "NETWORK_ALLOWLIST_NOTE, CLOUD_MEMORY_STAYS_OFF, NETWORK_OFF, "
            "NETWORK_FULL_INTERNET, ALLOW_ONCE_LABEL, DONT_ALLOW_LABEL}));\n"
        )
        self.assertEqual(measured["NETWORK_ALLOWLIST_NOTE"], NETWORK_ALLOWLIST_NOTE)
        self.assertEqual(measured["CLOUD_MEMORY_STAYS_OFF"], CLOUD_MEMORY_STAYS_OFF)
        self.assertEqual(measured["NETWORK_OFF"], NETWORK_OFF)
        self.assertEqual(measured["NETWORK_FULL_INTERNET"], NETWORK_FULL_INTERNET)
        self.assertEqual(measured["ALLOW_ONCE_LABEL"], ALLOW_ONCE_LABEL)
        self.assertEqual(measured["DONT_ALLOW_LABEL"], DONT_ALLOW_LABEL)
        self.assertEqual(USER_ALLOWLIST_NOTE, NETWORK_ALLOWLIST_NOTE)
        self.assertEqual(USER_CLOUD_MEMORY, CLOUD_MEMORY_STAYS_OFF)
        self.assertEqual(USER_NETWORK_OFF, NETWORK_OFF)
        self.assertEqual(USER_FULL_INTERNET, NETWORK_FULL_INTERNET)

    def test_permission_card_reuses_the_allowlist_sentence(self) -> None:
        card = run_node(
            f"import {{buildPermissionCard}} from '{(LIB / 'design/primitives.js').as_uri()}';\n"
            "console.log(JSON.stringify(buildPermissionCard({network: 'Off'})));\n"
        )
        self.assertEqual(card["networkHonesty"], NETWORK_ALLOWLIST_NOTE)

    def test_control_center_privacy_carries_both_sentences(self) -> None:
        js = run_node(
            f"import {{buildPrivacyModule}} from '{(LIB / 'controlCenter.js').as_uri()}';\n"
            "console.log(JSON.stringify(buildPrivacyModule({cloudContext: 'none'})));\n"
        )
        py = control_center(cloud_context="none")["privacy"]
        self.assertIn(NETWORK_ALLOWLIST_NOTE, js["warnings"])
        self.assertIn(CLOUD_MEMORY_STAYS_OFF, js["warnings"])
        self.assertIn(NETWORK_ALLOWLIST_NOTE, py.warnings)
        self.assertIn(CLOUD_MEMORY_STAYS_OFF, py.warnings)

    def test_a_hostname_is_full_internet_and_is_not_reprinted(self) -> None:
        self.assertEqual(network_facing_label("api.example.com"), NETWORK_FULL_INTERNET)
        self.assertEqual(network_facing_label("On"), NETWORK_FULL_INTERNET)
        self.assertEqual(network_facing_label("none"), NETWORK_OFF)
        measured = run_node(
            f"import {{networkFacingLabel}} from '{(LIB / 'trustPrompt.js').as_uri()}';\n"
            "console.log(JSON.stringify({"
            "listed: networkFacingLabel('api.example.com'),"
            "on: networkFacingLabel('On'),"
            "off: networkFacingLabel('none')}));\n"
        )
        self.assertEqual(measured["listed"], NETWORK_FULL_INTERNET)
        self.assertEqual(measured["on"], NETWORK_FULL_INTERNET)
        self.assertEqual(measured["off"], NETWORK_OFF)

    def test_remote_dispatch_disclosure_only_when_cloud_memory_is_off(self) -> None:
        self.assertEqual(
            remote_dispatch_disclosure(cloud_context="none", offering_remote_dispatch=True),
            CLOUD_MEMORY_STAYS_OFF,
        )
        self.assertEqual(
            remote_dispatch_disclosure(cloud_context="none", offering_remote_dispatch=False),
            "",
        )
        self.assertEqual(
            remote_dispatch_disclosure(cloud_context="minimized", offering_remote_dispatch=True),
            "",
        )


class CommandSurfaceTests(NodeBackedTestCase):
    def test_short_answers_stay_in_the_bubble(self) -> None:
        routed = route_command_answer("The file is on the desktop.")
        self.assertEqual(routed.surface, "bubble")
        self.assertFalse(routed.transcript)
        self.assertFalse(routed.companion_required)
        js = run_node(
            f"import {{routeCommandAnswer}} from '{(LIB / 'commandSurface.js').as_uri()}';\n"
            "console.log(JSON.stringify(routeCommandAnswer('The file is on the desktop.')));\n"
        )
        self.assertEqual(js["surface"], "bubble")
        self.assertFalse(js["transcript"])
        self.assertFalse(js["companionRequired"])
        self.assertFalse(js["chatbot"] if "chatbot" in js else False)

    def test_longer_work_opens_a_task_card_not_a_transcript(self) -> None:
        long = (
            "First I will open the file. Then I will resize it. "
            "Then I will save a copy. Then I will tell you where it went."
        )
        routed = route_command_answer(long)
        self.assertEqual(routed.surface, "task-card")
        self.assertFalse(routed.transcript)
        js = run_node(
            f"import {{routeCommandAnswer}} from '{(LIB / 'commandSurface.js').as_uri()}';\n"
            f"console.log(JSON.stringify(routeCommandAnswer({json.dumps(long)})));\n"
        )
        self.assertEqual(js["surface"], "task-card")
        self.assertIsNotNone(js["taskCard"])
        self.assertFalse(js["transcript"])

    def test_named_stages_and_working_are_task_cards(self) -> None:
        self.assertEqual(route_command_answer("Working.", working=True).surface, "task-card")
        self.assertEqual(
            route_command_answer("Working.", stages=("Plan", "Run")).surface, "task-card")
        js = run_node(
            f"import {{routeCommandAnswer}} from '{(LIB / 'commandSurface.js').as_uri()}';\n"
            "console.log(JSON.stringify({"
            "working: routeCommandAnswer('Working.', {working: true}).surface,"
            "stages: routeCommandAnswer('Working.', {stages: ['Plan']}).surface}));\n"
        )
        self.assertEqual(js["working"], "task-card")
        self.assertEqual(js["stages"], "task-card")

    def test_the_empty_surface_is_a_search_field(self) -> None:
        surface = build_command_surface(trigger="super-space")
        self.assertEqual(surface.trigger, "super-space")
        self.assertEqual(surface.accelerator, COMMAND_ACCELERATOR)
        self.assertFalse(surface.transcript)
        self.assertFalse(surface.chatbot)
        self.assertFalse(surface.companion_required)
        js = run_node(
            f"import {{buildCommandSurface, COMMAND_TRIGGERS, COMMAND_ACCELERATOR}} "
            f"from '{(LIB / 'commandSurface.js').as_uri()}';\n"
            "console.log(JSON.stringify({surface: buildCommandSurface({trigger: 'super-space'}),"
            "triggers: COMMAND_TRIGGERS, accelerator: COMMAND_ACCELERATOR}));\n"
        )
        self.assertEqual(js["accelerator"], "<Super>space")
        self.assertEqual(js["accelerator"], COMMAND_ACCELERATOR)
        self.assertEqual(tuple(js["triggers"]), COMMAND_TRIGGERS)
        self.assertEqual(js["surface"]["opens"], "search-field")
        self.assertFalse(js["surface"]["transcript"])
        self.assertFalse(js["surface"]["chatbot"])
        self.assertFalse(js["surface"]["companionRequired"])
        self.assertEqual(js["surface"]["accessibleName"], "Search or ask Bunny")

    def test_super_space_opens_the_command_surface_not_a_chat(self) -> None:
        shell = (LIB / "desktopShell.js").read_text(encoding="utf-8")
        extension = (EXTENSION / "extension.js").read_text(encoding="utf-8")
        schema = (EXTENSION / "schemas/org.gnome.shell.extensions.bunny-shell.gschema.xml").read_text(
            encoding="utf-8")
        self.assertIn("bind('open-launcher', () => this._openCommandSurface('super-space'))", shell)
        self.assertIn("bind('focus-desktop-assistant', () => this._activateAssistant())", shell)
        self.assertNotIn("addTurn", shell)
        self.assertIn("_presentCommandAnswer", shell)
        self.assertIn("if (key === 'open-launcher' && this._settings.get_boolean('desktop-enabled'))",
                      extension)
        self.assertIn("&lt;Super&gt;space", schema.split('name="open-launcher"', 1)[1].split("</key>", 1)[0])
        assistant = schema.split('name="focus-desktop-assistant"', 1)[1].split("</key>", 1)[0]
        self.assertNotIn("&lt;Super&gt;space", assistant)


class ControlCenterTests(NodeBackedTestCase):
    def test_the_three_bunny_modules_exist(self) -> None:
        self.assertEqual(CONTROL_CENTER_MODULES, ("bunny", "ai", "privacy"))
        js = run_node(
            f"import {{buildControlCenter, CONTROL_CENTER_MODULES}} "
            f"from '{(LIB / 'controlCenter.js').as_uri()}';\n"
            "console.log(JSON.stringify({ids: CONTROL_CENTER_MODULES,"
            "model: buildControlCenter()}));\n"
        )
        self.assertEqual(js["ids"], ["bunny", "ai", "privacy"])
        self.assertEqual([module["id"] for module in js["model"]["modules"]], ["bunny", "ai", "privacy"])
        self.assertTrue(js["model"]["gnomeOwnsDevices"])
        self.assertFalse(js["model"]["companionRequired"])
        for module in js["model"]["modules"]:
            self.assertFalse(module["companionRequired"])
            self.assertTrue(module["canFocus"])

    def test_voice_listening_is_off_until_wanted_and_ai_is_local_first(self) -> None:
        py = control_center()["ai"]
        listening = next(row for row in py.rows if row.id == "voiceListening")
        self.assertEqual(listening.value, "Off until you ask")
        self.assertIn("Super+Alt+Space", listening.hint)
        js = run_node(
            f"import {{buildAiModule}} from '{(LIB / 'controlCenter.js').as_uri()}';\n"
            "console.log(JSON.stringify(buildAiModule({localAiEnabled: true})));\n"
        )
        row = next(item for item in js["rows"] if item["id"] == "voiceListening")
        self.assertEqual(row["value"], "Off until you ask")
        local = next(item for item in js["rows"] if item["id"] == "localAiEnabled")
        self.assertEqual(local["value"], "On")


class NotificationCenterTests(NodeBackedTestCase):
    def test_quiet_defaults_fold_duplicate_info_and_summarize_bunny(self) -> None:
        self.assertTrue(QUIET_DEFAULTS["quiet"])
        self.assertEqual(QUIET_DEFAULTS["max_visible_toasts"], 3)
        items = (
            {"source": "Bunny", "title": "Working", "body": "step 1", "severity": "info", "at": 1000},
            {"source": "Bunny", "title": "Working", "body": "step 2", "severity": "info", "at": 1500},
            {"source": "Files", "title": "Saved", "body": "holiday.png", "severity": "info", "at": 2000},
        )
        center = build_notification_center(items)
        self.assertFalse(center["spam"])
        self.assertFalse(center["companionRequired"])
        self.assertEqual(center["maxVisibleToasts"], 3)
        self.assertTrue(center["bunnySummary"])
        self.assertEqual(len(center["items"]), 2)
        self.assertTrue(center["items"][0]["title"].startswith("Working"))
        js = run_node(
            f"import {{buildNotificationCenter, shouldToast}} "
            f"from '{(LIB / 'notificationCenter.js').as_uri()}';\n"
            f"const model = buildNotificationCenter({{items: {json.dumps(items)}}});\n"
            "console.log(JSON.stringify({model, toast: shouldToast('info', 'Working', "
            "[{level: 'info', message: 'Working', at: 1}], {quiet: true, now: 1000})}));\n"
        )
        self.assertEqual(len(js["model"]["items"]), 2)
        self.assertFalse(js["model"]["spam"])
        self.assertFalse(js["toast"])

    def test_errors_still_toast_and_do_not_disturb_hides_the_list(self) -> None:
        self.assertTrue(should_toast("error", "failed", [{"level": "error", "message": "failed", "at": 1}], now=10))
        silent = build_notification_center(
            [{"source": "Bunny", "title": "Working", "severity": "info", "at": 1}],
            do_not_disturb=True,
        )
        self.assertEqual(silent["items"], [])
        self.assertIn("Do Not Disturb", silent["emptyCopy"])


class PermissionChromeTests(NodeBackedTestCase):
    def test_deny_is_the_default_and_labels_are_allow_once_dont_allow(self) -> None:
        model = run_node(
            f"import {{buildApproval}} from '{(LIB / 'trustPrompt.js').as_uri()}';\n"
            "console.log(JSON.stringify(buildApproval({requestId: 'r', "
            "action: 'remote_dispatch', cloudContext: 'none', "
            "prompt: {network: 'Off', kind: 'remote_dispatch'}})));\n"
        )
        self.assertEqual(model["initialFocus"], "deny")
        self.assertEqual(model["defaultAction"], "deny")
        self.assertEqual(model["escapeAction"], "deny")
        self.assertEqual(model["closeAction"], "deny")
        self.assertEqual([button["label"] for button in model["buttons"]],
                         [ALLOW_ONCE_LABEL, DONT_ALLOW_LABEL])
        body = " ".join(line["text"] for line in model["body"])
        self.assertIn(NETWORK_ALLOWLIST_NOTE, body)
        self.assertIn(CLOUD_MEMORY_STAYS_OFF, body)

    def test_gtk_privacy_and_settings_surfaces_include_the_honesty_copy(self) -> None:
        ui = (ROOT / "shell/services/bunny_shell/ui.py").read_text(encoding="utf-8")
        self.assertIn("NETWORK_ALLOWLIST_NOTE", ui)
        self.assertIn("CLOUD_MEMORY_STAYS_OFF", ui)
        self.assertIn("privacy_module", ui)
        self.assertIn("route_command_answer", ui)
        self.assertIn("build_notification_center", ui)

    def test_notification_summary_defaults_on(self) -> None:
        self.assertTrue(DEFINITIONS["bunnyNotificationSummary"]["default"])
        with tempfile.TemporaryDirectory() as directory:
            store = SettingsStore(Path(directory) / "settings.json")
            self.assertTrue(store.get_all()["bunnyNotificationSummary"])


class FrozenEvidenceTests(unittest.TestCase):
    def test_phase7_frozen_evidence_is_not_retargeted(self) -> None:
        for relative in FROZEN:
            current = (ROOT / relative).read_bytes()
            committed = subprocess.check_output(
                ["git", "show", f"origin/main:{relative}"], cwd=ROOT)
            self.assertEqual(current, committed, f"{relative} must stay pinned to main")


if __name__ == "__main__":
    unittest.main()
