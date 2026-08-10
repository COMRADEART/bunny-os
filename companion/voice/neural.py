# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Pocket and Kitten providers behind Bunny's existing local voice contract.

Neither provider imports PyTorch, ONNX Runtime, Pocket TTS or Kitten TTS in the
companion process.  A single allowlisted worker process owns those runtimes and
stays alive between utterances.  Providers exchange bounded JSON and private WAV
paths with it; playback remains in :mod:`companion.voice.audio`.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time
from typing import Any, Callable, Mapping, Sequence

from .chunking import sentence_chunks
from .execution import (
    CancellationSignal,
    ExecutableRefused,
    PersistentJsonWorker,
    PrivateWorkspace,
    WorkerProtocolError,
)
from .pcm import PcmError, probe_wav
from .provider import (
    ProviderDeclaration,
    ProviderHealth,
    ResourceEstimate,
    StreamOutcome,
    SynthesisResult,
    VoiceDescriptor,
)
from .request import SAMPLE_RATES, VoiceRequest

__all__ = [
    "DEFAULT_TTS_PROVIDER",
    "KittenTTSProvider",
    "PocketTTSProvider",
]


DEFAULT_TTS_PROVIDER = "pocket"
NEURAL_WORKER_NAME = "bunny-voice-neural-worker"
HEALTH_TTL_SECONDS = 30.0
DEFAULT_IDLE_UNLOAD_SECONDS = 300.0
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}\Z")
_SHA256 = re.compile(r"^[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class _InstalledVoice:
    descriptor: VoiceDescriptor
    relative_path: str


@dataclass(frozen=True)
class _Installation:
    provider_id: str
    model_id: str
    root: Path
    voices: tuple[_InstalledVoice, ...]
    sample_rate: int
    manifest_digest: str


def _safe_relative(root: Path, raw: Any) -> Path | None:
    if not isinstance(raw, str) or not raw or "\0" in raw:
        return None
    candidate = Path(raw)
    if candidate.is_absolute() or ".." in candidate.parts:
        return None
    try:
        resolved = (root / candidate).resolve(strict=True)
        resolved.relative_to(root.resolve(strict=True))
    except (OSError, RuntimeError, ValueError):
        return None
    return resolved


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_installation(root: Path, provider_id: str, model_id: str) -> tuple[_Installation | None, str, str]:
    """Validate every declared byte before a model can be marked ready."""
    manifest_path = root / "manifest.json"
    try:
        raw = manifest_path.read_bytes()
        if len(raw) > 256 * 1024:
            return None, "MODEL_CORRUPT", "the model manifest is oversized"
        document = json.loads(raw.decode("utf-8"))
    except FileNotFoundError:
        return None, "MODEL_MISSING", f"{manifest_path} is not installed"
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, "MODEL_CORRUPT", f"the model manifest cannot be read: {exc}"
    if not isinstance(document, Mapping) or document.get("schemaVersion") != 1:
        return None, "MODEL_CORRUPT", "the model manifest schema is not supported"
    if document.get("providerId") != provider_id or document.get("modelId") != model_id:
        return None, "MODEL_CORRUPT", "the model manifest names a different provider or model"
    files = document.get("files")
    voices = document.get("voices")
    if not isinstance(files, list) or not files or not isinstance(voices, list) or not voices:
        return None, "MODEL_CORRUPT", "the model manifest has no bounded file and voice inventory"

    validated_files: set[Path] = set()
    for item in files:
        if not isinstance(item, Mapping):
            return None, "MODEL_CORRUPT", "the model file inventory is malformed"
        path = _safe_relative(root, item.get("path"))
        expected_size = item.get("sizeBytes")
        expected_digest = item.get("sha256")
        if path is None or not path.is_file():
            return None, "MODEL_MISSING", f"a required {provider_id} model file is absent"
        if not isinstance(expected_size, int) or expected_size <= 0 or path.stat().st_size != expected_size:
            return None, "MODEL_CORRUPT", f"{path.name} has the wrong size"
        if not isinstance(expected_digest, str) or not _SHA256.match(expected_digest):
            return None, "MODEL_CORRUPT", f"{path.name} has no valid pinned digest"
        try:
            actual = _sha256(path)
        except OSError as exc:
            return None, "MODEL_CORRUPT", f"{path.name} cannot be hashed: {exc}"
        if actual != expected_digest:
            return None, "MODEL_CORRUPT", f"{path.name} failed its SHA-256 check"
        validated_files.add(path)

    installed_voices: list[_InstalledVoice] = []
    for item in voices:
        if not isinstance(item, Mapping):
            return None, "MODEL_CORRUPT", "the voice inventory is malformed"
        voice_id = item.get("voiceId")
        voice_path = _safe_relative(root, item.get("path"))
        if not isinstance(voice_id, str) or not _SAFE_ID.match(voice_id) or voice_path is None:
            return None, "MODEL_CORRUPT", "a voice id or path is invalid"
        if voice_path not in validated_files:
            return None, "MODEL_CORRUPT", f"voice {voice_id!r} has no pinned digest"
        if not voice_path.is_file() or voice_path.stat().st_size <= 0:
            return None, "MODEL_MISSING", f"voice {voice_id!r} is not installed"
        installed_voices.append(_InstalledVoice(
            descriptor=VoiceDescriptor(
                voice_id=voice_id,
                provider_id=provider_id,
                name=str(item.get("name") or voice_id),
                language="en",
                locale="en-US",
                preference=float(item.get("preference", 0.5)),
                default=bool(item.get("default", False)),
            ),
            relative_path=str(item.get("path")),
        ))
    sample_rate = document.get("sampleRate", 24_000)
    if sample_rate not in SAMPLE_RATES:
        return None, "MODEL_CORRUPT", "the model manifest has an unsupported sample rate"
    return _Installation(
        provider_id=provider_id,
        model_id=model_id,
        root=root.resolve(strict=True),
        voices=tuple(installed_voices),
        sample_rate=int(sample_rate),
        manifest_digest=hashlib.sha256(raw).hexdigest(),
    ), "READY", "installed model and voice assets passed their integrity checks"


class _NeuralTTSProvider:
    provider_id = ""
    display_name = ""
    implementation_id = ""
    model_ids: tuple[str, ...] = ()
    default_model_id = ""
    default_directory = ""
    environment_root_name = ""
    supports_rate = False
    memory_estimate = 0
    latency_estimate = 1.0

    def __init__(
        self,
        *,
        resolver: Callable[[str], tuple[str, bool]] | None = None,
        roots: Mapping[str, Sequence[Path]] | None = None,
        worker_factory: Callable[..., Any] | None = None,
        idle_unload_seconds: float = DEFAULT_IDLE_UNLOAD_SECONDS,
    ) -> None:
        from .execution import resolve_executable

        self._resolver = resolver or resolve_executable
        self._roots = {str(key): tuple(Path(item) for item in value) for key, value in (roots or {}).items()}
        self._worker_factory = worker_factory or PersistentJsonWorker
        self._idle_unload_seconds = max(0.0, float(idle_unload_seconds))
        self._executable = ""
        self._trusted = True
        self._runtime_error = ""
        try:
            self._executable, self._trusted = self._resolver(NEURAL_WORKER_NAME)
        except (ExecutableRefused, OSError) as exc:
            self._runtime_error = str(exc)
        self._health: ProviderHealth | None = None
        self._health_checked = 0.0
        self._health_refreshing = False
        self._failures = 0
        self._installations: dict[str, _Installation] = {}
        self._installation_errors: dict[str, tuple[str, str]] = {}
        self._client: Any = None
        self._client_model_id = ""
        self._active_request_id = ""
        self._generation = 0
        self._idle_timer: threading.Timer | None = None
        self._guard = threading.RLock()
        self._closed = False

    @property
    def declaration(self) -> ProviderDeclaration:
        return ProviderDeclaration(
            provider_id=self.provider_id,
            display_name=self.display_name,
            implementation_id=self.implementation_id,
            languages=("en",),
            locales=("en-US", "en-GB"),
            audio_formats=("wav-pcm-s16le",),
            sample_rates=tuple(SAMPLE_RATES),
            supports_synthesis=True,
            # The pinned provider API supports complete synthesis in this
            # milestone.  Pocket's real stream API is not exposed until Bunny's
            # AudioRouter accepts incremental PCM; claiming it here would route
            # into provider-owned playback, which Pocket does not do.
            supports_streaming=False,
            supports_cancellation=True,
            rate_control=self.supports_rate,
            pitch_control=False,
            volume_control=False,
            local=True,
            cost_class="free",
            maximum_privacy_class="secret",
            trusted_resolution=self._trusted,
            models=self.model_ids,
            default_model_id=self.default_model_id,
        )

    def _candidate_roots(self, model_id: str) -> tuple[Path, ...]:
        explicit = self._roots.get(model_id)
        if explicit is not None:
            return tuple(explicit)
        configured = os.environ.get(self.environment_root_name, "").strip()
        candidates: list[Path] = []
        if configured:
            candidates.append(Path(configured))
        candidates.extend((
            Path("/usr/share/bunny-os/voice") / self.default_directory / model_id,
            Path.home() / ".local/share/bunny-os/voice" / self.default_directory / model_id,
        ))
        return tuple(candidates)

    def _installation(self, model_id: str, *, refresh: bool = False) -> tuple[_Installation | None, str, str]:
        model = model_id if model_id in self.model_ids else self.default_model_id
        with self._guard:
            if not refresh and model in self._installations:
                return self._installations[model], "READY", "installed model is cached"
            if not refresh and model in self._installation_errors:
                status, detail = self._installation_errors[model]
                return None, status, detail
        last_status, last_detail = "MODEL_MISSING", f"{self.display_name} model {model!r} is not installed"
        for root in self._candidate_roots(model):
            installation, status, detail = _read_installation(root, self.provider_id, model)
            if installation is not None:
                with self._guard:
                    self._installations[model] = installation
                    self._installation_errors.pop(model, None)
                return installation, status, detail
            if status != "MODEL_MISSING" or root.exists():
                last_status, last_detail = status, detail
                break
        with self._guard:
            self._installation_errors[model] = (last_status, last_detail)
        return None, last_status, last_detail

    def _new_client(self) -> Any:
        return self._worker_factory(
            self._executable,
            ("--provider", self.provider_id),
            environment={
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
                "BUNNY_VOICE_NETWORK": "disabled",
            },
        )

    def _voice(self, installation: _Installation, voice_id: str = "") -> _InstalledVoice | None:
        if voice_id:
            for voice in installation.voices:
                if voice.descriptor.voice_id == voice_id:
                    return voice
            return None
        defaults = [voice for voice in installation.voices if voice.descriptor.default]
        return (defaults or list(installation.voices))[0] if installation.voices else None

    def _ensure_worker(
        self,
        installation: _Installation,
        voice: _InstalledVoice,
        *,
        cancellation: CancellationSignal | None = None,
    ) -> tuple[Any | None, str]:
        with self._guard:
            if self._closed:
                return None, "the provider is closed"
            if self._client is None or self._client_model_id != installation.model_id:
                if self._client is not None:
                    self._client.close()
                self._client = self._new_client()
                self._client_model_id = installation.model_id
            client = self._client
        initialization_finished = threading.Event()
        cancellation_watcher: threading.Thread | None = None
        if cancellation is not None:
            def _cancel_initialization() -> None:
                while not initialization_finished.wait(0.025):
                    if not cancellation.cancelled:
                        continue
                    with self._guard:
                        active = self._client is client
                        if active:
                            self._client = None
                            self._client_model_id = ""
                    if active:
                        try:
                            client.stop()
                        except Exception:  # noqa: BLE001 - cancel stays bounded
                            pass
                    return

            cancellation_watcher = threading.Thread(
                target=_cancel_initialization,
                name=f"bunny-{self.provider_id}-initialization-cancel",
                daemon=True,
            )
            cancellation_watcher.start()
        try:
            answer = client.call({
                "op": "initialize",
                "providerId": self.provider_id,
                "modelId": installation.model_id,
                "modelRoot": str(installation.root),
                "manifestDigest": installation.manifest_digest,
                "voiceId": voice.descriptor.voice_id,
                "voicePath": voice.relative_path,
            }, timeout_seconds=120.0 if self.provider_id == "pocket" else 45.0)
        except (WorkerProtocolError, OSError, ValueError) as exc:
            with self._guard:
                if self._client is client:
                    self._client = None
                    self._client_model_id = ""
            try:
                client.close()
            except Exception:  # noqa: BLE001 - a failed worker is already unavailable
                pass
            return None, (
                cancellation.reason
                if cancellation is not None and cancellation.cancelled else str(exc)
            )
        finally:
            initialization_finished.set()
            if cancellation_watcher is not None:
                cancellation_watcher.join(timeout=0.25)
        if cancellation is not None and cancellation.cancelled:
            return None, cancellation.reason or "cancelled"
        if not answer.get("ready") or answer.get("providerId") != self.provider_id:
            detail = str(answer.get("detail") or "the neural worker did not initialize the requested provider")
            return None, detail
        self._schedule_idle_unload()
        return client, ""

    def _schedule_idle_unload(self) -> None:
        with self._guard:
            if self._idle_timer is not None:
                self._idle_timer.cancel()
                self._idle_timer = None
            if self._idle_unload_seconds <= 0 or self._active_request_id:
                return
            timer = threading.Timer(self._idle_unload_seconds, self._unload_if_idle)
            timer.daemon = True
            self._idle_timer = timer
            timer.start()

    def _unload_if_idle(self) -> None:
        with self._guard:
            if self._active_request_id:
                return
            client = self._client
            self._client = None
            self._client_model_id = ""
            self._idle_timer = None
        if client is not None:
            try:
                client.close()
            except Exception:  # noqa: BLE001
                pass

    def _compute_health(
        self,
        now: float,
        *,
        refresh: bool,
        initialize_worker: bool,
    ) -> ProviderHealth:
        if not self._executable:
            health = ProviderHealth(
                provider_id=self.provider_id,
                available=False,
                healthy=False,
                detail=self._runtime_error or "the isolated Bunny neural voice worker is not installed",
                status="RUNTIME_MISSING",
                checked_at_monotonic=now,
                consecutive_failures=self._failures,
            )
        else:
            installation, status, detail = self._installation(self.default_model_id, refresh=refresh)
            if installation is None:
                health = ProviderHealth(
                    provider_id=self.provider_id,
                    available=False,
                    healthy=False,
                    detail=detail,
                    status=status,
                    checked_at_monotonic=now,
                    consecutive_failures=self._failures,
                )
            else:
                voice = self._voice(installation)
                if voice is None:
                    client, worker_error = None, "no default voice is installed"
                    ready = False
                elif initialize_worker:
                    client, worker_error = self._ensure_worker(installation, voice)
                    ready = client is not None
                else:
                    # Login readiness validates every pinned byte but does not
                    # import either inference stack. Keeping Pocket and Kitten
                    # resident together would spend over a gigabyte before the
                    # user had asked Bunny to speak. A selected provider is
                    # initialized synchronously on the dedicated voice worker.
                    with self._guard:
                        client = self._client
                        ready = (
                            client is not None
                            and self._client_model_id == installation.model_id
                        )
                    worker_error = ""
                health = ProviderHealth(
                    provider_id=self.provider_id,
                    available=ready,
                    healthy=ready or not initialize_worker,
                    detail=(
                        f"{self.display_name} worker, {installation.model_id} model and "
                        f"{voice.descriptor.name if voice else 'voice'} initialized locally"
                        if ready else (
                            worker_error if initialize_worker else
                            f"{self.display_name} model and prepared voice passed integrity checks; "
                            "the isolated worker will load them on first use"
                        )
                    ),
                    status=(
                        "READY" if ready else
                        ("WORKER_FAILED" if initialize_worker else "MODEL_VERIFIED")
                    ),
                    checked_at_monotonic=now,
                    consecutive_failures=self._failures,
                )
        with self._guard:
            self._health = health
            self._health_checked = now
            self._health_refreshing = False
        return health

    def _background_health(self, now: float) -> None:
        try:
            self._compute_health(now, refresh=False, initialize_worker=False)
        except Exception as exc:  # noqa: BLE001 - readiness must not kill the service
            with self._guard:
                self._health = ProviderHealth(
                    provider_id=self.provider_id,
                    available=False,
                    healthy=False,
                    detail=f"the readiness probe failed: {type(exc).__name__}",
                    status="WORKER_FAILED",
                    checked_at_monotonic=now,
                    consecutive_failures=self._failures,
                )
                self._health_checked = now
                self._health_refreshing = False

    def health(self, *, monotonic: float = 0.0, refresh: bool = False) -> ProviderHealth:
        """Return readiness without ever loading a model on the caller's thread.

        ``VoiceService`` calls this during companion startup, on the graphical
        session's critical path. An ordinary observation starts one daemon
        integrity probe and reports ``INITIALIZING``; it does not import an
        inference runtime or make both neural models resident. Explicit
        diagnostic refreshes remain synchronous, which makes image acceptance
        able to prove that READY means the model and prepared voice really
        initialized.
        """
        now = float(monotonic or time.monotonic())
        if refresh:
            return self._compute_health(now, refresh=True, initialize_worker=True)
        start_probe = False
        with self._guard:
            cached = self._health
            if cached is not None and now - self._health_checked < HEALTH_TTL_SECONDS:
                return cached
            if not self._health_refreshing and not self._closed:
                self._health_refreshing = True
                start_probe = True
        if start_probe:
            thread = threading.Thread(
                target=self._background_health,
                args=(now,),
                name=f"bunny-{self.provider_id}-readiness",
                daemon=True,
            )
            thread.start()
        if cached is not None:
            # Keep the last measured truth while it is refreshed. Marking a
            # ready provider unavailable every TTL would make normal speech
            # fall down the fallback ladder for no failure at all.
            return cached
        return ProviderHealth(
            provider_id=self.provider_id,
            available=False,
            healthy=True,
            detail=f"{self.display_name} is verifying its local model and prepared voice",
            status="INITIALIZING",
            checked_at_monotonic=now,
            consecutive_failures=self._failures,
        )

    def model_health(self, *, refresh: bool = False) -> list[dict[str, Any]]:
        reports: list[dict[str, Any]] = []
        for model_id in self.model_ids:
            with self._guard:
                cached = self._installations.get(model_id)
                cached_error = self._installation_errors.get(model_id)
                verifying = self._health_refreshing and model_id == self.default_model_id
            if not refresh and cached is not None:
                installation, status, detail = (
                    cached,
                    "READY",
                    "installed model assets passed their integrity checks",
                )
            elif not refresh and cached_error is not None:
                installation = None
                status, detail = cached_error
            elif not refresh and verifying:
                installation, status, detail = (
                    None,
                    "INITIALIZING",
                    "model and prepared voice integrity checks are still running",
                )
            else:
                installation, status, detail = self._installation(model_id, refresh=refresh)
            reports.append({
                "modelId": model_id,
                "installed": installation is not None,
                "status": status,
                "detail": detail,
            })
        return reports

    def inventory(self) -> Sequence[VoiceDescriptor]:
        voices: list[VoiceDescriptor] = []
        for model_id in self.model_ids:
            with self._guard:
                installation = self._installations.get(model_id)
                known_missing = model_id in self._installation_errors
                verifying = self._health_refreshing and model_id == self.default_model_id
            if installation is None and not known_missing and not verifying:
                installation, _status, _detail = self._installation(model_id)
            if installation is not None:
                voices.extend(voice.descriptor for voice in installation.voices)
        # Stable de-duplication when multiple Kitten model sizes carry the same
        # built-in voices.
        unique: dict[str, VoiceDescriptor] = {}
        for voice in voices:
            unique.setdefault(voice.voice_id, voice)
        return tuple(unique.values())

    def estimate(self, request: VoiceRequest) -> ResourceEstimate:
        return ResourceEstimate(
            memory_bytes=self.memory_estimate,
            temporary_bytes=max(256 * 1024, len(request.speech_text) * 24_000),
            cpu_share=2.0,
            expected_latency_seconds=self.latency_estimate,
        )

    def _model_for_request(self, request: VoiceRequest) -> str:
        if request.provider_id == self.provider_id and request.model_id in self.model_ids:
            return request.model_id
        return self.default_model_id

    def _voice_for_request(self, request: VoiceRequest) -> str:
        return request.voice_id if request.provider_id == self.provider_id else ""

    def synthesize(
        self,
        request: VoiceRequest,
        workspace: PrivateWorkspace,
        *,
        cancellation: CancellationSignal | None = None,
    ) -> SynthesisResult:
        started = time.monotonic()
        model_id = self._model_for_request(request)
        installation, _status, detail = self._installation(model_id)
        voice = self._voice(installation, self._voice_for_request(request)) if installation else None
        if installation is None or voice is None:
            return self._failure(request, started, detail or "the selected voice is not installed")

        with self._guard:
            self._generation += 1
            generation = f"{request.request_id}.{self._generation}"
            self._active_request_id = request.request_id
            if self._idle_timer is not None:
                self._idle_timer.cancel()
                self._idle_timer = None
        client, detail = self._ensure_worker(
            installation, voice, cancellation=cancellation,
        )
        if client is None:
            if cancellation is None or not cancellation.cancelled:
                self._record_failure()
            with self._guard:
                if self._active_request_id == request.request_id:
                    self._active_request_id = ""
            self._schedule_idle_unload()
            return self._failure(request, started, detail)
        if cancellation is not None and cancellation.cancelled:
            with self._guard:
                if self._active_request_id == request.request_id:
                    self._active_request_id = ""
            self._schedule_idle_unload()
            return self._failure(request, started, cancellation.reason or "cancelled")
        output = workspace.file(f"neural-{self._generation}", suffix=".wav")
        chunks = sentence_chunks(request.speech_text)
        call_finished = threading.Event()
        cancellation_watcher: threading.Thread | None = None
        if cancellation is not None:
            # ``PersistentJsonWorker.call`` is intentionally blocking and
            # serial while the model owns its tensors.  A cancellation flag by
            # itself would therefore only be noticed after inference returned.
            # This watcher turns the one-way flag into termination of the
            # exact resident client/generation, which wakes the blocked call,
            # reaps the child and prevents its output from reaching playback.
            def _watch_cancellation() -> None:
                while not call_finished.wait(0.025):
                    if not cancellation.cancelled:
                        continue
                    with self._guard:
                        active = (
                            self._active_request_id == request.request_id
                            and self._client is client
                        )
                        if active:
                            self._client = None
                            self._client_model_id = ""
                            self._active_request_id = ""
                    if active:
                        try:
                            client.stop()
                        except Exception:  # noqa: BLE001 - cancel stays bounded
                            pass
                    return

            cancellation_watcher = threading.Thread(
                target=_watch_cancellation,
                name=f"bunny-{self.provider_id}-cancel-{request.request_id}",
                daemon=True,
            )
            cancellation_watcher.start()
        try:
            answer = client.call({
                "op": "synthesize",
                "providerId": self.provider_id,
                "modelId": installation.model_id,
                "generationId": generation,
                "requestId": request.request_id,
                "voiceId": voice.descriptor.voice_id,
                "voicePath": voice.relative_path,
                "chunks": list(chunks),
                "speakingRate": request.speaking_rate,
                "sampleRate": request.sample_rate,
                "outputPath": str(output),
            }, timeout_seconds=max(15.0, min(180.0, 12.0 + len(request.speech_text) / 12.0)))
        except (WorkerProtocolError, OSError, ValueError) as exc:
            if cancellation is None or not cancellation.cancelled:
                self._record_failure()
            return self._failure(
                request, started,
                cancellation.reason if cancellation is not None and cancellation.cancelled else str(exc),
                voice_id=voice.descriptor.voice_id,
            )
        finally:
            call_finished.set()
            if cancellation_watcher is not None:
                cancellation_watcher.join(timeout=0.25)
            with self._guard:
                if self._active_request_id == request.request_id:
                    self._active_request_id = ""
            self._schedule_idle_unload()

        if cancellation is not None and cancellation.cancelled:
            return self._failure(
                request, started, cancellation.reason or "cancelled",
                voice_id=voice.descriptor.voice_id,
            )
        if answer.get("generationId") != generation:
            self._record_failure()
            return self._failure(request, started, "the neural worker returned stale generation audio")
        if not answer.get("succeeded"):
            self._record_failure()
            return self._failure(
                request, started, str(answer.get("detail") or "neural synthesis failed"),
                voice_id=voice.descriptor.voice_id,
            )
        try:
            probe = probe_wav(output)
        except (OSError, PcmError) as exc:
            self._record_failure()
            return self._failure(request, started, f"the neural audio artifact is invalid: {exc}")
        if probe.frame_count <= 0 or probe.sample_rate != request.sample_rate:
            self._record_failure()
            return self._failure(request, started, "the neural worker returned empty or wrong-rate audio")

        self._record_success()
        degradations: list[str] = []
        if request.provider_id and request.provider_id != self.provider_id:
            degradations.append(f"fallback from {request.provider_id} to {self.provider_id}")
        if not self.supports_rate and request.speaking_rate != 1.0:
            degradations.append(f"{self.display_name} does not expose speech-rate control")
        return SynthesisResult(
            request_id=request.request_id,
            provider_id=self.provider_id,
            implementation_id=self.implementation_id,
            voice_id=voice.descriptor.voice_id,
            succeeded=True,
            audio_path=str(output),
            audio_format="wav-pcm-s16le",
            sample_rate=probe.sample_rate,
            channels=probe.channels,
            frame_count=probe.frame_count,
            duration_seconds=probe.duration_seconds,
            synthesis_seconds=time.monotonic() - started,
            degradations=tuple(degradations),
            detail=f"synthesized locally by {self.display_name} ({installation.model_id})",
        )

    def _failure(
        self,
        request: VoiceRequest,
        started: float,
        detail: str,
        *,
        voice_id: str = "",
    ) -> SynthesisResult:
        return SynthesisResult(
            request_id=request.request_id,
            provider_id=self.provider_id,
            implementation_id=self.implementation_id,
            voice_id=voice_id,
            succeeded=False,
            synthesis_seconds=max(0.0, time.monotonic() - started),
            detail=detail or f"{self.display_name} is unavailable",
        )

    def stream(
        self,
        request: VoiceRequest,
        *,
        cancellation: CancellationSignal | None = None,
        on_started: Callable[[], None] | None = None,
    ) -> StreamOutcome:
        del cancellation, on_started
        return StreamOutcome(
            request_id=request.request_id,
            provider_id=self.provider_id,
            implementation_id=self.implementation_id,
            voice_id="",
            succeeded=False,
            detail=(
                f"{self.display_name} streaming is not wired to Bunny AudioRouter in this build; "
                "complete local synthesis remains available"
            ),
        )

    def _record_failure(self) -> None:
        with self._guard:
            self._failures += 1
            self._health = None
            self._health_checked = 0.0

    def _record_success(self) -> None:
        with self._guard:
            self._failures = 0

    def cancel(self, request_id: str) -> bool:
        with self._guard:
            if not request_id or self._active_request_id != request_id:
                return False
            client = self._client
            self._client = None
            self._client_model_id = ""
            self._active_request_id = ""
        if client is not None:
            try:
                client.stop()
            except Exception:  # noqa: BLE001 - cancellation must remain bounded
                pass
        return True

    def close(self) -> None:
        with self._guard:
            if self._closed:
                return
            self._closed = True
            timer = self._idle_timer
            self._idle_timer = None
            client = self._client
            self._client = None
            self._active_request_id = ""
        if timer is not None:
            timer.cancel()
        if client is not None:
            try:
                client.close()
            except Exception:  # noqa: BLE001
                pass


class PocketTTSProvider(_NeuralTTSProvider):
    provider_id = "pocket"
    display_name = "Pocket TTS"
    implementation_id = "pocket-tts/2.1.0-bunny-worker-1"
    model_ids = ("english",)
    default_model_id = "english"
    default_directory = "pocket"
    environment_root_name = "BUNNY_POCKET_TTS_ROOT"
    supports_rate = False
    memory_estimate = 1024 * 1024 * 1024
    latency_estimate = 1.5


class KittenTTSProvider(_NeuralTTSProvider):
    provider_id = "kitten"
    display_name = "Kitten TTS"
    implementation_id = "kitten-tts/0.8.1-bunny-worker-1"
    model_ids = ("nano-int8", "nano", "micro", "mini")
    default_model_id = "nano-int8"
    default_directory = "kitten"
    environment_root_name = "BUNNY_KITTEN_TTS_ROOT"
    supports_rate = True
    memory_estimate = 192 * 1024 * 1024
    latency_estimate = 0.6
