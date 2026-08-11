# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The line-endings validator, and its own negative control.

A check that passes because it looked at nothing is worse than no check, and
this one is easy to write that way: point it at a tree with no matching files
and it reports PASS. So the first test here is that it *fails* on a file it
should fail on, and only then does the second one assert the repository is
clean.

The defect behind it: `.gitattributes` marks `*.sh` as `-text`, which stops git
converting line endings and does nothing to stop a script being authored with
CRLF and committed verbatim. One was. It failed on its first line inside a
booted guest with `set: pipefail: invalid option name`, and `bash -n` on a
Windows host had accepted it, because bash there tolerates the carriage return
that bash on Linux does not.
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from release.validation import CRLF, _line_endings

from tests.support import ROOT


class TheValidatorCatchesIt(unittest.TestCase):
    def test_a_shell_script_with_crlf_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / "good.sh").write_bytes(b"#!/usr/bin/bash\nset -euo pipefail\n")
            (base / "bad.sh").write_bytes(b"#!/usr/bin/bash\r\nset -euo pipefail\r\n")
            outcome = _line_endings(base)
        self.assertEqual(outcome.result, "FAIL")
        self.assertEqual([failure.path for failure in outcome.failures], ["bad.sh"])

    def test_a_systemd_unit_with_crlf_fails(self) -> None:
        """Units are the case .gitattributes' own comment is about: a directive
        value ending in a carriage return is a value systemd takes literally."""
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / "systemd").mkdir()
            (base / "systemd" / "bunny.service").write_bytes(b"[Unit]\r\nDescription=x\r\n")
            outcome = _line_endings(base)
        self.assertEqual(outcome.result, "FAIL")

    def test_a_clean_tree_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / "fine.sh").write_bytes(b"#!/usr/bin/bash\necho ok\n")
            outcome = _line_endings(base)
        self.assertEqual(outcome.result, "PASS")
        self.assertEqual(outcome.checked, 1)

    def test_the_constant_is_built_rather_than_written(self) -> None:
        """A literal CRLF in the source of a CRLF detector is a literal that the
        thing being detected can corrupt."""
        self.assertEqual(CRLF, b"\x0d\x0a")


class TheRepositoryIsClean(unittest.TestCase):
    def test_no_attribute_protected_file_carries_crlf(self) -> None:
        outcome = _line_endings(ROOT)
        self.assertEqual(
            [failure.path for failure in outcome.failures], [],
            "a file the attributes protect was committed with CRLF",
        )
        self.assertGreater(outcome.checked, 50)


if __name__ == "__main__":
    unittest.main()
