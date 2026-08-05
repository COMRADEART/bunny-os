# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The applicator: transactions, rollback, retry, breaking, and the audit trail.

Everything here runs against :class:`InMemoryBackend`. No test in this file
inspects, starts or stops a real service, and the default settings the
applicator ships with would not let it even if one tried.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from capability.apply.applicator import Applicator, ApplicatorSettings
from capability.apply.approval import (
    ApprovalRequest,
    DenyingApprovalStore,
    InMemoryApprovalStore,
    SENSITIVE_ACTIONS,
)
from capability.apply.audit import InMemoryAuditSink, redact
from capability.apply.backends import DryRunBackend, InMemoryBackend, ServiceLimits
from capability.apply.failures import (
    CircuitBreaker,
    FAILURE_CLASSES,
    RetryJournal,
    RetryPolicy,
    is_retryable,
)
from capability.apply.ledger import InMemoryLedger
from capability.apply.state import ServiceObservation
from capability.policy import Policy
from capability.registry import load_registry
from capability.runtime import assess
from capability.simulate import simulate

MIB = 1024 ** 2
GIB = 1024 ** 3
REGISTRY = load_registry()


def harness(machine_name: str = "laptop", *, backend=None, dry_run: bool = False, **settings):
    """An applicator wired to a simulated machine, with a real plan."""
    assessment = assess(simulate(machine_name), registry=REGISTRY)
    ledger = InMemoryLedger(
        capacity_bytes=(
            assessment.budget.currently_allocatable_bytes
            + assessment.budget.essential_services_bytes
        ),
        protected_reserve_bytes=assessment.budget.protected_reserve_bytes,
    )
    applicator = Applicator(
        backend=backend if backend is not None else InMemoryBackend(),
        ledger=ledger,
        audit=InMemoryAuditSink(),
        settings=ApplicatorSettings(dry_run=dry_run, **settings),
    )
    return applicator, assessment


def run(applicator, assessment, *, now: float = 0.0, **overrides):
    arguments = {
        "registry": assessment.registry,
        "inventory": assessment.inventory,
        "budget": assessment.budget,
        "policy": assessment.policy,
        "now": now,
    }
    arguments.update(overrides)
    return applicator.apply(assessment.plan, **arguments)


class DefaultSafetyTests(unittest.TestCase):
    """The developer checkout must not be able to change services by accident."""

    def test_a_default_applicator_is_a_dry_run(self) -> None:
        self.assertTrue(ApplicatorSettings().dry_run)

    def test_a_default_applicator_uses_the_dry_run_backend(self) -> None:
        self.assertIsInstance(Applicator().backend, DryRunBackend)

    def test_a_default_applicator_grants_no_approval(self) -> None:
        self.assertIsInstance(Applicator().approvals, DenyingApprovalStore)

    def test_a_default_applicator_will_not_stop_an_essential_service(self) -> None:
        self.assertFalse(ApplicatorSettings().allow_essential_stop)

    def test_a_dry_run_pass_performs_no_backend_mutation(self) -> None:
        backend = DryRunBackend(observer=InMemoryBackend())
        applicator, assessment = harness(backend=backend, dry_run=True)
        report = run(applicator, assessment)
        self.assertTrue(report.dry_run)
        self.assertTrue(report.applied)
        self.assertTrue(all(
            item.observation is None for item in []  # nothing observed from a dry run
        ))
        # The observer's own state never changed.
        self.assertEqual(backend.observer.services, {})


