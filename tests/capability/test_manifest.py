# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Manifest validation and registry consistency.

A manifest is a safety input: it is what tells the engine how much memory a
service needs *before* that service is started. So validation refuses rather
than repairs, and every test here asserts that a malformed declaration raises
instead of being partially honoured.
"""

from __future__ import annotations

import json
import unittest

from capability.budget import ESSENTIAL_CATEGORY
from capability.manifest import ManifestError, PRIORITIES, parse_manifest, parse_requirements
from capability.registry import DEFAULT_SERVICE_DIRECTORY, build_registry, load_registry

MIB = 1024 ** 2
GIB = 1024 ** 3


def document(**overrides):
    value = {
        "schemaVersion": 1,
        "id": "test.service",
        "title": "Test service",
        "essential": False,
        "priority": "standard",
        "budgetCategory": "optional_services",
        "implementations": [
            {"id": "only", "title": "Only", "locality": "local", "rank": 1,
             "requirements": {"memory": {"minimumBytes": 64 * MIB}}},
        ],
    }
    value.update(overrides)
    return value


class ManifestValidationTests(unittest.TestCase):
    def test_a_valid_manifest_parses(self) -> None:
        manifest = parse_manifest(document())
        self.assertEqual(manifest.id, "test.service")
        self.assertEqual(manifest.priority, PRIORITIES["standard"])

    def test_an_unsupported_schema_version_is_refused(self) -> None:
        with self.assertRaises(ManifestError):
            parse_manifest(document(schemaVersion=2))

    def test_a_malformed_service_id_is_refused(self) -> None:
        for identifier in ("Test.Service", "noDot", "test..service", "", "test.SERVICE"):
            with self.subTest(id=identifier), self.assertRaises(ManifestError):
                parse_manifest(document(id=identifier))

    def test_a_manifest_with_no_implementations_is_refused(self) -> None:
        with self.assertRaises(ManifestError):
            parse_manifest(document(implementations=[]))

    def test_duplicate_implementation_ids_are_refused(self) -> None:
        with self.assertRaises(ManifestError):
            parse_manifest(document(implementations=[
                {"id": "same", "locality": "local", "rank": 1, "requirements": {}},
                {"id": "same", "locality": "local", "rank": 2, "requirements": {}},
            ]))

    def test_an_essential_service_without_a_local_implementation_is_refused(self) -> None:
        # A control plane that only runs remotely cannot bring up the machine
        # it runs on.
        with self.assertRaises(ManifestError) as caught:
            parse_manifest(document(
                essential=True, budgetCategory=ESSENTIAL_CATEGORY,
                implementations=[{"id": "remote", "locality": "remote", "rank": 1,
                                  "provider": "somewhere", "requirements": {}}],
            ))
        self.assertIn("local implementation", str(caught.exception))

    def test_a_remote_implementation_may_not_deny_sending_data_remotely(self) -> None:
        with self.assertRaises(ManifestError):
            parse_manifest(document(implementations=[
                {"id": "remote", "locality": "remote", "rank": 1, "provider": "x",
                 "sendsUserDataRemotely": False, "requirements": {}},
            ]))

    def test_a_service_may_not_depend_on_itself(self) -> None:
        with self.assertRaises(ManifestError):
            parse_manifest(document(dependencies={"requires": ["test.service"]}))

    def test_a_service_may_not_both_require_and_conflict_with_the_same_service(self) -> None:
        with self.assertRaises(ManifestError):
            parse_manifest(document(dependencies={"requires": ["a.b"], "conflictsWith": ["a.b"]}))

    def test_a_recommended_below_the_minimum_is_refused(self) -> None:
        with self.assertRaises(ManifestError):
            parse_requirements({"memory": {"minimumBytes": 100, "recommendedBytes": 50}})

    def test_a_negative_memory_requirement_is_refused(self) -> None:
        with self.assertRaises(ManifestError):
            parse_requirements({"memory": {"minimumBytes": -1}})

    def test_an_unknown_gpu_runtime_is_refused(self) -> None:
        with self.assertRaises(ManifestError):
            parse_requirements({"gpu": {"required": True, "runtime": "metal"}})

    def test_a_malformed_resolution_is_refused(self) -> None:
        with self.assertRaises(ManifestError):
            parse_requirements({"display": {"required": True, "minimumResolution": "big"}})

    def test_a_score_gate_outside_the_documented_range_is_refused(self) -> None:
        with self.assertRaises(ManifestError):
            parse_requirements({"scores": {"graphics": 250.0}})

    def test_an_unknown_restart_policy_is_refused(self) -> None:
        with self.assertRaises(ManifestError):
            parse_manifest(document(execution={"restartPolicy": "sometimes"}))

    def test_priority_accepts_a_band_or_an_integer(self) -> None:
        self.assertEqual(parse_manifest(document(priority="critical")).priority, 90)
        self.assertEqual(parse_manifest(document(priority=42)).priority, 42)
        with self.assertRaises(ManifestError):
            parse_manifest(document(priority="enormous"))
        with self.assertRaises(ManifestError):
            parse_manifest(document(priority=500))


class DegradationLadderTests(unittest.TestCase):
    def test_implementations_are_ordered_by_rank(self) -> None:
        manifest = parse_manifest(document(implementations=[
            {"id": "poor", "locality": "local", "rank": 3, "requirements": {}},
            {"id": "rich", "locality": "local", "rank": 1, "requirements": {}},
            {"id": "middling", "locality": "local", "rank": 2, "requirements": {}},
        ]))
        self.assertEqual([item.id for item in manifest.ordered_implementations()],
                         ["rich", "middling", "poor"])

    def test_a_service_with_one_local_implementation_is_not_degradable(self) -> None:
        self.assertFalse(parse_manifest(document()).degradable)

    def test_a_service_with_several_local_implementations_is_degradable(self) -> None:
        manifest = parse_manifest(document(implementations=[
            {"id": "rich", "locality": "local", "rank": 1, "requirements": {}},
            {"id": "poor", "locality": "local", "rank": 2, "requirements": {}},
        ]))
        self.assertTrue(manifest.degradable)

    def test_remote_support_is_derived_from_the_implementations(self) -> None:
        self.assertFalse(parse_manifest(document()).supports_remote)
        with_remote = parse_manifest(document(implementations=[
            {"id": "local", "locality": "local", "rank": 1, "requirements": {}},
            {"id": "remote", "locality": "remote", "rank": 2, "provider": "x", "requirements": {}},
        ]))
        self.assertTrue(with_remote.supports_remote)


class RegistryConsistencyTests(unittest.TestCase):
    def test_a_dependency_nothing_declares_is_refused(self) -> None:
        with self.assertRaises(ManifestError) as caught:
            build_registry([parse_manifest(document(dependencies={"requires": ["nobody.ships.this"]}))])
        self.assertIn("no manifest declares", str(caught.exception))

    def test_an_asymmetric_conflict_is_refused(self) -> None:
        # Otherwise the engine's verdict would depend on evaluation order.
        with self.assertRaises(ManifestError) as caught:
            build_registry([
                parse_manifest(document(id="a.one", dependencies={"conflictsWith": ["a.two"]})),
                parse_manifest(document(id="a.two")),
            ])
        self.assertIn("does not declare back", str(caught.exception))

    def test_a_symmetric_conflict_is_accepted(self) -> None:
        registry = build_registry([
            parse_manifest(document(id="a.one", dependencies={"conflictsWith": ["a.two"]})),
            parse_manifest(document(id="a.two", dependencies={"conflictsWith": ["a.one"]})),
        ])
        self.assertEqual(len(registry), 2)

    def test_a_dependency_cycle_is_refused(self) -> None:
        with self.assertRaises(ManifestError) as caught:
            build_registry([
                parse_manifest(document(id="a.one", dependencies={"requires": ["a.two"]})),
                parse_manifest(document(id="a.two", dependencies={"requires": ["a.one"]})),
            ])
        self.assertIn("cycle", str(caught.exception))

    def test_an_essential_service_in_a_discretionary_category_is_refused(self) -> None:
        with self.assertRaises(ManifestError) as caught:
            build_registry([parse_manifest(document(essential=True, budgetCategory="optional_services"))])
        self.assertIn("essential_services", str(caught.exception))

    def test_an_optional_service_in_the_essential_category_is_refused(self) -> None:
        with self.assertRaises(ManifestError):
            build_registry([parse_manifest(document(essential=False, budgetCategory=ESSENTIAL_CATEGORY))])

    def test_an_unknown_budget_category_is_refused(self) -> None:
        with self.assertRaises(ManifestError):
            build_registry([parse_manifest(document(budgetCategory="miscellaneous"))])

    def test_start_order_places_dependencies_before_dependents(self) -> None:
        registry = load_registry()
        order = [service.id for service in registry.start_order()]
        for service in registry:
            for dependency in service.requires:
                with self.subTest(service=service.id, dependency=dependency):
                    self.assertLess(order.index(dependency), order.index(service.id))

    def test_essential_services_are_ordered_first(self) -> None:
        registry = load_registry()
        order = registry.start_order()
        essential_positions = [index for index, item in enumerate(order) if item.essential]
        self.assertEqual(essential_positions, list(range(len(essential_positions))))

    def test_ordering_is_stable_across_repeated_loads(self) -> None:
        first = [item.id for item in load_registry().start_order()]
        second = [item.id for item in load_registry().start_order()]
        self.assertEqual(first, second)


class ShippedManifestTests(unittest.TestCase):
    """The manifests Bunny OS actually ships."""

    def setUp(self) -> None:
        self.registry = load_registry()

    def test_every_shipped_manifest_loads(self) -> None:
        paths = sorted(DEFAULT_SERVICE_DIRECTORY.glob("*.json"))
        self.assertGreater(len(paths), 0)
        self.assertEqual(len(self.registry), len(paths))

    def test_the_essential_set_is_a_control_plane_and_not_a_desktop(self) -> None:
        essential = {service.id for service in self.registry.essential()}
        # §5: on severely constrained hardware these must remain local.
        for identifier in ("bunny.system.broker", "bunny.system.health", "bunny.system.recovery"):
            self.assertIn(identifier, essential)
        # And these must not be essential, because they cannot fit in 64 MB.
        for identifier in ("bunny.shell.session", "bunny.inference.local", "bunny.companion",
                           "bunny.browser.automation", "bunny.memory.vector"):
            self.assertNotIn(identifier, essential)

    def test_the_essential_floor_fits_within_a_64_megabyte_machine(self) -> None:
        # The architectural constraint from §5, asserted as arithmetic.
        self.assertLess(self.registry.essential_floor_bytes(), 40 * MIB)

    def test_no_manifest_contains_a_mode_word_anywhere(self) -> None:
        """The project rule, asserted as a property of the shipped bytes.

        This is a plain substring search on purpose. A structural check would
        pass a manifest with ``"priority": "high"``, and the whole point is that
        a reader grepping this tree for a performance mode should find nothing
        at all rather than find something they must then reason about. The
        priority vocabulary was renamed to make this assertion possible.
        """
        forbidden = ("low", "balanced", "high", "ultra", "tier", "mode")
        for path in sorted(DEFAULT_SERVICE_DIRECTORY.glob("*.json")):
            text = path.read_text(encoding="utf-8").lower()
            for word in forbidden:
                with self.subTest(path=path.name, word=word):
                    self.assertNotIn(f'"{word}"', text)
                    self.assertNotIn(f'"{word}-', text)

    def test_no_manifest_declares_a_mode_shaped_key(self) -> None:
        shaped = {"mode", "tier", "profile", "performancemode", "hardwareclass", "powerlevel"}

        def walk(value, path: str) -> None:
            if isinstance(value, dict):
                for key, item in value.items():
                    self.assertNotIn(
                        key.lower(), shaped,
                        f"{path}.{key} names a mode; capability is derived from measurement",
                    )
                    walk(item, f"{path}.{key}")
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    walk(item, f"{path}[{index}]")

        for path in sorted(DEFAULT_SERVICE_DIRECTORY.glob("*.json")):
            walk(json.loads(path.read_text(encoding="utf-8")), path.name)

    def test_the_priority_vocabulary_avoids_the_reserved_words(self) -> None:
        self.assertNotIn("low", PRIORITIES)
        self.assertNotIn("high", PRIORITIES)
        self.assertEqual(len(PRIORITIES), 5)

    def test_every_service_that_handles_sensitive_data_says_so(self) -> None:
        for identifier in ("bunny.inference.local", "bunny.speech.recognition",
                           "bunny.memory.vector", "bunny.browser.automation"):
            with self.subTest(service=identifier):
                self.assertTrue(self.registry.get(identifier).handles_sensitive_data)

    def test_every_remote_implementation_names_a_provider(self) -> None:
        # An unnamed destination cannot be allowlisted, so it could never be
        # authorised; a manifest declaring one would be dead weight that looks
        # like a capability.
        for service in self.registry:
            for implementation in service.implementations:
                if implementation.locality == "remote":
                    with self.subTest(service=service.id, implementation=implementation.id):
                        self.assertTrue(implementation.provider)

    def test_the_companion_ladder_reaches_a_floor_that_needs_nothing(self) -> None:
        companion = self.registry.get("bunny.companion")
        floor = companion.ordered_implementations()[-1]
        self.assertEqual(floor.id, "text-only")
        self.assertFalse(floor.requirements.display_required)
        self.assertFalse(floor.requirements.gpu_required)
        self.assertFalse(floor.requirements.audio_output_required)

    def test_shipped_manifests_are_json_and_parse_as_committed(self) -> None:
        for path in sorted(DEFAULT_SERVICE_DIRECTORY.glob("*.json")):
            with self.subTest(path=path.name):
                json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
