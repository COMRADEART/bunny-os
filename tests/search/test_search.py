from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from bunny_shell.search import SearchIndex


class SearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.approved = self.root / "approved"
        self.approved.mkdir()
        self.index = SearchIndex(self.root / "config.json", self.root / "index.json")

    def test_only_approved_location_is_indexed(self) -> None:
        (self.approved / "notes.txt").write_text("private content is not indexed", encoding="utf-8")
        (self.root / "outside.txt").write_text("outside", encoding="utf-8")
        self.index.add(str(self.approved))
        self.index.rebuild()
        results = self.index.query("notes")
        self.assertEqual(len(results), 1)
        payload = (self.root / "index.json").read_text(encoding="utf-8")
        self.assertNotIn("private content", payload)
        self.assertNotIn("outside.txt", payload)

    def test_deleted_file_disappears_after_rebuild(self) -> None:
        path = self.approved / "gone.txt"
        path.write_text("x", encoding="utf-8")
        self.index.add(str(self.approved)); self.index.rebuild()
        path.unlink(); self.index.rebuild()
        self.assertEqual(self.index.query("gone"), [])

    def test_remove_deterministically_purges_index(self) -> None:
        (self.approved / "found.txt").write_text("x", encoding="utf-8")
        self.index.add(str(self.approved)); self.index.rebuild()
        self.index.remove(str(self.approved))
        self.assertEqual(self.index.query("found"), [])

    def test_exclusions_and_symlinks(self) -> None:
        ignored = self.approved / "node_modules"
        ignored.mkdir(); (ignored / "secret.js").write_text("x", encoding="utf-8")
        self.index.add(str(self.approved)); self.index.rebuild()
        self.assertEqual(self.index.query("secret"), [])

    def test_home_directory_is_never_a_default_grant(self) -> None:
        with self.assertRaises(ValueError):
            self.index.add(str(Path.home()))


if __name__ == "__main__":
    unittest.main()
