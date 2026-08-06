# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Health, usage and the journal: failure is counted, spending is pre-checked.

Three §16/§17/§19 stances, each asserted where the code holds it. The circuit
breaker's two asymmetries — authentication never closes on a timer, rate
limiting opens on the first refusal — are tested as behaviour, not as
constants, because the constants could hold while the behaviour drifted. The
ledger's ceilings are tested *before* the generation they would refuse,
because a ceiling noticed afterwards has already been spent through. And the
journal's reconcile is tested for what it does not do: nothing here retries an
interrupted generation, it only names the interruption.
"""

from __future__ import annotations

import os
import tempfile
import threading
import unittest
from pathlib import Path

from companion.agents.errors import AgentSchemaError, GenerationBudgetExceeded
from companion.agents.health import (
    AUTH_OPEN_SECONDS,
    MAX_RETRY_HINT_SECONDS,
    OPEN_SECONDS,
    CircuitBreaker,
    ProviderHealthMonitor,
)
from companion.agents.journal import GenerationJournal, reconcile
from companion.agents.usage import UsageLedger, UsageReport


def _failures(breaker: CircuitBreaker, count: int, monotonic: float = 0.0) -> None:
    for _ in range(count):
        breaker.record_failure("connection", monotonic)


class CircuitBreakerStates(unittest.TestCase):
    def test_the_threshold_of_consecutive_failures_opens_the_circuit(self) -> None:
        breaker = CircuitBreaker()
        _failures(breaker, breaker.failure_threshold - 1)
        self.assertEqual(breaker.state, "closed")
        breaker.record_failure("connection", 0.0)
        self.assertEqual(breaker.state, "open")

    def test_a_success_resets_the_consecutive_count(self) -> None:
        breaker = CircuitBreaker()
        _failures(breaker, breaker.failure_threshold - 1)
        breaker.record_success()
        _failures(breaker, breaker.failure_threshold - 1)
        self.assertEqual(breaker.state, "closed")

    def test_an_open_circuit_refuses_with_the_reason(self) -> None:
        breaker = CircuitBreaker()
        _failures(breaker, breaker.failure_threshold)
        allowed, why = breaker.allows(1.0)
        self.assertFalse(allowed)
        self.assertIn("connection", why)

    def test_after_the_open_window_exactly_one_probe_is_admitted(self) -> None:
        breaker = CircuitBreaker()
        _failures(breaker, breaker.failure_threshold)
        allowed, _ = breaker.allows(OPEN_SECONDS - 0.1)
        self.assertFalse(allowed)
        allowed, why = breaker.allows(OPEN_SECONDS)
        self.assertTrue(allowed)
        self.assertEqual(why, "")
        # The probe is outstanding: a second attempt in the same window waits.
        allowed, why = breaker.allows(OPEN_SECONDS + 0.1)
        self.assertFalse(allowed)
        self.assertIn("probe already in flight", why)

    def test_a_successful_probe_closes_the_circuit(self) -> None:
        breaker = CircuitBreaker()
        _failures(breaker, breaker.failure_threshold)
        self.assertTrue(breaker.allows(OPEN_SECONDS)[0])
        breaker.record_success()
        self.assertEqual(breaker.state, "closed")
        self.assertTrue(breaker.allows(OPEN_SECONDS + 0.1)[0])

    def test_a_failed_probe_reopens_the_full_window(self) -> None:
        breaker = CircuitBreaker()
        _failures(breaker, breaker.failure_threshold)
        self.assertTrue(breaker.allows(OPEN_SECONDS)[0])
        breaker.record_failure("connection", OPEN_SECONDS + 1.0)
        self.assertEqual(breaker.state, "open")
        self.assertFalse(breaker.allows(OPEN_SECONDS + 1.0 + OPEN_SECONDS - 0.1)[0])
        self.assertTrue(breaker.allows(OPEN_SECONDS + 1.0 + OPEN_SECONDS)[0])

    def test_an_authentication_failure_requires_intervention_not_patience(self) -> None:
        """A wrong key at 09:00 is a wrong key at 09:05."""
        breaker = CircuitBreaker()
        breaker.record_failure("authentication", 0.0)
        self.assertEqual(breaker.state, "open")
        self.assertTrue(breaker.requires_intervention)
        allowed, why = breaker.allows(AUTH_OPEN_SECONDS - 0.1)
        self.assertFalse(allowed)
        self.assertIn("credential", why)
        self.assertTrue(breaker.allows(AUTH_OPEN_SECONDS)[0])

    def test_a_rate_limit_opens_on_the_first_failure_without_a_threshold(self) -> None:
        """One 429 is the provider saying stop; counting first would be continuing."""
        breaker = CircuitBreaker()
        breaker.record_failure("rate-limit", 0.0)
        self.assertEqual(breaker.state, "open")

    def test_a_retry_hint_is_honoured_but_bounded(self) -> None:
        hinted = CircuitBreaker()
        hinted.record_failure("rate-limit", 0.0, retry_hint_seconds=120.0)
        self.assertFalse(hinted.allows(119.9)[0])
        self.assertTrue(hinted.allows(120.0)[0])
        hostile = CircuitBreaker()
        hostile.record_failure("rate-limit", 0.0, retry_hint_seconds=604800.0)
        self.assertFalse(hostile.allows(MAX_RETRY_HINT_SECONDS - 0.1)[0])
        self.assertTrue(hostile.allows(MAX_RETRY_HINT_SECONDS)[0])

    def test_an_unnamed_failure_kind_cannot_be_recorded(self) -> None:
        """A failure that cannot be named cannot be counted."""
        with self.assertRaises(AgentSchemaError):
            CircuitBreaker().record_failure("weather", 0.0)


class HealthMonitorAccounting(unittest.TestCase):
    def test_failures_are_counted_by_kind_per_provider(self) -> None:
        monitor = ProviderHealthMonitor()
        monitor.record_failure("local.scripted", "connection", 0.0)
        monitor.record_failure("local.scripted", "connection", 1.0)
        monitor.record_failure("local.scripted", "timeout", 2.0)
        report = monitor.report("local.scripted")
        self.assertEqual(report["failureCounts"], {"connection": 2, "timeout": 1})

    def test_the_reports_mapping_names_every_known_provider(self) -> None:
        monitor = ProviderHealthMonitor()
        monitor.record_failure("local.one", "timeout", 0.0, detail="slow")
        monitor.record_success("local.two")
        reports = monitor.reports()
        self.assertEqual(sorted(reports), ["local.one", "local.two"])
        for provider_id, report in reports.items():
            self.assertEqual(report["providerId"], provider_id)
            self.assertIn("circuit", report)
            self.assertIn("failureCounts", report)
            self.assertIn("lastFailureDetail", report)

    def test_concurrent_recording_loses_no_count(self) -> None:
        monitor = ProviderHealthMonitor()

        def hammer() -> None:
            for index in range(100):
                monitor.record_failure("local.scripted", "connection", float(index))

        threads = [threading.Thread(target=hammer) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        report = monitor.report("local.scripted")
        self.assertEqual(report["failureCounts"]["connection"], 200)


class UsageReportSchema(unittest.TestCase):
    def test_an_unknown_basis_is_refused(self) -> None:
        with self.assertRaises(AgentSchemaError):
            UsageReport(request_id="gen-1", provider_id="p", basis="guessed")

    def test_negative_units_are_refused(self) -> None:
        with self.assertRaises(AgentSchemaError):
            UsageReport(request_id="gen-1", provider_id="p", output_units=-1)

    def test_a_currency_amount_without_a_currency_is_not_an_amount(self) -> None:
        with self.assertRaises(AgentSchemaError):
            UsageReport(request_id="gen-1", provider_id="p",
                        reported_currency_amount=0.02)

    def test_spent_units_is_the_higher_of_reported_and_estimated(self) -> None:
        """Conservative in the direction that protects the wallet."""
        report = UsageReport(request_id="gen-1", provider_id="p",
                             reported_cost_units=4, estimated_cost_units=6)
        self.assertEqual(report.spent_units, 6)
        report = UsageReport(request_id="gen-2", provider_id="p",
                             reported_cost_units=9, estimated_cost_units=3)
        self.assertEqual(report.spent_units, 9)


class UsageLedgerCeilings(unittest.TestCase):
    def _report(self, request_id: str, units: int) -> UsageReport:
        return UsageReport(request_id=request_id, provider_id="local.scripted",
                           reported_cost_units=units, basis="reported")

    def test_recording_accumulates_per_task_and_per_session(self) -> None:
        ledger = UsageLedger()
        ledger.record("ses-1", "task-1", self._report("gen-1", 3))
        ledger.record("ses-1", "task-1", self._report("gen-2", 4))
        ledger.record("ses-1", "task-2", self._report("gen-3", 5))
        self.assertEqual(ledger.task_spent_units("task-1"), 7)
        self.assertEqual(ledger.task_spent_units("task-2"), 5)
        self.assertEqual(ledger.session_spent_units("ses-1"), 12)

    def test_an_estimate_that_would_cross_the_task_ceiling_is_refused(self) -> None:
        ledger = UsageLedger()
        ledger.record("ses-1", "task-1", self._report("gen-1", 8))
        with self.assertRaises(GenerationBudgetExceeded) as caught:
            ledger.check_budget(session_id="ses-1", task_id="task-1",
                                task_limit_units=10, session_limit_units=100,
                                next_generation_estimate_units=3)
        self.assertEqual(caught.exception.limit, "task-cost")

    def test_an_estimate_that_would_cross_the_session_ceiling_is_refused(self) -> None:
        ledger = UsageLedger()
        ledger.record("ses-1", "task-1", self._report("gen-1", 8))
        with self.assertRaises(GenerationBudgetExceeded) as caught:
            ledger.check_budget(session_id="ses-1", task_id="task-2",
                                task_limit_units=100, session_limit_units=10,
                                next_generation_estimate_units=3)
        self.assertEqual(caught.exception.limit, "session-cost")

    def test_a_zero_estimate_generation_passes_under_the_ceiling_but_not_over_it(self) -> None:
        ledger = UsageLedger()
        ledger.record("ses-1", "task-1", self._report("gen-1", 8))
        # Under the ceiling a free generation may start.
        ledger.check_budget(session_id="ses-1", task_id="task-1",
                            task_limit_units=10, session_limit_units=100)
        # Once the ledger is over the line, even a free generation is a stop.
        ledger.record("ses-1", "task-1", self._report("gen-2", 3))
        with self.assertRaises(GenerationBudgetExceeded) as caught:
            ledger.check_budget(session_id="ses-1", task_id="task-1",
                                task_limit_units=10, session_limit_units=100)
        self.assertEqual(caught.exception.limit, "task-cost")

    def test_forgetting_a_task_keeps_the_session_total(self) -> None:
        """Per-task detail is bounded memory; the session's spending is history."""
        ledger = UsageLedger()
        ledger.record("ses-1", "task-1", self._report("gen-1", 7))
        ledger.forget_task("task-1")
        self.assertEqual(ledger.task_spent_units("task-1"), 0)
        self.assertEqual(ledger.session_spent_units("ses-1"), 7)


