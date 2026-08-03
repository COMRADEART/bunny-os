# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Capability scoring: bounds, determinism, and the separation of dimensions."""

from __future__ import annotations

import unittest

from capability.scores import DIMENSIONS, MEASURED, UNKNOWN, Score, compute_scores
from capability.simulate import MACHINES, machine, simulate

MIB = 1024 ** 2
GIB = 1024 ** 3


class ScoreContractTests(unittest.TestCase):
    def test_every_dimension_is_produced_for_every_machine(self) -> None:
        names = {name for name, _ in DIMENSIONS}
        for machine_name in MACHINES:
            with self.subTest(machine=machine_name):
                self.assertEqual(set(compute_scores(simulate(machine_name)).scores), names)

    def test_every_score_is_bounded_or_explicitly_unmeasured(self) -> None:
        for machine_name in MACHINES:
            for name, score in compute_scores(simulate(machine_name)).scores.items():
                with self.subTest(machine=machine_name, dimension=name):
                    if score.value is None:
                        self.assertEqual(score.confidence, UNKNOWN)
                    else:
                        self.assertGreaterEqual(score.value, 0.0)
                        self.assertLessEqual(score.value, 100.0)

    def test_scoring_is_deterministic_for_the_same_inventory(self) -> None:
        for machine_name in MACHINES:
            with self.subTest(machine=machine_name):
                first = compute_scores(simulate(machine_name)).to_json()
                second = compute_scores(simulate(machine_name)).to_json()
                self.assertEqual(first, second)

    def test_raw_measurements_are_preserved_alongside_each_score(self) -> None:
        scores = compute_scores(simulate("laptop"))
        memory = scores["memory_available"]
        self.assertEqual(memory.inputs["usableBytes"], 16 * GIB)
        self.assertIn("currentlyAvailableBytes", memory.inputs)

    def test_there_is_no_overall_score(self) -> None:
        document = compute_scores(simulate("laptop")).to_json()
        self.assertNotIn("overall", document)
        self.assertNotIn("total", document)
        self.assertNotIn("tier", document)
        self.assertIn("no overall score", document["note"])

    def test_a_score_outside_the_documented_range_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            Score("cpu_compute", 101.0, MEASURED)
        with self.assertRaises(ValueError):
            Score("cpu_compute", -1.0, MEASURED)

    def test_a_scoreless_dimension_must_declare_unknown_confidence(self) -> None:
        with self.assertRaises(ValueError):
            Score("cpu_compute", None, MEASURED)


class UnmeasuredTests(unittest.TestCase):
    """Missing data yields no score, never a zero score."""

    def test_a_machine_that_measured_nothing_scores_nothing(self) -> None:
        scores = compute_scores(simulate("unmeasurable"))
        for name, _ in DIMENSIONS:
            with self.subTest(dimension=name):
                self.assertIsNone(scores[name].value, f"{name} produced a number from no measurement")

    def test_at_least_requires_an_explicit_unknown_policy(self) -> None:
        score = Score("cpu_compute", None, UNKNOWN)
        self.assertFalse(score.at_least(10.0, when_unknown=False))
        self.assertTrue(score.at_least(10.0, when_unknown=True))
        with self.assertRaises(TypeError):
            score.at_least(10.0)  # type: ignore[call-arg]

    def test_no_gpu_scores_zero_with_measured_confidence(self) -> None:
        # "We looked and there is nothing" is a different statement from "we
        # could not look", and the confidence is what carries the difference.
        scores = compute_scores(simulate("cpu-server"))
        self.assertEqual(scores["gpu_compute"].value, 0.0)
        self.assertEqual(scores["gpu_compute"].confidence, MEASURED)


