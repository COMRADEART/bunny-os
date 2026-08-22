# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression tests for the Voice & AI settings added in STEP 7.

Every new setting is exercised for: default value, valid write, rejection of
bad values, and the managed-overlay coupling discipline (local voice/AI
controls are *not* dragged by localOnly/offline — they are local capabilities,
and the remote dimension is already governed by ``cloudFailoverPolicy``).
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from bunny_shell.managed import ManagedOverlay, ManagedSetting
from bunny_shell.settings import DEFINITIONS, SECTIONS, SettingsStore


class VoiceAiDefinitionTests(unittest.TestCase):
    def test_voice_section_is_listed_in_sections(self) -> None:
        self.assertIn("Voice & AI", SECTIONS)

    def test_every_new_key_has_scope_owner_and_default(self) -> None:
        for key in ("voiceEnabled", "microphoneEnabled", "speechRecognizerModel",
                     "ttsEngine", "localAiEnabled", "agentModel"):
            with self.subTest(key=key):
                self.assertIn(key, DEFINITIONS)
                definition = DEFINITIONS[key]
                self.assertIn("scope", definition)
                self.assertIn("owner", definition)
                self.assertIn("default", definition)
                self.assertIn("validate", definition)


class VoiceAiDefaultsTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "settings.json"
        self.settings = SettingsStore(self.path)

    def test_defaults_for_voice_ai_keys(self) -> None:
        values = self.settings.get_all()
        self.assertTrue(values["voiceEnabled"])
        self.assertTrue(values["microphoneEnabled"])
        self.assertEqual(values["speechRecognizerModel"], "automatic")
        self.assertEqual(values["ttsEngine"], "automatic")
        self.assertTrue(values["localAiEnabled"])
        self.assertEqual(values["agentModel"], "automatic")


class VoiceAiValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "settings.json"
        self.settings = SettingsStore(self.path)

    def test_voice_enabled_accepts_boolean(self) -> None:
        self.assertFalse(self.settings.set("voiceEnabled", False)["voiceEnabled"])

    def test_voice_enabled_rejects_non_boolean(self) -> None:
        with self.assertRaises(ValueError):
            self.settings.set("voiceEnabled", "yes")

    def test_microphone_enabled_accepts_boolean(self) -> None:
        self.assertFalse(self.settings.set("microphoneEnabled", False)["microphoneEnabled"])

    def test_microphone_enabled_rejects_non_boolean(self) -> None:
        with self.assertRaises(ValueError):
            self.settings.set("microphoneEnabled", 1)

    def test_speech_recognizer_model_accepts_alias(self) -> None:
        self.assertEqual(
            self.settings.set("speechRecognizerModel", "vosk-model-small-en-us-0.15")["speechRecognizerModel"],
            "vosk-model-small-en-us-0.15",
        )

    def test_speech_recognizer_model_rejects_secret_shape(self) -> None:
        with self.assertRaises(ValueError):
            self.settings.set("speechRecognizerModel", "sk-live secret value")

    def test_speech_recognizer_model_rejects_empty(self) -> None:
        with self.assertRaises(ValueError):
            self.settings.set("speechRecognizerModel", "")

    def test_tts_engine_accepts_choice(self) -> None:
        for value in ("automatic", "espeak-ng", "speech-dpatcher"):
            with self.subTest(value=value):
                self.assertEqual(self.settings.set("ttsEngine", value)["ttsEngine"], value)

    def test_tts_engine_rejects_unknown_choice(self) -> None:
        with self.assertRaises(ValueError):
            self.settings.set("ttsEngine", "speech-dispatcher")

    def test_tts_engine_rejects_non_string(self) -> None:
        with self.assertRaises(ValueError):
            self.settings.set("ttsEngine", True)

    def test_local_ai_enabled_accepts_boolean(self) -> None:
        self.assertFalse(self.settings.set("localAiEnabled", False)["localAiEnabled"])

    def test_local_ai_enabled_rejects_non_boolean(self) -> None:
        with self.assertRaises(ValueError):
            self.settings.set("localAiEnabled", "off")

    def test_agent_model_accepts_alias(self) -> None:
        self.assertEqual(
            self.settings.set("agentModel", "mistral-7b-instruct.Q4_K_M.gguf")["agentModel"],
            "mistral-7b-instruct.Q4_K_M.gguf",
        )

    def test_agent_model_rejects_secret_shape(self) -> None:
        with self.assertRaises(ValueError):
            self.settings.set("agentModel", "key=abc123 path=/etc/shadow")

    def test_agent_model_rejects_path_separators(self) -> None:
        with self.assertRaises(ValueError):
            self.settings.set("agentModel", "../escape")


