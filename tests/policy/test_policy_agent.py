# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Fail-closed policy agent: a real ExecStart, no silent apply."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests.support import ROOT

AGENT = ROOT / "scripts/bunny-policy-agent.py"


class PolicyAgentFailClosedTests(unittest.TestCase):
    def _run(self, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        merged = os.environ.copy()
        merged.update(env)
        return subprocess.run(
            [sys.executable, str(AGENT)],
            cwd=ROOT, capture_output=True, text=True, check=False, env=merged,
        )

    def test_refuses_when_enrolment_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "enrolment.json"
            result = self._run({"BUNNY_POLICY_ENROLMENT": str(missing)})
        self.assertEqual(2, result.returncode)
        self.assertIn("no enrolment record", result.stderr)

    def test_enrolment_without_a_signature_still_applies_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            enrolment = Path(tmp) / "enrolment.json"
            managed = Path(tmp) / "managed-settings.json"
            staged = Path(tmp) / "staged-policies.json"
            enrolment.write_text('{"schemaVersion": 1}\n', encoding="utf-8")
            result = self._run({
                "BUNNY_POLICY_ENROLMENT": str(enrolment),
                "BUNNY_POLICY_MANAGED": str(managed),
                "BUNNY_POLICY_STAGED": str(staged),
            })
            self.assertEqual(2, result.returncode)
            self.assertIn("no signed policy bundle", result.stderr)
            self.assertFalse(managed.exists())
            self.assertFalse(staged.exists())
            self.assertEqual('{"schemaVersion": 1}\n', enrolment.read_text(encoding="utf-8"))

    def test_the_unit_and_installer_name_the_same_program(self) -> None:
        unit = (ROOT / "systemd/bunny-policy-agent.service").read_text(encoding="utf-8")
        self.assertIn("ExecStart=/usr/libexec/bunny-policy-agent", unit)
        routes = (ROOT / "build/scripts/install_routes.py").read_text(encoding="utf-8")
        self.assertIn('"bunny-policy-agent"', routes)
        ci = (ROOT / "build/scripts/ci-verify-units.sh").read_text(encoding="utf-8")
        self.assertIn("bunny-policy-agent", ci)
        gaps = json.loads(
            (ROOT / "operations/data/unit-program-gaps.json").read_text(encoding="utf-8")
        )
        recorded = {item["unit"] for item in gaps["gaps"]}
        self.assertNotIn("bunny-policy-agent.service", recorded)

    def test_sysusers_creates_the_service_account(self) -> None:
        text = (ROOT / "config/sysusers/bunny-policy.conf").read_text(encoding="utf-8")
        self.assertIn("u bunny-policy 471:471", text)
        self.assertIn("/usr/sbin/nologin", text)
        routes = (ROOT / "build/scripts/install_routes.py").read_text(encoding="utf-8")
        self.assertIn("/usr/lib/sysusers.d/bunny-policy.conf", routes)


if __name__ == "__main__":
    unittest.main()
