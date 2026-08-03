# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The inventory model, and the three-state availability rule it enforces."""

from __future__ import annotations

import unittest

from capability.model import (
    ABSENT,
    CpuFacts,
    DisplayFacts,
    MemoryFacts,
    NetworkFacts,
    Observation,
    UNKNOWN,
    absent,
    inventory_from_json,
    measured,
    unknown,
)
from capability.simulate import MACHINES, simulate

MIB = 1024 ** 2
GIB = 1024 ** 3


class ObservationTests(unittest.TestCase):
    def test_only_a_measured_observation_may_carry_a_value(self) -> None:
        # The invariant that keeps "we did not measure this" from acquiring a
        # plausible-looking number by accident.
        with self.assertRaises(ValueError):
            Observation(value=1024, state=UNKNOWN)
        with self.assertRaises(ValueError):
            Observation(value=0, state=ABSENT)

    def test_absent_and_unknown_are_different_states(self) -> None:
        no_battery = absent("/sys/class/power_supply", "no battery")
        unread = unknown("/sys/class/power_supply", "unreadable")
        self.assertNotEqual(no_battery.state, unread.state)
        self.assertTrue(no_battery.is_known)
        self.assertFalse(unread.is_known)
        self.assertFalse(no_battery.is_measured)

    def test_get_requires_an_explicit_default(self) -> None:
        # There is deliberately no zero-argument form: every call site must
        # record what it decided to assume about the unmeasured case.
        with self.assertRaises(TypeError):
            unknown("x").get()  # type: ignore[call-arg]
        self.assertEqual(unknown("x").get(7), 7)
        self.assertEqual(measured(3, "x").get(7), 3)

    def test_unmeasured_observations_serialise_without_a_value_key(self) -> None:
        self.assertNotIn("value", unknown("x", "why").to_json())
        self.assertEqual(measured(5, "x").to_json()["value"], 5)

    def test_json_roundtrip_preserves_state_and_provenance(self) -> None:
        for observation in (measured(5, "src", "detail"), absent("src", "gone"), unknown("src")):
            with self.subTest(state=observation.state):
                self.assertEqual(Observation.from_json(observation.to_json()), observation)

    def test_an_unrecognised_state_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            Observation(state="probably")


class UsableMemoryTests(unittest.TestCase):
    """The cgroup ceiling binds, not the host's physical memory."""

    def test_cgroup_limit_wins_over_physical_memory(self) -> None:
        memory = MemoryFacts(
            physical_bytes=measured(512 * GIB, "x"),
            cgroup_limit_bytes=measured(512 * MIB, "x"),
        )
        self.assertEqual(memory.usable_bytes(None), 512 * MIB)

    def test_physical_memory_is_used_when_there_is_no_ceiling(self) -> None:
        memory = MemoryFacts(
            physical_bytes=measured(8 * GIB, "x"),
            cgroup_limit_bytes=absent("x", "no limit"),
        )
        self.assertEqual(memory.usable_bytes(None), 8 * GIB)

    def test_available_never_exceeds_the_usable_ceiling(self) -> None:
        # The host reports 480 GiB free; the container may use 512 MiB of it.
        memory = MemoryFacts(
            physical_bytes=measured(512 * GIB, "x"),
            available_bytes=measured(480 * GIB, "x"),
            cgroup_limit_bytes=measured(512 * MIB, "x"),
        )
        self.assertEqual(memory.usable_available_bytes(None), 512 * MIB)

    def test_unmeasured_memory_returns_the_default_not_zero(self) -> None:
        self.assertIsNone(MemoryFacts().usable_bytes(None))
        self.assertEqual(MemoryFacts().usable_bytes(-1), -1)


class EffectiveCoreTests(unittest.TestCase):
    def test_cpu_quota_binds_below_the_thread_count(self) -> None:
        cpu = CpuFacts(logical_threads=measured(128, "x"), quota_cores=measured(0.5, "x"))
        self.assertEqual(cpu.effective_cores(0.0), 0.5)

    def test_thread_count_is_used_when_no_quota_is_imposed(self) -> None:
        cpu = CpuFacts(logical_threads=measured(8, "x"), quota_cores=absent("x", "none"))
        self.assertEqual(cpu.effective_cores(0.0), 8.0)

    def test_unmeasured_topology_returns_the_default(self) -> None:
        self.assertEqual(CpuFacts().effective_cores(-1.0), -1.0)


class OfflineSemanticsTests(unittest.TestCase):
    """Unknown connectivity is neither online nor offline."""

    def test_unknown_route_is_not_offline_and_not_online(self) -> None:
        network = NetworkFacts(default_route=unknown("/proc/net", "unreadable"))
        self.assertFalse(network.offline)
        self.assertFalse(network.online)

    def test_measured_absence_of_a_route_is_offline(self) -> None:
        network = NetworkFacts(default_route=measured(False, "/proc/net/route"))
        self.assertTrue(network.offline)
        self.assertFalse(network.online)

    def test_measured_route_is_online(self) -> None:
        network = NetworkFacts(default_route=measured(True, "/proc/net/route"))
        self.assertTrue(network.online)
        self.assertFalse(network.offline)


class DisplayTests(unittest.TestCase):
    def test_a_display_requires_a_positive_connected_output_count(self) -> None:
        self.assertFalse(DisplayFacts(connected_outputs=measured(0, "x")).has_display)
        self.assertTrue(DisplayFacts(connected_outputs=measured(1, "x")).has_display)

    def test_unmeasured_outputs_do_not_claim_a_display(self) -> None:
        # Conservative in the safe direction: a renderer is not started on a
        # display nobody observed.
        self.assertFalse(DisplayFacts().has_display)


class UsableGpuTests(unittest.TestCase):
    def test_a_gpu_without_a_driver_is_not_usable(self) -> None:
        inventory = simulate("gpu-without-driver")
        self.assertEqual(len(inventory.gpu), 1)
        self.assertEqual(inventory.usable_gpus, [])

    def test_a_gpu_with_a_driver_and_a_render_node_is_usable(self) -> None:
        inventory = simulate("gaming-desktop")
        self.assertEqual(len(inventory.usable_gpus), 1)


class SerialisationTests(unittest.TestCase):
    def test_every_simulated_inventory_survives_a_json_roundtrip(self) -> None:
        for name in MACHINES:
            with self.subTest(machine=name):
                document = simulate(name).to_json()
                self.assertEqual(inventory_from_json(document).to_json(), document)

    def test_an_unsupported_schema_version_is_refused(self) -> None:
        document = simulate("laptop").to_json()
        document["schemaVersion"] = 99
        with self.assertRaises(ValueError):
            inventory_from_json(document)

    def test_no_identifying_information_is_collected(self) -> None:
        # §14: the inventory must be safe to show a user and safe to attach to
        # a diagnostic. The cheapest guarantee is never collecting the fields.
        import json

        for name in MACHINES:
            with self.subTest(machine=name):
                document = json.dumps(simulate(name).to_json()).lower()
                for forbidden in ("serial", "macaddress", "hostname", "uuid", "boot_id", "bootid"):
                    self.assertNotIn(f'"{forbidden}"', document)
                self.assertIs(simulate(name).to_json()["privacy"]["transmitted"], False)


if __name__ == "__main__":
    unittest.main()
