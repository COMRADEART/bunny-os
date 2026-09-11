# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""UX Phase 4: Bunny Files, remaining app chrome, snap, responsive, rendering tiers.

Host-testable models and copy. Live GNOME is not claimed. Not IMAGE. Not BOOT.
STATUS PARTIAL.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from bunny_shell.app_chrome import (
    IN_TREE_APPS,
    build_app_chrome,
    build_software_chrome,
    build_terminal_chrome,
    build_updates_chrome,
)
from bunny_shell.bunny_files import (
    FILE_ACTIONS,
    apply_file_open_after_trust,
    build_bunny_files,
    file_open_needs_trust,
    granted_file_path,
    parse_files_uri,
    resolve_file_open_after_trust,
    route_files_action,
)
from bunny_shell.bunny_settings import bunny_companion_module
from bunny_shell.multitasking import (
    COMPANION_CORNER,
    NAMED_VIEWPORTS,
    SNAP_TARGETS,
    build_multitasking,
    viewport_for_name,
)
from bunny_shell.settings import DEFINITIONS, SettingsStore
from bunny_shell.terminal import propose
from bunny_shell.trust_copy import (
    ALLOW_ONCE_LABEL,
    DONT_ALLOW_LABEL,
    FILE_NOT_UPLOADED,
    FILE_OPEN_BUBBLE,
    FILE_OPEN_DENIED,
    FILE_OPEN_DRIFT,
    FILE_OPEN_EXPIRED,
    FILE_OPEN_FAILED,
    FILE_OPEN_GRANTED,
    FILE_OPEN_HEADLINE,
    NETWORK_ALLOWLIST_NOTE,
)
from companion.os_companion import fidelity_for_tier, tier_is_fully_featured, tier_is_implemented
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


class BunnyFilesTests(NodeBackedTestCase):
    def test_overlay_is_a_sheet_not_a_chatbot(self) -> None:
        model = build_bunny_files(query="notes", reduced_motion=True)
        self.assertEqual(model["kind"], "BunnyFiles")
        self.assertFalse(model["chatbot"])
        self.assertFalse(model["transcript"])
        self.assertFalse(model["companionRequired"])
        self.assertTrue(model["nautilusIsBrowser"])
        self.assertFalse(model["uploaded"])
        self.assertEqual(model["note"], FILE_NOT_UPLOADED)
        self.assertEqual(model["motionMs"], 0)
        self.assertEqual(model["actions"], list(FILE_ACTIONS))
        self.assertIn("open", model["actions"])

    def test_open_always_needs_trust_and_deny_is_the_safe_answer(self) -> None:
        self.assertTrue(file_open_needs_trust(action="open", approved_location=True))
        routed = route_files_action(action="open", paths=["/home/ravi/docs/notes.txt"], application="Text Editor")
        self.assertEqual(routed["surface"], "trust")
        self.assertTrue(routed["needsTrust"])
        self.assertEqual(routed["bubbleText"], FILE_OPEN_BUBBLE)
        self.assertEqual(routed["trust"]["denyLabel"], DONT_ALLOW_LABEL)
        self.assertEqual(routed["trust"]["allowLabel"], ALLOW_ONCE_LABEL)
        self.assertTrue(routed["trust"]["focusSafeAnswer"])
        self.assertIn("notes.txt", routed["trust"]["heading"])
        self.assertEqual(routed["note"], FILE_NOT_UPLOADED)
        ask = route_files_action(action="ask", paths=["/home/ravi/docs/notes.txt"])
        self.assertEqual(ask["surface"], "bubble")
        self.assertFalse(ask["needsTrust"])
        self.assertFalse(ask["chatbot"])

    def test_nautilus_uri_handoff_parses(self) -> None:
        parsed = parse_files_uri("bunny://files/ask?selection=file%3A%2F%2Ftmp%2Fphoto.png")
        self.assertTrue(parsed["valid"])
        self.assertEqual(parsed["action"], "ask")
        self.assertEqual(parsed["paths"], ["file://tmp/photo.png"])
        self.assertFalse(parsed["companionRequired"])
        self.assertFalse(parse_files_uri("https://example.com")["valid"])

    def test_javascript_files_match_python(self) -> None:
        js = run_node(
            f"import {{buildBunnyFiles, routeFilesAction, parseFilesUri, FILE_OPEN_BUBBLE, FILE_NOT_UPLOADED}} "
            f"from '{(LIB / 'bunnyFiles.js').as_uri()}';\n"
            "import {FILE_OPEN_BUBBLE as TRUST_BUBBLE, FILE_NOT_UPLOADED as TRUST_NOTE, "
            "DONT_ALLOW_LABEL} from "
            f"'{(LIB / 'trustPrompt.js').as_uri()}';\n"
            "const files = buildBunnyFiles({reducedMotion: true});\n"
            "const open = routeFilesAction({action: 'open', paths: ['/tmp/a.txt'], application: 'GIMP'});\n"
            "const parsed = parseFilesUri('bunny://files/summarise?selection=file%3A%2F%2Fx');\n"
            "console.log(JSON.stringify({files, open, parsed, TRUST_BUBBLE, TRUST_NOTE, DONT_ALLOW_LABEL}));\n"
        )
        self.assertEqual(js["TRUST_BUBBLE"], FILE_OPEN_BUBBLE)
        self.assertEqual(js["TRUST_NOTE"], FILE_NOT_UPLOADED)
        self.assertEqual(js["DONT_ALLOW_LABEL"], DONT_ALLOW_LABEL)
        self.assertFalse(js["files"]["chatbot"])
        self.assertEqual(js["files"]["motionMs"], 0)
        self.assertEqual(js["open"]["surface"], "trust")
        self.assertTrue(js["open"]["trust"]["focusSafeAnswer"])
        self.assertEqual(js["parsed"]["action"], "summarise")
        self.assertIn(FILE_OPEN_HEADLINE.split()[0], "Bunny")


