"""A crash must never be reported as a protected gate correctly refusing.

Several CI steps asserted only "the gate did not return 0". A traceback exits 1.
So does a missing evidence file, an import error and a syntax error. A job
written that way goes green when `release.py` stops parsing, and prints that the
stable gate correctly reports NO-GO — the most misleading thing this pipeline
could say.

The contract is exit 0 approved, exit 2 evaluated-and-refused, anything else
failed-to-evaluate.
"""

from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "build/scripts/assert-gate.sh"
WORKFLOWS = ROOT / ".github/workflows"

PROTECTED_GATES = (
    "gate --kind qualification-candidate",
    "gate --kind stable-release",
    "gate --kind oem-pilot",
    "gate --kind enterprise-pilot",
    "gate --kind sync-pilot",
)


def run_helper(expected: str, *command: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(HELPER), expected, "probe", "--", *command],
        cwd=ROOT, capture_output=True, text=True,
    )


@unittest.skipUnless(shutil.which("bash"), "bash unavailable on this host")
class AssertGateSemanticsTests(unittest.TestCase):
    def test_a_gate_that_refuses_with_exit_two_is_accepted(self) -> None:
        result = run_helper("2", "bash", "-c", "exit 2")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("correctly refused", result.stdout)

    def test_a_gate_that_approves_when_refusal_was_expected_fails(self) -> None:
        result = run_helper("2", "bash", "-c", "exit 0")
        self.assertEqual(result.returncode, 1)
        self.assertIn("unexpectedly returned approval", result.stdout)

    def test_a_crash_is_not_accepted_as_a_refusal(self) -> None:
        # The defect. Exit 1 is a traceback, not a refusal.
        result = run_helper("2", "bash", "-c", "exit 1")
        self.assertEqual(result.returncode, 1)
        self.assertIn("failed to evaluate", result.stdout)
        self.assertIn("NOT a protected refusal", result.stdout)

    def test_a_missing_file_is_not_accepted_as_a_refusal(self) -> None:
        # CPython exits 2 for "can't open file", which is also the refusal
        # status — the one crash an exit code alone cannot distinguish. The
        # helper checks the script exists before running it.
        result = run_helper("2", sys.executable, "does-not-exist.py")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("does not exist", result.stdout)
        self.assertIn("NOT a protected refusal", result.stdout)

    def test_every_script_a_workflow_asserts_on_exists(self) -> None:
        missing = []
        for path in sorted(WORKFLOWS.glob("*.yml")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if "assert-gate.sh" not in line:
                    continue
                for token in line.split():
                    if token.endswith((".py", ".sh")) and not (ROOT / token).is_file():
                        missing.append(f"{path.name}: {token}")
        self.assertEqual(missing, [])

    def test_a_python_traceback_is_not_accepted_as_a_refusal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "crash.py"
            script.write_text("raise RuntimeError('boom')\n", encoding="utf-8")
            result = run_helper("2", sys.executable, str(script))
            self.assertEqual(result.returncode, 1)
            self.assertIn("failed to evaluate", result.stdout)

    def test_an_unusual_exit_status_is_not_accepted_as_a_refusal(self) -> None:
        for status in (3, 5, 127):
            with self.subTest(status=status):
                result = run_helper("2", "bash", "-c", f"exit {status}")
                self.assertEqual(result.returncode, 1)
                self.assertIn(f"exit {status}", result.stdout)

    def test_expecting_a_pass_reports_a_refusal_distinctly(self) -> None:
        result = run_helper("0", "bash", "-c", "exit 2")
        self.assertEqual(result.returncode, 1)
        self.assertIn("refused (exit 2) but was expected to pass", result.stdout)

    def test_evaluated_accepts_either_verdict_but_not_a_crash(self) -> None:
        for status in (0, 2):
            with self.subTest(status=status):
                self.assertEqual(run_helper("evaluated", "bash", "-c", f"exit {status}").returncode, 0)
        crash = run_helper("evaluated", "bash", "-c", "exit 1")
        self.assertEqual(crash.returncode, 1)
        self.assertIn("a crash is not", crash.stdout)

    def test_a_nonsense_expectation_is_rejected(self) -> None:
        self.assertEqual(run_helper("7", "bash", "-c", "exit 0").returncode, 64)


class NoWorkflowAcceptsAnyNonZeroStatusTests(unittest.TestCase):
    """Every protected-gate call site must assert an exact status."""

    def workflow_text(self) -> dict[str, str]:
        return {
            path.name: path.read_text(encoding="utf-8")
            for path in sorted(WORKFLOWS.glob("*.yml"))
        }

    def test_every_protected_gate_invocation_goes_through_the_helper(self) -> None:
        offenders = []
        for name, text in self.workflow_text().items():
            for number, line in enumerate(text.splitlines(), 1):
                if not any(gate in line for gate in PROTECTED_GATES):
                    continue
                if "assert-gate.sh" in line:
                    continue
                # A `for kind in ...` loop body is checked by the line that runs
                # the gate, not the line that names the kinds.
                if line.strip().startswith("#") or "for kind" in line:
                    continue
                offenders.append(f"{name}:{number}: {line.strip()}")
        self.assertEqual(offenders, [], "protected gate invoked without an exact status assertion")

    def test_no_workflow_treats_any_nonzero_status_as_a_refusal(self) -> None:
        # `if python ...; then error; fi` and a bare `[ "$status" -ne 0 ]` both
        # accept a crash. Neither may return.
        offenders = []
        for name, text in self.workflow_text().items():
            for number, line in enumerate(text.splitlines(), 1):
                if re.search(r'\[\s*"\$status"\s*-ne\s*0\s*\]', line):
                    offenders.append(f"{name}:{number}: {line.strip()}")
                if re.search(r"^\s*if\s+python\s+scripts/(release|phase5|phase7)\.py", line):
                    offenders.append(f"{name}:{number}: {line.strip()}")
        self.assertEqual(offenders, [])

    def test_no_workflow_still_hand_rolls_the_status_capture(self) -> None:
        offenders = [
            name for name, text in self.workflow_text().items() if "set +e" in text
        ]
        self.assertEqual(offenders, [], "hand-rolled status capture remains; use assert-gate.sh")


class DocumentedExitCodesHoldTests(unittest.TestCase):
    """The contract the helper depends on, checked against the real commands."""

    def _status(self, *command: str) -> int:
        return subprocess.run(
            [sys.executable, *command], cwd=ROOT, capture_output=True, text=True
        ).returncode

    # The source gate is deliberately not invoked here. It runs
    # `scripts/task.py test`, which discovers this file, which would invoke the
    # source gate again — the suite would never terminate. `gate --kind source`
    # is asserted from CI instead, where it is the top of the call stack.

    def test_each_protected_gate_returns_exactly_two(self) -> None:
        for kind in ("qualification-candidate", "stable-release",
                     "oem-pilot", "enterprise-pilot", "sync-pilot"):
            with self.subTest(kind=kind):
                self.assertEqual(
                    self._status("scripts/release.py", "gate", "--kind", kind), 2,
                    f"{kind} did not return the documented refusal status",
                )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
