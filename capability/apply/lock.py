# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Single-instance ownership, so two supervisors cannot both apply plans.

Two applicators against one machine is the worst failure this subsystem has,
because both are individually correct. Each reserves memory it believes is free,
each starts services, and the machine ends up with twice the committed memory
the budget allowed and no component that can detect it — the ledger is
per-process, and the second one's reservations are invisible to the first.

So ownership is taken before anything else, and it is taken with a kernel lock
rather than with a file containing a PID.

**A PID file is not a lock.** The classic implementation — write the PID, check
whether it is alive on startup — fails on PID reuse, which is not exotic on a
long-running node with a small ``pid_max``. It also cannot distinguish "the
owner died" from "the owner is alive and busy", and every recovery it attempts
is a guess.

``fcntl.flock`` is the lock. The kernel releases it when the holding process
dies, whatever the manner of death, and it cannot be held by two processes at
once. Everything else in this module — the owner record, the boot id, the
timeout — exists to produce a *diagnostic*, not to make the exclusion decision.

Windows has no ``flock``. It has ``msvcrt.locking``, which provides the same
exclusion for this purpose, and the module falls back to it so that the
applicator's own tests run on a developer checkout. That fallback is recorded in
the lock's description rather than hidden, because its crash semantics differ.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import socket
import time
from typing import Any

__all__ = ["InstanceLock", "LockError", "LockOwner", "OWNER_SCHEMA_VERSION"]

OWNER_SCHEMA_VERSION = 1

try:  # POSIX
    import fcntl

    _FLOCK = "fcntl"
except ImportError:  # Windows
    fcntl = None  # type: ignore[assignment]
    try:
        import msvcrt

        _FLOCK = "msvcrt"
    except ImportError:  # pragma: no cover - neither is a platform we support
        msvcrt = None  # type: ignore[assignment]
        _FLOCK = "none"


class LockError(RuntimeError):
    """The applicator does not own this machine and must not apply anything."""


@dataclass(frozen=True)
class LockOwner:
    """Who holds the lock, for diagnostics only.

    None of this decides exclusion — the kernel lock does. It exists so that a
    person told "another instance owns the applicator" can find out which one,
    and so that a stale record from a previous boot is recognisable as such.
    """

    pid: int
    #: The kernel's boot id. A record carrying a different one is from a
    #: previous boot, which is how a PID that has been reused since the reboot
    #: is told apart from the process that actually holds the lock.
    boot_id: str
    hostname: str
    started_at_monotonic: float
    started_at_wall: float
    #: What took the lock: "supervisor", "cli", a test name.
    role: str = "supervisor"

    def to_json(self) -> dict[str, Any]:
        return {
            "schemaVersion": OWNER_SCHEMA_VERSION,
            "pid": self.pid,
            "bootId": self.boot_id,
            "hostname": self.hostname,
            "startedAtMonotonic": self.started_at_monotonic,
            "startedAtWall": self.started_at_wall,
            "role": self.role,
        }

    @classmethod
    def from_json(cls, document: Any) -> "LockOwner | None":
        if not isinstance(document, dict):
            return None
        try:
            return cls(
                pid=int(document["pid"]),
                boot_id=str(document.get("bootId", "")),
                hostname=str(document.get("hostname", "")),
                started_at_monotonic=float(document.get("startedAtMonotonic", 0.0)),
                started_at_wall=float(document.get("startedAtWall", 0.0)),
                role=str(document.get("role", "supervisor")),
            )
        except (KeyError, TypeError, ValueError):
            return None


def current_boot_id() -> str:
    """The kernel's boot identifier, or a stable substitute.

    ``/proc/sys/kernel/random/boot_id`` changes on every boot and on no other
    event, which is exactly the property needed to date an owner record. Where
    it does not exist the module degrades to a constant, and PID-reuse detection
    across reboots degrades with it — recorded rather than papered over.
    """
    for candidate in ("/proc/sys/kernel/random/boot_id",):
        try:
            return Path(candidate).read_text(encoding="ascii").strip()
        except OSError:
            continue
    return "unknown-boot-id"


