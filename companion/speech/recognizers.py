# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The real local recognisers this build can drive, and no other kind.

One genuine adapter: **Vosk**, a Kaldi-derived offline recogniser that runs as
an in-process library against a model directory on disk. It is here because it
is the recogniser a Fedora host can actually have — installable without a
network service, runnable without a GPU, and measurable (§25) on the reference
target. Where the library or its model is absent, the adapter reports
unavailable with the reason, and everything above it degrades to typed input;
it never fabricates an empty transcript, for the reason
:class:`companion.voice.system.AbsentSpeechRecognition` wrote down before any
recogniser existed.

There is deliberately **no remote adapter and no placeholder shaped like one**
(§9). There is also no "download a model" path: a model is present or the
recogniser is not, and the set of places a model may be present is a fixed
tuple of trusted directories below. §22's model-path-injection test holds
because no request field, no protocol parameter and no environment variable
reaches :func:`_discover_model` — the search list is a constant, and each
candidate is validated for ownership and permissions before a byte of it is
loaded, the same discipline :func:`companion.voice.recovery._owned_by_us`
applies before deleting anything.

The library is imported lazily and injectably. Lazily, because §4 forbids any
microphone-adjacent initialisation at service start and loading a 200 MiB model
in a constructor would be exactly that; injectably, because the deterministic
tests drive this adapter with a scripted engine and the contract must not
change shape depending on which is behind it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import threading
from typing import Any, Callable, Sequence

from .recognizer import (
    RecognizerDeclaration,
    RecognizerHealth,
    RecognizerResourceEstimate,
    SpeechRecognizer,
)
from .request import SpeechInputRequest
from .transcript import FinalTranscript, PartialTranscript, TranscriptError

__all__ = [
    "MODEL_DIRECTORIES",
    "VoskRecognizer",
    "local_recognizers",
]

#: Every place a recognition model may live, in search order. A fixed tuple —
#: not configuration, not a request field, not an environment variable —
#: because a writable model path is code injection with extra steps: a model
#: is data a native library parses, and pointing that parser at an attacker's
#: file is handing it the process.
#:
#: The system location first, because a model the image ships is a model the
#: build reviewed. The per-user location exists so a developer or a validation
#: host can install one without root; it is validated for ownership before use.
MODEL_DIRECTORIES: tuple[str, ...] = (
    "/usr/share/bunny-os/speech-models",
    "~/.local/share/bunny-os/speech-models",
)

#: Model directory names Vosk publishes look like
#: ``vosk-model-small-en-us-0.15``. The language is the first token after the
#: prefixes; the locale is that token plus the region when one follows.
_MODEL_NAME = re.compile(
    r"^vosk-model(?:-small)?-(?P<language>[a-z]{2,3})(?:-(?P<region>[a-z]{2}))?"
)

#: How many samples of silence-free audio the session keeps per partial
#: comparison. Only the *text* is compared; audio never accumulates here.
_SAMPLE_RATES = (8_000, 16_000, 22_050, 44_100, 48_000)


def _directory_safe(path: Path) -> tuple[bool, str]:
    """Whether a model directory is one this process may trust.

    Ownership and permissions, checked before anything is parsed: a model
    directory writable by another account is a model another account chooses.
    Root-owned is accepted — the system location is root's — and so is our own
    uid; nothing else is.
    """
    try:
        info = path.lstat()
    except OSError as exc:
        return False, f"could not be inspected: {exc.strerror or exc}"
    if stat.S_ISLNK(info.st_mode):
        return False, "is a symbolic link rather than a directory"
    if not stat.S_ISDIR(info.st_mode):
        return False, "is not a directory"
    if hasattr(os, "getuid") and info.st_uid not in (0, os.getuid()):
        return False, f"is owned by uid {info.st_uid} rather than root or this user"
    if os.name == "posix" and info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        return False, "is writable by group or other"
    return True, ""


def _directory_bytes(path: Path) -> int:
    total = 0
    try:
        for item in path.rglob("*"):
            try:
                if item.is_file():
                    total += item.stat().st_size
            except OSError:
                continue
    except OSError:
        pass
    return total


def _discover_model(
    directories: Sequence[str] = MODEL_DIRECTORIES,
) -> tuple[Path | None, str, str, str]:
    """The first usable model, or the reason there is none.

    Returns ``(path, language, locale, detail)``. The search is breadth-one:
    each trusted directory's immediate children, name-matched and
    permission-checked, first hit wins. Nothing recurses into unexpected
    places and nothing follows a link out of the tree.
    """
    problems: list[str] = []
    for root_name in directories:
        root = Path(os.path.expanduser(root_name))
        if not root.is_dir():
            continue
        try:
            children = sorted(root.iterdir())
        except OSError as exc:
            problems.append(f"{root}: {exc.strerror or exc}")
            continue
        for child in children:
            match = _MODEL_NAME.match(child.name)
            if match is None:
                continue
            safe, reason = _directory_safe(child)
            if not safe:
                problems.append(f"{child.name}: {reason}")
                continue
            language = match.group("language")
            region = match.group("region")
            locale = f"{language}-{region.upper()}" if region else ""
            return child, language, locale, ""
    if problems:
        return None, "", "", "; ".join(problems[:4])
    return None, "", "", (
        "no recognition model is installed in a trusted directory; searched "
        + ", ".join(directories)
    )


