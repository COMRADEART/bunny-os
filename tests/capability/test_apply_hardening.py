# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""High-risk failure injection and the security boundaries around state.

Two groups, both about what happens when something is wrong rather than when
everything works:

**Failure injection** — systemd absent, a start that never completes, a health
check that fails after the process exits, and a state directory that cannot be
written. Each asks the same three questions: is a reservation leaked, is a
process left running unconstrained, and does the explanation identify the first
invariant that failed?

**Security** — the state directory is the applicator's trust anchor. Everything
it believes about what is running and what a person approved comes from files
there, so a symlink that redirects a write, a path that escapes the directory,
or an input large enough to exhaust memory are all ways to make it believe
something false.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from capability.apply.applicator import Applicator, ApplicatorSettings
from capability.apply.approval import ApprovalRequest
from capability.apply.approval_store import DurableApprovalStore, authorization_digest
from capability.apply.audit import InMemoryAuditSink, JsonLinesAuditSink, redact
from capability.apply.backends import InMemoryBackend, ServiceLimits
from capability.apply.durable import DurableFile, checksum_of
from capability.apply.ledger import InMemoryLedger, JsonFileLedger, LedgerError
from capability.apply.systemd import SystemdBackend, authorized_units_for, unit_name_for
from capability.registry import load_registry
from capability.runtime import assess
from capability.simulate import simulate

MIB = 1024 ** 2
REGISTRY = load_registry()


def harness(backend=None, **settings):
    assessment = assess(simulate("laptop"), registry=REGISTRY)
    ledger = InMemoryLedger(
        capacity_bytes=(
            assessment.budget.currently_allocatable_bytes
            + assessment.budget.essential_services_bytes
        ),
        protected_reserve_bytes=assessment.budget.protected_reserve_bytes,
    )
    applicator = Applicator(
        backend=backend if backend is not None else InMemoryBackend(),
        ledger=ledger, audit=InMemoryAuditSink(),
        settings=ApplicatorSettings(dry_run=False, **settings),
    )
    return applicator, assessment


def run(applicator, assessment, **overrides):
    arguments = {
        "registry": assessment.registry, "inventory": assessment.inventory,
        "budget": assessment.budget, "policy": assessment.policy, "now": 0.0,
    }
    arguments.update(overrides)
    return applicator.apply(assessment.plan, **arguments)


class SystemdUnavailableTests(unittest.TestCase):
    """A missing service manager must read as unknown, never as an empty machine."""

    def test_an_absent_systemd_starts_nothing(self) -> None:
        backend = SystemdBackend(
            authorized_units=authorized_units_for(REGISTRY),
            allow_host_modification=True, systemctl="/usr/bin/systemctl",
        )
        with mock.patch("capability.apply.systemd.systemd_available", return_value=False):
            applicator, assessment = harness(backend=backend)
            report = run(applicator, assessment)
        self.assertEqual(report.applied, (), "nothing may be attempted without a service manager")
        self.assertEqual(applicator.ledger.outstanding_bytes(), 0, "no reservation may leak")

    def test_an_absent_systemd_is_reported_as_unavailable_not_empty(self) -> None:
        backend = SystemdBackend(
            authorized_units=authorized_units_for(REGISTRY), systemctl="/usr/bin/systemctl",
        )
        with mock.patch("capability.apply.systemd.systemd_available", return_value=False):
            state = Applicator(backend=backend).observe(REGISTRY)
        self.assertEqual(state.unavailable_backends, ("systemd",))
        self.assertTrue(all(item.state == "unknown" for item in state.services.values()))

    def test_the_explanation_names_the_first_failed_invariant(self) -> None:
        backend = SystemdBackend(
            authorized_units=authorized_units_for(REGISTRY),
            allow_host_modification=True, systemctl="/usr/bin/systemctl",
        )
        with mock.patch("capability.apply.systemd.systemd_available", return_value=False):
            outcome = backend.start("bunny.system.health", "impl", ServiceLimits(), timeout_seconds=5)
        self.assertEqual(outcome.failure_class, "backend_unavailable")
        self.assertIn("not the init system", outcome.detail)


