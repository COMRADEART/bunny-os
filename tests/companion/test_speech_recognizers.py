# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Vosk adapter, driven by an injected engine so the contract is testable
anywhere.

What these tests prove is the *adapter*: lazy probing, honest unavailability,
model discovery restricted to trusted directories, partial assembly and final
flushing. What they cannot prove is the model itself, which the Linux
validation runs against the real library and reports separately.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

from companion.speech.recognizers import (
    MODEL_DIRECTORIES,
    VoskRecognizer,
    _discover_model,
)

from .speech_support import make_request

from .support import temporary_root


class _FakeEngine:
    """The KaldiRecognizer surface the session drives, scripted."""

    def __init__(self, model: object, rate: float) -> None:
        self.rate = rate
        self.fed = 0
        self.words_set = False
        self._segments = ["count the", "words"]
        self._partials = ["count", "count the", "count the words"]
        self._step = 0

    def SetWords(self, value: bool) -> None:  # noqa: N802 - vosk's own casing
        self.words_set = bool(value)

    def AcceptWaveform(self, data: bytes) -> bool:  # noqa: N802
        self.fed += len(data)
        self._step += 1
        return self._step % 3 == 0  # every third chunk finalises a segment

    def Result(self) -> str:  # noqa: N802
        segment = self._segments.pop(0) if self._segments else ""
        return json.dumps({
            "text": segment,
            "result": [{"word": word, "conf": 0.9} for word in segment.split()],
        })

    def PartialResult(self) -> str:  # noqa: N802
        index = min(self._step, len(self._partials) - 1)
        return json.dumps({"partial": self._partials[index]})

    def FinalResult(self) -> str:  # noqa: N802
        return json.dumps({
            "text": "please",
            "result": [{"word": "please", "conf": 0.8}],
        })


class _FakeVosk:
    __version__ = "0.3.45-test"

    def __init__(self) -> None:
        self.models_loaded: list[str] = []

    def Model(self, path: str):  # noqa: N802
        self.models_loaded.append(path)
        return object()

    def KaldiRecognizer(self, model: object, rate: float) -> _FakeEngine:  # noqa: N802
        return _FakeEngine(model, rate)


def _model_directory(parent: Path, name: str = "vosk-model-small-en-us-0.15") -> Path:
    target = parent / name
    target.mkdir(parents=True)
    (target / "README").write_text("model data", encoding="utf-8")
    return target


class Availability(unittest.TestCase):
    def test_no_library_reports_unavailable_with_the_reason(self) -> None:
        def _refuse():
            raise ImportError("No module named 'vosk'")

        recognizer = VoskRecognizer(
            model_directories=(str(temporary_root(self)),), importer=_refuse,
        )
        health = recognizer.health()
        self.assertFalse(health.available)
        self.assertIn("not importable", health.detail)

    def test_a_library_with_no_model_reports_unavailable(self) -> None:
        recognizer = VoskRecognizer(
            model_directories=(str(temporary_root(self)),), importer=_FakeVosk,
        )
        health = recognizer.health()
        self.assertFalse(health.available)
        self.assertIn("no recognition model", health.detail)

    def test_an_installed_model_makes_the_adapter_ready_and_declared(self) -> None:
        root = temporary_root(self)
        _model_directory(root)
        recognizer = VoskRecognizer(model_directories=(str(root),), importer=_FakeVosk)
        health = recognizer.health()
        self.assertTrue(health.available)
        declaration = recognizer.declaration
        self.assertTrue(declaration.fully_declared)
        self.assertTrue(declaration.local)
        self.assertEqual(declaration.languages, ("en",))
        self.assertEqual(declaration.locales, ("en-US",))
        self.assertTrue(declaration.supports_streaming)
        self.assertIn("vosk/0.3.45-test", declaration.implementation_id)
        self.assertGreater(declaration.resource_estimate.model_memory_bytes, 0)

    def test_nothing_loads_at_construction(self) -> None:
        """§4: no model in memory until a capture needs one."""
        root = temporary_root(self)
        _model_directory(root)
        fake = _FakeVosk()
        recognizer = VoskRecognizer(model_directories=(str(root),), importer=lambda: fake)
        recognizer.health()
        self.assertEqual(fake.models_loaded, [])
        recognizer.start(make_request())
        self.assertEqual(len(fake.models_loaded), 1)


