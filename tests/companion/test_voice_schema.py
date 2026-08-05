# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""§21 "Schema and requests": what the voice runtime may be asked, and refuses."""

from __future__ import annotations

import unittest

from companion.presentation import PresentationState
from companion.voice.request import (
    AUDIO_FORMATS,
    InterruptionPolicy,
    MAX_SPEECH_BYTES,
    MAX_SPEECH_CHARACTERS,
    Priority,
    SAMPLE_RATES,
    VOICE_REQUEST_SCHEMA_VERSION,
    VoiceRequest,
    VoiceRequestError,
    coalescing_key,
    may_speak_locally,
    may_speak_remotely,
    priority_for_phase,
    sanitized_speech_text,
    speech_digest,
)

from .voice_support import make_request, presentation


class ValidRequestTests(unittest.TestCase):
    def test_a_valid_request_carries_every_field_the_specification_names(self) -> None:
        request = make_request()
        document = request.to_json()
        for field in (
            "requestId", "sessionId", "taskId", "presentationRevision", "textDigest",
            "speechText", "language", "locale", "voiceId", "speakingRate", "pitch",
            "volume", "audioFormat", "sampleRate", "preferStreaming", "captionReference",
            "privacyClassification", "localityRequirement", "costCeilingUnits",
            "createdAtWall", "expiresAtMonotonic", "cancellationToken", "priority",
            "interruptionPolicy",
        ):
            self.assertIn(field, document, f"§3 requires {field}")

    def test_the_digest_is_derived_and_a_disagreeing_one_is_refused(self) -> None:
        request = make_request()
        self.assertEqual(request.text_digest, speech_digest(request.speech_text))
        document = request.to_json()
        document["textDigest"] = "0" * 32
        with self.assertRaises(VoiceRequestError):
            VoiceRequest.from_json(document)

    def test_a_request_survives_a_round_trip_through_the_wire_form(self) -> None:
        request = make_request(
            pitch=1.2, volume=0.7, prefer_streaming=True, expires_at_monotonic=2000.0,
            cancellation_token="cancel-1", priority=Priority.APPROVAL_REQUIRED,
            interruption_policy=InterruptionPolicy.INTERRUPT,
        )
        rebuilt = VoiceRequest.from_json(request.to_json())
        self.assertEqual(rebuilt, request)
        self.assertEqual(rebuilt.priority, Priority.APPROVAL_REQUIRED)
        self.assertEqual(rebuilt.interruption_policy, InterruptionPolicy.INTERRUPT)

    def test_the_wire_form_can_omit_the_text_entirely(self) -> None:
        """§15: anything that persists a request gets everything but the words."""
        document = make_request().to_json(include_text=False)
        self.assertNotIn("speechText", document)
        self.assertIn("textDigest", document)
        self.assertIn("textCharacters", document)

    def test_a_redacted_view_never_carries_the_utterance(self) -> None:
        request = make_request(text="the passphrase is hunter2 apparently")
        redacted = request.redacted()
        self.assertNotIn("hunter2", repr(redacted))
        self.assertEqual(redacted["textDigest"], request.text_digest)