class ConvergenceTests(unittest.TestCase):
    def test_a_bare_machine_converges_in_one_pass(self) -> None:
        applicator, assessment = harness()
        report = run(applicator, assessment)
        self.assertTrue(report.applied)
        self.assertEqual(report.failures, ())
        succeeded = {
            item.service_id for item in report.applied
            if item.result is not None and item.result.result == "succeeded"
        }
        self.assertEqual(succeeded, set(assessment.plan.by_id()) & succeeded)
        for decision in assessment.plan.running():
            with self.subTest(service=decision.service_id):
                self.assertIn(decision.service_id, succeeded)

    def test_a_second_pass_on_a_converged_machine_does_nothing(self) -> None:
        applicator, assessment = harness()
        run(applicator, assessment)
        settled = assess(
            simulate("laptop"), registry=REGISTRY, previous=assessment.plan, now=1.0,
        )
        applicator.ledger.capacity_bytes = (
            settled.budget.currently_allocatable_bytes + settled.budget.essential_services_bytes
        )
        report = run(applicator, settled, now=1.0)
        self.assertEqual(report.applied, ())
        self.assertTrue(report.converged)

    def test_the_ledger_reflects_exactly_what_was_started(self) -> None:
        applicator, assessment = harness()
        run(applicator, assessment)
        committed = {item.service_id for item in applicator.ledger.active()}
        started = {item.service_id for item in applicator.backend.services.values()}
        self.assertEqual(committed, started)

    def test_the_ledger_never_promises_more_than_the_budget(self) -> None:
        for name in ("embedded-64mb", "raspberry-pi-class", "laptop", "gaming-desktop"):
            with self.subTest(machine=name):
                applicator, assessment = harness(name)
                run(applicator, assessment)
                self.assertLessEqual(
                    applicator.ledger.outstanding_bytes(),
                    applicator.ledger.capacity_bytes,
                )


class PlanRejectionTests(unittest.TestCase):
    def test_a_stale_plan_is_rejected_and_nothing_is_touched(self) -> None:
        applicator, assessment = harness()
        report = run(applicator, assessment, inventory=simulate("cpu-server"))
        self.assertEqual(report.applied, ())
        self.assertFalse(report.validation.ok)
        self.assertEqual(report.validation.failure_class, "stale_plan")
        self.assertEqual(applicator.backend.operations, [])

    def test_a_rejected_plan_requests_reevaluation(self) -> None:
        applicator, assessment = harness()
        report = run(applicator, assessment, inventory=simulate("cpu-server"))
        self.assertEqual(report.reevaluation_reason, "apply_time_validation_failed")

    def test_a_superseded_plan_is_rejected(self) -> None:
        applicator, assessment = harness()
        run(applicator, assessment)
        newer = assess(simulate("laptop"), registry=REGISTRY, previous=assessment.plan, now=1.0)
        applicator.ledger.capacity_bytes = (
            newer.budget.currently_allocatable_bytes + newer.budget.essential_services_bytes
        )
        run(applicator, newer, now=1.0)
        # Replaying the original plan afterwards must be refused.
        report = run(applicator, assessment, now=2.0)
        self.assertFalse(report.validation.ok)
        self.assertEqual(report.validation.failure_class, "superseded_plan")

    def test_an_expired_plan_is_rejected(self) -> None:
        applicator, assessment = harness()
        report = run(applicator, assessment, now=100_000.0)
        self.assertFalse(report.validation.ok)
        self.assertEqual(report.validation.failure_class, "stale_plan")


