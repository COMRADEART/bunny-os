# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""§3, §4, §5 and §6: the schemas, the catalogue, and what a descriptor promises.

Most of this file is about *consistency between tables*, which is the failure
mode a catalogue of this shape actually has. An action can be declared and have
no schema; a schema can exist for an action nobody declared; a descriptor can
claim reversibility and name no undo; a retry policy can be missing for an action
that will one day be uncertain. None of those breaks a test that exercises the
happy path, and every one of them breaks something a user relies on.

The import-time checks in :mod:`companion.desktop.catalogue` and
:mod:`companion.desktop.parameters` already refuse most of these. The tests here
assert the same properties from outside, so that a check being deleted is a test
failure rather than a silence.
"""

from __future__ import annotations

import unittest

from companion.desktop import DESKTOP_ACTION_SCHEMA_VERSION
from companion.desktop.catalogue import (
    ACTION_IDS,
    ACTION_STANDING,
    BACKENDS,
    DEFERRED_ACTIONS,
    DESCRIPTORS,
    REVERSIBILITY_CLASSES,
    descriptor_for,
)
from companion.desktop.errors import DesktopRefused, DesktopSchemaError
from companion.desktop.idempotency import OPERATION_STATES, RETRY_POLICIES
from companion.desktop.parameters import (
    PARAMETER_SCHEMAS,
    SETTINGS_PAGES,
    normalise,
    validate_parameters,
)
from companion.desktop.result import (
    OBSERVATION_KINDS,
    RESULT_STATES,
    DesktopActionResult,
    Observation,
)

from .desktop_support import make_paths, sample_parameters


class Catalogue(unittest.TestCase):
    def test_the_catalogue_is_the_nine_actions_section_four_names(self) -> None:
        self.assertEqual(sorted(ACTION_IDS), sorted((
            "desktop.notification.show",
            "desktop.application.launch",
            "desktop.application.present",
            "desktop.settings.open",
            "desktop.audio.set-volume",
            "desktop.notifications.set-do-not-disturb",
            "desktop.clipboard.copy-text",
            "desktop.uri.open",
            "desktop.file.reveal",
        )))

    def test_the_standing_ladder_is_section_six_s_seven_words(self) -> None:
        self.assertEqual(ACTION_STANDING, (
            "declared", "available", "eligible", "approved",
            "executing", "completed", "undone",
        ))

    def test_every_action_has_a_schema_a_normaliser_and_a_retry_policy(self) -> None:
        for action_id in ACTION_IDS:
            self.assertIn(action_id, PARAMETER_SCHEMAS, action_id)
            self.assertIn(action_id, RETRY_POLICIES, action_id)
            self.assertIn(DESCRIPTORS[action_id].backend, BACKENDS, action_id)

    def test_no_action_is_both_declared_and_deferred(self) -> None:
        self.assertFalse(set(ACTION_IDS) & set(DEFERRED_ACTIONS))

    def test_every_deferred_action_names_itself_as_a_decision(self) -> None:
        """§5: a typed absence, not a placeholder and not an unknown name."""
        for action_id, reason in DEFERRED_ACTIONS.items():
            with self.assertRaises(DesktopSchemaError, msg=action_id) as caught:
                descriptor_for(action_id)
            self.assertIn("deliberately not implemented", str(caught.exception))
            self.assertEqual(str(caught.exception), reason)

    def test_an_unknown_action_is_distinguished_from_a_deferred_one(self) -> None:
        with self.assertRaises(DesktopSchemaError) as caught:
            descriptor_for("desktop.something.invented")
        self.assertIn("not a desktop action this build declares", str(caught.exception))

    def test_the_forbidden_capabilities_are_absent_from_the_catalogue(self) -> None:
        """The §5 list, checked as an absence of *actions* rather than of code."""
        for forbidden in (
            "type", "click", "drag", "resize", "move", "screen", "capture",
            "camera", "remote", "keyboard.press", "mouse",
        ):
            self.assertFalse(
                [item for item in ACTION_IDS if forbidden in item],
                f"an action id contains {forbidden!r}",
            )


class Descriptors(unittest.TestCase):
    def test_reversibility_and_undo_agree(self) -> None:
        for action_id, descriptor in DESCRIPTORS.items():
            self.assertIn(descriptor.reversibility, REVERSIBILITY_CLASSES, action_id)
            if descriptor.reversibility == "reversible":
                self.assertTrue(descriptor.undo_action_id, action_id)
                self.assertIn(descriptor.undo_action_id, DESCRIPTORS, action_id)
            if descriptor.reversibility == "irreversible":
                self.assertFalse(descriptor.undo_action_id, action_id)

    def test_section_eleven_s_examples_are_the_declared_classifications(self) -> None:
        self.assertEqual(DESCRIPTORS["desktop.audio.set-volume"].reversibility, "reversible")
        self.assertEqual(
            DESCRIPTORS["desktop.notifications.set-do-not-disturb"].reversibility, "reversible"
        )
        self.assertEqual(
            DESCRIPTORS["desktop.clipboard.copy-text"].reversibility, "compensatable"
        )
        for irreversible in (
            "desktop.notification.show", "desktop.application.launch",
            "desktop.uri.open", "desktop.settings.open",
        ):
            self.assertEqual(DESCRIPTORS[irreversible].reversibility, "irreversible", irreversible)

    def test_only_the_three_verifiable_actions_claim_verification(self) -> None:
        verifiable = {
            action_id for action_id, item in DESCRIPTORS.items() if item.supports_verification
        }
        self.assertEqual(verifiable, {
            "desktop.audio.set-volume",
            "desktop.notifications.set-do-not-disturb",
            "desktop.clipboard.copy-text",
        })

    def test_every_descriptor_says_what_the_user_will_see(self) -> None:
        for action_id, descriptor in DESCRIPTORS.items():
            self.assertTrue(descriptor.expected_visibility, action_id)
            self.assertTrue(descriptor.known_limitations, action_id)

    def test_the_privacy_ceiling_keeps_secrets_off_the_desk(self) -> None:
        for action_id, descriptor in DESCRIPTORS.items():
            self.assertNotEqual(descriptor.privacy_ceiling, "secret", action_id)
        self.assertEqual(DESCRIPTORS["desktop.clipboard.copy-text"].privacy_ceiling, "sensitive")
        self.assertEqual(DESCRIPTORS["desktop.settings.open"].privacy_ceiling, "internal")


class Schemas(unittest.TestCase):
    def test_every_schema_closes_additional_properties(self) -> None:
        for action_id, schema in PARAMETER_SCHEMAS.items():
            self.assertIs(schema["additionalProperties"], False, action_id)

    def test_an_undeclared_parameter_is_refused_rather_than_ignored(self) -> None:
        for action_id in ACTION_IDS:
            parameters = {**sample_parameters(action_id), "extra": "value"}
            with self.assertRaises(DesktopSchemaError, msg=action_id) as caught:
                validate_parameters(action_id, parameters)
            self.assertIn("refused rather than ignored", str(caught.exception))

    def test_a_missing_required_parameter_is_refused(self) -> None:
        with self.assertRaises(DesktopSchemaError):
            validate_parameters("desktop.notification.show", {"body": "no title"})

    def test_bounds_are_enforced_at_both_ends(self) -> None:
        for value in (-1, 101):
            with self.assertRaises(DesktopSchemaError, msg=str(value)):
                validate_parameters("desktop.audio.set-volume", {"percent": value})
        validate_parameters("desktop.audio.set-volume", {"percent": 0})
        validate_parameters("desktop.audio.set-volume", {"percent": 100})

    def test_the_settings_pages_are_exactly_section_four_four_s_list(self) -> None:
        self.assertEqual(sorted(SETTINGS_PAGES), sorted((
            "network", "sound", "display", "accessibility",
            "privacy", "notifications", "power", "keyboard",
        )))
        with self.assertRaises(DesktopSchemaError):
            validate_parameters("desktop.settings.open", {"page": "gnome-control-center"})

    def test_an_indefinite_critical_notification_needs_a_justification(self) -> None:
        with self.assertRaises(DesktopRefused) as caught:
            normalise("desktop.notification.show", {"title": "Urgent", "urgency": "critical"})
        self.assertIn("must state why", str(caught.exception))
        # With one, it is permitted — the requirement is that it be argued for.
        action = normalise("desktop.notification.show", {
            "title": "Urgent", "urgency": "critical",
            "persistJustification": "the battery will stop the machine in a minute",
        })
        self.assertEqual(action.parameters["urgency"], "critical")

    def test_a_notification_has_no_field_for_an_action_button(self) -> None:
        schema = PARAMETER_SCHEMAS["desktop.notification.show"]
        for hostile in ("actions", "action", "callback", "url", "link", "icon", "image"):
            self.assertNotIn(hostile, schema["properties"], hostile)

    def test_the_schema_version_is_carried_on_every_request(self) -> None:
        for action_id, descriptor in DESCRIPTORS.items():
            self.assertEqual(descriptor.schema_version, DESKTOP_ACTION_SCHEMA_VERSION, action_id)


class Presentation(unittest.TestCase):
    """§18: the exact sentence, not a category."""

    def test_the_examples_in_section_eighteen_are_produced(self) -> None:
        context, _ = make_paths("report.pdf", test=self)
        cases = {
            "desktop.uri.open": (
                sample_parameters("desktop.uri.open"), "Open https://example.com/docs",
            ),
            "desktop.clipboard.copy-text": (
                {"text": "x" * 84}, "Copy 84 characters of internal text to the clipboard",
            ),
        }
        for action_id, (parameters, expected) in cases.items():
            action = normalise(action_id, parameters, path_context=context)
            self.assertEqual(action.presentation, expected, action_id)

    def test_a_volume_change_names_the_previous_and_requested_values(self) -> None:
        action = normalise(
            "desktop.audio.set-volume",
            {"percent": 50, "outputId": "sink"},
            observed_state={"percent": 35, "outputId": "sink", "outputName": "speaker"},
        )
        self.assertEqual(action.presentation, "Set speaker volume from 35% to 50%")
        self.assertEqual(action.previous_state["percent"], 35)

    def test_a_reveal_names_the_file_as_the_user_knows_it(self) -> None:
        context, _ = make_paths("report.pdf", test=self)
        action = normalise("desktop.file.reveal", {"pathReference": "ref-0"}, path_context=context)
        self.assertTrue(action.presentation.startswith("Reveal "))
        self.assertIn("report.pdf", action.presentation)

    def test_no_presentation_is_a_vague_label(self) -> None:
        context, _ = make_paths("report.pdf", test=self)
        for action_id in ACTION_IDS:
            parameters = sample_parameters(action_id)
            try:
                action = normalise(action_id, parameters, path_context=context)
            except DesktopRefused:
                continue
            self.assertNotIn("task action", action.presentation.lower(), action_id)
            self.assertNotEqual(action.presentation.lower(), "allow", action_id)
            self.assertGreater(len(action.presentation), 10, action_id)


class Results(unittest.TestCase):
    def test_the_result_states_are_section_twelve_s_seven(self) -> None:
        self.assertEqual(sorted(RESULT_STATES), sorted((
            "confirmed", "accepted-not-confirmed", "refused",
            "failed", "cancelled", "unknown", "unsupported",
        )))

    def test_confirmed_requires_a_verifying_observation(self) -> None:
        with self.assertRaises(DesktopSchemaError) as caught:
            DesktopActionResult(
                request_id="r", action_id="desktop.audio.set-volume", idempotency_key="k",
                state="confirmed",
                observation=Observation("acknowledgement", detail="the backend said yes"),
            )
        self.assertIn("acknowledgement verifies nothing", str(caught.exception))

    def test_a_read_back_that_did_not_match_cannot_confirm(self) -> None:
        with self.assertRaises(DesktopSchemaError):
            DesktopActionResult(
                request_id="r", action_id="desktop.audio.set-volume", idempotency_key="k",
                state="confirmed",
                observation=Observation("read-back", detail="compared", matched=False),
            )

    def test_an_acknowledgement_is_a_success_without_being_a_confirmation(self) -> None:
        result = DesktopActionResult(
            request_id="r", action_id="desktop.notification.show", idempotency_key="k",
            state="accepted-not-confirmed",
            observation=Observation("acknowledgement", detail="the daemon returned an id"),
        )
        self.assertTrue(result.succeeded)
        self.assertEqual(result.confidence, "reported")

    def test_effect_prevented_belongs_only_to_a_cancellation(self) -> None:
        with self.assertRaises(DesktopSchemaError):
            DesktopActionResult(
                request_id="r", action_id="desktop.settings.open", idempotency_key="k",
                state="failed", effect_prevented=True,
            )

    def test_the_provider_view_carries_no_machine_state(self) -> None:
        result = DesktopActionResult(
            request_id="r", action_id="desktop.audio.set-volume", idempotency_key="k-secret",
            state="confirmed",
            observation=Observation("read-back", detail="compared", matched=True, observed_value=50),
            previous_state={"percent": 35, "outputId": "alsa_output.pci-0000"},
        )
        view = result.to_tool_json()
        self.assertNotIn("previousState", view)
        self.assertNotIn("idempotencyKey", view)
        self.assertNotIn("observation", view)
        self.assertEqual(set(view), {
            "actionId", "state", "confidence", "succeeded", "explanation", "undoAvailable",
        })

    def test_the_observation_kinds_are_closed(self) -> None:
        self.assertEqual(sorted(OBSERVATION_KINDS), sorted((
            "acknowledgement", "read-back", "ownership", "error", "none",
        )))
        with self.assertRaises(DesktopSchemaError):
            Observation("guess")


class Idempotency(unittest.TestCase):
    def test_the_operation_states_are_section_nine_s_seven(self) -> None:
        self.assertEqual(sorted(OPERATION_STATES), sorted((
            "not-started", "started", "completed", "failed",
            "cancelled", "unknown", "undone",
        )))

    def test_opening_a_uri_is_never_offered_as_a_repeat(self) -> None:
        policy = RETRY_POLICIES["desktop.uri.open"]
        self.assertFalse(policy.duplicate_is_safe)
        self.assertFalse(policy.reconcilable)
        self.assertFalse(policy.may_offer_repeat)

    def test_a_notification_may_be_offered_as_a_repeat_and_cannot_be_reconciled(self) -> None:
        policy = RETRY_POLICIES["desktop.notification.show"]
        self.assertTrue(policy.duplicate_is_safe)
        self.assertFalse(policy.reconcilable)

    def test_a_volume_change_is_reconcilable_and_not_safe_to_repeat(self) -> None:
        policy = RETRY_POLICIES["desktop.audio.set-volume"]
        self.assertFalse(policy.duplicate_is_safe)
        self.assertTrue(policy.reconcilable)

    def test_every_policy_says_something_a_person_could_read(self) -> None:
        for action_id, policy in RETRY_POLICIES.items():
            self.assertGreater(len(policy.explanation), 40, action_id)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