class RefusalTests(unittest.TestCase):
    def test_oversized_text_is_refused_rather_than_shortened(self) -> None:
        with self.assertRaises(VoiceRequestError) as caught:
            make_request(text="a" * (MAX_SPEECH_CHARACTERS + 1))
        self.assertIn("refused rather than shortened", str(caught.exception))

    def test_the_byte_bound_is_reachable_and_bites_before_the_character_bound(self) -> None:
        """Two bounds, and the second one has to be able to fire.

        This is the test that caught the byte bound being set to four times the
        character bound — where UTF-8's own four-bytes-per-character maximum
        made it unreachable, so the check existed and could never run. Asserting
        the arithmetic rather than only the refusal is deliberate: a future
        change to either constant that made the byte check dead again would pass
        a test that only checked that oversized text was refused.
        """
        self.assertLess(
            MAX_SPEECH_BYTES, 4 * MAX_SPEECH_CHARACTERS,
            "a byte bound at or above four times the character bound can never be reached",
        )
        text = "\U0001f600" * MAX_SPEECH_CHARACTERS  # four bytes each
        self.assertLessEqual(len(text), MAX_SPEECH_CHARACTERS, "within the character bound")
        self.assertGreater(len(text.encode("utf-8")), MAX_SPEECH_BYTES, "past the byte bound")
        with self.assertRaises(VoiceRequestError) as caught:
            make_request(text=text)
        self.assertIn("bytes", str(caught.exception))

    def test_three_byte_scripts_keep_the_whole_character_allowance(self) -> None:
        """The bound must not silently shorten Han, Hangul or Devanagari prose.

        A byte bound tight enough to fire on emoji and loose enough not to fire
        on ordinary non-Latin writing is the only useful place for it.
        """
        text = "漢" * MAX_SPEECH_CHARACTERS  # three bytes each
        self.assertEqual(len(text.encode("utf-8")), 3 * MAX_SPEECH_CHARACTERS)
        request = make_request(text=text)
        self.assertEqual(len(request.speech_text), MAX_SPEECH_CHARACTERS)

    def test_an_empty_utterance_is_not_a_request(self) -> None:
        for text in ("", "   ", "\t\n "):
            with self.assertRaises(VoiceRequestError):
                make_request(text=text)

    def test_control_characters_are_refused(self) -> None:
        with self.assertRaises(VoiceRequestError):
            make_request(text="the answer is\x00 six")

    def test_an_invalid_language_or_locale_is_refused(self) -> None:
        for kwargs in (
            {"language": "english"},
            {"language": "e"},
            {"locale": "not a locale"},
            {"language": "en", "locale": "fr-FR"},
        ):
            with self.subTest(**kwargs):
                with self.assertRaises(VoiceRequestError):
                    make_request(**kwargs)

    def test_an_invalid_voice_identifier_is_refused(self) -> None:
        for voice_id in ("../../etc/passwd", "a voice", "-leading-hyphen", "x" * 80):
            with self.subTest(voice_id=voice_id):
                with self.assertRaises(VoiceRequestError):
                    make_request(voice_id=voice_id)

    def test_an_unsupported_format_or_rate_is_refused(self) -> None:
        with self.assertRaises(VoiceRequestError):
            make_request(audio_format="mp3")
        with self.assertRaises(VoiceRequestError):
            make_request(sample_rate=11_025)
        # And every declared one is accepted, so the list is not decorative.
        for item in AUDIO_FORMATS:
            make_request(audio_format=item)
        for rate in SAMPLE_RATES:
            make_request(sample_rate=rate)

    def test_out_of_range_prosody_is_refused(self) -> None:
        for kwargs in (
            {"speaking_rate": 0.0}, {"speaking_rate": 9.0},
            {"pitch": 0.1}, {"pitch": 5.0},
            {"volume": -0.1}, {"volume": 1.5},
        ):
            with self.subTest(**kwargs):
                with self.assertRaises(VoiceRequestError):
                    make_request(**kwargs)

    def test_an_unknown_classification_or_locality_is_refused(self) -> None:
        with self.assertRaises(VoiceRequestError):
            make_request(privacy_classification="top-secret")
        with self.assertRaises(VoiceRequestError):
            make_request(locality_requirement="anywhere")

    def test_a_malformed_document_is_refused_rather_than_partly_read(self) -> None:
        with self.assertRaises(VoiceRequestError):
            VoiceRequest.from_json("not an object")  # type: ignore[arg-type]
        document = make_request().to_json()
        document["apiKey"] = "sk-live-0000"
        with self.assertRaises(VoiceRequestError) as caught:
            VoiceRequest.from_json(document)
        self.assertIn("apiKey", str(caught.exception))

    def test_a_schema_version_this_runtime_does_not_serve_is_refused(self) -> None:
        with self.assertRaises(VoiceRequestError) as caught:
            make_request(schema_version=VOICE_REQUEST_SCHEMA_VERSION + 1)
        self.assertIn("no downgrade path", str(caught.exception))

    def test_a_caption_reference_is_required(self) -> None:
        with self.assertRaises(VoiceRequestError):
            make_request(caption_reference="")


class ExpiryTests(unittest.TestCase):
    def test_expiry_is_measured_on_the_monotonic_clock(self) -> None:
        request = make_request(expires_at_monotonic=1500.0)
        self.assertFalse(request.expired(1499.0))
        self.assertTrue(request.expired(1500.0))
        self.assertTrue(request.expired(9999.0))

    def test_a_request_with_no_expiry_never_expires(self) -> None:
        self.assertFalse(make_request().expired(10 ** 9))


class DuplicateTests(unittest.TestCase):
    def test_the_same_id_with_the_same_words_is_not_a_conflict(self) -> None:
        first = make_request(request_id="speech-1", text="the same words")
        second = make_request(request_id="speech-1", text="the same words")
        self.assertFalse(first.conflicts_with(second))

    def test_the_same_id_with_different_words_is_a_conflict(self) -> None:
        first = make_request(request_id="speech-1", text="the first thing")
        second = make_request(request_id="speech-1", text="something else entirely")
        self.assertTrue(first.conflicts_with(second))
        self.assertTrue(second.conflicts_with(first))

    def test_coalescing_keys_separate_ranks(self) -> None:
        """The same words at different ranks are not the same utterance.

        A progress line later reissued as an error must not be swallowed by the
        harmless earlier one — which is what would happen if the key were only
        task and content.
        """
        progress = make_request(request_id="a", text="something went wrong", priority=Priority.PROGRESS_UPDATE)
        error = make_request(request_id="b", text="something went wrong", priority=Priority.TASK_ERROR)
        self.assertNotEqual(coalescing_key(progress), coalescing_key(error))


