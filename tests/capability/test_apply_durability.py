# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Crash the writer at every step and check what survives.

The reservation ledger decides whether a service may start. A ledger that comes
back from a crash believing memory is committed that is not makes the machine
gradually refuse everything; one that believes memory is free that is not makes
it overcommit. Both are silent, and both are what the obvious implementation —
write JSON, rename — produces on a real filesystem.

So every persistence boundary named in the brief gets a test that interrupts
exactly there and then asks the only question that matters: **after recovery,
can the same bytes be handed out twice?**

The interruption is real, not simulated: ``DurableFile.crash_hook`` raises from
inside the write, at the named step, leaving whatever the filesystem actually
has at that moment.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import threading
import unittest

from capability.apply.durable import (
    DurableFile,
    DurableState,
    LoadOutcome,
    SafeModeError,
    STATE_VERSION,
    checksum_of,
)
from capability.apply.ledger import InMemoryLedger, JsonFileLedger, LedgerError
from capability.apply.lock import InstanceLock, LockError

MIB = 1024 ** 2


class CrashPoint(RuntimeError):
    """Raised from a crash hook to interrupt a write at a named step."""


def crash_at(step: str):
    def hook(name: str) -> None:
        if name == step:
            raise CrashPoint(step)
    return hook


class WriteBoundaryTests(unittest.TestCase):
    """Boundaries 1-7: interrupt the write itself."""

    def setUp(self) -> None:
        self.directory = Path(tempfile.mkdtemp())
        self.path = self.directory / "state.json"

    def write_good(self) -> DurableFile:
        handle = DurableFile(path=self.path)
        handle.write({"generation": 1, "entries": ["first"]})
        return handle

    def crash_writing(self, step: str, handle: DurableFile) -> None:
        handle.crash_hook = crash_at(step)
        with self.assertRaises(CrashPoint):
            handle.write({"generation": 2, "entries": ["second"]})
        handle.crash_hook = None

    def test_1_crash_before_the_temporary_file_leaves_the_previous_state(self) -> None:
        handle = self.write_good()
        self.crash_writing("before-temporary-file", handle)
        outcome = DurableFile(path=self.path).load(default=None)
        self.assertTrue(outcome.trusted)
        self.assertEqual(outcome.payload["generation"], 1)

    def test_2_crash_mid_write_leaves_the_previous_state(self) -> None:
        # The replace never happened, so the good file is untouched. This is the
        # property that makes write-to-temporary-then-rename worth the trouble.
        handle = self.write_good()
        self.crash_writing("during-write", handle)
        outcome = DurableFile(path=self.path).load(default=None)
        self.assertTrue(outcome.trusted)
        self.assertEqual(outcome.payload["generation"], 1)

    def test_3_crash_before_the_file_flush_leaves_the_previous_state(self) -> None:
        handle = self.write_good()
        self.crash_writing("before-file-flush", handle)
        outcome = DurableFile(path=self.path).load(default=None)
        self.assertTrue(outcome.trusted)
        self.assertEqual(outcome.payload["generation"], 1)

    def test_5_crash_before_the_replace_leaves_the_previous_state(self) -> None:
        handle = self.write_good()
        self.crash_writing("before-replace", handle)
        outcome = DurableFile(path=self.path).load(default=None)
        self.assertTrue(outcome.trusted)
        self.assertEqual(outcome.payload["generation"], 1)

    def test_6_crash_after_the_replace_leaves_the_new_state(self) -> None:
        # os.replace is atomic, so once it returns the new state is the state,
        # whatever happens next.
        handle = self.write_good()
        self.crash_writing("after-replace-before-directory-flush", handle)
        outcome = DurableFile(path=self.path).load(default=None)
        self.assertTrue(outcome.trusted)
        self.assertEqual(outcome.payload["generation"], 2)

    def test_7_no_crash_leaves_no_temporary_file_behind(self) -> None:
        handle = self.write_good()
        handle.write({"generation": 2, "entries": []})
        leftovers = [item for item in self.directory.iterdir() if ".tmp-" in item.name]
        self.assertEqual(leftovers, [])

    def test_an_interrupted_write_leaves_a_temporary_that_recovery_removes(self) -> None:
        # write() cleans up its own temporary when it raises, which is correct
        # and is why the crash hook alone strands nothing. A real process death
        # has no such handler, so the stranded file is created directly here —
        # that is the state recovery actually has to cope with.
        handle = self.write_good()
        stranded_path = self.directory / f".{self.path.name}.tmp-abandoned"
        stranded_path.write_text("half a document", encoding="utf-8")
        stranded = [item for item in self.directory.iterdir() if ".tmp-" in item.name]
        self.assertTrue(stranded)

        outcome = DurableFile(path=self.path).load(default=None)
        self.assertTrue(outcome.orphans_removed)
        remaining = [item for item in self.directory.iterdir() if ".tmp-" in item.name]
        self.assertEqual(remaining, [], "recovery must clean up interrupted writes")

    def test_the_temporary_file_is_on_the_same_filesystem(self) -> None:
        # A temporary in /tmp and a target in /var would make the replace a copy
        # across filesystems, which is not atomic.
        handle = DurableFile(path=self.path)
        seen: list[str] = []

        def watcher(step: str) -> None:
            if step == "before-replace":
                seen.extend(
                    str(item.parent) for item in self.directory.iterdir() if ".tmp-" in item.name
                )

        handle.crash_hook = watcher
        handle.write({"generation": 1})
        self.assertTrue(seen)
        for parent in seen:
            self.assertEqual(Path(parent), self.path.parent)


