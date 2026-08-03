# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the retention manifest.

The manifest records what was retained outside the repository so that a committed
evidence record can be checked against real bytes later. Its second job is to
refuse to describe a secret-bearing artifact as retained, because the realistic
way a passphrase escapes is not a deliberate commit but a serial log capturing an
echoed prompt.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"

spec = importlib.util.spec_from_file_location("retention", SCRIPTS / "retention-manifest.py")
retention = importlib.util.module_from_spec(spec)
spec.loader.exec_module(retention)

NOW = "2026-08-03T12:00:00+00:00"


def make_run(tmp: Path, files: dict[str, bytes], run: str = "ENC-20260803-01") -> Path:
    run_root = tmp / "evidence" / run
    run_root.mkdir(parents=True)
    for name, content in files.items():
        target = run_root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return tmp


class ManifestShapeTests(unittest.TestCase):
    def test_every_required_field_is_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_run(Path(tmp), {"console.log": b"booted cleanly\n"})
            manifest = retention.build("ENC-20260803-01", root, {}, now=NOW)
            entry = manifest["entries"][0]
            for field in ("path", "size", "sha256", "createdTime", "sourceRun",
                          "retentionClass", "containsSecrets", "redactionStatus"):
                self.assertIn(field, entry)

    def test_the_digest_is_of_the_actual_bytes(self):
        from hashlib import sha256
        payload = b"unlock completed in 2.4s\n"
        with tempfile.TemporaryDirectory() as tmp:
            root = make_run(Path(tmp), {"console.log": payload})
            manifest = retention.build("ENC-20260803-01", root, {}, now=NOW)
            self.assertEqual(manifest["entries"][0]["sha256"], sha256(payload).hexdigest())

    def test_a_missing_run_directory_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                retention.build("NO-SUCH-RUN", Path(tmp), {}, now=NOW)

    def test_files_default_to_the_conservative_class(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_run(Path(tmp), {"console.log": b"x\n"})
            manifest = retention.build("ENC-20260803-01", root, {}, now=NOW)
            self.assertEqual(manifest["entries"][0]["retentionClass"], "diagnostic")

    def test_classes_can_be_assigned_by_path_fragment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_run(Path(tmp), {"summary.json": b"{}\n", "overlays/disk.qcow2": b"x\n"})
            manifest = retention.build(
                "ENC-20260803-01", root, {"summary.json": "authority", "overlays/": "disposable"},
                now=NOW,
            )
            classes = {Path(e["path"]).name: e["retentionClass"] for e in manifest["entries"]}
            self.assertEqual(classes["summary.json"], "authority")
            self.assertEqual(classes["disk.qcow2"], "disposable")


class SecretRefusalTests(unittest.TestCase):
    """A retained artifact carrying a secret is refused, not footnoted."""

    def assert_flagged(self, content: bytes):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_run(Path(tmp), {"serial.log": content})
            manifest = retention.build("ENC-20260803-01", root, {}, now=NOW)
            entry = manifest["entries"][0]
            self.assertTrue(entry["containsSecrets"], content)
            self.assertEqual(entry["redactionStatus"], "REVIEW_REQUIRED")
            self.assertFalse(manifest["clean"])

    def test_an_echoed_passphrase_is_flagged(self):
        self.assert_flagged(b"cryptsetup: passphrase=hunter2\n")

    def test_a_password_assignment_is_flagged(self):
        self.assert_flagged(b"PASSWORD: correct-horse\n")

    def test_a_private_key_is_flagged(self):
        self.assert_flagged(b"-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n")

    def test_tpm_owner_authorization_is_flagged(self):
        self.assert_flagged(b"tpm_owner_auth = 0123456789\n")

    def test_ordinary_evidence_is_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_run(Path(tmp), {
                "console.log": b"LUKS device unlocked; mount succeeded\n",
                "summary.json": b'{"unlockSeconds": 2.4, "result": "PASS"}\n',
            })
            manifest = retention.build("ENC-20260803-01", root, {}, now=NOW)
            self.assertTrue(manifest["clean"])
            self.assertEqual(manifest["secretBearingCount"], 0)

    def test_the_word_password_alone_is_not_a_secret(self):
        """A prose mention must not make every log unretainable."""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_run(Path(tmp), {"notes.txt": b"the wrong password was rejected\n"})
            manifest = retention.build("ENC-20260803-01", root, {}, now=NOW)
            self.assertTrue(manifest["clean"], "a bare mention should not trip the scanner")

    def test_an_unreadable_file_is_treated_as_unclean(self):
        """Not scannable is not clean."""
        self.assertTrue(retention.contains_secret(Path("does-not-exist-at-all")))


class ExitCodeTests(unittest.TestCase):
    def _run(self, root: Path, run: str = "ENC-20260803-01") -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPTS / "retention-manifest.py"),
             "--run", run, "--root", str(root)],
            capture_output=True, text=True,
        )

    def test_a_clean_run_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_run(Path(tmp), {"console.log": b"ok\n"})
            proc = self._run(root)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_a_secret_bearing_run_exits_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_run(Path(tmp), {"serial.log": b"passphrase=hunter2\n"})
            proc = self._run(root)
            self.assertEqual(proc.returncode, 2, proc.stdout)
            self.assertIn("BLOCKED", proc.stdout)
            self.assertIn("serial.log", proc.stdout)

    def test_a_missing_run_exits_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = self._run(Path(tmp), run="NO-SUCH-RUN")
            self.assertEqual(proc.returncode, 2, proc.stdout)
            self.assertIn("BLOCKED", proc.stdout)


if __name__ == "__main__":
    unittest.main()