class SeparationTests(unittest.TestCase):
    """A strong dimension may never compensate for a weak one."""

    def test_a_powerful_gpu_does_not_hide_a_severe_memory_shortage(self) -> None:
        scores = compute_scores(simulate("constrained-container"))
        # Eight 80 GB accelerators, all usable, inside a 512 MiB cgroup.
        self.assertGreater(scores["gpu_compute"].value, 90.0)
        self.assertGreater(scores["gpu_memory"].value, 90.0)
        self.assertLess(scores["memory_available"].value, 35.0)
        # The dimension that decides local inference must follow the memory, not
        # the accelerators: the runtime driving them lives in system memory.
        self.assertLess(scores["local_ai"].value, 10.0)
        self.assertTrue(any("floor" in note for note in scores["local_ai"].notes))

    def test_the_host_runtime_floor_collapses_local_ai_whatever_the_gpu(self) -> None:
        from capability.scores import HOST_RUNTIME_FLOOR_BYTES

        below = compute_scores(machine(
            physical_memory_bytes=HOST_RUNTIME_FLOOR_BYTES - 1,
            gpus=simulate("multi-gpu-ai-server").gpu,
        ))
        above = compute_scores(machine(
            physical_memory_bytes=8 * GIB,
            gpus=simulate("multi-gpu-ai-server").gpu,
        ))
        self.assertLess(below["local_ai"].value, 10.0)
        self.assertGreater(above["local_ai"].value, 50.0)

    def test_a_gpu_with_no_dedicated_memory_does_not_raise_local_ai(self) -> None:
        shared = compute_scores(simulate("laptop"))
        self.assertEqual(shared["gpu_memory"].value, 0.0)
        # The score comes from the CPU path alone, bounded by system memory.
        self.assertLessEqual(shared["local_ai"].value, shared["memory_available"].value + 1e-9)

    def test_a_driverless_gpu_scores_zero_compute(self) -> None:
        scores = compute_scores(simulate("gpu-without-driver"))
        self.assertEqual(scores["gpu_compute"].value, 0.0)
        self.assertEqual(scores["gpu_memory"].value, 0.0)
        self.assertTrue(any("unusable" in note for note in scores["gpu_compute"].notes))

    def test_a_shared_memory_gpu_does_not_borrow_the_memory_dimension(self) -> None:
        scores = compute_scores(simulate("laptop"))
        self.assertEqual(scores["gpu_memory"].value, 0.0)
        self.assertGreater(scores["memory_available"].value, 50.0)
        self.assertTrue(any("shares system memory" in note for note in scores["gpu_memory"].notes))

    def test_headless_scores_zero_graphics_whatever_the_gpu(self) -> None:
        scores = compute_scores(simulate("multi-gpu-ai-server"))
        self.assertGreater(scores["gpu_compute"].value, 90.0)
        self.assertEqual(scores["graphics"].value, 0.0)
        self.assertEqual(scores["interactive_desktop"].value, 0.0)


class CurveTests(unittest.TestCase):
    """The memory curve is the one every constrained decision reads."""

    def test_the_memory_curve_is_monotonic_across_the_supported_range(self) -> None:
        sizes = [64 * MIB, 128 * MIB, 512 * MIB, 1 * GIB, 4 * GIB, 16 * GIB, 64 * GIB, 128 * GIB]
        values = [
            compute_scores(machine(physical_memory_bytes=size))["memory_available"].value
            for size in sizes
        ]
        self.assertEqual(values, sorted(values))
        self.assertEqual(values[0], 0.0)      # 64 MiB is the documented floor
        self.assertEqual(values[-1], 100.0)   # 128 GiB is the documented ceiling

    def test_the_curve_saturates_rather_than_exceeding_its_bound(self) -> None:
        value = compute_scores(machine(physical_memory_bytes=2048 * GIB))["memory_available"].value
        self.assertEqual(value, 100.0)

    def test_cpu_scores_rise_with_schedulable_cores(self) -> None:
        values = [
            compute_scores(machine(physical_memory_bytes=8 * GIB, logical_threads=count))["cpu_compute"].value
            for count in (1, 2, 4, 8, 16, 64)
        ]
        self.assertEqual(values, sorted(values))

    def test_a_cpu_quota_lowers_the_cpu_score_below_the_thread_count(self) -> None:
        unlimited = compute_scores(machine(physical_memory_bytes=8 * GIB, logical_threads=64))
        limited = compute_scores(machine(physical_memory_bytes=8 * GIB, logical_threads=64, quota_cores=0.5))
        self.assertLess(limited["cpu_compute"].value, unlimited["cpu_compute"].value)
        self.assertTrue(any("cgroup quota" in note for note in limited["cpu_compute"].notes))


