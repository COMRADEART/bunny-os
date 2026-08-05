# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Running a local synthesiser without giving it, or its input, the machine.

Every command-backed provider in this package goes through this module, and no
provider builds a :class:`subprocess.Popen` of its own. That is not a style
preference. Speech text is task-derived and therefore attacker-influenced — a
task's result summary can contain whatever the request that produced it
contained — and the distance between "a spoken sentence" and "a shell command"
is exactly the distance between a list and a string.

§5's rules, and where each one lives:

``argument arrays only``
    :class:`CommandSpec` holds a tuple. There is no code path in this package
    that produces a command *string*, and ``shell=True`` appears nowhere.

``never concatenate user text into a command``
    :meth:`CommandSpec.with_text` puts the utterance either in
    :attr:`CommandSpec.stdin_text` or in exactly one argv slot chosen by the
    provider, and :func:`run` refuses a spec whose text appears in an argument
    it was not declared for. Preferring stdin is not cosmetic: an argv is
    visible in ``/proc`` to every process the user runs, so a caption passed as
    an argument is a caption readable by anything on the machine.

``executable allowlists and deterministic resolution``
    :func:`resolve_executable` searches :data:`TRUSTED_DIRECTORIES` in order —
    never the inherited ``PATH`` — and refuses a name outside
    :data:`ALLOWED_EXECUTABLES`. It then checks what it found: a regular file,
    executable, not writable by group or other, and still inside a trusted
    directory after symlinks are resolved. A synthesiser is invoked by a
    background service on behalf of a user who never typed its name, so
    "whatever ``PATH`` happens to say today" is not an acceptable answer.

``bounded environment``
    :func:`child_environment` builds the child's environment from an allowlist
    with ``PATH`` overwritten by the trusted one. The child does not inherit the
    service's environment, so a variable that reached the service reaches no
    synthesiser.

``timeouts, escalation, and reaping``
    :func:`run` always terminates and always waits. The escalation is
    ``terminate`` → grace → ``kill`` → grace, and the final ``wait()`` is in a
    ``finally``, so a provider that ignores ``SIGTERM`` (§21 tests one that
    does) costs a bounded delay rather than a leaked process. On POSIX the child
    is put in its own process group and the *group* is signalled, because
    ``spd-say`` and ``aplay`` both fork helpers that a signal to the leader
    alone would strand.

``bounded stderr``
    Read into a fixed buffer and truncated with a marker. A synthesiser that
    writes a megabyte of warnings must not be able to grow the service's memory
    by writing more.

``redaction``
    :func:`redacted_argv` replaces the declared text slot with a marker.
    :class:`CommandOutcome` never holds the utterance, so a record of a failure
    is publishable without a review of what the task was about.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import errno
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
from typing import Any, Iterable, Mapping, Sequence

__all__ = [
    "ALLOWED_EXECUTABLES",
    "CancellationSignal",
    "CommandOutcome",
    "CommandSpec",
    "ExecutableRefused",
    "PrivateWorkspace",
    "TRUSTED_DIRECTORIES",
    "child_environment",
    "redacted_argv",
    "resolve_executable",
    "run",
]

#: Every program this package may start, by base name. A name absent from this
#: set is refused before anything touches the filesystem, so adding a provider
#: is a change to this line and therefore a change somebody reviews.
#:
#: Synthesisers and audio players are in one set on purpose. Splitting them
#: would suggest the two categories have different trust, and they do not: both
#: are local binaries handed bounded arguments by the same runner.
ALLOWED_EXECUTABLES = frozenset({
    # Synthesis
    "spd-say", "espeak-ng", "espeak", "say",
    # Playback
    "paplay", "pw-play", "aplay",
    # Device enumeration
    "pactl", "pw-dump",
    # Speech Dispatcher inventory
    "spd-conf",
})