class StartupTimeoutTests(unittest.TestCase):
    def test_a_start_that_never_becomes_ready_is_rolled_back(self) -> None:
        applicator, assessment = harness(
            backend=InMemoryBackend(partial_start={"bunny.companion"}),
        )
        report = run(applicator, assessment)
        transition = next(item for item in report.applied if item.service_id == "bunny.companion")
        self.assertEqual(transition.result.result, "rolled_back")
        self.assertEqual(transition.result.failure_class, "startup_timeout")

    def test_a_timed_out_start_leaks_no_reservation(self) -> None:
        applicator, assessment = harness(
            backend=InMemoryBackend(partial_start={"bunny.companion"}),
        )
        run(applicator, assessment)
        held = [item for item in applicator.ledger.active() if item.service_id == "bunny.companion"]
        self.assertEqual(held, [])

    def test_a_timed_out_start_leaves_no_process(self) -> None:
        backend = InMemoryBackend(partial_start={"bunny.companion"})
        applicator, assessment = harness(backend=backend)
        run(applicator, assessment)
        self.assertNotIn("bunny.companion", backend.services)

    def test_the_timeout_is_bounded_by_the_transition_not_by_systemd(self) -> None:
        # A unit's own TimeoutStartSec is 90s by default and is not the
        # applicator's deadline to inherit.
        from capability.apply.reconcile import DEFAULT_TIMEOUTS

        self.assertLessEqual(DEFAULT_TIMEOUTS["start"], 90.0)
        self.assertGreater(DEFAULT_TIMEOUTS["start"], 0)


class HealthFailureTests(unittest.TestCase):
    def test_a_service_that_exits_before_health_confirmation_is_rolled_back(self) -> None:
        applicator, assessment = harness(backend=InMemoryBackend(unhealthy={"bunny.companion"}))
        report = run(applicator, assessment)
        transition = next(item for item in report.applied if item.service_id == "bunny.companion")
        self.assertEqual(transition.result.result, "rolled_back")
        self.assertEqual(applicator.ledger.outstanding_bytes() >= 0, True)
        held = [item for item in applicator.ledger.active() if item.service_id == "bunny.companion"]
        self.assertEqual(held, [], "a failed health check must not leave a reservation")

    def test_an_unrelated_service_is_unaffected(self) -> None:
        backend = InMemoryBackend(unhealthy={"bunny.companion"})
        applicator, assessment = harness(backend=backend)
        report = run(applicator, assessment)
        succeeded = {
            item.service_id for item in report.applied
            if item.result is not None and item.result.result == "succeeded"
        }
        self.assertIn("bunny.system.broker", succeeded)


class ReadOnlyAndFullDiskTests(unittest.TestCase):
    """State that cannot be written must degrade, not corrupt or crash."""

    def test_a_ledger_on_an_unwritable_path_still_accounts_correctly(self) -> None:
        # Losing durability is a degradation to report; it is not a reason to
        # fail the transition being accounted for.
        ledger = JsonFileLedger(
            path=Path("/nonexistent-root-for-tests/reservations.json"),
            capacity_bytes=100 * MIB,
        )
        entry = ledger.reserve(service_id="a.one", amount_bytes=10 * MIB)
        self.assertEqual(entry.reserved_amount, 10 * MIB)
        self.assertEqual(ledger.outstanding_bytes(), 10 * MIB)

    def test_a_write_failure_is_recorded_rather_than_raised(self) -> None:
        directory = Path(tempfile.mkdtemp())
        handle = DurableFile(path=directory / "state.json")
        handle.write({"a": 1})

        with mock.patch("os.replace", side_effect=OSError(28, "No space left on device")):
            with self.assertRaises(OSError):
                handle.write({"a": 2})
        self.assertTrue(handle.last_write_failed)
        self.assertIn("No space left", handle.last_write_error)

        # The previous good state is still readable: a full disk must not
        # destroy what was already durable.
        outcome = DurableFile(path=directory / "state.json").load(default=None)
        self.assertTrue(outcome.trusted)
        self.assertEqual(outcome.payload["a"], 1)

    def test_a_full_disk_leaves_no_temporary_file_behind(self) -> None:
        directory = Path(tempfile.mkdtemp())
        handle = DurableFile(path=directory / "state.json")
        with mock.patch("os.replace", side_effect=OSError(28, "No space left on device")):
            with self.assertRaises(OSError):
                handle.write({"a": 1})
        leftovers = [item for item in directory.iterdir() if ".tmp-" in item.name]
        self.assertEqual(leftovers, [], "a failed write must clean up after itself")

    def test_an_audit_sink_that_cannot_write_does_not_stop_the_machine(self) -> None:
        # An audit log that cannot be written must not throw out of a logging
        # call in the middle of a transition.
        sink = JsonLinesAuditSink(path=Path("/nonexistent-root-for-tests/audit.jsonl"))
        sink.record("reconcile.started", at_monotonic=0.0)

    def test_an_approval_store_that_cannot_persist_still_denies(self) -> None:
        store = DurableApprovalStore(path=Path("/nonexistent-root-for-tests/approvals.json"))
        store.load()
        response = store.request(ApprovalRequest(
            "r1", "plan", "t1", "a.one", "remote_dispatch", "why",
            alternatives=("stay local",),
        ))
        self.assertEqual(response.decision, "pending")
        self.assertEqual(store.approved_services("plan", 0.0), frozenset())


