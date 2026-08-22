# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the Voice & AI readiness probe.

The probe reports ``available`` only after a real probe target was found,
``unavailable`` after a check that found nothing, and ``unknown`` when the
host cannot measure the concern at all. These tests exercise the probing
helpers against tempdirs we control and assert the public
:func:`voice_ai_readiness` returns ``unknown`` on a non-POSIX host (the host
these tests run on is Windows, where ``/usr/share/...`` is not a real
filesystem location and claiming anything else would be a measurement that
was never made).

No mocks: the tempdirs hold real files, and the binary probe is driven by
real executables created on disk.
"""

from __future__ import annotations

import os
from pathlib import Path
import stat
import tempfile
import unittest

from bunny_shell.readiness import (
    _is_gguf_model,
    _is_vosk_model,
    _probe_binary,
    _probe_directory,
    voice_ai_readiness,
)


class ProbeDirectoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name)

    def test_nonexistent_directory_is_unavailable(self) -> None:
        result = _probe_directory([self.root / "does-not-exist"], predicate=_is_vosk_model)
        self.assertEqual(result, "unavailable")

    def test_empty_directory_is_unavailable(self) -> None:
        (self.root / "models").mkdir()
        result = _probe_directory([self.root / "models"], predicate=_is_vosk_model)
        self.assertEqual(result, "unavailable")

    def test_directory_with_matching_entry_is_available(self) -> None:
        directory = self.root / "models"
        directory.mkdir()
        (directory / "vosk-model-small-en-us-0.15").mkdir()
        result = _probe_directory([directory], predicate=_is_vosk_model)
        self.assertEqual(result, "available")

    def test_first_directory_with_match_wins(self) -> None:
        empty = self.root / "empty"
        empty.mkdir()
        full = self.root / "full"
        full.mkdir()
        (full / "vosk-model-small-en-us-0.15").mkdir()
        result = _probe_directory([empty, full], predicate=_is_vosk_model)
        self.assertEqual(result, "available")

    def test_gguf_predicate_matches_model_file(self) -> None:
        directory = self.root / "agent-models"
        directory.mkdir()
        model = directory / "mistral-7b.Q4_K_M.gguf"
        model.write_bytes(b"\x00")
        self.assertTrue(_is_gguf_model(model))

    def test_gguf_predicate_rejects_non_gguf(self) -> None:
        directory = self.root / "agent-models"
        directory.mkdir()
        not_model = directory / "README.txt"
        not_model.write_bytes(b"not a model")
        self.assertFalse(_is_gguf_model(not_model))

    def test_vosk_predicate_rejects_non_model_directory(self) -> None:
        directory = self.root / "models"
        directory.mkdir()
        (directory / "not-a-model").mkdir()
        result = _probe_directory([directory], predicate=_is_vosk_model)
        self.assertEqual(result, "unavailable")


class ProbeBinaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name)

    def _make_executable(self, name: str) -> Path:
        """Create a real executable in a tempdir and return the directory.

        ``shutil.which`` resolves a bare name by appending each PATHEXT
        extension on Windows, but a Unix executable is found by its executable
        bit. The file is therefore created with the platform's own convention —
        ``name`` on POSIX, ``name + ".exe"`` on Windows — so the probe
        genuinely resolves it on either host instead of the test passing only
        where the executable bit is honoured.
        """
        directory = self.root / "bin"
        directory.mkdir(exist_ok=True)
        filename = name if os.name == "posix" else f"{name}.exe"
        path = directory / filename
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        try:
            path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        except OSError:
            pass
        return directory

    def test_absent_binary_is_unavailable(self) -> None:
        result = _probe_binary(("does-not-exist-xyz",), path_dirs=[self.root])
        self.assertEqual(result, "unavailable")

    def test_present_binary_is_available(self) -> None:
        binary_dir = self._make_executable("espeak-ng")
        result = _probe_binary(("espeak-ng",), path_dirs=[binary_dir])
        self.assertEqual(result, "available")

    def test_first_matching_binary_wins(self) -> None:
        binary_dir = self._make_executable("speech-dispatcher")
        result = _probe_binary(("espeak-ng", "speech-dispatcher"), path_dirs=[binary_dir])
        self.assertEqual(result, "available")

    def test_no_path_dirs_uses_environment_path(self) -> None:
        # We cannot assert available (PATH varies), but the probe must not
        # crash and must return a valid verdict.
        result = _probe_binary(("python3", "python"))
        self.assertIn(result, ("available", "unavailable"))


class VoiceAiReadinessTests(unittest.TestCase):
    def test_non_posix_host_reports_unknown_for_every_concern(self) -> None:
        if os.name == "posix":
            self.skipTest("this test asserts the non-POSIX refusal")
        result = voice_ai_readiness()
        for concern in ("microphone", "recognizerModel", "ttsEngine", "localAiModel"):
            with self.subTest(concern=concern):
                self.assertEqual(result[concern], "unknown", f"{concern} must be unknown on a non-POSIX host")

    def test_unknown_when_companion_directories_are_overridden_to_nonexistent(self) -> None:
        if os.name != "posix":
            self.skipTest("directory probing is a POSIX concern")
        result = voice_ai_readiness(
            speech_model_dirs=[Path("/nonexistent-speech-models")],
            agent_model_dirs=[Path("/nonexistent-agent-models")],
        )
        self.assertEqual(result["recognizerModel"], "unavailable")
        self.assertEqual(result["localAiModel"], "unavailable")

    def test_available_only_when_a_real_probe_target_exists(self) -> None:
        if os.name != "posix":
            self.skipTest("directory probing is a POSIX concern")
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            speech_dir = root / "speech-models"
            speech_dir.mkdir()
            (speech_dir / "vosk-model-small-en-us-0.15").mkdir()
            agent_dir = root / "agent-models"
            agent_dir.mkdir()
            (agent_dir / "mistral-7b.Q4_K_M.gguf").write_bytes(b"\x00")
            # Create a fake llama-cli executable so the local-ai probe can
            # resolve the binary without claiming available for a model it
            # cannot run.
            bin_dir = root / "bin"
            bin_dir.mkdir()
            llama_cli = bin_dir / "llama-cli"
            llama_cli.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            llama_cli.chmod(llama_cli.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
            result = voice_ai_readiness(
                speech_model_dirs=[speech_dir],
                agent_model_dirs=[agent_dir],
                binary_path_dirs=[bin_dir],
            )
            self.assertEqual(result["recognizerModel"], "available")
            self.assertEqual(result["localAiModel"], "available")

    def test_local_ai_unavailable_when_model_present_but_binary_absent(self) -> None:
        if os.name != "posix":
            self.skipTest("directory probing is a POSIX concern")
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            agent_dir = root / "agent-models"
            agent_dir.mkdir()
            (agent_dir / "mistral-7b.Q4_K_M.gguf").write_bytes(b"\x00")
            result = voice_ai_readiness(
                agent_model_dirs=[agent_dir],
                binary_path_dirs=[root / "empty-bin"],
            )
            self.assertEqual(result["localAiModel"], "unavailable")

    def test_result_has_exactly_the_four_concerns(self) -> None:
        result = voice_ai_readiness()
        self.assertEqual(set(result), {"microphone", "recognizerModel", "ttsEngine", "localAiModel"})

    def test_every_value_is_a_known_verdict(self) -> None:
        result = voice_ai_readiness()
        for concern, verdict in result.items():
            with self.subTest(concern=concern):
                self.assertIn(verdict, ("available", "unavailable", "unknown"))


if __name__ == "__main__":
    unittest.main()