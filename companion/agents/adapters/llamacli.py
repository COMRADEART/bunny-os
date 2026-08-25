# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The genuine llama-cli adapter: an allowlisted subprocess, reaped or dead.

The §4 "explicit local subprocess runtime". The execution discipline is the
voice runtime's, restated inside this package because the import boundary
keeps each subsystem's subprocess law next to its subprocesses:

* the program is one of :data:`ALLOWED_PROGRAMS`, resolved against
  :data:`TRUSTED_DIRECTORIES` only — never ``PATH``, never a configured path;
* the model is a *file name* (no separators) resolved against the fixed
  trusted model directories, the same two-tuple arrangement the speech
  runtime uses for recognizer models, refused when loose-moded;
* argv is an argument array built here; nothing from a provider, a model or a
  request is ever a program name or a flag;
* the environment is a fixed allowlist, not an inheritance;
* termination escalates terminate → kill on a watchdog that watches both the
  cancellation signal and the deadline, and the exit status is always reaped
  — a zombie is a gate failure (§24 counts children), so ``finally`` owns the
  reap.

This adapter serves the prompt-based structured-output path the planner uses:
the JSON instruction is in the prompt, ``parse_structured`` validates the text,
and one bounded repair round handles malformation. ``llama-cli`` has no native
grammar hook, so unlike the server adapters it passes no schema to the engine --
but the planner never asked for one, and the same llama.cpp engine whose server
adapter (``llamacpp``) claims structured support is claimed here for the prompt
path. ``False`` here routed every local question to a blocked task instead of to
the model. Usage is byte-estimated and labelled so; parsing timing lines off
stderr would be a report built on a format nobody promised.
"""

from __future__ import annotations

import os
import stat
import subprocess
import threading
import codecs
from pathlib import Path
from typing import Any, Callable, Mapping

from ..adapter import (
    CancellationSignal,
    GenerationOutcome,
    ModelListing,
    ProbeResult,
    StreamEventFactory,
    unavailable_probe,
)
from ..credentials import Secret
from ..request import GenerationRequest
from ..stream import MAX_DELTA_BYTES, StreamEvent
from .common import chunked, estimated_usage

__all__ = ["LlamaCliAdapter", "ALLOWED_PROGRAMS", "TRUSTED_DIRECTORIES", "trusted_model_directories"]

ALLOWED_PROGRAMS = ("llama-cli",)
TRUSTED_DIRECTORIES = ("/usr/bin", "/bin")
_GRACE_SECONDS = 2.0
_KILL_GRACE_SECONDS = 3.0
_MAX_STDERR_BYTES = 8 * 1024
_MAX_MODELS_LISTED = 16


def trusted_model_directories() -> tuple[Path, ...]:
    """The fixed pair; nothing configurable, nothing writable by others."""
    return (
        Path.home() / ".local" / "share" / "bunny-os" / "agent-models",
        Path("/usr/share/bunny-os/agent-models"),
    )


def _resolve_program(name: str) -> tuple[str, str]:
    """Return (path, "") or ("", refusal)."""
    if name not in ALLOWED_PROGRAMS:
        return "", f"program {name!r} is not one of {ALLOWED_PROGRAMS}"
    if os.name != "posix":
        return "", "trusted-directory resolution is a POSIX arrangement; unavailable here"
    for directory in TRUSTED_DIRECTORIES:
        candidate = Path(directory) / name
        try:
            info = os.stat(candidate)
        except OSError:
            continue
        if not stat.S_ISREG(info.st_mode):
            continue
        if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            return "", f"{candidate} is group- or world-writable; a writable binary is nobody's binary"
        return str(candidate), ""
    return "", f"{name} is not present in {TRUSTED_DIRECTORIES}"


def _resolve_model(model_id: str) -> tuple[Path | None, str]:
    if not model_id:
        return None, "no model file is configured"
    if "/" in model_id or "\\" in model_id or model_id.startswith("."):
        return None, "a model is named by file name, not by path"
    for directory in trusted_model_directories():
        candidate = directory / model_id
        try:
            info = os.stat(candidate)
        except OSError:
            continue
        if not stat.S_ISREG(info.st_mode):
            continue
        if os.name == "posix" and info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            return None, f"{candidate} is group- or world-writable; refused"
        return candidate, ""
    return None, (
        f"model {model_id!r} is not present in "
        f"{tuple(str(item) for item in trusted_model_directories())}"
    )


def _child_environment() -> dict[str, str]:
    return {
        "PATH": ":".join(TRUSTED_DIRECTORIES),
        "HOME": str(Path.home()),
        "LC_ALL": "C.UTF-8",
    }


def _prompt_from(request: GenerationRequest) -> str:
    """A labelled flat prompt: llama-cli applies no template, so none is faked."""
    sections = []
    for message in request.messages:
        sections.append(f"[{message.role}]\n{message.content}")
    sections.append("[assistant]\n")
    return "\n\n".join(sections)


class LlamaCliAdapter:
    #: Prompt-based, not grammar-based. The planner puts the JSON instruction
    #: in the prompt and validates the text with ``parse_structured`` plus one
    #: repair round, so a plain text completion is enough -- the same engine's
    #: server adapter (``llamacpp``) claims this for its native grammar path,
    #: and the CLI path claims it for the prompt path. ``False`` here routed
    #: every local question to a blocked task instead of to the model.
    supports_structured_output = True

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._live: dict[str, tuple[subprocess.Popen[bytes], CancellationSignal]] = {}

    @property
    def adapter_id(self) -> str:
        return "llamacli"

    @property
    def endpoint_kind(self) -> str:
        return "subprocess"

    # -- probe ---------------------------------------------------------------

    def probe(self, configuration: Any, *, deadline_seconds: float = 5.0) -> ProbeResult:
        program, refusal = _resolve_program(configuration.program or "llama-cli")
        if refusal:
            return unavailable_probe(self.adapter_id, refusal)
        models: list[ModelListing] = []
        for directory in trusted_model_directories():
            try:
                entries = sorted(directory.glob("*.gguf"))
            except OSError:
                continue
            for entry in entries[:_MAX_MODELS_LISTED]:
                try:
                    size = entry.stat().st_size
                except OSError:
                    size = 0
                models.append(ModelListing(model_id=entry.name, size_bytes=size))
        model_path, model_refusal = _resolve_model(configuration.model_id)
        if model_path is None and models:
            # Nothing configured, but the trusted directories hold models the
            # registry will choose from — the same way a server adapter's
            # ``/v1/models`` listing is chosen from. Reporting unavailable
            # here would contradict the descriptor the registry then builds.
            model_path, model_refusal = _resolve_model(models[0].model_id)
        if model_path is None:
            return ProbeResult(
                adapter_id=self.adapter_id, available=False,
                detail=f"{program} present; {model_refusal}",
                implementation=program, models=tuple(models),
            )
        return ProbeResult(
            adapter_id=self.adapter_id, available=True,
            detail=f"{program} with {model_path.name}",
            implementation=program, models=tuple(models),
        )

    # -- generation ----------------------------------------------------------

    def generate(
        self,
        request: GenerationRequest,
        configuration: Any,
        *,
        secret: Secret | None,
        emit: Callable[[StreamEvent], None],
        events: StreamEventFactory,
        cancellation: CancellationSignal,
    ) -> GenerationOutcome:
        def failed(kind: str, detail: str) -> GenerationOutcome:
            return GenerationOutcome(
                request_id=request.request_id, provider_id=request.provider_id,
                ok=False, failure_kind=kind, detail=detail,
            )

        program, refusal = _resolve_program(configuration.program or "llama-cli")
        if refusal:
            return failed("model-unavailable", refusal)
        model_path, model_refusal = _resolve_model(request.model_id or configuration.model_id)
        if model_path is None:
            return failed("model-unavailable", model_refusal)
        # The plan step's JSON instruction is already in the prompt assembled
        # by ``_prompt_from``; the schema reference is metadata for the
        # prompt-based parse + repair path, not a native grammar hook, so a
        # plain text completion is what the planner validates.
        argv = [
            program,
            "-m", str(model_path),
            "-n", str(request.maximum_output_tokens),
            "--temp", f"{request.sampling.temperature:.3f}",
            "--top-p", f"{request.sampling.top_p:.3f}",
            "--seed", str(request.sampling.seed),
            "-no-cnv",
            "--no-display-prompt",
            "--simple-io",
            "-p", _prompt_from(request),
        ]
        try:
            process = subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=_child_environment(),
                cwd=str(Path.home()),
            )
        except OSError as error:
            return failed("connection", f"could not start {program}: {error}")
        with self._guard:
            self._live[request.request_id] = (process, cancellation)

        stderr_chunks: list[bytes] = []
        stderr_thread = threading.Thread(
            target=self._drain_stderr, args=(process, stderr_chunks),
            name="agents-llamacli-stderr", daemon=True,
        )
        stderr_thread.start()
        watchdog_fired = threading.Event()
        watchdog = threading.Thread(
            target=self._watchdog,
            args=(process, cancellation, request.deadline_seconds, watchdog_fired),
            name="agents-llamacli-watchdog", daemon=True,
        )
        watchdog.start()

        emit(events.started())
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        output_bytes = 0
        try:
            assert process.stdout is not None
            while True:
                chunk = process.stdout.read(4096)
                if not chunk:
                    break
                output_bytes += len(chunk)
                text = decoder.decode(chunk)
                for piece in chunked(text, bound=MAX_DELTA_BYTES):
                    emit(events.delta(piece))
            tail = decoder.decode(b"", final=True)
            for piece in chunked(tail, bound=MAX_DELTA_BYTES):
                emit(events.delta(piece))
        finally:
            # The reap is unconditional: exit status is collected on every
            # path, including a raise out of emit, or a zombie survives into
            # the §24 child-process column. A normal EOF is given a grace to
            # exit with its real code before escalation begins — terminating
            # an exiting process would rewrite a success into a signal death.
            try:
                process.wait(timeout=_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=_GRACE_SECONDS)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            watchdog_fired.set()
            stderr_thread.join(timeout=2.0)
            watchdog.join(timeout=2.0)
            with self._guard:
                self._live.pop(request.request_id, None)

        stderr_text = b"".join(stderr_chunks)[:_MAX_STDERR_BYTES].decode("utf-8", errors="replace")
        if cancellation.cancelled:
            emit(events.cancelled(cancellation.reason))
            return GenerationOutcome(
                request_id=request.request_id, provider_id=request.provider_id,
                ok=False, cancelled=True, detail=cancellation.reason,
            )
        if process.returncode != 0:
            emit(events.failed(f"llama-cli exited {process.returncode}"))
            return failed(
                "invalid-response",
                f"llama-cli exited {process.returncode}: {stderr_text[-400:]}",
            )
        usage = estimated_usage(
            request, output_bytes=output_bytes,
            units_per_kilotoken=configuration.estimated_units_per_kilotoken,
            pricing_reference=configuration.pricing_reference,
        )
        emit(events.usage(usage.to_json()))
        emit(events.completed())
        return GenerationOutcome(
            request_id=request.request_id, provider_id=request.provider_id,
            ok=True, usage=usage,
        )

    @staticmethod
    def _drain_stderr(process: subprocess.Popen[bytes], into: list[bytes]) -> None:
        collected = 0
        assert process.stderr is not None
        while True:
            chunk = process.stderr.read(4096)
            if not chunk:
                return
            if collected < _MAX_STDERR_BYTES:
                into.append(chunk)
                collected += len(chunk)

    @staticmethod
    def _watchdog(
        process: subprocess.Popen[bytes],
        cancellation: CancellationSignal,
        deadline_seconds: float,
        released: threading.Event,
    ) -> None:
        # Poll in short steps rather than sleeping out the whole deadline: a
        # watchdog that lingered after a fast, successful generation would be
        # a thread the §24 delta column counts between iterations.
        remaining = deadline_seconds
        step = 0.1
        while remaining > 0 and not released.is_set() and process.poll() is None:
            if cancellation.wait(timeout=min(step, remaining)):
                break
            remaining -= step
        if released.is_set() or process.poll() is not None:
            return
        if not cancellation.cancelled:
            cancellation.cancel("deadline exceeded")
        process.terminate()
        try:
            process.wait(timeout=_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=_KILL_GRACE_SECONDS)
            except subprocess.TimeoutExpired:  # pragma: no cover - kill cannot be refused
                pass

    def cancel(self, request_id: str) -> bool:
        with self._guard:
            entry = self._live.get(request_id)
        if entry is None:
            return False
        _, signal = entry
        signal.cancel("cancelled by runtime")
        return True

    def close(self) -> None:
        with self._guard:
            live = dict(self._live)
        for _, (process, signal) in live.items():
            signal.cancel("adapter closing")
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=_GRACE_SECONDS)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        with self._guard:
            self._live.clear()

    @property
    def live_children(self) -> int:
        with self._guard:
            return len(self._live)
