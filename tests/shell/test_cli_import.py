# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression test for the ``bunny-settings`` CLI entry point.

The task brief names a "bunny-settings import" break to fix. No break was
found: ``from bunny_shell.cli import main`` succeeds and ``bunny-settings
--help`` exits 0. This test pins that so a future import cycle or a missing
dependency does not silently regress it.

The test imports the CLI module and drives ``--help`` through argparse without
touching a GTK surface. ``argparse`` raises ``SystemExit(0)`` for ``--help``,
which is the expected clean exit.
"""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout


class CliImportTests(unittest.TestCase):
    def test_cli_module_imports_without_gtk(self) -> None:
        from bunny_shell import cli
        self.assertTrue(hasattr(cli, "main"))

    def test_bunny_settings_help_exits_zero(self) -> None:
        from bunny_shell.cli import main
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                main("bunny-settings", ["--help"])
        self.assertEqual(caught.exception.code, 0)

    def test_bunny_settings_section_argument_is_accepted(self) -> None:
        """``--section "Voice & AI"`` parses without error.

        The section value is passed through to the UI surface; we only assert
        that argparse accepts it. We cannot run the GTK surface here (gi is
        not importable on this host), so we stop at parse time by giving a
        subcommand that does not import ui.
        """
        from bunny_shell.cli import main
        # ``schema`` is a subcommand that does not touch GTK; pairing it with
        # --section exercises the parser without spawning a surface. argparse
        # parses --section before the subcommand dispatch.
        with redirect_stdout(io.StringIO()):
            try:
                result = main("bunny-settings", ["--section", "Voice & AI", "schema"])
            except SystemExit as exc:
                # A non-zero SystemExit here would mean argparse rejected the
                # section value; zero or None is the normal path.
                self.assertNotEqual(exc.code, 2, "argparse rejected --section 'Voice & AI'")
            else:
                self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()