"""Repository validation must name what failed.

The source gate reported:

    FAIL    repositoryValidation: every JSON document parses, every schema is
            well formed, every Python file compiles

when the failing check was ShellCheck on one line of one file. The description
named three things that had not failed. One Boolean stood for twelve checks.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from release.validation import (  # noqa: E402
    REQUIRED_VALIDATORS,
    run_validators,
)


class FixtureRepository:
    """A minimal tree the validators can run over."""

    def __init__(self, directory: Path) -> None:
        self.root = directory
        for relative in ("schemas", "shell/session", "shell/services", "shell/components",
                         "shell/schemas", "shell/themes", "shell/assets", "shell/icons",
                         "operations/data", ".github/workflows", "security/reachability/findings"):
            (self.root / relative).mkdir(parents=True, exist_ok=True)
        self.write("schemas/thing.schema.json", json.dumps({
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://bunny.example/thing.schema.json",
            "type": "object",
        }))
        self.write("shell/session/bunny.desktop",
                   "[Desktop Entry]\nType=Application\nName=Bunny\nExec=/usr/bin/bunny\n"
                   "DesktopNames=Bunny\n")
        self.write("shell/launcher.desktop",
                   "[Desktop Entry]\nType=Application\nName=Launcher\nExec=/usr/bin/l\n")
        self.write("good.py", "# SPDX-License-Identifier: GPL-3.0-or-later\nvalue = 1\n")
        self.write("good.sh", "#!/usr/bin/env bash\n# SPDX-License-Identifier: GPL-3.0-or-later\n"
                              "set -euo pipefail\necho ok\n")
        self.write(".github/workflows/ci.yml",
                   "name: ci\non: push\njobs:\n  build:\n    runs-on: ubuntu-24.04\n"
                   "    steps:\n      - run: echo ok\n")
        self.write("operations/data/release-evidence.json",
                   json.dumps({"candidateCommit": "a" * 40}))

    def write(self, relative: str, text: str) -> None:
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")


class EveryRequiredValidatorIsReportedTests(unittest.TestCase):
    def test_all_ten_required_validators_run_against_this_repository(self) -> None:
        report = run_validators(ROOT)
        reported = {outcome.name for outcome in report.outcomes}
        for name in REQUIRED_VALIDATORS:
            with self.subTest(validator=name):
                self.assertIn(name, reported)

    def test_the_ten_required_names_are_exactly_those_specified(self) -> None:
        self.assertEqual(
            REQUIRED_VALIDATORS,
            ("JSON parsing", "Schema validation", "Python compilation", "Shell syntax",
             "ShellCheck", "Desktop entries", "XML and SVG", "Licence headers",
             "Workflow YAML", "Committed evidence consistency"),
        )

    def test_this_repository_currently_passes_every_validator(self) -> None:
        report = run_validators(ROOT)
        self.assertTrue(report.passed, [o.as_dict() for o in report.failing])

    def test_a_skip_is_reported_as_skip_and_not_as_pass(self) -> None:
        # A check that never ran must not read as a check that passed.
        report = run_validators(ROOT)
        for outcome in report.outcomes:
            if outcome.result == "SKIP":
                self.assertTrue(outcome.skipReason, f"{outcome.name} skipped with no reason")
        self.assertIn("SKIP is not a PASS", report.as_dict()["note"])


class OneFailureDoesNotImplicateTheOthersTests(unittest.TestCase):
    """The defect: a ShellCheck failure reported as a JSON/schema/Python failure."""

    def _report(self, mutate):
        with tempfile.TemporaryDirectory() as directory:
            fixture = FixtureRepository(Path(directory))
            mutate(fixture)
            return run_validators(fixture.root)

    def test_a_broken_json_document_fails_only_json_parsing(self) -> None:
        report = self._report(lambda f: f.write("operations/data/broken.json", "{not json"))
        self.assertEqual([o.name for o in report.failing], ["JSON parsing"])
        self.assertFalse(report.passed)

    def test_a_broken_python_file_fails_only_python_compilation(self) -> None:
        report = self._report(lambda f: f.write("broken.py", "def (:\n"))
        self.assertEqual([o.name for o in report.failing], ["Python compilation"])

    def test_a_broken_shell_script_fails_only_shell_syntax(self) -> None:
        report = self._report(lambda f: f.write("broken.sh", "#!/usr/bin/env bash\nif then fi\n"))
        failing = [o.name for o in report.failing]
        # ShellCheck also rejects it when installed; both are shell validators
        # and neither is JSON, schemas or Python.
        self.assertIn("Shell syntax", failing)
        self.assertNotIn("JSON parsing", failing)
        self.assertNotIn("Schema validation", failing)
        self.assertNotIn("Python compilation", failing)

    def test_a_wrong_licence_header_fails_only_licence_headers(self) -> None:
        report = self._report(
            lambda f: f.write("proprietary.py", "# SPDX-License-Identifier: LicenseRef-Proprietary\n")
        )
        self.assertEqual([o.name for o in report.failing], ["Licence headers"])

    def test_a_broken_workflow_fails_only_workflow_yaml(self) -> None:
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("PyYAML unavailable")
        report = self._report(
            lambda f: f.write(".github/workflows/broken.yml", "name: x\non: push\njobs: []\n")
        )
        self.assertEqual([o.name for o in report.failing], ["Workflow YAML"])

    def test_a_schema_without_an_id_fails_only_schema_validation(self) -> None:
        report = self._report(lambda f: f.write("schemas/bad.schema.json", json.dumps({
            "$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object",
        })))
        self.assertEqual([o.name for o in report.failing], ["Schema validation"])

    def test_the_failure_names_the_exact_file(self) -> None:
        report = self._report(lambda f: f.write("operations/data/broken.json", "{not json"))
        failure = report.failing[0].failures[0]
        self.assertEqual(failure.path, "operations/data/broken.json")
        self.assertTrue(failure.detail)


class DesktopEntryKindsTests(unittest.TestCase):
    """Session entries and launchers obey different specifications."""

    def _report(self, mutate):
        with tempfile.TemporaryDirectory() as directory:
            fixture = FixtureRepository(Path(directory))
            mutate(fixture)
            return run_validators(fixture.root, only={"Desktop entries"})

    def test_a_session_entry_without_desktop_names_fails(self) -> None:
        report = self._report(lambda f: f.write(
            "shell/session/bunny.desktop",
            "[Desktop Entry]\nType=Application\nName=Bunny\nExec=/usr/bin/bunny\n",
        ))
        self.assertFalse(report.passed)
        self.assertIn("DesktopNames", report.failing[0].failures[0].detail)

    def test_a_launcher_carrying_desktop_names_fails(self) -> None:
        report = self._report(lambda f: f.write(
            "shell/launcher.desktop",
            "[Desktop Entry]\nType=Application\nName=L\nExec=/usr/bin/l\nDesktopNames=Bunny\n",
        ))
        self.assertFalse(report.passed)
        self.assertIn("session key", report.failing[0].failures[0].detail)

    def test_the_repositorys_own_session_entries_declare_desktop_names(self) -> None:
        report = run_validators(ROOT, only={"Desktop entries"})
        self.assertTrue(report.passed, [o.as_dict() for o in report.failing])
        self.assertIn("session", report.outcomes[0].summary)


class CommittedEvidenceConsistencyTests(unittest.TestCase):
    def test_a_finding_bound_to_another_commit_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = FixtureRepository(Path(directory))
            fixture.write(
                "security/reachability/findings/CVE-1999-0001.json",
                json.dumps({"sourceCommit": "b" * 40}),
            )
            report = run_validators(fixture.root, only={"Committed evidence consistency"})
            self.assertFalse(report.passed)
            self.assertIn("does not transfer between commits",
                          report.failing[0].failures[0].detail)

    def test_an_abbreviated_candidate_commit_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = FixtureRepository(Path(directory))
            fixture.write("operations/data/release-evidence.json",
                          json.dumps({"candidateCommit": "79bb99d"}))
            report = run_validators(fixture.root, only={"Committed evidence consistency"})
            self.assertFalse(report.passed)
            self.assertIn("not a full 40-character SHA", report.failing[0].failures[0].detail)


class MachineReadableOutputTests(unittest.TestCase):
    def test_validate_writes_the_machine_readable_report(self) -> None:
        destination = ROOT / "build/out/qualification/repository-validation.json"
        destination.unlink(missing_ok=True)
        result = subprocess.run(
            [sys.executable, "scripts/task.py", "validate"],
            cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(destination.is_file())
        payload = json.loads(destination.read_text(encoding="utf-8"))
        self.assertEqual(payload["result"], "PASS")
        self.assertEqual(payload["requiredValidators"], list(REQUIRED_VALIDATORS))
        names = {item["validator"] for item in payload["validators"]}
        for name in REQUIRED_VALIDATORS:
            self.assertIn(name, names)

    def test_each_validator_reports_its_own_count(self) -> None:
        payload = run_validators(ROOT).as_dict()
        for item in payload["validators"]:
            if item["result"] == "PASS":
                with self.subTest(validator=item["validator"]):
                    self.assertGreater(item["checked"], 0, item)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
