# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The earlier phases' records are immutable, and this is what says so.

This phase adds a capability. It corrects no earlier phase, supersedes no
earlier claim, and therefore owes the earlier records exactly one thing: that
they are still there, byte for byte. A sentence promising that is worth nothing
a year from now; a test that reads the digests is worth the same in five.

The digests come from
``qualification/companion-3d-renderer/preserved-evidence.json``, written once
when this branch was cut from ``fa49380``. A file that changed, disappeared or
was added under a *prior* phase's tree fails here — including a change that
looks harmless, because "harmless" is a judgement the digest is not asking for.

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
_RECORD = _ROOT / "qualification" / "companion-3d-renderer" / "preserved-evidence.json"

#: This phase's own tree. It did not exist when the record was written, so it is
#: excluded from the "nothing was added" check rather than added to the record —
#: a record that included its own evidence would have to be rewritten every time
#: a gate ran, which is the opposite of an immutable one.
_OWN_PHASE = "qualification/companion-3d-renderer/"


def _digest(path: Path) -> tuple[int, str]:
    raw = path.read_bytes()
    return len(raw), hashlib.sha256(raw).hexdigest()


class PreservedEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.record = json.loads(_RECORD.read_text(encoding="utf-8"))

    def test_the_record_names_the_base_commit_this_branch_was_cut_from(self) -> None:
        self.assertEqual(
            self.record["baseCommit"], "fa49380dadf0aa90690c4f2be5b483b16a56c0db"
        )
        self.assertEqual(self.record["phase"], "companion-3d-renderer")

    def test_every_prior_evidence_file_is_byte_identical(self) -> None:
        mismatched: list[str] = []
        missing: list[str] = []
        for name, expected in sorted(self.record["preservedEvidence"].items()):
            path = _ROOT / name
            if not path.is_file():
                missing.append(name)
                continue
            size, digest = _digest(path)
            if size != expected["bytes"] or digest != expected["sha256"]:
                mismatched.append(name)
        self.assertEqual(missing, [], "prior evidence files disappeared")
        self.assertEqual(mismatched, [], "prior evidence files changed")

    def test_no_file_was_added_to_an_earlier_phase_tree(self) -> None:
        recorded = set(self.record["preservedEvidence"])
        added = [
            path.relative_to(_ROOT).as_posix()
            for path in sorted((_ROOT / "qualification").rglob("*"))
            if path.is_file()
            and path.relative_to(_ROOT).as_posix() not in recorded
            and not path.relative_to(_ROOT).as_posix().startswith(_OWN_PHASE)
        ]
        self.assertEqual(added, [], "a file was added to an earlier phase's evidence tree")

    def test_the_record_covers_every_earlier_phase(self) -> None:
        phases = {
            name.split("/")[1] for name in self.record["preservedEvidence"]
            if name.startswith("qualification/")
        }
        for earlier in (
            "companion-agent-providers", "companion-desktop-actions", "companion-linux",
            "companion-speech-input", "companion-voice", "companion-voice-closure",
            "display-stack", "first-login", "hardware", "installed-system",
            "reproducibility", "tpm",
        ):
            self.assertIn(earlier, phases, f"{earlier} is not covered by the record")


if __name__ == "__main__":
    unittest.main()
