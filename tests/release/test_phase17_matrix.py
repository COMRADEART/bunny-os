# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""One discovered regression per executable Phase 17 matrix scenario."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


_ROOT = Path(__file__).resolve().parents[2]
_OPS = _ROOT / "qualification" / "phase17" / "tools" / "external_floor_ops.py"


def _load():
    spec = importlib.util.spec_from_file_location("phase17_matrix_under_test", _OPS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ops = _load()
_MATRIX = ops.load_json(ops.MATRIX_PATH)


class MatrixScenarioRegressions(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.real_before = {path: path.read_bytes()
                           for path in ops.REAL_IMMUTABLE_INPUTS if path.is_file()}
        cls.derived = {row["id"]: row for row in ops.run_scenarios()["scenarios"]}

    @classmethod
    def tearDownClass(cls) -> None:
        for path, raw in cls.real_before.items():
            if path.read_bytes() != raw:
                raise AssertionError("matrix scenario mutated %s" % path)


def _scenario_test(scenario: dict):
    def test(self):
        observed = self.derived[scenario["id"]]
        self.assertEqual(observed, scenario)
        self.assertEqual(observed["observedOutcome"], observed["expectedOutcome"])
        self.assertIn("realLedgerSha256", observed["inputHashes"])
    return test


for _row in _MATRIX["scenarios"]:
    _name = "test_%s" % _row["id"].lower().replace("-", "_")
    setattr(MatrixScenarioRegressions, _name, _scenario_test(_row))


class MatrixShape(unittest.TestCase):
    def test_scenario_count_is_substantive_and_bounded(self) -> None:
        self.assertEqual(_MATRIX["scenarioCount"], len(_MATRIX["scenarios"]))
        self.assertGreaterEqual(_MATRIX["scenarioCount"], 50)
        self.assertLessEqual(_MATRIX["scenarioCount"], 70)

    def test_real_universe_control_is_present(self) -> None:
        self.assertIn("REAL_UNIVERSE_READ_ONLY",
                      {row["id"] for row in _MATRIX["scenarios"]})

    def test_every_required_matrix_field_is_present(self) -> None:
        fields = {
            "id", "source", "evidenceClass", "route", "artifactIdentity",
            "intakeResult", "validationResult", "bindingResult",
            "sourceSpecificEvaluation", "floorContribution", "cutEffect",
            "candidateEffect", "fixtureOrReal", "expectedOutcome",
            "observedOutcome", "inputHashes",
        }
        for row in _MATRIX["scenarios"]:
            with self.subTest(scenario=row["id"]):
                self.assertTrue(fields <= set(row))


if __name__ == "__main__":
    unittest.main()