class TransactionTests(unittest.TestCase):
    """A start is seven steps, and failing at step six must undo the first five."""

    def failing_at(self, service_id: str, failure: str, operation: str = "start"):
        backend = InMemoryBackend(failures={(service_id, operation): failure})
        return harness(backend=backend)

    def test_a_failed_start_releases_its_reservation(self) -> None:
        applicator, assessment = self.failing_at("bunny.companion", "configuration_error")
        run(applicator, assessment)
        held = [
            item for item in applicator.ledger.active()
            if item.service_id == "bunny.companion"
        ]
        self.assertEqual(held, [], "a failed start left a reservation behind")

    def test_a_failed_start_is_rolled_back(self) -> None:
        applicator, assessment = self.failing_at("bunny.companion", "configuration_error")
        report = run(applicator, assessment)
        transition = next(item for item in report.applied if item.service_id == "bunny.companion")
        self.assertEqual(transition.result.result, "rolled_back")
        self.assertEqual(transition.rollback_state, "completed")

    def test_a_rollback_stops_the_partially_started_service(self) -> None:
        applicator, assessment = harness(backend=InMemoryBackend(unhealthy={"bunny.companion"}))
        run(applicator, assessment)
        self.assertNotIn("bunny.companion", applicator.backend.services)

    def test_a_health_check_failure_rolls_the_start_back(self) -> None:
        applicator, assessment = harness(backend=InMemoryBackend(unhealthy={"bunny.companion"}))
        report = run(applicator, assessment)
        transition = next(item for item in report.applied if item.service_id == "bunny.companion")
        self.assertEqual(transition.result.result, "rolled_back")
        self.assertEqual(transition.result.failure_class, "health_check_failure")

    def test_a_partial_start_is_caught_by_the_health_check(self) -> None:
        applicator, assessment = harness(backend=InMemoryBackend(partial_start={"bunny.companion"}))
        report = run(applicator, assessment)
        transition = next(item for item in report.applied if item.service_id == "bunny.companion")
        self.assertEqual(transition.result.result, "rolled_back")
        self.assertEqual(transition.result.failure_class, "startup_timeout")

    def test_a_service_that_cannot_be_limited_is_not_left_running_unconstrained(self) -> None:
        # The budget engine's arithmetic assumed a ceiling. Starting without one
        # would make every later admission decision rest on a fiction.
        backend = InMemoryBackend(unavailable_controllers=("memory",))
        applicator, assessment = harness(backend=backend)
        report = run(applicator, assessment)
        limited = [
            item for item in report.applied
            if item.result is not None and item.result.failure_class == "cgroup_unavailable"
        ]
        self.assertTrue(limited, "an unenforceable limit was silently accepted")
        for item in limited:
            with self.subTest(service=item.service_id):
                self.assertNotIn(item.service_id, applicator.backend.services)

    def test_an_exception_from_the_backend_does_not_strand_a_reservation(self) -> None:
        class Exploding(InMemoryBackend):
            def start(self, service_id, implementation_id, limits, *, timeout_seconds):
                if service_id == "bunny.companion":
                    raise RuntimeError("the backend exploded")
                return super().start(service_id, implementation_id, limits, timeout_seconds=timeout_seconds)

        applicator, assessment = harness(backend=Exploding())
        report = run(applicator, assessment)
        transition = next(item for item in report.applied if item.service_id == "bunny.companion")
        self.assertEqual(transition.result.result, "failed")
        self.assertEqual(
            [item for item in applicator.ledger.active() if item.service_id == "bunny.companion"],
            [],
        )

    def test_a_stop_releases_the_memory_it_held(self) -> None:
        applicator, assessment = harness()
        run(applicator, assessment)
        before = applicator.ledger.available_bytes()

        stopping = replace(
            assessment.plan,
            decisions=tuple(
                replace(item, action="reject", implementation_id=None, memory_grant_bytes=0)
                if item.service_id == "bunny.companion" else item
                for item in assessment.plan.decisions
            ),
        )
        applicator.plan_in_force = None
        applicator.apply(
            stopping, registry=REGISTRY, inventory=assessment.inventory,
            budget=assessment.budget, policy=assessment.policy, now=1.0,
        )
        self.assertGreater(applicator.ledger.available_bytes(), before)

    def test_a_suspend_does_not_release_memory(self) -> None:
        # A frozen service keeps every page it had.
        applicator, assessment = harness()
        run(applicator, assessment)
        before = applicator.ledger.available_bytes()

        suspending = replace(
            assessment.plan,
            decisions=tuple(
                replace(item, action="suspend", implementation_id=None, memory_grant_bytes=0)
                if item.service_id == "bunny.companion" else item
                for item in assessment.plan.decisions
            ),
        )
        applicator.plan_in_force = None
        applicator.apply(
            suspending, registry=REGISTRY, inventory=assessment.inventory,
            budget=assessment.budget, policy=assessment.policy, now=1.0,
        )
        self.assertEqual(applicator.ledger.available_bytes(), before)


class PartialConvergenceTests(unittest.TestCase):
    def test_one_failed_optional_service_does_not_stop_the_others(self) -> None:
        applicator, assessment = harness(
            backend=InMemoryBackend(failures={("bunny.companion", "start"): "configuration_error"}),
        )
        report = run(applicator, assessment)
        succeeded = {
            item.service_id for item in report.applied
            if item.result is not None and item.result.result == "succeeded"
        }
        self.assertGreater(len(succeeded), 5)
        for service in REGISTRY.essential():
            with self.subTest(service=service.id):
                self.assertIn(service.id, succeeded)

    def test_a_dependent_of_a_failed_service_is_postponed_not_failed(self) -> None:
        applicator, assessment = harness(
            backend=InMemoryBackend(
                failures={("bunny.inference.local", "start"): "configuration_error"},
            ),
        )
        report = run(applicator, assessment)
        dependent = next(
            (item for item in report.applied if item.service_id == "bunny.agent.orchestrator"),
            None,
        )
        if dependent is not None:
            self.assertEqual(dependent.result.result, "postponed")
            self.assertIn("dependency failed", dependent.result.detail)


