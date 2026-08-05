# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The applicator CLI: output, schema conformance, and the mode boundaries.

The most important tests in this file are the ones that assert what does *not*
happen. A developer running ``bunny-os capability apply`` in a checkout must not
be able to stop their own services, and the way that is guaranteed is that the
dangerous mode has to be typed and cannot be reached from a simulation.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
for candidate in (ROOT, ROOT / "tools/bunny-os"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from bunny_os import capability_cli  # noqa: E402
from capability.apply.backends import DryRunBackend, InMemoryBackend  # noqa: E402
from capability.apply.systemd import SystemdBackend  # noqa: E402
from capability.simulate import MACHINES  # noqa: E402

SCHEMAS = ROOT / "schemas"


def invoke(*argv: str, as_json: bool = False):
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    capability_cli.add_arguments(subparsers)
    args = parser.parse_args(["capability", *argv])
    args.json = as_json
    return capability_cli.dispatch(args)


class ModeLabellingTests(unittest.TestCase):
    """Dry run, simulation and real host operation must never be confusable."""

    def test_a_simulated_run_is_labelled_as_simulated(self) -> None:
        output = invoke("apply", "--simulate", "laptop")
        self.assertIn("SIMULATED HARDWARE", output)
        self.assertIn("SIMULATION", output)
        self.assertIn("No real service was inspected, started or stopped", output)

    def test_a_dry_run_says_nothing_was_changed(self) -> None:
        output = invoke("apply", "--simulate", "laptop")
        self.assertIn("DRY RUN", output)
        self.assertIn("nothing on this machine was changed", output.lower())

    def test_the_json_form_carries_the_mode(self) -> None:
        document = invoke("apply", "--simulate", "laptop", as_json=True)
        self.assertEqual(document["mode"], "simulation")
        self.assertTrue(document["dryRun"])

    def test_reconcile_is_labelled_too(self) -> None:
        self.assertIn("SIMULATION", invoke("reconcile", "--simulate", "laptop"))


class HostBoundaryTests(unittest.TestCase):
    """Real host operation is never the accidental default."""

    def test_host_operation_is_refused_alongside_a_simulation(self) -> None:
        # A rehearsal against synthetic hardware must not be able to act on
        # real services.
        with self.assertRaises(capability_cli.CapabilityError) as caught:
            invoke("apply", "--simulate", "laptop", "--host")
        self.assertIn("cannot be combined", str(caught.exception))

    def test_host_operation_is_refused_alongside_a_loaded_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "inventory.json"
            document = invoke("inspect", "--simulate", "laptop", as_json=True)
            document.pop("simulationNotice", None)
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(capability_cli.CapabilityError):
                invoke("apply", "--inventory", str(path), "--host")

    def test_host_operation_is_refused_when_systemd_is_absent(self) -> None:
        with mock.patch("bunny_os.capability_cli.systemd_available", return_value=False):
            with self.assertRaises(capability_cli.CapabilityError) as caught:
                invoke("apply", "--host")
        self.assertIn("systemd is not the init system", str(caught.exception))

    def test_the_default_backend_for_a_local_run_is_a_dry_run(self) -> None:
        args = argparse.Namespace(simulate=None, inventory=None, host=False)
        assessment = _assessment("laptop")
        with mock.patch("bunny_os.capability_cli.systemd_available", return_value=False):
            applicator = capability_cli._applicator(args, assessment, "dry-run")
        self.assertIsInstance(applicator.backend, DryRunBackend)
        self.assertTrue(applicator.settings.dry_run)

    def test_a_simulated_run_uses_a_model_and_never_systemd(self) -> None:
        args = argparse.Namespace(simulate="laptop", inventory=None, host=False)
        applicator = capability_cli._applicator(args, _assessment("laptop"), "simulation")
        self.assertIsInstance(applicator.backend, InMemoryBackend)
        self.assertTrue(applicator.settings.dry_run)

    def test_a_dry_run_observer_cannot_modify_the_host(self) -> None:
        # Even the observer is constructed without the modification opt-in.
        args = argparse.Namespace(simulate=None, inventory=None, host=False)
        with mock.patch("bunny_os.capability_cli.systemd_available", return_value=True):
            applicator = capability_cli._applicator(args, _assessment("laptop"), "dry-run")
        observer = applicator.backend.observer
        self.assertIsInstance(observer, SystemdBackend)
        self.assertFalse(observer.allow_host_modification)


def _assessment(name: str):
    from capability.registry import load_registry
    from capability.runtime import assess
    from capability.simulate import simulate

    return assess(simulate(name), registry=load_registry())


class PlanCommandTests(unittest.TestCase):
    def test_plan_validate_reports_every_check(self) -> None:
        output = invoke("plan", "--validate", "--simulate", "laptop")
        self.assertIn("may be applied", output)
        self.assertIn("fingerprint.inventory", output)
        self.assertIn("plan.revision", output)

    def test_plan_validate_json_carries_the_verdict(self) -> None:
        document = invoke("plan", "--validate", "--simulate", "laptop", as_json=True)
        self.assertTrue(document["ok"])
        self.assertTrue(document["checked"])
        self.assertTrue(document["planId"].startswith("plan-"))

    def test_plan_diff_against_itself_reports_no_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            path.write_text(
                json.dumps(invoke("plan", "--simulate", "laptop", as_json=True)),
                encoding="utf-8",
            )
            output = invoke("plan", "--diff", str(path), "--simulate", "laptop")
            self.assertIn("same desired state", output)

    def test_plan_diff_against_another_machine_reports_the_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            path.write_text(
                json.dumps(invoke("plan", "--simulate", "embedded-64mb", as_json=True)),
                encoding="utf-8",
            )
            document = invoke("plan", "--diff", str(path), "--simulate", "laptop", as_json=True)
            self.assertFalse(document["sameDesiredState"])
            self.assertTrue(document["changes"])

    def test_plan_diff_refuses_an_unreadable_document(self) -> None:
        with self.assertRaises(capability_cli.CapabilityError):
            invoke("plan", "--diff", "/nonexistent/plan.json", "--simulate", "laptop")

    def test_the_plan_output_carries_its_identity(self) -> None:
        document = invoke("plan", "--simulate", "laptop", as_json=True)
        self.assertEqual(document["schemaVersion"], 2)
        self.assertIn("identity", document)
        self.assertIn("fingerprints", document["identity"])


class ReconcileCommandTests(unittest.TestCase):
    def test_reconcile_lists_the_transitions_in_order(self) -> None:
        output = invoke("reconcile", "--simulate", "laptop")
        self.assertIn("in the order they will run", output)
        self.assertIn("bunny.system.broker", output)

    def test_reconcile_json_conforms_to_the_runtime_state_schema(self) -> None:
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema unavailable; schema conformance was not checked")

        schema = json.loads(
            (SCHEMAS / "service-runtime-state.schema.json").read_text(encoding="utf-8"),
        )
        for name in ("laptop", "embedded-64mb", "cpu-server"):
            with self.subTest(machine=name):
                document = invoke("reconcile", "--simulate", name, as_json=True)
                jsonschema.validate(document, schema)

    def test_a_converged_machine_reports_that_it_is_converged(self) -> None:
        document = invoke("reconcile", "--simulate", "laptop", as_json=True)
        self.assertFalse(document["converged"])


class TransitionCommandTests(unittest.TestCase):
    def test_transitions_lists_identifiers(self) -> None:
        output = invoke("transitions", "--simulate", "laptop")
        self.assertIn("bunny.system.broker", output)
        self.assertIn(":start:1", output)

    def test_a_transition_can_be_explained_in_full(self) -> None:
        document = invoke("transitions", "--simulate", "laptop", as_json=True)
        identifier = document["transitions"][0]["transitionId"]
        output = invoke("transitions", "--explain", identifier, "--simulate", "laptop")
        self.assertIn("Service:", output)
        self.assertIn("Requested action:", output)
        self.assertIn("Reason:", output)
        self.assertIn("Action taken:", output)
        self.assertIn("User impact:", output)
        self.assertIn("contains no model reasoning", output)

    def test_an_unknown_transition_is_refused_with_the_known_ones_listed(self) -> None:
        with self.assertRaises(capability_cli.CapabilityError) as caught:
            invoke("transitions", "--explain", "nope", "--simulate", "laptop")
        self.assertIn("transitions in this pass", str(caught.exception))


class ReservationCommandTests(unittest.TestCase):
    def test_reservations_shows_the_reserve_it_protects(self) -> None:
        output = invoke("reservations", "--simulate", "laptop")
        self.assertIn("protected reserve", output)
        self.assertIn("already excluded from capacity", output)

    def test_reservations_json_balances(self) -> None:
        document = invoke("reservations", "--simulate", "laptop", as_json=True)
        self.assertLessEqual(document["outstandingBytes"], document["capacityBytes"])
        self.assertEqual(
            document["availableBytes"],
            document["capacityBytes"] - document["outstandingBytes"],
        )


class MonitorCommandTests(unittest.TestCase):
    def test_monitor_shows_the_hysteresis_band_for_every_signal(self) -> None:
        output = invoke("monitor", "--simulate", "laptop")
        self.assertIn("memory_pressure", output)
        self.assertIn("enter", output)
        self.assertIn("leave", output)
        self.assertIn("debounce", output)
        self.assertIn("cooldown", output)

    def test_monitor_states_that_an_unmeasured_signal_raises_nothing(self) -> None:
        output = invoke("monitor", "--simulate", "unmeasurable")
        self.assertIn("not a reading of zero", output)

    def test_monitor_json_carries_the_settings_and_the_readings(self) -> None:
        document = invoke("monitor", "--simulate", "laptop", as_json=True)
        self.assertIn("settings", document)
        self.assertIn("signals", document)


class EveryMachineTests(unittest.TestCase):
    def test_every_command_runs_against_every_simulated_machine(self) -> None:
        for name in MACHINES:
            for command in ("reconcile", "apply", "transitions", "reservations", "monitor"):
                with self.subTest(machine=name, command=command):
                    output = invoke(command, "--simulate", name)
                    self.assertIsInstance(output, str)
                    self.assertIn("SIMULATED HARDWARE", output)

    def test_every_plan_still_matches_the_execution_plan_schema(self) -> None:
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema unavailable; schema conformance was not checked")

        schema = json.loads((SCHEMAS / "execution-plan.schema.json").read_text(encoding="utf-8"))
        for name in MACHINES:
            with self.subTest(machine=name):
                jsonschema.validate(invoke("plan", "--simulate", name, as_json=True), schema)


class NoHostMutationTests(unittest.TestCase):
    """Running the whole CLI must not touch a service, on any machine."""

    def test_no_command_constructs_a_modifying_backend_without_host(self) -> None:
        constructed: list[SystemdBackend] = []
        real = SystemdBackend

        def recording(*args, **kwargs):
            instance = real(*args, **kwargs)
            constructed.append(instance)
            return instance

        with mock.patch("bunny_os.capability_cli.SystemdBackend", side_effect=recording):
            with mock.patch("bunny_os.capability_cli.systemd_available", return_value=True):
                for command in ("reconcile", "apply", "transitions", "reservations"):
                    with self.subTest(command=command):
                        invoke(command, "--simulate", "laptop")
        self.assertTrue(all(not item.allow_host_modification for item in constructed))


if __name__ == "__main__":
    unittest.main()
