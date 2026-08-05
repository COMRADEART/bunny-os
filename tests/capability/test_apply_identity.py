# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Plan identity: determinism, supersession, and what a fingerprint must not carry."""

from __future__ import annotations

from dataclasses import replace
import json
import unittest

from capability import PLAN_SCHEMA_VERSION
from capability.apply.identity import (
    DEFAULT_MAXIMUM_AGE_SECONDS,
    PlanIdentity,
    REEVALUATION_REASONS,
    budget_fingerprint,
    canonical_json,
    digest,
    inventory_fingerprint,
    policy_fingerprint,
    registry_fingerprint,
)
from capability.policy import Policy, RemoteExecutionPolicy
from capability.registry import load_registry
from capability.runtime import assess
from capability.simulate import MACHINES, simulate

REGISTRY = load_registry()


class CanonicalSerializationTests(unittest.TestCase):
    def test_key_order_does_not_change_the_serialization(self) -> None:
        self.assertEqual(
            canonical_json({"b": 1, "a": 2}),
            canonical_json({"a": 2, "b": 1}),
        )

    def test_whitespace_does_not_change_the_digest(self) -> None:
        self.assertEqual(digest({"a": [1, 2]}), digest(json.loads('{"a": [1,   2]}')))

    def test_a_set_is_refused_rather_than_ordered_arbitrarily(self) -> None:
        # A set's iteration order is not a property of its contents, so hashing
        # one would make a fingerprint depend on the interpreter.
        with self.assertRaises(TypeError) as caught:
            canonical_json({"values": {1, 2, 3}})
        self.assertIn("no defined order", str(caught.exception))

    def test_an_unserializable_object_is_refused_rather_than_stringified(self) -> None:
        class Opaque:
            pass

        with self.assertRaises(TypeError):
            canonical_json({"thing": Opaque()})


class FingerprintTests(unittest.TestCase):
    def test_the_same_machine_fingerprints_the_same_way(self) -> None:
        self.assertEqual(
            inventory_fingerprint(simulate("laptop")),
            inventory_fingerprint(simulate("laptop")),
        )

    def test_different_machines_fingerprint_differently(self) -> None:
        seen = {name: inventory_fingerprint(simulate(name)) for name in MACHINES}
        self.assertEqual(len(set(seen.values())), len(seen))

    def test_detection_time_is_excluded_from_the_inventory_fingerprint(self) -> None:
        # A plan is not a different plan for having been decided a second later.
        original = simulate("laptop")
        later = replace(original, detected_at="2027-06-06T12:34:56Z", detection_duration_ms=999)
        self.assertEqual(inventory_fingerprint(original), inventory_fingerprint(later))

    def test_a_probe_that_failed_does_change_the_inventory_fingerprint(self) -> None:
        # Probe outcomes are decision-relevant even when the durations are not.
        original = simulate("laptop")
        degraded = replace(original, probes=tuple(
            replace(item, state="failed") for item in original.probes
        ))
        self.assertNotEqual(inventory_fingerprint(original), inventory_fingerprint(degraded))

    def test_policy_source_does_not_change_the_policy_fingerprint(self) -> None:
        # Otherwise passing --policy in a test would look like a policy change.
        self.assertEqual(
            policy_fingerprint(Policy(source="/etc/bunny-os/capability-policy.json")),
            policy_fingerprint(Policy(source="/tmp/test-policy.json")),
        )

    def test_a_changed_permission_does_change_the_policy_fingerprint(self) -> None:
        permissive = Policy(remote_execution=RemoteExecutionPolicy(enabled=True))
        self.assertNotEqual(policy_fingerprint(Policy()), policy_fingerprint(permissive))

    def test_a_changed_manifest_changes_the_registry_fingerprint(self) -> None:
        from capability.manifest import parse_manifest
        from capability.registry import build_registry

        def registry_with(memory: int):
            return build_registry([parse_manifest({
                "schemaVersion": 1, "id": "test.service", "title": "T",
                "essential": False, "priority": "standard",
                "budgetCategory": "optional_services",
                "implementations": [{
                    "id": "only", "title": "Only", "locality": "local", "rank": 1,
                    "requirements": {"memory": {"minimumBytes": memory}},
                }],
            })])

        self.assertNotEqual(
            registry_fingerprint(registry_with(64 * 1024 ** 2)),
            registry_fingerprint(registry_with(128 * 1024 ** 2)),
        )

    def test_a_fingerprint_carries_nothing_that_names_the_machine(self) -> None:
        # The inventory model collects no identifiers at all, and the projection
        # narrows further. This asserts the property the privacy model depends on.
        document = simulate("laptop").to_json()
        text = canonical_json(document).lower()
        for forbidden in ("serial", "macaddress", "hostname", "uuid"):
            with self.subTest(field=forbidden):
                self.assertNotIn(forbidden, text)


