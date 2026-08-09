# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The small Python boundary around Fedora's packaged Vosk C runtime.

Fedora 44 ships ``libvosk.so`` in ``vosk-api-devel`` but does not ship the
upstream Python wheel.  The wheel imports HTTP, progress-bar, subtitle and
WebSocket packages even when an application only needs local recognition.  A
desktop input service should not gain those dependencies (or the wheel's model
download helpers) merely to call the six C functions it uses.

This module therefore wraps the public, Apache-2.0 Vosk C API with
:mod:`ctypes`, which is part of Python.  It deliberately exposes the same tiny
surface :class:`companion.speech.recognizers.VoskRecognizer` already consumes:
``Model``, ``KaldiRecognizer`` and ``SetLogLevel``.  It has no model discovery,
network access, command execution or user-controlled library path.

Loading is lazy.  Importing this module does not map the native library; the
recogniser's health probe calls :func:`probe`, and a missing or unloadable
runtime becomes ``STT_RUNTIME_MISSING`` rather than a service crash.
"""

from __future__ import annotations

import ctypes
from pathlib import Path
import threading
from typing import Any

__all__ = [
    "KaldiRecognizer",
    "Model",
    "SetLogLevel",
    "VoskRuntimeUnavailable",
    "probe",
]

__version__ = "native-c-api-1"

# Fixed, administrator-owned locations only.  A bare soname would let
# ``LD_LIBRARY_PATH`` redirect the user service to an unreviewed library even
# though no request supplied a path.  Fedora installs the development soname in
# one of these multiarch roots, so no dynamic search fallback is needed.
LIBRARY_CANDIDATES: tuple[str, ...] = (
    "/usr/lib64/libvosk.so",
    "/usr/lib/libvosk.so",
)


class VoskRuntimeUnavailable(RuntimeError):
    """The packaged native runtime could not be loaded."""


class _Api:
    """Typed functions from one successfully loaded Vosk shared library."""

    def __init__(self, library: Any, origin: str) -> None:
        self.library = library
        self.origin = origin

        library.vosk_model_new.argtypes = [ctypes.c_char_p]
        library.vosk_model_new.restype = ctypes.c_void_p
        library.vosk_model_free.argtypes = [ctypes.c_void_p]
        library.vosk_model_free.restype = None

        library.vosk_recognizer_new.argtypes = [ctypes.c_void_p, ctypes.c_float]
        library.vosk_recognizer_new.restype = ctypes.c_void_p
        library.vosk_recognizer_free.argtypes = [ctypes.c_void_p]
        library.vosk_recognizer_free.restype = None
        library.vosk_recognizer_set_words.argtypes = [ctypes.c_void_p, ctypes.c_int]
        library.vosk_recognizer_set_words.restype = None
        library.vosk_recognizer_accept_waveform.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_int,
        ]
        library.vosk_recognizer_accept_waveform.restype = ctypes.c_int
        for name in (
            "vosk_recognizer_result",
            "vosk_recognizer_partial_result",
            "vosk_recognizer_final_result",
        ):
            function = getattr(library, name)
            function.argtypes = [ctypes.c_void_p]
            function.restype = ctypes.c_char_p

        library.vosk_set_log_level.argtypes = [ctypes.c_int]
        library.vosk_set_log_level.restype = None


_guard = threading.RLock()
_loaded: _Api | None = None


def _load() -> _Api:
    global _loaded
    with _guard:
        if _loaded is not None:
            return _loaded
        failures: list[str] = []
        for candidate in LIBRARY_CANDIDATES:
            # Do not turn a missing fixed path into a noisy loader error.
            if not Path(candidate).is_file():
                continue
            try:
                library = ctypes.CDLL(candidate)
                api = _Api(library, candidate)
            except (AttributeError, OSError) as exc:
                failures.append(f"{candidate}: {exc}")
                continue
            _loaded = api
            return api
        detail = "; ".join(failures[:3]) or "libvosk.so was not found"
        raise VoskRuntimeUnavailable(
            "the packaged Vosk runtime is unavailable: " + detail
        )


def probe() -> str:
    """Load the runtime if necessary and return its resolved origin."""
    return _load().origin


def _text(function: Any, handle: ctypes.c_void_p) -> str:
    raw = function(handle)
    if raw is None:
        raise RuntimeError("Vosk returned no JSON result")
    return bytes(raw).decode("utf-8", errors="strict")


class Model:
    """One reference-counted Vosk model handle."""

    def __init__(self, path: str) -> None:
        api = _load()
        handle = api.library.vosk_model_new(path.encode("utf-8"))
        if not handle:
            raise RuntimeError("Vosk could not load the selected recognition model")
        self._api = api
        self._handle: ctypes.c_void_p | None = handle

    def close(self) -> None:
        handle, self._handle = self._handle, None
        if handle:
            self._api.library.vosk_model_free(handle)

    def __del__(self) -> None:  # pragma: no cover - deterministic owners retain it
        try:
            self.close()
        except Exception:
            pass


class KaldiRecognizer:
    """A streaming recogniser over one shared :class:`Model`."""

    def __init__(self, model: Model, sample_rate: float) -> None:
        if model._handle is None:
            raise RuntimeError("the Vosk model was already closed")
        handle = model._api.library.vosk_recognizer_new(
            model._handle, ctypes.c_float(float(sample_rate))
        )
        if not handle:
            raise RuntimeError("Vosk could not create a streaming recogniser")
        self._api = model._api
        self._model = model
        self._handle: ctypes.c_void_p | None = handle

    def _open_handle(self) -> ctypes.c_void_p:
        if self._handle is None:
            raise RuntimeError("the Vosk recogniser was already closed")
        return self._handle

    def SetWords(self, enabled: bool) -> None:  # noqa: N802 - Vosk compatibility
        self._api.library.vosk_recognizer_set_words(
            self._open_handle(), 1 if enabled else 0
        )

    def AcceptWaveform(self, frames: bytes) -> bool:  # noqa: N802
        if not isinstance(frames, bytes):
            frames = bytes(frames)
        result = self._api.library.vosk_recognizer_accept_waveform(
            self._open_handle(), frames, len(frames)
        )
        if result < 0:
            raise RuntimeError("Vosk rejected captured audio frames")
        return bool(result)

    def Result(self) -> str:  # noqa: N802
        return _text(self._api.library.vosk_recognizer_result, self._open_handle())

    def PartialResult(self) -> str:  # noqa: N802
        return _text(
            self._api.library.vosk_recognizer_partial_result,
            self._open_handle(),
        )

    def FinalResult(self) -> str:  # noqa: N802
        return _text(
            self._api.library.vosk_recognizer_final_result,
            self._open_handle(),
        )

    def close(self) -> None:
        handle, self._handle = self._handle, None
        if handle:
            self._api.library.vosk_recognizer_free(handle)

    def __del__(self) -> None:  # pragma: no cover - sessions own deterministic close
        try:
            self.close()
        except Exception:
            pass


def SetLogLevel(level: int) -> None:  # noqa: N802 - Vosk compatibility
    _load().library.vosk_set_log_level(int(level))
