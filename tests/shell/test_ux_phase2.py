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
from bunny_shell.control_center import (
    AI_MODE_HINTS,
    AI_MODE_LABELS,
    AI_MODES,
    CONTROL_CENTER_MODULES,
    control_center,
    resolve_ai_mode,
)
from bunny_shell.notification_center import (
    QUIET_DEFAULTS,
    build_notification_center,
    should_toast,
)
from bunny_shell.settings import DEFINITIONS, SettingsStore
from bunny_shell.trust_copy import (
    ALLOWLISTED_CEILING_NOTE,
    ALLOW_ACCESSIBLE_NAME,
    ALLOW_ONCE_LABEL,
    CLIPBOARD_BLUETOOTH_NOTE,
    CLOUD_MEMORY_IS_OFF,
    CLOUD_MEMORY_STAYS_OFF,
    DENY_ACCESSIBLE_NAME,
    DONT_ALLOW_LABEL,
    NETWORK_ALLOWLIST_NOTE,
    NETWORK_FULL_INTERNET,
    NETWORK_OFF,
    bounded_allow_options,
    network_facing_label,
    network_is_declared_only,
    remote_dispatch_disclosure,
)
from companion.user_copy import (
    ALLOWLISTED_CEILING_NOTE as USER_ALLOWLISTED_CEILING,
    CLIPBOARD_BLUETOOTH_NOTE as USER_CLIPBOARD_BT,
    CLOUD_MEMORY_IS_OFF as USER_CLOUD_MEMORY_OFF,
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
            f"import {{NETWORK_ALLOWLIST_NOTE, CLOUD_MEMORY_STAYS_OFF, CLOUD_MEMORY_IS_OFF, "
            f"NETWORK_OFF, NETWORK_FULL_INTERNET, ALLOW_ONCE_LABEL, "
            f"DONT_ALLOW_LABEL, ALLOWLISTED_CEILING_NOTE, CLIPBOARD_BLUETOOTH_NOTE, "
            f"ALLOW_ACCESSIBLE_NAME, DENY_ACCESSIBLE_NAME}} "
            f"from '{(LIB / 'trustPrompt.js').as_uri()}';\n"
            "console.log(JSON.stringify({"
            "NETWORK_ALLOWLIST_NOTE, CLOUD_MEMORY_STAYS_OFF, CLOUD_MEMORY_IS_OFF, NETWORK_OFF, "
            "NETWORK_FULL_INTERNET, ALLOW_ONCE_LABEL, DONT_ALLOW_LABEL, "
            "ALLOWLISTED_CEILING_NOTE, CLIPBOARD_BLUETOOTH_NOTE, "
            "ALLOW_ACCESSIBLE_NAME, DENY_ACCESSIBLE_NAME}));\n"
        )
        self.assertEqual(measured["NETWORK_ALLOWLIST_NOTE"], NETWORK_ALLOWLIST_NOTE)
        self.assertEqual(measured["CLOUD_MEMORY_STAYS_OFF"], CLOUD_MEMORY_STAYS_OFF)
        self.assertEqual(measured["CLOUD_MEMORY_IS_OFF"], CLOUD_MEMORY_IS_OFF)
        self.assertEqual(measured["NETWORK_OFF"], NETWORK_OFF)
        self.assertEqual(measured["NETWORK_FULL_INTERNET"], NETWORK_FULL_INTERNET)
        self.assertEqual(measured["ALLOW_ONCE_LABEL"], ALLOW_ONCE_LABEL)
        self.assertEqual(measured["DONT_ALLOW_LABEL"], DONT_ALLOW_LABEL)
        self.assertEqual(measured["ALLOWLISTED_CEILING_NOTE"], ALLOWLISTED_CEILING_NOTE)
        self.assertEqual(measured["CLIPBOARD_BLUETOOTH_NOTE"], CLIPBOARD_BLUETOOTH_NOTE)
        self.assertEqual(measured["ALLOW_ACCESSIBLE_NAME"], ALLOW_ACCESSIBLE_NAME)
        self.assertEqual(measured["DENY_ACCESSIBLE_NAME"], DENY_ACCESSIBLE_NAME)
        self.assertEqual(USER_ALLOWLIST_NOTE, NETWORK_ALLOWLIST_NOTE)
        self.assertEqual(USER_CLOUD_MEMORY, CLOUD_MEMORY_STAYS_OFF)
        self.assertEqual(USER_CLOUD_MEMORY_OFF, CLOUD_MEMORY_IS_OFF)
        self.assertEqual(USER_NETWORK_OFF, NETWORK_OFF)
        self.assertEqual(USER_FULL_INTERNET, NETWORK_FULL_INTERNET)
        self.assertEqual(USER_ALLOWLISTED_CEILING, ALLOWLISTED_CEILING_NOTE)
        self.assertEqual(USER_CLIPBOARD_BT, CLIPBOARD_BLUETOOTH_NOTE)
        self.assertEqual(NETWORK_FULL_INTERNET, "On (full internet)")
        self.assertNotEqual(CLOUD_MEMORY_IS_OFF, CLOUD_MEMORY_STAYS_OFF)
        self.assertIn("that online service", CLOUD_MEMORY_STAYS_OFF)
        self.assertNotIn("an online service", CLOUD_MEMORY_STAYS_OFF)

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
        self.assertIn(CLOUD_MEMORY_IS_OFF, js["warnings"])
        self.assertIn(ALLOWLISTED_CEILING_NOTE, js["warnings"])
        self.assertIn(CLIPBOARD_BLUETOOTH_NOTE, js["warnings"])
        self.assertIn(NETWORK_ALLOWLIST_NOTE, py.warnings)
        self.assertIn(CLOUD_MEMORY_STAYS_OFF, py.warnings)
        self.assertIn(CLOUD_MEMORY_IS_OFF, py.warnings)
        self.assertIn(ALLOWLISTED_CEILING_NOTE, py.warnings)
        self.assertIn(CLIPBOARD_BLUETOOTH_NOTE, py.warnings)
        ids = {row["id"] for row in js["rows"]}
        self.assertIn("appClipboard", ids)
        self.assertIn("appBluetooth", ids)
        self.assertIn("remoteDispatch", ids)
        cloud = next(item for item in js["rows"] if item["id"] == "cloudContext")
        hop = next(item for item in js["rows"] if item["id"] == "remoteDispatch")
        self.assertEqual(cloud["hint"], CLOUD_MEMORY_IS_OFF)
        self.assertEqual(hop["hint"], CLOUD_MEMORY_STAYS_OFF)
        blob = json.dumps(js).casefold()
        self.assertNotIn("always allow everything", blob)
        self.assertNotIn("waiting for domains", blob)

    def test_a_hostname_or_allowlisted_ceiling_reads_as_off(self) -> None:
        self.assertEqual(network_facing_label("api.example.com"), NETWORK_OFF)
        self.assertTrue(network_is_declared_only("allowlisted"))
        self.assertTrue(network_is_declared_only("extensions.libreoffice.org"))
        self.assertFalse(network_is_declared_only("On"))
        self.assertEqual(network_facing_label("On"), NETWORK_FULL_INTERNET)
        self.assertEqual(network_facing_label("none"), NETWORK_OFF)
        self.assertEqual(network_facing_label("allowlisted"), NETWORK_OFF)
        measured = run_node(
            f"import {{networkFacingLabel, networkIsDeclaredOnly}} "
            f"from '{(LIB / 'trustPrompt.js').as_uri()}';\n"
            "console.log(JSON.stringify({"
            "listed: networkFacingLabel('api.example.com'),"
            "on: networkFacingLabel('On'),"
            "off: networkFacingLabel('none'),"
            "office: networkFacingLabel('allowlisted'),"
            "declared: networkIsDeclaredOnly('extensions.libreoffice.org')}));\n"
        )
        self.assertEqual(measured["listed"], NETWORK_OFF)
        self.assertEqual(measured["on"], NETWORK_FULL_INTERNET)
        self.assertEqual(measured["off"], NETWORK_OFF)
        self.assertEqual(measured["office"], NETWORK_OFF)
        self.assertTrue(measured["declared"])

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

    def test_voice_listening_is_off_until_wanted_and_ai_is_one_local_first_control(self) -> None:
        py = control_center()["ai"]
        listening = next(row for row in py.rows if row.id == "voiceListening")
        self.assertEqual(listening.value, "Off until you ask")
        self.assertIn("Super+Alt+Space", listening.hint)
        mode = next(row for row in py.rows if row.id == "aiMode")
        self.assertEqual(mode.value, "Automatic")
        self.assertEqual(resolve_ai_mode({}), "automatic")
        self.assertEqual(AI_MODES, ("automatic", "local-only", "online-enhanced"))
        js = run_node(
            f"import {{buildAiModule, AI_MODES, AI_MODE_LABELS, AI_MODE_HINTS, resolveAiMode}} "
            f"from '{(LIB / 'controlCenter.js').as_uri()}';\n"
            "console.log(JSON.stringify({"
            "module: buildAiModule({}),"
            "modes: AI_MODES,"
            "labels: AI_MODE_LABELS,"
            "hints: AI_MODE_HINTS,"
            "local: resolveAiMode({localOnlyMode: true, aiMode: 'automatic'}),"
            "online: buildAiModule({aiMode: 'online-enhanced'})}));\n"
        )
        row = next(item for item in js["module"]["rows"] if item["id"] == "voiceListening")
        self.assertEqual(row["value"], "Off until you ask")
        ai_row = next(item for item in js["module"]["rows"] if item["id"] == "aiMode")
        self.assertEqual(ai_row["value"], "Automatic")
        self.assertEqual(tuple(js["modes"]), AI_MODES)
        self.assertEqual(js["labels"], AI_MODE_LABELS)
        self.assertEqual(js["hints"], AI_MODE_HINTS)
        self.assertEqual(js["local"], "local-only")
        ids = {item["id"] for item in js["module"]["rows"]}
        self.assertNotIn("localAiEnabled", ids)
        self.assertNotIn("localOnlyMode", ids)
        self.assertEqual(set(AI_MODE_LABELS.values()), {"Automatic", "Local only", "Online enhanced"})
        self.assertNotIn("High", AI_MODE_LABELS.values())
        self.assertNotIn("Ultra", AI_MODE_LABELS.values())
        normal = json.dumps(js["module"]["rows"]).casefold()
        self.assertNotIn("gguf", normal)
        self.assertNotIn("tok/s", normal)
        self.assertNotIn("vram", normal)
        self.assertNotIn("npu", normal)
        self.assertNotIn("always cloud", json.dumps(js["online"]["rows"] + js["online"]["warnings"]).casefold().replace("not always cloud", ""))
        self.assertIn("not always cloud", json.dumps(js["online"]).casefold())
        self.assertEqual(
            next(item for item in js["online"]["rows"] if item["id"] == "aiMode")["value"],
            "Online enhanced",
        )
        local_py = control_center({"localOnlyMode": True})["ai"]
        self.assertEqual(next(row for row in local_py.rows if row.id == "aiMode").value, "Local only")
        self.assertTrue(any("will not ask to generate online" in note for note in local_py.warnings))

    def test_advanced_ai_stays_unknown_until_measured(self) -> None:
        from bunny_shell.control_center import (
            ACCELERATOR_UNKNOWN,
            CONVERSATION_SUMMARY_UNWIRED,
            THROUGHPUT_NOT_MEASURED,
            WHY_THIS_MODEL_UNAVAILABLE,
            accelerator_facing_label,
            throughput_facing_label,
        )
        py = control_center()["ai"]
        by_id = {row.id: row.value for row in py.advanced}
        self.assertEqual(py.advanced_title, "Advanced")
        self.assertEqual(by_id["modelId"], "Unknown")
        self.assertEqual(by_id["throughput"], THROUGHPUT_NOT_MEASURED)
        self.assertEqual(by_id["gpu"], ACCELERATOR_UNKNOWN)
        self.assertEqual(by_id["vram"], ACCELERATOR_UNKNOWN)
        self.assertEqual(by_id["npu"], ACCELERATOR_UNKNOWN)
        self.assertEqual(by_id["whyThisModel"], WHY_THIS_MODEL_UNAVAILABLE)
        self.assertEqual(throughput_facing_label("fast"), THROUGHPUT_NOT_MEASURED)
        self.assertEqual(throughput_facing_label(12), "12 tok/s")
        self.assertEqual(accelerator_facing_label("present-unusable"), "Unusable")
        self.assertEqual(accelerator_facing_label("nvidia"), ACCELERATOR_UNKNOWN)
        measured = control_center({"tokensPerSecond": 12, "gpu": "absent", "whyThisModel": "fits RAM"})["ai"]
        measured_ids = {row.id: row.value for row in measured.advanced}
        self.assertEqual(measured_ids["throughput"], "12 tok/s")
        self.assertEqual(measured_ids["gpu"], "Absent")
        self.assertEqual(measured_ids["whyThisModel"], "fits RAM")
        self.assertNotIn("tok/s", json.dumps([{"id": row.id, "value": row.value} for row in measured.rows]))
        privacy = control_center()["privacy"]
        privacy_ids = {row.id: row.value for row in privacy.advanced}
        self.assertEqual(privacy_ids["cloudContextSession"], "Off")
        self.assertEqual(privacy_ids["cloudContextDurable"], "Off")
        self.assertEqual(privacy_ids["conversationSummary"], CONVERSATION_SUMMARY_UNWIRED)
        js = run_node(
            f"import {{buildAiModule, buildPrivacyModule, THROUGHPUT_NOT_MEASURED, "
            f"ACCELERATOR_UNKNOWN, CONVERSATION_SUMMARY_UNWIRED}} "
            f"from '{(LIB / 'controlCenter.js').as_uri()}';\n"
            "console.log(JSON.stringify({"
            "ai: buildAiModule({}),"
            "measured: buildAiModule({tokensPerSecond: 12, gpu: 'absent'}),"
            "privacy: buildPrivacyModule({cloudContext: 'none'}),"
            "THROUGHPUT_NOT_MEASURED, ACCELERATOR_UNKNOWN, CONVERSATION_SUMMARY_UNWIRED}));\n"
        )
        js_ai = {row["id"]: row["value"] for row in js["ai"]["advanced"]}
        self.assertEqual(js_ai["throughput"], js["THROUGHPUT_NOT_MEASURED"])
        self.assertEqual(js_ai["gpu"], js["ACCELERATOR_UNKNOWN"])
        self.assertEqual(js["ai"]["advancedTitle"], "Advanced")
        self.assertEqual(
            next(row["value"] for row in js["measured"]["advanced"] if row["id"] == "throughput"),
            "12 tok/s",
        )
        self.assertEqual(
            next(row["value"] for row in js["privacy"]["advanced"] if row["id"] == "conversationSummary"),
            js["CONVERSATION_SUMMARY_UNWIRED"],
        )


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
        names = {button["accessibleName"] for button in model["buttons"]}
        self.assertEqual(names, {ALLOW_ACCESSIBLE_NAME, DENY_ACCESSIBLE_NAME})

    def test_unbounded_grants_are_dropped(self) -> None:
        self.assertEqual(
            bounded_allow_options(
                [{"scope": "always", "label": "Always allow everything"}],
                "files",
            ),
            [],
        )
        self.assertEqual(
            [item["scope"] for item in bounded_allow_options(
                [{"scope": "session", "label": "Allow while using"},
                 {"scope": "always", "label": "Always allow"}],
                "network",
            )],
            ["session"],
        )
        model = run_node(
            f"import {{buildPrompt, boundedAllowOptions}} from '{(LIB / 'trustPrompt.js').as_uri()}';\n"
            "const record = {requestId: 'r', headline: 'Network?', category: 'network',"
            "options: [{scope: 'always', label: 'Always allow everything'},"
            "{scope: 'session', label: 'Allow while using'}],"
            "denyOption: {verdict: 'deny', label: \"Don't allow\"}};\n"
            "console.log(JSON.stringify({model: buildPrompt(record),"
            "kept: boundedAllowOptions(record.options, 'network')}));\n"
        )
        labels = [button["label"] for button in model["model"]["buttons"]]
        self.assertNotIn("Always allow everything", labels)
        self.assertNotIn("Always allow", labels)
        self.assertIn("Don't allow", labels)
        self.assertEqual(model["model"]["initialFocus"], "deny")
        blob = json.dumps(model).casefold()
        self.assertNotIn("always allow everything", blob)

    def test_libreoffice_allowlisted_ceiling_reads_as_no_network(self) -> None:
        model = run_node(
            f"import {{buildApproval}} from '{(LIB / 'trustPrompt.js').as_uri()}';\n"
            "console.log(JSON.stringify(buildApproval({requestId: 'r',"
            "prompt: {applicationName: 'LibreOffice',"
            "network: 'allowlisted', kind: 'capsule-task'}})));\n"
        )
        network = next(row for row in model["confinement"] if row["key"] == "network")
        self.assertEqual(network["value"], NETWORK_OFF)
        self.assertEqual(network["standing"], "blocked")
        body = " ".join(line["text"] for line in model["body"])
        self.assertIn(ALLOWLISTED_CEILING_NOTE, body)
        self.assertNotIn("waiting for domains", body.casefold())
        self.assertNotIn("extensions.libreoffice.org", json.dumps(model))

    def test_clipboard_and_bluetooth_prompts_do_not_imply_mediation(self) -> None:
        model = run_node(
            f"import {{buildPrompt}} from '{(LIB / 'trustPrompt.js').as_uri()}';\n"
            "console.log(JSON.stringify(buildPrompt({requestId: 'r',"
            "headline: 'Notes wants to read what you copied.',"
            "category: 'clipboard', categoryTitle: 'Clipboard',"
            "options: [{scope: 'once', label: 'Allow once'}],"
            "denyOption: {verdict: 'deny', label: \"Don't allow\"}})));\n"
        )
        body = " ".join(line["text"] for line in model["body"])
        self.assertIn(CLIPBOARD_BLUETOOTH_NOTE, body)
        self.assertFalse(model["enforced"])
        self.assertEqual(model["standing"], "unenforced")
        names = {button["accessibleName"] for button in model["buttons"]}
        self.assertEqual(names, {ALLOW_ACCESSIBLE_NAME, DENY_ACCESSIBLE_NAME})

    def test_gtk_privacy_and_settings_surfaces_include_the_honesty_copy(self) -> None:
        ui = (ROOT / "shell/services/bunny_shell/ui.py").read_text(encoding="utf-8")
        self.assertIn("ALLOWLISTED_CEILING_NOTE", ui)
        self.assertIn("CLIPBOARD_BLUETOOTH_NOTE", ui)
        self.assertIn("CLOUD_MEMORY_IS_OFF", ui)
        self.assertIn("CLOUD_MEMORY_STAYS_OFF", ui)
        self.assertIn("advanced", ui)
        self.assertIn("privacy_module", ui)
        self.assertIn("route_command_answer", ui)
        self.assertIn("build_notification_center", ui)

    def test_notification_summary_defaults_on(self) -> None:
        self.assertTrue(DEFINITIONS["bunnyNotificationSummary"]["default"])
        self.assertEqual(DEFINITIONS["aiMode"]["default"], "automatic")
        self.assertTrue(DEFINITIONS["voiceEnabled"]["default"])
        self.assertTrue(DEFINITIONS["microphoneEnabled"]["default"])
        with tempfile.TemporaryDirectory() as directory:
            store = SettingsStore(Path(directory) / "settings.json")
            self.assertTrue(store.get_all()["bunnyNotificationSummary"])
            self.assertEqual(store.get_all()["aiMode"], "automatic")
            self.assertFalse(store.get_all()["localOnlyMode"])
            store.set("aiMode", "local-only")
            values = store.get_all()
            self.assertTrue(values["localOnlyMode"])
            self.assertEqual(values["aiMode"], "local-only")
            self.assertEqual(values["cloudFailoverPolicy"], "never")
            store.set("aiMode", "online-enhanced")
            values = store.get_all()
            self.assertFalse(values["localOnlyMode"])
            self.assertEqual(values["aiMode"], "online-enhanced")
            self.assertTrue(values["voiceEnabled"])


class FrozenEvidenceTests(unittest.TestCase):
    def test_phase7_frozen_evidence_is_not_retargeted(self) -> None:
        for relative in FROZEN:
            current = (ROOT / relative).read_bytes()
            committed = subprocess.check_output(
                ["git", "show", f"origin/main:{relative}"], cwd=ROOT)
            self.assertEqual(current, committed, f"{relative} must stay pinned to main")


if __name__ == "__main__":
    unittest.main()
