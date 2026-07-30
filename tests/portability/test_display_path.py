"""Report output must work wherever the report is written.

The two-person signing drill writes its record to ``$RUNNER_TEMP`` in CI, on
purpose: a drill artifact inside the working tree could be mistaken for a
committed one. The closing progress line called ``Path.relative_to``, which
raises for a path outside the root, so the drill crashed after all nine of its
checks had passed and its record had been written.

These tests fix the boundary between the two uses of ``relative_to``. Display
never raises. Containment always does.
"""

from __future__ import annotations

import datetime as _datetime
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from release.paths import display_path, is_within  # noqa: E402


class DisplayPathTests(unittest.TestCase):
    def test_output_inside_the_repository_displays_relative(self) -> None:
        rendered = display_path(ROOT / "build/out/qualification/report.json", ROOT)
        self.assertEqual(rendered, "build/out/qualification/report.json")

    def test_relative_output_path_resolves_against_the_working_directory(self) -> None:
        previous = Path.cwd()
        os.chdir(ROOT)
        try:
            self.assertEqual(display_path(Path("build/out/x.json"), ROOT), "build/out/x.json")
        finally:
            os.chdir(previous)

    def test_output_in_the_system_temporary_directory_displays_absolute(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "two-person-signing-drill.json"
            rendered = display_path(target, ROOT)
            self.assertEqual(rendered, str(target.resolve()))
            self.assertTrue(Path(rendered).is_absolute())

    @unittest.skipIf(os.name != "posix", "POSIX temporary-directory layout")
    def test_posix_runner_temp_displays_absolute(self) -> None:
        # The exact path from the failing CI run.
        target = Path("/tmp/_temp/two-person-signing-drill.json")
        self.assertEqual(display_path(target, ROOT), str(target))

    @unittest.skipIf(os.name != "nt", "Windows temporary-path form")
    def test_windows_temporary_path_displays_absolute(self) -> None:
        target = Path(os.environ.get("TEMP", "C:/Windows/Temp")) / "drill.json"
        rendered = display_path(target, ROOT)
        self.assertEqual(rendered, str(target.resolve()))
        self.assertTrue(Path(rendered).is_absolute())
        self.assertRegex(rendered, r"^[A-Za-z]:|^\\\\")

    def test_a_repository_relative_result_is_posix_on_every_platform(self) -> None:
        # A message must read the same on a Windows development host and an
        # Ubuntu runner, or diffing two runs' logs reports noise.
        rendered = display_path(ROOT / "scripts" / "release.py", ROOT)
        self.assertEqual(rendered, "scripts/release.py")
        self.assertNotIn("\\", rendered)

    def test_a_symlink_is_described_by_its_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            outside = Path(directory).resolve()
            (outside / "record.json").write_text("{}", encoding="utf-8")
            link = ROOT / "build" / "out" / "portability-symlink-probe"
            link.parent.mkdir(parents=True, exist_ok=True)
            try:
                link.symlink_to(outside / "record.json")
            except (OSError, NotImplementedError) as exc:  # pragma: no cover
                self.skipTest(f"symlinks unavailable: {exc}")
            try:
                # The link lives in the repository; its target does not. Display
                # follows the target, so the rendered path is absolute.
                self.assertEqual(display_path(link, ROOT), str((outside / "record.json").resolve()))
            finally:
                link.unlink(missing_ok=True)

    def test_display_never_raises_for_an_unrelated_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.assertTrue(display_path(ROOT / "README.md", directory))


class ContainmentIsStillEnforcedTests(unittest.TestCase):
    """The fallback is display-only. No boundary check may acquire it."""

    def test_is_within_reports_containment_without_raising(self) -> None:
        self.assertTrue(is_within(ROOT / "scripts", ROOT))
        with tempfile.TemporaryDirectory() as directory:
            self.assertFalse(is_within(directory, ROOT))

    def test_an_evidence_reference_escaping_the_repository_is_still_refused(self) -> None:
        from release.evidence import parse_record, verify_record

        with tempfile.TemporaryDirectory() as directory:
            outside = Path(directory).resolve()
            (outside / "leak.txt").write_text("x", encoding="utf-8")
            record = parse_record(
                {
                    "id": "escape-probe",
                    "category": "Build",
                    "description": "an evidence reference pointing outside the repository",
                    "evidenceType": "artifact-digest",
                    "evidenceReference": "../" * 12 + "etc/passwd",
                    "result": "PASS",
                    "sourceCommit": "a" * 40,
                    "generatedAt": "2026-07-30T00:00:00Z",
                    "contentDigest": "a" * 64,
                    "reviewer": "portability probe",
                }
            )
            verdict = verify_record(
                record,
                root=ROOT,
                sourceCommit="a" * 40,
                now=_datetime.datetime(2026, 7, 30, tzinfo=_datetime.timezone.utc),
            )
            self.assertTrue(verdict.blocking)
            self.assertTrue(
                any("escapes the repository" in reason for reason in verdict.reasons),
                f"an escaping evidenceReference was not refused: {verdict.reasons}",
            )

    def test_a_private_signing_key_inside_the_repository_is_still_refused(self) -> None:
        # sign-stable-rc.py inverts the check: relative_to *succeeding* is the
        # failure. A blanket fallback here would have accepted a committed key.
        source = (ROOT / "build/scripts/sign-stable-rc.py").read_text(encoding="utf-8")
        self.assertIn("private signing keys must not be stored in the repository", source)
        self.assertIn("key.relative_to(ROOT.resolve())", source)
        self.assertNotIn("display_path(key", source)


class DrillWritesOutsideTheRepositoryTests(unittest.TestCase):
    """The exact CI invocation that failed, end to end."""

    def test_the_drill_completes_with_its_output_outside_the_repository(self) -> None:
        if not __import__("shutil").which("openssl"):
            self.skipTest("openssl unavailable")
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/two_person_drill.py"),
                    "--keydir", str(base / "keys"),
                    "--logdir", str(base / "logs"),
                    "--out", str(base / "two-person-signing-drill.json"),
                ],
                cwd=ROOT, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn("ValueError", result.stderr)
            self.assertIn("9/9", result.stdout)
            self.assertTrue((base / "two-person-signing-drill.json").is_file())

    def test_output_location_does_not_change_record_content(self) -> None:
        if not __import__("shutil").which("openssl"):
            self.skipTest("openssl unavailable")
        import json

        records = []
        for label in ("inside", "outside"):
            with tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                destination = (
                    ROOT / "build/out/portability-drill.json" if label == "inside"
                    else base / "portability-drill.json"
                )
                destination.parent.mkdir(parents=True, exist_ok=True)
                try:
                    result = subprocess.run(
                        [
                            sys.executable,
                            str(ROOT / "scripts/two_person_drill.py"),
                            "--keydir", str(base / "keys"),
                            "--logdir", str(base / "logs"),
                            "--out", str(destination),
                        ],
                        cwd=ROOT, capture_output=True, text=True,
                    )
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    records.append(json.loads(destination.read_text(encoding="utf-8")))
                finally:
                    if label == "inside":
                        destination.unlink(missing_ok=True)

        # Everything the drill measured must be identical. The fields that name
        # the run's own scratch directories and its wall-clock are expected to
        # differ, and are the only fields permitted to.
        # The scratch directories, the wall-clock, the synthetic artifact and
        # the per-run keys differ by construction; "checks" quotes the log
        # directory in its detail text, so its names and results are compared
        # separately below rather than its prose.
        variable = {"runAt", "keyDirectory", "operationLogDirectory", "artifactDigest",
                    "signers", "artifact", "checks"}
        left = {k: v for k, v in records[0].items() if k not in variable}
        right = {k: v for k, v in records[1].items() if k not in variable}
        self.assertEqual(left, right)
        self.assertEqual(
            [check["check"] for check in records[0]["checks"]],
            [check["check"] for check in records[1]["checks"]],
        )
        self.assertEqual(
            [check["outcome"] for check in records[0]["checks"]],
            [check["outcome"] for check in records[1]["checks"]],
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