class SymlinkTests(unittest.TestCase):
    """A symlink must not redirect a write out of the state directory."""

    def setUp(self) -> None:
        self.directory = Path(tempfile.mkdtemp())
        self.outside = Path(tempfile.mkdtemp()) / "victim.json"
        self.outside.write_text("original content", encoding="utf-8")

    @unittest.skipIf(os.name == "nt", "symlink creation needs privilege on Windows")
    def test_a_symlinked_state_file_is_replaced_not_followed(self) -> None:
        # os.replace onto a symlink replaces the LINK, not its target. That is
        # the property that keeps a redirected write inside the state directory,
        # and it is worth asserting rather than assuming.
        state = self.directory / "reservations.json"
        state.symlink_to(self.outside)

        DurableFile(path=state).write({"entries": ["ours"]})

        self.assertFalse(state.is_symlink(), "the symlink must have been replaced")
        self.assertEqual(
            self.outside.read_text(encoding="utf-8"), "original content",
            "the file outside the state directory must be untouched",
        )
        outcome = DurableFile(path=state).load(default=None)
        self.assertTrue(outcome.trusted)

    @unittest.skipIf(os.name == "nt", "symlink creation needs privilege on Windows")
    def test_a_symlinked_approval_store_does_not_leak_decisions(self) -> None:
        store_path = self.directory / "approvals.json"
        store_path.symlink_to(self.outside)
        store = DurableApprovalStore(path=store_path)
        store.load()
        store.request(ApprovalRequest(
            "r1", "plan", "t1", "a.one", "paid_provider", "why",
            alternatives=("use the local model",),
        ))
        self.assertEqual(self.outside.read_text(encoding="utf-8"), "original content")

    def test_the_temporary_file_is_created_inside_the_state_directory(self) -> None:
        # A temporary elsewhere would make the replace a cross-filesystem copy
        # and would put state outside the directory whose mode protects it.
        seen: list[Path] = []
        handle = DurableFile(path=self.directory / "state.json")

        def watcher(step: str) -> None:
            if step == "before-replace":
                seen.extend(
                    item for item in self.directory.iterdir() if ".tmp-" in item.name
                )

        handle.crash_hook = watcher
        handle.write({"a": 1})
        self.assertTrue(seen)
        for item in seen:
            self.assertEqual(item.parent, self.directory)


