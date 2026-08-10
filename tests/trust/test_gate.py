# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The gate: everything that must not be able to become an allow.

The permission surface is the most exposed component in this design — it draws,
it takes input, it runs in the user's session — so the tests that matter here are
the ones where the surface misbehaves. Each of the five below is a thing a
compromised or merely buggy surface would try, and each has to end in a denial
that is *distinguishable in the audit* from a person saying no.
"""

from __future__ import annotations

import unittest

import trust
from trust.categories import DENY_SCOPE
from trust.declaration import PermissionDeclaration
from trust.gate import DEFAULT_PROMPT_TTL_SECONDS, TrustGate, UserAnswer

from tests.capsule_support import World


DECLARATION = PermissionDeclaration(
    application_id="org.example.PhotoEditor",
    required=frozenset({"files"}),
    optional=frozenset({"camera", "gpu", "notifications"}),
    reasons={"files": "to open the picture you choose"},
)


class GateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.world = World.build()
        self.addCleanup(self.world.close)
        self.picture = self.world.file("Pictures/cat.png")

    def request(self, category: str, *, resource=None, purpose: str = "use", request_id: str = "r-1"):
        return trust.PermissionRequest.build(
            request_id=request_id,
            application_id="org.example.PhotoEditor",
            category=category,
            session_id="session-1",
            resource=resource,
            purpose=purpose,
        )

    def gate_with(self, surface) -> TrustGate:  # noqa: ANN001
        return TrustGate(store=self.world.store, audit=self.world.audit, surface=surface, names={})

    # -- the happy path, and what it leaves behind -----------------------

    def test_a_once_answer_leaves_no_grant(self) -> None:
        self.world.answer(("files", "allow", "once"))
        decision = self.world.gate.check(
            self.request("files", resource=trust.path_resource(self.picture), purpose="read"),
            declaration=DECLARATION,
        )
        self.assertTrue(decision.allowed)
        self.assertIsNone(decision.grant_id)
        self.assertEqual(list(self.world.store), [])

    def test_an_always_answer_is_reused_without_asking_again(self) -> None:
        self.world.answer(("files", "allow", "always"))
        resource = trust.path_resource(self.picture)
        first = self.world.gate.check(self.request("files", resource=resource, purpose="read"), declaration=DECLARATION)
        second = self.world.gate.check(
            self.request("files", resource=resource, purpose="read", request_id="r-2"), declaration=DECLARATION
        )
        self.assertEqual(first.reason_code, "user-allowed")
        self.assertEqual(second.reason_code, "granted-previously")
        self.assertEqual(len(self.world.surface.asked), 1)

    def test_a_standing_allow_is_not_written_down_twice(self) -> None:
        self.world.answer(("files", "allow", "always"))
        resource = trust.path_resource(self.picture)
        for index in range(4):
            self.world.gate.check(
                self.request("files", resource=resource, purpose="read", request_id=f"r-{index}"),
                declaration=DECLARATION,
            )
        self.assertEqual(len(list(self.world.store)), 1)

    def test_a_read_grant_does_not_authorise_a_write(self) -> None:
        """The property §15's 'the original is preserved' rests on."""
        self.world.answer(("files", "allow", "always"))
        resource = trust.path_resource(self.picture)
        self.world.gate.check(self.request("files", resource=resource, purpose="read"), declaration=DECLARATION)
        decision = self.world.gate.check(
            self.request("files", resource=resource, purpose="write", request_id="r-2"), declaration=DECLARATION
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "unanswered")

    def test_a_write_grant_does_authorise_a_read(self) -> None:
        self.world.answer(("files", "allow", "always"))
        resource = trust.path_resource(self.picture)
        self.world.gate.check(self.request("files", resource=resource, purpose="write"), declaration=DECLARATION)
        decision = self.world.gate.check(
            self.request("files", resource=resource, purpose="read", request_id="r-2"), declaration=DECLARATION
        )
        self.assertEqual(decision.reason_code, "granted-previously")

    def test_a_folder_grant_covers_a_file_inside_it(self) -> None:
        declaration = PermissionDeclaration(
            application_id="org.example.PhotoEditor", required=frozenset({"files", "folders"})
        )
        self.world.answer(("folders", "allow", "always"))
        folder = trust.path_resource(self.world.home / "Pictures", directory=True)
        self.world.gate.check(
            trust.PermissionRequest.build(
                request_id="r-folder",
                application_id="org.example.PhotoEditor",
                category="folders",
                session_id="session-1",
                resource=folder,
                purpose="read",
            ),
            declaration=declaration,
        )
        inside = trust.path_resource(self.picture)
        decision = self.world.gate.check(
            trust.PermissionRequest.build(
                request_id="r-file",
                application_id="org.example.PhotoEditor",
                category="folders",
                session_id="session-1",
                resource=inside,
                purpose="read",
            ),
            declaration=declaration,
        )
        self.assertEqual(decision.reason_code, "granted-previously")

    def test_a_file_grant_does_not_cover_its_folder(self) -> None:
        self.world.answer(("files", "allow", "always"))
        self.world.gate.check(
            self.request("files", resource=trust.path_resource(self.picture), purpose="read"), declaration=DECLARATION
        )
        folder = trust.path_resource(self.world.home / "Pictures", directory=True)
        decision = self.world.gate.check(
            self.request("files", resource=folder, purpose="read", request_id="r-2"), declaration=DECLARATION
        )
        self.assertFalse(decision.allowed)

    # -- a misbehaving surface -------------------------------------------

    def test_a_surface_that_raises_denies_and_is_not_recorded_as_the_user(self) -> None:
        class Broken:
            def ask(self, prompt, ticket):  # noqa: ANN001
                raise RuntimeError("the dialog crashed")

        decision = self.gate_with(Broken()).check(self.request("gpu"), declaration=DECLARATION)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "surface-failed")
        self.assertEqual(decision.source, "policy")
        self.assertEqual(list(self.world.store), [], "a broken surface must not write a denial")

    def test_silence_denies(self) -> None:
        class Silent:
            def ask(self, prompt, ticket):  # noqa: ANN001
                return None

        decision = self.gate_with(Silent()).check(self.request("gpu"), declaration=DECLARATION)
        self.assertEqual(decision.reason_code, "unanswered")
        self.assertEqual(list(self.world.store), [])

    def test_a_surface_cannot_widen_a_scope_beyond_what_was_offered(self) -> None:
        class Greedy:
            def ask(self, prompt, ticket):  # noqa: ANN001
                return UserAnswer(ticket_id=ticket.ticket_id, verdict="allow", scope="always")

        decision = self.gate_with(Greedy()).check(self.request("camera"), declaration=DECLARATION)
        self.assertEqual(decision.reason_code, "scope-not-offered")
        self.assertFalse(decision.allowed)

    def test_a_surface_cannot_answer_a_question_that_was_not_asked(self) -> None:
        captured: dict[str, object] = {}

        class Capturing:
            def ask(self, prompt, ticket):  # noqa: ANN001
                captured["ticket"] = ticket
                return UserAnswer(ticket_id=ticket.ticket_id, verdict="allow", scope="session")

        gate = self.gate_with(Capturing())
        gate.check(self.request("gpu"), declaration=DECLARATION)

        class Replaying:
            def __init__(self, ticket):  # noqa: ANN001
                self.ticket = ticket

            def ask(self, prompt, ticket):  # noqa: ANN001
                return UserAnswer(ticket_id=self.ticket.ticket_id, verdict="allow", scope="session")

        decision = self.gate_with(Replaying(captured["ticket"])).check(
            self.request("camera", request_id="r-2"), declaration=DECLARATION
        )
        self.assertEqual(decision.reason_code, "answer-mismatch")

    def test_an_answer_cannot_be_used_twice(self) -> None:
        tickets: list[object] = []

        class Recording:
            def ask(self, prompt, ticket):  # noqa: ANN001
                tickets.append(ticket)
                return UserAnswer(ticket_id=ticket.ticket_id, verdict="allow", scope="session")

        gate = self.gate_with(Recording())
        gate.check(self.request("gpu"), declaration=DECLARATION)

        class Reusing:
            def ask(self, prompt, ticket):  # noqa: ANN001
                return UserAnswer(ticket_id=tickets[0].ticket_id, verdict="allow", scope="session")

        decision = gate.check(self.request("notifications", request_id="r-3"), declaration=DECLARATION)
        # A fresh ticket answered honestly still works...
        self.assertTrue(decision.allowed)
        replayed = TrustGate(
            store=self.world.store, audit=self.world.audit, surface=Reusing(), names={}
        )
        replayed._consumed.update({tickets[0].ticket_id})  # the gate that issued it has consumed it
        outcome = replayed.check(self.request("camera", request_id="r-4"), declaration=DECLARATION)
        self.assertEqual(outcome.reason_code, "replayed")

    def test_an_expired_ticket_denies(self) -> None:
        clock = {"now": 0.0}

        class Slow:
            def ask(self, prompt, ticket):  # noqa: ANN001
                clock["now"] += DEFAULT_PROMPT_TTL_SECONDS + 1
                return UserAnswer(ticket_id=ticket.ticket_id, verdict="allow", scope="session")

        gate = TrustGate(
            store=self.world.store,
            audit=self.world.audit,
            surface=Slow(),
            names={},
            clock=lambda: clock["now"],
        )
        decision = gate.check(self.request("gpu"), declaration=DECLARATION)
        self.assertEqual(decision.reason_code, "expired")

    # -- denials the user did make ---------------------------------------

    def test_a_user_denial_is_durable_and_is_not_asked_again(self) -> None:
        self.world.answer(("camera", "deny", "once"))
        first = self.world.gate.check(self.request("camera"), declaration=DECLARATION)
        self.assertEqual(first.reason_code, "user-denied")
        self.assertEqual(first.scope, DENY_SCOPE)
        second = self.world.gate.check(self.request("camera", request_id="r-2"), declaration=DECLARATION)
        self.assertEqual(second.reason_code, "user-denied")
        self.assertEqual(len(self.world.surface.asked), 1)

    def test_a_block_on_one_file_beats_an_allow_on_the_folder_around_it(self) -> None:
        """The narrower, later decision wins, which is what makes an exception
        expressible at all: 'this folder, except that file' is a thing people
        want and a first-match-by-insertion-order store would get wrong."""
        declaration = PermissionDeclaration(
            application_id="org.example.PhotoEditor", required=frozenset({"folders"})
        )
        self.world.answer(("folders", "allow", "always"))
        folder = trust.path_resource(self.world.home / "Pictures", directory=True)
        inside = trust.path_resource(self.picture)
        build = lambda rid, res: trust.PermissionRequest.build(  # noqa: E731
            request_id=rid,
            application_id="org.example.PhotoEditor",
            category="folders",
            session_id="session-1",
            resource=res,
            purpose="read",
        )
        self.world.gate.check(build("r-1", folder), declaration=declaration)
        self.assertEqual(
            self.world.gate.check(build("r-2", inside), declaration=declaration).reason_code,
            "granted-previously",
        )
        self.world.gate.block(
            application_id="org.example.PhotoEditor", category="folders", resource=inside, purpose="read"
        )
        outcome = self.world.gate.check(build("r-3", inside), declaration=declaration)
        self.assertEqual(outcome.reason_code, "user-denied")
        # And the rest of the folder is unaffected.
        other = trust.path_resource(self.world.file("Pictures/dog.png"))
        self.assertEqual(
            self.world.gate.check(build("r-4", other), declaration=declaration).reason_code,
            "granted-previously",
        )

    def test_block_can_only_ever_write_a_denial(self) -> None:
        """There is no method on the gate that writes a standing allow without a
        person having answered a question. If one is ever added, this fails."""
        grant = self.world.gate.block(application_id="org.example.PhotoEditor", category="gpu")
        self.assertEqual(grant.verdict, "deny")
        self.assertFalse(
            any(getattr(self.world.gate, name, None) for name in ("allow", "grant", "permit")),
            "the gate must expose no way to create an allow without a prompt",
        )


if __name__ == "__main__":
    unittest.main()
