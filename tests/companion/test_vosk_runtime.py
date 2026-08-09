# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The standard-library binding used with Fedora's packaged libvosk."""

from __future__ import annotations

import unittest

from companion.speech import vosk_runtime


class _Function:
    def __init__(self, answer=None) -> None:
        self.answer = answer
        self.calls: list[tuple[object, ...]] = []
        self.argtypes = None
        self.restype = None

    def __call__(self, *arguments):
        self.calls.append(arguments)
        return self.answer


class _Library:
    def __init__(self) -> None:
        self.vosk_model_new = _Function(101)
        self.vosk_model_free = _Function()
        self.vosk_recognizer_new = _Function(202)
        self.vosk_recognizer_free = _Function()
        self.vosk_recognizer_set_words = _Function()
        self.vosk_recognizer_accept_waveform = _Function(1)
        self.vosk_recognizer_result = _Function(b'{"text":"open files"}')
        self.vosk_recognizer_partial_result = _Function(b'{"partial":"open"}')
        self.vosk_recognizer_final_result = _Function(b'{"text":"open files"}')
        self.vosk_set_log_level = _Function()


class NativeBinding(unittest.TestCase):
    def setUp(self) -> None:
        self.original = vosk_runtime._loaded
        self.library = _Library()
        vosk_runtime._loaded = vosk_runtime._Api(self.library, "fixture-libvosk.so")
        self.addCleanup(setattr, vosk_runtime, "_loaded", self.original)

    def test_minimal_streaming_surface_calls_the_public_c_api(self) -> None:
        self.assertEqual(vosk_runtime.probe(), "fixture-libvosk.so")
        model = vosk_runtime.Model("/trusted/model")
        recognizer = vosk_runtime.KaldiRecognizer(model, 16_000)
        recognizer.SetWords(True)
        self.assertTrue(recognizer.AcceptWaveform(b"\x00\x01" * 320))
        self.assertEqual(recognizer.PartialResult(), '{"partial":"open"}')
        self.assertEqual(recognizer.Result(), '{"text":"open files"}')
        self.assertEqual(recognizer.FinalResult(), '{"text":"open files"}')
        recognizer.close()
        model.close()

        self.assertEqual(self.library.vosk_model_new.calls[0][0], b"/trusted/model")
        self.assertEqual(self.library.vosk_recognizer_set_words.calls[0][1], 1)
        self.assertEqual(len(self.library.vosk_recognizer_free.calls), 1)
        self.assertEqual(len(self.library.vosk_model_free.calls), 1)

    def test_runtime_path_is_not_supplied_by_a_request_or_environment_variable(self) -> None:
        self.assertEqual(vosk_runtime.LIBRARY_CANDIDATES, (
            "/usr/lib64/libvosk.so", "/usr/lib/libvosk.so",
        ))
        self.assertTrue(all(path.startswith("/") for path in vosk_runtime.LIBRARY_CANDIDATES))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
