# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The second transport: a short allowlist of programs, run the hardened way.

Some desktop facts have no D-Bus interface worth the name. The mixer is one:
PulseAudio and PipeWire are both driven by ``pactl`` in practice, and pretending
otherwise would mean writing a protocol client to avoid writing an argv. So
there is a command transport, and it is deliberately built on the runner this
codebase already has rather than on a second one.

:mod:`companion.voice.execution` is that runner. It resolves an executable
through :data:`~companion.voice.execution.TRUSTED_DIRECTORIES` rather than an
inherited ``PATH``, refuses anything group- or world-writable, refuses a
substituted symlink, builds the child's environment instead of inheriting it,
puts the child in its own process group, bounds its stderr, and always reaps it.
Every one of those was written because of something that happened. Copying it
here would produce a second implementation of the same rules — which is exactly
the failure ``build/scripts/install_routes.py`` exists to prevent, one layer up:
two lists, two truths, and eventually a difference nobody notices.

What is *not* shared is the allowlist. :data:`ALLOWED_EXECUTABLES` here is the
desktop's own, and it does not intersect the voice one except where the same
program genuinely does both jobs. A single joint allowlist would mean adding a
synthesiser also added it to the desktop broker's reach.

Two shapes of child, because the desktop needs both:

:func:`run_command`
    start, wait, reap. Everything except the clipboard.
:class:`BackgroundChild`
    start and **keep**. A Wayland clipboard selection belongs to a living
    process: ``wl-copy --foreground`` holds it until it is killed, which is what
    makes "release the clipboard on cancellation" (§4.7, §10) an operation that
    exists rather than a wish. The child is owned by this object, its process
    group is signalled on release, and it is always waited for.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import signal
import subprocess
import threading
import time
from typing import Any, Mapping, Sequence

from ...voice.execution import (
    CommandOutcome,
    CommandSpec,
    ExecutableRefused,
    child_environment,
    resolve_executable,
    run,
)
from ..errors import DesktopUnavailable

__all__ = [
    "ALLOWED_EXECUTABLES",
    "BackgroundChild",
    "CommandUnavailable",
    "capture_command",
    "desktop_environment",
    "have",
    "run_command",
]

#: The most stdout kept from a program run for its answer. A mixer that prints a
#: megabyte is a mixer this build does not understand, and reading all of it
#: into memory is not needed to say so.
MAX_CAPTURED_BYTES = 64 * 1024


class CommandUnavailable(DesktopUnavailable):
    """A program this transport needs is not installed or may not be run."""


#: Every program the desktop broker may start, by base name, with the one thing
#: each is for. A name absent from this set is refused before anything touches
#: the filesystem.
#:
#: There is no shell here, no ``xdg-open``, no ``sh``, no ``env``, no ``dbus-send``
#: and no ``gdbus``. The last two are the interesting absences: both are generic
#: D-Bus clients, and having one on this list would undo
#: :mod:`companion.desktop.adapters.dbus` entirely.
ALLOWED_EXECUTABLES: Mapping[str, str] = {
    # Audio: read and set the output volume and mute.
    "pactl": "read and set the default or approved output sink's volume",
    # Do-not-disturb, on desktops that keep it in GSettings.
    "gsettings": "read and set the do-not-disturb value",
    # Clipboard ownership, Wayland and X11 respectively.
    "wl-copy": "hold the Wayland clipboard selection with given text",
    "xclip": "hold the X11 clipboard selection with given text",
    # Settings pages, per environment. Each takes a panel name from a closed
    # enum this package owns; none takes anything a provider supplied.
    "gnome-control-center": "open one settings page on GNOME",
    "systemsettings": "open one settings page on KDE",
    "systemsettings5": "open one settings page on KDE Plasma 5",
    # The notification fallback for a session with no notification daemon on
    # the bus but a working `notify-send`. Recorded when used; never silent.
    "notify-send": "show one notification when the session bus has no daemon",
}

#: Environment variables a desktop child needs on top of the voice runner's
#: allowlist, and why each. Read from this process's environment and passed
#: explicitly, so :func:`companion.voice.execution.child_environment` still gets
#: to refuse the dangerous names.
_DESKTOP_ENVIRONMENT = (
    # How a client finds the compositor, and which one it is.
    "WAYLAND_DISPLAY",
    "DISPLAY",
    "XAUTHORITY",
    "XDG_SESSION_TYPE",
    "XDG_CURRENT_DESKTOP",
    "XDG_SESSION_DESKTOP",
    # How a client finds the session bus, when it is not at the default path.
    "DBUS_SESSION_BUS_ADDRESS",
    # Where installed applications and their icons are, so a settings program
    # and a launcher agree with the entry resolution in companion.desktop.entries.
    "XDG_DATA_DIRS",
    "XDG_DATA_HOME",
    "XDG_CONFIG_HOME",
    # GSettings needs its schema directory when the schemas are not in the
    # default location, which is the case in a development tree.
    "GSETTINGS_SCHEMA_DIR",
)


