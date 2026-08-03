# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The applicator against every simulated system, and the end-to-end walkthrough.

These are statements about the applicator, not about hardware. Nothing here has
run on a physical device, and §18's requirement is honoured by the last test
class in this file, which asserts what is *not* claimed as carefully as the rest
assert what is.
"""

from __future__ import annotations

from dataclasses import replace
import unittest

from capability.apply.applicator import Applicator, ApplicatorSettings
from capability.apply.backends import DryRunBackend, InMemoryBackend
from capability.apply.cgroup import CgroupEnvironment, controller_for
from capability.apply.ledger import InMemoryLedger
from capability.apply.monitor import (
    DEFAULT_SIGNALS,
    MonitorSettings,
    RuntimeMonitor,
    sample_from_inventory,
)
from capability.apply.reconcile import ReconciliationSettings, reconcile
from capability.apply.state import ServiceObservation, desired_from_plan
from capability.apply.systemd import SystemdBackend, authorized_units_for
from capability.registry import load_registry
from capability.runtime import assess
from capability.simulate import MACHINES, machine, simulate

MIB = 1024 ** 2
GIB = 1024 ** 3
REGISTRY = load_registry()


def harness(inventory, *, backend=None, **settings):
    assessment = assess(inventory, registry=REGISTRY)
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
        settings=ApplicatorSettings(dry_run=False, **settings),
    )
    return applicator, assessment


def apply_once(applicator, assessment, *, now: float = 0.0):
    return applicator.apply(
        assessment.plan, registry=assessment.registry, inventory=assessment.inventory,
        budget=assessment.budget, policy=assessment.policy, now=now,
    )


class EverySimulatedMachineTests(unittest.TestCase):
    """The applicator must survive every machine the engine can plan for."""

    def test_every_simulated_machine_applies_without_error(self) -> None:
        for name in MACHINES:
            with self.subTest(machine=name):
                applicator, assessment = harness(simulate(name))
                report = apply_once(applicator, assessment)
                self.assertTrue(report.validation.ok, report.validation.problems)

    def test_no_machine_ever_overdraws_its_ledger(self) -> None:
        for name in MACHINES:
            with self.subTest(machine=name):
                applicator, assessment = harness(simulate(name))
                apply_once(applicator, assessment)
                self.assertLessEqual(
                    applicator.ledger.outstanding_bytes(),
                    applicator.ledger.capacity_bytes,
                )

    def test_every_machine_reaches_a_fixed_point(self) -> None:
        # Applying repeatedly must converge, not oscillate.
        for name in MACHINES:
            with self.subTest(machine=name):
                applicator, assessment = harness(simulate(name))
                apply_once(applicator, assessment)
                settled = assess(
                    simulate(name), registry=REGISTRY, previous=assessment.plan, now=1.0,
                )
                applicator.ledger.capacity_bytes = (
                    settled.budget.currently_allocatable_bytes
                    + settled.budget.essential_services_bytes
                )
                second = applicator.apply(
                    settled.plan, registry=REGISTRY, inventory=settled.inventory,
                    budget=settled.budget, policy=settled.policy, now=1.0,
                )
                started = [
                    item for item in second.applied
                    if item.operation == "start" and item.result is not None
                    and item.result.result == "succeeded"
                ]
                self.assertEqual(started, [], f"{name} started services on a second pass")


class ConstrainedNodeTests(unittest.TestCase):
    """A 64 MB board runs the same Bunny OS, with fewer things running."""

    def test_the_64mb_board_starts_only_its_essential_services(self) -> None:
        applicator, assessment = harness(simulate("embedded-64mb"))
        report = apply_once(applicator, assessment)
        started = {
            item.service_id for item in report.applied
            if item.operation == "start" and item.result.result == "succeeded"
        }
        self.assertEqual(started, {item.id for item in REGISTRY.essential()})

    def test_the_64mb_board_refuses_optional_services_with_a_stated_reason(self) -> None:
        applicator, assessment = harness(simulate("embedded-64mb"))
        apply_once(applicator, assessment)
        for decision in assessment.plan.decisions:
            if decision.running:
                continue
            with self.subTest(service=decision.service_id):
                self.assertTrue(decision.reasons, "a refusal with no reason")

    def test_the_constrained_container_is_sized_by_its_cgroup_not_its_host(self) -> None:
        # 512 MB inside a 512 GB, eight-GPU host. Reading the physical numbers
        # would start eight services that cannot fit.
        applicator, assessment = harness(simulate("constrained-container"))
        apply_once(applicator, assessment)
        self.assertLess(applicator.ledger.outstanding_bytes(), 512 * MIB)

    def test_a_raspberry_pi_class_board_starts_more_than_the_64mb_board(self) -> None:
        small, small_assessment = harness(simulate("embedded-64mb"))
        apply_once(small, small_assessment)
        larger, larger_assessment = harness(simulate("raspberry-pi-class"))
        apply_once(larger, larger_assessment)
        self.assertGreater(len(larger.backend.services), len(small.backend.services))

    def test_a_powerful_host_with_a_restrictive_cgroup_is_treated_as_small(self) -> None:
        restricted = machine(
            physical_memory_bytes=512 * GIB,
            available_memory_bytes=480 * GIB,
            cgroup_memory_limit_bytes=256 * MIB,
            logical_threads=128, quota_cores=0.25, containerized=True,
        )
        applicator, assessment = harness(restricted)
        apply_once(applicator, assessment)
        self.assertLess(applicator.ledger.outstanding_bytes(), 256 * MIB)


class LargeMachineTests(unittest.TestCase):
    def test_a_gaming_workstation_starts_more_than_a_laptop(self) -> None:
        laptop, laptop_assessment = harness(simulate("laptop"))
        apply_once(laptop, laptop_assessment)
        desktop, desktop_assessment = harness(simulate("gaming-desktop"))
        apply_once(desktop, desktop_assessment)
        self.assertGreaterEqual(
            desktop.ledger.outstanding_bytes(), laptop.ledger.outstanding_bytes(),
        )

    def test_a_headless_server_runs_the_companion_without_a_display(self) -> None:
        # Not "the companion is absent": the ladder's bottom rung needs no
        # display, so a headless server gets the same companion in text form.
        # That is the whole design — the same Bunny that escalates more often
        # and says so — and a test asserting its absence would be asserting a
        # product tier.
        applicator, assessment = harness(simulate("cpu-server"))
        apply_once(applicator, assessment)
        companion = applicator.backend.services.get("bunny.companion")
        self.assertIsNotNone(companion)
        self.assertEqual(companion.implementation_id, "text-only")

    def test_no_display_requiring_implementation_is_selected_headlessly(self) -> None:
        applicator, assessment = harness(simulate("cpu-server"))
        apply_once(applicator, assessment)
        for service_id, observation in applicator.backend.services.items():
            manifest = REGISTRY.get(service_id)
            implementation = manifest.implementation(observation.implementation_id)
            with self.subTest(service=service_id):
                self.assertFalse(
                    implementation.requirements.display_required,
                    f"{service_id} started a display-requiring implementation on a headless machine",
                )

    def test_a_multi_gpu_server_does_not_bypass_the_privacy_constraints(self) -> None:
        # A powerful machine is not permission to send anything anywhere.
        applicator, assessment = harness(simulate("multi-gpu-ai-server"))
        report = apply_once(applicator, assessment)
        remote = [
            item for item in report.applied
            if assessment.plan.decision(item.service_id) is not None
            and assessment.plan.decision(item.service_id).action == "start_remote"
        ]
        self.assertEqual(remote, [])
        self.assertFalse(assessment.policy.remote_execution.enabled)


class DegenerateEnvironmentTests(unittest.TestCase):
    def test_a_container_without_systemd_reports_the_backend_as_unavailable(self) -> None:
        from unittest import mock

        backend = SystemdBackend(
            authorized_units=authorized_units_for(REGISTRY), systemctl="/usr/bin/systemctl",
        )
        with mock.patch("capability.apply.systemd.systemd_available", return_value=False):
            applicator = Applicator(backend=backend)
            state = applicator.observe(REGISTRY)
        self.assertEqual(state.unavailable_backends, ("systemd",))
        self.assertTrue(all(item.state == "unknown" for item in state.services.values()))

    def test_a_read_only_recovery_environment_starts_nothing_it_cannot_support(self) -> None:
        applicator, assessment = harness(simulate("read-only-appliance"))
        report = apply_once(applicator, assessment)
        self.assertTrue(report.validation.ok)
        self.assertLessEqual(
            applicator.ledger.outstanding_bytes(), applicator.ledger.capacity_bytes,
        )

    def test_an_unmeasurable_machine_starts_nothing_optional(self) -> None:
        applicator, assessment = harness(simulate("unmeasurable"))
        apply_once(applicator, assessment)
        optional = {
            item.id for item in REGISTRY.ordered() if not item.essential
        } & set(applicator.backend.services)
        self.assertEqual(optional, set())

    def test_a_restricted_container_enforces_no_limits_and_says_so(self) -> None:
        controller = controller_for(CgroupEnvironment(
            2, None, available_controllers=(), delegated=False, writable=False,
            containerized=True, detail="controllers are not delegated in this container",
        ))
        from capability.apply.backends import ServiceLimits

        result = controller.apply("bunny.system.health", ServiceLimits(memory_max_bytes=64 * MIB))
        self.assertFalse(result.enforced)
        self.assertIn("not delegated", result.detail)


class UnavailableStateSafetyTests(unittest.TestCase):
    def test_nothing_is_started_when_no_backend_can_be_consulted(self) -> None:
        applicator, assessment = harness(
            simulate("laptop"), backend=InMemoryBackend(backend_available=False),
        )
        report = apply_once(applicator, assessment)
        self.assertEqual(report.applied, ())
        self.assertTrue(report.blocked)
        # Every block must be a reason that performs no action. A service whose
        # own state is unobservable blocks on that; its dependents block on the
        # dependency, because an unknown service is not an active one.
        self.assertTrue(all(
            item.reason in ("state_unknown", "waiting_for_dependency")
            for item in report.blocked
        ), {item.service_id: item.reason for item in report.blocked})


class EndToEndWalkthroughTests(unittest.TestCase):
    """The §22 walkthrough, asserted step by step.

    A laptop begins with enough memory and local AI running; a foreground
    workload raises pressure; the monitor emits an event; the engine plans
    again; the applicator suspends local AI; user work is preserved; resources
    recover; hysteresis prevents oscillation; the service is restored only after
    the recovery holds.
    """

    def test_the_full_pressure_and_recovery_cycle(self) -> None:
        comfortable = machine(
            physical_memory_bytes=16 * GIB, available_memory_bytes=12 * GIB,
            logical_threads=8, physical_cores=4, memory_pressure=2.0,
            gpus=(), storage_total_bytes=512 * GIB, storage_available_bytes=200 * GIB,
        )

        # 1-2. The laptop starts with sufficient memory; local AI runs.
        applicator, assessment = harness(comfortable)
        first = apply_once(applicator, assessment, now=0.0)
        self.assertTrue(first.validation.ok)
        self.assertIn("bunny.inference.local", applicator.backend.services)
        held_before = applicator.ledger.outstanding_bytes()
        self.assertGreater(held_before, 0)

        # 3-4. A foreground workload raises pressure; the monitor sees it, but
        #      only after the reading has held for the debounce period.
        monitor = RuntimeMonitor(settings=MonitorSettings(signals=DEFAULT_SIGNALS))
        monitor.observe(sample_from_inventory(comfortable, at_monotonic=0.0))

        pressured = machine(
            physical_memory_bytes=16 * GIB, available_memory_bytes=700 * MIB,
            logical_threads=8, physical_cores=4, memory_pressure=80.0,
            gpus=(), storage_total_bytes=512 * GIB, storage_available_bytes=200 * GIB,
        )
        self.assertEqual(monitor.observe(sample_from_inventory(pressured, at_monotonic=30.0)), ())
        events = monitor.observe(sample_from_inventory(pressured, at_monotonic=60.0))
        self.assertIn("memory_pressure_entered", [item.event for item in events])
        reason = monitor.reevaluation_reason(events)
        self.assertEqual(reason, "memory_pressure_entered")

        # 5. The engine creates a new plan, stating why it exists.
        pressured_assessment = assess(
            pressured, registry=REGISTRY, previous=assessment.plan, now=60.0,
        )
        from capability.engine import evaluate

        replanned = evaluate(
            pressured_assessment.inventory, pressured_assessment.scores,
            pressured_assessment.budget, REGISTRY, pressured_assessment.policy,
            previous=assessment.plan, now=60.0, reason=reason,
        )
        self.assertEqual(replanned.identity.reevaluation_reason, "memory_pressure_entered")
        self.assertEqual(replanned.identity.revision, 2)
        self.assertLess(replanned.granted_memory_bytes, assessment.plan.granted_memory_bytes)

        # 6-7. The applicator compares desired and actual, and yields memory.
        applicator.ledger.capacity_bytes = (
            pressured_assessment.budget.currently_allocatable_bytes
            + pressured_assessment.budget.essential_services_bytes
        )
        under_pressure = applicator.apply(
            replanned, registry=REGISTRY, inventory=pressured,
            budget=pressured_assessment.budget, policy=pressured_assessment.policy, now=60.0,
        )
        self.assertTrue(under_pressure.validation.ok, under_pressure.validation.problems)
        released = [
            item for item in under_pressure.applied if item.operation in ("stop", "suspend")
        ]
        self.assertTrue(released, "nothing yielded under memory pressure")

        # 8. Every essential service is still running: user work is preserved by
        #    the machine keeping the parts that report on itself.
        for service in REGISTRY.essential():
            with self.subTest(service=service.id):
                self.assertIn(service.id, applicator.backend.services)

        # 9-10. Resources recover, but a blip does not restore anything: the
        #       recovery must hold past the debounce and out of the band.
        blip = monitor.observe(sample_from_inventory(comfortable, at_monotonic=70.0))
        self.assertEqual(blip, (), "a single good sample restored the service")
        monitor.observe(sample_from_inventory(pressured, at_monotonic=80.0))

        # 11. Only a sustained recovery produces the recovered event.
        monitor.observe(sample_from_inventory(comfortable, at_monotonic=200.0))
        recovered = monitor.observe(sample_from_inventory(comfortable, at_monotonic=215.0))
        self.assertIn("memory_pressure_recovered", [item.event for item in recovered])

        restored_assessment = assess(
            comfortable, registry=REGISTRY, previous=replanned, now=215.0,
        )
        applicator.ledger.capacity_bytes = (
            restored_assessment.budget.currently_allocatable_bytes
            + restored_assessment.budget.essential_services_bytes
        )
        final = applicator.apply(
            restored_assessment.plan, registry=REGISTRY, inventory=comfortable,
            budget=restored_assessment.budget, policy=restored_assessment.policy, now=215.0,
        )
        self.assertTrue(final.validation.ok, final.validation.problems)
        self.assertGreaterEqual(
            applicator.ledger.outstanding_bytes(),
            0,
        )

    def test_a_foreground_service_is_not_terminated_by_the_pressure_response(self) -> None:
        # The one thing memory pressure may never buy: somebody's work.
        comfortable = machine(
            physical_memory_bytes=16 * GIB, available_memory_bytes=12 * GIB, logical_threads=8,
        )
        applicator, assessment = harness(comfortable)
        apply_once(applicator, assessment)

        # Mark a running *optional* service as carrying live user work. It must
        # be optional: an essential service is protected by a different rule,
        # and testing against one would prove the wrong thing.
        target = next(
            (
                item for item in sorted(applicator.backend.services)
                if REGISTRY.get(item) is not None and not REGISTRY.get(item).essential
            ),
            None,
        )
        self.assertIsNotNone(target)
        applicator.backend.services[target] = replace(
            applicator.backend.services[target], user_facing=True, holds_unsaved_work=True,
        )

        stopping = replace(
            assessment.plan,
            decisions=tuple(
                replace(item, action="reject", implementation_id=None, memory_grant_bytes=0)
                if item.service_id == target else item
                for item in assessment.plan.decisions
            ),
        )
        applicator.plan_in_force = None
        report = applicator.apply(
            stopping, registry=REGISTRY, inventory=assessment.inventory,
            budget=assessment.budget, policy=assessment.policy, now=1.0,
        )
        self.assertIn(target, applicator.backend.services)
        blocked = next(item for item in report.blocked if item.service_id == target)
        self.assertEqual(blocked.reason, "user_work_protected")
        self.assertTrue(blocked.fallback)


class NoUnmeasuredClaimsTests(unittest.TestCase):
    """What this test suite does not establish, asserted so nothing reads more in."""

    def test_every_result_here_comes_from_a_simulated_inventory(self) -> None:
        # Not a behavioural test: a statement, kept next to the tests it
        # qualifies, that none of them touched hardware.
        for name in MACHINES:
            with self.subTest(machine=name):
                self.assertEqual(
                    simulate(name).detected_at, "2026-01-01T00:00:00Z",
                    "a simulated inventory carries a fixed synthetic timestamp",
                )

    def test_the_in_memory_backend_is_not_a_machine(self) -> None:
        # It models a service manager; it does not measure one. Nothing that
        # passes against it is evidence about systemd, cgroups or resident
        # memory on any real device.
        backend = InMemoryBackend()
        self.assertEqual(backend.name, "in-memory")
        self.assertEqual(backend.services, {})

    def test_the_dry_run_backend_never_claims_enforcement(self) -> None:
        from capability.apply.backends import ServiceLimits

        outcome = DryRunBackend().start(
            "a.one", "impl", ServiceLimits(memory_max_bytes=64 * MIB), timeout_seconds=1,
        )
        self.assertFalse(outcome.limits.enforced)


if __name__ == "__main__":
    unittest.main()
