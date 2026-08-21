# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import unittest

from companion.model import Locality, PrivacyClass
from companion.providers import (
    MicrophoneController,
    SpeechInputDescriptor,
    SpeechInputProvider,
    SpeechInputRequest,
    SpeechRequest,
    SpeechResult,
    Transcript,
    VoiceDescriptor,
    VoiceProvider,
    VoiceRouter,
)


class RecordingVoice(VoiceProvider):
    def __init__(
        self,
        *,
        health: str = "healthy",
        provider_id: str = "test-system-voice",
        locality: Locality = Locality.LOCAL,
        cost_class: str = "free",
    ) -> None:
        self.requests: list[SpeechRequest] = []
        self.cancelled: list[str] = []
        self.health = health
        self.provider_id = provider_id
        self.locality = locality
        self.cost_class = cost_class

    @property
    def descriptor(self):
        return VoiceDescriptor(
            provider_id=self.provider_id,
            voice_id="test-default",
            languages=("en",),
            styles=("neutral",),
            streaming=False,
            cancellation=True,
            audio_formats=("system-device",),
            locality=self.locality,
            cost_class=self.cost_class,
            privacy_classification=PrivacyClass.INTERNAL,
            health=self.health,
        )

    def speak(self, request):
        self.requests.append(request)
        return SpeechResult(request.speech_id, completed=True)

    def cancel(self, speech_id):
        self.cancelled.append(speech_id)
        return True


class RecordingSpeechInput(SpeechInputProvider):
    def __init__(self, locality: Locality = Locality.LOCAL) -> None:
        self.locality = locality
        self.started = False
        self.cancelled = False
        self.indicator_was_on = False
        self.indicators: list[tuple[bool, bool]] | None = None

    @property
    def descriptor(self):
        return SpeechInputDescriptor(
            provider_id="test-speech-input",
            languages=("en",),
            partial_transcription=True,
            cancellation=True,
            locality=self.locality,
            privacy_classification=PrivacyClass.SENSITIVE,
            health="healthy",
        )

    def start(self, request, on_transcript):
        self.started = True
        self.indicator_was_on = bool(self.indicators and self.indicators[-1][0])
        on_transcript(Transcript(request.interaction_id, "partial", False))
        on_transcript(Transcript(request.interaction_id, "final text", True))

    def cancel(self, interaction_id):
        self.cancelled = True
        return True


class VoiceContractTests(unittest.TestCase):
    def test_voice_provider_unavailable_reports_no_false_success(self) -> None:
        voice = RecordingVoice(health="unavailable")
        self.assertEqual(voice.descriptor.health, "unavailable")
        self.assertEqual(voice.requests, [])

    def test_voice_cancellation_is_provider_neutral(self) -> None:
        voice = RecordingVoice()
        self.assertTrue(voice.cancel("speech-test"))
        self.assertEqual(voice.cancelled, ["speech-test"])

    def test_speech_request_bounds_rate(self) -> None:
        with self.assertRaises(ValueError):
            SpeechRequest("speech-test", "hello", speed=3.0)

    def test_unavailable_remote_voice_falls_back_to_local_system_voice(self) -> None:
        remote = RecordingVoice(
            health="unavailable",
            provider_id="test-remote-voice",
            locality=Locality.REMOTE,
        )
        local = RecordingVoice(provider_id="test-local-system-voice")
        selected = VoiceRouter((remote, local)).select(remote_approved=True)
        self.assertIs(selected, local)

    def test_remote_or_paid_voice_cannot_activate_without_prior_approval(self) -> None:
        remote = RecordingVoice(
            provider_id="test-paid-remote-voice",
            locality=Locality.REMOTE,
            cost_class="paid",
        )
        local = RecordingVoice(provider_id="test-local-system-voice")
        router = VoiceRouter((remote, local))
        self.assertIs(router.select(), local)
        self.assertIs(router.select(remote_approved=True), local)
        self.assertIs(router.select(remote_approved=True, paid_approved=True), remote)


class MicrophoneGateTests(unittest.TestCase):
    def controller(self, available: bool = True):
        indicators: list[tuple[bool, bool]] = []
        return MicrophoneController(microphone_available=available, indicator=lambda on, remote: indicators.append((on, remote))), indicators

    def request(self, **changes):
        values = {"interaction_id": "interaction-test", "explicit_user_activation": True}
        values.update(changes)
        return SpeechInputRequest(**values)

    def test_microphone_disabled_is_refused(self) -> None:
        controller, indicators = self.controller(available=False)
        with self.assertRaises(PermissionError):
            controller.start(RecordingSpeechInput(), self.request(), lambda _item: None)
        self.assertEqual(indicators, [])

    def test_silent_activation_is_refused(self) -> None:
        controller, indicators = self.controller()
        with self.assertRaises(PermissionError):
            controller.start(
                RecordingSpeechInput(),
                self.request(explicit_user_activation=False),
                lambda _item: None,
            )
        self.assertEqual(indicators, [])

    def test_remote_transmission_denied(self) -> None:
        controller, indicators = self.controller()
        with self.assertRaises(PermissionError):
            controller.start(
                RecordingSpeechInput(Locality.REMOTE),
                self.request(remote_transmission_approved=False),
                lambda _item: None,
            )
        self.assertEqual(indicators, [])

    def test_continuous_conversation_requires_explicit_enablement(self) -> None:
        controller, _indicators = self.controller()
        with self.assertRaises(PermissionError):
            controller.start(
                RecordingSpeechInput(),
                self.request(mode="continuous", continuous_conversation_enabled=False),
                lambda _item: None,
            )

    def test_visible_indicator_precedes_provider_activation(self) -> None:
        controller, indicators = self.controller()
        provider = RecordingSpeechInput()
        provider.indicators = indicators
        transcripts: list[Transcript] = []
        controller.start(provider, self.request(), transcripts.append)
        self.assertTrue(provider.indicator_was_on)
        self.assertEqual(indicators[0], (True, False))
        self.assertTrue(transcripts[-1].final)
        self.assertTrue(controller.stop())
        self.assertEqual(indicators[-1], (False, False))

    def test_remote_indicator_shows_transmission(self) -> None:
        controller, indicators = self.controller()
        provider = RecordingSpeechInput(Locality.REMOTE)
        provider.indicators = indicators
        controller.start(
            provider,
            self.request(remote_transmission_approved=True),
            lambda _item: None,
        )
        self.assertEqual(indicators[0], (True, True))
        controller.stop()


if __name__ == "__main__":
    unittest.main()
