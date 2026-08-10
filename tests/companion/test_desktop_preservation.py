# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The earlier phases' records are immutable, and this is what says so.

This phase adds a capability. It corrects no earlier phase, supersedes no
earlier claim, and therefore owes the earlier records exactly one thing: that
they are still there, byte for byte. A sentence promising that is worth nothing
a year from now; a test that reads the digests is worth the same in five.

The digests come from
``qualification/companion-desktop-actions/preserved-evidence.json``, written
once when this branch was cut from `ef0c957`. A file that changed, disappeared
or was added fails here — including a change that looks harmless, because
"harmless" is a judgement the digest is not asking for.

``qualification/**`` is ``-text`` in ``.gitattributes``, which is what makes the
comparison meaningful across the two hosts this phase used: without it a Windows
checkout would renormalise line endings and every digest would fail for a reason
that has nothing to do with the evidence.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest

_ROOT = Path(__file__).resolve().parents[2]
_RECORD = _ROOT / "qualification" / "companion-desktop-actions" / "preserved-evidence.json"


def _digest(path: Path) -> tuple[int, str]:
    raw = path.read_bytes()
    return len(raw), hashlib.sha256(raw).hexdigest()


class PreservedEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.record = json.loads(_RECORD.read_text(encoding="utf-8"))

    def test_the_record_names_the_base_commit_this_branch_was_cut_from(self) -> None:
        self.assertEqual(
            self.record["baseCommit"],
            "ef0c9572262acd8bd48b74ff7234573ac0b78d55",
        )
        self.assertEqual(self.record["phase"], "companion-desktop-actions")

    def test_every_prior_evidence_file_is_byte_identical(self) -> None:
        preserved = self.record["preservedEvidence"]
        self.assertGreaterEqual(len(preserved), 55, "the record itself looks truncated")
        for relative, expected in preserved.items():
            with self.subTest(path=relative):
                path = _ROOT / relative
                self.assertTrue(path.is_file(), f"{relative} has disappeared")
                size, digest = _digest(path)
                self.assertEqual(size, expected["bytes"], relative)
                self.assertEqual(digest, expected["sha256"], relative)

    def test_every_prior_report_is_byte_identical(self) -> None:
        for name, expected in self.record["preservedReports"].items():
            with self.subTest(report=name):
                path = _ROOT / name
                self.assertTrue(path.is_file(), f"{name} has disappeared")
                size, digest = _digest(path)
                self.assertEqual(size, expected["bytes"], name)
                self.assertEqual(digest, expected["sha256"], name)

    def test_no_prior_evidence_directory_gained_a_file(self) -> None:
        """A file *added* to an earlier phase's tree is as much a change as one
        edited: the manifest that phase committed would no longer describe it."""
        preserved = set(self.record["preservedEvidence"])
        for phase in self.record["priorPhases"]:
            directory = _ROOT / "qualification" / phase
            with self.subTest(phase=phase):
                self.assertTrue(directory.is_dir(), f"{phase} has disappeared")
                found = {
                    item.relative_to(_ROOT).as_posix()
                    for item in directory.rglob("*") if item.is_file()
                }
                self.assertEqual(found - preserved, set(), f"{phase} gained files")

    def test_qualification_evidence_is_declared_binary_so_digests_survive(self) -> None:
        attributes = (_ROOT / ".gitattributes").read_text(encoding="utf-8")
        self.assertIn("qualification/**", attributes)
        line = next(
            item for item in attributes.splitlines()
            if item.strip().startswith("qualification/**")
        )
        self.assertIn("-text", line)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