#: Where an executable may be found, searched in this order. Not ``PATH``:
#: ``PATH`` is inherited, and a service that resolved ``espeak-ng`` through an
#: inherited ``PATH`` would run whatever a user's profile put first.
#:
#: ``/usr/local/bin`` is deliberately absent. It is the conventional home for
#: locally built software and, on a system where an administrator installs
#: things by hand, the directory most likely to shadow a packaged binary.
TRUSTED_DIRECTORIES: tuple[str, ...] = ("/usr/bin", "/bin", "/usr/sbin", "/sbin")

#: The most stderr kept from any one child.
MAX_STDERR_BYTES = 8 * 1024

#: What replaces the utterance in anything written to a log or an event.
TEXT_MARKER = "[speech-text]"

#: Environment variables a child may inherit, and why each is here.
#:
#: ``XDG_RUNTIME_DIR`` and the ``PULSE``/``PIPEWIRE`` pair are how a player
#: finds the user's audio server; without them ``paplay`` cannot connect at all.
#: ``HOME`` is needed by Speech Dispatcher to find the user's own configuration.
#: The locale pair fixes the language a synthesiser assumes when the request
#: does not name one. Nothing else is passed, and in particular no variable that
#: could name a library path, a preload, a proxy or a credential.
_ENVIRONMENT_ALLOWLIST = (
    "HOME", "USER", "LOGNAME",
    "XDG_RUNTIME_DIR",
    "PULSE_SERVER", "PULSE_SINK", "PULSE_COOKIE",
    "PIPEWIRE_RUNTIME_DIR",
    "LANG", "LC_ALL", "LC_MESSAGES",
    "SPEECHD_ADDRESS",
    "ALSA_CONFIG_PATH",
)

#: Variables that must never reach a child even if some future allowlist entry
#: would carry them. Checked after the allowlist, so the two cannot disagree in
#: the dangerous direction.
_ENVIRONMENT_DENYLIST = frozenset({
    "LD_PRELOAD", "LD_LIBRARY_PATH", "LD_AUDIT", "PYTHONPATH", "PYTHONHOME",
    "IFS", "BASH_ENV", "ENV", "SHELLOPTS",
    "http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
})


class ExecutableRefused(RuntimeError):
    """A program may not be run, with the reason stated rather than implied."""


# --------------------------------------------------------------------------- #
# Resolution
# --------------------------------------------------------------------------- #


def _permissions_safe(path: Path) -> tuple[bool, str]:
    """Whether a resolved binary is one a service may run.

    Group- or world-writable means somebody other than root can replace it
    between the check and the call, which makes the allowlist decorative.
    """
    try:
        info = path.stat()
    except OSError as exc:
        return False, f"could not be inspected: {exc.strerror or exc}"
    if not stat.S_ISREG(info.st_mode):
        return False, "is not a regular file"
    if not os.access(path, os.X_OK):
        return False, "is not executable"
    if os.name == "posix" and info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        return False, "is writable by group or other"
    return True, ""