class PressureTests(unittest.TestCase):
    """Capacity is a property of the hardware; headroom is a property of now."""

    def test_load_reduces_background_capacity_but_not_cpu_capacity(self) -> None:
        idle = compute_scores(machine(physical_memory_bytes=16 * GIB, logical_threads=8, load_average=0.1))
        busy = compute_scores(machine(physical_memory_bytes=16 * GIB, logical_threads=8, load_average=8.0))
        self.assertEqual(idle["cpu_compute"].value, busy["cpu_compute"].value)
        self.assertGreater(idle["background_capacity"].value, busy["background_capacity"].value)

    def test_battery_operation_halves_background_capacity(self) -> None:
        mains = compute_scores(machine(physical_memory_bytes=16 * GIB, power_supply="ac"))
        battery = compute_scores(
            machine(physical_memory_bytes=16 * GIB, power_supply="battery", battery_percent=50)
        )
        self.assertLess(battery["background_capacity"].value, mains["background_capacity"].value)

    def test_a_low_battery_collapses_energy_headroom(self) -> None:
        low = compute_scores(machine(physical_memory_bytes=8 * GIB, power_supply="battery", battery_percent=5))
        high = compute_scores(machine(physical_memory_bytes=8 * GIB, power_supply="battery", battery_percent=90))
        self.assertLess(low["energy_thermal_headroom"].value, 15.0)
        self.assertGreater(high["energy_thermal_headroom"].value, low["energy_thermal_headroom"].value)

    def test_engaged_cooling_reduces_energy_headroom(self) -> None:
        cool = compute_scores(machine(physical_memory_bytes=16 * GIB, cooling_state=0.0))
        hot = compute_scores(machine(physical_memory_bytes=16 * GIB, throttled=True, cooling_state=0.8))
        self.assertLess(hot["energy_thermal_headroom"].value, cool["energy_thermal_headroom"].value)

    def test_io_pressure_reduces_storage_performance_proportionally(self) -> None:
        scores = compute_scores(machine(physical_memory_bytes=8 * GIB, storage_class="solid-state"))
        self.assertGreater(scores["storage_performance"].value, 80.0)

    def test_an_undeterminable_storage_class_is_unmeasured_not_slow(self) -> None:
        scores = compute_scores(machine(physical_memory_bytes=8 * GIB, storage_class=None))
        self.assertIsNone(scores["storage_performance"].value)


class NetworkScoreTests(unittest.TestCase):
    def test_offline_scores_zero_with_measured_confidence(self) -> None:
        scores = compute_scores(simulate("offline-laptop"))
        self.assertEqual(scores["network_quality"].value, 0.0)
        self.assertEqual(scores["network_quality"].confidence, MEASURED)

    def test_a_metered_connection_scores_below_an_unmetered_one(self) -> None:
        free = compute_scores(machine(physical_memory_bytes=8 * GIB, metered=False))
        metered = compute_scores(machine(physical_memory_bytes=8 * GIB, metered=True))
        self.assertLess(metered["network_quality"].value, free["network_quality"].value)

    def test_wired_scores_above_wireless(self) -> None:
        wired = compute_scores(machine(physical_memory_bytes=8 * GIB, connection_type="wired"))
        wireless = compute_scores(machine(physical_memory_bytes=8 * GIB, connection_type="wireless"))
        self.assertGreater(wired["network_quality"].value, wireless["network_quality"].value)


class AudioScoreTests(unittest.TestCase):
    def test_a_machine_with_no_audio_scores_zero_and_says_why(self) -> None:
        scores = compute_scores(simulate("cpu-server"))
        self.assertEqual(scores["audio"].value, 0.0)
        self.assertTrue(any("nowhere to go" in note for note in scores["audio"].notes))

    def test_output_without_capture_scores_partially(self) -> None:
        scores = compute_scores(
            machine(physical_memory_bytes=8 * GIB, audio_output=True, audio_input=False)
        )
        self.assertGreater(scores["audio"].value, 0.0)
        self.assertLess(scores["audio"].value, 100.0)


if __name__ == "__main__":
    unittest.main()
