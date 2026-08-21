# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""§6: a probe must not alter the state it is measuring.

The principle has a specific history here. Phase 4's process-hygiene audit ran
``sudo -u alex`` to look at a session, and logind built the audit a *fresh user
manager* — ``mpris-proxy``, ``dbus-broker`` — which the next audit then reported
as processes surviving a logout. The instrument created the thing it went on to
find. The measurement was not wrong about what it saw; it was wrong about what
had put it there.

    observe -> record -> grade

not

    probe -> change the system -> observe the changed system

Two tests, at two levels, because either alone is easy to satisfy without the
property holding.

**Behavioural.** Grade a real run directory and compare every byte of the tree
before and after. This catches a write however it arrives — including through a
library the grader did not know it was calling.

**Structural.** Read the grader's own source and refuse the constructs that let
a probe reach out: subprocess, sockets, writes, a clock. This catches the write
that a particular fixture happened not to trigger.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from qualification.grader import grade_run_directory

PACKAGE = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[3]
GRADER_MODULES = ("core.py", "models.py", "rules.py", "__init__.py")


def tree_digest(root: Path) -> dict[str, str]:
    """Every file under ``root``, by relative path, by content digest."""
    digests: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digests[str(path.relative_to(root)).replace(os.sep, "/")] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return digests


class GradingChangesNothingTests(unittest.TestCase):
    """The behavioural half. Bytes in, bytes out, and the tree untouched."""

    def _run_directory(self) -> Path:
        root = Path(self.temporary.name) / "g12-copy"
        root.mkdir(parents=True)
        source = ROOT / "qualification" / "phase4" / "release-candidate" / "g12"
        for name in ("interaction.json", "result.json", "journal-lastboot.log"):
            (root / name).write_bytes((source / name).read_bytes())
        return root

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="bunny-grader-purity-")
        self.addCleanup(self.temporary.cleanup)

    def test_grading_a_run_leaves_its_directory_byte_identical(self) -> None:
        run = self._run_directory()
        before = tree_digest(run)
        grade_run_directory(run, user="alex")
        after = tree_digest(run)
        self.assertEqual(before, after, "grading modified the evidence it was reading")

    def test_grading_creates_no_new_file_anywhere_in_the_tree(self) -> None:
        """Including a result file. A grader that writes its own verdict beside
        the evidence has made the evidence a function of how many times it was
        graded."""
        run = self._run_directory()
        names_before = sorted(p.name for p in run.iterdir())
        grade_run_directory(run, user="alex")
        self.assertEqual(sorted(p.name for p in run.iterdir()), names_before)

    def test_grading_the_committed_evidence_in_place_leaves_it_untouched(self) -> None:
        """The real tree, not a copy.

        This is the one that matters: the recorded fixtures point at
        ``qualification/phase4/`` in place, and every suite run grades it. If
        that were not read-only, running the tests would rewrite an earlier
        phase's immutable evidence.
        """
        run = ROOT / "qualification" / "phase4" / "release-candidate" / "g7"
        before = tree_digest(run)
        grade_run_directory(run, user="alex")
        self.assertEqual(tree_digest(run), before)

    def test_the_verdict_is_the_same_however_many_times_it_is_taken(self) -> None:
        """Determinism, which is what makes a fixture a regression test.

        A grader that consults a clock, a random source or the order of a set
        would drift here without ever writing a file.
        """
        run = self._run_directory()
        verdicts = [
            json.dumps(grade_run_directory(run, user="alex").to_json(), sort_keys=True)
            for _ in range(5)
        ]
        self.assertEqual(len(set(verdicts)), 1, "the grader is not deterministic")