class AppChromeTests(NodeBackedTestCase):
    def test_in_tree_apps_are_terminal_software_updates(self) -> None:
        self.assertEqual(IN_TREE_APPS, ("terminal", "software", "updates"))
        term = build_terminal_chrome(command="ls", classification="read_only")
        self.assertFalse(term["companionRequired"])
        self.assertIn("Not required", term["rows"][2]["value"])
        risky = build_terminal_chrome(command="rm -rf tmp", classification="destructive")
        self.assertIn("Trust", risky["next"])
        store = build_software_chrome(installed=False)
        self.assertEqual(store["rows"][1]["value"], "No")
        self.assertIn(NETWORK_ALLOWLIST_NOTE, store["warnings"])
        updates = build_updates_chrome()
        values = {row["value"] for row in updates["rows"]}
        self.assertNotIn("PASS", values)
        self.assertNotIn("IMAGE", values)
        self.assertNotIn("BOOT", values)
        self.assertIn("broker", json.dumps(updates["rows"]).casefold())
        self.assertIn("not a boot claim", updates["next"].casefold())

    def test_javascript_chrome_matches_python(self) -> None:
        js = run_node(
            f"import {{buildTerminalChrome, buildSoftwareChrome, buildUpdatesChrome, IN_TREE_APPS}} "
            f"from '{(LIB / 'appChrome.js').as_uri()}';\n"
            "console.log(JSON.stringify({"
            "apps: IN_TREE_APPS,"
            "term: buildTerminalChrome({classification: 'network_action', reducedMotion: true}),"
            "store: buildSoftwareChrome({installed: true}),"
            "updates: buildUpdatesChrome()}));\n"
        )
        self.assertEqual(js["apps"], list(IN_TREE_APPS))
        self.assertEqual(js["term"]["motionMs"], 0)
        self.assertIn("Trust", js["term"]["next"])
        self.assertEqual(js["store"]["rows"][0]["value"], "GNOME Software")
        self.assertIn("Not a boot claim", js["updates"]["next"])
        proposal = propose("ls", str(ROOT))
        self.assertEqual(proposal.classification, "read_only")
        self.assertEqual(build_app_chrome("updates")["id"], "updates")


