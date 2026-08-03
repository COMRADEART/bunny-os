# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the Fedora host readiness gate.

The gate decides whether a machine may produce qualification evidence at all, so
the failure that matters is not a wrong refusal but a wrong acceptance. Most of
these tests therefore start from a host that would pass, break one thing, and
assert that the gate stops.

The ideal-host fixture is a fiction written to satisfy every condition. That is
the point: no such machine exists yet, and the gate has to be testable before one
does, or it gets written against whatever hardware happened to be nearby.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import importlib.util

spec = importlib.util.spec_from_file_location("gate", SCRIPTS / "host-readiness-gate.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def ideal_host() -> dict:
    """A machine that satisfies every mandatory condition."""
    return {
        "schemaVersion": 1,
        "environmentId": "FQH-20260803-01",
        "role": "host",
        "collectedAt": "2026-08-03T12:00:00+00:00",
        "operator": "test",
        "host": {
            "hostname": "qual-01",
            "manufacturer": "Example",
            "model": "Workstation",
            "serialHash": "a" * 64,
            "bareMetal": True,
            "hypervisorDetected": None,
        },
        "os": {"name": "Fedora Linux", "versionId": "44", "kernel": "6.18.0",
               "isoDigest": None, "installedOn": None},
        "boot": {"mode": "uefi", "secureBoot": "enabled", "platformSize": 64},
        "cpu": {"model": "Example CPU", "logicalCores": 16, "virtualisationFlag": "vmx"},
        "memory": {"totalBytes": 32 * 1024**3},
        "storage": {"availableBytesForEvidence": 800 * 1024**3, "devices": []},
        "graphics": {
            "drmCardNodes": ["/dev/dri/card1"],
            "drmRenderNodes": ["/dev/dri/renderD128"],
            "pciIdentity": "00:02.0 VGA compatible controller",
            "kernelDriver": "i915",
            "mesaVersion": "4.6 Mesa 26.1",
            "openglRenderer": "Mesa Intel(R) Graphics (ADL GT2)",
            "vulkanDevice": "Intel(R) Graphics (ADL GT2)",
            "softwareRasteriser": False,
        },
        "displays": {
            "connectedOutputs": 2,
            "outputs": [
                {"connector": "card1-DP-1", "status": "connected", "preferredMode": "3840x2160"},
                {"connector": "card1-HDMI-A-1", "status": "connected", "preferredMode": "1920x1080"},
            ],
            "mixedResolution": True,
        },
        "tpm": {"present": True, "version": "2.0", "manufacturer": "IFX", "physical": True},
        "virtualisation": {"kvmAvailable": True, "virtHostValidate": "PASS",
                           "qemuVersion": "9.0", "libvirtVersion": "10.0"},
        "selinux": {"mode": "Enforcing"},
        "session": {"type": "wayland", "desktop": "GNOME", "pipewire": True,
                    "wireplumber": True, "portal": True,
                    "portalBackends": ["xdg-desktop-portal-gnome"]},
        "audio": {"devices": ["alsa_output.pci-0000_00_1f.3"]},
        "accessibility": {"orcaInstalled": True, "orcaVersion": "orca 47",
                          "speechDispatcherInstalled": True,
                          "speechDispatcherVersion": "spd-say 0.12", "atspiPresent": True},
        "inputMethod": {"available": ["ibus"], "ibusVersion": "IBus 1.5",
                        "fcitx5Version": None, "engines": ["anthy", "libpinyin", "hangul"]},
        "crypto": {"cryptsetupVersion": "cryptsetup 2.7", "luks2Supported": True,
                   "argon2idAvailable": True},
        "tooling": {"git": "git 2.47"},
        "git": {"version": "git 2.47", "autocrlf": "false", "byteRoundtripTestsPass": True},
        "clock": {"synchronised": True, "timezone": "UTC", "systemTime": "2026-08-03T12:00:00+00:00"},
    }


def evaluate(env: dict) -> dict:
    return gate.evaluate(env, now="2026-08-03T12:00:00+00:00")


def condition(result: dict, identifier: str) -> dict:
    return next(c for c in result["conditions"] if c["id"] == identifier)


class IdealHostTests(unittest.TestCase):
    def test_the_ideal_host_is_ready(self):
        result = evaluate(ideal_host())
        unsatisfied = [c["id"] for c in result["conditions"] if not c["satisfied"]]
        self.assertEqual(unsatisfied, [], "the fixture should satisfy every condition")
        self.assertEqual(result["result"], "READY")

    def test_every_condition_is_mandatory(self):
        """There is no warning tier, by construction."""
        result = evaluate(ideal_host())
        self.assertTrue(all(c["mandatory"] for c in result["conditions"]))


class RefusalTests(unittest.TestCase):
    """Break one thing at a time; the gate must stop."""

    def assert_blocked_by(self, mutate, identifier: str):
        env = ideal_host()
        mutate(env)
        result = evaluate(env)
        self.assertEqual(result["result"], "BLOCKED")
        failed = condition(result, identifier)
        self.assertFalse(failed["satisfied"], f"{identifier} should have refused")
        self.assertTrue(failed["refusal"], f"{identifier} must say why")

    def test_a_virtualised_host_is_refused(self):
        def mutate(e):
            e["host"]["bareMetal"] = False
            e["host"]["hypervisorDetected"] = "wsl"
        self.assert_blocked_by(mutate, "bare-metal")

    def test_llvmpipe_is_refused(self):
        def mutate(e):
            e["graphics"]["openglRenderer"] = "llvmpipe (LLVM 22.1.8, 256 bits)"
            e["graphics"]["softwareRasteriser"] = True
        self.assert_blocked_by(mutate, "hardware-renderer")

    def test_llvmpipe_is_refused_even_if_the_flag_says_otherwise(self):
        """The collector's own classification is not taken on trust."""
        def mutate(e):
            e["graphics"]["openglRenderer"] = "llvmpipe (LLVM 22.1.8)"
            e["graphics"]["softwareRasteriser"] = False
        self.assert_blocked_by(mutate, "hardware-renderer")

    def test_a_translated_vulkan_device_is_refused(self):
        """Regression: WSL advertises a real-sounding GPU over Direct3D12.

        The name contains no software-rasteriser marker, so a substring check
        against llvmpipe alone accepted it while OpenGL was in fact software.
        """
        def mutate(e):
            e["graphics"]["vulkanDevice"] = "Microsoft Direct3D12 (NVIDIA GeForce RTX 4050 Laptop GPU)"
        self.assert_blocked_by(mutate, "vulkan-device")

    def test_a_vulkan_device_without_a_drm_node_is_refused(self):
        def mutate(e):
            e["graphics"]["drmCardNodes"] = []
        self.assert_blocked_by(mutate, "vulkan-device")

    def test_missing_dev_dri_is_refused(self):
        def mutate(e):
            e["graphics"]["drmCardNodes"] = []
            e["graphics"]["drmRenderNodes"] = []
        self.assert_blocked_by(mutate, "drm-card-node")

    def test_one_connected_output_is_refused(self):
        def mutate(e):
            e["displays"]["connectedOutputs"] = 1
        self.assert_blocked_by(mutate, "two-connected-outputs")

    def test_an_emulated_tpm_is_refused(self):
        def mutate(e):
            e["tpm"]["physical"] = False
        self.assert_blocked_by(mutate, "physical-tpm-2")

    def test_a_tpm_1_2_is_refused(self):
        def mutate(e):
            e["tpm"]["version"] = "1.2"
        self.assert_blocked_by(mutate, "physical-tpm-2")

    def test_unobserved_secure_boot_is_refused(self):
        def mutate(e):
            e["boot"]["secureBoot"] = "unknown"
        self.assert_blocked_by(mutate, "secure-boot-observed")

    def test_disabled_secure_boot_is_accepted_because_it_was_observed(self):
        env = ideal_host()
        env["boot"]["secureBoot"] = "disabled"
        self.assertTrue(condition(evaluate(env), "secure-boot-observed")["satisfied"])

    def test_permissive_selinux_is_refused(self):
        def mutate(e):
            e["selinux"]["mode"] = "Permissive"
        self.assert_blocked_by(mutate, "selinux-enforcing")

    def test_an_x11_session_is_refused(self):
        def mutate(e):
            e["session"]["type"] = "x11"
        self.assert_blocked_by(mutate, "wayland-session")

    def test_missing_kvm_is_refused(self):
        def mutate(e):
            e["virtualisation"]["kvmAvailable"] = False
        self.assert_blocked_by(mutate, "kvm-available")

    def test_inactive_portal_is_refused(self):
        def mutate(e):
            e["session"]["portal"] = False
        self.assert_blocked_by(mutate, "portal-active")

    def test_missing_orca_is_refused(self):
        def mutate(e):
            e["accessibility"]["orcaInstalled"] = False
        self.assert_blocked_by(mutate, "orca-installed")

    def test_missing_input_method_is_refused(self):
        def mutate(e):
            e["inputMethod"]["available"] = []
        self.assert_blocked_by(mutate, "input-method-available")

    def test_a_failing_byte_roundtrip_guard_is_refused(self):
        def mutate(e):
            e["git"]["byteRoundtripTestsPass"] = False
        self.assert_blocked_by(mutate, "git-byte-roundtrip")

    def test_an_unrun_byte_roundtrip_guard_is_refused(self):
        """null means not run, and not run is not a pass."""
        def mutate(e):
            e["git"]["byteRoundtripTestsPass"] = None
        self.assert_blocked_by(mutate, "git-byte-roundtrip")

    def test_a_non_host_role_is_refused(self):
        def mutate(e):
            e["role"] = "vm-qualification"
        self.assert_blocked_by(mutate, "role-is-host")


class MalformedReportTests(unittest.TestCase):
    """An environment report that cannot answer has not answered."""

    def test_a_missing_section_blocks_rather_than_crashes(self):
        env = ideal_host()
        del env["graphics"]
        result = evaluate(env)
        self.assertEqual(result["result"], "BLOCKED")
        self.assertIn("incomplete", condition(result, "drm-card-node")["refusal"])

    def test_a_missing_field_blocks_rather_than_passes(self):
        env = ideal_host()
        del env["tpm"]["physical"]
        result = evaluate(env)
        self.assertFalse(condition(result, "physical-tpm-2")["satisfied"])


class ExitCodeTests(unittest.TestCase):
    """A blocked host must exit non-zero, or a caller can ignore the refusal."""

    def _run(self, env: dict, tmp: Path) -> subprocess.CompletedProcess:
        path = tmp / "environment.json"
        path.write_text(json.dumps(env), encoding="utf-8")
        return subprocess.run(
            [sys.executable, str(SCRIPTS / "host-readiness-gate.py"), "--environment", str(path)],
            capture_output=True, text=True,
        )

    def test_a_ready_host_exits_zero(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            proc = self._run(ideal_host(), Path(tmp))
            self.assertEqual(proc.returncode, 0, proc.stdout)
            self.assertIn("READY", proc.stdout)

    def test_a_blocked_host_exits_two(self):
        import tempfile
        env = ideal_host()
        env["graphics"]["softwareRasteriser"] = True
        with tempfile.TemporaryDirectory() as tmp:
            proc = self._run(env, Path(tmp))
            self.assertEqual(proc.returncode, 2, proc.stdout)
            self.assertIn("BLOCKED", proc.stdout)

    def test_a_missing_environment_file_exits_two(self):
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / "host-readiness-gate.py"),
             "--environment", "does-not-exist.json"],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 2)


class SchemaTests(unittest.TestCase):
    def test_the_result_matches_the_readiness_schema_shape(self):
        schema = json.loads((HERE.parent / "host-readiness.schema.json").read_text(encoding="utf-8"))
        result = evaluate(ideal_host())
        for field in schema["required"]:
            self.assertIn(field, result)
        self.assertIn(result["result"], schema["properties"]["result"]["enum"])


if __name__ == "__main__":
    unittest.main()
