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

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import threading
from typing import Any, Callable, Sequence

from ..ownership import owner_is_trusted
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
    "STT_MODEL_CORRUPT",
    "STT_MODEL_MISSING",
    "STT_PROVIDER_FAILED",
    "STT_READY",
    "STT_RUNTIME_MISSING",
    "VoskRecognizer",
    "local_recognizers",
]

#: Every place a recognition model may live, in search order. A fixed tuple —
#: not configuration, not a request field, not an environment variable —
#: because a writable model path is code injection with extra steps: a model
#: is data a native library parses, and pointing that parser at an attacker's
#: file is handing it the process.
#:
#: The immutable system location first, because a model the image ships is a
#: model the build reviewed; then an administrator-managed mutable location;
#: then the user's own data location. A setting selects only a model *name*,
#: never a path, so this precedence cannot be redirected through IPC.
MODEL_DIRECTORIES: tuple[str, ...] = (
    "/usr/share/bunny-os/speech-models",
    "/var/lib/bunny-os/voice/models",
    "~/.local/share/bunny-os/speech-models",
)

STT_READY = "STT_READY"
STT_MODEL_MISSING = "STT_MODEL_MISSING"
STT_MODEL_CORRUPT = "STT_MODEL_CORRUPT"
STT_RUNTIME_MISSING = "STT_RUNTIME_MISSING"
STT_PROVIDER_FAILED = "STT_PROVIDER_FAILED"

_MODEL_MANIFEST = ".bunny-model.json"
_REQUIRED_MODEL_FILES: tuple[str, ...] = (
    "am/final.mdl",
    "conf/mfcc.conf",
    "conf/model.conf",
    "graph/phones/word_boundary.int",
)
_REQUIRED_IVECTOR_FILES: tuple[str, ...] = (
    "ivector/final.dubm",
    "ivector/final.ie",
    "ivector/final.mat",
    "ivector/global_cmvn.stats",
    "ivector/online_cmvn.conf",
    "ivector/splice.conf",
)
_SHA256 = re.compile(r"^[a-f0-9]{64}$")

#: Model directory names Vosk publishes look like
#: ``vosk-model-small-en-us-0.15``. The language is the first token after the
#: prefixes; the locale is that token plus the region when one follows.
_MODEL_NAME = re.compile(
    r"^vosk-model(?:-small)?-(?P<language>[a-z]{2,3})(?:-(?P<region>[a-z]{2}))?"
)

#: How many samples of silence-free audio the session keeps per partial
#: comparison. Only the *text* is compared; audio never accumulates here.
_SAMPLE_RATES = (8_000, 16_000, 22_050, 44_100, 48_000)


def _path_safe(path: Path, *, require_directory: bool | None = None) -> tuple[bool, str]:
    """Whether a model-tree entry is one this process may trust.

    Ownership and permissions, checked before anything is parsed: a model
    entry writable by another account is data another account chooses.
    Root-owned is accepted — the system location is root's — and so is our own
    uid; nothing else is, except the one case
    :mod:`companion.ownership` documents, where this process is inside a user
    namespace that does not map root and the kernel therefore reports every
    root-owned file as the overflow uid. That is the configuration the
    companion service actually runs in, and refusing it disabled speech input
    on every shipped image.
    """
    try:
        info = path.lstat()
    except OSError as exc:
        return False, f"could not be inspected: {exc.strerror or exc}"
    if stat.S_ISLNK(info.st_mode):
        return False, "is a symbolic link"
    if require_directory is True and not stat.S_ISDIR(info.st_mode):
        return False, "is not a directory"
    if require_directory is False and not stat.S_ISREG(info.st_mode):
        return False, "is not a regular file"
    if require_directory is None and not (
        stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)
    ):
        return False, "is neither a regular file nor a directory"
    if hasattr(os, "getuid") and not owner_is_trusted(info.st_uid):
        return False, f"is owned by uid {info.st_uid} rather than root or this user"
    if os.name == "posix" and info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        return False, "is writable by group or other"
    return True, ""