def resolve_executable(
    name: str,
    *,
    directories: Sequence[str] = TRUSTED_DIRECTORIES,
    allowlist: Iterable[str] = ALLOWED_EXECUTABLES,
) -> tuple[str, bool]:
    """Find one allowlisted program, or say precisely why it may not be run.

    Returns ``(path, trusted)``. ``trusted`` is ``False`` only on a platform
    with no :data:`TRUSTED_DIRECTORIES` — development machines that are not
    Linux — where the fallback is :func:`shutil.which`. The flag is returned
    rather than hidden because a provider that resolved through the fallback
    must report itself as such: the installed system never takes that path, and
    a measurement taken on a machine that did is not a measurement of the
    installed system.
    """
    if name not in set(allowlist):
        raise ExecutableRefused(
            f"{name!r} is not in the voice runtime's executable allowlist; "
            "a provider may only start a program named in it"
        )
    if os.sep in name or (os.altsep and os.altsep in name):
        # Belt and braces: the allowlist already excludes anything with a
        # separator, and this makes the refusal explicit rather than incidental.
        raise ExecutableRefused(f"{name!r} names a path rather than a program")

    for directory in directories:
        candidate = Path(directory) / name
        if not candidate.exists():
            continue
        resolved = candidate.resolve()
        # After symlinks. A trusted directory that links out to a writable one
        # is the substitution this check exists to reject.
        if not any(
            str(resolved).startswith(str(Path(item).resolve()) + os.sep)
            for item in directories
            if Path(item).exists()
        ):
            raise ExecutableRefused(
                f"{name!r} in {directory} resolves to {resolved}, which is outside every "
                "trusted directory; this is an executable substitution and was refused"
            )
        safe, reason = _permissions_safe(resolved)
        if not safe:
            raise ExecutableRefused(f"{resolved} {reason}; it was refused")
        # The *requested* path is returned, not the symlink target, and the
        # difference is not cosmetic. Several of the programs in the allowlist
        # are multi-call binaries that decide what they do from ``argv[0]``:
        # ``/usr/bin/paplay`` is a symlink to ``pacat``, and ``pacat`` invoked
        # under its own name reads its input as *raw PCM* while ``paplay`` parses
        # it as a sound file.
        #
        # Returning the resolved target made the runtime exec ``pacat``, which
        # played a WAV's RIFF header and mono samples as stereo raw data at the
        # wrong rate — 0.73 seconds of noise where 2.80 seconds of speech should
        # have been, and it exited 0, so nothing downstream could tell. The
        # duration mismatch is what caught it.
        #
        # The security properties are unchanged: the target was resolved and
        # checked above, and the path returned here is itself inside a trusted
        # directory. What is preserved is the program's own idea of which
        # program it is.
        return str(candidate), True

    if any(Path(item).is_dir() for item in directories):
        # At least one trusted directory exists and the program is not in it.
        # On Linux that is the whole answer, and falling back to PATH here would
        # undo the point of the search order.
        raise ExecutableRefused(f"{name!r} is not installed in a trusted directory")

    # No trusted directory exists at all: a non-Linux development machine.
    found = shutil.which(name)
    if not found:
        raise ExecutableRefused(f"{name!r} is not installed")
    return found, False


# --------------------------------------------------------------------------- #
# Environment
# --------------------------------------------------------------------------- #