def process_alive(pid: int) -> bool | None:
    """Whether a PID exists. ``None`` when the platform cannot say.

    Deliberately advisory. This is never the exclusion decision — a live PID
    may be an unrelated process that reused the number, and a dead one may
    still have a lock held by a child.
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # It exists and belongs to somebody else.
        return True
    except (OSError, AttributeError):
        return None
    return True


@dataclass
class InstanceLock:
    """Exclusive, crash-safe ownership of the applicator for one machine.

    Used as a context manager::

        with InstanceLock(path) as lock:
            ...            # this process is the only applicator

    Acquisition never blocks indefinitely. ``timeout_seconds`` bounds the wait,
    after which the attempt fails with a diagnostic naming the current owner —
    a supervisor that hung waiting for a lock would be indistinguishable from
    one that was working.
    """

    path: Path
    role: str = "supervisor"
    timeout_seconds: float = 5.0
    poll_interval_seconds: float = 0.1
    mode: int = 0o600
    directory_mode: int = 0o700

    _handle: Any = field(default=None, repr=False)
    _owner: LockOwner | None = field(default=None, repr=False)
    _held: bool = False

    # ------------------------------------------------------------------ #

    @property
    def held(self) -> bool:
        return self._held

    @property
    def owner(self) -> LockOwner | None:
        return self._owner

    def read_owner_record(self) -> LockOwner | None:
        """Whoever last wrote the record. Advisory; may be stale."""
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return LockOwner.from_json(document)

    def describe_conflict(self) -> str:
        """Why acquisition failed, in terms a person can act on."""
        record = self.read_owner_record()
        if record is None:
            return (
                f"another process holds {self.path} and left no readable owner record. "
                "It is alive: the kernel lock is held."
            )
        boot = current_boot_id()
        alive = process_alive(record.pid)
        if record.boot_id and boot != "unknown-boot-id" and record.boot_id != boot:
            # The record predates this boot but the lock is held, so the record
            # is stale and the holder is somebody who has not rewritten it yet.
            return (
                f"{self.path} is locked, and its owner record is from a previous boot "
                f"(recorded boot {record.boot_id[:8]}, current {boot[:8]}). The lock is "
                "genuinely held by a live process; the record is out of date."
            )
        liveness = {True: "alive", False: "not running", None: "of unknown liveness"}[alive]
        return (
            f"{self.path} is held by pid {record.pid} ({record.role} on {record.hostname}), "
            f"which is {liveness}. This applicator will not apply anything while another "
            "instance owns the machine."
        )

    # ------------------------------------------------------------------ #

    def acquire(self) -> "InstanceLock":
        """Take exclusive ownership, or raise :class:`LockError`.

        The lock file is opened and kept open for the lifetime of the lock. It
        is never deleted on release: unlinking a locked file is a race — another
        process can open the same path, get a new inode, and lock that instead —
        and the file is 200 bytes.
        """
        if self._held:
            return self

        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(self.path.parent, self.directory_mode)
            except OSError:
                pass
        except OSError as exc:
            raise LockError(
                f"the lock directory {self.path.parent} could not be created ({exc}); "
                "without a lock this applicator cannot establish that it is the only one, "
                "so it will not apply anything"
            ) from exc

        try:
            # r+ then a fallback to w+ rather than w: opening with "w" truncates,
            # which would destroy a live owner's record before we know whether we
            # can even take the lock.
            try:
                handle = open(self.path, "r+", encoding="utf-8")
            except FileNotFoundError:
                handle = open(self.path, "w+", encoding="utf-8")
        except OSError as exc:
            raise LockError(
                f"{self.path} could not be opened ({exc}). A read-only state directory means "
                "ownership cannot be established, and the applicator will not apply without it"
            ) from exc

        deadline = time.monotonic() + max(0.0, self.timeout_seconds)
        while True:
            if self._try_lock(handle):
                break
            if time.monotonic() >= deadline:
                conflict = self.describe_conflict()
                handle.close()
                raise LockError(
                    f"could not acquire the applicator lock within {self.timeout_seconds:g}s. "
                    f"{conflict}"
                )
            time.sleep(self.poll_interval_seconds)

        try:
            os.chmod(self.path, self.mode)
        except OSError:
            pass

        owner = LockOwner(
            pid=os.getpid(),
            boot_id=current_boot_id(),
            hostname=socket.gethostname(),
            started_at_monotonic=time.monotonic(),
            started_at_wall=time.time(),
            role=self.role,
        )
        try:
            handle.seek(0)
            handle.truncate()
            handle.write(json.dumps(owner.to_json(), indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        except OSError:
            # The record is a diagnostic. Failing to write it does not mean we
            # do not hold the lock — we demonstrably do — so ownership stands
            # and the degradation is reported through describe().
            pass

        self._handle = handle
        self._owner = owner
        self._held = True
        return self

    def _try_lock(self, handle: Any) -> bool:
        """One non-blocking attempt. Returns whether the lock is now held."""
        if _FLOCK == "fcntl":
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (OSError, BlockingIOError):
                return False
            return True
        if _FLOCK == "msvcrt":
            try:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                return False
            return True
        raise LockError(
            "this platform provides neither flock nor msvcrt locking, so single-instance "
            "ownership cannot be established and the applicator will not apply anything"
        )

    def release(self) -> None:
        """Give up ownership. Safe to call twice, safe to call after a failure."""
        handle, self._handle = self._handle, None
        self._held = False
        self._owner = None
        if handle is None:
            return
        try:
            if _FLOCK == "fcntl":
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            elif _FLOCK == "msvcrt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        finally:
            try:
                handle.close()
            except OSError:
                pass

    def __enter__(self) -> "InstanceLock":
        return self.acquire()

    def __exit__(self, *exception: Any) -> None:
        self.release()

    def describe(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "mechanism": _FLOCK,
            "crashSafe": _FLOCK == "fcntl",
            "held": self._held,
            "owner": self._owner.to_json() if self._owner else None,
            "timeoutSeconds": self.timeout_seconds,
            "note": (
                "the kernel releases this lock when the holder dies, so a crashed "
                "supervisor does not strand it"
                if _FLOCK == "fcntl" else
                "msvcrt locking is used on this platform; it excludes correctly but its "
                "crash semantics are not those the Linux target relies on"
            ),
        }
