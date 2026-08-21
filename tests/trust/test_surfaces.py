# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The permission question as it reaches a person who is not looking at a dialog.

The text surface is the reference implementation, so it is the one with tests.
Everything a graphical dialog must do — deny by default, the same facts in the
same order, no way to answer by pressing Return — is checkable here over a pipe,
and the graphical surface is asserted to derive its content from the same
function rather than composing its own.
"""

from __future__ import annotations

import io
import unittest

import trust
from companion.trust_surface import (
    AutomationSurface,
    GtkConsentSurface,
    TextConsentSurface,
    prompt_lines,
    select_consent_surface,
)
from trust.declaration import PermissionDeclaration
from trust.gate import DenyingSurface, TrustGate

from tests.capsule_support import World


DECLARATION = PermissionDeclaration(
    application_id="org.example.PhotoEditor",
    required=frozenset({"files"}),
    optional=frozenset({"camera", "gpu"}),
    reasons={"files": "to open the picture you choose"},
)


class TextSurfaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.world = World.build()
        self.addCleanup(self.world.close)
        self.picture = self.world.file("Pictures/cat.png")

    def ask(self, typed: str, *, category: str = "camera"):
        stdin = io.StringIO(typed)
        stdout = io.StringIO()
        gate = TrustGate(
            store=self.world.store,
            audit=self.world.audit,
            surface=TextConsentSurface(input_stream=stdin, output_stream=stdout),
            names={"org.example.PhotoEditor": "Photo Editor"},
        )
        resource = trust.path_resource(self.picture) if category in ("files", "folders") else None
        decision = gate.check(
            trust.PermissionRequest.build(
                request_id="r-1",
                application_id="org.example.PhotoEditor",
                category=category,
                session_id="session-1",
                resource=resource,
                purpose="read" if resource is not None else "use",
            ),
            declaration=DECLARATION,
        )
        return decision, stdout.getvalue()

    def test_choosing_the_first_option_allows_at_the_weakest_scope(self) -> None:
        decision, _ = self.ask("1\n")
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.scope, "once")

    def test_choosing_the_last_option_denies(self) -> None:
        decision, _ = self.ask("3\n")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "user-denied")

    def test_pressing_return_denies(self) -> None:
        """A person who answers without reading has denied something. That is
        recoverable; the opposite is not."""
        decision, _ = self.ask("\n")
        self.assertFalse(decision.allowed)

    def test_end_of_input_denies(self) -> None:
        decision, _ = self.ask("")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "unanswered")

    def test_nonsense_denies_without_re_prompting(self) -> None:
        decision, output = self.ask("yes please\n")
        self.assertFalse(decision.allowed)
        self.assertEqual(output.count("Choose a number"), 1)

    def test_an_out_of_range_number_denies(self) -> None:
        decision, _ = self.ask("99\n")
        self.assertFalse(decision.allowed)

    def test_a_non_interactive_surface_denies_without_reading(self) -> None:
        stdin = io.StringIO("1\n")
        stdout = io.StringIO()
        surface = TextConsentSurface(input_stream=stdin, output_stream=stdout, interactive=False)
        gate = TrustGate(store=self.world.store, audit=self.world.audit, surface=surface, names={})
        decision = gate.check(
            trust.PermissionRequest.build(
                request_id="r-1",
                application_id="org.example.PhotoEditor",
                category="camera",
                session_id="session-1",
            ),
            declaration=DECLARATION,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(stdin.tell(), 0, "a non-interactive surface must not consume input")

    def test_the_question_carries_the_facts_and_the_attribution(self) -> None:
        _decision, output = self.ask("1\n", category="files")
        self.assertIn("Photo Editor", output)
        self.assertIn("Bunny's catalogue says", output)
        self.assertIn("Don't allow", output)

    def test_a_camera_prompt_offers_no_always_option(self) -> None:
        _decision, output = self.ask("3\n")
        self.assertNotIn("Always allow", output)
        self.assertIn("Allow while using", output)


class PromptLineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.world = World.build()
        self.addCleanup(self.world.close)

    def prompt(self, category: str = "camera"):
        from trust.explain import build_prompt
        from trust.policy import resolve

        resource = trust.path_resource(self.world.file("Pictures/cat.png")) if category in ("files", "folders") else None
        request = trust.PermissionRequest.build(
            request_id="r-1",
            application_id="org.example.PhotoEditor",
            category=category,
            session_id="session-1",
            resource=resource,
            purpose="read" if resource is not None else "use",
        )
        resolution = resolve(request, store=self.world.store, declaration=DECLARATION)
        return build_prompt(request, resolution, DECLARATION, application_name="Photo Editor")

    def test_deny_is_last_in_reading_order_and_marked_as_the_default(self) -> None:
        lines = prompt_lines(self.prompt())
        self.assertIn("(default)", lines[-1])
        self.assertIn("Don't allow", lines[-1])

    def test_an_unenforceable_category_never_reaches_a_prompt(self) -> None:
        """Asking would record a consent the build cannot keep. The refusal
        happens at policy, mirroring ``not-declared``: no surface ever renders
        the question."""
        declaration = PermissionDeclaration(
            application_id="org.example.PhotoEditor", optional=frozenset({"clipboard"})
        )
        from trust.policy import resolve

        request = trust.PermissionRequest.build(
            request_id="r-1",
            application_id="org.example.PhotoEditor",
            category="clipboard",
            session_id="session-1",
        )
        resolution = resolve(request, store=self.world.store, declaration=declaration)
        self.assertEqual(resolution.verdict, "deny")
        self.assertEqual(resolution.reason_code, "not-enforceable")

    def test_a_declared_only_network_class_says_what_it_really_opens(self) -> None:
        """A prompt headlined 'connect to api.example.com' must not let the
        person believe the grant stops anywhere short of the internet."""
        declaration = PermissionDeclaration(
            application_id="org.example.PhotoEditor", optional=frozenset({"network"})
        )
        from trust.explain import build_prompt
        from trust.policy import resolve

        request = trust.PermissionRequest.build(
            request_id="r-1",
            application_id="org.example.PhotoEditor",
            category="network",
            session_id="session-1",
            resource=trust.network_resource("allowlisted", allowlist=("api.example.com",)),
            purpose="use",
        )
        prompt = build_prompt(
            request,
            resolve(request, store=self.world.store, declaration=declaration),
            declaration,
            application_name="Photo Editor",
        )
        self.assertIsNotNone(prompt.enforcement_note)
        self.assertIn("anything on the internet", prompt.enforcement_note)
        self.assertIn("anything on the internet", prompt.spoken)

    def test_a_plain_internet_request_carries_no_enforcement_note(self) -> None:
        """'internet' is enforced by the absence of a boundary; there is nothing
        to warn about because nothing was promised."""
        declaration = PermissionDeclaration(
            application_id="org.example.PhotoEditor", optional=frozenset({"network"})
        )
        from trust.explain import build_prompt
        from trust.policy import resolve

        request = trust.PermissionRequest.build(
            request_id="r-1",
            application_id="org.example.PhotoEditor",
            category="network",
            session_id="session-1",
            resource=trust.network_resource("internet"),
            purpose="use",
        )
        prompt = build_prompt(
            request,
            resolve(request, store=self.world.store, declaration=declaration),
            declaration,
            application_name="Photo Editor",
        )
        self.assertIsNone(prompt.enforcement_note)

    def test_the_spoken_form_contains_every_fact_the_drawn_form_does(self) -> None:
        prompt = self.prompt("files")
        spoken = prompt.spoken
        self.assertIn(prompt.headline, spoken)
        self.assertIn(prompt.capability_note, spoken)
        for _scope, label in prompt.options:
            self.assertIn(label, spoken)


class SurfaceSelectionTests(unittest.TestCase):
    def test_a_text_only_preference_wins_over_a_graphical_session(self) -> None:
        surface = select_consent_surface(
            environment={"WAYLAND_DISPLAY": "wayland-0"}, text_only=True, isatty=lambda: True
        )
        self.assertIsInstance(surface, TextConsentSurface)

    def test_no_display_and_no_terminal_means_nowhere_to_ask(self) -> None:
        surface = select_consent_surface(environment={}, isatty=lambda: False)
        self.assertIsInstance(surface, DenyingSurface)

    def test_a_graphical_session_gets_the_dialog(self) -> None:
        surface = select_consent_surface(environment={"WAYLAND_DISPLAY": "wayland-0"}, isatty=lambda: False)
        self.assertIsInstance(surface, GtkConsentSurface)

    def test_the_automation_surface_is_never_selected(self) -> None:
        """It exists for the slice and the tests, and reaching it has to be an
        explicit statement somebody can grep for."""
        for environment in ({}, {"DISPLAY": ":0"}, {"WAYLAND_DISPLAY": "wayland-0"}):
            for text_only in (True, False):
                for tty in (True, False):
                    surface = select_consent_surface(
                        environment=environment, text_only=text_only, isatty=lambda: tty
                    )
                    self.assertNotIsInstance(surface, AutomationSurface)

    def test_the_graphical_surface_builds_its_text_from_the_shared_function(self) -> None:
        source = __import__("inspect").getsource(GtkConsentSurface.ask)
        self.assertIn("prompt_lines", source)


if __name__ == "__main__":
    unittest.main()
