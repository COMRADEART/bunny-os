# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The hardware matrix's rules, enforced before any machine exists.

The §8 distinctions are structural: a PASS without evidence is not a PASS, a
machine without its full identity record cannot carry rows, NOT_SUPPORTED
must be grounded in the identity record, and 3D-native and 3D-fallback are
different rows. The validator is written now — with its failure branches
exercised on constructed machines — so the first real machine is judged by
rules that predate it.
"""

from __future__ import annotations

import json
from pathlib import Path
import unittest

_ROOT = Path(__file__).resolve().parents[2]
_MATRIX = _ROOT / "qualification/phase8/hardware-matrix.json"


def validate_machine(matrix: dict, machine: dict) -> list[str]:
    """Return every rule violation for one machine record."""
    problems: list[str] = []
    hardware_id = machine.get("hardwareId") or "<missing hardwareId>"
    if not str(machine.get("hardwareId", "")).startswith("HW-"):
        problems.append(f"{hardware_id}: hardwareId must be HW-NNN")
    identity = machine.get("identity") or {}
    for field in matrix["identityFields"]:
        if field not in identity:
            problems.append(f"{hardware_id}: identity field missing: {field}")
    if not machine.get("mediaDigestOnWritingHost") or not machine.get("mediaDigestFromWrittenMedium"):
        problems.append(f"{hardware_id}: media digest not verified on both ends")
    rows = machine.get("rows") or {}
    for dimension in matrix["dimensions"]:
        if dimension not in rows:
            problems.append(f"{hardware_id}: dimension missing: {dimension}")
    for dimension, row in rows.items():
        if dimension not in matrix["dimensions"]:
            problems.append(f"{hardware_id}: unknown dimension: {dimension}")
            continue
        status = row.get("status")
        if status not in matrix["statusVocabulary"]:
            problems.append(f"{hardware_id}/{dimension}: illegal status {status!r}")
        if status == "PASS" and not row.get("evidence"):
            problems.append(f"{hardware_id}/{dimension}: PASS without evidence")
        if status == "NOT_SUPPORTED" and not row.get("groundedIn"):
            problems.append(
                f"{hardware_id}/{dimension}: NOT_SUPPORTED must cite the identity "
                "field that makes it a statement about the machine"
            )
    return problems


def _machine(matrix: dict, **overrides) -> dict:
    base = {
        "hardwareId": "HW-001",
        "identity": {field: "recorded" for field in matrix["identityFields"]},
        "mediaDigestOnWritingHost": "823d50ca",
        "mediaDigestFromWrittenMedium": "823d50ca",
        "rows": {
            d: {"status": "NOT_RUN"} for d in matrix["dimensions"]
        },
    }
    base.update(overrides)
    return base


class HardwareMatrix(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.matrix = json.loads(_MATRIX.read_text(encoding="utf-8"))

    def test_the_committed_matrix_is_valid_and_empty(self) -> None:
        self.assertEqual(self.matrix["machines"], [])
        self.assertEqual(self.matrix["artifact"]["identifier"], "e906a48793d7")
        for machine in self.matrix["machines"]:
            self.assertEqual(validate_machine(self.matrix, machine), [])

    def test_native_and_fallback_3d_are_separate_dimensions(self) -> None:
        self.assertIn("companion-3d-native", self.matrix["dimensions"])
        self.assertIn("companion-3d-fallback", self.matrix["dimensions"])

    def test_a_fresh_machine_with_all_not_run_is_valid(self) -> None:
        self.assertEqual(validate_machine(self.matrix, _machine(self.matrix)), [])

    def test_a_pass_without_evidence_is_refused(self) -> None:
        machine = _machine(self.matrix)
        machine["rows"]["voice-microphone"] = {"status": "PASS"}
        problems = validate_machine(self.matrix, machine)
        self.assertIn("HW-001/voice-microphone: PASS without evidence", problems)

    def test_not_supported_must_be_grounded_in_the_identity_record(self) -> None:
        machine = _machine(self.matrix)
        machine["rows"]["voice-microphone"] = {"status": "NOT_SUPPORTED"}
        problems = validate_machine(self.matrix, machine)
        self.assertTrue(any("NOT_SUPPORTED must cite" in p for p in problems))

    def test_an_incomplete_identity_record_is_refused(self) -> None:
        machine = _machine(self.matrix)
        del machine["identity"]["microphone"]
        problems = validate_machine(self.matrix, machine)
        self.assertIn("HW-001: identity field missing: microphone", problems)

    def test_unverified_media_is_refused(self) -> None:
        machine = _machine(self.matrix, mediaDigestFromWrittenMedium="")
        problems = validate_machine(self.matrix, machine)
        self.assertTrue(any("media digest" in p for p in problems))

    def test_a_missing_dimension_is_refused_rather_than_implied(self) -> None:
        machine = _machine(self.matrix)
        del machine["rows"]["companion-3d-fallback"]
        problems = validate_machine(self.matrix, machine)
        self.assertIn("HW-001: dimension missing: companion-3d-fallback", problems)


if __name__ == "__main__":
    unittest.main()