def child_environment(
    *,
    extra: Mapping[str, str] | None = None,
    source: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """The environment a synthesiser or player gets. Built, never inherited.

    ``extra`` is for the small number of variables a provider legitimately sets
    for itself — a locale for one utterance, a sink name for one playback. It is
    filtered through the same denylist as everything else, so a provider cannot
    reintroduce ``LD_PRELOAD`` by passing it here.
    """
    origin = os.environ if source is None else source
    environment = {
        key: str(origin[key])
        for key in _ENVIRONMENT_ALLOWLIST
        if key in origin and origin[key] is not None
    }
    for key, value in (extra or {}).items():
        if key in _ENVIRONMENT_DENYLIST:
            raise ExecutableRefused(f"{key} may not be set for a voice child process")
        if not isinstance(key, str) or not key or "=" in key or "\0" in key:
            raise ExecutableRefused(f"{key!r} is not a usable environment variable name")
        if "\0" in str(value):
            raise ExecutableRefused(f"the value of {key} contains a NUL and was refused")
        environment[key] = str(value)
    for key in _ENVIRONMENT_DENYLIST:
        environment.pop(key, None)
    # Overwritten rather than inherited, so a child that execs a helper finds the
    # same trusted directories this module searched.
    environment["PATH"] = os.pathsep.join(TRUSTED_DIRECTORIES)
    return environment


# --------------------------------------------------------------------------- #
# Private storage
# --------------------------------------------------------------------------- #


class PrivateWorkspace:
    """A directory only this user can read, and the files inside it.

    §15 requires temporary audio to be private and to be removed after playback
    or cancellation. Both halves are here: the directory is created ``0o700`` by
    :func:`tempfile.mkdtemp`, every file inside it is opened ``0o600``, and
    :meth:`close` removes the tree whatever happened to the utterance.

    The name carries a fixed prefix so :mod:`companion.voice.recovery` can find
    the workspaces a crashed worker left behind — and it validates ownership
    before removing anything, because a prefix is not a proof.
    """

    #: The prefix recovery matches on. Changing it strands every workspace an
    #: older build left behind, so it is deliberately dull and deliberately here
    #: rather than composed at each call site.
    PREFIX = "bunny-voice-"

    def __init__(self, *, parent: Path | None = None) -> None:
        self.root = Path(tempfile.mkdtemp(prefix=self.PREFIX, dir=str(parent) if parent else None))
        self._files: list[Path] = []
        self._closed = False
        self._guard = threading.RLock()

    def file(self, name: str, *, suffix: str = ".wav") -> Path:
        """A private path inside this workspace, created empty and ``0o600``.

        Created here rather than left to the child so that the *permissions* are
        ours: a synthesiser writing its own output file uses its own umask, and
        a umask of ``0o022`` produces a world-readable recording of whatever the
        task said.
        """
        with self._guard:
            if self._closed:
                raise RuntimeError("this workspace has been closed")
            safe = "".join(character for character in name if character.isalnum() or character in "._-")
            if not safe:
                safe = "audio"
            path = self.root / f"{safe}{suffix}"
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
            self._files.append(path)
            return path

    @property
    def files(self) -> tuple[Path, ...]:
        with self._guard:
            return tuple(self._files)

    @property
    def closed(self) -> bool:
        with self._guard:
            return self._closed

    def close(self) -> None:
        """Remove everything. Safe to call twice, and safe to call after a fault."""
        with self._guard:
            if self._closed:
                return
            self._closed = True
            root = self.root
            self._files.clear()
        shutil.rmtree(root, ignore_errors=True)

    def __enter__(self) -> "PrivateWorkspace":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


# --------------------------------------------------------------------------- #
# Cancellation
# --------------------------------------------------------------------------- #


class CancellationSignal:
    """A one-way flag a running command watches.

    An :class:`threading.Event` with a name and a reason attached. The name is
    what makes a diagnostic record readable; the reason is what distinguishes
    "the user cancelled" from "a more urgent utterance took the floor", which
    §7 requires to be recorded differently.
    """

    def __init__(self, *, name: str = "") -> None:
        self._event = threading.Event()
        self.name = name
        self.reason = ""

    def cancel(self, reason: str = "cancelled") -> bool:
        """Raise the flag. Returns whether this call was the one that raised it."""
        if self._event.is_set():
            return False
        self.reason = reason
        self._event.set()
        return True

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def wait(self, timeout: float | None = None) -> bool:
        return self._event.wait(timeout)


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CommandSpec:
    """One program, its arguments, and where the utterance goes.

    ``text_argument_index`` names the single argv slot that may hold the
    utterance. It is ``None`` when the text goes through stdin, which is the
    preferred shape and the one every provider here uses when its program
    supports it. :func:`run` checks the declaration against the argv, so a
    provider that put the text somewhere it did not declare is refused rather
    than run.
    """

    executable: str
    arguments: tuple[str, ...] = ()
    stdin_text: str = ""
    #: Index into :attr:`arguments` (not into the full argv) that holds the
    #: utterance, when it cannot go through stdin.
    text_argument_index: int | None = None
    environment: Mapping[str, str] = field(default_factory=dict)
    working_directory: str = ""
    timeout_seconds: float = 60.0
    #: How long a terminated child gets before it is killed, and how long a
    #: killed child gets before the runner gives up waiting and says so.
    grace_seconds: float = 2.0
    kill_grace_seconds: float = 3.0
    #: ``True`` when the child is expected to write to an audio device. Recorded
    #: so a degradation caused by a missing device can be attributed to the
    #: right half of the pipeline.
    touches_audio: bool = False

    def argv(self) -> list[str]:
        return [self.executable, *self.arguments]

    def with_text(self, text: str) -> "CommandSpec":
        """Place the utterance where this spec declared it goes."""
        if self.text_argument_index is None:
            return replace(self, stdin_text=text)
        index = self.text_argument_index
        if not 0 <= index < len(self.arguments):
            raise ExecutableRefused("the declared text argument is outside the argument list")
        arguments = list(self.arguments)
        arguments[index] = text
        return replace(self, arguments=tuple(arguments))

    def redacted(self) -> list[str]:
        return redacted_argv(self.argv(), text_argument_index=self.text_argument_index)


def redacted_argv(argv: Sequence[str], *, text_argument_index: int | None = None) -> list[str]:
    """An argv safe to write into a log, an event or a support bundle.

    The declared text slot becomes :data:`TEXT_MARKER`. Note the ``+1``: the
    index is into the *arguments*, and the argv this receives has the executable
    at position zero. Getting that wrong would redact a flag and publish the
    caption, which is the failure this function exists to prevent.
    """
    items = [str(item) for item in argv]
    if text_argument_index is not None and 0 <= text_argument_index + 1 < len(items):
        items[text_argument_index + 1] = TEXT_MARKER
    return items


@dataclass(frozen=True)
class CommandOutcome:
    """What one child did. Never holds the utterance.

    ``exit_code`` is the process's own where it exited normally and negative
    where a signal ended it, matching :mod:`subprocess`. ``killed`` distinguishes
    "we escalated" from "it exited on its own", which is what makes the §21 test
    for a provider that ignores termination an assertion rather than a timing
    guess.
    """

    executable: str
    redacted_argv: tuple[str, ...]
    exit_code: int | None
    duration_seconds: float
    stderr: str = ""
    stderr_truncated: bool = False
    timed_out: bool = False
    cancelled: bool = False
    terminated: bool = False
    killed: bool = False
    reaped: bool = True
    start_error: str = ""

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0 and not self.timed_out and not self.cancelled and not self.start_error

    def to_json(self) -> dict[str, Any]:
        return {
            "executable": self.executable,
            "argv": list(self.redacted_argv),
            "exitCode": self.exit_code,
            "durationSeconds": round(self.duration_seconds, 6),
            "stderr": self.stderr,
            "stderrTruncated": self.stderr_truncated,
            "timedOut": self.timed_out,
            "cancelled": self.cancelled,
            "terminated": self.terminated,
            "killed": self.killed,
            "reaped": self.reaped,
            "startError": self.start_error,
            "succeeded": self.succeeded,
        }


def _bounded(raw: bytes | None) -> tuple[str, bool]:
    if not raw:
        return "", False
    truncated = len(raw) > MAX_STDERR_BYTES
    body = raw[:MAX_STDERR_BYTES].decode("utf-8", errors="replace")
    # Control characters out: this string ends up in a JSON record and in a log
    # line, and a synthesiser that writes an escape sequence should not be able
    # to rewrite the terminal of whoever reads it.
    body = "".join(character if character.isprintable() or character in " \t\n" else " " for character in body)
    return body.strip(), truncated


def _signal_group(process: "subprocess.Popen[bytes]", number: int) -> bool:
    """Signal the child's whole process group where the platform has them.

    ``spd-say --wait`` and ``paplay`` both spawn helpers. Signalling only the
    leader leaves those helpers holding the audio device, which is precisely the
    "no orphan audio stream" §6 forbids.
    """
    try:
        if os.name == "posix" and hasattr(os, "killpg"):
            os.killpg(os.getpgid(process.pid), number)
            return True
    except (ProcessLookupError, PermissionError, OSError) as exc:
        if isinstance(exc, OSError) and exc.errno not in (errno.ESRCH, errno.EPERM):
            raise
        return False
    try:
        process.send_signal(number)
        return True
    except (ProcessLookupError, OSError):
        return False


class Child:
    """One running program, owned explicitly.

    Split out from :func:`run` because playback needs the *same* process
    lifecycle without the blocking wait: an utterance being played has to be
    pausable, resumable and stoppable while it runs, and a second
    implementation of "terminate, escalate, reap" living in the audio backend is
    a second place for a leaked process to come from. There is one, here, and
    :func:`run` is a thin loop over it.

    Every instance must reach :meth:`finish`. The two callers both do it in a
    ``finally``.
    """

    def __init__(self, spec: CommandSpec) -> None:
        self.spec = spec
        self.redacted_argv = tuple(spec.redacted())
        self.start_error = ""
        self.terminated = False
        self.killed = False
        self.reaped = True
        self._stderr: list[bytes] = []
        self._reader: threading.Thread | None = None
        self._paused = False
        self._process: subprocess.Popen[bytes] | None = None

        # The text must be where the spec said it is. A provider that built an
        # argv with the utterance in an undeclared slot would produce a
        # redaction that silently published it.
        if spec.text_argument_index is None and spec.stdin_text:
            for index, item in enumerate(spec.arguments):
                if item == spec.stdin_text:
                    raise ExecutableRefused(
                        f"the utterance appears in argument {index} but the command declared it "
                        "goes through stdin; refusing rather than publishing it in the process table"
                    )

        popen_extra: dict[str, Any] = {}
        if os.name == "posix":
            # Its own process group, so the whole tree can be signalled and so a
            # terminal signal aimed at the service does not reach the
            # synthesiser by a route this module does not control.
            popen_extra["start_new_session"] = True

        try:
            self._process = subprocess.Popen(  # noqa: S603 - argv list, never a shell
                spec.argv(),
                stdin=subprocess.PIPE if spec.stdin_text else subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                env=child_environment(extra=spec.environment),
                cwd=spec.working_directory or None,
                close_fds=True,
                shell=False,
                **popen_extra,
            )
        except OSError as exc:
            self.start_error = f"{exc.strerror or exc}"
            return

        process = self._process

        def _drain() -> None:
            # A dedicated reader so the child cannot block on a full stderr pipe
            # while the caller waits for it — the classic deadlock, and the
            # reason this is not a `wait()` with a `read()` after it.
            try:
                stream = process.stderr
                if stream is not None:
                    self._stderr.append(stream.read(MAX_STDERR_BYTES * 4))
            except (OSError, ValueError):
                pass

        self._reader = threading.Thread(target=_drain, name="voice-stderr", daemon=True)
        self._reader.start()

        if spec.stdin_text and process.stdin is not None:
            try:
                process.stdin.write(spec.stdin_text.encode("utf-8"))
            except (BrokenPipeError, OSError):
                # The child exited before reading. Not an error: the exit code
                # is the real answer, and this path is reached whenever a
                # synthesiser rejects its arguments.
                pass
            finally:
                try:
                    process.stdin.close()
                except (BrokenPipeError, OSError):
                    pass

    @property
    def started(self) -> bool:
        return self._process is not None

    @property
    def pid(self) -> int:
        return self._process.pid if self._process is not None else -1

    @property
    def paused(self) -> bool:
        return self._paused

    def poll(self) -> int | None:
        """The exit code, or ``None`` while it runs.

        A *paused* child is reported as still running, which is what it is: a
        stopped process has not exited, and a poll that reported completion for
        one would let the worker advance past an utterance still holding the
        device.
        """
        return None if self._process is None else self._process.poll()

    def pause(self) -> bool:
        """Suspend the whole process group. POSIX only; ``False`` elsewhere.

        ``SIGSTOP`` rather than a player-specific pause command: every player in
        the allowlist is a one-shot process with no control channel, and the
        kernel's own stop is the only mechanism all of them share. The audio
        server sees the stream stop being fed and goes quiet, which is what a
        pause is.
        """
        if self._process is None or self._process.poll() is not None or self._paused:
            return False
        if not (os.name == "posix" and hasattr(signal, "SIGSTOP")):
            return False
        if _signal_group(self._process, signal.SIGSTOP):
            self._paused = True
            return True
        return False

    def resume(self) -> bool:
        if self._process is None or not self._paused:
            return False
        if _signal_group(self._process, signal.SIGCONT):
            self._paused = False
            return True
        return False

    def terminate(self, *, grace_seconds: float, kill_grace_seconds: float) -> None:
        """Stop it, escalating once, and never wait unboundedly.

        A *paused* child is continued first. ``SIGTERM`` is not delivered to a
        stopped process until it runs again, so terminating without the
        ``SIGCONT`` would leave a suspended player holding the audio device
        until something else happened to resume it — an orphan audio stream
        produced by the cleanup path itself.
        """
        process = self._process
        if process is None or process.poll() is not None:
            return
        if self._paused:
            _signal_group(process, signal.SIGCONT)
            self._paused = False
        self.terminated = _signal_group(process, signal.SIGTERM) or self.terminated
        try:
            process.wait(timeout=grace_seconds)
            return
        except subprocess.TimeoutExpired:
            pass
        # §21 tests a provider that ignores termination. This is the branch that
        # makes it bounded rather than indefinite.
        self.killed = _signal_group(process, signal.SIGKILL) or self.killed
        try:
            process.wait(timeout=kill_grace_seconds)
        except subprocess.TimeoutExpired:
            pass

    def finish(self) -> None:
        """Reap, join the reader, close the pipes. Idempotent."""
        process = self._process
        if process is None:
            return
        if process.poll() is None:
            try:
                process.wait(timeout=self.spec.kill_grace_seconds)
            except subprocess.TimeoutExpired:
                # A child left unwaited is a zombie, and §22 measures the
                # child-process delta across a hundred runs. Reported rather
                # than swallowed so the gate can fail on it.
                self.reaped = False
        if self._reader is not None:
            self._reader.join(timeout=self.spec.grace_seconds)
            self._reader = None
        for stream in (process.stdin, process.stderr):
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
        body, truncated = _bounded(b"".join(item for item in self._stderr if item))
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


def run(
    spec: CommandSpec,
    *,
    cancellation: CancellationSignal | None = None,
    monotonic: Any = None,
    poll_interval: float = 0.02,
) -> CommandOutcome:
    """Start one program, wait for it, and leave nothing behind.

    The loop is a poll rather than a blocking ``communicate`` because
    cancellation must be observable *while* the child runs — a synthesiser
    reading a long caption takes seconds, and a cancel that only took effect
    when the child finished would not be a cancel. The interval is small enough
    that §24's cancellation latency is dominated by the child's own exit and
    large enough that an idle worker is not a spin.

    Whatever happens — success, timeout, cancellation, an exception from the
    reader thread — the child is signalled and waited for before this returns.
    """
    import time as _time

    now = monotonic or _time.monotonic
    started = now()
    child = Child(spec)
    if not child.started:
        return child.outcome(duration_seconds=now() - started)

    timed_out = False
    cancelled = False
    deadline = started + max(0.0, spec.timeout_seconds)
    try:
        while True:
            if child.poll() is not None:
                break
            if cancellation is not None and cancellation.cancelled:
                cancelled = True
                break
            if now() >= deadline:
                timed_out = True
                break
            # Waiting on the cancellation event rather than sleeping means a
            # cancel is observed as soon as it is raised, not up to one interval
            # later. With no signal to wait on, the interval is the poll period.
            if cancellation is not None:
                cancellation.wait(poll_interval)
            else:
                _time.sleep(poll_interval)
        if cancelled or timed_out:
            child.terminate(
                grace_seconds=spec.grace_seconds,
                kill_grace_seconds=spec.kill_grace_seconds,
            )
    finally:
        child.finish()
    return child.outcome(
        duration_seconds=now() - started, timed_out=timed_out, cancelled=cancelled
    )


def posix_only() -> bool:
    """Whether this platform can enforce the guarantees above.

    Process groups, ``0o600`` modes and the writable-by-other check are all
    POSIX. On Windows the code runs — the tests need it to — but the isolation
    is weaker, and a measurement or a security claim taken there is not a claim
    about the installed system. Reported rather than assumed so that a report
    can say which platform produced it.
    """
    return os.name == "posix" and sys.platform != "win32"
