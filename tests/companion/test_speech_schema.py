# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The speech-input request and transcript schemas: refusal at construction.

Every test here is a §3, §12 or §13 sentence asserted against the *type*, which
is where this codebase puts its rules: an invalid request is not representable,
so no discipline downstream has to remember one.
"""

from __future__ import annotations

import unittest

from companion.speech.request import (
    ACTIVATION_SOURCES,
    MAX_CAPTURE_SECONDS,
    MAX_TRANSCRIPT_CHARACTERS,
    SpeechInputRequest,
    SpeechInputRequestError,
    transcript_digest,
)
from companion.speech.transcript import (
    FinalTranscript,
    PartialTranscript,
    TranscriptError,
    bounded_transcript_text,
    pango_escaped,
)

from .speech_support import make_request


class ActivationSources(unittest.TestCase):
    """§3: a closed set of explicit interactions, and nothing passive."""

    def test_every_declared_source_is_an_explicit_interaction(self) -> None:
        self.assertEqual(ACTIVATION_SOURCES, (
            "push-to-talk-button",
            "keyboard-shortcut",
            "explicit-protocol-request",
            "accessibility-control",
        ))

    def test_a_passive_or_invented_source_is_refused(self) -> None:
        for hostile in ("wake-word", "always-listening", "service-startup",
                        "timer", "scheduled", "", "push-to-talk-button "):
            with self.subTest(source=hostile):
                with self.assertRaises(SpeechInputRequestError):
                    make_request(activation_source=hostile)

    def test_there_is_no_default_activation_source(self) -> None:
        """An activation nobody performed cannot exist by omission."""
        with self.assertRaises(TypeError):
            SpeechInputRequest(request_id="r-1", session_id="s-1")  # type: ignore[call-arg]


class RequestBounds(unittest.TestCase):
    """Ceilings are refused, never clamped."""

    def test_a_capture_longer_than_the_ceiling_is_refused(self) -> None:
        with self.assertRaises(SpeechInputRequestError) as caught:
            make_request(maximum_capture_seconds=MAX_CAPTURE_SECONDS + 1)
        self.assertIn("refused rather than clamped", str(caught.exception))

    def test_silence_timeouts_are_bounded_both_ways(self) -> None:
        for field, value in (
            ("initial_silence_seconds", 0.05),
            ("initial_silence_seconds", 31.0),
            ("endpoint_silence_seconds", 0.0),
            ("endpoint_silence_seconds", 100.0),
        ):
            with self.subTest(field=field, value=value):
                with self.assertRaises(SpeechInputRequestError):
                    make_request(**{field: value})

    def test_formats_rates_and_channels_are_a_closed_set(self) -> None:
        with self.assertRaises(SpeechInputRequestError):
            make_request(audio_format="ogg-vorbis")
        with self.assertRaises(SpeechInputRequestError):
            make_request(sample_rate=11_025)
        with self.assertRaises(SpeechInputRequestError):
            make_request(channels=6)

    def test_the_byte_budget_scales_with_the_request_not_past_the_ceiling(self) -> None:
        small = make_request(maximum_capture_seconds=2.0)
        self.assertLess(small.maximum_capture_bytes, 200_000)
        large = make_request(
            maximum_capture_seconds=300.0, sample_rate=48_000, channels=2,
        )
        self.assertLessEqual(large.maximum_capture_bytes, 64 * 1024 * 1024)

    def test_expiry_is_monotonic(self) -> None:
        request = make_request(expires_at_monotonic=100.0)
        self.assertFalse(request.expired(99.9))
        self.assertTrue(request.expired(100.0))


class LocalityAndPrivacy(unittest.TestCase):
    """§1 and §10: audio does not leave, and the type refuses the name of the path."""

    def test_only_device_only_locality_is_representable(self) -> None:
        for wider in ("trusted-remote", "any", "remote", ""):
            with self.subTest(locality=wider):
                with self.assertRaises(SpeechInputRequestError) as caught:
                    make_request(locality_requirement=wider)
                self.assertIn("local incapability", str(caught.exception))

    def test_an_unknown_privacy_classification_is_refused(self) -> None:
        with self.assertRaises(SpeechInputRequestError):
            make_request(privacy_classification="mystery")

    def test_the_default_classification_is_personal(self) -> None:
        self.assertEqual(make_request().privacy_classification, "personal")


class DeviceAndProviderIdentifiers(unittest.TestCase):
    """§22's device-name injection, refused where the name enters."""

    def test_real_device_names_are_accepted(self) -> None:
        for name in ("hw:0,0", "RDPSource", "alsa_input.pci-0000_00_1f.3.analog-stereo",
                     "RDPSink.monitor"):
            with self.subTest(device=name):
                self.assertEqual(make_request(device_preference=name).device_preference, name)

    def test_injection_shaped_device_names_are_refused(self) -> None:
        for hostile in ("-not-a-device", "a device", "dev;rm -rf /", "../etc/passwd",
                        "dev\nname", "dev|cat", "$(reboot)", "dev`x`"):
            with self.subTest(device=hostile):
                with self.assertRaises(SpeechInputRequestError):
                    make_request(device_preference=hostile)

    def test_provider_identifiers_are_bounded_and_shaped(self) -> None:
        self.assertEqual(make_request(provider_preference="vosk").provider_preference, "vosk")
        for hostile in ("/usr/lib/evil.so", "provider name", "a" * 80):
            with self.subTest(provider=hostile):
                with self.assertRaises(SpeechInputRequestError):
                    make_request(provider_preference=hostile)


