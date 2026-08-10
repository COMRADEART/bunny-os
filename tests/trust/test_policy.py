# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The decision procedure, asserted on reason codes rather than only on verdicts.

Almost every test here could be written as ``assertFalse(decision.allowed)`` and
almost every one would then pass for the wrong reason. "Denied because you said
no" and "denied because the grant store was corrupt" are the same verdict and
completely different facts, and the second one masquerading as the first is how a
security defect survives a green suite. So each test names the code.
"""

from __future__ import annotations

import unittest

import trust
from trust.categories import CATEGORIES, SCOPES
from trust.decision import DECISION_REASONS
from trust.declaration import UNDECLARED, PermissionDeclaration
from trust.errors import TrustStoreUnreadable
from trust.policy import REASON_CODES, resolve

from tests.capsule_support import World


DECLARATION = PermissionDeclaration(
    application_id="org.example.PhotoEditor",
    required=frozenset({"files", "gpu"}),
    optional=frozenset({"network", "camera", "credentials"}),
    reasons={"files": "to open the picture you choose"},
    network_ceiling="allowlisted",
    network_domains=frozenset({"updates.example.com"}),
)


class PolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.world = World.build()
        self.addCleanup(self.world.close)

    def request(self, category: str, *, resource=None, purpose: str = "use", application: str = "org.example.PhotoEditor"):
        return trust.PermissionRequest.build(
            request_id="r-1",
            application_id=application,
            category=category,
            session_id="session-1",
            resource=resource,
            purpose=purpose,
        )

    def resolve(self, request, *, declaration=DECLARATION, install_consent: bool = False):
        return resolve(request, store=self.world.store, declaration=declaration, install_consent=install_consent)

    # -- the eight ordered checks ----------------------------------------

    def test_an_undeclared_category_never_reaches_a_prompt(self) -> None:
        """The strong form of deny-by-default: no surface is asked at all."""
        outcome = self.resolve(self.request("microphone"))
        self.assertEqual(outcome.verdict, "deny")
        self.assertEqual(outcome.reason_code, "not-declared")
        self.assertEqual(outcome.offered_scopes, ())

    def test_an_application_with_no_catalogue_entry_is_refused(self) -> None:
        outcome = self.resolve(
            self.request("files", resource=trust.path_resource(self.world.file("Pictures/cat.png"))),
            declaration=UNDECLARED("org.example.PhotoEditor"),
        )
        self.assertEqual(outcome.reason_code, "unknown-application")

    def test_a_declaration_for_a_different_application_is_malformed(self) -> None:
        outcome = self.resolve(self.request("gpu", application="org.example.Other"))
        self.assertEqual(outcome.reason_code, "malformed-request")
        self.assertEqual(outcome.failure, "declaration-mismatch")

    def test_a_network_class_above_the_declared_ceiling_is_refused(self) -> None:
        outcome = self.resolve(self.request("network", resource=trust.network_resource("internet")))
        self.assertEqual(outcome.reason_code, "beyond-ceiling")

    def test_a_network_class_inside_the_declared_ceiling_is_asked_about(self) -> None:
        outcome = self.resolve(
            self.request(
                "network",
                resource=trust.network_resource("allowlisted", allowlist=("updates.example.com",)),
            )
        )
        self.assertEqual(outcome.verdict, "prompt")

    def test_a_wider_allowlist_than_declared_is_refused(self) -> None:
        """An entry naming one host cannot become an entry naming two."""
        outcome = self.resolve(
            self.request(
                "network",
                resource=trust.network_resource("allowlisted", allowlist=("updates.example.com", "telemetry.example.net")),
            )
        )
        self.assertEqual(outcome.reason_code, "beyond-ceiling")

    def test_local_network_is_not_subsumed_by_an_allowlist(self) -> None:
        """Reaching a named domain is not consent to enumerate the house."""
        outcome = self.resolve(self.request("network", resource=trust.network_resource("local-network")))
        self.assertEqual(outcome.reason_code, "beyond-ceiling")

    def test_a_declared_category_with_nothing_stored_asks(self) -> None:
        outcome = self.resolve(self.request("gpu"))
        self.assertEqual(outcome.verdict, "prompt")
        self.assertEqual(outcome.reason_code, "needs-user")
        self.assertEqual(outcome.offered_scopes, CATEGORIES["gpu"].allow_scopes)

    def test_an_install_consent_covers_a_required_medium_risk_category(self) -> None:
        outcome = self.resolve(self.request("gpu"), install_consent=True)
        self.assertEqual(outcome.reason_code, "catalog-default")

    def test_an_install_consent_never_covers_a_high_risk_category(self) -> None:
        """camera is optional *and* high risk; two independent reasons to ask."""
        declaration = PermissionDeclaration(
            application_id="org.example.PhotoEditor",
            required=frozenset({"camera"}),
            reasons={},
        )
        outcome = self.resolve(self.request("camera"), declaration=declaration, install_consent=True)
        self.assertEqual(outcome.verdict, "prompt")

    def test_an_install_consent_never_covers_a_critical_risk_category(self) -> None:
        declaration = PermissionDeclaration(
            application_id="org.example.PhotoEditor",
            required=frozenset({"credentials"}),
        )
        outcome = self.resolve(
            self.request("credentials", resource=trust.peer_resource("example-com")),
            declaration=declaration,
            install_consent=True,
        )
        self.assertEqual(outcome.verdict, "prompt")

    # -- fail closed ------------------------------------------------------

    def test_an_unreadable_store_denies_and_says_so(self) -> None:
        class Broken:
            def matching(self, request):  # noqa: D401, ANN001
                raise TrustStoreUnreadable("the grant file is not JSON")

        outcome = resolve(self.request("gpu"), store=Broken(), declaration=DECLARATION)
        self.assertEqual(outcome.verdict, "deny")
        self.assertEqual(outcome.reason_code, "store-unreadable")
        self.assertTrue(outcome.failure)

    def test_a_store_failure_is_checked_before_the_declaration(self) -> None:
        """A corrupt store denies even for a category that would have been refused
        anyway, so the reason a person is shown is the true one."""

        class Broken:
            def matching(self, request):  # noqa: ANN001
                raise TrustStoreUnreadable("damaged")

        outcome = resolve(self.request("microphone"), store=Broken(), declaration=DECLARATION)
        self.assertEqual(outcome.reason_code, "store-unreadable")

    # -- the vocabulary itself -------------------------------------------

    def test_every_policy_reason_code_is_a_decision_reason(self) -> None:
        self.assertTrue(set(REASON_CODES) <= set(DECISION_REASONS))

    def test_every_decision_reason_has_a_sentence(self) -> None:
        """A decision nothing can explain reaches a person as a blank refusal."""
        from trust.explain import _DECISION_SENTENCES

        self.assertEqual(set(DECISION_SENTENCES_KEYS(_DECISION_SENTENCES)), set(DECISION_REASONS))

    def test_offered_scopes_come_from_the_table_not_the_request(self) -> None:
        for category, entry in CATEGORIES.items():
            for scope in entry.allow_scopes:
                self.assertIn(scope, SCOPES)
            self.assertTrue(entry.allow_scopes, f"{category} can only ever deny")


def DECISION_SENTENCES_KEYS(mapping):  # noqa: N802 - reads as a helper in the assertion
    return tuple(mapping)


if __name__ == "__main__":
    unittest.main()
