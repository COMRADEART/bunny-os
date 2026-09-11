# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Host-honest voice pipeline inventory. Never a spoken e2e PASS."""

from __future__ import annotations

import json
import unittest

from companion.voice_pipeline import (
    IMAGE_BOOT,
    NOT_RUN,
    construct_speech_and_voice_safely,
    run_voice_pipeline_inventory,
)
from companion.voice_story import VOICE_STORY_UTTERANCE, run_voice_story

from .test_cli import parse


LIVE_STAGES = frozenset({
    "live microphone journey",
    "STT live recognition",
    "TTS live playback",
    "spoken e2e",
})


class VoicePipelineInventoryTests(unittest.TestCase):
    def test_spoken_e2e_is_never_pass(self) -> None:
        report = run_voice_pipeline_inventory()
        document = report.to_json()
        json.dumps(document)
        self.assertEqual(document["spokenE2e"], NOT_RUN)
        self.assertEqual(document["transcriptSource"], "labelled-fixture")
        self.assertEqual(document["transcript"], VOICE_STORY_UTTERANCE)
        self.assertFalse(document["modelBytesVendored"])
        self.assertFalse(document["gpuClaimed"])
        self.assertFalse(document["npuClaimed"])
        self.assertFalse(document["physicalMicrophoneValidated"])
        self.assertTrue(document["typedInputPreserved"])
        self.assertEqual(document["aiStatus"], "PARTIAL")
        self.assertNotEqual(document["spokenE2e"], "PASS")
        by_name = {item["name"]: item for item in document["stages"]}
        self.assertEqual(by_name["spoken e2e"]["status"], NOT_RUN)
        self.assertEqual(by_name["spoken e2e"]["evidence"], IMAGE_BOOT)
        self.assertNotEqual(by_name["spoken e2e"]["status"], "PASS")

    def test_live_stt_mic_and_tts_stay_not_run(self) -> None:
        report = run_voice_pipeline_inventory()
        by_name = {item["name"]: item for item in report.stages}
        for name in LIVE_STAGES:
            self.assertIn(name, by_name)
            self.assertEqual(by_name[name]["status"], NOT_RUN, name)
            self.assertNotEqual(by_name[name]["status"], "PASS", name)
        stt = by_name["STT live recognition"]
        self.assertTrue(stt.get("fixture"))
        self.assertIn("labelled fixture", stt["detail"])

    def test_missing_libvosk_is_not_run_not_a_crash(self) -> None:
        report = run_voice_pipeline_inventory()
        by_name = {item["name"]: item for item in report.stages}
        runtime = by_name["STT runtime (libvosk)"]
        self.assertIn(runtime["status"], {"PASS", NOT_RUN})
        if runtime["status"] == NOT_RUN:
            detail = runtime["detail"].lower()
            self.assertTrue("vosk" in detail or "libvosk" in detail, runtime["detail"])
        model = by_name["STT Vosk model directory"]
        self.assertIn(model["status"], {"PASS", NOT_RUN})
        if model["status"] == NOT_RUN:
            self.assertIn("does not vendor model bytes", model["detail"])

    def test_text_path_still_plans_from_a_labelled_fixture(self) -> None:
        report = run_voice_pipeline_inventory()
        self.assertTrue(report.passed)
        self.assertEqual(report.intent_kind, "system_metric")
        self.assertEqual(report.planned_tool, "system.get_metric")
        by_name = {item["name"]: item for item in report.stages}
        self.assertEqual(by_name["text / keyboard fallback"]["status"], "PASS")
        self.assertEqual(by_name["keyboard path remains callable"]["status"], "PASS")
        self.assertEqual(by_name["companion AI states (real pipeline)"]["status"], "PASS")
        self.assertTrue(by_name["companion AI states (real pipeline)"]["thinkingIsNotChainOfThought"])

    def test_inventory_refuses_to_record_spoken_pass(self) -> None:
        report = run_voice_pipeline_inventory()
        with self.assertRaises(ValueError):
            report.record(99, "spoken e2e", evidence=IMAGE_BOOT, status="PASS", detail="no")
        with self.assertRaises(ValueError):
            report.record(
                99, "live microphone journey",
                evidence=IMAGE_BOOT, status="PASS", detail="no",
            )


class ConstructionBoundaryTests(unittest.TestCase):
    def test_missing_libvosk_or_tts_does_not_raise(self) -> None:
        result = construct_speech_and_voice_safely()
        self.assertFalse(result["speechRaised"], result.get("speechError"))
        self.assertFalse(result["voiceRaised"], result.get("voiceError"))
        self.assertTrue(result["typedInputPreserved"])
        self.assertEqual(result["spokenE2e"], NOT_RUN)
        self.assertTrue(result["speechAvailable"])
        self.assertTrue(result["voiceAvailable"])
        if "speechReadiness" in result:
            self.assertNotEqual(result["speechReadiness"], "PASS")


class VoiceStoryHonestyTests(unittest.TestCase):
    def test_story_does_not_pass_live_stt_or_tts(self) -> None:
        report = run_voice_story()
        statuses = {item["name"]: item for item in report.steps}
        self.assertEqual(statuses["speech-to-text"]["status"], NOT_RUN)
        self.assertTrue(statuses["speech-to-text"].get("fixture"))
        self.assertEqual(statuses["local TTS"]["status"], NOT_RUN)
        self.assertEqual(statuses["probe microphone capture"]["status"], NOT_RUN)
        document = report.to_json()
        self.assertEqual(document["spokenE2e"], NOT_RUN)
        self.assertEqual(document["transcriptSource"], "labelled-fixture")
        self.assertTrue(report.passed)

    def test_unrecognised_utterance_still_does_not_invent_a_shell(self) -> None:
        report = run_voice_story(utterance="rm -rf /")
        self.assertFalse(report.passed)
        self.assertEqual(report.planned_tool, "")


class InventoryCliTests(unittest.TestCase):
    def test_cli_inventory_never_claims_spoken_pass(self) -> None:
        from companion import cli as companion_cli
        from pathlib import Path
        import tempfile

        root = Path(tempfile.mkdtemp(prefix="bunny-voice-pipeline-cli-"))
        document = companion_cli.dispatch(parse("voice-pipeline-inventory", root=root))
        json.dumps(document)
        self.assertEqual(document["spokenE2e"], NOT_RUN)
        self.assertNotEqual(document["spokenE2e"], "PASS")
        self.assertFalse(document["construction"]["speechRaised"])
        self.assertFalse(document["construction"]["voiceRaised"])
        live = [
            item for item in document["stages"]
            if item["name"] in LIVE_STAGES
        ]
        self.assertEqual(len(live), len(LIVE_STAGES))
        self.assertTrue(all(item["status"] == NOT_RUN for item in live))


if __name__ == "__main__":
    unittest.main()
