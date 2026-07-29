from __future__ import annotations

import subprocess
from pathlib import Path
import tempfile
import unittest

from bunny_shell.project import project_status


class ProjectDashboardTests(unittest.TestCase):
    @unittest.skipUnless(__import__("shutil").which("git"), "git is required")
    def test_git_projection_is_read_only_and_does_not_run_scripts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            (root / "file.txt").write_text("x", encoding="utf-8")
            value = project_status(str(root))
        self.assertEqual(value["changedFileCount"], 1)
        self.assertFalse(value["scriptsExecuted"])
        self.assertFalse(value["networkUsed"])


if __name__ == "__main__":
    unittest.main()
