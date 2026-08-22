# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Derived Voice & AI readiness probe.

This module reports, per concern, whether a Voice & AI capability is
``available``, ``unavailable``, or ``unknown`` on the current host. It is a
*derived* probe: nothing it reports is stored in ``settings.json``. The
settings page shows these values alongside the stored toggles so a user can
see the difference between "I turned voice on" and "voice can actually run
here".

Discipline:

* **Never claim available without checking.** A concern is ``available`` only
  after a real probe target — a trusted directory that exists and holds a
  model, or a binary resolved on ``PATH`` — was found. An absent path that was
  checked is ``unavailable``; a path that cannot be measured at all (a
  non-POSIX host where ``/usr/share/...`` is not a real filesystem location)
  is ``unknown``.
* **Headless-importable.** No ``gi`` / ``GTK`` import, now or in any companion
  module pulled in. The companion trusted-directory constants are imported
  lazily inside :func:`voice_ai_readiness` so that a host without the companion
  package still gets ``unknown`` rather than an ``ImportError``.
* **No execution.** The probe never launches a binary; it only checks for the
  binary's presence with :func:`shutil.which`.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
from typing import Any, Sequence


def _probe_directory(
    directories: Sequence[Path | str],
    *,
    predicate: Any,
) -> str:
    """``available`` if any directory holds a matching entry, else ``unavailable``.

    ``predicate`` is a callable that receives a :class:`Path` entry and returns
    ``True`` for a match. A directory that does not exist or cannot be read is
    counted as "checked and empty" — ``unavailable`` — because the probe did
    run; it found nothing. This is distinct from ``unknown``, which is reserved
    for hosts where the probe cannot run at all (see :func:`voice_ai_readiness`).
    """
    for raw in directories:
        directory = Path(raw).expanduser()
        try:
            entries = list(directory.iterdir())
        except (FileNotFoundError, NotADirectoryError, PermissionError, OSError):
            continue
        for entry in entries:
            try:
                if predicate(entry):
                    return "available"
            except OSError:
                continue
    return "unavailable"


def _probe_binary(names: Sequence[str], *, path_dirs: Sequence[Path | str] | None = None) -> str:
    """``available`` if any named binary is resolvable, else ``unavailable``.

    ``path_dirs`` is prepended to ``PATH`` for the search, so a test can point
    at a temporary directory holding a real executable without modifying the
    process environment. The probe never runs the binary — :func:`shutil.which`
    only checks that an executable file exists at a resolvable location.
    """
    search_path: str | None = None
    if path_dirs is not None:
        existing = os.environ.get("PATH", "")
        extra = os.pathsep.join(str(Path(p)) for p in path_dirs)
        search_path = f"{extra}{os.pathsep}{existing}" if existing else extra
    for name in names:
        if shutil.which(name, path=search_path) is not None:
            return "available"
    return "unavailable"


def _is_vosk_model(entry: Path) -> bool:
    """A recogniser model directory looks like ``vosk-model-*``."""
    return entry.is_dir() and entry.name.startswith("vosk-model-")


def _is_gguf_model(entry: Path) -> bool:
    """A local agent model file has a ``.gguf`` extension."""
    return entry.is_file() and entry.suffix == ".gguf"


def voice_ai_readiness(
    *,
    speech_model_dirs: Sequence[Path | str] | None = None,
    agent_model_dirs: Sequence[Path | str] | None = None,
    binary_path_dirs: Sequence[Path | str] | None = None,
) -> dict[str, str]:
    """Report Voice & AI readiness per concern.

    Returns a dict with keys ``microphone``, ``recognizerModel``, ``ttsEngine``
    and ``localAiModel``, each mapping to one of ``available``, ``unavailable``
    or ``unknown``.

    On a non-POSIX host (Windows, macOS) every concern is ``unknown``: the
    trusted directories are Linux filesystem locations (``/usr/share/...``)
    that cannot be probed honestly here, and claiming they are absent would be
    a measurement that was never made.

    The optional directory and ``binary_path_dirs`` overrides exist for tests
    that want to drive the probe against a tempdir they control. When omitted,
    the companion package's trusted-directory constants are imported lazily.
    If the companion package is itself unavailable, the directory-based
    concerns fall back to ``unknown`` rather than raising.
    """
    if os.name != "posix":
        return {
            "microphone": "unknown",
            "recognizerModel": "unknown",
            "ttsEngine": "unknown",
            "localAiModel": "unknown",
        }

    # Microphone: the cheapest honest signal is a capture tool on PATH. A
    # tool being present does not prove a device is plugged in, but it proves
    # the audio subsystem that would drive one is installed. The probe never
    # claims more than it checked.
    microphone = _probe_binary(("parecord", "arecord"), path_dirs=binary_path_dirs)

    # Recogniser model: probe the companion speech-model trusted directories
    # for a ``vosk-model-*`` directory. If the caller did not override the
    # directories, import the companion constant lazily.
    if speech_model_dirs is None:
        speech_model_dirs = _companion_speech_directories()
    if speech_model_dirs is None:
        recognizer_model: str = "unknown"
    else:
        recognizer_model = _probe_directory(speech_model_dirs, predicate=_is_vosk_model)

    # TTS engine: check for the two local engines the ``ttsEngine`` setting
    # names. ``speech-dpatcher`` is the setting alias; the binary is
    # ``speech-dispatcher``.
    tts = _probe_binary(
        ("espeak-ng", "speech-dispatcher", "spd-say"),
        path_dirs=binary_path_dirs,
    )

    # Local AI model: available only when both a model file is present in a
    # trusted directory *and* the ``llama-cli`` runtime binary is resolvable.
    if agent_model_dirs is None:
        agent_model_dirs = _companion_agent_directories()
    if agent_model_dirs is None:
        local_ai: str = "unknown"
    else:
        model_present = _probe_directory(agent_model_dirs, predicate=_is_gguf_model)
        binary_present = _probe_binary(("llama-cli",), path_dirs=binary_path_dirs)
        local_ai = "available" if (model_present == "available" and binary_present == "available") else "unavailable"

    return {
        "microphone": microphone,
        "recognizerModel": recognizer_model,
        "ttsEngine": tts,
        "localAiModel": local_ai,
    }


def _companion_speech_directories() -> tuple[str, ...] | None:
    """Lazily import the companion speech-model directory constant."""
    try:
        from companion.speech.recognizers import MODEL_DIRECTORIES  # type: ignore[import-not-found]
    except ImportError:
        return None
    return MODEL_DIRECTORIES


def _companion_agent_directories() -> tuple[Path, ...] | None:
    """Lazily import the companion agent-model directory constant."""
    try:
        from companion.agents.adapters.llamacli import trusted_model_directories  # type: ignore[import-not-found]
    except ImportError:
        return None
    return trusted_model_directories()