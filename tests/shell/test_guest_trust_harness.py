# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The guest Trust journey harness: AT-SPI press, no protocol shortcut, honest NOT_RUN."""

from __future__ import annotations

import ast
from pathlib import Path
import subprocess
import unittest

from tests.support import ROOT
from companion.trust_surface import ALLOW_ACCESSIBLE_NAME, DENY_ACCESSIBLE_NAME

SCRIPTS = ROOT / "build/scripts"
DRIVER = SCRIPTS / "desktop-drive.py"
STORY = SCRIPTS / "vm-desktop-story.sh"
GUEST = SCRIPTS / "vm-guest-trust.sh"
LIB = SCRIPTS / "vm-lib.sh"
TRUST_JS = ROOT / "shell/components/gnome-shell-extension/lib/components/trust.js"
DEMO = ROOT / "demos/09-guest-trust/run.py"


class GuestTrustHarnessTests(unittest.TestCase):
    def test_accessible_names_are_the_guest_harness_names(self) -> None:
        self.assertEqual(ALLOW_ACCESSIBLE_NAME, "Allow this Bunny action")
        self.assertEqual(DENY_ACCESSIBLE_NAME, "Deny this Bunny action")
        driver = DRIVER.read_text(encoding="utf-8")
        self.assertIn(ALLOW_ACCESSIBLE_NAME, driver)
        self.assertIn(DENY_ACCESSIBLE_NAME, driver)
        self.assertIn(ALLOW_ACCESSIBLE_NAME, TRUST_JS.read_text(encoding="utf-8"))
        self.assertIn(DENY_ACCESSIBLE_NAME, TRUST_JS.read_text(encoding="utf-8"))

    def test_the_driver_never_calls_resolve_approval(self) -> None:
        """AT-SPI extents + tablet, not a protocol shortcut."""
        tree = ast.parse(DRIVER.read_text(encoding="utf-8"))
        calls: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr == "resolve_approval":
                    calls.append("resolve_approval")
                if isinstance(func, ast.Attribute) and func.attr == "call":
                    for arg in node.args:
                        if isinstance(arg, ast.Constant) and arg.value == "resolve_approval":
                            calls.append("call(resolve_approval)")
        self.assertEqual(calls, [], "desktop-drive must not resolve the approval over the protocol")

    def test_there_is_no_always_allow_everything_control(self) -> None:
        source = TRUST_JS.read_text(encoding="utf-8")
        self.assertNotIn("Always allow everything", source)
        self.assertNotIn("alwaysAllowEverything", source)
        demo = DEMO.read_text(encoding="utf-8")
        self.assertIn("Always allow everything", demo)
        self.assertIn("FORBIDDEN_LABELS", demo)

    def test_the_story_accepts_a_journey_flag(self) -> None:
        text = STORY.read_text(encoding="utf-8")
        self.assertIn("--journey", text)
        self.assertIn("granted|denied|failing", text)
        self.assertIn("--journey-only", text)
        self.assertIn("attaching the driver as soon as QMP exists", text)

    def test_a_requested_journey_fails_the_story_when_incomplete(self) -> None:
        text = STORY.read_text(encoding="utf-8")
        self.assertIn('exit 7', text)
        self.assertIn("did not complete", text)

    def test_ubuntu_ovmf_4m_is_a_firmware_candidate(self) -> None:
        text = LIB.read_text(encoding="utf-8")
        self.assertIn("/usr/share/OVMF/OVMF_CODE_4M.fd", text)
        self.assertIn("/usr/share/qemu/OVMF.fd", text)

    def test_the_driver_photographs_character_state_changes(self) -> None:
        text = DRIVER.read_text(encoding="utf-8")
        self.assertIn("journey-state-", text)
        self.assertIn("journey-04-trust-prompt", text)
        self.assertIn("journey-03b-asking", text)

    def test_an_unpressed_prompt_is_an_incomplete_journey(self) -> None:
        text = DRIVER.read_text(encoding="utf-8")
        self.assertIn('or not journey.get("pressed")', text)
        self.assertIn('outcome["pressed"] = wanted', text)

    def test_the_one_command_wrapper_runs_granted_then_denied(self) -> None:
        text = GUEST.read_text(encoding="utf-8")
        self.assertIn("for journey in granted denied", text)
        self.assertIn("--journey", text)
        self.assertIn("never calls resolve_approval", text)

    def test_the_demo_will_not_mark_a_missing_guest_as_pass(self) -> None:
        text = DEMO.read_text(encoding="utf-8")
        self.assertIn('"status": "NOT_RUN"', text)
        self.assertIn("NO-GO", text)
        self.assertIn("resolve_approval", text)
        self.assertNotIn('guestBoot": "PASS"', text)
        self.assertIn("guestPassed", text)
        self.assertIn("probePassed", text)
        self.assertIn('passed = guest_passed', text)

    def test_top_level_passed_is_guest_success_not_a_probe(self) -> None:
        """NOT_RUN must not set report.passed unless PROBE_OK is explicit."""
        source = DEMO.read_text(encoding="utf-8")
        self.assertIn("BUNNY_GUEST_TRUST_PROBE_OK", source)
        self.assertIn("passed = guest_passed", source)
        self.assertIn('"guestPassed": guest_passed', source)
        self.assertIn('"probePassed": probe_passed', source)

    def test_a_guest_boot_requires_writable_kvm(self) -> None:
        """`/dev/kvm` existing is not permission to use it.

        The probe used to set canBootGuest from the device node alone, so a
        host whose kvm group the operator is not in would attempt QEMU and
        FAIL instead of recording BLOCKED.
        """
        text = DEMO.read_text(encoding="utf-8")
        self.assertIn("kvm and kvm_rw and qemu", text)
        self.assertIn("writable /dev/kvm", text)
        self.assertIn('host.get("kvmWritable")', text)

    def test_vm_desktop_story_refuses_without_a_disk(self) -> None:
        result = subprocess.run(
            ["bash", str(STORY), "--journey", "granted", "harness-no-disk"],
            cwd=ROOT, capture_output=True, text=True, timeout=30, check=False,
        )
        self.assertEqual(2, result.returncode)
        self.assertIn("no qcow2", result.stderr)

    def test_unknown_journey_is_refused(self) -> None:
        result = subprocess.run(
            ["bash", str(STORY), "--journey", "always-allow", "nope"],
            cwd=ROOT, capture_output=True, text=True, timeout=15, check=False,
        )
        self.assertEqual(2, result.returncode)
        self.assertIn("unknown journey", result.stderr)

    def test_firmware_discovery_finds_ubuntu_ovmf(self) -> None:
        result = subprocess.run(
            ["bash", "-c", "source build/scripts/vm-lib.sh && bunny_firmware"],
            cwd=ROOT, capture_output=True, text=True, timeout=10, check=False,
        )
        if result.returncode != 0:
            self.skipTest("no OVMF firmware on this host")
        self.assertTrue(Path(result.stdout.strip()).is_file(), result.stdout)


class GuestTrustDemoHonestyTests(unittest.TestCase):
    def test_summarise_journey_requires_a_photographed_press(self) -> None:
        import importlib.util

        loader = importlib.util.spec_from_file_location("guest_trust_demo", DEMO)
        module = importlib.util.module_from_spec(loader)
        assert loader.loader is not None
        loader.loader.exec_module(module)
        outcome = module.summarise_journey(Path("/nonexistent/guest-trust"), "granted")
        self.assertEqual("NOT_RUN", outcome["status"])
        self.assertNotEqual("PASS", outcome["status"])


if __name__ == "__main__":
    unittest.main()
