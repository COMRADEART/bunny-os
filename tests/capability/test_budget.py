# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The resource-budget engine across the whole supported memory range.

§16 names eight memory sizes that must be budgeted correctly. Each is checked
here for the same three properties: the reserve is never allocated, the budget
never exceeds what the machine has, and categories too small to be useful are
reported unfunded rather than given a token allocation.
"""

from __future__ import annotations

import unittest

from capability.budget import (
    ALL_CATEGORIES,
    CATEGORIES,
    ESSENTIAL_CATEGORY,
    MAXIMUM_RESERVE_BYTES,
    MINIMUM_RESERVE_BYTES,
    compute_budget,
)
from capability.policy import Policy
from capability.scores import compute_scores
from capability.simulate import machine, simulate

MIB = 1024 ** 2
GIB = 1024 ** 3

#: The sizes §16 requires a budgeting test for.
SIZES = (64 * MIB, 128 * MIB, 512 * MIB, 1 * GIB, 4 * GIB, 16 * GIB, 64 * GIB)


def budget_for(inventory, policy: Policy | None = None, essential: int = 28 * MIB):
    scores = compute_scores(inventory)
    return compute_budget(inventory, scores, policy or Policy(), essential_floor_bytes=essential)


class MemoryLadderTests(unittest.TestCase):
    def test_every_required_size_produces_a_coherent_budget(self) -> None:
        for size in SIZES:
            with self.subTest(bytes=size):
                budget = budget_for(machine(physical_memory_bytes=size))
                self.assertEqual(budget.usable_bytes, size)
                self.assertGreater(budget.protected_reserve_bytes, 0)
                self.assertLessEqual(
                    budget.allocatable_bytes + budget.protected_reserve_bytes, size,
                    "the budget promised more than the machine has",
                )
                self.assertLessEqual(budget.currently_allocatable_bytes, budget.allocatable_bytes)

    def test_allocatable_memory_rises_monotonically_with_the_machine(self) -> None:
        values = [budget_for(machine(physical_memory_bytes=size)).allocatable_bytes for size in SIZES]
        self.assertEqual(values, sorted(values))

    def test_the_reserve_has_an_absolute_floor_on_tiny_machines(self) -> None:
        # A proportional reserve of 64 MiB is 13 MiB, which is not enough slack
        # for the kernel to reclaim its way out of trouble.
        budget = budget_for(machine(physical_memory_bytes=64 * MIB))
        self.assertGreaterEqual(budget.protected_reserve_bytes, min(MINIMUM_RESERVE_BYTES, 32 * MIB))

    def test_the_reserve_has_a_ceiling_on_large_machines(self) -> None:
        # 20% of 512 GiB would strand a hundred gigabytes for no benefit.
        budget = budget_for(machine(physical_memory_bytes=512 * GIB))
        self.assertEqual(budget.protected_reserve_bytes, MAXIMUM_RESERVE_BYTES)

    def test_the_reserve_never_consumes_the_whole_machine(self) -> None:
        budget = budget_for(machine(physical_memory_bytes=32 * MIB))
        self.assertLessEqual(budget.protected_reserve_bytes, 16 * MIB)
        self.assertGreaterEqual(budget.allocatable_bytes, 0)


class ContainerTests(unittest.TestCase):
    """A constrained container on a powerful host is budgeted as the container."""

    def test_the_cgroup_ceiling_is_what_is_budgeted(self) -> None:
        budget = budget_for(simulate("constrained-container"))
        self.assertEqual(budget.usable_bytes, 512 * MIB)
        self.assertLess(budget.allocatable_bytes, 512 * MIB)
        # Not the host's 512 GiB, which is the whole point.
        self.assertLess(budget.allocatable_bytes, 1 * GIB)

    def test_the_cpu_quota_is_what_is_reported_as_effective_cores(self) -> None:
        self.assertEqual(budget_for(simulate("constrained-container")).effective_cores, 0.5)

    def test_the_container_note_names_the_ceiling(self) -> None:
        scores = compute_scores(simulate("constrained-container"))
        self.assertTrue(any("cgroup ceiling" in note for note in scores["memory_available"].notes))


class CategoryTests(unittest.TestCase):
    def test_categories_too_small_to_use_are_unfunded_not_token_funded(self) -> None:
        budget = budget_for(machine(physical_memory_bytes=64 * MIB))
        inference = budget.categories["local_ai_inference"]
        self.assertFalse(inference.funded)
        self.assertEqual(inference.bytes_allowed, 0)
        self.assertIn("floor", inference.reason)

    def test_a_capable_machine_funds_the_expensive_categories(self) -> None:
        budget = budget_for(machine(physical_memory_bytes=64 * GIB))
        for name in ("local_ai_inference", "companion_rendering", "speech_recognition", "user_applications"):
            with self.subTest(category=name):
                self.assertTrue(budget.categories[name].funded)
                self.assertGreater(budget.categories[name].bytes_allowed, 0)

    def test_funded_categories_never_exceed_the_discretionary_pool(self) -> None:
        for size in SIZES:
            with self.subTest(bytes=size):
                budget = budget_for(machine(physical_memory_bytes=size))
                total = sum(item.bytes_allowed for item in budget.categories.values())
                pool = max(0, budget.allocatable_bytes - budget.essential_services_bytes)
                self.assertLessEqual(total, pool + 1)

    def test_every_declared_category_appears_in_every_budget(self) -> None:
        budget = budget_for(machine(physical_memory_bytes=4 * GIB))
        self.assertEqual(set(budget.categories), set(CATEGORIES))

    def test_the_essential_category_is_not_part_of_the_discretionary_split(self) -> None:
        # Essential memory is taken off the top; a category that could be
        # outbid by an optional service would not be essential.
        self.assertIn(ESSENTIAL_CATEGORY, ALL_CATEGORIES)
        self.assertNotIn(ESSENTIAL_CATEGORY, CATEGORIES)


class ViabilityTests(unittest.TestCase):
    def test_a_machine_that_cannot_fund_its_control_plane_is_not_viable(self) -> None:
        budget = budget_for(machine(physical_memory_bytes=64 * MIB), essential=2 * GIB)
        self.assertFalse(budget.viable)
        self.assertGreater(budget.essential_shortfall_bytes, 0)
        self.assertTrue(any("control plane" in note for note in budget.notes))

    def test_the_shipped_essential_floor_fits_on_the_smallest_supported_machine(self) -> None:
        from capability.registry import load_registry

        registry = load_registry()
        budget = budget_for(
            machine(physical_memory_bytes=64 * MIB, available_memory_bytes=44 * MIB),
            essential=registry.essential_floor_bytes(),
        )
        self.assertTrue(
            budget.viable,
            f"the essential floor of {registry.essential_floor_bytes() // MIB} MiB does not fit "
            f"in the {budget.allocatable_bytes // MIB} MiB allocatable on a 64 MB device",
        )


class UnmeasuredTests(unittest.TestCase):
    def test_unmeasured_memory_funds_essential_services_and_nothing_else(self) -> None:
        budget = budget_for(simulate("unmeasurable"))
        self.assertIsNone(budget.usable_bytes)
        self.assertEqual(budget.currently_allocatable_bytes, 0)
        self.assertEqual(budget.essential_services_bytes, 28 * MIB)
        self.assertEqual(budget.confidence, "unknown")
        self.assertFalse(budget.gpu_local_inference_allowed)
        self.assertFalse(budget.gpu_rendering_allowed)
        self.assertTrue(all(not item.funded for item in budget.categories.values()))

    def test_unmeasured_memory_does_not_crash_and_states_why(self) -> None:
        budget = budget_for(simulate("unmeasurable"))
        self.assertTrue(any("could not be measured" in note for note in budget.notes))


class GpuPermissionTests(unittest.TestCase):
    def test_a_driverless_gpu_grants_no_permission(self) -> None:
        budget = budget_for(simulate("gpu-without-driver"))
        self.assertFalse(budget.gpu_local_inference_allowed)
        self.assertFalse(budget.gpu_rendering_allowed)
        self.assertTrue(any("none with both a bound driver" in reason for reason in budget.gpu_reasons))

    def test_rendering_is_refused_when_headless_even_with_a_capable_gpu(self) -> None:
        budget = budget_for(simulate("multi-gpu-ai-server"))
        self.assertTrue(budget.gpu_local_inference_allowed)
        self.assertFalse(budget.gpu_rendering_allowed)
        self.assertTrue(any("no display is connected" in reason for reason in budget.gpu_reasons))

    def test_a_shared_memory_gpu_does_not_permit_local_inference(self) -> None:
        budget = budget_for(simulate("laptop"))
        self.assertFalse(budget.gpu_local_inference_allowed)
        self.assertTrue(budget.gpu_rendering_allowed)

    def test_prefer_low_energy_withdraws_gpu_inference_permission(self) -> None:
        inventory = simulate("gaming-desktop")
        self.assertTrue(budget_for(inventory).gpu_local_inference_allowed)
        frugal = budget_for(inventory, Policy(prefer_low_energy=True))
        self.assertFalse(frugal.gpu_local_inference_allowed)
        self.assertTrue(any("preferLowEnergy" in reason for reason in frugal.gpu_reasons))


class StorageBudgetTests(unittest.TestCase):
    def test_a_read_only_root_grants_no_cache_or_log_budget(self) -> None:
        budget = budget_for(simulate("read-only-appliance"))
        self.assertEqual(budget.cache_storage_bytes, 0)
        self.assertEqual(budget.log_storage_bytes, 0)
        self.assertTrue(any("read-only" in note for note in budget.notes))

    def test_storage_budgets_never_promise_more_than_is_free(self) -> None:
        budget = budget_for(machine(physical_memory_bytes=4 * GIB, storage_available_bytes=100 * MIB))
        total = budget.cache_storage_bytes + budget.log_storage_bytes + budget.temporary_storage_bytes
        self.assertLessEqual(total, 100 * MIB)


class PolicyConstraintTests(unittest.TestCase):
    """User settings are constraints, and they may only narrow."""

    def test_a_user_memory_ceiling_overrides_the_derived_budget(self) -> None:
        unlimited = budget_for(machine(physical_memory_bytes=16 * GIB))
        capped = budget_for(
            machine(physical_memory_bytes=16 * GIB),
            Policy(maximum_service_memory_bytes=512 * MIB),
        )
        self.assertLess(capped.allocatable_bytes, unlimited.allocatable_bytes)
        self.assertEqual(capped.allocatable_bytes, 512 * MIB)
        self.assertTrue(any("takes precedence" in note for note in capped.notes))

    def test_a_user_ceiling_above_the_derived_budget_does_not_widen_it(self) -> None:
        derived = budget_for(machine(physical_memory_bytes=4 * GIB))
        generous = budget_for(
            machine(physical_memory_bytes=4 * GIB),
            Policy(maximum_service_memory_bytes=64 * GIB),
        )
        self.assertEqual(generous.allocatable_bytes, derived.allocatable_bytes)

    def test_a_user_background_cpu_limit_is_respected(self) -> None:
        budget = budget_for(
            machine(physical_memory_bytes=16 * GIB, logical_threads=16),
            Policy(maximum_background_cpu_percent=5.0),
        )
        self.assertLessEqual(budget.background_cpu_percent, 5.0)

    def test_a_larger_reserve_fraction_shrinks_the_budget(self) -> None:
        default = budget_for(machine(physical_memory_bytes=8 * GIB))
        cautious = budget_for(machine(physical_memory_bytes=8 * GIB), Policy(protected_reserve_fraction=0.5))
        self.assertGreater(cautious.protected_reserve_bytes, default.protected_reserve_bytes)
        self.assertLess(cautious.allocatable_bytes, default.allocatable_bytes)

    def test_prefer_low_energy_halves_background_cpu(self) -> None:
        inventory = machine(physical_memory_bytes=16 * GIB, logical_threads=16)
        normal = budget_for(inventory)
        frugal = budget_for(inventory, Policy(prefer_low_energy=True))
        self.assertLess(frugal.background_cpu_percent, normal.background_cpu_percent)


class LiveMemoryTests(unittest.TestCase):
    """The admission number tracks what is free; the planning number does not."""

    def test_admission_uses_free_memory_when_it_is_the_smaller_number(self) -> None:
        loaded = budget_for(machine(physical_memory_bytes=16 * GIB, available_memory_bytes=1 * GIB))
        self.assertLess(loaded.currently_allocatable_bytes, loaded.allocatable_bytes)
        self.assertTrue(any("free right now" in note for note in loaded.notes))

    def test_the_foreground_workload_is_measured_and_not_assumed_away(self) -> None:
        budget = budget_for(machine(physical_memory_bytes=16 * GIB, available_memory_bytes=4 * GIB))
        self.assertEqual(budget.foreground_workload_bytes, 12 * GIB)

    def test_the_reserve_is_excluded_from_the_admission_number_too(self) -> None:
        budget = budget_for(machine(physical_memory_bytes=8 * GIB, available_memory_bytes=3 * GIB))
        self.assertLessEqual(
            budget.currently_allocatable_bytes,
            3 * GIB - budget.protected_reserve_bytes,
        )

    def test_free_memory_below_the_reserve_admits_nothing_rather_than_going_negative(self) -> None:
        # 1 GiB free against a 1.6 GiB reserve. The machine is already inside
        # its own safety margin, so nothing further may be admitted; a negative
        # budget would be an arithmetic accident, not a safety property.
        budget = budget_for(machine(physical_memory_bytes=8 * GIB, available_memory_bytes=1 * GIB))
        self.assertGreater(budget.protected_reserve_bytes, 1 * GIB)
        self.assertEqual(budget.currently_allocatable_bytes, 0)

    def test_determinism(self) -> None:
        inventory = simulate("laptop")
        self.assertEqual(budget_for(inventory).to_json(), budget_for(inventory).to_json())


if __name__ == "__main__":
    unittest.main()