class MultitaskingTests(NodeBackedTestCase):
    def test_python_chrome_keeps_companion_optional(self) -> None:
        model = build_multitasking(reduced_motion=True, screen=NAMED_VIEWPORTS["hd1366"])
        self.assertEqual(model["companionCorner"], COMPANION_CORNER)
        self.assertFalse(model["companionRequired"])
        self.assertFalse(model["companionCoversWork"])
        self.assertFalse(model["liveMutterTiling"])
        self.assertEqual(model["motionMs"], 0)
        self.assertEqual(model["snapTargets"], list(SNAP_TARGETS))
        self.assertEqual(viewport_for_name("4K")["width"], 3840)

    def test_snap_does_not_cover_companion_at_named_viewports(self) -> None:
        measured = run_node(
            f"import {{snapLayout, NAMED_VIEWPORTS}} from '{(LIB / 'layout.js').as_uri()}';\n"
            "const scales = [1, 1.5, 2];\n"
            "const out = {};\n"
            "for (const [name, screen] of Object.entries(NAMED_VIEWPORTS)) {\n"
            "  out[name] = scales.map(scale => {\n"
            "    const layout = snapLayout(screen, {profile: 'skeleton', scale});\n"
            "    return {\n"
            "      scale, covering: layout.covering, corner: layout.companionCorner,\n"
            "      work: layout.work, reserved: layout.reserved,\n"
            "      overlaps: layout.companionCoversWork,\n"
            "      workWide: layout.work.width >= 320, workTall: layout.work.height >= 240,\n"
            "    };\n"
            "  });\n"
            "}\n"
            "console.log(JSON.stringify(out));\n"
        )
        for name in ("hd1366", "fhd", "uhd"):
            self.assertIn(name, measured)
            for row in measured[name]:
                self.assertEqual(row["corner"], "bottom-right")
                self.assertEqual(row["covering"], [])
                self.assertFalse(row["overlaps"])
                self.assertTrue(row["workWide"])
                self.assertTrue(row["workTall"])
                self.assertLess(row["work"]["x"] + row["work"]["width"], row["reserved"]["x"] + 1)

    def test_javascript_multitasking_chrome_matches(self) -> None:
        js = run_node(
            f"import {{buildMultitasking, COMPANION_CORNER}} from '{(LIB / 'multitasking.js').as_uri()}';\n"
            "console.log(JSON.stringify(buildMultitasking({reducedMotion: true, "
            "screen: {width: 1366, height: 768}})));\n"
        )
        self.assertEqual(js["companionCorner"], COMPANION_CORNER)
        self.assertFalse(js["companionCoversWork"])
        self.assertEqual(js["motionMs"], 0)
        self.assertEqual(js["viewport"], "1366×768")


