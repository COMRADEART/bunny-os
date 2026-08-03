# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The ten properties §20 requires of the reconciliation engine.

Every test here asserts on a returned value. Nothing in this file starts,
stops or inspects a service, which is the point: reconciliation is a pure
function, and its safety properties are therefore checkable without a machine.
"""

from __future__ import annotations

from dataclasses import replace
import unittest

from capability.apply.reconcile import (
    ReconciliationSettings,
    reconcile,
    start_order,
    stop_order,
)
from capability.apply.state import (
    ActualState,
    DesiredService,
    DesiredState,
    ServiceObservation,
    desired_from_plan,
)
from capability.registry import load_registry
from capability.runtime import assess
from capability.simulate import simulate

MIB = 1024 ** 2
REGISTRY = load_registry()


def service(
    service_id: str, *, run: bool = True, essential: bool = False, priority: int = 50,
    memory: int = 64 * MIB, requires: tuple[str, ...] = (), conflicts: tuple[str, ...] = (),
    implementation: str = "only", suspendable: bool = True, approval: bool = False,
    action: str | None = None, locality: str = "local",
) -> DesiredService:
    return DesiredService(
        service_id=service_id,
        should_run=run,
        implementation_id=implementation if run else None,
        locality=locality if run else "none",
        memory_limit_bytes=memory if run else 0,
        cpu_percent=25.0,
        essential=essential,
        priority=priority,
        requires=requires,
        conflicts_with=conflicts,
        suspendable=suspendable,
        requires_approval=approval,
        action=action or ("start_local" if run else "reject"),
    )


def desired(*services: DesiredService, plan_id: str = "plan-test", revision: int = 1) -> DesiredState:
    return DesiredState(plan_id, revision, {item.service_id: item for item in services})


def running(
    service_id: str, *, implementation: str = "only", memory: int = 64 * MIB,
    state: str = "running", user_facing: bool = False, unsaved: bool = False,
    observed_by: str = "in-memory",
) -> ServiceObservation:
    return ServiceObservation(
        service_id, state,
        implementation_id=implementation,
        memory_limit_bytes=memory,
        enforced_memory_limit_bytes=memory,
        user_facing=user_facing,
        holds_unsaved_work=unsaved,
        observed_by=observed_by,
    )


def actual(*observations: ServiceObservation) -> ActualState:
    return ActualState({item.service_id: item for item in observations})


def stopped(*service_ids: str) -> ActualState:
    return actual(*(
        ServiceObservation(item, "stopped", observed_by="in-memory") for item in service_ids
    ))


class EmptyAndConvergedTests(unittest.TestCase):
    """Empty desired and actual state; an already converged system."""

    def test_nothing_desired_and_nothing_running_produces_no_transition(self) -> None:
        result = reconcile(desired(), ActualState())
        self.assertEqual(result.transitions, ())
        self.assertEqual(result.blocked, ())
        self.assertTrue(result.converged)

    def test_a_converged_system_produces_no_transition(self) -> None:
        state = desired(service("a.one"), service("b.two"))
        result = reconcile(state, actual(running("a.one"), running("b.two")))
        self.assertEqual(result.transitions, ())
        self.assertTrue(result.converged)

    def test_a_service_neither_wanted_nor_running_produces_no_transition(self) -> None:
        result = reconcile(desired(service("a.one", run=False)), stopped("a.one"))
        self.assertEqual(result.transitions, ())

    def test_reconciliation_is_idempotent_when_repeated(self) -> None:
        # Applying reconciliation repeatedly to a converged system must cause no
        # new actions, however many times it is called.
        state = desired(service("a.one"), service("b.two"))
        converged = actual(running("a.one"), running("b.two"))
        for attempt in range(5):
            with self.subTest(attempt=attempt):
                self.assertEqual(reconcile(state, converged).transitions, ())


class DependencyOrderingTests(unittest.TestCase):
    """Dependencies start before dependents; dependents stop before dependencies."""

    def test_a_dependency_starts_before_its_dependent(self) -> None:
        state = desired(
            service("a.dependent", requires=("b.dependency",), priority=90),
            service("b.dependency", priority=10),
        )
        result = reconcile(state, stopped("a.dependent", "b.dependency"))
        order = [item.service_id for item in result.transitions]
        self.assertLess(order.index("b.dependency"), order.index("a.dependent"))

    def test_a_dependent_stops_before_the_dependency_it_needs(self) -> None:
        state = desired(
            service("a.dependent", run=False, requires=("b.dependency",)),
            service("b.dependency", run=False),
        )
        result = reconcile(state, actual(running("a.dependent"), running("b.dependency")))
        order = [item.service_id for item in result.transitions]
        self.assertLess(order.index("a.dependent"), order.index("b.dependency"))

    def test_stop_order_is_exactly_the_reverse_of_start_order(self) -> None:
        state = desired(
            service("a.one", requires=("b.two",)),
            service("b.two", requires=("c.three",)),
            service("c.three"),
            service("d.four"),
        )
        self.assertEqual(stop_order(state.services), tuple(reversed(start_order(state.services))))

    def test_a_transitive_dependency_chain_is_ordered_throughout(self) -> None:
        state = desired(
            service("a.one", requires=("b.two",)),
            service("b.two", requires=("c.three",)),
            service("c.three"),
        )
        order = list(start_order(state.services))
        self.assertEqual(order, ["c.three", "b.two", "a.one"])

    def test_a_dependency_cycle_terminates_rather_than_recursing_forever(self) -> None:
        # The registry refuses cycles, but this function also runs against
        # desired states assembled by hand, and a guard that costs one set
        # membership is cheaper than a stack overflow.
        state = desired(
            service("a.one", requires=("b.two",)),
            service("b.two", requires=("a.one",)),
        )
        self.assertEqual(len(start_order(state.services)), 2)

    def test_every_service_appears_exactly_once_in_the_order(self) -> None:
        state = desired_from_plan(assess(simulate("laptop"), registry=REGISTRY).plan, REGISTRY)
        order = start_order(state.services)
        self.assertEqual(len(order), len(set(order)))
        self.assertEqual(set(order), set(state.services))


class DeterminismTests(unittest.TestCase):
    """The same inputs must produce the same transition ordering."""

    def test_repeated_reconciliation_produces_an_identical_order(self) -> None:
        state = desired(*(service(f"s{index}.svc", priority=50) for index in range(12)))
        empty = stopped(*state.services)
        first = [item.transition_id for item in reconcile(state, empty).transitions]
        for attempt in range(5):
            with self.subTest(attempt=attempt):
                self.assertEqual(
                    [item.transition_id for item in reconcile(state, empty).transitions],
                    first,
                )

    def test_declaration_order_does_not_change_transition_order(self) -> None:
        services = [service(f"s{index}.svc", priority=index * 5) for index in range(8)]
        forward = desired(*services)
        backward = desired(*reversed(services))
        self.assertEqual(
            [item.service_id for item in reconcile(forward, stopped(*forward.services)).transitions],
            [item.service_id for item in reconcile(backward, stopped(*backward.services)).transitions],
        )

    def test_equal_priority_is_broken_by_service_id(self) -> None:
        state = desired(service("z.last", priority=50), service("a.first", priority=50))
        order = [item.service_id for item in reconcile(state, stopped("z.last", "a.first")).transitions]
        self.assertEqual(order, ["a.first", "z.last"])

    def test_essential_services_are_ordered_before_optional_ones(self) -> None:
        state = desired(
            service("z.optional", priority=99),
            service("a.essential", essential=True, priority=1),
        )
        order = [item.service_id for item in reconcile(state, stopped("z.optional", "a.essential")).transitions]
        self.assertEqual(order[0], "a.essential")

    def test_stops_are_ordered_before_starts(self) -> None:
        # Everything that yields resources happens before anything that consumes
        # them, so the memory freed by a stop is available to a later start.
        state = desired(service("a.starting"), service("b.stopping", run=False))
        result = reconcile(state, actual(
            ServiceObservation("a.starting", "stopped", observed_by="in-memory"),
            running("b.stopping"),
        ))
        order = [(item.service_id, item.operation) for item in result.transitions]
        self.assertEqual(order, [("b.stopping", "stop"), ("a.starting", "start")])


class ConflictTests(unittest.TestCase):
    """Mutually exclusive services must never run simultaneously."""

    def test_a_plan_wanting_two_conflicting_services_is_refused_entirely(self) -> None:
        state = desired(
            service("a.one", conflicts=("b.two",)),
            service("b.two", conflicts=("a.one",)),
        )
        result = reconcile(state, stopped("a.one", "b.two"))
        self.assertEqual(result.transitions, ())
        self.assertTrue(all(item.reason == "conflict" for item in result.blocked))
        self.assertEqual(result.reevaluation_reason, "apply_time_validation_failed")

    def test_a_start_is_blocked_by_a_running_conflicting_service(self) -> None:
        state = desired(service("a.one", conflicts=("b.two",)), service("b.two", run=False))
        # b.two is running and the plan does not ask to stop it, so a.one waits.
        result = reconcile(
            state,
            actual(ServiceObservation("a.one", "stopped", observed_by="in-memory"), running("b.two")),
            settings=ReconciliationSettings(allow_essential_stop=True),
        )
        starts = [item for item in result.transitions if item.operation == "start"]
        stops = [item for item in result.transitions if item.operation == "stop"]
        self.assertEqual([item.service_id for item in stops], ["b.two"])
        # The stop is ordered first; a.one is held until the next pass observes
        # that its conflict is gone, rather than being started alongside it.
        self.assertEqual(starts, [])
        self.assertEqual(result.block_for("a.one").reason, "conflict")


class ResourceTests(unittest.TestCase):
    """No transition may draw the machine below its protected reserve."""

    def test_a_start_that_does_not_fit_is_blocked_rather_than_attempted(self) -> None:
        state = desired(service("a.big", memory=512 * MIB))
        result = reconcile(
            state, stopped("a.big"),
            settings=ReconciliationSettings(available_bytes=128 * MIB, protected_reserve_bytes=64 * MIB),
        )
        self.assertEqual(result.transitions, ())
        blocked = result.block_for("a.big")
        self.assertEqual(blocked.reason, "waiting_for_resources")
        self.assertIn("protected reserve", blocked.fallback)

    def test_availability_is_projected_across_a_batch_of_starts(self) -> None:
        # Without projection, five services would each be told there is room and
        # four would fail at the ledger.
        state = desired(*(service(f"s{index}.svc", memory=100 * MIB) for index in range(5)))
        result = reconcile(
            state, stopped(*state.services),
            settings=ReconciliationSettings(available_bytes=250 * MIB),
        )
        self.assertEqual(len(result.transitions), 2)
        self.assertEqual(len(result.blocked), 3)

    def test_memory_freed_by_a_stop_funds_a_later_start(self) -> None:
        state = desired(
            service("a.new", memory=200 * MIB),
            service("b.old", run=False),
        )
        result = reconcile(
            state,
            actual(
                ServiceObservation("a.new", "stopped", observed_by="in-memory"),
                running("b.old", memory=256 * MIB),
            ),
            settings=ReconciliationSettings(available_bytes=0),
        )
        operations = [(item.service_id, item.operation) for item in result.transitions]
        self.assertEqual(operations, [("b.old", "stop"), ("a.new", "start")])

    def test_a_suspend_does_not_count_as_freeing_memory(self) -> None:
        # A frozen service keeps every page it had. Counting it as freed would
        # admit the next start against memory that is still occupied.
        state = desired(
            service("a.new", memory=200 * MIB),
            service("b.old", run=False, action="suspend"),
        )
        state = desired(
            service("a.new", memory=200 * MIB),
            replace(state.services["b.old"], action="suspend", should_run=False),
        )
        result = reconcile(
            state,
            actual(
                ServiceObservation("a.new", "stopped", observed_by="in-memory"),
                running("b.old", memory=256 * MIB),
            ),
            settings=ReconciliationSettings(available_bytes=0),
        )
        started = [item for item in result.transitions if item.operation == "start"]
        self.assertEqual(started, [])
        self.assertEqual(result.block_for("a.new").reason, "waiting_for_resources")


class EssentialProtectionTests(unittest.TestCase):
    """The applicator does not take the control plane away on its own judgement."""

    def test_an_essential_service_is_not_stopped_without_an_explicit_allowance(self) -> None:
        state = desired(service("a.essential", run=False, essential=True))
        result = reconcile(state, actual(running("a.essential")))
        self.assertEqual(result.transitions, ())
        self.assertEqual(result.block_for("a.essential").reason, "essential_protected")

    def test_an_essential_service_is_stopped_when_explicitly_allowed(self) -> None:
        state = desired(service("a.essential", run=False, essential=True))
        result = reconcile(
            state, actual(running("a.essential")),
            settings=ReconciliationSettings(
                allow_essential_stop=True,
                approved_interruptions=frozenset({"a.essential"}),
            ),
        )
        self.assertEqual([item.operation for item in result.transitions], ["stop"])

    def test_stopping_an_essential_service_is_classified_user_visible(self) -> None:
        state = desired(service("a.essential", run=False, essential=True))
        result = reconcile(state, actual(running("a.essential")))
        assessment = result.block_for("a.essential").adaptation
        self.assertEqual(assessment.adaptation_class, "user_visible")
        self.assertTrue(assessment.requires_approval)


class UserWorkProtectionTests(unittest.TestCase):
    """A foreground or unsaved-work service is not terminated automatically."""

    def test_a_foreground_service_is_not_stopped_without_approval(self) -> None:
        state = desired(service("a.editor", run=False))
        result = reconcile(state, actual(running("a.editor", user_facing=True)))
        self.assertEqual(result.transitions, ())
        blocked = result.block_for("a.editor")
        self.assertEqual(blocked.reason, "user_work_protected")
        self.assertIn("a person is using this service right now", blocked.detail)

    def test_a_service_holding_unsaved_work_is_not_stopped_without_approval(self) -> None:
        state = desired(service("a.editor", run=False))
        result = reconcile(state, actual(running("a.editor", unsaved=True)))
        self.assertEqual(result.block_for("a.editor").reason, "user_work_protected")

    def test_an_approved_interruption_proceeds(self) -> None:
        state = desired(service("a.editor", run=False))
        result = reconcile(
            state, actual(running("a.editor", user_facing=True)),
            settings=ReconciliationSettings(approved_interruptions=frozenset({"a.editor"})),
        )
        self.assertEqual([item.operation for item in result.transitions], ["stop"])

    def test_an_idle_service_is_stopped_without_an_approval(self) -> None:
        state = desired(service("a.indexer", run=False))
        result = reconcile(state, actual(running("a.indexer")))
        self.assertEqual([item.operation for item in result.transitions], ["stop"])

    def test_a_block_always_states_what_the_user_still_has(self) -> None:
        state = desired(service("a.editor", run=False))
        result = reconcile(state, actual(running("a.editor", unsaved=True)))
        self.assertTrue(result.block_for("a.editor").fallback)


class ApprovalTests(unittest.TestCase):
    def test_a_start_needing_approval_is_blocked_until_it_is_given(self) -> None:
        state = desired(service("a.remote", approval=True))
        result = reconcile(state, stopped("a.remote"))
        self.assertEqual(result.transitions, ())
        self.assertEqual(result.block_for("a.remote").reason, "waiting_for_approval")

    def test_an_approved_start_proceeds(self) -> None:
        state = desired(service("a.remote", approval=True))
        result = reconcile(
            state, stopped("a.remote"),
            settings=ReconciliationSettings(approved_starts=frozenset({"a.remote"})),
        )
        self.assertEqual([item.operation for item in result.transitions], ["start"])


class ObservationSafetyTests(unittest.TestCase):
    """Nothing is acted on with the strength of an inference."""

    def test_an_unobserved_service_is_not_started(self) -> None:
        # Starting a service that may already be running risks two of them.
        state = desired(service("a.one"))
        result = reconcile(state, ActualState())
        self.assertEqual(result.transitions, ())
        self.assertEqual(result.block_for("a.one").reason, "state_unknown")

    def test_an_unobserved_service_is_not_stopped(self) -> None:
        state = desired(service("a.one", run=False))
        unobserved = actual(ServiceObservation(
            "a.one", "running", observed_by="inferred", memory_limit_bytes=64 * MIB,
        ))
        result = reconcile(state, unobserved)
        self.assertEqual(result.transitions, ())
        self.assertEqual(result.block_for("a.one").reason, "state_unknown")

    def test_an_externally_managed_service_is_never_stopped(self) -> None:
        state = desired(service("a.one", run=False))
        result = reconcile(state, actual(ServiceObservation(
            "a.one", "externally_managed", observed_by="systemd",
        )))
        self.assertEqual(result.transitions, ())
        self.assertEqual(result.block_for("a.one").reason, "externally_managed")

    def test_an_externally_managed_service_is_never_started_over(self) -> None:
        state = desired(service("a.one"))
        result = reconcile(state, actual(ServiceObservation(
            "a.one", "externally_managed", observed_by="systemd",
        )))
        self.assertEqual(result.transitions, ())
        self.assertEqual(result.block_for("a.one").reason, "externally_managed")

    def test_an_unavailable_backend_is_reported_rather_than_read_as_empty(self) -> None:
        state = desired(service("a.one"))
        unavailable = ActualState(
            {"a.one": ServiceObservation("a.one", "unknown", observed_by="inferred")},
            unavailable_backends=("systemd",),
        )
        result = reconcile(state, unavailable)
        self.assertEqual(result.transitions, ())
        self.assertTrue(any("systemd" in note for note in result.notes))


class LimitConvergenceTests(unittest.TestCase):
    def test_a_running_service_with_the_wrong_limit_gets_apply_limits(self) -> None:
        state = desired(service("a.one", memory=128 * MIB))
        result = reconcile(state, actual(running("a.one", memory=64 * MIB)))
        self.assertEqual(
            [(item.service_id, item.operation) for item in result.transitions],
            [("a.one", "apply_limits")],
        )

    def test_a_limit_that_was_requested_but_never_enforced_is_not_converged(self) -> None:
        # Treating it as converged would leave the service permanently
        # unconstrained while reporting that everything matched.
        state = desired(service("a.one", memory=128 * MIB))
        unenforced = ServiceObservation(
            "a.one", "running", implementation_id="only",
            memory_limit_bytes=128 * MIB, enforced_memory_limit_bytes=None,
            observed_by="in-memory",
        )
        result = reconcile(state, actual(unenforced))
        self.assertEqual([item.operation for item in result.transitions], ["apply_limits"])

    def test_a_changed_implementation_stops_then_starts(self) -> None:
        state = desired(service("a.one", implementation="lean"))
        result = reconcile(state, actual(running("a.one", implementation="rich")))
        self.assertEqual(
            [(item.service_id, item.operation) for item in result.transitions],
            [("a.one", "stop"), ("a.one", "start")],
        )

    def test_a_suspended_service_wanted_running_is_resumed(self) -> None:
        state = desired(service("a.one"))
        result = reconcile(state, actual(running("a.one", state="suspended")))
        self.assertEqual([item.operation for item in result.transitions], ["resume"])

    def test_a_service_already_starting_is_not_started_twice(self) -> None:
        state = desired(service("a.one"))
        result = reconcile(state, actual(running("a.one", state="starting")))
        self.assertEqual(result.transitions, ())


class BackoffTests(unittest.TestCase):
    def test_a_service_inside_its_backoff_window_is_blocked(self) -> None:
        state = desired(service("a.one"))
        result = reconcile(
            state, stopped("a.one"),
            settings=ReconciliationSettings(retry_not_before={"a.one": 100.0}),
            now=50.0,
        )
        self.assertEqual(result.transitions, ())
        self.assertEqual(result.block_for("a.one").reason, "retry_backoff")

    def test_a_service_past_its_backoff_window_is_attempted(self) -> None:
        state = desired(service("a.one"))
        result = reconcile(
            state, stopped("a.one"),
            settings=ReconciliationSettings(retry_not_before={"a.one": 100.0}),
            now=150.0,
        )
        self.assertEqual([item.operation for item in result.transitions], ["start"])

    def test_an_open_circuit_blocks_a_start(self) -> None:
        state = desired(service("a.one"))
        result = reconcile(
            state, stopped("a.one"),
            settings=ReconciliationSettings(circuit_open=frozenset({"a.one"})),
        )
        self.assertEqual(result.transitions, ())
        self.assertEqual(result.block_for("a.one").reason, "circuit_open")


class PartialConvergenceTests(unittest.TestCase):
    """One blocked service must not prevent unrelated ones from converging."""

    def test_an_unrelated_service_converges_while_another_is_blocked(self) -> None:
        state = desired(
            service("a.blocked", memory=512 * MIB),
            service("b.fine", memory=16 * MIB),
        )
        result = reconcile(
            state, stopped("a.blocked", "b.fine"),
            settings=ReconciliationSettings(available_bytes=64 * MIB),
        )
        self.assertEqual([item.service_id for item in result.transitions], ["b.fine"])
        self.assertEqual([item.service_id for item in result.blocked], ["a.blocked"])

    def test_a_dependent_of_a_blocked_service_is_blocked_but_others_are_not(self) -> None:
        state = desired(
            service("a.blocked", approval=True),
            service("b.dependent", requires=("a.blocked",)),
            service("c.unrelated"),
        )
        result = reconcile(state, stopped("a.blocked", "b.dependent", "c.unrelated"))
        self.assertEqual([item.service_id for item in result.transitions], ["c.unrelated"])
        reasons = {item.service_id: item.reason for item in result.blocked}
        self.assertEqual(reasons["a.blocked"], "waiting_for_approval")
        self.assertEqual(reasons["b.dependent"], "waiting_for_dependency")


class AuthorizationTests(unittest.TestCase):
    def test_an_unauthorized_service_is_neither_started_nor_stopped(self) -> None:
        for should_run, observation in (
            (True, ServiceObservation("a.one", "stopped", observed_by="systemd")),
            (False, running("a.one", observed_by="systemd")),
        ):
            with self.subTest(should_run=should_run):
                state = desired(service("a.one", run=should_run))
                result = reconcile(
                    state, actual(observation),
                    settings=ReconciliationSettings(unauthorized=frozenset({"a.one"})),
                )
                self.assertEqual(result.transitions, ())
                self.assertEqual(result.block_for("a.one").reason, "not_authorized")


class RealRegistryTests(unittest.TestCase):
    """The properties hold against the manifests Bunny OS actually ships."""

    def test_the_shipped_registry_reconciles_deterministically(self) -> None:
        plan = assess(simulate("laptop"), registry=REGISTRY).plan
        state = desired_from_plan(plan, REGISTRY)
        empty = stopped(*state.services)
        first = [item.transition_id for item in reconcile(state, empty).transitions]
        second = [item.transition_id for item in reconcile(state, empty).transitions]
        self.assertEqual(first, second)

    def test_every_shipped_dependency_is_ordered_correctly(self) -> None:
        plan = assess(simulate("gaming-desktop"), registry=REGISTRY).plan
        state = desired_from_plan(plan, REGISTRY)
        order = list(start_order(state.services))
        for manifest in REGISTRY.ordered():
            for dependency in manifest.requires:
                with self.subTest(service=manifest.id, dependency=dependency):
                    self.assertLess(order.index(dependency), order.index(manifest.id))

    def test_the_bare_machine_starts_only_essential_services(self) -> None:
        plan = assess(simulate("embedded-64mb"), registry=REGISTRY).plan
        state = desired_from_plan(plan, REGISTRY)
        result = reconcile(state, stopped(*state.services))
        started = {item.service_id for item in result.transitions if item.operation == "start"}
        self.assertEqual(started, {item.id for item in REGISTRY.essential()})


if __name__ == "__main__":
    unittest.main()