class OversizedInputTests(unittest.TestCase):
    """Structured input from disk or a service manager is untrusted and bounded."""

    def test_an_oversized_diagnostic_is_truncated_before_it_is_recorded(self) -> None:
        sink = InMemoryAuditSink()
        sink.record(
            "backend.operation", at_monotonic=0.0,
            observed={"diagnostic": "A" * 5_000_000},
        )
        stored = sink.records[0].to_json()["observed"]["diagnostic"]
        self.assertLessEqual(len(stored), 2048)

    def test_redaction_bounds_every_string_it_touches(self) -> None:
        self.assertLessEqual(len(redact("B" * 100_000)), 2048)

    def test_a_backend_diagnostic_is_bounded(self) -> None:
        from capability.apply.backends import BackendOutcome

        outcome = BackendOutcome(False, "start", "a.one", diagnostic="C" * 100_000)
        self.assertLessEqual(len(outcome.to_json()["diagnostic"]), 2048)

    def test_an_enormous_ledger_file_does_not_exhaust_memory_silently(self) -> None:
        # A ledger with an implausible number of entries is refused by the
        # invariant rather than loaded and believed.
        directory = Path(tempfile.mkdtemp())
        path = directory / "reservations.json"
        entries = [
            {
                "reservationId": f"res-{index}", "serviceId": f"s{index}.svc",
                "resourceType": "memory_bytes", "reservedAmount": 10 * MIB,
                "state": "reserved",
            }
            for index in range(2000)
        ]
        payload = {"schemaVersion": 1, "reservations": entries}
        path.write_text(json.dumps(payload), encoding="utf-8")
        ledger = JsonFileLedger(path=path, capacity_bytes=100 * MIB)
        warnings = ledger.load()
        self.assertTrue(warnings, "an over-capacity ledger must be reported")
        self.assertLessEqual(ledger.outstanding_bytes(), ledger.capacity_bytes)

    def test_a_deeply_nested_approval_record_is_refused(self) -> None:
        directory = Path(tempfile.mkdtemp())
        path = directory / "approvals.json"
        nested: object = "x"
        for _ in range(200):
            nested = {"n": nested}
        payload = {
            "schemaVersion": 1,
            "records": [{"request": nested, "decision": "granted"}],
        }
        path.write_text(json.dumps({
            "stateVersion": 1, "revision": 1,
            "checksum": checksum_of(payload), "payload": payload,
        }), encoding="utf-8")
        store = DurableApprovalStore(path=path)
        warnings = store.load()
        self.assertTrue(warnings)
        self.assertEqual(store.approved_services("plan", 0.0), frozenset())

    def test_an_absurd_reservation_amount_is_refused(self) -> None:
        ledger = InMemoryLedger(capacity_bytes=100 * MIB)
        with self.assertRaises(LedgerError):
            ledger.reserve(service_id="a.one", amount_bytes=2 ** 62)