class VoiceAiManagedCouplingTests(unittest.TestCase):
    """The new voice/AI settings are local; localOnly/offline must not drag them.

    ``localOnlyMode`` and ``offlineMode`` govern the *remote* dimension. They
    already drag ``cloudFailoverPolicy`` to ``never``. The voice/AI controls
    are local capabilities (a local recogniser, a local TTS engine, a local
    agent model) and must remain available under a local-only policy —
    local-only means "use local", not "use nothing".
    """

    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.directory = Path(self._temp.name)

    def test_local_only_does_not_disable_voice(self) -> None:
        settings = SettingsStore(self.directory / "settings.json")
        settings.set("localOnlyMode", True)
        values = settings.get_all()
        self.assertTrue(values["localOnlyMode"])
        self.assertTrue(values["voiceEnabled"])
        self.assertTrue(values["microphoneEnabled"])
        self.assertTrue(values["localAiEnabled"])

    def test_offline_does_not_disable_voice(self) -> None:
        settings = SettingsStore(self.directory / "settings.json")
        settings.set("offlineMode", True)
        values = settings.get_all()
        self.assertTrue(values["offlineMode"])
        self.assertTrue(values["voiceEnabled"])
        self.assertTrue(values["localAiEnabled"])

    def test_local_only_still_drags_cloud_failover_for_voice_ai(self) -> None:
        settings = SettingsStore(self.directory / "settings.json")
        settings.set("localOnlyMode", True)
        values = settings.get_all()
        self.assertEqual(values["cloudFailoverPolicy"], "never")

    def test_offline_still_drags_cloud_failover_for_voice_ai(self) -> None:
        settings = SettingsStore(self.directory / "settings.json")
        settings.set("offlineMode", True)
        values = settings.get_all()
        self.assertEqual(values["cloudFailoverPolicy"], "never")

    def test_locked_local_only_does_not_drag_voice_ai_settings(self) -> None:
        overlay = ManagedOverlay(
            organisationId="org-example-school",
            settings={"localOnlyMode": ManagedSetting(True, "POL-0001", 1)},
        )
        settings = SettingsStore(self.directory / "settings.json", managed=overlay)
        values = settings.get_all()
        self.assertTrue(values["localOnlyMode"])
        self.assertEqual(values["cloudFailoverPolicy"], "never")
        self.assertEqual(values["defaultProviderAlias"], "local")
        # Voice & AI controls stay at their user values, not dragged.
        self.assertTrue(values["voiceEnabled"])
        self.assertTrue(values["microphoneEnabled"])
        self.assertTrue(values["localAiEnabled"])
        self.assertEqual(values["ttsEngine"], "automatic")

    def test_locked_offline_does_not_drag_voice_ai_settings(self) -> None:
        overlay = ManagedOverlay(
            organisationId="org-example-school",
            settings={"offlineMode": ManagedSetting(True, "POL-0001", 1)},
        )
        settings = SettingsStore(self.directory / "settings.json", managed=overlay)
        values = settings.get_all()
        self.assertTrue(values["offlineMode"])
        self.assertEqual(values["cloudFailoverPolicy"], "never")
        self.assertTrue(values["voiceEnabled"])
        self.assertTrue(values["localAiEnabled"])

    def test_user_can_disable_voice_independently_of_local_only(self) -> None:
        settings = SettingsStore(self.directory / "settings.json")
        settings.set("voiceEnabled", False)
        settings.set("localOnlyMode", True)
        values = settings.get_all()
        self.assertFalse(values["voiceEnabled"])
        self.assertTrue(values["localOnlyMode"])
        self.assertEqual(values["cloudFailoverPolicy"], "never")


class VoiceAiUnknownKeyTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.settings = SettingsStore(Path(temporary.name) / "settings.json")

    def test_setting_an_unknown_voice_key_raises(self) -> None:
        with self.assertRaises(KeyError):
            self.settings.set("voiceCloudEndpoint", "https://example.com")


if __name__ == "__main__":
    unittest.main()