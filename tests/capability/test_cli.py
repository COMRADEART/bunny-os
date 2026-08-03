# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The ``bunny-os capability`` command group, and schema conformance of its output."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
for candidate in (ROOT, ROOT / "tools/bunny-os"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from bunny_os import capability_cli  # noqa: E402
from capability.policy import PolicyError, parse_policy  # noqa: E402
from capability.registry import load_registry  # noqa: E402
from capability.runtime import assess  # noqa: E402
from capability.simulate import MACHINES, simulate  # noqa: E402

SCHEMAS = ROOT / "schemas"
MIB = 1024 ** 2


def invoke(*argv: str, as_json: bool = False):
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    capability_cli.add_arguments(subparsers)
    args = parser.parse_args(["capability", *argv])
    args.json = as_json
    return capability_cli.dispatch(args)


class CommandTests(unittest.TestCase):
    def test_inspect_renders_the_inventory(self) -> None:
        output = invoke("inspect", "--simulate", "laptop")
        self.assertIn("Capability inventory", output)
        self.assertIn("Memory", output)
        self.assertIn("SIMULATED HARDWARE", output)

    def test_scores_renders_every_dimension(self) -> None:
        from capability.scores import DIMENSIONS

        output = invoke("scores", "--simulate", "laptop")
        for name, _ in DIMENSIONS:
            with self.subTest(dimension=name):
                self.assertIn(name, output)
        self.assertIn("there is no overall score", output)

    def test_budget_renders_the_reserve_and_the_categories(self) -> None:
        output = invoke("budget", "--simulate", "raspberry-pi-class")
        self.assertIn("protected reserve", output)
        self.assertIn("never allocatable", output)
        self.assertIn("local_ai_inference", output)

    def test_plan_lists_every_service(self) -> None:
        output = invoke("plan", "--simulate", "gaming-desktop")
        for service in load_registry():
            with self.subTest(service=service.id):
                self.assertIn(service.id, output)

    def test_status_is_one_line_per_service(self) -> None:
        output = invoke("status", "--simulate", "laptop")
        self.assertIn("bunny.companion", output)
        self.assertIn("start_local", output)

    def test_explain_gives_the_reason_and_the_ladder(self) -> None:
        output = invoke("explain", "bunny.companion", "--simulate", "raspberry-pi-class")
        self.assertIn("bunny.companion runs locally", output)
        self.assertIn("Reason:", output)
        self.assertIn("Implementation ladder", output)
        self.assertIn("no model reasoning", output)

    def test_explain_of_a_refused_service_names_the_measurement_and_the_requirement(self) -> None:
        output = invoke("explain", "bunny.shell.session", "--simulate", "cpu-server")
        self.assertIn("was not started locally", output)
        self.assertIn("Requirements not satisfied", output)
        self.assertIn("display.required", output)
        self.assertIn("required", output)

    def test_explain_of_an_unknown_service_is_refused_with_the_known_list(self) -> None:
        with self.assertRaises(capability_cli.CapabilityError) as caught:
            invoke("explain", "bunny.nonexistent", "--simulate", "laptop")
        self.assertIn("known services", str(caught.exception))

    def test_machines_lists_the_simulations_and_labels_them(self) -> None:
        output = invoke("machines")
        for name in MACHINES:
            with self.subTest(machine=name):
                self.assertIn(name, output)
        self.assertIn("none describes real hardware", output)

    def test_policy_prints_the_effective_settings(self) -> None:
        output = invoke("policy", "--simulate", "laptop")
        self.assertIn("remoteExecution", output)
        self.assertIn("preferLocal", output)

    def test_an_unknown_simulated_machine_is_refused(self) -> None:
        with self.assertRaises(capability_cli.CapabilityError) as caught:
            invoke("plan", "--simulate", "quantum-toaster")
        self.assertIn("unknown simulated machine", str(caught.exception))


class SimulationLabellingTests(unittest.TestCase):
    """A simulated plan must never read as a claim about hardware."""

    def test_every_text_command_carries_the_simulation_banner(self) -> None:
        for command in ("inspect", "scores", "budget", "plan", "status", "policy"):
            with self.subTest(command=command):
                output = invoke(command, "--simulate", "multi-gpu-ai-server")
                self.assertIn("SIMULATED HARDWARE", output)
                self.assertIn("not a measurement of any physical machine", output)

    def test_explain_carries_the_simulation_banner(self) -> None:
        output = invoke("explain", "bunny.companion", "--simulate", "multi-gpu-ai-server")
        self.assertIn("SIMULATED HARDWARE", output)

    def test_the_json_inventory_carries_a_simulation_notice(self) -> None:
        document = invoke("inspect", "--simulate", "laptop", as_json=True)
        self.assertIn("simulationNotice", document)
        self.assertIn("SIMULATED", document["simulationNotice"])


class JsonOutputTests(unittest.TestCase):
    def test_json_output_matches_the_published_schemas(self) -> None:
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema unavailable; schema conformance was not checked")

        pairs = (
            ("inspect", "capability-inventory.schema.json"),
            ("budget", "resource-budget.schema.json"),
            ("plan", "execution-plan.schema.json"),
        )
        for name in MACHINES:
            for command, schema_name in pairs:
                with self.subTest(machine=name, command=command):
                    schema = json.loads((SCHEMAS / schema_name).read_text(encoding="utf-8"))
                    jsonschema.validate(invoke(command, "--simulate", name, as_json=True), schema)

    def test_every_shipped_manifest_matches_the_manifest_schema(self) -> None:
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema unavailable; schema conformance was not checked")

        from capability.registry import DEFAULT_SERVICE_DIRECTORY

        schema = json.loads((SCHEMAS / "service-capability-manifest.schema.json").read_text(encoding="utf-8"))
        paths = sorted(DEFAULT_SERVICE_DIRECTORY.glob("*.json"))
        self.assertGreater(len(paths), 0)
        for path in paths:
            with self.subTest(manifest=path.name):
                jsonschema.validate(json.loads(path.read_text(encoding="utf-8")), schema)

    def test_json_output_is_serialisable(self) -> None:
        for command in ("inspect", "scores", "budget", "plan", "status", "policy", "machines"):
            with self.subTest(command=command):
                arguments = ("machines",) if command == "machines" else (command, "--simulate", "laptop")
                json.dumps(invoke(*arguments, as_json=True))


class InventoryFileTests(unittest.TestCase):
    """A captured inventory can be assessed on a machine that is not its own."""

    def test_a_captured_inventory_produces_the_same_plan_it_would_have(self) -> None:
        import tempfile

        document = simulate("gaming-desktop").to_json()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "inventory.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            from_file = invoke("plan", "--inventory", str(path), as_json=True)
        direct = assess(simulate("gaming-desktop"), registry=load_registry()).plan.to_json()
        self.assertEqual(
            [(d["serviceId"], d["action"], d["implementationId"]) for d in from_file["decisions"]],
            [(d["serviceId"], d["action"], d["implementationId"]) for d in direct["decisions"]],
        )

    def test_an_unreadable_inventory_is_refused_with_the_path(self) -> None:
        with self.assertRaises(capability_cli.CapabilityError) as caught:
            invoke("plan", "--inventory", "/nonexistent/inventory.json")
        self.assertIn("inventory.json", str(caught.exception))


class PolicyFileTests(unittest.TestCase):
    def test_a_mode_based_policy_key_is_refused_with_its_replacement_named(self) -> None:
        # §15: a stale configuration must produce an actionable error, never be
        # silently ignored, which would leave an operator believing a limit was
        # in force when it was not.
        for key in ("performanceMode", "hardwareTier", "capabilityTier", "profile", "powerLevel"):
            with self.subTest(key=key), self.assertRaises(PolicyError) as caught:
                parse_policy({"schemaVersion": 1, key: "high"})
            self.assertIn(key, str(caught.exception))

    def test_the_error_names_what_to_use_instead(self) -> None:
        with self.assertRaises(PolicyError) as caught:
            parse_policy({"schemaVersion": 1, "performanceMode": "ultra"})
        self.assertIn("maximumBackgroundCpuPercent", str(caught.exception))

    def test_a_policy_file_is_read_and_narrows_the_plan(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            path.write_text(json.dumps({
                "schemaVersion": 1,
                "disabledServices": ["bunny.companion"],
                "maximumBackgroundCpuPercent": 5.0,
            }), encoding="utf-8")
            plan = invoke("plan", "--simulate", "gaming-desktop", "--policy", str(path), as_json=True)
        companion = next(d for d in plan["decisions"] if d["serviceId"] == "bunny.companion")
        self.assertEqual(companion["action"], "reject")

    def test_a_malformed_policy_is_refused_rather_than_partially_applied(self) -> None:
        for document in (
            {"schemaVersion": 2},
            {"schemaVersion": 1, "maximumBackgroundCpuPercent": 150},
            {"schemaVersion": 1, "disabledServices": "bunny.companion"},
            {"schemaVersion": 1, "hysteresisFraction": 0.9},
            {"schemaVersion": 1, "reachabilityEndpoints": ["not-a-host-port"]},
            {"schemaVersion": 1, "pinnedImplementations": {"a": 1}},
        ):
            with self.subTest(document=document), self.assertRaises(PolicyError):
                parse_policy(document)

    def test_an_enabled_remote_policy_with_no_provider_warns(self) -> None:
        policy = parse_policy({
            "schemaVersion": 1,
            "remoteExecution": {"enabled": True, "permittedProviders": []},
        })
        self.assertTrue(any("no task can be dispatched" in warning for warning in policy.warnings))

    def test_a_user_policy_may_narrow_but_not_widen(self) -> None:
        from capability.policy import _narrow

        system = parse_policy({
            "schemaVersion": 1,
            "maximumBackgroundCpuPercent": 20.0,
            "meteredNetworkAllowed": False,
            "remoteExecution": {"enabled": False, "permittedProviders": ["approved"]},
        })
        user = parse_policy({
            "schemaVersion": 1,
            "maximumBackgroundCpuPercent": 90.0,
            "meteredNetworkAllowed": True,
            "remoteExecution": {"enabled": True, "permittedProviders": ["approved", "sneaky"]},
        })
        merged = _narrow(system, user)
        self.assertEqual(merged.maximum_background_cpu_percent, 20.0)
        self.assertFalse(merged.metered_network_allowed)
        self.assertFalse(merged.remote_execution.enabled)
        self.assertEqual(merged.remote_execution.permitted_providers, ("approved",))

    def test_a_user_may_narrow_further(self) -> None:
        from capability.policy import _narrow

        system = parse_policy({"schemaVersion": 1, "maximumBackgroundCpuPercent": 80.0})
        user = parse_policy({"schemaVersion": 1, "maximumBackgroundCpuPercent": 10.0})
        self.assertEqual(_narrow(system, user).maximum_background_cpu_percent, 10.0)

    def test_disabled_services_are_the_union_of_both_layers(self) -> None:
        from capability.policy import _narrow

        system = parse_policy({"schemaVersion": 1, "disabledServices": ["a.one"]})
        user = parse_policy({"schemaVersion": 1, "disabledServices": ["b.two"]})
        self.assertEqual(_narrow(system, user).disabled_services, ("a.one", "b.two"))

    def test_defaults_are_privacy_preserving(self) -> None:
        policy = parse_policy({"schemaVersion": 1})
        self.assertTrue(policy.prefer_local)
        self.assertFalse(policy.remote_execution.enabled)
        self.assertFalse(policy.remote_execution.allow_sensitive_data)
        self.assertTrue(policy.remote_execution.require_user_approval)
        self.assertFalse(policy.metered_network_allowed)
        self.assertTrue(policy.confirm_before_paid_api)
        self.assertEqual(policy.reachability_endpoints, ())


class LiveHostTests(unittest.TestCase):
    """The commands must also work on whatever host runs the tests."""

    def test_inspect_runs_against_this_machine_without_raising(self) -> None:
        output = invoke("inspect")
        self.assertIn("Capability inventory", output)
        self.assertNotIn("SIMULATED HARDWARE", output)

    def test_plan_runs_against_this_machine_without_raising(self) -> None:
        output = invoke("plan")
        self.assertIn("Execution plan", output)

    def test_status_runs_against_this_machine_without_raising(self) -> None:
        self.assertIn("bunny.system.broker", invoke("status"))


if __name__ == "__main__":
    unittest.main()
