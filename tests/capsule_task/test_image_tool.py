# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The program that runs inside the capsule, checked from outside it.

Two kinds of assertion here, and the split matters.

**Structural**, which run everywhere: the program imports nothing of Bunny's,
refuses paths outside the sandbox, refuses widths outside its own bounds, and is
installed at the path the catalogue entry names. Each of these fails into
something that would only be discovered on a machine where the sandbox worked,
which is the worst place to discover it.

**Behavioural**, which need GdkPixbuf and skip without it: given a real PNG it
writes a real, smaller PNG. That runs on the Linux qualification host and in the
guest, and is skipped on a Windows developer machine rather than replaced by a
weaker check that would pass there.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests.support import ROOT

TOOL = ROOT / "scripts" / "bunny-image-tool.py"


def _load():
    specification = importlib.util.spec_from_file_location("bunny_image_tool", TOOL)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _pixbuf_available() -> bool:
    try:
        import gi  # type: ignore

        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


class TheProgramIsStandalone(unittest.TestCase):
    def test_it_imports_nothing_of_bunnys(self) -> None:
        """A capsule puts no Bunny code on its process's import path. A program
        that imported the Companion could not run in the sandbox it exists for,
        and the ImportError would only appear where the sandbox worked."""
        source = TOOL.read_text(encoding="utf-8")
        for forbidden in ("import companion", "import trust", "import capsules",
                          "from companion", "from trust", "from capsules"):
            self.assertNotIn(forbidden, source, forbidden)

    def test_it_lives_where_the_catalogue_entry_says(self) -> None:
        """A catalogue entry naming a path no route installs is an operation
        that cannot start on a real machine."""
        import json

        sys.path.insert(0, str(ROOT / "build" / "scripts"))
        try:
            import install_routes
        finally:
            sys.path.pop(0)
        destinations = {route.destination for route in install_routes.INSTALL_ROUTES}
        entries = json.loads((ROOT / "catalog/data/images.json").read_text(encoding="utf-8"))
        entry = next(
            item for item in entries["entries"] if item["entryId"] == "bunny-image-tool"
        )
        self.assertIn(entry["packageReference"], destinations)
        self.assertEqual(entry["networkCeiling"], "none")

    def test_the_bounds_are_stated_twice_on_purpose(self) -> None:
        """The operation table validates, and so does the program. Two
        independent checks, because the program runs where the table is not
        importable and a check that depends on an absent import is not a check."""
        from companion.capsule_tasks import OPERATIONS

        module = _load()
        self.assertEqual(module._MIN_PIXELS, 16)
        self.assertEqual(module._MAX_PIXELS, 16384)
        # The same numbers the table enforces, reached from the other side.
        OPERATIONS["image.resize"].validate({"width": module._MIN_PIXELS})
        OPERATIONS["image.resize"].validate({"width": module._MAX_PIXELS})


class TheProgramRefusesBadInput(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load()

    def _run(self, **overrides) -> tuple[int, str]:
        """The exit code *and* what it said.

        Asserting only the code is how these four tests first passed on a
        Windows developer machine for entirely the wrong reason: the containment
        check went through ``pathlib.Path``, which rewrote the separators, so
        every path was "outside the sandbox" and a bad width was never reached.
        The reason is the assertion.
        """
        import contextlib
        import io

        arguments = {
            "--input": "/run/bunny/files/abc/holiday.png",
            "--output": "/run/bunny/app/exports/holiday-resized.png",
            "--width": "1024",
        }
        arguments.update(overrides)
        argv = ["resize"]
        for key, value in arguments.items():
            argv += [key, value]
        captured = io.StringIO()
        with contextlib.redirect_stderr(captured):
            code = self.module.main(argv)
        return code, captured.getvalue()

    def test_an_input_outside_the_sandbox_is_refused(self) -> None:
        code, said = self._run(**{"--input": "/home/bunny/Pictures/holiday.png"})
        self.assertEqual(code, 2)
        self.assertIn("input path is outside", said)

    def test_a_traversal_out_of_the_sandbox_is_refused(self) -> None:
        code, said = self._run(**{"--input": "/run/bunny/app/data/../../../etc/passwd"})
        self.assertEqual(code, 2)
        self.assertIn("input path is outside", said)

    def test_an_output_outside_the_sandbox_is_refused(self) -> None:
        code, said = self._run(**{"--output": "/home/bunny/Pictures/out.png"})
        self.assertEqual(code, 2)
        self.assertIn("output path is outside", said)

    def test_a_width_below_the_floor_is_refused_for_being_a_width(self) -> None:
        code, said = self._run(**{"--width": "8"})
        self.assertEqual(code, 2)
        self.assertIn("width must be between", said)

    def test_a_width_above_the_ceiling_is_refused_for_being_a_width(self) -> None:
        code, said = self._run(**{"--width": "99999"})
        self.assertEqual(code, 2)
        self.assertIn("width must be between", said)

    def test_a_sandbox_path_that_does_not_exist_reaches_the_file_check(self) -> None:
        """The positive control for the four above: a well-formed sandbox path
        and a valid width get past both checks and fail on the file instead."""
        code, said = self._run()
        self.assertEqual(code, 2)
        self.assertIn("not a file this app can see", said)

    def test_it_has_no_shell_and_no_eval(self) -> None:
        source = TOOL.read_text(encoding="utf-8")
        for forbidden in ("os.system", "subprocess", "eval(", "exec(", "shell=True"):
            self.assertNotIn(forbidden, source, forbidden)


@unittest.skipUnless(_pixbuf_available(), "GdkPixbuf is not available on this machine")
class TheProgramActuallyResizes(unittest.TestCase):
    """Runs on the Linux qualification host and in the guest. Skipped, not
    weakened, where the library is absent."""

    def setUp(self) -> None:
        import gi

        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf

        self.GdkPixbuf = GdkPixbuf
        self.directory = Path(tempfile.mkdtemp())
        self.source = self.directory / "holiday.png"
        pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 400, 200)
        pixbuf.fill(0x3366CCFF)
        pixbuf.savev(str(self.source), "png", [], [])

    def test_it_writes_a_smaller_image_and_keeps_the_ratio(self) -> None:
        module = _load()
        output = self.directory / "holiday-resized.png"
        code = module.resize(self.source, output, 100)
        self.assertEqual(code, 0)
        self.assertTrue(output.is_file())
        result = self.GdkPixbuf.Pixbuf.new_from_file(str(output))
        self.assertEqual(result.get_width(), 100)
        self.assertEqual(result.get_height(), 50)

    def test_the_original_is_not_touched(self) -> None:
        before = self.source.read_bytes()
        _load().resize(self.source, self.directory / "out.png", 100)
        self.assertEqual(self.source.read_bytes(), before)

    def test_the_same_input_and_width_produce_the_same_bytes(self) -> None:
        """The compression level is pinned, so a digest comparison across two
        qualification runs compares the resize rather than a library default."""
        module = _load()
        first, second = self.directory / "a.png", self.directory / "b.png"
        module.resize(self.source, first, 120)
        module.resize(self.source, second, 120)
        self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_it_refuses_to_overwrite_an_existing_output(self) -> None:
        output = self.directory / "taken.png"
        output.write_bytes(b"already here")
        self.assertEqual(
            _load().main([
                "resize", "--input", str(self.source), "--output", str(output), "--width", "100",
            ]),
            2,
        )
        self.assertEqual(output.read_bytes(), b"already here")


if __name__ == "__main__":
    unittest.main()
