# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The runtime monitor: hysteresis, debounce, cooldown and coalescing.

The four mechanisms are routinely confused, so each is tested in isolation
before they are tested together. A monitor that got any one of them wrong would
either flap services or fail to adapt, and both failures look like "it works"
on a machine that never changes.
"""

from __future__ import annotations

from dataclasses import replace
import unittest

from capability.apply.identity import REEVALUATION_REASONS
from capability.apply.monitor import (
    CONSTRAINED_SIGNALS,
    DEFAULT_SIGNALS,
    EVENTS,
    MonitorEvent,
    MonitorSettings,
    RuntimeMonitor,
    Sample,
    SignalConfig,
    sample_from_inventory,
)
from capability.simulate import machine, simulate

MIB = 1024 ** 2
GIB = 1024 ** 3

PRESSURE = SignalConfig(
    "memory_pressure", 60.0, 20.0,
    "memory_pressure_entered", "memory_pressure_recovered",
    higher_is_worse=True, debounce_seconds=10.0, cooldown_seconds=60.0,
)


def monitor(*signals: SignalConfig, **settings) -> RuntimeMonitor:
    return RuntimeMonitor(settings=MonitorSettings(
        signals=signals or (PRESSURE,), **settings,
    ))


def feed(instance: RuntimeMonitor, readings, *, signal: str = "memory_pressure"):
    """Feed (time, value) pairs and collect every event raised."""
    raised = []
    for at, value in readings:
        raised.extend(instance.observe(Sample(at, numeric={signal: value})))
    return raised


class VocabularyTests(unittest.TestCase):
    def test_every_monitor_event_is_a_valid_reevaluation_reason(self) -> None:
        # The monitor hands its event straight to the engine as a plan's stated
        # cause. A vocabulary mismatch would need a translation table, and a
        # translation table is where the two drift apart.
        for event in EVENTS:
            with self.subTest(event=event):
                self.assertIn(event, REEVALUATION_REASONS)

    def test_a_signal_with_no_hysteresis_band_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            SignalConfig(
                "bad", 50.0, 50.0, "memory_pressure_entered", "memory_pressure_recovered",
                higher_is_worse=True,
            )

    def test_an_inverted_band_is_refused_for_a_lower_is_worse_signal(self) -> None:
        with self.assertRaises(ValueError):
            SignalConfig(
                "bad", 0.5, 0.2, "battery_critical", "battery_recovered",
                higher_is_worse=False,
            )

    def test_every_shipped_signal_has_a_real_band(self) -> None:
        for config in DEFAULT_SIGNALS:
            with self.subTest(signal=config.name):
                self.assertNotEqual(config.enter_threshold, config.leave_threshold)


class DebounceTests(unittest.TestCase):
    def test_a_single_crossing_raises_nothing(self) -> None:
        # A signal that crosses the line for one sample produces nothing at all.
        events = feed(monitor(), [(0.0, 10.0), (5.0, 90.0), (10.0, 10.0)])
        self.assertEqual(events, [])

    def test_a_crossing_that_holds_raises_one_event(self) -> None:
        events = feed(monitor(), [(0.0, 10.0), (5.0, 90.0), (20.0, 90.0)])
        self.assertEqual([item.event for item in events], ["memory_pressure_entered"])

    def test_a_crossing_shorter_than_the_debounce_raises_nothing(self) -> None:
        events = feed(monitor(), [(0.0, 10.0), (5.0, 90.0), (9.0, 90.0), (12.0, 10.0)])
        self.assertEqual(events, [])

    def test_the_debounce_measures_from_the_first_sample_that_held(self) -> None:
        instance = monitor()
        feed(instance, [(0.0, 10.0), (5.0, 90.0)])
        events = feed(instance, [(15.0, 90.0)])
        self.assertEqual(len(events), 1)
        self.assertAlmostEqual(events[0].at_monotonic, 15.0)


class HysteresisTests(unittest.TestCase):
    def test_a_value_inside_the_band_does_not_recover(self) -> None:
        # Entered at 60, recovers below 20. A value of 40 is inside the band and
        # must change nothing.
        instance = monitor()
        feed(instance, [(0.0, 90.0), (20.0, 90.0)])
        events = feed(instance, [(100.0, 40.0), (200.0, 40.0)])
        self.assertEqual(events, [])

    def test_a_value_below_the_recovery_threshold_recovers(self) -> None:
        instance = monitor()
        feed(instance, [(0.0, 90.0), (20.0, 90.0)])
        events = feed(instance, [(200.0, 5.0), (300.0, 5.0)])
        self.assertEqual([item.event for item in events], ["memory_pressure_recovered"])

    def test_oscillation_across_one_threshold_produces_one_event_not_forty(self) -> None:
        # The property the whole band exists for: a laptop whose free memory
        # sits on a boundary must not flap its services.
        instance = monitor()
        readings = []
        at = 0.0
        for step in range(40):
            at += 15.0
            readings.append((at, 61.0 if step % 2 == 0 else 59.0))
        events = feed(instance, readings)
        self.assertLessEqual(len(events), 1)

    def test_a_full_cycle_produces_exactly_one_entry_and_one_recovery(self) -> None:
        instance = monitor()
        events = feed(instance, [
            (0.0, 5.0),
            (10.0, 90.0), (25.0, 90.0), (40.0, 90.0),
            (200.0, 5.0), (215.0, 5.0), (230.0, 5.0),
        ])
        self.assertEqual(
            [item.event for item in events],
            ["memory_pressure_entered", "memory_pressure_recovered"],
        )


class CooldownTests(unittest.TestCase):
    def test_a_non_emergency_event_is_suppressed_inside_its_cooldown(self) -> None:
        config = replace(
            PRESSURE, entered_event="cpu_saturation_entered",
            recovered_event="cpu_saturation_recovered", name="cpu_saturation",
            debounce_seconds=1.0, cooldown_seconds=1000.0,
        )
        instance = monitor(config)
        first = feed(instance, [(0.0, 90.0), (5.0, 90.0)], signal="cpu_saturation")
        self.assertEqual(len(first), 1)
        # Recover and re-enter well inside the cooldown window.
        second = feed(instance, [
            (10.0, 5.0), (20.0, 5.0), (30.0, 90.0), (40.0, 90.0),
        ], signal="cpu_saturation")
        self.assertEqual(second, [])

    def test_an_emergency_event_bypasses_the_cooldown(self) -> None:
        # A cooldown that suppressed "memory is critically short" would be a
        # stability mechanism that let the machine run out of memory quietly.
        #
        # The recovery in the middle has to be allowed to fire, or the re-entry
        # is not a transition at all: the monitor would still believe it was in
        # pressure and would have nothing new to report. So the recovery happens
        # past the cooldown window, and the re-entry immediately after it — well
        # inside the window — is the thing being tested.
        instance = monitor(replace(PRESSURE, debounce_seconds=1.0, cooldown_seconds=1000.0))
        entered = feed(instance, [(0.0, 90.0), (5.0, 90.0)])
        self.assertEqual([item.event for item in entered], ["memory_pressure_entered"])

        recovered = feed(instance, [(1100.0, 5.0), (1110.0, 5.0)])
        self.assertEqual([item.event for item in recovered], ["memory_pressure_recovered"])

        # 5s after the recovery event, far inside a 1000s cooldown.
        reentered = feed(instance, [(1115.0, 90.0), (1125.0, 90.0)])
        self.assertIn("memory_pressure_entered", [item.event for item in reentered])

    def test_a_suppressed_event_is_delayed_and_not_discarded(self) -> None:
        """A cooldown bounds how often we act, not whether something happened.

        This replaces a test that asserted the opposite. The old behaviour
        flipped the signal's state while suppressing the notification, on the
        reasoning that the monitor's view should stay accurate — and measured
        against a real kernel that silently destroyed the event. A recovery
        arriving inside the cooldown window was suppressed, the state flipped so
        it was no longer a transition, and the recovery could never be raised
        again. The service stayed degraded indefinitely because nothing told the
        engine to look.
        """
        config = replace(
            PRESSURE, name="cpu_saturation",
            entered_event="cpu_saturation_entered", recovered_event="cpu_saturation_recovered",
            debounce_seconds=1.0, cooldown_seconds=100.0,
        )
        instance = monitor(config)
        feed(instance, [(0.0, 90.0), (5.0, 90.0)], signal="cpu_saturation")

        # Recovery arrives well inside the cooldown: suppressed for now.
        held = feed(instance, [(10.0, 5.0), (20.0, 5.0)], signal="cpu_saturation")
        self.assertEqual(held, [])
        state = next(item for item in instance.status()["signals"] if item["signal"] == "cpu_saturation")
        self.assertTrue(
            state["breached"],
            "the announced state must not flip while the notification is held, "
            "or the transition stops being one and is lost",
        )

        # Past the window, with the condition still true, it fires.
        late = feed(instance, [(200.0, 5.0)], signal="cpu_saturation")
        self.assertEqual([item.event for item in late], ["cpu_saturation_recovered"])


class UnmeasuredSignalTests(unittest.TestCase):
    def test_an_unmeasured_signal_raises_nothing(self) -> None:
        instance = monitor()
        self.assertEqual(instance.observe(Sample(0.0, numeric={})), ())

    def test_an_unmeasured_signal_does_not_resolve_a_breach(self) -> None:
        # A signal that stops being readable holds its state; it does not
        # silently recover.
        instance = monitor()
        feed(instance, [(0.0, 90.0), (20.0, 90.0)])
        instance.observe(Sample(100.0, numeric={}))
        state = next(item for item in instance.status()["signals"] if item["signal"] == "memory_pressure")
        self.assertTrue(state["breached"])

    def test_a_battery_that_was_never_measured_does_not_raise_battery_critical(self) -> None:
        # Reading an unmeasured battery as 0% would fire on every desktop.
        instance = RuntimeMonitor(settings=MonitorSettings(signals=DEFAULT_SIGNALS))
        sample = sample_from_inventory(simulate("cpu-server"), at_monotonic=0.0)
        self.assertNotIn("battery_percent", sample.numeric)
        self.assertEqual(instance.observe(sample), ())


class BooleanSignalTests(unittest.TestCase):
    def test_network_loss_and_restoration_are_raised(self) -> None:
        instance = monitor()
        instance.observe(Sample(0.0, boolean={"network_online": True}))
        lost = instance.observe(Sample(10.0, boolean={"network_online": False}))
        restored = instance.observe(Sample(20.0, boolean={"network_online": True}))
        self.assertEqual([item.event for item in lost], ["network_lost"])
        self.assertEqual([item.event for item in restored], ["network_restored"])

    def test_the_first_observation_of_a_boolean_is_not_an_event(self) -> None:
        # Otherwise every boot would report the display as newly attached.
        instance = monitor()
        self.assertEqual(instance.observe(Sample(0.0, boolean={"display_present": True})), ())

    def test_display_attachment_and_removal_are_raised(self) -> None:
        instance = monitor()
        instance.observe(Sample(0.0, boolean={"display_present": False}))
        attached = instance.observe(Sample(10.0, boolean={"display_present": True}))
        removed = instance.observe(Sample(20.0, boolean={"display_present": False}))
        self.assertEqual([item.event for item in attached], ["display_attached"])
        self.assertEqual([item.event for item in removed], ["display_removed"])

    def test_an_unchanged_boolean_raises_nothing(self) -> None:
        instance = monitor()
        instance.observe(Sample(0.0, boolean={"network_online": True}))
        self.assertEqual(instance.observe(Sample(10.0, boolean={"network_online": True})), ())


class ServiceAndConfigurationTests(unittest.TestCase):
    def test_a_newly_failed_service_raises_one_event(self) -> None:
        instance = monitor()
        first = instance.observe(Sample(0.0, failed_services=("a.one",)))
        self.assertEqual([item.event for item in first], ["service_failed"])

    def test_a_service_that_is_still_failed_does_not_raise_again(self) -> None:
        # Repeated service failure must not produce an event per sample.
        instance = monitor()
        instance.observe(Sample(0.0, failed_services=("a.one",)))
        for at in (30.0, 60.0, 90.0):
            with self.subTest(at=at):
                self.assertEqual(instance.observe(Sample(at, failed_services=("a.one",))), ())

    def test_a_policy_change_is_detected_by_fingerprint(self) -> None:
        instance = monitor()
        instance.observe(Sample(0.0, policy_fingerprint="a" * 32))
        events = instance.observe(Sample(30.0, policy_fingerprint="b" * 32))
        self.assertEqual([item.event for item in events], ["user_policy_changed"])

    def test_a_manifest_change_is_detected_by_fingerprint(self) -> None:
        instance = monitor()
        instance.observe(Sample(0.0, registry_fingerprint="a" * 32))
        events = instance.observe(Sample(30.0, registry_fingerprint="b" * 32))
        self.assertEqual([item.event for item in events], ["manifest_registry_changed"])

    def test_an_unreachable_provider_is_reported(self) -> None:
        events = monitor().observe(Sample(0.0, unreachable_providers=("test-provider",)))
        self.assertEqual([item.event for item in events], ["remote_provider_unavailable"])


class CoalescingTests(unittest.TestCase):
    def test_several_events_produce_one_reevaluation_reason(self) -> None:
        instance = monitor()
        events = [
            MonitorEvent("display_attached", 0.0),
            MonitorEvent("network_restored", 0.0),
            MonitorEvent("service_failed", 0.0),
        ]
        self.assertIsNotNone(instance.reevaluation_reason(events))

    def test_an_emergency_outranks_everything_else_in_the_batch(self) -> None:
        # A plan generated in response to a display being attached is not the
        # plan a machine short of memory needs.
        instance = monitor()
        events = [
            MonitorEvent("display_attached", 0.0),
            MonitorEvent("memory_pressure_entered", 0.0),
            MonitorEvent("network_restored", 0.0),
        ]
        self.assertEqual(instance.reevaluation_reason(events), "memory_pressure_entered")

    def test_the_same_batch_always_produces_the_same_reason(self) -> None:
        instance = monitor()
        events = [
            MonitorEvent("network_restored", 0.0),
            MonitorEvent("display_attached", 0.0),
            MonitorEvent("audio_device_changed", 0.0),
        ]
        first = instance.reevaluation_reason(events)
        self.assertEqual(instance.reevaluation_reason(list(reversed(events))), first)

    def test_no_events_produce_no_reason(self) -> None:
        self.assertIsNone(monitor().reevaluation_reason([]))


class SamplingTests(unittest.TestCase):
    def test_the_monitor_is_not_due_before_its_interval_elapses(self) -> None:
        # The monitor must not recalculate continuously without reason.
        instance = monitor(interval_seconds=30.0)
        self.assertTrue(instance.due(0.0))
        instance.observe(Sample(0.0, numeric={"memory_pressure": 1.0}))
        self.assertFalse(instance.due(10.0))
        self.assertTrue(instance.due(31.0))

    def test_a_constrained_node_watches_memory_only(self) -> None:
        self.assertEqual(len(CONSTRAINED_SIGNALS), 1)
        self.assertEqual(CONSTRAINED_SIGNALS[0].name, "memory_pressure")
        self.assertGreaterEqual(CONSTRAINED_SIGNALS[0].cooldown_seconds, 300.0)

    def test_a_disabled_signal_is_never_evaluated(self) -> None:
        instance = monitor(replace(PRESSURE, enabled=False))
        self.assertEqual(feed(instance, [(0.0, 99.0), (60.0, 99.0)]), [])

    def test_history_is_bounded(self) -> None:
        instance = monitor(replace(PRESSURE, debounce_seconds=0.0, cooldown_seconds=0.0))
        instance.history_limit = 4
        at = 0.0
        for _ in range(20):
            at += 10.0
            instance.observe(Sample(at, numeric={"memory_pressure": 99.0}))
            at += 10.0
            instance.observe(Sample(at, numeric={"memory_pressure": 1.0}))
        self.assertLessEqual(len(instance.history), 4)


class InventorySamplingTests(unittest.TestCase):
    def test_a_sample_is_built_only_from_measurements(self) -> None:
        sample = sample_from_inventory(simulate("laptop"), at_monotonic=0.0)
        self.assertIn("memory_available_fraction", sample.numeric)
        self.assertIn("battery_percent", sample.numeric)
        self.assertEqual(sample.numeric["battery_percent"], 72.0)

    def test_an_unmeasurable_machine_produces_an_empty_sample(self) -> None:
        sample = sample_from_inventory(simulate("unmeasurable"), at_monotonic=0.0)
        self.assertEqual(sample.numeric, {})
        self.assertEqual(sample.boolean, {})

    def test_memory_pressure_on_a_loaded_machine_is_sampled(self) -> None:
        loaded = machine(
            physical_memory_bytes=8 * GIB, available_memory_bytes=256 * MIB,
            logical_threads=4, memory_pressure=75.0,
        )
        sample = sample_from_inventory(loaded, at_monotonic=0.0)
        self.assertEqual(sample.numeric["memory_pressure"], 75.0)
        self.assertLess(sample.numeric["memory_available_fraction"], 0.1)

    def test_an_offline_machine_reports_the_network_as_down(self) -> None:
        sample = sample_from_inventory(simulate("offline-laptop"), at_monotonic=0.0)
        self.assertFalse(sample.boolean["network_online"])

    def test_a_pressure_event_fires_from_real_inventory_readings(self) -> None:
        loaded = machine(
            physical_memory_bytes=8 * GIB, available_memory_bytes=256 * MIB,
            logical_threads=4, memory_pressure=75.0,
        )
        instance = RuntimeMonitor(settings=MonitorSettings(signals=DEFAULT_SIGNALS))
        instance.observe(sample_from_inventory(loaded, at_monotonic=0.0))
        events = instance.observe(sample_from_inventory(loaded, at_monotonic=30.0))
        self.assertIn("memory_pressure_entered", [item.event for item in events])


class OscillationTests(unittest.TestCase):
    """No rapid start-stop oscillation, across a realistic pressure trace."""

    def test_a_noisy_trace_around_the_threshold_produces_at_most_two_events(self) -> None:
        instance = RuntimeMonitor(settings=MonitorSettings(signals=(PRESSURE,)))
        readings = []
        at = 0.0
        # Twenty minutes of a signal wandering across the entry threshold.
        for step in range(80):
            at += 15.0
            readings.append((at, 55.0 + (10.0 if step % 3 == 0 else -5.0)))
        events = feed(instance, readings)
        self.assertLessEqual(
            len(events), 2,
            f"a wandering signal produced {len(events)} events: {[item.event for item in events]}",
        )

    def test_a_sustained_recovery_is_required_before_the_recovered_event(self) -> None:
        # Resources recover; hysteresis prevents an immediate restoration, and
        # the service is restored only after the recovery holds.
        instance = RuntimeMonitor(settings=MonitorSettings(signals=(PRESSURE,)))
        feed(instance, [(0.0, 90.0), (20.0, 90.0)])
        blip = feed(instance, [(100.0, 5.0), (105.0, 90.0), (115.0, 90.0)])
        self.assertEqual(blip, [])
        sustained = feed(instance, [(200.0, 5.0), (215.0, 5.0), (230.0, 5.0)])
        self.assertEqual([item.event for item in sustained], ["memory_pressure_recovered"])


if __name__ == "__main__":
    unittest.main()
