# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Host-honest voice pipeline inventory. Every voice stage is NOT_RUN."""

from __future__ import annotations

import json
import unittest

from companion.voice_pipeline import (
    NOT_RUN,
    VOICE_STAGES,
    construct_speech_and_voice_safely,
    run_voice_pipeline_inventory,
)
from companion.voice_story import VOICE_STORY_UTTERANCE, run_voice_story

from .test_cli import parse


class VoicePipelineInventoryTests(unittest.TestCase):
    def test_every_voice_stage_is_not_run(self) -> None:
        report = run_voice_pipeline_inventory()
        document = report.to_json()
        json.dumps(document)
        self.assertEqual(document["spokenE2e"], NOT_RUN)
        self.assertFalse(document["fedoraImageOnHorizon"])
        self.assertTrue(document["packageListIsNotImageEvidence"])
        self.assertFalse(document["conversationSummaryWired"])
        self.assertFalse(document["cloudContextNoneTightened"])
        self.assertFalse(document["modelBytesVendored"])
        self.assertFalse(document["gpuClaimed"])
        self.assertFalse(document["npuClaimed"])
        self.assertEqual(document["transcriptSource"], "labelled-fixture")
        self.assertEqual(document["transcript"], VOICE_STORY_UTTERANCE)
        names = [item["name"] for item in document["stages"]]
        self.assertEqual(tuple(names), VOICE_STAGES)
        for item in document["stages"]:
            self.assertEqual(item["status"], NOT_RUN, item["name"])
            self.assertEqual(item["evidence"], NOT_RUN, item["name"])
            self.assertNotEqual(item["status"], "PASS", item["name"])
            self.assertIn("NOT_RUN", item["detail"])
            self.assertIn("horizon", item["detail"].lower())

    def test_failure_isolation_is_not_run_live(self) -> None:
        report = run_voice_pipeline_inventory()
        failures = {row["failure"] for row in report.isolation}
        self.assertGreaterEqual(len(failures), 8)
        for row in report.isolation:
            self.assertEqual(row["hostStatus"], NOT_RUN, row["failure"])
            self.assertNotEqual(row["hostStatus"], "PASS", row["failure"])
        expected = {
            "mic unavailable",
            "STT / libvosk missing",
            "STT failure",
            "silence",
            "malformed transcript",
            "model timeout / crash",
            "tool failure",
            "TTS unavailable",
        }
        self.assertTrue(expected <= failures)

    def test_package_list_names_are_not_image_claims(self) -> None:
        report = run_voice_pipeline_inventory()
        blob = json.dumps(report.to_json())
        self.assertIn("package list", blob.lower())
        self.assertFalse(report.to_json()["fedoraImageOnHorizon"])

    def test_typed_path_is_not_a_voice_stage_pass(self) -> None:
        report = run_voice_pipeline_inventory()
        document = report.to_json()
        self.assertTrue(document["typedInputPreserved"])
        self.assertTrue(document["typedFallback"]["submit"])
        self.assertTrue(document["typedFallback"]["thinkingIsNotChainOfThought"])
        names = {item["name"] for item in document["stages"]}
        self.assertNotIn("text / keyboard fallback", names)
        self.assertTrue(report.passed)

    def test_inventory_refuses_a_voice_stage_pass(self) -> None:
        report = run_voice_pipeline_inventory()
        with self.assertRaises(ValueError):
            report.record_voice_stage(
                99, "spoken e2e", detail="no", status="PASS",
            )
        with self.assertRaises(ValueError):
            report.record_voice_stage(99, "not a stage", detail="no")


class ConstructionBoundaryTests(unittest.TestCase):
    def test_missing_libvosk_or_tts_does_not_raise(self) -> None:
        result = construct_speech_and_voice_safely()
        self.assertFalse(result["speechRaised"], result.get("speechError"))
        self.assertFalse(result["voiceRaised"], result.get("voiceError"))
        self.assertTrue(result["typedInputPreserved"])
        self.assertEqual(result["spokenE2e"], NOT_RUN)
        self.assertFalse(result["fedoraImageOnHorizon"])
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
        self.assertEqual(statuses["probe packaged Vosk runtime"]["status"], NOT_RUN)
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
        self.assertFalse(document["fedoraImageOnHorizon"])
        self.assertTrue(document["packageListIsNotImageEvidence"])
        self.assertFalse(document["construction"]["speechRaised"])
        self.assertFalse(document["construction"]["voiceRaised"])
        self.assertTrue(all(item["status"] == NOT_RUN for item in document["stages"]))
        self.assertEqual(len(document["stages"]), len(VOICE_STAGES))


if __name__ == "__main__":
    unittest.main()
