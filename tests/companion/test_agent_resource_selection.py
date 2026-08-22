# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Resource-aware model selection: the derivation, not a tier.

STEP 5's rule is that a small machine gets a smaller local model, a powerful
machine a larger one, and memory pressure downgrades or refuses — with no
invented Low/Medium/Ultra tier. These tests pin the three inputs to that
derivation (available RAM, the pressure band, the model's resident footprint)
and the one property that keeps it honest: when the host cannot be measured,
nothing is refused that was not already refused, so every existing test that
constructs a registry without machine resources is unchanged.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from companion.agents.adapter import ModelListing, ProbeResult
from companion.agents.config import AgentConfiguration, ProviderConfiguration
from companion.agents.descriptor import EndpointIdentity
from companion.agents.registry import AgentProviderRegistry, SelectionRequirement
from companion.agents.resources import (
    CONTEXT_BYTES_PER_TOKEN,
    MachineResources,
    default_machine_resources,
    model_memory_budget,
    model_runtime_footprint,
)

from .agents_support import ScriptedAdapter

_GIB = 1024 ** 3
_MIB = 1024 ** 2


def _sized_provider(*, provider_id: str = "local.sized", model_id: str = "") -> ProviderConfiguration:
    """A subprocess provider with no configured model, so discovery runs."""
    return ProviderConfiguration(
        provider_id=provider_id,
        adapter_id="sized",
        endpoint=EndpointIdentity(kind="subprocess", locator="sized"),
        program="sized",
        model_id=model_id,
    )


def _sized_adapter(models: tuple[ModelListing, ...]) -> ScriptedAdapter:
    return ScriptedAdapter(
        adapter_identity="sized",
        models=models,
        probe_available=True,
        probe_detail="sized runtime",
    )


def _registry(
    models: tuple[ModelListing, ...],
    resources: MachineResources | None,
    *,
    model_id: str = "",
) -> AgentProviderRegistry:
    configuration = AgentConfiguration(providers=(_sized_provider(model_id=model_id),))
    return AgentProviderRegistry(
        configuration,
        {"sized": _sized_adapter(models)},
        machine_resources=resources,
    )


def _requirement() -> SelectionRequirement:
    return SelectionRequirement(task_class="question", locality="device-only")


# --------------------------------------------------------------------------- #
# resources module
# --------------------------------------------------------------------------- #


class MachineResourcesShape(unittest.TestCase):
    def test_available_ram_makes_the_budget_a_constraint(self) -> None:
        self.assertTrue(MachineResources(available_ram_bytes=_GIB).known)

    def test_zero_available_ram_is_unknown_not_a_refusal(self) -> None:
        self.assertFalse(MachineResources(available_ram_bytes=0).known)

    def test_unknown_pressure_level_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            MachineResources(available_ram_bytes=_GIB, memory_pressure_level="huge")

    def test_negative_bytes_are_refused(self) -> None:
        with self.assertRaises(ValueError):
            MachineResources(available_ram_bytes=-1)


class MemoryBudget(unittest.TestCase):
    def test_nominal_is_half_of_available(self) -> None:
        self.assertEqual(
            model_memory_budget(MachineResources(available_ram_bytes=4 * _GIB, memory_pressure_level="nominal")),
            2 * _GIB,
        )

    def test_elevated_is_thirty_percent(self) -> None:
        self.assertEqual(
            model_memory_budget(MachineResources(available_ram_bytes=10 * _GIB, memory_pressure_level="elevated")),
            3 * _GIB,
        )

    def test_critical_is_fifteen_percent(self) -> None:
        self.assertEqual(
            model_memory_budget(MachineResources(available_ram_bytes=10 * _GIB, memory_pressure_level="critical")),
            int(10 * _GIB * 0.15),
        )

    def test_an_active_model_subtracts_from_the_budget(self) -> None:
        budget = model_memory_budget(MachineResources(
            available_ram_bytes=4 * _GIB, memory_pressure_level="nominal", active_model_bytes=_GIB,
        ))
        self.assertEqual(budget, _GIB)

    def test_an_active_model_larger_than_the_share_floors_to_zero(self) -> None:
        # Nominal share of 4 GiB is 2 GiB; an active model holding 3 GiB leaves
        # a negative budget, which floors at zero — a refusal, not a credit.
        budget = model_memory_budget(MachineResources(
            available_ram_bytes=4 * _GIB, memory_pressure_level="nominal", active_model_bytes=3 * _GIB,
        ))
        self.assertEqual(budget, 0)

    def test_an_unmeasured_host_has_no_budget_and_no_refusal(self) -> None:
        self.assertEqual(model_memory_budget(MachineResources(available_ram_bytes=0)), 0)

    def test_the_budget_floors_at_zero(self) -> None:
        budget = model_memory_budget(MachineResources(
            available_ram_bytes=2 * _GIB, memory_pressure_level="nominal", active_model_bytes=2 * _GIB,
        ))
        self.assertEqual(budget, 0)


class RuntimeFootprint(unittest.TestCase):
    def test_weights_plus_context_cache(self) -> None:
        self.assertEqual(
            model_runtime_footprint(model_size_bytes=_GIB, context_limit_tokens=4096),
            _GIB + 4096 * CONTEXT_BYTES_PER_TOKEN,
        )

    def test_a_model_with_no_context_window_is_weights_only(self) -> None:
        self.assertEqual(model_runtime_footprint(model_size_bytes=_GIB, context_limit_tokens=0), _GIB)

    def test_a_model_whose_size_was_not_statted_is_context_only(self) -> None:
        self.assertEqual(
            model_runtime_footprint(model_size_bytes=0, context_limit_tokens=4096),
            4096 * CONTEXT_BYTES_PER_TOKEN,
        )


class DefaultMachineResources(unittest.TestCase):
    def _proc(self, **files: str) -> Path:
        root = TemporaryDirectory()
        self.addCleanup(root.cleanup)
        base = Path(root.name)
        (base / "meminfo").write_text(files.get("meminfo", ""), encoding="utf-8")
        pressure = base / "pressure"
        pressure.mkdir()
        if "memory" in files:
            (pressure / "memory").write_text(files["memory"], encoding="utf-8")
        return base

    def test_reads_memavailable_and_a_nominal_pressure(self) -> None:
        proc = self._proc(
            meminfo="MemTotal:       8000000 kB\nMemAvailable:   4000000 kB\n",
            memory="some avg10=5.00 avg60=5.00 avg300=5.00 total=123\n"
                   "full avg10=5.00 avg60=5.00 avg300=5.00 total=123\n",
        )
        resources = default_machine_resources(proc_root=proc)
        self.assertTrue(resources.known)
        self.assertEqual(resources.available_ram_bytes, 4000000 * 1024)
        self.assertEqual(resources.memory_pressure_level, "nominal")

    def test_full_avg10_above_60_is_critical(self) -> None:
        proc = self._proc(
            meminfo="MemAvailable:   4000000 kB\n",
            memory="full avg10=70.00 avg60=70.00 avg300=70.00 total=123\n",
        )
        self.assertEqual(default_machine_resources(proc_root=proc).memory_pressure_level, "critical")

    def test_full_avg10_above_30_is_elevated(self) -> None:
        proc = self._proc(
            meminfo="MemAvailable:   4000000 kB\n",
            memory="full avg10=40.00 avg60=40.00 avg300=40.00 total=123\n",
        )
        self.assertEqual(default_machine_resources(proc_root=proc).memory_pressure_level, "elevated")

    def test_a_missing_proc_is_unknown_and_disables_the_guard(self) -> None:
        resources = default_machine_resources(proc_root=Path("/this/does/not/exist"))
        self.assertFalse(resources.known)
        self.assertEqual(resources.memory_pressure_level, "unknown")

    def test_no_memavailable_line_is_unknown(self) -> None:
        proc = self._proc(meminfo="MemTotal:       8000000 kB\n")
        resources = default_machine_resources(proc_root=proc)
        self.assertFalse(resources.known)


# --------------------------------------------------------------------------- #
# registry: discovery picks the model that fits
# --------------------------------------------------------------------------- #


class DiscoveryPicksByFootprint(unittest.TestCase):
    """Small machine → smaller model; powerful machine → larger; no tiers named."""

    def setUp(self) -> None:
        # Three discovered models, no configured model_id, so discovery runs.
        self.models = (
            ModelListing(model_id="alpha-200m", size_bytes=200 * _MIB, context_limit_tokens=2048),
            ModelListing(model_id="beta-800m", size_bytes=800 * _MIB, context_limit_tokens=2048),
            ModelListing(model_id="gamma-1p5b", size_bytes=int(1.5 * _GIB), context_limit_tokens=2048),
        )

    def test_a_powerful_machine_binds_the_largest_that_fits(self) -> None:
        registry = _registry(
            self.models,
            MachineResources(available_ram_bytes=16 * _GIB, memory_pressure_level="nominal"),
        )
        descriptor = registry.descriptor("local.sized", monotonic=0.0)
        self.assertEqual(descriptor.model_id, "gamma-1p5b")

    def test_a_small_machine_binds_the_smaller_model_that_fits(self) -> None:
        # 1 GiB available, nominal budget 512 MiB: only the 200m fits.
        registry = _registry(
            self.models,
            MachineResources(available_ram_bytes=_GIB, memory_pressure_level="nominal"),
        )
        descriptor = registry.descriptor("local.sized", monotonic=0.0)
        self.assertEqual(descriptor.model_id, "alpha-200m")

    def test_critical_pressure_where_nothing_fits_binds_the_smallest(self) -> None:
        # 256 MiB available, critical budget ~38 MiB: none fit. The smallest is
        # bound so the eligibility gate can refuse it, not the descriptor.
        registry = _registry(
            (ModelListing(model_id="big", size_bytes=100 * _MIB, context_limit_tokens=2048),
             ModelListing(model_id="huge", size_bytes=200 * _MIB, context_limit_tokens=2048)),
            MachineResources(available_ram_bytes=256 * _MIB, memory_pressure_level="critical"),
        )
        descriptor = registry.descriptor("local.sized", monotonic=0.0)
        self.assertEqual(descriptor.model_id, "big")

    def test_an_unmeasured_host_keeps_the_deterministic_first_by_name(self) -> None:
        registry = _registry(self.models, None)
        descriptor = registry.descriptor("local.sized", monotonic=0.0)
        self.assertEqual(descriptor.model_id, "alpha-200m")


# --------------------------------------------------------------------------- #
# registry: the eligibility gate refuses what does not fit
# --------------------------------------------------------------------------- #


class ResourceEligibilityGate(unittest.TestCase):
    def test_a_model_larger_than_the_budget_is_ineligible(self) -> None:
        # 2 GiB model on a 2 GiB-available nominal host: budget 1 GiB, refused.
        registry = _registry(
            (ModelListing(model_id="big", size_bytes=2 * _GIB, context_limit_tokens=2048),),
            MachineResources(available_ram_bytes=2 * _GIB, memory_pressure_level="nominal"),
        )
        explanation = registry.select(_requirement(), monotonic=0.0)
        self.assertFalse(explanation.found)
        reasons = dict(explanation.ineligible).get("local.sized", ())
        self.assertTrue(any("MiB resident" in r and "available" in r for r in reasons),
                        f"resource reason missing from {reasons}")

    def test_the_same_model_is_eligible_on_a_larger_machine(self) -> None:
        registry = _registry(
            (ModelListing(model_id="big", size_bytes=2 * _GIB, context_limit_tokens=2048),),
            MachineResources(available_ram_bytes=16 * _GIB, memory_pressure_level="nominal"),
        )
        explanation = registry.select(_requirement(), monotonic=0.0)
        self.assertTrue(explanation.found)
        self.assertEqual(explanation.selected, "local.sized")

    def test_critical_pressure_downgrades_to_the_model_that_fits(self) -> None:
        # Both models offered; critical pressure shrinks the budget so only the
        # small one is eligible — a downgrade, not a refusal and not a tier.
        registry = _registry(
            (ModelListing(model_id="alpha-200m", size_bytes=200 * _MIB, context_limit_tokens=2048),
             ModelListing(model_id="gamma-1p5b", size_bytes=int(1.5 * _GIB), context_limit_tokens=2048)),
            MachineResources(available_ram_bytes=4 * _GIB, memory_pressure_level="critical"),
        )
        explanation = registry.select(_requirement(), monotonic=0.0)
        self.assertTrue(explanation.found)
        self.assertEqual(explanation.selected, "local.sized")
        self.assertEqual(explanation.fallback_order, ())

    def test_an_unmeasured_host_never_refuses_on_resources(self) -> None:
        # A huge model and no machine resources: backward-compatibility path.
        registry = _registry(
            (ModelListing(model_id="huge", size_bytes=64 * _GIB, context_limit_tokens=2048),),
            None,
        )
        explanation = registry.select(_requirement(), monotonic=0.0)
        self.assertTrue(explanation.found)
        reasons = dict(explanation.ineligible).get("local.sized", ())
        self.assertNotIn("local.sized", dict(explanation.ineligible))

    def test_an_unstatted_model_is_estimated_from_its_context_window(self) -> None:
        # A discovered model the probe could not stat (size 0) still has a
        # resident footprint: the context window's cache allowance, derived
        # from the configuration's default context limit when the listing
        # declares none. That is the estimate the gate weighs — never zero for
        # a resolved model, so a measured host always has something to compare.
        registry = _registry(
            (ModelListing(model_id="phantom", size_bytes=0, context_limit_tokens=0),),
            MachineResources(available_ram_bytes=8 * _MIB, memory_pressure_level="critical"),
        )
        descriptor = registry.descriptor("local.sized", monotonic=0.0)
        self.assertEqual(
            descriptor.resource_estimate.memory_bytes,
            4096 * CONTEXT_BYTES_PER_TOKEN,
        )


class ConfiguredModelKeepsItsSize(unittest.TestCase):
    def test_an_explicit_model_id_is_bound_with_its_size_regardless_of_fit_choice(self) -> None:
        # A configured model is not subject to discovery's largest-that-fits
        # choice; it is bound by name and carries its size into the estimate.
        registry = _registry(
            (ModelListing(model_id="chosen", size_bytes=_GIB, context_limit_tokens=2048),
             ModelListing(model_id="other", size_bytes=100 * _MIB, context_limit_tokens=2048)),
            MachineResources(available_ram_bytes=16 * _GIB, memory_pressure_level="nominal"),
            model_id="chosen",
        )
        descriptor = registry.descriptor("local.sized", monotonic=0.0)
        self.assertEqual(descriptor.model_id, "chosen")
        self.assertEqual(
            descriptor.resource_estimate.memory_bytes,
            _GIB + 2048 * CONTEXT_BYTES_PER_TOKEN,
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()