class _VoskSession:
    """One Vosk recognition, owned by the capture worker that started it.

    Vosk finalises internal segments on its own silence heuristic; the full
    utterance is those segments joined plus the final flush. Confidence is the
    mean of per-word confidences where the model reports them, and ``None``
    where it does not — never a number nothing measured.
    """

    def __init__(
        self,
        engine: Any,
        request: SpeechInputRequest,
        declaration: RecognizerDeclaration,
    ) -> None:
        self._engine = engine
        self._request = request
        self._declaration = declaration
        self._segments: list[str] = []
        self._confidences: list[float] = []
        self._revision = 0
        self._last_partial_text = ""
        self._first_position = 0.0
        self._last_position = 0.0
        self._cancelled = False
        self._finished = False
        self._guard = threading.Lock()

    def _harvest(self, raw: str) -> None:
        try:
            document = json.loads(raw or "{}")
        except json.JSONDecodeError:
            return
        text = str(document.get("text", "")).strip()
        if text:
            self._segments.append(text)
        for word in document.get("result", ()) or ():
            confidence = word.get("conf") if isinstance(word, dict) else None
            if isinstance(confidence, (int, float)):
                self._confidences.append(float(confidence))

    def accept(self, frames: bytes, *, position_seconds: float = 0.0) -> PartialTranscript | None:
        with self._guard:
            if self._cancelled or self._finished or not frames:
                return None
            if not self._first_position:
                self._first_position = position_seconds
            self._last_position = position_seconds
            if self._engine.AcceptWaveform(frames):
                self._harvest(self._engine.Result())
                partial_text = ""
            else:
                try:
                    partial_text = str(
                        json.loads(self._engine.PartialResult() or "{}").get("partial", "")
                    ).strip()
                except json.JSONDecodeError:
                    partial_text = ""
            settled = " ".join(self._segments)
            combined = " ".join(part for part in (settled, partial_text) if part)
            if not combined or combined == self._last_partial_text:
                return None
            self._last_partial_text = combined
            self._revision += 1
            try:
                return PartialTranscript(
                    request_id=self._request.request_id,
                    revision=self._revision,
                    text=combined,
                    provider_id=self._declaration.provider_id,
                    implementation_id=self._declaration.implementation_id,
                    stable_prefix=min(len(settled), len(combined)),
                    position_seconds=position_seconds,
                )
            except TranscriptError:
                # A partial past the transcript bound is dropped rather than
                # allowed to grow; the final flush applies the same bound and
                # *its* refusal is the one the user is told about.
                return None

    def finish(self) -> FinalTranscript:
        with self._guard:
            if self._cancelled:
                raise RuntimeError("this recognition was cancelled and has no answer")
            if not self._finished:
                self._harvest(self._engine.FinalResult())
                self._finished = True
            text = " ".join(self._segments)
            confidence = (
                max(0.0, min(1.0, sum(self._confidences) / len(self._confidences)))
                if self._confidences else None
            )
            return FinalTranscript(
                request_id=self._request.request_id,
                session_id=self._request.session_id,
                text=text,
                provider_id=self._declaration.provider_id,
                implementation_id=self._declaration.implementation_id,
                language=self._request.language,
                confidence=confidence,
                audio_started_at=self._first_position,
                audio_ended_at=self._last_position,
                recognition_mode="streaming",
            )

    def cancel(self) -> None:
        with self._guard:
            self._cancelled = True

    def close(self) -> None:
        with self._guard:
            self._engine = None
            self._segments.clear()
            self._confidences.clear()


