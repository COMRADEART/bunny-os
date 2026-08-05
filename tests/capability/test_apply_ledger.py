# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The reservation ledger: atomicity, idempotency, expiry and recovery."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import threading
import unittest

from capability.apply.ledger import (
    DEFAULT_RESERVATION_TTL_SECONDS,
    InMemoryLedger,
    JsonFileLedger,
    LedgerError,
    LedgerInvariantError,
    Reservation,
)

MIB = 1024 ** 2


class ReservationTests(unittest.TestCase):
    def test_a_reservation_reduces_what_is_available(self) -> None:
        ledger = InMemoryLedger(capacity_bytes=100 * MIB)
        ledger.reserve(service_id="a.one", amount_bytes=40 * MIB)
        self.assertEqual(ledger.available_bytes(), 60 * MIB)

    def test_a_reservation_larger_than_the_pool_is_refused(self) -> None:
        ledger = InMemoryLedger(capacity_bytes=100 * MIB)
        with self.assertRaises(LedgerError) as caught:
            ledger.reserve(service_id="a.one", amount_bytes=200 * MIB)
        self.assertIn("104857600 bytes remain", str(caught.exception))
        self.assertEqual(ledger.available_bytes(), 100 * MIB)

    def test_two_reservations_cannot_both_consume_the_same_remainder(self) -> None:
        ledger = InMemoryLedger(capacity_bytes=100 * MIB)
        ledger.reserve(service_id="a.one", amount_bytes=60 * MIB)
        with self.assertRaises(LedgerError):
            ledger.reserve(service_id="b.two", amount_bytes=60 * MIB)

    def test_a_negative_reservation_is_refused(self) -> None:
        ledger = InMemoryLedger(capacity_bytes=100 * MIB)
        with self.assertRaises(LedgerError):
            ledger.reserve(service_id="a.one", amount_bytes=-1)

    def test_the_protected_reserve_is_excluded_from_capacity_not_subtracted_twice(self) -> None:
        # capacity_bytes is already net of the reserve; the reserve is carried
        # only so a refusal can name what it is protecting.
        ledger = InMemoryLedger(capacity_bytes=100 * MIB, protected_reserve_bytes=32 * MIB)
        ledger.reserve(service_id="a.one", amount_bytes=100 * MIB)
        self.assertEqual(ledger.available_bytes(), 0)


class ConcurrencyTests(unittest.TestCase):
    """Two simultaneous transitions must not both be told there is room."""

    def test_concurrent_reservations_never_overdraw_the_pool(self) -> None:
        ledger = InMemoryLedger(capacity_bytes=10 * MIB)
        granted: list[str] = []
        refused: list[str] = []
        barrier = threading.Barrier(8)

        def attempt(index: int) -> None:
            barrier.wait()
            try:
                entry = ledger.reserve(service_id=f"s{index}.svc", amount_bytes=2 * MIB)
                granted.append(entry.reservation_id)
            except LedgerError:
                refused.append(f"s{index}.svc")

        threads = [threading.Thread(target=attempt, args=(index,)) for index in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(len(granted), 5)
        self.assertEqual(len(refused), 3)
        self.assertEqual(ledger.outstanding_bytes(), 10 * MIB)

    def test_concurrent_release_and_reserve_keep_the_invariant(self) -> None:
        ledger = InMemoryLedger(capacity_bytes=8 * MIB)
        errors: list[BaseException] = []

        def churn(index: int) -> None:
            try:
                for _ in range(50):
                    try:
                        entry = ledger.reserve(service_id=f"s{index}.svc", amount_bytes=1 * MIB)
                    except LedgerError:
                        continue
                    ledger.release(entry.reservation_id)
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=churn, args=(index,)) for index in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        self.assertEqual(ledger.outstanding_bytes(), 0)


