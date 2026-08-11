# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What a copy is allowed to move, asserted so it cannot quietly grow again.

An operations script copied the whole repository — including tens of gigabytes
of generated images under ``build/out`` — into a work directory three times, and
filled the WSL virtual disk until the distribution remounted read-only. Every
command then failed with an I/O error, which reads like hardware trouble and is
not.

Two things are asserted here, and they are different:

* **the container build context** already excluded the large trees. That was
  never the problem, and this locks it in so a new generated directory has to be
  added to ``.containerignore`` deliberately;
* **the size guard** refuses a copy an order of magnitude larger than a source
  tree, with a positive control proving it can still say no.

The guard has no allowlist. The failure mode was somebody creating a directory
nobody had thought about, and an allowlist would not have known about that one
either.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

from tests.support import ROOT

GUARD = ROOT / "scripts" / "check-copy-size.py"


def _load():
    specification = importlib.util.spec_from_file_location("check_copy_size", GUARD)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


class TheBuildContextExcludesGeneratedTrees(unittest.TestCase):
    def setUp(self) -> None:
        self.rules = {
            line.strip()
            for line in (ROOT / ".containerignore").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        }

    def test_the_known_large_trees_are_excluded(self) -> None:
        for tree in ("build/out", ".git", "node_modules"):
            with self.subTest(tree=tree):
                self.assertIn(tree, self.rules)

    def test_the_file_was_actually_read(self) -> None:
        """A rule set that parsed to nothing would pass every check above."""
        self.assertGreater(len(self.rules), 4, self.rules)


class TheSizeGuardRefuses(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load()

    def _tree(self, sizes: dict[str, int]) -> Path:
        import tempfile

        base = Path(tempfile.mkdtemp())
        for relative, size in sizes.items():
            path = base / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x" * size)
        return base

    def test_a_source_sized_tree_passes(self) -> None:
        base = self._tree({"companion/runtime.py": 4096, "docs/readme.md": 512})
        self.assertEqual(self.module.main([str(base), "--limit-mb", "1", "--quiet"]), 0)

    def test_an_oversized_tree_is_refused(self) -> None:
        """The positive control. A guard that never refuses is not a guard."""
        base = self._tree({"assets/big.bin": 3 * 1024 * 1024})
        self.assertEqual(self.module.main([str(base), "--limit-mb", "1", "--quiet"]), 2)

    def test_the_generated_trees_are_excluded_by_default(self) -> None:
        """The exact shape of the incident: the source is small and the copy was
        enormous because of one generated directory."""
        base = self._tree({
            "companion/runtime.py": 4096,
            "build/out/image.qcow2": 3 * 1024 * 1024,
            "node_modules/pkg/index.js": 3 * 1024 * 1024,
        })
        self.assertEqual(self.module.main([str(base), "--limit-mb", "1", "--quiet"]), 0)

    def test_a_missing_source_is_its_own_exit_code(self) -> None:
        self.assertEqual(self.module.main(["/nonexistent/tree", "--quiet"]), 3)

    def test_it_is_installed_or_deliberately_not(self) -> None:
        """This is developer tooling and does not belong in the image. Asserted
        so that adding it to the install routes is a decision rather than an
        accident — a size guard on a running Bunny OS protects nothing."""
        import sys

        sys.path.insert(0, str(ROOT / "build" / "scripts"))
        try:
            import install_routes
        finally:
            sys.path.pop(0)
        sources = {route.source for route in install_routes.INSTALL_ROUTES}
        self.assertNotIn("scripts/check-copy-size.py", sources)


if __name__ == "__main__":
    unittest.main()