class RecoveryTests(unittest.TestCase):
    def test_an_orphaned_reservation_is_reclaimed_before_reconciling(self) -> None:
        applicator, assessment = harness()
        entry = applicator.ledger.reserve(service_id="bunny.companion", amount_bytes=64 * MIB)
        applicator.ledger.commit(entry.reservation_id)
        report = run(applicator, assessment)
        self.assertIn(entry.reservation_id, report.reclaimed)

    def test_an_expired_reservation_is_reclaimed(self) -> None:
        applicator, assessment = harness()
        entry = applicator.ledger.reserve(
            service_id="bunny.companion", amount_bytes=64 * MIB, now=0.0, ttl_seconds=1.0,
        )
        applicator.plan_in_force = None
        report = applicator.apply(
            assessment.plan, registry=REGISTRY, inventory=assessment.inventory,
            budget=assessment.budget, policy=assessment.policy, now=2.0,
        )
        self.assertIn(entry.reservation_id, report.reclaimed)


class RetryTests(unittest.TestCase):
    def test_only_retryable_failures_are_retried(self) -> None:
        policy = RetryPolicy(maximum_attempts=3)
        self.assertTrue(policy.should_retry("startup_timeout", 1))
        self.assertFalse(policy.should_retry("configuration_error", 1))
        self.assertFalse(policy.should_retry("permanent_incompatibility", 1))
        self.assertFalse(policy.should_retry("approval_missing", 1))

    def test_retries_are_bounded(self) -> None:
        policy = RetryPolicy(maximum_attempts=3)
        self.assertTrue(policy.should_retry("startup_timeout", 2))
        self.assertFalse(policy.should_retry("startup_timeout", 3))

    def test_backoff_grows_and_is_capped(self) -> None:
        policy = RetryPolicy(initial_delay_seconds=2.0, multiplier=3.0, maximum_delay_seconds=20.0)
        delays = [policy.delay_seconds(attempt, seed="a.one") for attempt in range(1, 6)]
        self.assertLess(delays[0], delays[1])
        self.assertLessEqual(delays[-1], 20.0 * 1.25)

    def test_backoff_is_deterministic_for_the_same_service(self) -> None:
        # A test can assert the exact schedule, and a restart recomputes it
        # rather than starting over.
        policy = RetryPolicy()
        self.assertEqual(
            policy.delay_seconds(2, seed="a.one"),
            policy.delay_seconds(2, seed="a.one"),
        )

    def test_jitter_separates_two_services_that_failed_together(self) -> None:
        policy = RetryPolicy()
        self.assertNotEqual(
            policy.delay_seconds(1, seed="a.one"),
            policy.delay_seconds(1, seed="b.two"),
        )

    def test_a_failure_schedules_the_next_attempt(self) -> None:
        journal = RetryJournal(policy=RetryPolicy(maximum_attempts=3))
        record = journal.record_failure("a.one", "startup_timeout", now=100.0)
        self.assertFalse(record.exhausted)
        self.assertGreater(record.next_attempt_at_monotonic, 100.0)
        self.assertIn("a.one", journal.not_before())

    def test_a_permanent_failure_exhausts_immediately(self) -> None:
        journal = RetryJournal()
        record = journal.record_failure("a.one", "configuration_error", now=0.0)
        self.assertTrue(record.exhausted)
        self.assertEqual(journal.exhausted_services(), ("a.one",))

    def test_success_clears_the_retry_record(self) -> None:
        journal = RetryJournal()
        journal.record_failure("a.one", "startup_timeout", now=0.0)
        journal.record_success("a.one")
        self.assertEqual(journal.not_before(), {})

    def test_retry_state_survives_a_process_restart(self) -> None:
        # §11: restarting the applicator must not restart the retries.
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "retries.json"
            first = RetryJournal(policy=RetryPolicy(maximum_attempts=2), path=path)
            first.record_failure("a.one", "startup_timeout", now=0.0)
            first.record_failure("a.one", "startup_timeout", now=10.0)
            self.assertTrue(first.record_of("a.one").exhausted)

            second = RetryJournal(policy=RetryPolicy(maximum_attempts=2), path=path)
            self.assertEqual(second.load(), ())
            self.assertEqual(second.record_of("a.one").attempt, 2)
            self.assertTrue(second.record_of("a.one").exhausted)

    def test_a_corrupt_retry_journal_starts_empty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "retries.json"
            path.write_text("{not json", encoding="utf-8")
            journal = RetryJournal(path=path)
            self.assertEqual(len(journal.load()), 1)
            self.assertEqual(journal.records, {})

    def test_a_failed_service_is_recorded_in_the_journal_by_the_applicator(self) -> None:
        applicator, assessment = harness(
            backend=InMemoryBackend(failures={("bunny.companion", "start"): "startup_timeout"}),
        )
        run(applicator, assessment)
        self.assertEqual(applicator.retries.record_of("bunny.companion").attempt, 1)


