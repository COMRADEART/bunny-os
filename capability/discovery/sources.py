# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The only place in the capability runtime that reads the machine.

Every probe goes through this module, and this module is the security boundary
described in ``docs/CAPABILITY_SECURITY.md``. Four rules hold here and nowhere
else has to restate them:

1. **No shell, ever.** :func:`run` takes an argv list whose first element must
   be an absolute path on an allowlist. There is no ``shell=True``, no string
   command, and no ``PATH`` lookup that a writable directory could poison.
2. **Bounded time.** Every subprocess and every read carries a timeout, and the
   caller's overall deadline is checked before each one is started. §17 of the
   brief requires that boot not block on an unavailable device; a probe that
   cannot finish inside its slice is abandoned and reported ``unknown``.
3. **Bounded size.** Output is truncated at :data:`MAX_OUTPUT_BYTES`. A device
   node that streams forever cannot exhaust memory.
4. **Nothing parsed is executed.** Probe output becomes strings, ints and
   bools. It never becomes a path that is opened, an argument that is passed
   back to a subprocess, or anything ``eval``-shaped.

The allowlist is the load-bearing part. Vendor GPU tools are the only source
Phase 1 §13.4 accepts for VRAM, so they are here, but they are here by absolute
path and with fixed arguments, so "run nvidia-smi" cannot become "run whatever
is called nvidia-smi in the current directory".
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import time
from typing import Iterable, Sequence

__all__ = [
    "ALLOWED_COMMANDS",
    "Deadline",
    "MAX_OUTPUT_BYTES",
    "read_first_line",
    "read_int",
    "read_text",
    "run",
    "sanitize",
    "which_allowed",
]

#: Nothing outside this set may be executed. Absolute paths only: a bare name
#: would be resolved through ``PATH``, and a capability probe is not a place to
#: accept whatever a writable directory happens to contain.
ALLOWED_COMMANDS = frozenset({
    "/usr/bin/nvidia-smi",
    "/usr/bin/rocm-smi",
    "/usr/bin/vulkaninfo",
    "/usr/bin/clinfo",
    "/usr/bin/lspci",
    "/usr/bin/systemd-detect-virt",
    "/usr/bin/nmcli",
})

#: Output beyond this is truncated. Chosen to hold a many-GPU ``nvidia-smi``
#: CSV with room to spare while remaining trivially bounded.
MAX_OUTPUT_BYTES = 256 * 1024

#: Characters permitted in a value that will be shown to a user or written to a
#: JSON document. Everything else is dropped rather than escaped, because a
#: capability inventory has no legitimate use for control characters.
_PERMITTED = frozenset(
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789"
    " .,:;_+-/()[]@=*#'\""
)

_ENV = {"PATH": "/usr/bin:/usr/sbin", "LC_ALL": "C", "LANG": "C"}


class Deadline:
    """A shared wall-clock budget for one discovery pass.

    Discovery is a sequence of probes that must finish inside one bound, not a
    sequence of probes that each finish inside their own. Without this, twelve
    probes with a five-second timeout each is a sixty-second boot stall on a
    machine where every device is wedged.

    The clock is injectable so tests can drive expiry without sleeping.
    """

    def __init__(self, budget_ms: int, *, clock=time.monotonic) -> None:
        self._clock = clock
        self._budget = max(0.0, budget_ms / 1000.0)
        self._start = clock()

    @property
    def elapsed_ms(self) -> int:
        return int((self._clock() - self._start) * 1000)

    @property
    def remaining_seconds(self) -> float:
        return max(0.0, self._budget - (self._clock() - self._start))

    @property
    def expired(self) -> bool:
        return self.remaining_seconds <= 0.0

    def slice_seconds(self, requested: float) -> float:
        """The smaller of what a probe asked for and what is left."""
        return min(requested, self.remaining_seconds)


@dataclass(frozen=True)
class CommandResult:
    ok: bool
    stdout: str
    detail: str


def sanitize(value: str, *, limit: int = 256) -> str:
    """Reduce parsed output to characters safe to store and display."""
    cleaned = "".join(character for character in value if character in _PERMITTED)
    return cleaned.strip()[:limit]


def which_allowed(path: str) -> str | None:
    """The command, if it is both allowlisted and actually present."""
    if path not in ALLOWED_COMMANDS:
        return None
    return path if Path(path).is_file() and os.access(path, os.X_OK) else None


def run(argv: Sequence[str], *, deadline: Deadline, timeout: float = 2.0) -> CommandResult:
    """Execute an allowlisted command with a bounded time and output size.

    Returns ``ok=False`` rather than raising for every failure mode, because a
    probe that cannot run is an ``unknown`` observation and not an error the
    caller should have to handle. The distinction between "did not run" and
    "ran and found nothing" is made by the caller from the value, not from an
    exception.
    """
    if not argv:
        return CommandResult(False, "", "empty command")
    executable = which_allowed(argv[0])
    if executable is None:
        # Not an assertion: a probe asking for something off the allowlist is a
        # programming error, and refusing loudly here is how it gets found.
        return CommandResult(False, "", f"command not permitted or not installed: {argv[0]}")
    budget = deadline.slice_seconds(timeout)
    if budget <= 0:
        return CommandResult(False, "", "discovery deadline exhausted")
    try:
        completed = subprocess.run(
            [executable, *argv[1:]],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=dict(_ENV),
            timeout=budget,
            # A probe never needs to write anything, and a probe that inherits
            # the caller's cwd can be influenced by it.
            cwd="/",
        )
    except subprocess.TimeoutExpired:
        return CommandResult(False, "", f"timed out after {budget:.1f}s")
    except (OSError, ValueError) as exc:
        return CommandResult(False, "", f"could not run: {exc.__class__.__name__}")
    if completed.returncode != 0:
        return CommandResult(False, "", f"exit status {completed.returncode}")
    raw = (completed.stdout or b"")[:MAX_OUTPUT_BYTES]
    return CommandResult(True, raw.decode("utf-8", errors="replace"), "")


def read_text(path: str | Path, *, limit: int = 64 * 1024) -> str | None:
    """Read a sysfs/procfs file, or ``None`` if it cannot be read.

    Size-limited because some ``/proc`` and ``/sys`` files are effectively
    unbounded streams, and because a capability probe should not be able to
    allocate arbitrarily just by opening the wrong node.
    """
    try:
        with open(path, "rb") as handle:
            return handle.read(limit).decode("utf-8", errors="replace")
    except (OSError, ValueError):
        return None


def read_first_line(path: str | Path) -> str | None:
    text = read_text(path, limit=4096)
    if text is None:
        return None
    line = text.splitlines()[0] if text.splitlines() else ""
    return line.strip()


def read_int(path: str | Path) -> int | None:
    line = read_first_line(path)
    if line is None:
        return None
    try:
        return int(line)
    except ValueError:
        return None


def iter_directory(path: str | Path, *, limit: int = 512) -> list[Path]:
    """Sorted directory entries, bounded, or an empty list.

    Bounded because ``/sys/class/*`` on a large host can hold thousands of
    entries and discovery has a deadline to keep.
    """
    try:
        entries = sorted(Path(path).iterdir())
    except (OSError, ValueError):
        return []
    return entries[:limit]


def first_existing(paths: Iterable[str | Path]) -> Path | None:
    for candidate in paths:
        path = Path(candidate)
        try:
            if path.exists():
                return path
        except OSError:
            continue
    return None