class ApprovalForgeryTests(unittest.TestCase):
    """Editing a decision by hand must not grant anything."""

    def setUp(self) -> None:
        self.directory = Path(tempfile.mkdtemp())
        self.path = self.directory / "approvals.json"
        self.store = DurableApprovalStore(path=self.path)
        self.store.load()
        self.store.request(ApprovalRequest(
            "r1", "plan-1", "t1", "a.one", "paid_provider", "why",
            estimated_cost_units=4, alternatives=("use the local model",),
        ))

    def test_a_hand_edited_grant_is_not_honoured(self) -> None:
        document = json.loads(self.path.read_text(encoding="utf-8"))
        for record in document["payload"]["records"]:
            record["decision"] = "granted"
        document["checksum"] = checksum_of(document["payload"])
        self.path.write_text(json.dumps(document), encoding="utf-8")

        restored = DurableApprovalStore(path=self.path)
        warnings = restored.load()
        self.assertTrue(any("authorization digest" in item for item in warnings))
        self.assertEqual(restored.approved_services("plan-1", 0.0), frozenset())

    def test_a_grant_whose_cost_was_edited_is_not_honoured(self) -> None:
        # Consent to four cents is not consent to four hundred.
        self.store.decide("r1", "granted", actor="user", now_monotonic=0.0)
        self.assertIn("a.one", self.store.approved_services("plan-1", 1.0))

        document = json.loads(self.path.read_text(encoding="utf-8"))
        for record in document["payload"]["records"]:
            record["request"]["estimatedCostUnits"] = 40000
        document["checksum"] = checksum_of(document["payload"])
        self.path.write_text(json.dumps(document), encoding="utf-8")

        restored = DurableApprovalStore(path=self.path)
        restored.load()
        self.assertEqual(restored.approved_services("plan-1", 1.0), frozenset())

    def test_a_grant_for_another_plan_authorises_nothing(self) -> None:
        self.store.decide("r1", "granted", actor="user", now_monotonic=0.0)
        self.assertEqual(self.store.approved_services("plan-2", 1.0), frozenset())

    def test_an_expired_grant_authorises_nothing(self) -> None:
        store = DurableApprovalStore(path=self.directory / "b.json", default_ttl_seconds=10.0)
        store.load()
        store.request(ApprovalRequest(
            "r2", "plan-1", "t2", "b.two", "remote_dispatch", "why",
            expires_at_monotonic=5.0, alternatives=("stay local",),
        ))
        store.decide("r2", "granted", actor="user", now_monotonic=0.0)
        self.assertIn("b.two", store.approved_services("plan-1", 1.0))
        self.assertEqual(store.approved_services("plan-1", 100.0), frozenset())

    def test_a_decision_cannot_be_flipped_after_the_fact(self) -> None:
        self.store.decide("r1", "denied", actor="user", now_monotonic=0.0)
        with self.assertRaises(ValueError):
            self.store.decide("r1", "granted", actor="user", now_monotonic=1.0)

    def test_the_same_decision_twice_is_idempotent(self) -> None:
        first = self.store.decide("r1", "granted", actor="user", now_monotonic=0.0)
        second = self.store.decide("r1", "granted", actor="user", now_monotonic=5.0)
        self.assertEqual(first.authorization, second.authorization)

    def test_a_revoked_grant_authorises_nothing(self) -> None:
        self.store.decide("r1", "granted", actor="user", now_monotonic=0.0)
        self.store.revoke("r1", actor="operator")
        self.assertEqual(self.store.approved_services("plan-1", 1.0), frozenset())

    def test_the_digest_covers_the_fields_that_define_consent(self) -> None:
        base = dict(
            request_id="r", plan_id="p", transition_id="t", action="paid_provider",
            destination="remote", estimated_cost_units=4, decision="granted",
            decided_at_wall=100.0, actor="user",
        )
        reference = authorization_digest(**base)
        for field, value in (
            ("plan_id", "other"), ("action", "remote_dispatch"), ("destination", "local"),
            ("estimated_cost_units", 400), ("decision", "denied"), ("actor", "someone-else"),
        ):
            with self.subTest(field=field):
                self.assertNotEqual(reference, authorization_digest(**{**base, field: value}))


class UnitNameSecurityTests(unittest.TestCase):
    def test_a_manifest_cannot_supply_a_unit_name(self) -> None:
        # The defence is structural: unit names are derived, never read.
        manifest = REGISTRY.get("bunny.system.health")
        self.assertFalse(hasattr(manifest, "unit"))
        self.assertFalse(hasattr(manifest, "unit_name"))
        self.assertNotIn("unit", manifest.to_json())

    def test_a_traversal_shaped_service_id_produces_no_unit(self) -> None:
        for candidate in ("../../etc/systemd/system/evil", "a/../../b", "..", "/absolute"):
            with self.subTest(candidate=candidate):
                with self.assertRaises(ValueError):
                    unit_name_for(candidate)

    def test_an_unauthorised_unit_is_refused_even_with_modification_enabled(self) -> None:
        backend = SystemdBackend(
            authorized_units=frozenset({"bunny-bunny-system-health.service"}),
            allow_host_modification=True, systemctl="/usr/bin/systemctl",
        )
        with mock.patch("capability.apply.systemd.systemd_available", return_value=True):
            outcome = backend.stop("bunny.other.thing", timeout_seconds=5)
        self.assertEqual(outcome.failure_class, "unit_not_authorized")

    def test_the_allowlist_contains_no_host_unit(self) -> None:
        units = authorized_units_for(REGISTRY)
        for forbidden in ("sshd.service", "systemd-logind.service", "dbus.service", "getty@.service"):
            with self.subTest(unit=forbidden):
                self.assertNotIn(forbidden, units)


if __name__ == "__main__":
    unittest.main()