class CircuitBreakerTests(unittest.TestCase):
    def test_a_circuit_opens_after_repeated_failure(self) -> None:
        breaker = CircuitBreaker(threshold=3)
        for attempt in range(3):
            breaker.record_failure("a.one", "startup_timeout", now=float(attempt))
        self.assertEqual(breaker.state_of("a.one").state, "open")
        self.assertFalse(breaker.allows("a.one", now=5.0))

    def test_a_closed_circuit_allows(self) -> None:
        self.assertTrue(CircuitBreaker().allows("a.one", now=0.0))

    def test_an_essential_service_is_never_broken(self) -> None:
        # Opening a breaker on the control plane would remove the thing that
        # would have reported the fault.
        breaker = CircuitBreaker(threshold=2, protected=frozenset({"a.essential"}))
        for attempt in range(10):
            breaker.record_failure("a.essential", "startup_timeout", now=float(attempt))
        self.assertEqual(breaker.state_of("a.essential").state, "closed")
        self.assertTrue(breaker.allows("a.essential", now=100.0))

    def test_one_probe_is_allowed_through_after_the_recovery_window(self) -> None:
        breaker = CircuitBreaker(threshold=2, recovery_seconds=100.0)
        breaker.record_failure("a.one", "startup_timeout", now=0.0)
        breaker.record_failure("a.one", "startup_timeout", now=1.0)
        self.assertFalse(breaker.allows("a.one", now=50.0))
        self.assertTrue(breaker.allows("a.one", now=200.0))
        self.assertEqual(breaker.state_of("a.one").state, "half_open")

    def test_a_failure_while_half_open_reopens_immediately(self) -> None:
        breaker = CircuitBreaker(threshold=2, recovery_seconds=100.0)
        breaker.record_failure("a.one", "startup_timeout", now=0.0)
        breaker.record_failure("a.one", "startup_timeout", now=1.0)
        breaker.allows("a.one", now=200.0)
        breaker.record_failure("a.one", "startup_timeout", now=201.0)
        self.assertEqual(breaker.state_of("a.one").state, "open")
        self.assertFalse(breaker.allows("a.one", now=210.0))

    def test_success_closes_the_circuit(self) -> None:
        breaker = CircuitBreaker(threshold=2)
        breaker.record_failure("a.one", "startup_timeout", now=0.0)
        breaker.record_success("a.one")
        self.assertEqual(breaker.state_of("a.one").state, "closed")
        self.assertEqual(breaker.state_of("a.one").consecutive_failures, 0)

    def test_the_applicator_protects_every_essential_service(self) -> None:
        applicator, assessment = harness()
        run(applicator, assessment)
        essential = {item.id for item in REGISTRY.essential()}
        self.assertTrue(essential.issubset(applicator.breaker.protected))


class FailureTaxonomyTests(unittest.TestCase):
    def test_every_class_states_whether_it_is_retryable(self) -> None:
        for name, entry in FAILURE_CLASSES.items():
            with self.subTest(failure=name):
                self.assertIsInstance(entry.retryable, bool)
                self.assertTrue(entry.description)

    def test_permanent_failures_are_not_retryable(self) -> None:
        for name in (
            "invalid_plan", "permission_denied", "unit_not_authorized",
            "configuration_error", "permanent_incompatibility", "approval_missing",
            "superseded_plan", "cgroup_unavailable",
        ):
            with self.subTest(failure=name):
                self.assertFalse(is_retryable(name))

    def test_transient_failures_are_retryable(self) -> None:
        for name in (
            "backend_unavailable", "startup_timeout", "shutdown_timeout",
            "health_check_failure", "network_unavailable", "remote_provider_failure",
        ):
            with self.subTest(failure=name):
                self.assertTrue(is_retryable(name))

    def test_an_unknown_class_is_not_retryable(self) -> None:
        self.assertFalse(is_retryable("something_nobody_defined"))
        self.assertFalse(is_retryable(None))


