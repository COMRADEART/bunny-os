# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""A script that cannot execute must not be counted as qualification infrastructure.

Phase 6 found two of its own scripts committed with CRLF under ``-text``: the
executable bit said "runnable", the bytes said otherwise, and no gate measured
the difference. ``-text`` makes the corruption permanent — the working tree
looks fine on the host that committed it, and the shebang carries a ``\\r`` on
every host that matters.

This gate asks the *repository*, not the working tree. On a Windows checkout
the working copy of an LF blob may legitimately be CRLF on disk; what executes
on the target is the committed blob, so the committed blob is what gets
checked, via ``git ls-files --eol`` (the index column) and ``git cat-file``.

Three rules, each with a constructed-blob negative control below so the suite
always exercises the failure branch:

1. **Executable implies script.** A mode-100755 file must open with ``#!``.
   Ten evidence data files carried stray executable bits when this gate was
   written; their *modes* were corrected (content untouched — both
   evidence-immutability guards pin bytes, and pass before and after).
2. **The shebang must be executable.** The interpreter line of any executable
   file must be CR-free and name an interpreter from the measured allowlist.
   ``exec`` hands ``/usr/bin/bash\\r`` to the kernel verbatim; there is no
   such file on any image this project builds.
3. **Shell scripts are CR-free throughout**, executable bit or not. Bash
   fails on ``\\r`` mid-file, not only in the shebang, and non-executable
   ``.sh`` files here are run via ``bash script.sh`` and sourced as
   libraries.

"Interpreter availability where practical": the allowlist below is what the
built image and the qualification hosts ship. On a POSIX host the suite also
resolves each direct-path interpreter on the machine actually running the
certification; on hosts where that question is meaningless (Windows), that
half is skipped, not passed.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys
import unittest

_ROOT = Path(__file__).resolve().parents[2]

#: Interpreters a committed script may name. Measured from the repository and
#: from what the image and the qualification hosts install — not aspirational.
ALLOWED_INTERPRETERS = frozenset({
    "/usr/bin/bash",
    "/bin/bash",
    "/usr/bin/sh",
    "/bin/sh",
    "/usr/bin/env bash",
    "/usr/bin/env sh",
    "/usr/bin/env python3",
    "/usr/bin/python3",
})


def shebang_violations(mode: str, name: str, first_line: bytes) -> list[str]:
    """Rules 1 and 2, as a function of one committed file's facts."""
    problems: list[str] = []
    executable = mode == "100755"
    has_shebang = first_line.startswith(b"#!")
    if executable and not has_shebang:
        problems.append(f"{name}: executable without a shebang")
    if has_shebang and executable:
        if b"\r" in first_line:
            problems.append(f"{name}: the shebang line carries CR")
        else:
            interpreter = first_line[2:].decode("utf-8", "replace").strip()
            if interpreter not in ALLOWED_INTERPRETERS:
                problems.append(f"{name}: unlisted interpreter {interpreter!r}")
    return problems


def eol_violations(name: str, index_eol: str) -> list[str]:
    """Rule 3, as a function of git's index eol classification."""
    if name.endswith(".sh") and index_eol in ("crlf", "mixed"):
        return [f"{name}: committed blob is {index_eol}"]
    return []


def _git(*args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(_ROOT), *args],
            capture_output=True, timeout=120, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.decode("utf-8", "replace")


class ScriptExecutability(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        listing = _git("ls-files", "-s", "-z")
        if listing is None:
            raise unittest.SkipTest("git is not available; the committed blobs cannot be read")
        cls.entries = []
        for record in listing.split("\0"):
            if not record:
                continue
            meta, name = record.split("\t", 1)
            mode, blob, _stage = meta.split(" ")
            cls.entries.append((mode, blob, name))

    def test_every_executable_is_a_well_formed_script(self) -> None:
        problems: list[str] = []
        for mode, blob, name in self.entries:
            if mode != "100755":
                continue
            raw = subprocess.run(
                ["git", "-C", str(_ROOT), "cat-file", "blob", blob],
                capture_output=True, timeout=120, check=True,
            ).stdout
            problems.extend(shebang_violations(mode, name, raw.split(b"\n", 1)[0]))
        self.assertEqual(problems, [])

    def test_no_shell_script_is_committed_with_crlf(self) -> None:
        listing = _git("ls-files", "--eol", "--", "*.sh")
        if listing is None:
            self.skipTest("git is not available")
        problems: list[str] = []
        for line in listing.splitlines():
            fields = line.split()
            index_eol = fields[0].removeprefix("i/")
            name = line.split("\t", 1)[1]
            problems.extend(eol_violations(name, index_eol))
        self.assertEqual(problems, [])

    def test_direct_path_interpreters_resolve_on_posix_hosts(self) -> None:
        if sys.platform == "win32":
            self.skipTest("interpreter paths are a POSIX question; skipped, not passed")
        missing = [
            interpreter for interpreter in sorted(ALLOWED_INTERPRETERS)
            if interpreter.startswith("/") and " " not in interpreter
            and not Path(interpreter).exists()
        ]
        env_targets = {
            entry.split(" ", 1)[1]
            for entry in ALLOWED_INTERPRETERS if entry.startswith("/usr/bin/env ")
        }
        missing += [t for t in sorted(env_targets) if shutil.which(t) is None]
        self.assertEqual(missing, [], "allowlisted interpreters absent on this host")


class ScriptExecutabilityNegativeControls(unittest.TestCase):
    """Constructed blobs on which each rule MUST fire."""

    def test_an_executable_data_file_fails(self) -> None:
        self.assertEqual(
            shebang_violations("100755", "evidence/x.json", b"{"),
            ["evidence/x.json: executable without a shebang"],
        )

    def test_a_crlf_shebang_fails(self) -> None:
        self.assertEqual(
            shebang_violations("100755", "run.sh", b"#!/usr/bin/bash\r"),
            ["run.sh: the shebang line carries CR"],
        )

    def test_an_unlisted_interpreter_fails(self) -> None:
        problems = shebang_violations("100755", "run.sh", b"#!/usr/local/bin/bash")
        self.assertEqual(
            problems, ["run.sh: unlisted interpreter '/usr/local/bin/bash'"],
        )

    def test_a_crlf_shell_blob_fails(self) -> None:
        self.assertEqual(
            eol_violations("lib.sh", "crlf"), ["lib.sh: committed blob is crlf"],
        )
        self.assertEqual(
            eol_violations("lib.sh", "mixed"), ["lib.sh: committed blob is mixed"],
        )

    def test_a_clean_script_passes(self) -> None:
        self.assertEqual(
            shebang_violations("100755", "ok.sh", b"#!/usr/bin/bash"), [],
        )
        self.assertEqual(eol_violations("ok.sh", "lf"), [])
        # A non-executable module keeps its shebang without being judged by
        # rule 2: it is invoked as `python3 module.py`, and its shebang is
        # documentation.
        self.assertEqual(
            shebang_violations("100644", "module.py", b"#!/anything/at/all"), [],
        )


if __name__ == "__main__":
    unittest.main()
