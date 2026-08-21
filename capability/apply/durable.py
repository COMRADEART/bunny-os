# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Durable state that survives a crash without lying about what it survived.

The reservation ledger decides whether a service may start. If it comes back
from a crash believing memory is committed that is not, the machine gradually
refuses to start anything; if it comes back believing memory is free that is
not, it overcommits. Both failures are silent, and both are produced by the
obvious implementation — write JSON, rename over the old file — which is not
crash-safe on any filesystem in the presence of a power loss.

So this is the write path everything durable in the applicator goes through, and
it is deliberately boring:

1. Serialize with an explicit ``stateVersion`` and a content checksum.
2. Write to a temporary file **in the same directory**, so the rename is a
   rename and not a copy across filesystems.
3. ``flush()`` then ``os.fsync()`` the file — Python's buffer reaching the
   kernel is not the same as the kernel reaching the disk.
4. ``os.replace()`` — atomic on POSIX and on Windows.
5. ``fsync()`` the **directory**, so the rename itself is durable. Skipped where
   the platform does not support it, and recorded as skipped rather than
   assumed.

On read, a file whose checksum does not match its content, whose version is
unrecognised, or which does not parse is **not repaired by guessing**. It is
moved aside and the caller is told to enter safe mode. A ledger that silently
reset would hand out memory that is already in use; one that silently kept a
truncated tail would be worse.

**Safe mode is a first-class outcome, not an error path.** When state cannot be
trusted, the applicator observes and explains but does not apply. That is
strictly better than either guessing or refusing to run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Callable, Mapping

__all__ = [
    "DurableFile",
    "DurableState",
    "LoadOutcome",
    "STATE_VERSION",
    "SafeModeError",
    "checksum_of",
]

#: The on-disk format version. Bumped when the envelope changes, never when the
#: payload does — the payload carries its own version.
STATE_VERSION = 1

#: Envelope keys. Fixed so a hand-inspected file is readable and a future reader
#: can tell an envelope from a payload.
_ENVELOPE_KEYS = ("stateVersion", "revision", "checksum", "payload")


class SafeModeError(RuntimeError):
    """State could not be trusted, and the caller must not apply anything."""


def checksum_of(payload: Any) -> str:
    """A content checksum over the canonical form of the payload.

    Canonical because the checksum must not depend on key order: a file
    rewritten by a different Python version with different dict ordering would
    otherwise read as corrupt.
    """
    material = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(material.encode("ascii")).hexdigest()[:32]


@dataclass(frozen=True)
class LoadOutcome:
    """What came back from disk, and how much of it can be believed."""

    payload: Any
    revision: int
    #: True when the file was read and verified. False means the payload is the
    #: caller's default and safe mode applies.
    trusted: bool
    #: Empty when nothing was wrong.
    problems: tuple[str, ...] = ()
    #: Where a rejected file was moved, so it can be inspected rather than lost.
    quarantined_to: Path | None = None
    #: Temporary files from an interrupted write that were cleaned up.
    orphans_removed: tuple[str, ...] = ()

    @property
    def safe_mode(self) -> bool:
        return not self.trusted

    def to_json(self) -> dict[str, Any]:
        return {
            "trusted": self.trusted,
            "safeMode": self.safe_mode,
            "revision": self.revision,
            "problems": list(self.problems),
            "quarantinedTo": str(self.quarantined_to) if self.quarantined_to else None,
            "orphansRemoved": list(self.orphans_removed),
        }