class RenderingTierTests(NodeBackedTestCase):
    def test_python_tokens_mark_all_tiers_implemented_and_only_full_featured(self) -> None:
        for name in ("FULL", "BALANCED", "LIGHT", "MINIMAL"):
            self.assertTrue(tier_is_implemented(name), name)
        self.assertTrue(tier_is_fully_featured("FULL"))
        self.assertFalse(tier_is_fully_featured("BALANCED"))
        self.assertEqual(fidelity_for_tier("BALANCED"), "lightweight-3d")
        self.assertEqual(DEFINITIONS["renderingTier"]["default"], "FULL")
        module = bunny_companion_module({"renderingTier": "LIGHT"})
        ids = [row.id for row in module.rows]
        self.assertIn("renderingTier", ids)
        with tempfile.TemporaryDirectory() as directory:
            store = SettingsStore(Path(directory) / "settings.json")
            self.assertEqual(store.get_all()["renderingTier"], "FULL")
            store.set("renderingTier", "MINIMAL")
            self.assertEqual(store.get_all()["renderingTier"], "MINIMAL")

    def test_balanced_cannot_claim_full_and_reduced_motion_is_not_a_tier(self) -> None:
        measured = run_node(
            f"import {{resolveRenderingTier, desktopPresentationForTier, resolve}} "
            f"from '{(LIB / 'companionPresence.js').as_uri()}';\n"
            "const balanced = resolveRenderingTier('BALANCED');\n"
            "const light = resolveRenderingTier('LIGHT');\n"
            "const minimal = resolveRenderingTier('MINIMAL');\n"
            "const full = resolveRenderingTier('FULL');\n"
            "const still = resolveRenderingTier('FULL', {reducedMotion: true});\n"
            "const identity = [\n"
            "  desktopPresentationForTier('FULL').identity,\n"
            "  desktopPresentationForTier('MINIMAL').identity,\n"
            "];\n"
            "const presence = resolve({renderingTier: 'BALANCED', selected: 'full-3d'});\n"
            "console.log(JSON.stringify({balanced, light, minimal, full, still, identity, presence}));\n"
        )
        self.assertEqual(measured["balanced"]["fidelity"], "lightweight-3d")
        self.assertFalse(measured["balanced"]["claimsFull3d"])
        self.assertFalse(measured["balanced"]["fullyFeatured"])
        self.assertEqual(measured["light"]["fidelity"], "static-image")
        self.assertFalse(measured["light"]["animate"])
        self.assertEqual(measured["minimal"]["fidelity"], "text-only")
        self.assertFalse(measured["minimal"]["drawCharacter"])
        self.assertTrue(measured["full"]["fullyFeatured"])
        self.assertEqual(measured["full"]["identity"], measured["minimal"]["identity"])
        self.assertEqual(measured["identity"][0], measured["identity"][1])
        self.assertEqual(measured["still"]["fidelity"], "full-3d")
        self.assertEqual(measured["still"]["motionMs"], 0)
        self.assertEqual(measured["presence"]["fidelity"], "lightweight-3d")
        self.assertNotEqual(measured["presence"]["fidelity"], "full-3d")

    def test_machine_pressure_cannot_raise_a_lower_tier(self) -> None:
        measured = run_node(
            f"import {{resolveRenderingTier}} from '{(LIB / 'companionPresence.js').as_uri()}';\n"
            "const light = resolveRenderingTier('LIGHT', {selected: 'full-3d'});\n"
            "const balanced = resolveRenderingTier('BALANCED', {machine: {frameRate: 12}});\n"
            "console.log(JSON.stringify({light, balanced}));\n"
        )
        self.assertEqual(measured["light"]["fidelity"], "static-image")
        self.assertNotEqual(measured["light"]["fidelity"], "full-3d")
        self.assertIn(measured["balanced"]["fidelity"], ("animated-2d", "static-image", "text-only", "lightweight-3d"))
        self.assertNotEqual(measured["balanced"]["fidelity"], "full-3d")