class PriorityTests(unittest.TestCase):
    def test_the_ladder_is_in_the_order_the_specification_gives(self) -> None:
        self.assertEqual(
            [item.name for item in sorted(Priority, key=lambda entry: entry.value)],
            [
                "CRITICAL_WARNING", "APPROVAL_REQUIRED", "TASK_ERROR",
                "DIRECT_USER_RESPONSE", "TASK_RESULT", "PROGRESS_UPDATE", "DECORATIVE",
            ],
        )

    def test_interruption_needs_both_the_policy_and_the_rank(self) -> None:
        speaking = make_request(request_id="a", priority=Priority.TASK_RESULT)
        # Asked to interrupt, and outranks: takes the floor.
        warning = make_request(
            request_id="b", priority=Priority.CRITICAL_WARNING,
            interruption_policy=InterruptionPolicy.INTERRUPT,
        )
        self.assertTrue(warning.may_interrupt(speaking))
        # Asked to interrupt and does *not* outrank: queued.
        decoration = make_request(
            request_id="c", priority=Priority.DECORATIVE,
            interruption_policy=InterruptionPolicy.INTERRUPT,
        )
        self.assertFalse(decoration.may_interrupt(speaking))
        # Outranks and did not ask: queued.
        polite = make_request(request_id="d", priority=Priority.CRITICAL_WARNING)
        self.assertFalse(polite.may_interrupt(speaking))

    def test_phases_map_to_ranks_by_table_rather_than_by_guess(self) -> None:
        self.assertEqual(priority_for_phase("error"), Priority.TASK_ERROR)
        self.assertEqual(priority_for_phase("success"), Priority.TASK_RESULT)
        self.assertEqual(priority_for_phase("working"), Priority.PROGRESS_UPDATE)
        self.assertEqual(priority_for_phase("idle"), Priority.DECORATIVE)
        self.assertEqual(
            priority_for_phase("waiting_for_approval"), Priority.APPROVAL_REQUIRED
        )
        # An approval outranks whatever the phase says.
        self.assertEqual(
            priority_for_phase("working", approval_pending=True), Priority.APPROVAL_REQUIRED
        )
        # An unknown phase is narration rather than an error.
        self.assertEqual(priority_for_phase("something-new"), Priority.PROGRESS_UPDATE)

    def test_only_results_and_above_are_essential(self) -> None:
        self.assertTrue(Priority.TASK_RESULT.essential)
        self.assertTrue(Priority.CRITICAL_WARNING.essential)
        self.assertFalse(Priority.PROGRESS_UPDATE.essential)
        self.assertFalse(Priority.DECORATIVE.essential)


class SanitisationTests(unittest.TestCase):
    def test_markup_is_removed_rather_than_read_aloud(self) -> None:
        spoken = sanitized_speech_text("<b>forty-two</b> words &amp; counting")
        self.assertNotIn("<", spoken)
        self.assertIn("forty-two", spoken)

    def test_anything_shaped_like_a_credential_is_scrubbed(self) -> None:
        """Delegated to :func:`companion.privacy.scrub_text`, and asserted here.

        The shapes are that module's list, not a second one: a caption should
        never contain a credential, and if one ever does the voice runtime must
        not be the component that reads it out to a room. Tested through the
        voice entry point so a future refactor that stopped calling it fails.
        """
        for secret in (
            "sk-abcdefghijklmnopqrstuvwxyz012345",
            "ghp_abcdefghijklmnopqrstuvwxyz012345",
            "Bearer abcdefghijklmnop",
            "AKIAIOSFODNN7EXAMPLE",
        ):
            with self.subTest(secret=secret):
                spoken = sanitized_speech_text(f"the key is {secret} apparently")
                self.assertNotIn(secret, spoken)
                self.assertIn("apparently", spoken)

    def test_a_long_caption_is_bounded_to_the_summary_limit(self) -> None:
        spoken = sanitized_speech_text("word " * 500)
        self.assertLessEqual(len(spoken), 240)


class PrivacyTests(unittest.TestCase):
    def test_every_classification_may_be_spoken_locally(self) -> None:
        for classification in ("public", "internal", "personal", "sensitive", "secret"):
            self.assertTrue(may_speak_locally(classification))

    def test_no_classification_may_be_spoken_remotely(self) -> None:
        """§15: secret text may not go to a remote provider, and none exists."""
        for classification in ("public", "internal", "personal", "sensitive", "secret"):
            self.assertFalse(may_speak_remotely(classification))

    def test_a_secret_request_is_constructible_and_stays_device_only(self) -> None:
        request = make_request(privacy_classification="secret")
        self.assertEqual(request.locality_requirement, "device-only")
        self.assertEqual(request.cost_ceiling_units, 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