@dataclass
class DurableFile:
    """One atomically-replaced, checksummed, versioned JSON file.

    ``fsync_enabled`` exists for tests and for filesystems where fsync is a
    no-op or prohibitively slow. Turning it off is a documented reduction in
    crash safety, reported through :meth:`describe`, never a silent default.
    """

    path: Path
    #: Permissions for the state file. Approval and reservation records are not
    #: world-readable: they name what a user was asked and what they answered.
    mode: int = 0o600
    directory_mode: int = 0o700
    fsync_enabled: bool = True
    #: Bumped on every successful write. Monotonic within a process; restored
    #: from disk on load, so a replayed older file is detectable.
    revision: int = 0
    #: Set when a write could not be persisted. The caller may still be correct
    #: in memory; durability is what was lost.
    last_write_failed: bool = False
    last_write_error: str = ""
    #: Injection hook for crash testing: called with the step name before each
    #: step. Raising from it simulates a crash at that exact point.
    crash_hook: Callable[[str], None] | None = None

    _directory_fsync_supported: bool = True

    # ------------------------------------------------------------------ #

    def _crash_point(self, name: str) -> None:
        if self.crash_hook is not None:
            self.crash_hook(name)

    def _temporary_prefix(self) -> str:
        return f".{self.path.name}.tmp-"

    def write(self, payload: Any) -> None:
        """Persist ``payload``. Raises only when the caller must know it failed.

        The five steps are separated so a crash hook can interrupt between any
        two of them, which is how the crash-recovery tests reach the states a
        real power loss produces.
        """
        self._crash_point("before-temporary-file")

        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(self.path.parent, self.directory_mode)
            except OSError:
                # A directory we do not own — a StateDirectory= systemd created,
                # for instance — is not ours to re-mode. Its permissions are the
                # unit's responsibility and are asserted separately.
                pass
        except OSError as exc:
            self.last_write_failed = True
            self.last_write_error = f"the state directory could not be created: {exc}"
            raise

        envelope = {
            "stateVersion": STATE_VERSION,
            "revision": self.revision + 1,
            "checksum": checksum_of(payload),
            "payload": payload,
        }
        body = json.dumps(envelope, indent=2, sort_keys=True) + "\n"

        handle = None
        temporary: Path | None = None
        try:
            descriptor, name = tempfile.mkstemp(
                prefix=self._temporary_prefix(), dir=str(self.path.parent),
            )
            temporary = Path(name)
            handle = os.fdopen(descriptor, "w", encoding="utf-8")

            self._crash_point("during-write")
            handle.write(body)

            self._crash_point("before-file-flush")
            handle.flush()
            if self.fsync_enabled:
                # flush() gets it to the kernel. fsync() gets it to the device.
                # Skipping this is the single most common way a "crash-safe"
                # writer turns out not to be.
                os.fsync(handle.fileno())
            handle.close()
            handle = None

            os.chmod(temporary, self.mode)

            self._crash_point("before-replace")
            os.replace(temporary, self.path)
            temporary = None

            self._crash_point("after-replace-before-directory-flush")
            if self.fsync_enabled:
                self._fsync_directory()

            self.revision += 1
            self.last_write_failed = False
            self.last_write_error = ""
        except BaseException as exc:
            self.last_write_failed = True
            self.last_write_error = f"{type(exc).__name__}: {exc}"
            if handle is not None:
                try:
                    handle.close()
                except OSError:
                    pass
            if temporary is not None:
                # The replace never happened, so the previous state is still on
                # disk and correct. Removing the temporary is cleanup, not
                # recovery, and its failure must not mask the original error.
                try:
                    temporary.unlink()
                except OSError:
                    pass
            raise

    def _fsync_directory(self) -> None:
        """Make the rename itself durable. Not supported everywhere."""
        try:
            descriptor = os.open(str(self.path.parent), os.O_RDONLY)
        except OSError:
            self._directory_fsync_supported = False
            return
        try:
            os.fsync(descriptor)
        except OSError:
            # Windows and some network filesystems refuse to fsync a directory.
            # Recorded rather than raised: the file itself is already durable,
            # and the residual risk is a rename that a power loss could undo.
            self._directory_fsync_supported = False
        finally:
            os.close(descriptor)

    # ------------------------------------------------------------------ #

    def load(self, default: Any) -> LoadOutcome:
        """Read and verify. Never raises; returns an outcome the caller acts on."""
        orphans = self._remove_orphans()

        if not self.path.is_file():
            # Nothing persisted yet is not a fault. A first boot is trusted with
            # the caller's empty default.
            return LoadOutcome(default, 0, True, orphans_removed=orphans)

        try:
            raw = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            return LoadOutcome(
                default, 0, False,
                (f"{self.path} could not be read: {exc}",),
                orphans_removed=orphans,
            )

        problems: list[str] = []
        try:
            envelope = json.loads(raw)
        except json.JSONDecodeError as exc:
            # A truncated write reaches here: valid JSON up to the cut, then EOF.
            problems.append(
                f"{self.path} is not valid JSON ({exc}); it was most likely truncated by an "
                "interrupted write"
            )
            return self._quarantine(default, problems, orphans)

        if not isinstance(envelope, Mapping):
            problems.append(f"{self.path} does not contain a state envelope object")
            return self._quarantine(default, problems, orphans)

        missing = [key for key in _ENVELOPE_KEYS if key not in envelope]
        if missing:
            problems.append(f"{self.path} is missing envelope field(s): {', '.join(missing)}")
            return self._quarantine(default, problems, orphans)

        version = envelope.get("stateVersion")
        if version != STATE_VERSION:
            # A future version is not corrupt; it is a downgrade, and guessing
            # at its meaning is how a newer format's reservations get dropped.
            problems.append(
                f"{self.path} declares stateVersion {version!r} and this build understands "
                f"{STATE_VERSION}; refusing to interpret it"
            )
            return self._quarantine(default, problems, orphans, move=False)

        payload = envelope.get("payload")
        expected = envelope.get("checksum")
        actual = checksum_of(payload)
        if expected != actual:
            problems.append(
                f"{self.path} checksum mismatch: the envelope records {expected!r} and the "
                f"payload hashes to {actual!r}; the file was modified or partially written"
            )
            return self._quarantine(default, problems, orphans)

        revision = envelope.get("revision")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
            problems.append(f"{self.path} has a non-monotonic revision {revision!r}")
            return self._quarantine(default, problems, orphans)

        self.revision = revision
        return LoadOutcome(payload, revision, True, orphans_removed=orphans)

    def _quarantine(
        self, default: Any, problems: list[str], orphans: tuple[str, ...], *, move: bool = True,
    ) -> LoadOutcome:
        """Move a file that cannot be trusted aside, and enter safe mode.

        Moved rather than deleted, always. The file is the only evidence of what
        went wrong, and a support question that begins "it reset itself" has no
        answer if the reader threw the file away.
        """
        destination: Path | None = None
        if move:
            candidate = self.path.with_suffix(self.path.suffix + ".corrupt")
            index = 0
            while candidate.exists() and index < 100:
                index += 1
                candidate = self.path.with_suffix(self.path.suffix + f".corrupt.{index}")
            try:
                os.replace(self.path, candidate)
                destination = candidate
            except OSError as exc:
                problems.append(f"the damaged file could not be moved aside: {exc}")
        return LoadOutcome(default, 0, False, tuple(problems), destination, orphans)

    def _remove_orphans(self) -> tuple[str, ...]:
        """Clean up temporary files left by an interrupted write.

        An interrupted write leaves a ``.tmp-`` file that is not state and never
        will be: the replace never happened, so the real file is either the
        previous good one or absent. Leaving them accumulates on a node whose
        storage is the constraint.
        """
        removed: list[str] = []
        prefix = self._temporary_prefix()
        try:
            entries = list(self.path.parent.iterdir())
        except OSError:
            return ()
        for entry in entries:
            if entry.name.startswith(prefix) and entry.is_file():
                try:
                    entry.unlink()
                    removed.append(entry.name)
                except OSError:
                    continue
        return tuple(sorted(removed))

    def describe(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "stateVersion": STATE_VERSION,
            "revision": self.revision,
            "mode": oct(self.mode),
            "fsyncEnabled": self.fsync_enabled,
            "directoryFsyncSupported": self._directory_fsync_supported,
            "lastWriteFailed": self.last_write_failed,
            "lastWriteError": self.last_write_error,
        }


