"""ShellCheck must pass on a hosted runner without broad suppression.

`scripts/reproducibility/collect-builder-record.sh` sourced `/etc/os-release`.
ShellCheck cannot follow an absolute runtime path, so it emitted SC1091, and
`scripts/task.py validate` runs shellcheck with no severity floor — an `info`
finding failed four jobs across three workflows. The development host that
produced the script has no shellcheck and printed `SKIP` instead.

The repair reads the two fields rather than sourcing them. These tests hold that
shape: no suppression anywhere, no sourcing, and the same output the sourcing
version produced — including `unknown` when the file is absent.
"""

from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
COLLECTOR = ROOT / "scripts/reproducibility/collect-builder-record.sh"


def shell_scripts() -> list[Path]:
    return sorted(
        path
        for path in ROOT.rglob("*.sh")
        if "node_modules" not in path.parts and ".git" not in path.parts
    )


class NoBroadSuppressionTests(unittest.TestCase):
    def test_no_shellcheckrc_disables_findings_repository_wide(self) -> None:
        for name in (".shellcheckrc", "shellcheckrc"):
            candidate = ROOT / name
            if candidate.is_file():
                text = candidate.read_text(encoding="utf-8")
                self.assertNotIn("disable=SC1091", text.replace(" ", ""))

    def test_no_script_carries_an_sc1091_directive(self) -> None:
        offenders = [
            str(path.relative_to(ROOT)).replace("\\", "/")
            for path in shell_scripts()
            if re.search(r"shellcheck\s+disable=.*SC1091", path.read_text(encoding="utf-8"))
        ]
        self.assertEqual(offenders, [], f"SC1091 suppressed in {offenders}")

    def test_validate_does_not_lower_the_shellcheck_severity_floor(self) -> None:
        # `--severity=warning` would hide SC1091 along with every other info
        # finding in the repository, which is the suppression this forbids
        # wearing a different name.
        source = (ROOT / "scripts/task.py").read_text(encoding="utf-8")
        self.assertNotIn("--severity", source)
        self.assertNotIn("--exclude", source)


class OsReleaseIsReadNotSourcedTests(unittest.TestCase):
    def test_no_shell_script_sources_etc_os_release(self) -> None:
        offenders = []
        for path in shell_scripts():
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if re.search(r"(^|[^\w])(\.|source)\s+/etc/os-release", line):
                    offenders.append(f"{path.relative_to(ROOT)}:{number}")
        self.assertEqual(offenders, [], f"/etc/os-release sourced at {offenders}")

    def test_the_collector_still_reports_an_operating_system(self) -> None:
        self.assertIn("os_release_id", COLLECTOR.read_text(encoding="utf-8"))
        self.assertIn('"operatingSystem": "$(os_release_id) $(uname -r)"', COLLECTOR.read_text(encoding="utf-8"))


class ShellCheckPassesTests(unittest.TestCase):
    def test_shellcheck_accepts_every_shell_script(self) -> None:
        if not shutil.which("shellcheck"):
            self.skipTest("shellcheck unavailable on this host")
        result = subprocess.run(
            ["shellcheck", *[str(path) for path in shell_scripts()]],
            cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class AbsentOsReleaseTests(unittest.TestCase):
    """The `unknown` fallback the sourcing version had must survive."""

    def _run_with_os_release(self, replacement: str | None) -> str:
        if not shutil.which("bash"):
            self.skipTest("bash unavailable on this host")
        import tempfile

        text = COLLECTOR.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            if replacement is None:
                probe = text.replace("/etc/os-release", str(base / "absent-os-release"))
            else:
                stub = base / "os-release"
                stub.write_text(replacement, encoding="utf-8")
                probe = text.replace("/etc/os-release", str(stub).replace("\\", "/"))
            script = base / "probe.sh"
            script.write_text(probe, encoding="utf-8", newline="\n")
            result = subprocess.run(
                ["bash", str(script), "probe"],
                cwd=ROOT, capture_output=True, text=True,
                # POSIX form: the script emits the worktree into JSON verbatim,
                # and a Windows path's backslashes would be JSON escapes. The
                # script only ever runs on a Linux builder in practice.
                env={**__import__("os").environ, "BUNNY_WORKTREE": base.as_posix()},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout

    def test_a_missing_os_release_reports_unknown(self) -> None:
        output = self._run_with_os_release(None)
        self.assertRegex(output, r'"operatingSystem": "unknown ')

    def test_a_present_os_release_reports_id_and_version(self) -> None:
        output = self._run_with_os_release('NAME="Fedora Linux"\nID=fedora\nVERSION_ID=44\n')
        self.assertRegex(output, r'"operatingSystem": "fedora-44 ')

    def test_quotes_around_the_values_are_stripped(self) -> None:
        output = self._run_with_os_release('ID="ubuntu"\nVERSION_ID="24.04"\n')
        self.assertRegex(output, r'"operatingSystem": "ubuntu-24\.04 ')

    def test_a_missing_version_id_does_not_emit_a_trailing_separator(self) -> None:
        output = self._run_with_os_release("ID=arch\n")
        self.assertRegex(output, r'"operatingSystem": "arch ')

    def test_the_record_remains_parseable_json_in_every_case(self) -> None:
        import json

        for replacement in (None, "ID=fedora\nVERSION_ID=44\n", "ID=arch\n"):
            with self.subTest(replacement=replacement):
                json.loads(self._run_with_os_release(replacement))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