class VoskRecognizer:
    """Vosk as a :class:`companion.speech.recognizer.SpeechRecognizer`.

    ``importer`` is injectable so the deterministic suite can drive this
    adapter — declaration, health, session lifecycle — with a scripted engine,
    while the Linux validation drives it with the real library. Production
    passes nothing and gets ``import vosk``.
    """

    provider_id = "vosk"

    def __init__(
        self,
        *,
        model_directories: Sequence[str] = MODEL_DIRECTORIES,
        importer: Callable[[], Any] | None = None,
    ) -> None:
        self._model_directories = tuple(model_directories)
        self._importer = importer or self._import_vosk
        self._guard = threading.RLock()
        self._probed = False
        self._module: Any = None
        self._model: Any = None
        self._model_path: Path | None = None
        self._language = ""
        self._locale = ""
        self._detail = ""
        self._failures = 0
        self._closed = False
        self._declaration: RecognizerDeclaration | None = None

    @staticmethod
    def _import_vosk() -> Any:
        import vosk  # noqa: PLC0415 - lazily, §4 forbids model load at service start

        try:
            vosk.SetLogLevel(-1)
        except Exception:  # noqa: BLE001 - logging control is best-effort
            pass
        return vosk

    # ----------------------------------------------------------------- #

    def _probe(self, *, refresh: bool = False) -> None:
        with self._guard:
            if self._probed and not refresh:
                return
            self._probed = True
            self._detail = ""
            if self._module is None:
                try:
                    self._module = self._importer()
                except Exception as exc:  # noqa: BLE001 - absence is a health answer
                    self._module = None
                    self._detail = f"the vosk library is not importable: {exc}"
                    return
            path, language, locale, detail = _discover_model(self._model_directories)
            if path is None:
                self._detail = detail
                return
            self._model_path = path
            self._language = language or "en"
            self._locale = locale

    def _build_declaration(self) -> RecognizerDeclaration:
        version = ""
        module = self._module
        if module is not None:
            version = str(getattr(module, "__version__", "") or "")
        model_name = self._model_path.name if self._model_path else ""
        disk = _directory_bytes(self._model_path) if self._model_path else 0
        return RecognizerDeclaration(
            provider_id=self.provider_id,
            implementation_id=f"vosk/{version or 'unknown'}+{model_name or 'no-model'}",
            local=True,
            languages=(self._language,) if self._language else (),
            locales=(self._locale,) if self._locale else (),
            supports_streaming=True,
            supports_partial_transcripts=True,
            provides_word_timestamps=True,
            provides_confidence=True,
            supports_cancellation=True,
            audio_formats=("raw-pcm-s16le",),
            sample_rates=_SAMPLE_RATES,
            resource_estimate=RecognizerResourceEstimate(
                # Conservative and deliberately round: a Kaldi model's resident
                # set runs several times its compressed disk size. §10 reads
                # this before any load happens, which is the point — refusing
                # is only cheaper than loading before the load.
                model_memory_bytes=max(128 * 1024 * 1024, disk * 4),
                working_memory_bytes=32 * 1024 * 1024,
                cpu_share=0.5,
                expected_first_partial_seconds=0.5,
            ),
            model_origin=str(self._model_path) if self._model_path else "",
        )

    @property
    def declaration(self) -> RecognizerDeclaration:
        self._probe()
        with self._guard:
            if self._declaration is None:
                self._declaration = self._build_declaration()
            return self._declaration

    def health(self, *, monotonic: float = 0.0, refresh: bool = False) -> RecognizerHealth:
        self._probe(refresh=refresh)
        with self._guard:
            if refresh:
                self._declaration = None
            available = (
                not self._closed
                and self._module is not None
                and self._model_path is not None
            )
            return RecognizerHealth(
                provider_id=self.provider_id,
                available=available,
                healthy=self._failures < 3,
                detail=self._detail if not available else "",
                checked_at_monotonic=monotonic,
                consecutive_failures=self._failures,
            )

    def record(self, succeeded: bool) -> None:
        with self._guard:
            self._failures = 0 if succeeded else self._failures + 1

    def start(self, request: SpeechInputRequest) -> _VoskSession:
        self._probe()
        with self._guard:
            if self._closed:
                raise RuntimeError("this recogniser has been closed")
            module = self._module
            path = self._model_path
            if module is None or path is None:
                raise RuntimeError(self._detail or "the vosk recogniser is unavailable")
            if self._model is None:
                # The model loads on the first capture that needs it, never at
                # service start, and is then kept: loading is the expensive
                # step §25 measures separately from recognition.
                self._model = module.Model(str(path))
            engine = module.KaldiRecognizer(self._model, float(request.sample_rate))
            try:
                engine.SetWords(True)
            except Exception:  # noqa: BLE001 - word timing is an extra, not a need
                pass
        return _VoskSession(engine, request, self.declaration)

    def close(self) -> None:
        with self._guard:
            self._closed = True
            self._model = None
            self._module = None


def local_recognizers(
    *,
    model_directories: Sequence[str] = MODEL_DIRECTORIES,
) -> "RecognizerRegistry":
    """Every real local recogniser, in preference order. Today that is one.

    The tuple stays a tuple so the day a second adapter exists — a
    whisper.cpp binding, a platform API — its position in the order is a
    reviewed line rather than a registry side effect.
    """
    from .recognizer import RecognizerRegistry

    return RecognizerRegistry([
        VoskRecognizer(model_directories=model_directories),
    ])