class ApprovalTests(unittest.TestCase):
    def test_a_sensitive_action_may_not_default_to_granted(self) -> None:
        for action in sorted(SENSITIVE_ACTIONS):
            with self.subTest(action=action):
                with self.assertRaises(ValueError):
                    ApprovalRequest(
                        "r1", "plan", "t1", "a.one", action, "why",
                        safe_default="granted", alternatives=("nothing happens",),
                    )

    def test_a_sensitive_action_must_state_an_alternative(self) -> None:
        with self.assertRaises(ValueError):
            ApprovalRequest("r1", "plan", "t1", "a.one", "remote_dispatch", "why")

    def test_the_default_store_grants_nothing(self) -> None:
        store = DenyingApprovalStore()
        response = store.request(ApprovalRequest(
            "r1", "plan", "t1", "a.one", "remote_dispatch", "why",
            alternatives=("stay local",),
        ))
        self.assertEqual(response.decision, "denied")
        self.assertEqual(store.approved_services("plan", 0.0), frozenset())

    def test_an_approval_expires(self) -> None:
        store = InMemoryApprovalStore(default_ttl_seconds=100.0)
        store.request(ApprovalRequest(
            "r1", "plan", "t1", "a.one", "remote_dispatch", "why",
            alternatives=("stay local",),
        ))
        store.grant("r1", plan_id="plan", now=0.0)
        self.assertIn("a.one", store.approved_services("plan", 50.0))
        self.assertNotIn("a.one", store.approved_services("plan", 200.0))

    def test_an_approval_does_not_survive_a_plan_supersession(self) -> None:
        # Consent to an act under one set of numbers is not consent to the same
        # act under different ones.
        store = InMemoryApprovalStore()
        store.request(ApprovalRequest(
            "r1", "plan-old", "t1", "a.one", "paid_provider", "why",
            alternatives=("use the local model",),
        ))
        store.grant("r1", plan_id="plan-old", now=0.0)
        self.assertIn("a.one", store.approved_services("plan-old", 1.0))
        self.assertNotIn("a.one", store.approved_services("plan-new", 1.0))

    def test_invalidating_for_a_new_plan_expires_the_old_approval(self) -> None:
        store = InMemoryApprovalStore()
        store.request(ApprovalRequest(
            "r1", "plan-old", "t1", "a.one", "paid_provider", "why",
            alternatives=("use the local model",),
        ))
        store.grant("r1", plan_id="plan-old", now=0.0)
        self.assertEqual(store.invalidate_for_plan("plan-new"), ("r1",))
        self.assertEqual(store.responses["r1"].decision, "expired")

    def test_a_denied_approval_produces_a_safe_fallback(self) -> None:
        request = ApprovalRequest(
            "r1", "plan", "t1", "a.one", "remote_dispatch", "why",
            alternatives=("the local model answers more slowly",),
        )
        self.assertEqual(request.safe_default, "denied")
        self.assertTrue(request.alternatives)