class ModelDiscovery(unittest.TestCase):
    def test_the_search_list_is_a_fixed_tuple_of_trusted_places(self) -> None:
        self.assertEqual(MODEL_DIRECTORIES, (
            "/usr/share/bunny-os/speech-models",
            "~/.local/share/bunny-os/speech-models",
        ))

    def test_an_unrecognised_directory_name_is_not_a_model(self) -> None:
        root = temporary_root(self)
        (root / "definitely-not-a-model").mkdir()
        path, _language, _locale, detail = _discover_model((str(root),))
        self.assertIsNone(path)
        self.assertIn("no recognition model", detail)

    @unittest.skipUnless(os.name == "posix", "permission semantics are POSIX")
    def test_a_world_writable_model_is_refused_with_the_reason(self) -> None:
        root = temporary_root(self)
        target = _model_directory(root)
        target.chmod(0o777)
        path, _language, _locale, detail = _discover_model((str(root),))
        self.assertIsNone(path)
        self.assertIn("writable by group or other", detail)

    @unittest.skipUnless(os.name == "posix", "symlink semantics are POSIX")
    def test_a_symlinked_model_is_refused(self) -> None:
        root = temporary_root(self)
        elsewhere = temporary_root(self) / "vosk-model-small-en-us-0.15"
        elsewhere.mkdir()
        (root / "vosk-model-small-en-us-0.15").symlink_to(elsewhere)
        path, _language, _locale, detail = _discover_model((str(root),))
        self.assertIsNone(path)
        self.assertIn("symbolic link", detail)


class Sessions(unittest.TestCase):
    def setUp(self) -> None:
        root = temporary_root(self)
        _model_directory(root)
        self.recognizer = VoskRecognizer(
            model_directories=(str(root),), importer=_FakeVosk,
        )

    def test_partials_grow_monotonically_and_carry_provenance(self) -> None:
        session = self.recognizer.start(make_request())
        revisions: list[int] = []
        for _ in range(6):
            partial = session.accept(b"\x00" * 640, position_seconds=0.1)
            if partial is not None:
                revisions.append(partial.revision)
                self.assertEqual(partial.provider_id, "vosk")
                self.assertTrue(partial.provisional)
        self.assertEqual(revisions, sorted(revisions))
        self.assertTrue(revisions)

    def test_the_final_joins_segments_and_averages_confidence(self) -> None:
        session = self.recognizer.start(make_request())
        for _ in range(6):
            session.accept(b"\x00" * 640)
        final = session.finish()
        self.assertEqual(final.text, "count the words please")
        # Three segment words at 0.9 and the final flush's one at 0.8.
        self.assertAlmostEqual(final.confidence, (0.9 * 3 + 0.8) / 4, places=3)
        self.assertEqual(final.recognition_mode, "streaming")

    def test_a_cancelled_session_has_no_answer(self) -> None:
        session = self.recognizer.start(make_request())
        session.accept(b"\x00" * 640)
        session.cancel()
        self.assertIsNone(session.accept(b"\x00" * 640))
        with self.assertRaises(RuntimeError):
            session.finish()

    def test_the_model_loads_once_across_sessions(self) -> None:
        fake = _FakeVosk()
        root = temporary_root(self)
        _model_directory(root)
        recognizer = VoskRecognizer(model_directories=(str(root),), importer=lambda: fake)
        recognizer.start(make_request(request_id="speechreq-a"))
        recognizer.start(make_request(request_id="speechreq-b"))
        self.assertEqual(len(fake.models_loaded), 1)

    def test_a_closed_recognizer_refuses_new_sessions(self) -> None:
        self.recognizer.close()
        with self.assertRaises(RuntimeError):
            self.recognizer.start(make_request())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