class TheGraderCannotReachOutTests(unittest.TestCase):
    """The structural half, read out of the source with ``ast``.

    A string search would be defeated by ``import subprocess as sp``. Parsing
    the module is what makes this a statement about the code rather than about
    its spelling.
    """

    #: Modules a pure grader has no business importing. ``subprocess`` and
    #: ``socket`` let it reach a machine; ``shutil`` and ``tempfile`` let it
    #: write; ``time``, ``datetime`` and ``random`` make it non-replayable.
    FORBIDDEN_IMPORTS = {
        "subprocess", "socket", "shutil", "tempfile", "random", "time",
        "datetime", "secrets", "urllib", "http", "requests", "sqlite3",
        "multiprocessing", "threading", "asyncio", "ctypes", "signal",
    }

    #: Call names that write or execute, whatever they were imported as.
    FORBIDDEN_CALLS = {
        "system", "popen", "spawn", "spawnv", "execv", "execve", "fork",
        "remove", "unlink", "rmdir", "makedirs", "mkdir", "rename", "replace",
        "chmod", "chown", "write_text", "write_bytes", "touch", "rmtree",
    }

    def modules(self):
        for name in GRADER_MODULES:
            yield name, ast.parse((PACKAGE / name).read_text(encoding="utf-8"))

    def test_no_grader_module_imports_a_way_to_reach_a_machine(self) -> None:
        for name, tree in self.modules():
            imported: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split(".")[0])
            with self.subTest(module=name):
                self.assertEqual(
                    imported & self.FORBIDDEN_IMPORTS,
                    set(),
                    f"{name} imports something a pure grader must not have",
                )

    def test_no_grader_module_calls_anything_that_writes_or_executes(self) -> None:
        for name, tree in self.modules():
            called: set[str] = set()
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                function = node.func
                if isinstance(function, ast.Name):
                    called.add(function.id)
                elif isinstance(function, ast.Attribute):
                    called.add(function.attr)
            with self.subTest(module=name):
                self.assertEqual(
                    called & self.FORBIDDEN_CALLS,
                    set(),
                    f"{name} calls something that writes or executes",
                )

    def test_open_is_never_called_for_writing(self) -> None:
        """``open`` itself is allowed; a write mode is not."""
        for name, tree in self.modules():
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                function = node.func
                is_open = (isinstance(function, ast.Name) and function.id == "open") or (
                    isinstance(function, ast.Attribute) and function.attr == "open"
                )
                if not is_open:
                    continue
                modes = [
                    argument.value
                    for argument in list(node.args)[1:]
                    if isinstance(argument, ast.Constant) and isinstance(argument.value, str)
                ]
                modes += [
                    keyword.value.value
                    for keyword in node.keywords
                    if keyword.arg == "mode"
                    and isinstance(keyword.value, ast.Constant)
                    and isinstance(keyword.value.value, str)
                ]
                for mode in modes:
                    with self.subTest(module=name, mode=mode):
                        self.assertNotIn("w", mode)
                        self.assertNotIn("a", mode)
                        self.assertNotIn("+", mode)

    def test_only_core_touches_the_filesystem_at_all(self) -> None:
        """One reading entry point, so §6 is a property of a file rather than a habit."""
        for name in ("models.py", "rules.py"):
            source = (PACKAGE / name).read_text(encoding="utf-8")
            with self.subTest(module=name):
                for reader in ("read_text", "read_bytes", "iterdir", "rglob", "glob", "open("):
                    self.assertNotIn(reader, source, f"{name} reads the filesystem; only core.py may")


class TheGraderNeedsNoLiveMachineTests(unittest.TestCase):
    """§4: "Do not make the grader dependent on a live VM unless absolutely necessary."

    It is not necessary. Extraction needs ``guestfish``, ``qemu-img`` and
    ``journalctl``; grading needs a directory. Keeping the two apart is what
    lets the whole fixture suite run on a laptop with none of them installed.
    """

    def test_no_grader_module_names_a_virtualisation_tool(self) -> None:
        for name in GRADER_MODULES:
            source = (PACKAGE / name).read_text(encoding="utf-8")
            body = "\n".join(
                line for line in source.splitlines() if not line.lstrip().startswith("#")
            )
            for tool in ("qemu-img", "guestfish", "qemu-system", "virsh", "ssh "):
                with self.subTest(module=name, tool=tool):
                    # Prose may mention them; a call may not. The check is on
                    # the parsed constants, not on the file's words.
                    tree = ast.parse(source)
                    constants = [
                        node.value
                        for node in ast.walk(tree)
                        if isinstance(node, ast.Constant) and isinstance(node.value, str)
                    ]
                    executable_constants = [
                        value for value in constants if "\n" not in value and len(value) < 200
                    ]
                    self.assertFalse(
                        any(value.strip() == tool.strip() for value in executable_constants),
                        f"{name} names {tool} as a value",
                    )
            del body


if __name__ == "__main__":
    unittest.main()