class WireRoundTrip(unittest.TestCase):
    def test_the_wire_form_round_trips(self) -> None:
        request = make_request(device_preference="hw:0,0", presentation_revision=7)
        rebuilt = SpeechInputRequest.from_json(request.to_json())
        self.assertEqual(rebuilt, request)

    def test_undeclared_keys_are_refused_not_ignored(self) -> None:
        document = make_request().to_json()
        document["modelPath"] = "/tmp/evil"
        with self.assertRaises(SpeechInputRequestError) as caught:
            SpeechInputRequest.from_json(document)
        self.assertIn("modelPath", str(caught.exception))

    def test_a_different_schema_version_is_refused(self) -> None:
        document = make_request().to_json()
        document["schemaVersion"] = 99
        with self.assertRaises(SpeechInputRequestError):
            SpeechInputRequest.from_json(document)


class TranscriptText(unittest.TestCase):
    """§12 and §13: bounded, provisional by type, escaped on the way to a label."""

    def test_transcript_text_is_refused_over_the_bound_never_truncated(self) -> None:
        with self.assertRaises(TranscriptError):
            bounded_transcript_text("word " * (MAX_TRANSCRIPT_CHARACTERS // 4))

    def test_control_characters_are_refused_and_whitespace_is_normalised(self) -> None:
        with self.assertRaises(TranscriptError):
            bounded_transcript_text("hello\x00world")
        with self.assertRaises(TranscriptError):
            bounded_transcript_text("hello\x1bworld")
        # Newlines are whitespace: collapsed to one space, not refused — a
        # transcript is one utterance whichever way a recogniser wrapped it.
        self.assertEqual(bounded_transcript_text("hello\nworld"), "hello world")

    def test_a_partial_is_provisional_by_type(self) -> None:
        partial = PartialTranscript(
            request_id="r-1", revision=1, text="count the",
            provider_id="scripted",
        )
        self.assertTrue(partial.provisional)
        self.assertTrue(partial.to_json()["provisional"])

    def test_partial_revisions_are_non_negative_integers(self) -> None:
        with self.assertRaises(TranscriptError):
            PartialTranscript(request_id="r-1", revision=-1, text="x", provider_id="p")

    def test_a_final_carries_provenance_and_a_derived_digest(self) -> None:
        final = FinalTranscript(
            request_id="r-1", session_id="s-1", text="count the words",
            provider_id="vosk", implementation_id="vosk/0.3+model",
            confidence=0.8, recognition_mode="streaming",
        )
        self.assertEqual(final.text_digest, transcript_digest("count the words"))
        self.assertFalse(final.user_edited)
        self.assertFalse(final.to_json()["provisional"])

    def test_editing_marks_the_transcript_as_the_users(self) -> None:
        final = FinalTranscript(
            request_id="r-1", session_id="s-1", text="count the words",
            provider_id="vosk",
        )
        edited = final.edited("count the words carefully")
        self.assertTrue(edited.user_edited)
        self.assertNotEqual(edited.text_digest, final.text_digest)
        # The original is untouched: both answers exist, as §13 requires.
        self.assertFalse(final.user_edited)

    def test_an_empty_edit_is_refused(self) -> None:
        final = FinalTranscript(
            request_id="r-1", session_id="s-1", text="count", provider_id="vosk",
        )
        with self.assertRaises(TranscriptError):
            final.edited("   ")

    def test_the_redacted_form_never_holds_the_words(self) -> None:
        final = FinalTranscript(
            request_id="r-1", session_id="s-1", text="a private sentence",
            provider_id="vosk",
        )
        record = final.redacted()
        self.assertNotIn("text", record)
        self.assertNotIn("a private sentence", str(record))
        self.assertEqual(record["textCharacters"], len("a private sentence"))


class PangoEscaping(unittest.TestCase):
    """§22's GTK markup injection: five entities, asserted character by character."""

    def test_markup_in_a_transcript_becomes_text(self) -> None:
        hostile = '<b>bold</b> & <span foreground="red">"x"</span> \'y\''
        escaped = pango_escaped(hostile)
        self.assertNotIn("<", escaped)
        self.assertNotIn(">", escaped)
        self.assertIn("&lt;b&gt;", escaped)
        self.assertIn("&amp;", escaped)
        self.assertIn("&quot;x&quot;", escaped)
        self.assertIn("&apos;y&apos;", escaped)

    def test_the_ampersand_is_escaped_first(self) -> None:
        self.assertEqual(pango_escaped("&lt;"), "&amp;lt;")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
