from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from installer.backend.transaction_journal import InstallationTransactionJournal, JournalOperation


NOW = datetime(2026, 7, 29, tzinfo=timezone.utc)


class InstallerJournalTests(unittest.TestCase):
    def test_full_non_destructive_lifecycle(self) -> None:
        operation = JournalOperation("probe", "Probe disks", False, True)
        for state in ("planned", "validated", "started", "completed"):
            operation.transition(state, timestamp=NOW)
        self.assertEqual(operation.state, "completed")
        self.assertFalse(operation.can_resume)

    def test_skip_validation_is_rejected(self) -> None:
        operation = JournalOperation("partition", "Partition", True, False)
        with self.assertRaises(ValueError):
            operation.transition("started")

    def test_destructive_failure_is_not_resumable(self) -> None:
        operation = JournalOperation("partition", "Partition", True, True)
        for state in ("planned", "validated", "started", "failed"):
            operation.transition(state, timestamp=NOW)
        self.assertFalse(operation.can_resume)

    def test_failed_operation_cannot_claim_completion(self) -> None:
        operation = JournalOperation("deploy", "Deploy", False, True)
        operation.transition("planned", timestamp=NOW)
        operation.transition("failed", timestamp=NOW)
        with self.assertRaises(ValueError):
            operation.transition("completed")

    def test_export_states_no_rollback_after_write(self) -> None:
        journal = InstallationTransactionJournal("install-1", [JournalOperation("partition", "Partition", True, False)])
        self.assertFalse(journal.export()["rollbackAfterDestructiveWrite"])

    def test_export_redacts_detail(self) -> None:
        operation = JournalOperation("user", "Create user", False, True)
        operation.transition("planned", detail="email a@example.org", timestamp=NOW)
        journal = InstallationTransactionJournal("install-1", [operation])
        self.assertNotIn("a@example.org", str(journal.export()))

    def test_journal_write_is_atomic_shape(self) -> None:
        journal = InstallationTransactionJournal("install-1", [JournalOperation("probe", "Probe", False, True)])
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "journal.json"
            journal.write(path)
            self.assertIn('"schemaVersion": 1', path.read_text(encoding="utf-8"))

    def test_duplicate_operations_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            InstallationTransactionJournal("id", [JournalOperation("x", "a", False, True), JournalOperation("x", "b", False, True)])


if __name__ == "__main__":
    unittest.main()