def desktop_environment(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """The environment a desktop child gets. Built, never inherited.

    The names above are added to the voice runner's own allowlist and then run
    through its denylist, so ``LD_PRELOAD``, ``PYTHONPATH`` and the proxy
    variables cannot be reintroduced by anything here.
    """
    values = {
        name: os.environ[name]
        for name in _DESKTOP_ENVIRONMENT
        if os.environ.get(name)
    }
    values.update({key: str(value) for key, value in (extra or {}).items()})
    return child_environment(extra=values)


def have(name: str) -> bool:
    """Whether an allowlisted program is installed and runnable.

    Availability of the *program*, which §16 says is not availability of the
    *action*. An adapter calls this and then checks that the service it drives
    is actually answering; neither check alone is enough.
    """
    if name not in ALLOWED_EXECUTABLES:
        return False
    try:
        resolve_executable(name, allowlist=ALLOWED_EXECUTABLES)
    except ExecutableRefused:
        return False
    return True


def run_command(
    name: str,
    arguments: Sequence[str],
    *,
    stdin_text: str = "",
    timeout_seconds: float = 10.0,
    cancellation: Any = None,
    environment: Mapping[str, str] | None = None,
) -> CommandOutcome:
    """Start one allowlisted program with an argument array, and wait for it.

    Every argument is a string this package produced: a sink identifier read
    from ``pactl``, a percentage from a validated integer, a settings panel from
    a closed enum. No caller passes a string through from a provider, and there
    is no parameter here through which one could.
    """
    if name not in ALLOWED_EXECUTABLES:
        raise CommandUnavailable(
            f"{name!r} is not in the desktop broker's executable allowlist; this build starts "
            f"only {', '.join(sorted(ALLOWED_EXECUTABLES))}"
        )
    for index, item in enumerate(arguments):
        if not isinstance(item, str):
            raise CommandUnavailable(f"argument {index} of {name} is not a string")
        if "\x00" in item:
            raise CommandUnavailable(f"argument {index} of {name} contains a null byte")
    try:
        executable, trusted = resolve_executable(name, allowlist=ALLOWED_EXECUTABLES)
    except ExecutableRefused as exc:
        raise CommandUnavailable(str(exc)) from None
    spec = CommandSpec(
        executable=executable,
        arguments=tuple(arguments),
        stdin_text=stdin_text,
        # Never in an argument. An argv is readable in /proc by everything the
        # user runs, so clipboard text goes through stdin or not at all.
        text_argument_index=None,
        environment=desktop_environment(environment),
        timeout_seconds=timeout_seconds,
    )
    outcome = run(spec, cancellation=cancellation)
    if not trusted:
        # A development machine with no trusted directory. Said in the outcome
        # rather than hidden, because a measurement taken here is not a
        # measurement of the installed system.
        return CommandOutcome(
            executable=outcome.executable,
            redacted_argv=outcome.redacted_argv,
            exit_code=outcome.exit_code,
            duration_seconds=outcome.duration_seconds,
            stderr=(outcome.stderr + "\n[resolved outside a trusted directory]").strip(),
            stderr_truncated=outcome.stderr_truncated,
            timed_out=outcome.timed_out,
            cancelled=outcome.cancelled,
            terminated=outcome.terminated,
            killed=outcome.killed,
            reaped=outcome.reaped,
            start_error=outcome.start_error,
        )
    return outcome


def capture_command(
    name: str,
    arguments: Sequence[str],
    *,
    timeout_seconds: float = 5.0,
) -> str | None:
    """Run one allowlisted program **for its answer**, and return its stdout.

    Separate from :func:`run_command` because the runner this package is built
    on deliberately keeps stderr and discards stdout: the voice runtime never
    needed a value back from a child, and widening that runner for two callers
    here would change a module three qualified phases depend on. So this is a
    second, much smaller path — same allowlisted resolution, same built
    environment, bounded output, always reaped — used only where the *value* is
    the point: reading a volume, reading a setting.

    Returns ``None`` for every failure. A caller that needs to distinguish "not
    installed" from "exited non-zero" uses :func:`have` first; a caller reading
    a value needs only "there is no value", and collapsing the failures here
    keeps that caller from having to invent a meaning for each one.
    """
    if name not in ALLOWED_EXECUTABLES:
        raise CommandUnavailable(f"{name!r} is not in the desktop broker's executable allowlist")
    for item in arguments:
        if not isinstance(item, str) or "\x00" in item:
            raise CommandUnavailable(f"an argument to {name} is not a usable string")
    try:
        executable, _trusted = resolve_executable(name, allowlist=ALLOWED_EXECUTABLES)
    except ExecutableRefused:
        return None
    try:
        completed = subprocess.run(  # noqa: S603 - argv array, allowlisted, built environment
            [executable, *arguments],
            capture_output=True,
            env=desktop_environment(),
            timeout=max(0.5, float(timeout_seconds)),
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout[:MAX_CAPTURED_BYTES].decode("utf-8", errors="replace")


@dataclass
class _ChildState:
    process: Any = None
    started_at: float = 0.0
    released: bool = False
    release_reason: str = ""


class BackgroundChild:
    """A long-lived child this object owns, for holding a clipboard selection.

    Distinguished from :func:`run_command` by what "success" means. A command
    succeeds by *finishing*; this succeeds by **continuing**. So the checks are
    inverted: after starting, a child that has already exited is a failure, and
    a child still running after the settle window is the ownership observation.

    :meth:`release` is idempotent, signals the whole process group, escalates
    from ``SIGTERM`` to ``SIGKILL``, and always waits. The escalation exists
    because ``wl-copy`` installs no handler for a group signal in some versions
    and a clipboard owner that survives the release would leave the user's
    clipboard held by a task that ended.
    """

    #: How long to wait before deciding the child is holding the selection. Long
    #: enough for a compositor round trip, short enough not to dominate §24's
    #: clipboard-ownership latency figure.
    SETTLE_SECONDS = 0.15

    def __init__(self, name: str, arguments: Sequence[str], *, stdin_text: str = "") -> None:
        if name not in ALLOWED_EXECUTABLES:
            raise CommandUnavailable(f"{name!r} is not in the desktop broker's executable allowlist")
        self.name = name
        self._arguments = tuple(arguments)
        self._stdin_text = stdin_text
        self._guard = threading.RLock()
        self._state = _ChildState()

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        try:
            executable, _trusted = resolve_executable(self.name, allowlist=ALLOWED_EXECUTABLES)
        except ExecutableRefused as exc:
            raise CommandUnavailable(str(exc)) from None
        with self._guard:
            if self._state.process is not None:
                raise CommandUnavailable(f"this {self.name} child has already been started")
            keywords: dict[str, Any] = {}
            if os.name == "posix":
                # Its own process group, so a release signals the child and
                # anything it forked rather than only the leader.
                keywords["start_new_session"] = True
            try:
                process = subprocess.Popen(  # noqa: S603 - argv array, allowlisted, built environment
                    [executable, *self._arguments],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    env=desktop_environment(),
                    close_fds=True,
                    **keywords,
                )
            except OSError as exc:
                raise CommandUnavailable(f"{self.name} could not be started: {exc}") from None
            self._state = _ChildState(process=process, started_at=time.monotonic())

        # The text goes down stdin and the pipe is closed, which is how
        # `wl-copy` knows the value is complete. Never an argument: an argv is
        # world-readable in /proc, and this is the one place user text travels.
        #
        # Checked rather than asserted: `python -O` removes an assert, and the
        # AttributeError that would follow is not in the except clause below —
        # so the one line that moves the user's text would raise a different
        # exception under a flag nobody sets deliberately.
        stream = process.stdin
        if stream is None:
            return
        try:
            stream.write(self._stdin_text.encode("utf-8"))
            stream.flush()
            stream.close()
        except (BrokenPipeError, OSError, ValueError):
            # The child died before it read anything. `holding` will report it.
            pass

    def holding(self, *, settle_seconds: float | None = None) -> bool:
        """Whether the child is alive and therefore owns the selection."""
        delay = self.SETTLE_SECONDS if settle_seconds is None else settle_seconds
        with self._guard:
            process = self._state.process
            if process is None or self._state.released:
                return False
        if delay > 0:
            time.sleep(delay)
        return process.poll() is None

    @property
    def released(self) -> bool:
        with self._guard:
            return self._state.released

    @property
    def pid(self) -> int:
        with self._guard:
            process = self._state.process
            return int(process.pid) if process is not None else 0

    def stderr_text(self) -> str:
        with self._guard:
            process = self._state.process
        if process is None or process.stderr is None:
            return ""
        try:
            data = process.stderr.read(4096) or b""
        except (OSError, ValueError):
            return ""
        return data.decode("utf-8", errors="replace").strip()

    def release(self, reason: str = "released") -> bool:
        """Give up the selection. Idempotent; returns whether this call did it."""
        with self._guard:
            process = self._state.process
            if process is None or self._state.released:
                return False
            self._state.released = True
            self._state.release_reason = reason

        if process.poll() is not None:
            _drain(process)
            return True
        _signal_group(process, signal.SIGTERM)
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            _signal_group(process, signal.SIGKILL)
            try:
                process.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                # Recorded rather than raised. A child that survives both
                # signals is a fact the result must carry, and raising here
                # would lose the rest of the release.
                pass
        _drain(process)
        return True

    def __enter__(self) -> "BackgroundChild":
        self.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release("scope exited")


def _signal_group(process: Any, number: int) -> None:
    try:
        if os.name == "posix":
            os.killpg(os.getpgid(process.pid), number)
        else:  # pragma: no cover - development machines only
            process.terminate()
    except (ProcessLookupError, PermissionError, OSError):
        try:
            process.send_signal(number)
        except (ProcessLookupError, OSError, ValueError):
            pass


def _drain(process: Any) -> None:
    """Close the child's pipes so no descriptor outlives it.

    §23 counts file descriptors across a hundred runs. A pipe left open per
    clipboard action is exactly the shape of leak that gate is for.
    """
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is None:
            continue
        try:
            stream.close()
        except (OSError, ValueError):
            pass