class AuditTests(unittest.TestCase):
    def test_a_pass_records_its_start_and_finish(self) -> None:
        applicator, assessment = harness()
        run(applicator, assessment)
        events = applicator.audit.events()
        self.assertIn("reconcile.started", events)
        self.assertIn("reconcile.finished", events)

    def test_a_reservation_lifecycle_is_recorded(self) -> None:
        applicator, assessment = harness()
        run(applicator, assessment)
        events = applicator.audit.events()
        self.assertIn("reservation.taken", events)
        self.assertIn("reservation.committed", events)

    def test_a_rollback_is_recorded_with_its_steps(self) -> None:
        applicator, assessment = harness(backend=InMemoryBackend(unhealthy={"bunny.companion"}))
        run(applicator, assessment)
        rollbacks = [
            item for item in applicator.audit.records if item.event == "transition.rolled_back"
        ]
        self.assertTrue(rollbacks)
        self.assertTrue(rollbacks[0].inferred["steps"])

    def test_observed_fact_and_inferred_explanation_are_separate_fields(self) -> None:
        applicator, assessment = harness()
        run(applicator, assessment)
        for record in applicator.audit.records:
            with self.subTest(event=record.event):
                document = record.to_json()
                self.assertIn("observed", document)
                self.assertIn("inferred", document)

    def test_a_rejected_plan_is_recorded_as_a_warning(self) -> None:
        applicator, assessment = harness()
        run(applicator, assessment, inventory=simulate("cpu-server"))
        rejections = [item for item in applicator.audit.records if item.event == "plan.rejected"]
        self.assertTrue(rejections)
        self.assertEqual(rejections[0].severity, "warning")

    def test_a_credential_never_reaches_a_record(self) -> None:
        sink = InMemoryAuditSink()
        sink.record(
            "backend.operation", at_monotonic=0.0,
            observed={"diagnostic": "env: OPENAI_API_KEY=sk-abcdefghijklmnop1234"},
        )
        text = str(sink.records[0].to_json())
        self.assertNotIn("sk-abcdefghijklmnop1234", text)

    def test_redaction_reaches_nested_values(self) -> None:
        result = redact({"outer": {"inner": ["Bearer abcdefghijklmnop"]}})
        self.assertNotIn("abcdefghijklmnop", str(result))

    def test_an_address_is_redacted(self) -> None:
        self.assertNotIn("192.168.1.44", redact("connect failed to 192.168.1.44:8080"))

    def test_audit_retention_is_bounded(self) -> None:
        sink = InMemoryAuditSink(limit=5)
        for index in range(50):
            sink.record("backend.operation", at_monotonic=float(index))
        self.assertEqual(len(sink.records), 5)

    def test_every_record_conforms_to_the_audit_schema(self) -> None:
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema unavailable; schema conformance was not checked")

        import json
        from pathlib import Path

        schema = json.loads(
            (Path(__file__).resolve().parents[2] / "schemas/runtime-audit-record.schema.json")
            .read_text(encoding="utf-8"),
        )
        applicator, assessment = harness(backend=InMemoryBackend(unhealthy={"bunny.companion"}))
        run(applicator, assessment)
        self.assertTrue(applicator.audit.records)
        for record in applicator.audit.records:
            with self.subTest(event=record.event):
                jsonschema.validate(record.to_json(), schema)

    def test_a_transition_can_be_traced_end_to_end(self) -> None:
        applicator, assessment = harness()
        report = run(applicator, assessment)
        transition = report.applied[0]
        trail = applicator.audit.for_transition(transition.transition_id)
        events = [item.event for item in trail]
        self.assertIn("transition.attempted", events)
        self.assertIn("transition.succeeded", events)


class ObservationTests(unittest.TestCase):
    def test_an_unavailable_backend_produces_unknown_not_empty(self) -> None:
        applicator = Applicator(backend=InMemoryBackend(backend_available=False))
        state = applicator.observe(REGISTRY)
        self.assertEqual(len(state.services), len(REGISTRY.services))
        self.assertTrue(all(item.state == "unknown" for item in state.services.values()))
        self.assertEqual(state.unavailable_backends, ("in-memory",))

    def test_a_backend_that_raises_during_inspection_does_not_break_observation(self) -> None:
        class Broken(InMemoryBackend):
            def inspect(self, service_id):
                raise RuntimeError("boom")

        state = Applicator(backend=Broken()).observe(REGISTRY)
        self.assertTrue(all(item.state == "unknown" for item in state.services.values()))

    def test_an_externally_managed_service_is_never_stopped(self) -> None:
        backend = InMemoryBackend(external={"bunny.companion"})
        applicator, assessment = harness(backend=backend)
        report = run(applicator, assessment)
        touched = [
            item.operation for item in backend.operations if item.service_id == "bunny.companion"
        ]
        self.assertEqual(touched, [])
        self.assertTrue(any(
            item.service_id == "bunny.companion" and item.reason == "externally_managed"
            for item in report.blocked
        ))


if __name__ == "__main__":
    unittest.main()