class PlanIdentityTests(unittest.TestCase):
    def test_the_same_inputs_produce_the_same_plan_id(self) -> None:
        first = assess(simulate("laptop"), registry=REGISTRY).plan
        second = assess(simulate("laptop"), registry=REGISTRY).plan
        self.assertEqual(first.plan_id, second.plan_id)
        self.assertEqual(first.identity.content_digest, second.identity.content_digest)

    def test_every_plan_carries_an_identity(self) -> None:
        for name in MACHINES:
            with self.subTest(machine=name):
                plan = assess(simulate(name), registry=REGISTRY).plan
                self.assertIsNotNone(plan.identity)
                self.assertEqual(plan.identity.schema_version, PLAN_SCHEMA_VERSION)
                self.assertEqual(plan.identity.revision, 1)

    def test_revision_increases_along_a_chain_of_reevaluations(self) -> None:
        inventory = simulate("laptop")
        plan = assess(inventory, registry=REGISTRY).plan
        for expected in (2, 3, 4):
            plan = assess(inventory, registry=REGISTRY, previous=plan, now=float(expected)).plan
            self.assertEqual(plan.identity.revision, expected)

    def test_the_previous_plan_id_links_the_chain(self) -> None:
        inventory = simulate("laptop")
        first = assess(inventory, registry=REGISTRY).plan
        second = assess(inventory, registry=REGISTRY, previous=first, now=10.0).plan
        self.assertEqual(second.identity.previous_plan_id, first.plan_id)

    def test_a_settled_machine_reaches_a_stable_content_digest(self) -> None:
        # This is what makes reconciliation idempotent: reevaluating an
        # unchanged machine must converge on one desired state rather than
        # oscillating between two.
        inventory = simulate("laptop")
        plan = assess(inventory, registry=REGISTRY).plan
        digests = []
        for step in range(4):
            plan = assess(inventory, registry=REGISTRY, previous=plan, now=100.0 * (step + 1)).plan
            digests.append(plan.identity.content_digest)
        self.assertEqual(len(set(digests)), 1, "the plan never settled")

    def test_a_higher_revision_supersedes_a_lower_one(self) -> None:
        inventory = simulate("laptop")
        first = assess(inventory, registry=REGISTRY).plan
        second = assess(inventory, registry=REGISTRY, previous=first, now=10.0).plan
        self.assertTrue(second.identity.supersedes(first.identity))
        self.assertFalse(first.identity.supersedes(second.identity))

    def test_an_equal_revision_does_not_supersede(self) -> None:
        # A replayed plan at the same revision must not displace the one in
        # force, even if its content differs.
        plan = assess(simulate("laptop"), registry=REGISTRY).plan
        replayed = replace(plan.identity, content_digest="0" * 32)
        self.assertFalse(replayed.supersedes(plan.identity))

    def test_expiry_uses_the_engine_clock_and_not_wall_clock(self) -> None:
        identity = assess(simulate("laptop"), registry=REGISTRY, now=1000.0).plan.identity
        self.assertFalse(identity.expired(1000.0 + DEFAULT_MAXIMUM_AGE_SECONDS - 1))
        self.assertTrue(identity.expired(1000.0 + DEFAULT_MAXIMUM_AGE_SECONDS + 1))

    def test_a_clock_reading_from_before_the_plan_is_not_a_negative_age(self) -> None:
        identity = assess(simulate("laptop"), registry=REGISTRY, now=500.0).plan.identity
        self.assertEqual(identity.age_seconds(100.0), 0.0)

    def test_identical_content_is_recognised_across_revisions(self) -> None:
        inventory = simulate("laptop")
        settled = assess(inventory, registry=REGISTRY).plan
        settled = assess(inventory, registry=REGISTRY, previous=settled, now=10.0).plan
        again = assess(inventory, registry=REGISTRY, previous=settled, now=20.0).plan
        self.assertNotEqual(settled.plan_id, again.plan_id)
        self.assertTrue(again.identity.describes_same_desired_state(settled.identity))

    def test_an_unknown_reevaluation_reason_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            PlanIdentity(
                "plan-1", 2, 1, "a" * 32, "b" * 32, "c" * 32, "d" * 32, "e" * 32,
                reevaluation_reason="because-i-felt-like-it",
            )

    def test_every_reevaluation_reason_is_accepted(self) -> None:
        for reason in REEVALUATION_REASONS:
            with self.subTest(reason=reason):
                identity = PlanIdentity(
                    "plan-1", 2, 1, "a" * 32, "b" * 32, "c" * 32, "d" * 32, "e" * 32,
                    reevaluation_reason=reason,
                )
                self.assertEqual(identity.reevaluation_reason, reason)


class IdentitySerializationTests(unittest.TestCase):
    def test_an_identity_survives_a_round_trip(self) -> None:
        original = assess(simulate("gaming-desktop"), registry=REGISTRY).plan.identity
        restored = PlanIdentity.from_json(original.to_json())
        self.assertEqual(restored, original)

    def test_a_missing_fingerprint_block_is_refused_rather_than_defaulted(self) -> None:
        # A missing fingerprint that read as None would compare unequal to the
        # observed one and look like "the machine changed", sending the
        # applicator into a reevaluation loop instead of reporting bad input.
        document = assess(simulate("laptop"), registry=REGISTRY).plan.identity.to_json()
        del document["fingerprints"]
        with self.assertRaises(ValueError) as caught:
            PlanIdentity.from_json(document)
        self.assertIn("fingerprints", str(caught.exception))

    def test_a_non_integer_revision_is_refused(self) -> None:
        document = assess(simulate("laptop"), registry=REGISTRY).plan.identity.to_json()
        document["revision"] = "2"
        with self.assertRaises(ValueError):
            PlanIdentity.from_json(document)

    def test_a_zero_revision_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            PlanIdentity("plan-1", 2, 0, "a" * 32, "b" * 32, "c" * 32, "d" * 32, "e" * 32)


if __name__ == "__main__":
    unittest.main()