class CommitAndReleaseTests(unittest.TestCase):
    def test_committing_holds_the_memory(self) -> None:
        ledger = InMemoryLedger(capacity_bytes=100 * MIB)
        entry = ledger.reserve(service_id="a.one", amount_bytes=40 * MIB)
        ledger.commit(entry.reservation_id)
        self.assertEqual(ledger.committed_bytes(), 40 * MIB)
        self.assertEqual(ledger.available_bytes(), 60 * MIB)

    def test_committing_less_than_reserved_returns_the_difference(self) -> None:
        ledger = InMemoryLedger(capacity_bytes=100 * MIB)
        entry = ledger.reserve(service_id="a.one", amount_bytes=40 * MIB)
        ledger.commit(entry.reservation_id, amount_bytes=10 * MIB)
        self.assertEqual(ledger.available_bytes(), 90 * MIB)

    def test_committing_more_than_reserved_is_refused(self) -> None:
        # This is the decision boundary in its least obvious place: a commit
        # that exceeded its reservation would let a service grow past the
        # plan's grant without anything above noticing.
        ledger = InMemoryLedger(capacity_bytes=100 * MIB)
        entry = ledger.reserve(service_id="a.one", amount_bytes=40 * MIB)
        with self.assertRaises(LedgerError) as caught:
            ledger.commit(entry.reservation_id, amount_bytes=80 * MIB)
        self.assertIn("never grant more than the plan reserved", str(caught.exception))

    def test_committing_twice_is_idempotent(self) -> None:
        ledger = InMemoryLedger(capacity_bytes=100 * MIB)
        entry = ledger.reserve(service_id="a.one", amount_bytes=40 * MIB)
        first = ledger.commit(entry.reservation_id)
        second = ledger.commit(entry.reservation_id)
        self.assertEqual(first, second)

    def test_release_is_idempotent(self) -> None:
        ledger = InMemoryLedger(capacity_bytes=100 * MIB)
        entry = ledger.reserve(service_id="a.one", amount_bytes=40 * MIB)
        first = ledger.release(entry.reservation_id)
        second = ledger.release(entry.reservation_id)
        self.assertEqual(first, second)
        self.assertEqual(ledger.available_bytes(), 100 * MIB)

    def test_releasing_something_that_does_not_exist_returns_none(self) -> None:
        # Cleanup paths must not be able to fail; a cleanup that raises leaks.
        ledger = InMemoryLedger(capacity_bytes=100 * MIB)
        self.assertIsNone(ledger.release("res-nothing"))

    def test_releasing_a_service_releases_every_reservation_it_holds(self) -> None:
        ledger = InMemoryLedger(capacity_bytes=100 * MIB)
        ledger.reserve(service_id="a.one", amount_bytes=10 * MIB)
        ledger.reserve(service_id="a.one", amount_bytes=20 * MIB)
        ledger.reserve(service_id="b.two", amount_bytes=30 * MIB)
        released = ledger.release_for_service("a.one")
        self.assertEqual(len(released), 2)
        self.assertEqual(ledger.outstanding_bytes(), 30 * MIB)


class ExpiryTests(unittest.TestCase):
    def test_an_uncommitted_reservation_expires(self) -> None:
        ledger = InMemoryLedger(capacity_bytes=100 * MIB)
        ledger.reserve(service_id="a.one", amount_bytes=40 * MIB, now=0.0, ttl_seconds=30.0)
        self.assertEqual(ledger.available_bytes(), 60 * MIB)
        expired = ledger.expire(31.0)
        self.assertEqual(len(expired), 1)
        self.assertEqual(ledger.available_bytes(), 100 * MIB)

    def test_a_committed_reservation_does_not_expire(self) -> None:
        # A running service does not stop running because a deadline passed.
        ledger = InMemoryLedger(capacity_bytes=100 * MIB)
        entry = ledger.reserve(service_id="a.one", amount_bytes=40 * MIB, now=0.0, ttl_seconds=30.0)
        ledger.commit(entry.reservation_id)
        self.assertEqual(ledger.expire(1000.0), ())
        self.assertEqual(ledger.committed_bytes(), 40 * MIB)

    def test_the_default_ttl_outlasts_a_slow_start(self) -> None:
        # Reclaiming a reservation out from under a service that is still
        # starting would be worse than the leak it prevents.
        self.assertGreater(DEFAULT_RESERVATION_TTL_SECONDS, 60.0)

    def test_expiry_happens_before_a_new_reservation_is_judged(self) -> None:
        ledger = InMemoryLedger(capacity_bytes=100 * MIB)
        ledger.reserve(service_id="a.one", amount_bytes=90 * MIB, now=0.0, ttl_seconds=10.0)
        entry = ledger.reserve(service_id="b.two", amount_bytes=90 * MIB, now=100.0)
        self.assertEqual(entry.reserved_amount, 90 * MIB)


class OrphanRecoveryTests(unittest.TestCase):
    def test_a_committed_reservation_for_a_stopped_service_is_an_orphan(self) -> None:
        ledger = InMemoryLedger(capacity_bytes=100 * MIB)
        entry = ledger.reserve(service_id="a.one", amount_bytes=40 * MIB)
        ledger.commit(entry.reservation_id)
        orphans = ledger.orphans(active_service_ids=[])
        self.assertEqual([item.service_id for item in orphans], ["a.one"])

    def test_a_committed_reservation_for_a_running_service_is_not_an_orphan(self) -> None:
        ledger = InMemoryLedger(capacity_bytes=100 * MIB)
        entry = ledger.reserve(service_id="a.one", amount_bytes=40 * MIB)
        ledger.commit(entry.reservation_id)
        self.assertEqual(ledger.orphans(active_service_ids=["a.one"]), ())

    def test_reconciling_against_actual_state_reclaims_orphans(self) -> None:
        ledger = InMemoryLedger(capacity_bytes=100 * MIB)
        for name in ("a.one", "b.two"):
            entry = ledger.reserve(service_id=name, amount_bytes=40 * MIB)
            ledger.commit(entry.reservation_id)
        reclaimed = ledger.reconcile_with_actual(active_service_ids=["a.one"])
        self.assertEqual([item.service_id for item in reclaimed], ["b.two"])
        self.assertEqual(ledger.available_bytes(), 60 * MIB)
        self.assertEqual(reclaimed[0].owner, "recovery")


