from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from bunny_shell.workspaces import WorkspaceStore, _assert_no_secrets


class WorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.store = WorkspaceStore(self.root / "workspaces.json")

    def test_create_rename_archive_restore_and_persist(self) -> None:
        created = self.store.create("Project", str(self.project))
        renamed = self.store.rename(created["id"], "Project two")
        self.assertEqual(renamed["name"], "Project two")
        self.store.archive(created["id"])
        self.assertEqual(self.store.list(), [])
        self.store.restore(created["id"])
        self.assertEqual(len(WorkspaceStore(self.root / "workspaces.json").list()), 1)

    def test_duplicate_has_new_identity(self) -> None:
        original = self.store.create("One")
        duplicate = self.store.duplicate(original["id"])
        self.assertNotEqual(original["id"], duplicate["id"])

    def test_detach_does_not_delete_project(self) -> None:
        workspace = self.store.create("One", str(self.project))
        self.store.detach_project(workspace["id"])
        self.assertTrue(self.project.is_dir())

    def test_rejects_credentials(self) -> None:
        with self.assertRaises(ValueError):
            _assert_no_secrets({"providerToken": "secret"})

    def test_rejects_cross_user_shaped_id(self) -> None:
        with self.assertRaises(ValueError):
            self.store.rename("../../other-user", "Bad")


if __name__ == "__main__":
    unittest.main()