class WiringAndHonestyTests(NodeBackedTestCase):
    def test_shell_and_gtk_wire_the_new_surfaces(self) -> None:
        ui = (ROOT / "shell/services/bunny_shell/ui.py").read_text(encoding="utf-8")
        shell = (LIB / "desktopShell.js").read_text(encoding="utf-8")
        self.assertIn("build_bunny_files", ui)
        self.assertIn("parse_files_uri", ui)
        self.assertIn("route_files_action", ui)
        self.assertIn("build_updates_chrome", ui)
        self.assertIn("build_multitasking", ui)
        self.assertIn("build_terminal_chrome", ui)
        self.assertIn("buildBunnyFiles", shell)
        self.assertIn("routeFilesAction", shell)
        self.assertIn("_presentFileOpenTrust", shell)
        self.assertIn("_presentApproval", shell[shell.find("_presentFileOpenTrust"):shell.find("_presentFileOpenTrust") + 1200])
        self.assertIn("desktopPresentationForTier", shell)
        self.assertIn("snapLayout", shell)
        self.assertIn("TextCharacterRenderer", (ROOT / "shell/components/gnome-shell-extension/lib/character/renderer.js").read_text(encoding="utf-8"))
        self.assertIn("case 'none'", (ROOT / "shell/components/gnome-shell-extension/lib/character/renderer.js").read_text(encoding="utf-8"))
        nautilus = (ROOT / "shell/components/nautilus/bunny-nautilus.py").read_text(encoding="utf-8")
        self.assertIn("bunny://files/", nautilus)
        self.assertIn("no file is uploaded automatically", nautilus.casefold())

    def test_file_open_copy_is_byte_identical(self) -> None:
        measured = run_node(
            f"import {{FILE_OPEN_BUBBLE, FILE_NOT_UPLOADED, FILE_OPEN_HEADLINE, "
            f"FILE_OPEN_GRANTED, FILE_OPEN_DENIED, FILE_OPEN_FAILED, "
            f"FILE_OPEN_DRIFT, FILE_OPEN_EXPIRED}} "
            f"from '{(LIB / 'trustPrompt.js').as_uri()}';\n"
            "console.log(JSON.stringify({FILE_OPEN_BUBBLE, FILE_NOT_UPLOADED, FILE_OPEN_HEADLINE, "
            "FILE_OPEN_GRANTED, FILE_OPEN_DENIED, FILE_OPEN_FAILED, "
            "FILE_OPEN_DRIFT, FILE_OPEN_EXPIRED}));\n"
        )
        self.assertEqual(measured["FILE_OPEN_BUBBLE"], FILE_OPEN_BUBBLE)
        self.assertEqual(measured["FILE_NOT_UPLOADED"], FILE_NOT_UPLOADED)
        self.assertEqual(measured["FILE_OPEN_HEADLINE"], FILE_OPEN_HEADLINE)
        self.assertEqual(measured["FILE_OPEN_GRANTED"], FILE_OPEN_GRANTED)
        self.assertEqual(measured["FILE_OPEN_DENIED"], FILE_OPEN_DENIED)
        self.assertEqual(measured["FILE_OPEN_FAILED"], FILE_OPEN_FAILED)
        self.assertEqual(measured["FILE_OPEN_DRIFT"], FILE_OPEN_DRIFT)
        self.assertEqual(measured["FILE_OPEN_EXPIRED"], FILE_OPEN_EXPIRED)