def _directory_safe(path: Path) -> tuple[bool, str]:
    """Compatibility name for the top-level model-directory trust check."""
    return _path_safe(path, require_directory=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _manifest_safe(model: Path, manifest_path: Path) -> tuple[bool, str]:
    """Validate every byte named by a bundled Bunny model manifest."""
    try:
        if manifest_path.stat().st_size > 1024 * 1024:
            return False, f"{_MODEL_MANIFEST} exceeds its 1 MiB bound"
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return False, f"{_MODEL_MANIFEST} cannot be read: {exc}"
    if not isinstance(document, dict) or document.get("schemaVersion") != 1:
        return False, f"{_MODEL_MANIFEST} has an unsupported schema"
    if document.get("modelId") != model.name:
        return False, f"{_MODEL_MANIFEST} names a different model"
    records = document.get("files")
    if not isinstance(records, list) or not records:
        return False, f"{_MODEL_MANIFEST} contains no file inventory"

    declared: dict[str, tuple[int, str]] = {}
    for record in records:
        if not isinstance(record, dict):
            return False, f"{_MODEL_MANIFEST} contains a non-object file record"
        relative = record.get("path")
        size = record.get("sizeBytes")
        digest = record.get("sha256")
        if not isinstance(relative, str) or not relative or "\\" in relative:
            return False, f"{_MODEL_MANIFEST} contains an invalid relative path"
        parts = Path(relative).parts
        if Path(relative).is_absolute() or any(part in ("", ".", "..") for part in parts):
            return False, f"{_MODEL_MANIFEST} contains an escaping relative path"
        if relative in declared:
            return False, f"{_MODEL_MANIFEST} names {relative!r} more than once"
        if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
            return False, f"{_MODEL_MANIFEST} has an invalid size for {relative!r}"
        if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
            return False, f"{_MODEL_MANIFEST} has an invalid digest for {relative!r}"
        declared[relative] = (size, digest)

    actual = {
        item.relative_to(model).as_posix()
        for item in model.rglob("*")
        if item.is_file() and item != manifest_path
    }
    if actual != set(declared):
        missing = sorted(set(declared) - actual)
        extra = sorted(actual - set(declared))
        summary: list[str] = []
        if missing:
            summary.append("missing " + ", ".join(missing[:3]))
        if extra:
            summary.append("unexpected " + ", ".join(extra[:3]))
        return False, f"{_MODEL_MANIFEST} inventory differs from disk: " + "; ".join(summary)

    for relative, (expected_size, expected_digest) in declared.items():
        target = model / relative
        try:
            observed_size = target.stat().st_size
        except OSError as exc:
            return False, f"{relative} cannot be inspected: {exc}"
        if observed_size != expected_size:
            return False, f"{relative} has size {observed_size}, expected {expected_size}"
        try:
            observed_digest = _sha256(target)
        except OSError as exc:
            return False, f"{relative} cannot be hashed: {exc}"
        if observed_digest != expected_digest:
            return False, f"{relative} failed its SHA-256 integrity check"
    return True, ""


def _model_safe(path: Path) -> tuple[bool, str]:
    """Validate trust, required Vosk structure, and optional pinned hashes."""
    safe, reason = _directory_safe(path)
    if not safe:
        return False, reason
    try:
        entries = list(path.rglob("*"))
    except OSError as exc:
        return False, f"the model tree could not be inspected: {exc}"
    for item in entries:
        safe, reason = _path_safe(item)
        if not safe:
            return False, f"{item.relative_to(path).as_posix()}: {reason}"

    for relative in _REQUIRED_MODEL_FILES:
        target = path / relative
        try:
            if not target.is_file() or target.stat().st_size <= 0:
                return False, f"required model file {relative} is missing or empty"
        except OSError:
            return False, f"required model file {relative} cannot be inspected"

    hclg = path / "graph/HCLG.fst"
    split_graph = (path / "graph/HCLr.fst", path / "graph/Gr.fst")
    try:
        has_hclg = hclg.is_file() and hclg.stat().st_size > 0
        has_split_graph = all(item.is_file() and item.stat().st_size > 0 for item in split_graph)
    except OSError:
        has_hclg = has_split_graph = False
    if not (has_hclg or has_split_graph):
        return False, "the decoding graph is missing or empty"

    if (path / "ivector").exists():
        for relative in _REQUIRED_IVECTOR_FILES:
            target = path / relative
            try:
                if not target.is_file() or target.stat().st_size <= 0:
                    return False, f"required i-vector file {relative} is missing or empty"
            except OSError:
                return False, f"required i-vector file {relative} cannot be inspected"

    manifest = path / _MODEL_MANIFEST
    if manifest.exists():
        return _manifest_safe(path, manifest)
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
    preferred_model_id: str = "",
) -> tuple[Path | None, str, str, str]:
    """The first usable model, or the reason there is none.

    Returns ``(path, language, locale, detail)``. The search is breadth-one:
    each trusted directory's immediate children, name-matched and
    permission-checked, first hit wins. Nothing recurses into unexpected
    places and nothing follows a link out of the tree.
    """
    path, language, locale, _status, detail = _discover_model_status(
        directories, preferred_model_id
    )
    return path, language, locale, detail