class JournalReconciliation(unittest.TestCase):
    """§19 with a price attached: a paid interruption is named, never repeated."""

    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.path = Path(self._directory.name) / "agents" / "journal.jsonl"
        self.journal = GenerationJournal(self.path)

    def _start(self, request_id: str = "gen-1", *, paid: bool = False) -> None:
        self.journal.record_start(
            request_id=request_id, provider_id="remote.paid" if paid else "local.scripted",
            session_id="ses-1", task_id="task-1", purpose="result",
            remote=paid, paid=paid,
        )

    def test_an_unsettled_paid_start_reconciles_to_interrupted_not_repeated(self) -> None:
        self._start("gen-1", paid=True)
        report = reconcile(self.journal)
        self.assertEqual(report["interruptedCount"], 1)
        self.assertEqual(report["paidInterrupted"], 1)
        self.assertEqual(
            report["interrupted"][0]["disposition"], "interrupted-not-repeated")
        self.assertTrue(report["interrupted"][0]["paid"])

    def test_a_settled_start_is_not_interrupted(self) -> None:
        self._start("gen-1")
        self.journal.record_settled("gen-1", "completed")
        report = reconcile(self.journal)
        self.assertEqual(report["interruptedCount"], 0)
        self.assertEqual(report["paidInterrupted"], 0)

    def test_reconcile_compacts_the_journal_to_nothing(self) -> None:
        """Fully settled history is accounting already acted on."""
        self._start("gen-1")
        self._start("gen-2", paid=True)
        self.journal.record_settled("gen-1", "completed")
        reconcile(self.journal)
        self.assertEqual(self.journal.entries(), ())

    def test_entries_survive_a_corrupt_line_between_valid_ones(self) -> None:
        self._start("gen-1")
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write("{{{not json at all\n")
        self.journal.record_settled("gen-1", "completed")
        entries = self.journal.entries()
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].request_id, "gen-1")
        self.assertEqual(entries[1].disposition, "completed")

    @unittest.skipUnless(os.name == "posix", "POSIX file modes")
    def test_the_journal_file_is_private_to_its_owner(self) -> None:
        self._start("gen-1")
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