class FileOpenGrantTests(NodeBackedTestCase):
    """P4.1: Allow once executes open. Don't allow opens nothing."""

    def test_allow_once_opens_only_the_granted_file(self) -> None:
        opened: list[tuple[list[str], str]] = []

        def opener(command: list[str], path: str) -> bool:
            opened.append((command, path))
            return True

        result = apply_file_open_after_trust(
            decision="allow",
            path="/home/ravi/docs/notes.txt",
            extra_paths=["/home/ravi/Pictures", "/home/ravi/docs"],
            opener=opener,
        )
        self.assertTrue(result["shouldOpen"])
        self.assertTrue(result["launched"])
        self.assertFalse(result["uploaded"])
        self.assertEqual(result["path"], "/home/ravi/docs/notes.txt")
        self.assertEqual(result["command"], ["gio", "open", "/home/ravi/docs/notes.txt"])
        self.assertEqual(result["paths"], ["/home/ravi/docs/notes.txt"])
        self.assertEqual(result["message"], FILE_OPEN_GRANTED)
        self.assertEqual(result["note"], FILE_NOT_UPLOADED)
        self.assertFalse(result["companionRequired"])
        self.assertEqual(opened, [(["gio", "open", "/home/ravi/docs/notes.txt"], "/home/ravi/docs/notes.txt")])
        self.assertNotIn("/home/ravi/Pictures", json.dumps(result))

    def test_dont_allow_opens_nothing_and_shows_recovery(self) -> None:
        opened: list[object] = []

        def opener(command: list[str], path: str) -> bool:
            opened.append((command, path))
            return True

        result = apply_file_open_after_trust(
            decision="deny",
            path="/home/ravi/docs/notes.txt",
            opener=opener,
        )
        self.assertFalse(result["shouldOpen"])
        self.assertFalse(result["launched"])
        self.assertFalse(result["uploaded"])
        self.assertEqual(result["path"], "")
        self.assertIsNone(result["command"])
        self.assertEqual(result["paths"], [])
        self.assertEqual(result["message"], FILE_OPEN_DENIED)
        self.assertIn("Allow once", result["message"])
        self.assertEqual(opened, [])
        defaulted = apply_file_open_after_trust(path="/tmp/a.txt", opener=opener)
        self.assertFalse(defaulted["shouldOpen"])
        self.assertEqual(defaulted["message"], FILE_OPEN_DENIED)
        always = apply_file_open_after_trust(
            decision="always", path="/tmp/a.txt", opener=opener,
        )
        self.assertFalse(always["shouldOpen"])
        session = apply_file_open_after_trust(
            decision="session", path="/tmp/a.txt", opener=opener,
        )
        self.assertFalse(session["shouldOpen"])
        for verdict in ("close", "timeout", "expired", "escape"):
            refused = apply_file_open_after_trust(
                decision=verdict, path="/tmp/a.txt", opener=opener,
            )
            self.assertFalse(refused["shouldOpen"], verdict)
            self.assertFalse(refused["launched"], verdict)
        self.assertEqual(opened, [])
        self.assertEqual(
            apply_file_open_after_trust(decision="timeout", path="/tmp/a.txt")["message"],
            FILE_OPEN_EXPIRED,
        )

    def test_placeholder_and_non_open_actions_do_not_launch(self) -> None:
        opened: list[object] = []

        def opener(command: list[str], path: str) -> bool:
            opened.append((command, path))
            return True

        fake = apply_file_open_after_trust(
            decision="allow", path="result first", opener=opener,
        )
        self.assertEqual(granted_file_path("result first"), "")
        self.assertFalse(fake["shouldOpen"])
        self.assertFalse(fake["launched"])
        self.assertEqual(opened, [])
        checkpoint = apply_file_open_after_trust(
            decision="allow",
            path="/tmp/a.txt",
            action="checkpoint",
            opener=opener,
        )
        self.assertFalse(checkpoint["shouldOpen"])
        failed = apply_file_open_after_trust(
            decision="allow", path="/tmp/a.txt", opener=lambda *_a: False,
        )
        self.assertTrue(failed["shouldOpen"])
        self.assertFalse(failed["launched"])
        self.assertEqual(failed["message"], FILE_OPEN_FAILED)
        planned = resolve_file_open_after_trust(
            decision="allow", path="file:///tmp/photo.png",
        )
        self.assertTrue(planned["shouldOpen"])
        self.assertEqual(planned["path"], "/tmp/photo.png")
        self.assertEqual(planned["command"], ["gio", "open", "/tmp/photo.png"])

    def test_javascript_grant_and_deny_match_python(self) -> None:
        js = run_node(
            f"import {{applyFileOpenAfterTrust, grantedFilePath}} "
            f"from '{(LIB / 'bunnyFiles.js').as_uri()}';\n"
            "const opened = [];\n"
            "const grant = applyFileOpenAfterTrust(\n"
            "  {decision: 'allow', path: '/home/ravi/docs/notes.txt',\n"
            "   extraPaths: ['/home/ravi/Pictures']},\n"
            "  (command, path) => { opened.push({command, path}); return true; });\n"
            "const deny = applyFileOpenAfterTrust(\n"
            "  {decision: 'deny', path: '/home/ravi/docs/notes.txt'},\n"
            "  (command, path) => { opened.push({command, path}); return true; });\n"
            "console.log(JSON.stringify({grant, deny, opened, "
            "placeholder: grantedFilePath('result first')}));\n"
        )
        py_grant = apply_file_open_after_trust(
            decision="allow",
            path="/home/ravi/docs/notes.txt",
            extra_paths=["/home/ravi/Pictures"],
            opener=lambda *_a: True,
        )
        py_deny = apply_file_open_after_trust(
            decision="deny",
            path="/home/ravi/docs/notes.txt",
            opener=lambda *_a: True,
        )
        self.assertEqual(js["grant"]["command"], py_grant["command"])
        self.assertEqual(js["grant"]["message"], py_grant["message"])
        self.assertEqual(js["grant"]["note"], FILE_NOT_UPLOADED)
        self.assertTrue(js["grant"]["launched"])
        self.assertFalse(js["deny"]["launched"])
        self.assertEqual(js["deny"]["message"], py_deny["message"])
        self.assertEqual(js["opened"], [{
            "command": ["gio", "open", "/home/ravi/docs/notes.txt"],
            "path": "/home/ravi/docs/notes.txt",
        }])
        self.assertEqual(js["placeholder"], "")

    def test_shell_executes_open_after_allow_once(self) -> None:
        shell = (LIB / "desktopShell.js").read_text(encoding="utf-8")
        launcher = (LIB / "services/launcher.js").read_text(encoding="utf-8")
        start = shell.find("_presentFileOpenTrust")
        self.assertGreaterEqual(start, 0)
        region = shell[start:start + 2200]
        self.assertIn("applyFileOpenAfterTrust", region)
        self.assertIn("openGrantedFile", region)
        self.assertNotIn("Bunny does not open the file itself", region)
        self.assertIn("FILE_OPEN_DENIED", region)
        self.assertIn("openGrantedFile", launcher)
        self.assertIn("gio", launcher)
        self.assertNotIn("Always allow everything", region)
        self.assertIn("approvedPath", region)
        self.assertIn("approvedApplication", region)

    def test_path_or_app_drift_after_allow_is_fail_closed(self) -> None:
        opened: list[object] = []

        def opener(command: list[str], path: str, application: str = "") -> bool:
            opened.append((command, path, application))
            return True

        path_drift = apply_file_open_after_trust(
            decision="allow",
            path="/home/ravi/Pictures/other.jpg",
            approved_path="/home/ravi/docs/notes.txt",
            application="Text Editor",
            approved_application="Text Editor",
            opener=opener,
        )
        self.assertFalse(path_drift["shouldOpen"])
        self.assertFalse(path_drift["launched"])
        self.assertEqual(path_drift["message"], FILE_OPEN_DRIFT)
        self.assertFalse(path_drift["uploaded"])
        app_drift = apply_file_open_after_trust(
            decision="allow",
            path="/home/ravi/docs/notes.txt",
            approved_path="/home/ravi/docs/notes.txt",
            application="GIMP",
            approved_application="Text Editor",
            opener=opener,
        )
        self.assertFalse(app_drift["shouldOpen"])
        self.assertEqual(app_drift["message"], FILE_OPEN_DRIFT)
        scoped = apply_file_open_after_trust(
            decision="allow",
            path="/home/ravi/docs/notes.txt",
            approved_path="/home/ravi/docs/notes.txt",
            application="Text Editor",
            approved_application="Text Editor",
            opener=opener,
        )
        self.assertTrue(scoped["launched"])
        self.assertEqual(scoped["application"], "Text Editor")
        self.assertEqual(opened, [(
            ["gio", "open", "/home/ravi/docs/notes.txt"],
            "/home/ravi/docs/notes.txt",
            "Text Editor",
        )])
        js = run_node(
            f"import {{applyFileOpenAfterTrust}} from '{(LIB / 'bunnyFiles.js').as_uri()}';\n"
            "const opened = [];\n"
            "const drift = applyFileOpenAfterTrust(\n"
            "  {decision: 'allow', path: '/tmp/b.txt', approvedPath: '/tmp/a.txt',\n"
            "   application: 'GIMP', approvedApplication: 'Text Editor'},\n"
            "  (command, path, application) => { opened.push({command, path, application}); return true; });\n"
            "const timeout = applyFileOpenAfterTrust(\n"
            "  {decision: 'timeout', path: '/tmp/a.txt', approvedPath: '/tmp/a.txt'},\n"
            "  () => true);\n"
            "console.log(JSON.stringify({drift, timeout, opened}));\n"
        )
        self.assertFalse(js["drift"]["launched"])
        self.assertEqual(js["drift"]["message"], FILE_OPEN_DRIFT)
        self.assertEqual(js["timeout"]["message"], FILE_OPEN_EXPIRED)
        self.assertEqual(js["opened"], [])


class FrozenEvidenceTests(unittest.TestCase):
    def test_phase7_frozen_evidence_is_not_retargeted(self) -> None:
        for relative in FROZEN:
            current = (ROOT / relative).read_bytes()
            committed = subprocess.check_output(
                ["git", "show", f"origin/main:{relative}"], cwd=ROOT)
            self.assertEqual(current, committed, f"{relative} must stay pinned to main")


if __name__ == "__main__":
    unittest.main()
