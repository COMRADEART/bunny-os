# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The prior phase's record is immutable, and this is what makes it so.

A closure that supersedes some of an earlier phase's claims has an obvious and
quiet failure mode: edit the earlier record so it never made the claim. The
result reads as a phase that got it right first time, and the audit trail for
the defect — which is the most valuable thing either phase produced — is gone.

So every artefact of the voice-runtime phase is pinned by digest in
``qualification/companion-voice-closure/preserved-evidence.json`` and checked
here. Superseding results go *beside* the pinned ones. If a pinned file has to
change, this test is what forces that to be a deliberate act with a reason
attached rather than a side effect of writing up the new work.

The report is pinned as a prefix rather than in whole, because the closure
appends to it: everything up to and including the voice-runtime phase's last
section must be byte-identical, and the new sections are appended after it.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
RECORD = ROOT / "qualification/companion-voice-closure/preserved-evidence.json"

#: The report is the one preserved artefact the closure is allowed to extend.
#: Its pinned digest covers the first ``bytes`` of the file and nothing after.
_APPENDABLE = {"COMPANION_VOICE_RUNTIME_REPORT.md"}


class PreservedEvidence(unittest.TestCase):
    def setUp(self) -> None:
        self.record = json.loads(RECORD.read_text(encoding="utf-8"))

    def test_the_pinned_evidence_files_are_byte_identical(self) -> None:
        for relative, expected in sorted(self.record["preserved"].items()):
            with self.subTest(file=relative):
                path = ROOT / relative
                self.assertTrue(path.is_file(), f"{relative} has been removed")
                content = path.read_bytes()
                if relative in _APPENDABLE:
                    self.assertGreaterEqual(
                        len(content), expected["bytes"],
                        f"{relative} lost bytes; the closure may only append to it",
                    )
                    content = content[: expected["bytes"]]
                else:
                    self.assertEqual(
                        len(content), expected["bytes"],
                        f"{relative} changed length; prior evidence is immutable",
                    )
                self.assertEqual(
                    hashlib.sha256(content).hexdigest(), expected["sha256"],
                    f"{relative} no longer matches the digest recorded before this closure began",
                )

    def test_the_prior_gate_manifest_still_records_its_three_gates(self) -> None:
        """100/100, 50/50 and 20/20, on one commit, still saying so."""
        manifest = json.loads(
            (ROOT / "qualification/companion-voice/evidence/manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["gateCommit"], self.record["priorGateCommit"])
        expected = {
            "gate1-voice-lifecycle-100": 100,
            "gate2-companion-suite-50": 50,
            "gate3-voice-slice-20": 20,
        }
        for name, runs in expected.items():
            with self.subTest(gate=name):
                gate = manifest["gates"][name]
                self.assertTrue(gate["gateMet"])
                self.assertEqual(gate["passed"], runs)
                self.assertEqual(gate["failed"], 0)
                self.assertEqual(gate["longestConsecutivePass"], runs)
                self.assertTrue(gate["singleCommit"])
                self.assertEqual(gate["commitsObserved"], [self.record["priorGateCommit"]])

    def test_the_prior_not_run_items_are_still_recorded_as_not_run(self) -> None:
        """A NOT_RUN item may be superseded by a run. It may not be edited into one."""
        manifest = json.loads(
            (ROOT / "qualification/companion-voice/evidence/manifest.json").read_text(encoding="utf-8")
        )
        absent = {item["file"] for item in manifest["files"] if not item["present"]}
        self.assertEqual(absent, {"slice.json", "suite.json", "env.json"})
        self.assertFalse(manifest["host"]["physicalSpeakerValidated"])
        self.assertGreaterEqual(len(self.record["notRunAtBase"]), 5)

    def test_both_measured_defects_are_still_described_with_their_guards(self) -> None:
        defects = {item["id"]: item for item in self.record["preservedDefects"]}
        self.assertEqual(set(defects), {"multi-call-executable", "stranded-voice-worker"})
        for identifier, defect in defects.items():
            with self.subTest(defect=identifier):
                self.assertTrue(defect["summary"])
                self.assertTrue(defect["guardedBy"])
                for guard in defect["guardedBy"]:
                    module = guard.split(":", 1)[0].strip()
                    self.assertTrue(
                        (ROOT / module).is_file(),
                        f"{identifier} names {module} as its guard and that file is gone",
                    )

    def test_the_report_still_carries_the_two_defect_sections(self) -> None:
        report = (ROOT / "COMPANION_VOICE_RUNTIME_REPORT.md").read_text(encoding="utf-8")
        self.assertIn("## 18a. The defect the gates could not see", report)
        self.assertIn("## 18b. The leak the tests could not see", report)
        self.assertIn("## 25. NOT_RUN items", report)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