def _discover_model_status(
    directories: Sequence[str] = MODEL_DIRECTORIES,
    preferred_model_id: str = "",
) -> tuple[Path | None, str, str, str, str]:
    """Detailed model discovery including a machine-readable readiness code."""
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
            if preferred_model_id and child.name != preferred_model_id:
                continue
            safe, reason = _model_safe(child)
            if not safe:
                problems.append(f"{child.name}: {reason}")
                continue
            language = match.group("language")
            region = match.group("region")
            locale = f"{language}-{region.upper()}" if region else ""
            return child, language, locale, STT_READY, ""
    if problems:
        return None, "", "", STT_MODEL_CORRUPT, "; ".join(problems[:4])
    if preferred_model_id:
        return None, "", "", STT_MODEL_MISSING, (
            f"the selected local model {preferred_model_id!r} is not installed in a trusted model directory"
        )
    return None, "", "", STT_MODEL_MISSING, (
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
            # The worker's final non-blocking drain has no activity-detector
            # position and therefore passes zero. It may add frames, but it
            # must not erase the real end position accumulated while capture
            # was live; doing so made every bridge transcript report 0 ms.
            if position_seconds > 0:
                if not self._first_position:
                    self._first_position = position_seconds
                self._last_position = max(self._last_position, position_seconds)
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
            engine = self._engine
            self._engine = None
            self._segments.clear()
            self._confidences.clear()
        close = getattr(engine, "close", None)
        if callable(close):
            close()


class VoskRecognizer:
    """Vosk as a :class:`companion.speech.recognizer.SpeechRecognizer`.

    ``importer`` is injectable so the deterministic suite can drive this
    adapter — declaration, health, session lifecycle — with a scripted engine,
    while the Linux validation drives it with Fedora's packaged native library.
    Production passes nothing and gets the narrow local C-API binding.
    """

    provider_id = "vosk"

    def __init__(
        self,
        *,
        model_directories: Sequence[str] = MODEL_DIRECTORIES,
        preferred_model_id: str = "",
        importer: Callable[[], Any] | None = None,
    ) -> None:
        self._model_directories = tuple(model_directories)
        self._preferred_model_id = preferred_model_id
        self._importer = importer or self._import_vosk
        self._guard = threading.RLock()
        self._probed = False
        self._module: Any = None
        self._model: Any = None
        self._model_path: Path | None = None
        self._language = ""
        self._locale = ""
        self._detail = ""
        self._status_code = STT_RUNTIME_MISSING
        self._failures = 0
        self._closed = False
        self._declaration: RecognizerDeclaration | None = None

    @staticmethod
    def _import_vosk() -> Any:
        from . import vosk_runtime  # noqa: PLC0415 - native load stays lazy

        # Importing Bunny's wrapper proves only that the wrapper ships. Probe
        # the distribution library here so a missing RPM is reported before a
        # microphone opens rather than becoming a first-capture exception.
        vosk_runtime.probe()
        vosk_runtime.SetLogLevel(-1)
        return vosk_runtime

    # ----------------------------------------------------------------- #

    def _probe(self, *, refresh: bool = False) -> None:
        with self._guard:
            if self._probed and not refresh:
                return
            self._probed = True
            self._detail = ""
            old_path = self._model_path
            self._model_path = None
            self._language = ""
            self._locale = ""
            if self._module is None:
                try:
                    self._module = self._importer()
                except Exception as exc:  # noqa: BLE001 - absence is a health answer
                    self._module = None
                    self._status_code = STT_RUNTIME_MISSING
                    self._detail = f"the Vosk runtime is unavailable: {exc}"
                    if old_path is not None:
                        self._model = None
                    return
            path, language, locale, status_code, detail = _discover_model_status(
                self._model_directories, self._preferred_model_id)
            self._status_code = status_code
            if path is None:
                self._detail = detail
                if old_path is not None:
                    self._model = None
                return
            if old_path is not None and old_path != path:
                self._model = None
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
            healthy = self._failures < 3
            status_code = (
                STT_READY if available and healthy
                else STT_PROVIDER_FAILED if available
                else self._status_code
            )
            detail = self._detail if not available else ""
            if available and not healthy:
                detail = f"the Vosk provider failed {self._failures} consecutive captures"
            return RecognizerHealth(
                provider_id=self.provider_id,
                available=available,
                healthy=healthy,
                detail=detail,
                status_code=status_code,
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
            model = self._model
            self._model = None
            self._module = None
        close = getattr(model, "close", None)
        if callable(close):
            close()


def local_recognizers(
    *,
    model_directories: Sequence[str] = MODEL_DIRECTORIES,
    preferred_model_id: str = "",
) -> "RecognizerRegistry":
    """Every real local recogniser, in preference order. Today that is one.

    The tuple stays a tuple so the day a second adapter exists — a
    whisper.cpp binding, a platform API — its position in the order is a
    reviewed line rather than a registry side effect.
    """
    from .recognizer import RecognizerRegistry

    return RecognizerRegistry([
        VoskRecognizer(
            model_directories=model_directories,
            preferred_model_id=preferred_model_id,
        ),
    ])