@dataclass
class DurableState:
    """A durable file plus the safe-mode decision that comes with it.

    Wraps :class:`DurableFile` so that every consumer — the ledger, the approval
    store — reaches safe mode the same way rather than each inventing its own
    handling of a damaged file.
    """

    file: DurableFile
    default_factory: Callable[[], Any] = dict
    payload: Any = None
    outcome: LoadOutcome | None = None

    def load(self) -> LoadOutcome:
        result = self.file.load(self.default_factory())
        self.payload = result.payload
        self.outcome = result
        return result

    @property
    def safe_mode(self) -> bool:
        return self.outcome is not None and self.outcome.safe_mode

    def require_trusted(self, what: str) -> None:
        """Raise if the caller is about to act on state it cannot trust."""
        if self.safe_mode:
            problems = "; ".join(self.outcome.problems) if self.outcome else "unknown"
            raise SafeModeError(
                f"{what} refused: {self.file.path} could not be trusted ({problems}). "
                "The applicator observes and explains in safe mode; it does not apply."
            )

    def save(self, payload: Any) -> None:
        self.payload = payload
        self.file.write(payload)

    def describe(self) -> dict[str, Any]:
        return {
            **self.file.describe(),
            "safeMode": self.safe_mode,
            "outcome": self.outcome.to_json() if self.outcome else None,
        }
