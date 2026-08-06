# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Running a capture program without giving it, or the microphone, the machine.

The voice runtime already built the machinery this needs —
:func:`companion.voice.execution.resolve_executable`'s deterministic search,
:func:`companion.voice.execution.child_environment`'s allowlisted environment,
:class:`companion.voice.execution.PrivateWorkspace`'s ``0o700``/``0o600``
storage — and this module reuses those functions rather than restating them,
because two implementations of "which binary may run" is how the two eventually
disagree in the dangerous direction.

What it does *not* reuse is the allowlist or the child. The allowlist is this
module's own because a speech-input runtime that could start ``espeak-ng`` — or
a voice runtime that could start ``parec`` — would be one subsystem holding the
other's capabilities, and the review question "what can touch the microphone" is
answerable only if the list is short and lives here. The child is this module's
own because capture inverts the data flow: a player is handed a file and its
stdout is discarded; a recorder is handed a device and its stdout *is the
microphone*. :class:`CaptureChild` reads that stream on a dedicated thread into
a caller-supplied sink, bounded at every step, so a recorder that produces data
faster than the worker consumes it stalls at a pipe rather than growing the
service.

One deliberate asymmetry with playback: there is no pause. ``SIGSTOP`` on a
recorder leaves the device *open* while the indicator says nothing is being
captured, which is precisely the state §5 exists to prevent. A capture that
must stop, stops.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import threading
from typing import Any, Callable

from ..voice.execution import (
    CommandOutcome,
    CommandSpec,
    ExecutableRefused,
    PrivateWorkspace,
    TRUSTED_DIRECTORIES,
    child_environment,
    resolve_executable,
)

__all__ = [
    "CAPTURE_EXECUTABLES",
    "CaptureChild",
    "SpeechWorkspace",
    "resolve_capture_executable",
]

#: Every program the speech-input runtime may start, by base name. Recorders and
#: the discovery tools beside them, and nothing else: no synthesiser, no player,
#: no recogniser binary — the recognisers in this build are in-process libraries
#: precisely so that no subprocess is ever handed the audio and a model path in
#: the same argv.
CAPTURE_EXECUTABLES = frozenset({
    # Capture
    "parec", "pw-record", "arecord",
    # Device enumeration
    "pactl", "pw-dump",
})

#: How much stderr is kept from a recorder. Same bound as playback, same reason.
MAX_STDERR_BYTES = 8 * 1024

#: The largest single read taken from a recorder's stdout. Small enough that a
#: cancellation is observed within a frame or two; large enough that a capture
#: is not a syscall per millisecond. At 16 kHz mono this is 128 ms of audio.
READ_CHUNK_BYTES = 4096


def resolve_capture_executable(name: str) -> tuple[str, bool]:
    """One allowlisted capture program, or precisely why it may not run.

    The same deterministic search over :data:`TRUSTED_DIRECTORIES` the voice
    runtime uses, against this module's own allowlist. The returned path keeps
    the *requested* name rather than any symlink target, because ``parec`` is
    ``pacat`` under another name and the name is the semantics — the measured
    multi-call defect, inherited here before it can be re-measured.
    """
    return resolve_executable(name, allowlist=CAPTURE_EXECUTABLES)


class SpeechWorkspace(PrivateWorkspace):
    """A private directory for captured audio, distinguishable from voice's.

    The prefix is what :func:`companion.speech.recovery.sweep_workspaces`
    matches on, and it is deliberately not the voice prefix: a recovery pass
    that swept both under one name could not report which subsystem abandoned
    what, and §21's crash-recovery evidence needs the attribution.
    """

    PREFIX = "bunny-speech-"