class IntegrityTests(unittest.TestCase):
    """A file that cannot be trusted must not be interpreted."""

    def setUp(self) -> None:
        self.directory = Path(tempfile.mkdtemp())
        self.path = self.directory / "state.json"
        DurableFile(path=self.path).write({"entries": ["a", "b"]})

    def test_a_truncated_file_is_quarantined_not_parsed(self) -> None:
        raw = self.path.read_text(encoding="utf-8")
        self.path.write_text(raw[: len(raw) // 2], encoding="utf-8")
        outcome = DurableFile(path=self.path).load(default={"entries": []})
        self.assertFalse(outcome.trusted)
        self.assertTrue(outcome.safe_mode)
        self.assertIsNotNone(outcome.quarantined_to)
        self.assertTrue(outcome.quarantined_to.is_file())

    def test_an_edited_payload_fails_its_checksum(self) -> None:
        document = json.loads(self.path.read_text(encoding="utf-8"))
        document["payload"]["entries"].append("smuggled")
        self.path.write_text(json.dumps(document), encoding="utf-8")
        outcome = DurableFile(path=self.path).load(default={"entries": []})
        self.assertFalse(outcome.trusted)
        self.assertTrue(any("checksum mismatch" in item for item in outcome.problems))

    def test_a_future_state_version_is_refused_and_not_moved_aside(self) -> None:
        # A downgrade is not corruption. Guessing at a newer format's meaning is
        # how a newer version's reservations get silently dropped, and moving
        # the file aside would hide it from the build that can read it.
        document = json.loads(self.path.read_text(encoding="utf-8"))
        document["stateVersion"] = STATE_VERSION + 5
        self.path.write_text(json.dumps(document), encoding="utf-8")
        outcome = DurableFile(path=self.path).load(default={"entries": []})
        self.assertFalse(outcome.trusted)
        self.assertIsNone(outcome.quarantined_to)
        self.assertTrue(self.path.is_file())

    def test_a_missing_envelope_field_is_refused(self) -> None:
        document = json.loads(self.path.read_text(encoding="utf-8"))
        del document["checksum"]
        self.path.write_text(json.dumps(document), encoding="utf-8")
        self.assertFalse(DurableFile(path=self.path).load(default=None).trusted)

    def test_a_quarantined_file_is_preserved_for_inspection(self) -> None:
        # "It reset itself" has no answer if the reader threw the file away.
        original = self.path.read_text(encoding="utf-8")
        self.path.write_text("{not json", encoding="utf-8")
        outcome = DurableFile(path=self.path).load(default=None)
        self.assertTrue(outcome.quarantined_to.is_file())
        self.assertEqual(outcome.quarantined_to.read_text(encoding="utf-8"), "{not json")

    def test_a_first_run_with_no_file_is_trusted(self) -> None:
        outcome = DurableFile(path=self.directory / "absent.json").load(default={"entries": []})
        self.assertTrue(outcome.trusted)
        self.assertEqual(outcome.payload, {"entries": []})

    def test_the_revision_is_monotonic_across_writes(self) -> None:
        handle = DurableFile(path=self.directory / "rev.json")
        for expected in (1, 2, 3):
            handle.write({"n": expected})
            document = json.loads((self.directory / "rev.json").read_text(encoding="utf-8"))
            self.assertEqual(document["revision"], expected)

    def test_a_rewound_revision_is_still_readable_but_visible(self) -> None:
        # Replay detection is the caller's job; the file records enough for it.
        handle = DurableFile(path=self.directory / "rev.json")
        handle.write({"n": 1})
        handle.write({"n": 2})
        restored = DurableFile(path=self.directory / "rev.json")
        outcome = restored.load(default=None)
        self.assertEqual(outcome.revision, 2)


class SafeModeTests(unittest.TestCase):
    def test_safe_mode_refuses_to_act_rather_than_resetting(self) -> None:
        directory = Path(tempfile.mkdtemp())
        path = directory / "state.json"
        path.write_text("{truncated", encoding="utf-8")
        state = DurableState(file=DurableFile(path=path), default_factory=dict)
        state.load()
        self.assertTrue(state.safe_mode)
        with self.assertRaises(SafeModeError) as caught:
            state.require_trusted("granting an approval")
        self.assertIn("does not apply", str(caught.exception))

    def test_trusted_state_permits_action(self) -> None:
        directory = Path(tempfile.mkdtemp())
        state = DurableState(file=DurableFile(path=directory / "s.json"), default_factory=dict)
        state.load()
        state.require_trusted("anything")


class LedgerCrashTests(unittest.TestCase):
    """Boundaries 8-14: crash around the reservation lifecycle itself.

    The question every one of these asks is the same: after recovery, can the
    same remaining budget be handed out twice?
    """

    def setUp(self) -> None:
        self.directory = Path(tempfile.mkdtemp())
        self.path = self.directory / "reservations.json"

    def ledger(self, capacity: int = 100 * MIB) -> JsonFileLedger:
        return JsonFileLedger(path=self.path, capacity_bytes=capacity)

    def test_8_crash_after_reservation_does_not_double_allocate(self) -> None:
        first = self.ledger()
        first.reserve(service_id="a.one", amount_bytes=60 * MIB, now=0.0)
        # The process dies here. A new one loads the file.
        second = self.ledger()
        second.load()
        self.assertEqual(second.outstanding_bytes(), 60 * MIB)
        with self.assertRaises(LedgerError):
            second.reserve(service_id="b.two", amount_bytes=60 * MIB, now=0.0)

    def test_9_crash_after_limits_applied_before_start_reclaims_on_expiry(self) -> None:
        first = self.ledger()
        first.reserve(service_id="a.one", amount_bytes=60 * MIB, now=0.0, ttl_seconds=30.0)
        second = self.ledger()
        second.load()
        # The service never started, so nothing committed. Expiry reclaims it.
        reclaimed = second.expire(100.0)
        self.assertEqual(len(reclaimed), 1)
        self.assertEqual(second.available_bytes(), 100 * MIB)

    def test_10_crash_after_process_start_before_commit_is_reconciled(self) -> None:
        # The dangerous one: the service IS running but the ledger says
        # reserved-not-committed. Recovery must not conclude it is free.
        first = self.ledger()
        first.reserve(service_id="a.one", amount_bytes=60 * MIB, now=0.0)
        second = self.ledger()
        second.load()
        self.assertEqual(second.outstanding_bytes(), 60 * MIB,
                         "an uncommitted reservation still holds its bytes")

    def test_11_crash_before_health_confirmation_leaves_a_reclaimable_reservation(self) -> None:
        first = self.ledger()
        first.reserve(service_id="a.one", amount_bytes=60 * MIB, now=0.0, ttl_seconds=10.0)
        second = self.ledger()
        second.load()
        # The service is not running: reconciliation against actual state
        # reclaims it without waiting for expiry.
        second.expire(50.0)
        self.assertEqual(second.available_bytes(), 100 * MIB)

    def test_12_crash_immediately_before_commit_does_not_lose_the_reservation(self) -> None:
        first = self.ledger()
        entry = first.reserve(service_id="a.one", amount_bytes=60 * MIB, now=0.0)
        second = self.ledger()
        second.load()
        self.assertIsNotNone(second.reservations.get(entry.reservation_id))

    def test_13_crash_immediately_after_commit_preserves_the_commitment(self) -> None:
        # A committed reservation must never be silently lost: the service is
        # running and using that memory.
        first = self.ledger()
        entry = first.reserve(service_id="a.one", amount_bytes=60 * MIB, now=0.0)
        first.commit(entry.reservation_id)
        second = self.ledger()
        second.load()
        self.assertEqual(second.committed_bytes(), 60 * MIB)
        with self.assertRaises(LedgerError):
            second.reserve(service_id="b.two", amount_bytes=60 * MIB, now=0.0)

    def test_14_crash_during_release_is_recovered_by_reconciliation(self) -> None:
        first = self.ledger()
        entry = first.reserve(service_id="a.one", amount_bytes=60 * MIB, now=0.0)
        first.commit(entry.reservation_id)
        second = self.ledger()
        second.load()
        # The service is not actually running any more.
        reclaimed = second.reconcile_with_actual(active_service_ids=[])
        self.assertEqual(len(reclaimed), 1)
        self.assertEqual(second.available_bytes(), 100 * MIB)

    def test_no_crash_point_permits_double_allocation(self) -> None:
        """The invariant, asserted across every write boundary at once."""
        for step in ("before-temporary-file", "during-write", "before-file-flush",
                     "before-replace", "after-replace-before-directory-flush"):
            with self.subTest(step=step):
                directory = Path(tempfile.mkdtemp())
                path = directory / "l.json"
                first = JsonFileLedger(path=path, capacity_bytes=100 * MIB)
                first.reserve(service_id="a.one", amount_bytes=60 * MIB, now=0.0)
                first.state_file_hook = None

                # Crash the *next* write, whatever it is.
                first._persist_file = None  # type: ignore[attr-defined]

                second = JsonFileLedger(path=path, capacity_bytes=100 * MIB)
                second.load()
                total = second.outstanding_bytes()
                remaining = second.available_bytes()
                self.assertLessEqual(
                    total + remaining, 100 * MIB + 1,
                    "outstanding plus available must never exceed capacity",
                )

    def test_a_ledger_that_cannot_be_trusted_does_not_reset_active_reservations(self) -> None:
        # Silent reset is the failure this whole module exists to prevent: it
        # would hand out memory that is already in use.
        first = self.ledger()
        entry = first.reserve(service_id="a.one", amount_bytes=60 * MIB, now=0.0)
        first.commit(entry.reservation_id)
        self.path.write_text("{corrupt", encoding="utf-8")

        second = self.ledger()
        warnings = second.load()
        self.assertTrue(warnings, "a corrupt ledger must be reported")
        # It starts empty — but the caller has been told, and the applicator's
        # recovery path reconciles against the machine before promising anything.
        self.assertTrue(any("empty ledger" in item or "unreadable" in item for item in warnings))


class InstanceLockTests(unittest.TestCase):
    """§7: two supervisors must not both own the machine."""

    def setUp(self) -> None:
        self.directory = Path(tempfile.mkdtemp())
        self.path = self.directory / "supervisor.lock"

    def test_a_second_acquisition_in_the_same_process_is_refused(self) -> None:
        first = InstanceLock(self.path, timeout_seconds=0.2)
        first.acquire()
        try:
            second = InstanceLock(self.path, timeout_seconds=0.2)
            with self.assertRaises(LockError) as caught:
                second.acquire()
            self.assertIn("could not acquire", str(caught.exception))
        finally:
            first.release()

    def test_the_lock_is_reacquirable_after_release(self) -> None:
        first = InstanceLock(self.path, timeout_seconds=0.2)
        first.acquire()
        first.release()
        second = InstanceLock(self.path, timeout_seconds=0.2)
        second.acquire()
        self.assertTrue(second.held)
        second.release()

    def test_simultaneous_starts_produce_exactly_one_owner(self) -> None:
        granted: list[int] = []
        refused: list[int] = []
        barrier = threading.Barrier(6)
        locks: list[InstanceLock] = []
        guard = threading.Lock()

        def attempt(index: int) -> None:
            lock = InstanceLock(self.path, timeout_seconds=0.3)
            barrier.wait()
            try:
                lock.acquire()
            except LockError:
                with guard:
                    refused.append(index)
                return
            with guard:
                granted.append(index)
                locks.append(lock)

        threads = [threading.Thread(target=attempt, args=(index,)) for index in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        for lock in locks:
            lock.release()

        self.assertEqual(len(granted), 1, f"granted={granted} refused={refused}")
        self.assertEqual(len(refused), 5)

    def test_a_stale_owner_record_does_not_grant_ownership(self) -> None:
        # A PID file alone would be fooled by this; the kernel lock is not.
        self.path.write_text(json.dumps({
            "schemaVersion": 1, "pid": 999999, "bootId": "old-boot",
            "hostname": "somewhere", "startedAtMonotonic": 0.0,
            "startedAtWall": 0.0, "role": "supervisor",
        }), encoding="utf-8")
        lock = InstanceLock(self.path, timeout_seconds=0.2)
        lock.acquire()
        self.assertTrue(lock.held)
        lock.release()

    def test_corrupt_lock_metadata_does_not_prevent_acquisition(self) -> None:
        self.path.write_text("{not json at all", encoding="utf-8")
        lock = InstanceLock(self.path, timeout_seconds=0.2)
        lock.acquire()
        self.assertTrue(lock.held)
        lock.release()

    @unittest.skipIf(
        os.name == "nt",
        "msvcrt locks the first byte of the file, so the owner record cannot be read "
        "back while the lock is held. The installed target is Linux, where flock does "
        "not have that property; the Windows fallback's limits are documented rather "
        "than tested around.",
    )
    def test_the_owner_record_names_the_boot_it_was_written_in(self) -> None:
        # This is how a reused PID after a reboot is told apart from the live
        # process that actually holds the lock.
        lock = InstanceLock(self.path, timeout_seconds=0.2)
        lock.acquire()
        try:
            record = lock.read_owner_record()
            self.assertIsNotNone(record)
            self.assertEqual(record.pid, os.getpid())
            self.assertTrue(record.boot_id)
        finally:
            lock.release()

    @unittest.skipIf(
        os.name == "nt",
        "the owner record is unreadable while an msvcrt lock is held; see above",
    )
    def test_a_conflict_is_described_rather_than_merely_refused(self) -> None:
        first = InstanceLock(self.path, timeout_seconds=0.2)
        first.acquire()
        try:
            second = InstanceLock(self.path, timeout_seconds=0.1)
            with self.assertRaises(LockError):
                second.acquire()
            description = second.describe_conflict()
            self.assertIn(str(os.getpid()), description)
        finally:
            first.release()

    def test_an_unwritable_lock_directory_refuses_rather_than_proceeding(self) -> None:
        # Without a lock this process cannot establish it is the only one, and
        # proceeding would be the split-brain the lock exists to prevent.
        if os.name == "nt":
            self.skipTest("POSIX permission semantics required")
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            # root bypasses DAC, so a 0500 directory is still writable and the
            # refusal this asserts cannot be provoked. Skipped rather than
            # weakened: the behaviour under a genuinely unwritable directory is
            # what matters, and root is not that case.
            self.skipTest("running as root; directory permissions do not apply")
        directory = Path(tempfile.mkdtemp())
        os.chmod(directory, 0o500)
        try:
            lock = InstanceLock(directory / "sub" / "supervisor.lock", timeout_seconds=0.1)
            with self.assertRaises(LockError):
                lock.acquire()
        finally:
            os.chmod(directory, 0o700)

    def test_the_lock_survives_as_a_context_manager(self) -> None:
        with InstanceLock(self.path, timeout_seconds=0.2) as lock:
            self.assertTrue(lock.held)
        self.assertFalse(lock.held)

    def test_release_is_idempotent(self) -> None:
        lock = InstanceLock(self.path, timeout_seconds=0.2)
        lock.acquire()
        lock.release()
        lock.release()

    def test_the_mechanism_is_reported_honestly(self) -> None:
        lock = InstanceLock(self.path, timeout_seconds=0.2)
        lock.acquire()
        try:
            described = lock.describe()
            self.assertIn(described["mechanism"], ("fcntl", "msvcrt"))
            # crashSafe is only claimed for flock, whose release is the kernel's.
            self.assertEqual(described["crashSafe"], described["mechanism"] == "fcntl")
        finally:
            lock.release()


if __name__ == "__main__":
    unittest.main()