class InvariantTests(unittest.TestCase):
    def test_the_invariant_catches_a_ledger_that_was_overdrawn_directly(self) -> None:
        # Nothing in the public API can produce this; the check exists so that a
        # future change to the ledger surfaces here rather than as an OOM kill.
        ledger = InMemoryLedger(capacity_bytes=10 * MIB)
        ledger.reservations["res-bad"] = Reservation(
            "res-bad", "plan", "trans", "a.one", "memory_bytes", 50 * MIB,
        )
        with self.assertRaises(LedgerInvariantError):
            ledger._check_invariants()

    def test_outstanding_never_exceeds_capacity_across_many_operations(self) -> None:
        ledger = InMemoryLedger(capacity_bytes=64 * MIB)
        held: list[str] = []
        for index in range(200):
            try:
                entry = ledger.reserve(service_id=f"s{index % 7}.svc", amount_bytes=8 * MIB)
                held.append(entry.reservation_id)
            except LedgerError:
                if held:
                    ledger.release(held.pop(0))
            self.assertLessEqual(ledger.outstanding_bytes(), ledger.capacity_bytes)


class DurabilityTests(unittest.TestCase):
    def test_a_ledger_survives_a_process_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.json"
            first = JsonFileLedger(capacity_bytes=100 * MIB, path=path)
            entry = first.reserve(service_id="a.one", amount_bytes=40 * MIB)
            first.commit(entry.reservation_id)

            second = JsonFileLedger(capacity_bytes=100 * MIB, path=path)
            self.assertEqual(second.load(), ())
            self.assertEqual(second.committed_bytes(), 40 * MIB)
            self.assertEqual(second.available_bytes(), 60 * MIB)

    def test_released_reservations_are_not_restored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.json"
            first = JsonFileLedger(capacity_bytes=100 * MIB, path=path)
            entry = first.reserve(service_id="a.one", amount_bytes=40 * MIB)
            first.release(entry.reservation_id)

            second = JsonFileLedger(capacity_bytes=100 * MIB, path=path)
            second.load()
            self.assertEqual(second.available_bytes(), 100 * MIB)

    def test_a_corrupt_ledger_file_starts_empty_with_a_warning(self) -> None:
        # Refusing to run because a bookkeeping file is unreadable would be
        # worse than reconciling against the machine.
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.json"
            path.write_text("{not json", encoding="utf-8")
            ledger = JsonFileLedger(capacity_bytes=100 * MIB, path=path)
            warnings = ledger.load()
            self.assertEqual(len(warnings), 1)
            self.assertIn("empty ledger", warnings[0])
            self.assertEqual(ledger.available_bytes(), 100 * MIB)

    def test_an_unreadable_entry_is_discarded_and_the_rest_survive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.json"
            ledger = JsonFileLedger(capacity_bytes=100 * MIB, path=path)
            ledger.reserve(service_id="a.one", amount_bytes=20 * MIB)
            document = json.loads(path.read_text(encoding="utf-8"))
            document["reservations"].append({"reservationId": "", "serviceId": "b.two"})
            path.write_text(json.dumps(document), encoding="utf-8")

            restored = JsonFileLedger(capacity_bytes=100 * MIB, path=path)
            warnings = restored.load()
            self.assertEqual(len(warnings), 1)
            self.assertEqual(restored.outstanding_bytes(), 20 * MIB)

    def test_a_persisted_ledger_that_violates_the_invariant_is_discarded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.json"
            path.write_text(json.dumps({
                "reservations": [{
                    "reservationId": "res-huge", "serviceId": "a.one",
                    "resourceType": "memory_bytes", "reservedAmount": 900 * MIB,
                    "state": "reserved",
                }],
            }), encoding="utf-8")
            ledger = JsonFileLedger(capacity_bytes=100 * MIB, path=path)
            warnings = ledger.load()
            self.assertTrue(any("invariant" in item for item in warnings))
            self.assertEqual(ledger.available_bytes(), 100 * MIB)

    def test_a_negative_amount_in_the_file_is_refused(self) -> None:
        with self.assertRaises(LedgerError):
            Reservation.from_json({
                "reservationId": "res-1", "serviceId": "a.one",
                "resourceType": "memory_bytes", "reservedAmount": -5,
            })

    def test_an_unknown_resource_type_in_the_file_is_refused(self) -> None:
        with self.assertRaises(LedgerError):
            Reservation.from_json({
                "reservationId": "res-1", "serviceId": "a.one",
                "resourceType": "unicorns", "reservedAmount": 5,
            })

    def test_writing_to_an_unwritable_path_does_not_break_the_ledger(self) -> None:
        # Losing durability is a degradation to report, not a reason to fail
        # the transition being accounted for.
        ledger = JsonFileLedger(
            capacity_bytes=100 * MIB,
            path=Path("/nonexistent-root-directory-for-tests/ledger.json"),
        )
        entry = ledger.reserve(service_id="a.one", amount_bytes=10 * MIB)
        self.assertEqual(entry.reserved_amount, 10 * MIB)
        self.assertEqual(ledger.outstanding_bytes(), 10 * MIB)


if __name__ == "__main__":
    unittest.main()