class CaptureChild:
    """One running recorder, owned explicitly, with its stdout read and bounded.

    The lifecycle is the voice runtime's — terminate, escalate, reap, always —
    reimplemented over a piped stdout. Every instance must reach
    :meth:`finish`; the capture worker does it in a ``finally``.

    ``sink`` receives each chunk of raw PCM on the reader thread and returns
    whether to keep reading. Returning ``False`` is backpressure: the reader
    stops consuming, the pipe fills, and the recorder blocks at the kernel —
    which is §7's "never grow memory without limit" enforced by the operating
    system rather than by bookkeeping.
    """

    def __init__(
        self,
        spec: CommandSpec,
        *,
        sink: Callable[[bytes], bool],
        refusal: str = "",
    ) -> None:
        self.spec = spec
        self.redacted_argv = tuple(spec.redacted())
        self.start_error = refusal
        self.terminated = False
        self.killed = False
        self.reaped = True
        self.bytes_read = 0
        self._sink = sink
        self._stderr: list[bytes] = []
        self._reader: threading.Thread | None = None
        self._stderr_reader: threading.Thread | None = None
        self._process: subprocess.Popen[bytes] | None = None
        self._guard = threading.RLock()
        if refusal:
            return

        popen_extra: dict[str, Any] = {}
        if os.name == "posix":
            # Its own process group, so the whole tree can be signalled. parec
            # does not fork helpers today; the guarantee is cheaper than the
            # assumption that it never will.
            popen_extra["start_new_session"] = True

        try:
            self._process = subprocess.Popen(  # noqa: S603 - argv list, never a shell
                spec.argv(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=child_environment(extra=spec.environment),
                close_fds=True,
                shell=False,
                **popen_extra,
            )
        except OSError as exc:
            self.start_error = f"{exc.strerror or exc}"
            return

        process = self._process

        def _read_audio() -> None:
            stream = process.stdout
            if stream is None:  # pragma: no cover - Popen always provides it
                return
            try:
                while True:
                    chunk = stream.read(READ_CHUNK_BYTES)
                    if not chunk:
                        return
                    with self._guard:
                        self.bytes_read += len(chunk)
                    if not self._sink(chunk):
                        # The sink said stop. Reading no further is the
                        # backpressure; the recorder blocks on a full pipe and
                        # is then terminated by whoever owns this child.
                        return
            except (OSError, ValueError):
                return

        def _read_stderr() -> None:
            stream = process.stderr
            if stream is None:  # pragma: no cover - Popen always provides it
                return
            try:
                self._stderr.append(stream.read(MAX_STDERR_BYTES * 4))
            except (OSError, ValueError):
                pass

        self._reader = threading.Thread(
            target=_read_audio, name="speech-capture-read", daemon=True
        )
        self._stderr_reader = threading.Thread(
            target=_read_stderr, name="speech-capture-stderr", daemon=True
        )
        self._reader.start()
        self._stderr_reader.start()

    @property
    def started(self) -> bool:
        return self._process is not None

    @property
    def pid(self) -> int:
        return self._process.pid if self._process is not None else -1

    def poll(self) -> int | None:
        return None if self._process is None else self._process.poll()

    def terminate(self, *, grace_seconds: float = 2.0, kill_grace_seconds: float = 3.0) -> None:
        """Stop recording, escalating once, and never wait unboundedly."""
        process = self._process
        if process is None or process.poll() is not None:
            return
        self.terminated = self._signal(process, "SIGTERM") or self.terminated
        try:
            process.wait(timeout=grace_seconds)
            return
        except subprocess.TimeoutExpired:
            pass
        self.killed = self._signal(process, "SIGKILL") or self.killed
        try:
            process.wait(timeout=kill_grace_seconds)
        except subprocess.TimeoutExpired:
            pass

    @staticmethod
    def _signal(process: "subprocess.Popen[bytes]", name: str) -> bool:
        import signal as _signal

        number = getattr(_signal, name, None)
        if number is None:  # pragma: no cover - Windows development hosts
            try:
                process.terminate()
                return True
            except OSError:
                return False
        try:
            if os.name == "posix" and hasattr(os, "killpg"):
                os.killpg(os.getpgid(process.pid), number)
                return True
        except (ProcessLookupError, PermissionError, OSError):
            pass
        try:
            process.send_signal(number)
            return True
        except (ProcessLookupError, OSError):
            return False

    def finish(self) -> None:
        """Reap, join the readers, close the pipes. Idempotent.

        The audio reader is joined *after* the process is reaped: a recorder
        that has exited closes its stdout, the pending read returns empty, and
        the thread ends. Joining first would wait on a read that only the
        child's exit can end.
        """
        process = self._process
        if process is None:
            return
        if process.poll() is None:
            self.terminate(
                grace_seconds=self.spec.grace_seconds,
                kill_grace_seconds=self.spec.kill_grace_seconds,
            )
        if process.poll() is None:
            self.reaped = False
        for thread in (self._reader, self._stderr_reader):
            if thread is not None:
                thread.join(timeout=self.spec.grace_seconds)
        self._reader = None
        self._stderr_reader = None
        for stream in (process.stdout, process.stderr):
            try:
                if stream is not None and not stream.closed:
                    stream.close()
            except OSError:
                pass

    def outcome(
        self,
        *,
        duration_seconds: float,
        timed_out: bool = False,
        cancelled: bool = False,
    ) -> CommandOutcome:
        raw = b"".join(item for item in self._stderr if item)
        truncated = len(raw) > MAX_STDERR_BYTES
        body = raw[:MAX_STDERR_BYTES].decode("utf-8", errors="replace")
        body = "".join(
            character if character.isprintable() or character in " \t\n" else " "
            for character in body
        ).strip()
        return CommandOutcome(
            executable=self.spec.executable,
            redacted_argv=self.redacted_argv,
            exit_code=None if self._process is None else self._process.returncode,
            duration_seconds=duration_seconds,
            stderr=body,
            stderr_truncated=truncated,
            timed_out=timed_out,
            cancelled=cancelled,
            terminated=self.terminated,
            killed=self.killed,
            reaped=self.reaped,
            start_error=self.start_error,
        )
