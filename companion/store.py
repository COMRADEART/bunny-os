# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Where the companion's memory lives, on a machine that may lose power.

No database. The brief asks for a store consistent with constrained-device
goals, and a session's history is an append-only sequence of small records read
in order — which is a log, and a log implemented as a log costs a file handle,
whereas a log implemented on top of a database costs a database. Bunny OS is
expected to run in 64 MB; the qualified base image does not carry a server, and
adding one to hold a few thousand JSON objects would be a dependency taken for
familiarity rather than need. If a future phase adds an access pattern this
cannot serve — full-text search across sessions is the obvious one — that is the
documented need and the decision can be revisited then.

The layout, per store root:

    store.json                      what this store is, and its schema version
    sessions/<id>/session.json      the session projection
    sessions/<id>/stream.json       the stream's anchor, retention and migrations
    sessions/<id>/events.jsonl      the append-only event chain, one JSON per line
    sessions/<id>/tasks/<id>.json   task projections

**Appends are durable before they are acknowledged.** A record is written,
``flush``ed and ``fsync``ed while the session lock is held, and only then does
:meth:`CompanionStore.append` return. A caller that has been told an event was
appended can rely on it having survived the power going out.

**Projections are replaced, never edited.** ``session.json`` and each task
document are written to a temporary file, fsynced, and moved into place with
``os.replace``, which is atomic. A reader therefore sees either the old document
or the new one and never a half-written one.

**A projection is never trusted over the stream.** The projection exists to make
opening a session cheap, not to be authoritative. Every load compares the
projection's revision against the stream's tip, and :mod:`companion.recovery`
rebuilds from the stream whenever they disagree — which they will, every time a
process dies between the append and the projection write. That window cannot be
closed without a transaction across two files; it can be made harmless, and
this is how.

**Nothing is ever invented.** A truncated final record is dropped and reported,
because a process that died mid-write leaves exactly that and the alternative is
refusing to open a session over one broken line. Anything else wrong — a bad
hash in the middle, a sequence gap, a duplicate id — raises. The store will not
manufacture a missing event to make a chain verify, and
:meth:`CompanionStore.migrate` verifies a chain *before* re-sealing it, so a
migration cannot be used to launder a stream that would otherwise be refused.

**Everything is owner-only.** Files are created 0600 and directories 0700, with
``O_NOFOLLOW`` on the append path — not left to the umask, and not resting on the
parent directory, because the store root is configurable and can be pointed
somewhere another user can write.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import stat
import tempfile
import time
from typing import Any, Iterator, Mapping, Sequence

from . import EVENT_SCHEMA_VERSION, STORE_SCHEMA_VERSION
from .errors import IntegrityError, SchemaError, StoreError
from .events import GENESIS_HASH, HASHED_FIELDS_BY_VERSION, TaskEvent, verify_chain
from .ids import valid_id
from .session import CompanionSession
from .task import CompanionTask

__all__ = [
    "CompanionStore",
    "DEFAULT_RETENTION",
    "FileLock",
    "RetentionPolicy",
    "StoreReport",
    "StreamRead",
]

#: How long to wait for another process to release a session lock before giving
#: up. Long enough to outlast an ordinary append, short enough that a user
#: waiting on a CLI command is not left wondering.
LOCK_TIMEOUT_SECONDS = 10.0

#: After this long a lock file is assumed to belong to a process that died. A
#: crashed runtime must not make a session permanently unopenable.
LOCK_STALE_SECONDS = 120.0


@dataclass(frozen=True)
class RetentionPolicy:
    """How much history a session keeps.

    Retention removes events from the *front* of a chain, never the middle, and
    records what it removed together with the hash the new head follows. A
    reader can then verify everything that remains and can tell that the stream
    begins where it does by policy — a chain that simply started at sequence 4801
    with no explanation is indistinguishable from one somebody edited.
    """

    #: Hard ceiling. Reaching it is refused rather than silently wrapped: a
    #: session that has produced a hundred thousand events has a defect in it,
    #: and quietly discarding the evidence would hide the defect.
    maximum_events: int = 100_000
    #: Events kept when :meth:`CompanionStore.prune` runs.
    retained_events: int = 10_000

    def __post_init__(self) -> None:
        if self.retained_events < 1 or self.maximum_events < self.retained_events:
            raise SchemaError("retention must keep at least one event and no more than the maximum")


DEFAULT_RETENTION = RetentionPolicy()


class FileLock:
    """An exclusive, advisory lock over one session directory.

    Three implementations, tried in order: POSIX ``fcntl.flock`` (what the
    installed system uses), Windows ``msvcrt.locking``, and — where neither
    exists — an ``O_EXCL`` lock file with a staleness timeout. The fallback is
    weaker and says so: it cannot distinguish a live holder from a dead one
    except by age, which is why the age is generous.
    """

    def __init__(self, path: Path, *, timeout: float = LOCK_TIMEOUT_SECONDS) -> None:
        self.path = path
        self.timeout = timeout
        self._handle: Any = None
        self._mode = "none"

    def __enter__(self) -> "FileLock":
        self.acquire()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()

    def acquire(self) -> None:
        _private_directory(self.path.parent)
        deadline = time.monotonic() + self.timeout
        try:
            import fcntl
        except ImportError:
            fcntl = None  # type: ignore[assignment]
        try:
            import msvcrt
        except ImportError:
            msvcrt = None  # type: ignore[assignment]

        while True:
            try:
                # 0600 and no symlink follow, like every other file the store
                # creates. A lock file is empty, but its *existence and name*
                # enumerate a user's sessions, and it sits in the same
                # attacker-writable-root scenario as the event log.
                flags = os.O_RDWR | os.O_CREAT
                flags |= getattr(os, "O_NOFOLLOW", 0)
                handle = os.fdopen(os.open(self.path, flags, _FILE_MODE), "a+b")
            except OSError as exc:
                raise StoreError(f"the session lock at {self.path} could not be opened: {exc}") from exc
            try:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self._mode = "flock"
                elif msvcrt is not None:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    self._mode = "msvcrt"
                else:
                    handle.close()
                    self._acquire_exclusive_file(deadline)
                    return
            except OSError:
                handle.close()
                if time.monotonic() >= deadline:
                    raise StoreError(
                        f"another process has held the session lock at {self.path} for "
                        f"longer than {self.timeout:g}s; nothing was written"
                    ) from None
                time.sleep(0.02)
                continue
            self._handle = handle
            return

    def _acquire_exclusive_file(self, deadline: float) -> None:
        marker = self.path.with_suffix(self.path.suffix + ".excl")
        while True:
            try:
                descriptor = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                try:
                    age = time.time() - marker.stat().st_mtime
                except OSError:
                    age = 0.0
                if age > LOCK_STALE_SECONDS:
                    try:
                        marker.unlink()
                    except OSError:
                        pass
                    continue
                if time.monotonic() >= deadline:
                    raise StoreError(
                        f"the session lock file {marker} is held; nothing was written"
                    ) from None
                time.sleep(0.02)
                continue
            except OSError as exc:
                raise StoreError(f"the session lock at {marker} could not be created: {exc}") from exc
            os.write(descriptor, str(os.getpid()).encode("ascii"))
            os.close(descriptor)
            self._mode = "exclusive-file"
            self._handle = marker
            return

    def release(self) -> None:
        if self._mode == "exclusive-file":
            try:
                Path(self._handle).unlink()
            except OSError:
                pass
        elif self._handle is not None:
            try:
                if self._mode == "flock":
                    import fcntl

                    fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
                elif self._mode == "msvcrt":
                    import msvcrt

                    self._handle.seek(0)
                    msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
            except (OSError, ImportError):
                pass
            try:
                self._handle.close()
            except OSError:
                pass
        self._handle = None
        self._mode = "none"


@dataclass(frozen=True)
class StreamRead:
    """The result of reading one session's chain, including what was wrong."""

    events: tuple[TaskEvent, ...] = ()
    anchor_hash: str = GENESIS_HASH
    anchor_sequence: int = 0
    #: A final record that was structurally incomplete — the signature of a
    #: process that died mid-append. Dropped, counted, never reconstructed.
    incomplete_tail: int = 0
    warnings: tuple[str, ...] = ()

    @property
    def tip_hash(self) -> str:
        return self.events[-1].event_hash if self.events else self.anchor_hash

    @property
    def tip_sequence(self) -> int:
        return self.events[-1].sequence if self.events else self.anchor_sequence


@dataclass(frozen=True)
class StoreReport:
    """What :meth:`CompanionStore.validate` found."""

    session_id: str
    events: int
    tip_sequence: int
    tip_hash: str
    projection_revision: int
    consistent: bool
    incomplete_tail: int = 0
    problems: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {
            "sessionId": self.session_id,
            "events": self.events,
            "tipSequence": self.tip_sequence,
            "tipHash": self.tip_hash,
            "projectionRevision": self.projection_revision,
            "consistent": self.consistent,
            "incompleteTail": self.incomplete_tail,
            "problems": list(self.problems),
            "warnings": list(self.warnings),
        }


#: Mode for everything the companion writes. The event log is the authoritative
#: record and carries the richest payloads, up to ``secret`` — so it gets the
#: same 0600 the projections already had. A security review found it was being
#: created with the process umask (0644 on a default install) while every other
#: file in the store was private, which meant any local account could read
#: another user's whole companion history. Directories are 0700 for the same
#: reason: a listing of session ids is itself information.
_FILE_MODE = 0o600
_DIRECTORY_MODE = 0o700


def _private_directory(path: Path) -> None:
    """Create a directory chain the owner alone can enter.

    Each missing level is created separately. ``Path.mkdir(parents=True,
    mode=…)`` applies the mode only to the *final* component and leaves every
    intermediate at the umask default — which on a real ext4 install left
    ``sessions/`` at 0755 while every directory either side of it was 0700, so a
    listing of a user's session ids was world-readable.

    Only directories this call creates are chmodded. An existing one is left
    alone: the store root may legitimately be somewhere shared, and silently
    tightening a directory the user already had is not this function's business.
    """
    missing: list[Path] = []
    current = path
    while not current.exists():
        missing.append(current)
        if current.parent == current:
            break
        current = current.parent
    for directory in reversed(missing):
        try:
            directory.mkdir(mode=_DIRECTORY_MODE)
        except FileExistsError:
            continue
        except OSError as exc:
            raise StoreError(f"{directory} could not be created: {exc}") from exc
        try:
            directory.chmod(_DIRECTORY_MODE)
        except OSError:
            # A filesystem without POSIX modes — a developer machine, not the
            # installed system. The file modes are the defence that matters.
            pass


def _append_private(path: Path, text: str) -> None:
    """Append durably to a private, non-symlink file.

    ``O_NOFOLLOW`` matters because the store root is configurable — through
    ``BUNNY_COMPANION_ROOT``, ``--root`` and ``run-demo --demo-root`` — so it can
    be pointed somewhere another user can write. Following a symlink planted
    there would append a user's task history to a file of the attacker's
    choosing. The mode is passed to ``os.open`` rather than applied afterwards
    so there is no window in which the file exists and is readable.
    """
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, _FILE_MODE)
    try:
        with os.fdopen(descriptor, "a", encoding="utf-8", newline="\n", closefd=False) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)


def _atomic_write_json(path: Path, document: Mapping[str, Any]) -> None:
    """Replace a file's contents, or leave them entirely unchanged.

    The temporary is created in the *same directory* as the destination, which
    is what makes the rename atomic — across filesystems it would be a copy,
    and a copy has a moment where the destination is half written. It is also
    what makes the retry in :func:`_replace_stable` safe: the directory has
    already accepted a file, so a later refusal cannot be a permissions problem
    with the directory.

    Nothing reports success before the replacement lands. The caller learns the
    write happened by this function returning, and it returns only after
    ``os.replace`` has and the directory entry has been synchronised.
    """
    _private_directory(path.parent)
    encoded = json.dumps(document, indent=2, sort_keys=True) + "\n"
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="\n", dir=str(path.parent), prefix=path.name + ".", suffix=".tmp", delete=False
    )
    temporary = Path(handle.name)
    try:
        with handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        _replace_stable(temporary, path)
    except OSError as exc:
        _discard(temporary)
        raise StoreError(f"{path} could not be written: {exc}") from exc
    except BaseException:
        # KeyboardInterrupt and SystemExit reach here, and they arrive most
        # easily during the backoff in `_replace_stable`. Without this the
        # temporary survived the interruption, and a store interrupted often
        # enough accumulated one orphan per attempt in the same directory it
        # later scans.
        _discard(temporary)
        raise
    _fsync_directory(path.parent)


def _discard(temporary: Path) -> None:
    """Remove a temporary that will never become the real file."""
    try:
        temporary.unlink()
    except OSError:
        pass


#: How many times a read will look again when it meets a file mid-replacement,
#: and how long it waits between attempts. Small: this is a window of
#: microseconds, and a fault that survives fifty milliseconds of retrying is a
#: real fault rather than a race.
_READ_ATTEMPTS = 5
_READ_BACKOFF_SECONDS = 0.01


def _read_bytes_stable(path: Path) -> bytes:
    """Read a file another writer may be atomically replacing underneath.

    ``os.replace`` is atomic *for the filesystem*: a reader sees the old
    contents or the new ones, never a mixture. On POSIX it is also atomic for
    *readers*, and this is a plain read that succeeds first time. On Windows the
    replacement is implemented as a rename over an existing name, and a reader
    that opens the path in the instant between can be refused with EACCES —
    which is not a damaged file, not a permissions problem, and not something to
    report as either.

    The companion meets this constantly now that a runtime worker writes task
    projections while the protocol serves readers from the same store. It cost
    a run of the suite to find, and reporting it as "the task document is not
    readable" is exactly the wrong diagnosis to hand somebody.

    Bounded, and the last failure is re-raised rather than swallowed: a store
    that genuinely cannot be read must still say so.
    """
    last: OSError | None = None
    for attempt in range(_READ_ATTEMPTS):
        try:
            return path.read_bytes()
        except OSError as exc:
            last = exc
            time.sleep(_READ_BACKOFF_SECONDS * (attempt + 1))
    raise last if last is not None else OSError(f"{path} could not be read")


def _read_text_stable(path: Path) -> str:
    return _read_bytes_stable(path).decode("utf-8")


#: Attempts and backoff for a replacement refused by a concurrent reader.
#:
#: Separate constants from the read side even though the numbers match, because
#: they answer different questions and a future measurement will move one
#: without moving the other. Five attempts at 10, 20, 30, 40 and 50 ms is 150 ms
#: of patience: far longer than a reader holds a file open for a single read,
#: and short enough that a permanent failure is still reported promptly.
_REPLACE_ATTEMPTS = 5
_REPLACE_BACKOFF_SECONDS = 0.01

#: Windows error codes for "somebody else has this file open".
#:
#: 5 is ``ERROR_ACCESS_DENIED``, which is what a rename over a path another
#: handle has open produces — this is the one that was measured, captured as
#: ``[WinError 5]`` out of the worker's fault log. 32 is
#: ``ERROR_SHARING_VIOLATION``, the same situation reported through a different
#: code depending on how the other handle was opened.
_SHARING_WINERRORS = frozenset({5, 32})


def _is_transient_replacement_failure(error: OSError, path: Path) -> bool:
    """Whether retrying this replacement could possibly help.

    True for exactly one situation: on Windows, a rename refused because
    another handle has the destination open. That is transient by construction
    — the reader closes — and it is the failure this store actually meets,
    because the protocol serves readers from the same files a worker writes.

    False for everything else, and the cases worth naming:

    * **POSIX.** A rename over an open file succeeds there. An ``EACCES`` on
      POSIX therefore means what it says, and retrying it would turn a real
      permissions problem into a slow real permissions problem.
    * **A read-only destination.** Permanent. The mode does not change because
      we waited.
    * **A full disk, a read-only filesystem, a missing directory.** All
      permanent for this attempt, all reported immediately.
    """
    if os.name != "nt":
        return False
    if not isinstance(error, PermissionError):
        return False
    if getattr(error, "winerror", None) not in _SHARING_WINERRORS:
        return False
    try:
        status = path.stat()
    except OSError:
        # No destination to be holding open. Whatever this is, waiting will not
        # change it.
        return False
    # A destination the process cannot write is refused for a reason that
    # outlasts any backoff.
    return bool(status.st_mode & stat.S_IWUSR)


def _replace_stable(temporary: Path, path: Path) -> None:
    """Rename over a destination a reader may have open.

    The mirror image of :func:`_read_bytes_stable`, and it was missing. That
    function documents the Windows behaviour precisely — a rename over an
    existing name meets a reader that has the path open and is refused with
    EACCES — but it only defended the *reader*. The writer met the same window
    from the other side and had no retry at all.

    The consequence was not a bad read; it was a frozen task. ``os.replace``
    raised, the store turned it into a :class:`StoreError`, and
    ``CompanionService._serve_work`` caught it as an ordinary refusal and moved
    on, leaving the task in whatever state it had last persisted — most often
    ``waiting_for_executor``, with nothing running, nothing queued and no
    explanation anywhere. That is the intermittent suite failure, and it is
    Windows-only: on POSIX a rename over an open file simply succeeds, which is
    why 52 consecutive Linux runs never reproduced it while one Windows run in
    three did.

    Bunny OS runs on Linux, where this loop retries nothing. It exists so that
    the development host stops manufacturing failures that the product does not
    have.

    **Only the measured failure is retried.** Retrying every ``OSError`` here
    would be worse than not retrying at all: a disk that is full, a filesystem
    mounted read-only or a destination somebody has genuinely locked down are
    all permanent, and looping over them adds a delay to an error that was
    correct the first time — and, worse, invites a reader to believe the store
    tried hard enough that the failure must be real when the opposite is true.
    :func:`_is_transient_replacement_failure` is the discriminator, and the
    original exception is re-raised unchanged once the attempts are spent.
    """
    last: OSError | None = None
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(temporary, path)
            return
        except OSError as exc:
            if not _is_transient_replacement_failure(exc, path):
                # Permanent. Raise it now rather than after a second of
                # pretending it might not be.
                raise
            last = exc
            time.sleep(_REPLACE_BACKOFF_SECONDS * (attempt + 1))
    raise last if last is not None else OSError(f"{path} could not be replaced")


def _fsync_directory(directory: Path) -> None:
    """Make a rename durable. A no-op where the platform has no directory fd.

    On Windows ``os.open`` cannot open a directory, so the rename's durability
    rests on the filesystem rather than on us. Bunny OS runs on Linux and gets
    the strong form; the weak form is only ever reached by a developer machine.
    """
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except (OSError, AttributeError):
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


class CompanionStore:
    """The durable home of sessions, tasks and event chains."""

    def __init__(self, root: Path, *, retention: RetentionPolicy = DEFAULT_RETENTION) -> None:
        self.root = Path(root)
        self.retention = retention

    # -- layout ------------------------------------------------------------

    @property
    def metadata_path(self) -> Path:
        return self.root / "store.json"

    def session_directory(self, session_id: str) -> Path:
        if not valid_id(session_id):
            raise StoreError(f"{session_id!r} is not a usable session identifier")
        return self.root / "sessions" / session_id

    def _events_path(self, session_id: str) -> Path:
        return self.session_directory(session_id) / "events.jsonl"

    def _stream_path(self, session_id: str) -> Path:
        return self.session_directory(session_id) / "stream.json"

    def _session_path(self, session_id: str) -> Path:
        return self.session_directory(session_id) / "session.json"

    def _task_path(self, session_id: str, task_id: str) -> Path:
        if not valid_id(task_id):
            raise StoreError(f"{task_id!r} is not a usable task identifier")
        return self.session_directory(session_id) / "tasks" / f"{task_id}.json"

    def _lock(self, session_id: str) -> FileLock:
        return FileLock(self.session_directory(session_id) / "session.lock")

    # -- store metadata ----------------------------------------------------

    def initialise(self) -> dict[str, Any]:
        """Create the store if it does not exist; validate it if it does."""
        _private_directory(self.root)
        if self.metadata_path.is_file():
            return self.metadata()
        document = {
            "schemaVersion": STORE_SCHEMA_VERSION,
            "eventSchemaVersion": EVENT_SCHEMA_VERSION,
            "kind": "bunny-companion-store",
        }
        _atomic_write_json(self.metadata_path, document)
        return document

    def metadata(self) -> dict[str, Any]:
        try:
            document = json.loads(_read_text_stable(self.metadata_path))
        except FileNotFoundError:
            raise StoreError(f"{self.root} is not an initialised companion store") from None
        except (OSError, json.JSONDecodeError) as exc:
            raise StoreError(f"{self.metadata_path} is not readable: {exc}") from exc
        if not isinstance(document, Mapping) or document.get("kind") != "bunny-companion-store":
            raise StoreError(f"{self.metadata_path} is not a companion store descriptor")
        version = document.get("schemaVersion")
        if not isinstance(version, int) or version > STORE_SCHEMA_VERSION:
            raise StoreError(
                f"the store at {self.root} declares schemaVersion {version!r}, which this build "
                "does not understand; refusing rather than reading it as though it did"
            )
        return dict(document)

    def session_ids(self) -> tuple[str, ...]:
        directory = self.root / "sessions"
        if not directory.is_dir():
            return ()
        return tuple(sorted(item.name for item in directory.iterdir() if item.is_dir() and valid_id(item.name)))

    # -- stream metadata ---------------------------------------------------

    def _stream_metadata(self, session_id: str) -> dict[str, Any]:
        path = self._stream_path(session_id)
        if not path.is_file():
            return {
                "schemaVersion": STORE_SCHEMA_VERSION,
                "anchorHash": GENESIS_HASH,
                "anchorSequence": 0,
                "droppedEvents": 0,
                "migrations": [],
            }
        try:
            document = json.loads(_read_text_stable(path))
        except (OSError, json.JSONDecodeError) as exc:
            raise StoreError(f"{path} is not readable: {exc}") from exc
        if not isinstance(document, Mapping):
            raise StoreError(f"{path} is not a stream descriptor")
        return dict(document)

    # -- reading -----------------------------------------------------------

    def read_stream(self, session_id: str) -> StreamRead:
        """Read and verify one session's chain.

        The only tolerated damage is an incomplete final record. Everything else
        raises, because everything else means the file was changed by something
        other than an interrupted append.
        """
        path = self._events_path(session_id)
        stream = self._stream_metadata(session_id)
        anchor_hash = str(stream.get("anchorHash", GENESIS_HASH))
        anchor_sequence = int(stream.get("anchorSequence", 0) or 0)
        if not path.is_file():
            return StreamRead(anchor_hash=anchor_hash, anchor_sequence=anchor_sequence)

        try:
            raw = _read_bytes_stable(path)
        except OSError as exc:
            raise StoreError(f"{path} is not readable: {exc}") from exc

        warnings: list[str] = []
        incomplete = 0
        text = raw.decode("utf-8", errors="strict") if raw else ""
        if text and not text.endswith("\n"):
            # A record without its terminating newline was being written when the
            # process stopped. It is the last one by construction: an append that
            # has not finished cannot have been followed by another.
            cut = text.rfind("\n")
            text = text[: cut + 1] if cut >= 0 else ""
            incomplete = 1
            warnings.append(
                "the final event record had no terminating newline and was discarded as an "
                "interrupted append; nothing was reconstructed in its place"
            )

        events: list[TaskEvent] = []
        lines = [line for line in text.split("\n") if line.strip()]
        for index, line in enumerate(lines):
            try:
                document = json.loads(line)
            except json.JSONDecodeError as exc:
                if index == len(lines) - 1:
                    incomplete += 1
                    warnings.append(
                        "the final event record was not parseable JSON and was discarded as an "
                        f"interrupted append ({exc.msg}); nothing was reconstructed in its place"
                    )
                    break
                raise IntegrityError(
                    f"{path} line {index + 1} is not parseable JSON and is not the last line, "
                    f"so it was not an interrupted append: {exc.msg}"
                ) from exc
            events.append(TaskEvent.from_json(document))

        _verify_from_anchor(events, anchor_hash, anchor_sequence)
        return StreamRead(
            events=tuple(events),
            anchor_hash=anchor_hash,
            anchor_sequence=anchor_sequence,
            incomplete_tail=incomplete,
            warnings=tuple(warnings),
        )

    def read_events(self, session_id: str, *, task_id: str | None = None) -> tuple[TaskEvent, ...]:
        """Events in order, optionally narrowed to one task."""
        events = self.read_stream(session_id).events
        if task_id is None:
            return events
        return tuple(event for event in events if event.task_id == task_id)

    def tip(self, session_id: str) -> tuple[int, str]:
        """The sequence and hash the next event must follow.

        Reads the last record rather than the whole chain. Appending is the
        operation a running task performs most, and re-verifying the entire
        history on each one would make a session quadratic in its own length —
        which on a 64 MB board is the difference between a companion and a
        space heater. Full verification happens in :meth:`read_stream`, on the
        reads where it means something: opening a session, replaying it,
        exporting it and recovering it.
        """
        fast = self._fast_tip(session_id)
        if fast is not None:
            return fast
        read = self.read_stream(session_id)
        return read.tip_sequence, read.tip_hash

    def _fast_tip(self, session_id: str) -> tuple[int, str] | None:
        """The last complete record's sequence and hash, or ``None``.

        ``None`` means "ask the slow path": the file is absent, ends in a
        partial write, or its final line is bigger than the window. Every one of
        those needs the full read, and returning ``None`` rather than guessing
        is what keeps the fast path from becoming a second, weaker parser.
        """
        path = self._events_path(session_id)
        try:
            size = path.stat().st_size
        except OSError:
            return None
        if size == 0:
            return None
        window = min(size, 131_072)
        try:
            with open(path, "rb") as handle:
                handle.seek(size - window)
                raw = handle.read(window)
        except OSError:
            return None
        if not raw.endswith(b"\n"):
            return None
        cut = raw.rfind(b"\n", 0, len(raw) - 1)
        if cut < 0:
            if window < size:
                return None  # the last line starts before the window
            line = raw[:-1]
        else:
            line = raw[cut + 1 : -1]
        try:
            event = TaskEvent.from_json(json.loads(line.decode("utf-8")))
        except (UnicodeDecodeError, json.JSONDecodeError, SchemaError, IntegrityError):
            return None
        return event.sequence, event.event_hash

    # -- appending ---------------------------------------------------------

    def append(self, event: TaskEvent) -> None:
        self.append_many((event,))

    def append_many(self, events: Sequence[TaskEvent]) -> None:
        """Append events under the session lock, durably, or not at all.

        The tip is re-read inside the lock rather than trusted from the caller.
        A caller that computed a chain against a tip which has since moved is
        refused — that is the deduplication and out-of-order defence, and it has
        to happen here because here is the only place that holds the lock.
        """
        if not events:
            return
        session_id = events[0].session_id
        if any(item.session_id != session_id for item in events):
            raise StoreError("a single append must belong to one session")

        directory = self.session_directory(session_id)
        _private_directory(directory)
        with self._lock(session_id):
            fast = self._fast_tip(session_id)
            if fast is None:
                read = self.read_stream(session_id)
                if read.incomplete_tail:
                    # Repair before extending. Appending after a partial line
                    # would produce a file whose damaged record sits in the
                    # middle, where it can no longer be recognised as an
                    # interrupted append.
                    self._rewrite_locked(session_id, read.events, read.anchor_hash, read.anchor_sequence)
                tip_sequence, tip_hash = read.tip_sequence, read.tip_hash
            else:
                tip_sequence, tip_hash = fast
            expected_sequence = tip_sequence + 1
            expected_previous = tip_hash
            total = tip_sequence + len(events)
            if total > self.retention.maximum_events:
                raise StoreError(
                    f"session {session_id} would exceed the {self.retention.maximum_events} event ceiling; "
                    "nothing was appended"
                )
            for item in events:
                if item.sequence != expected_sequence:
                    raise IntegrityError(
                        f"event {item.event_id!r} claims sequence {item.sequence} where the stream "
                        f"expects {expected_sequence}; it is a replay or was built against a stale tip"
                    )
                if item.previous_hash != expected_previous:
                    raise IntegrityError(
                        f"event {item.event_id!r} does not follow the current tip; "
                        "it is a replay or was built against a stale tip"
                    )
                expected_sequence += 1
                expected_previous = item.event_hash

            path = self._events_path(session_id)
            encoded = "".join(
                json.dumps(item.to_json(), sort_keys=True, separators=(",", ":")) + "\n" for item in events
            )
            try:
                _append_private(path, encoded)
            except OSError as exc:
                raise StoreError(f"{path} could not be appended to: {exc}") from exc

    # -- projections -------------------------------------------------------

    def save_session(self, session: CompanionSession) -> None:
        _atomic_write_json(self._session_path(session.session_id), session.to_json())

    def load_session(self, session_id: str) -> CompanionSession | None:
        path = self._session_path(session_id)
        if not path.is_file():
            return None
        try:
            document = json.loads(_read_text_stable(path))
        except (OSError, json.JSONDecodeError) as exc:
            raise StoreError(f"{path} is not readable: {exc}") from exc
        return CompanionSession.from_json(document)

    def save_task(self, task: CompanionTask) -> None:
        _atomic_write_json(self._task_path(task.session_id, task.task_id), task.to_json())

    def load_task(self, session_id: str, task_id: str) -> CompanionTask | None:
        path = self._task_path(session_id, task_id)
        if not path.is_file():
            return None
        try:
            document = json.loads(_read_text_stable(path))
        except (OSError, json.JSONDecodeError) as exc:
            raise StoreError(f"{path} is not readable: {exc}") from exc
        return CompanionTask.from_json(document)

    def task_ids(self, session_id: str) -> tuple[str, ...]:
        directory = self.session_directory(session_id) / "tasks"
        if not directory.is_dir():
            return ()
        return tuple(sorted(item.stem for item in directory.glob("*.json") if valid_id(item.stem)))

    def tasks(self, session_id: str) -> Iterator[CompanionTask]:
        for task_id in self.task_ids(session_id):
            task = self.load_task(session_id, task_id)
            if task is not None:
                yield task

    # -- validation, retention, migration ----------------------------------

    def validate(self, session_id: str) -> StoreReport:
        """Check one session end to end, without changing anything."""
        problems: list[str] = []
        try:
            read = self.read_stream(session_id)
        except (IntegrityError, SchemaError, StoreError) as exc:
            return StoreReport(
                session_id=session_id,
                events=0,
                tip_sequence=0,
                tip_hash="",
                projection_revision=0,
                consistent=False,
                problems=(str(exc),),
            )
        session = self.load_session(session_id)
        revision = session.event_stream_revision if session is not None else 0
        if session is None:
            problems.append("the session projection is missing; it can be rebuilt from the stream")
        elif revision != read.tip_sequence:
            problems.append(
                f"the session projection is at revision {revision} and the stream is at "
                f"{read.tip_sequence}; the stream is authoritative"
            )
        for task in self.tasks(session_id):
            if not any(event.task_id == task.task_id for event in read.events):
                problems.append(f"task {task.task_id} has a projection but no events")
        return StoreReport(
            session_id=session_id,
            events=len(read.events),
            tip_sequence=read.tip_sequence,
            tip_hash=read.tip_hash,
            projection_revision=revision,
            consistent=not problems,
            incomplete_tail=read.incomplete_tail,
            problems=tuple(problems),
            warnings=read.warnings,
        )

    def prune(self, session_id: str) -> int:
        """Drop the oldest events down to the retention policy. Returns the count.

        The chain that remains still verifies, because the anchor recorded in
        ``stream.json`` names the hash the new head follows. History removed on
        purpose is therefore distinguishable from history removed by damage,
        which is the whole point — a store that silently shortened its own
        chains would make every corruption look like housekeeping.
        """
        with self._lock(session_id):
            read = self.read_stream(session_id)
            surplus = len(read.events) - self.retention.retained_events
            if surplus <= 0:
                return 0
            dropped = read.events[:surplus]
            kept = read.events[surplus:]
            anchor = dropped[-1]
            self._rewrite_locked(session_id, kept, anchor.event_hash, anchor.sequence, dropped=surplus)
            return surplus

    def migrate(self, session_id: str) -> dict[str, Any]:
        """Bring a stream forward to the current event schema version.

        Migration re-seals every event, because the schema version is part of
        the hashed material — a migrated stream is genuinely a different chain.
        That would be indistinguishable from tampering if it were not written
        down, so the old tip hash, the new tip hash and the versions involved
        are recorded in ``stream.json``. A reader can then say "this chain was
        migrated from version 0 on this date and here is what it hashed to
        before", which is a claim that can be checked against a backup.
        """
        with self._lock(session_id):
            path = self._events_path(session_id)
            if not path.is_file():
                return {"migrated": 0, "fromVersions": [], "toVersion": EVENT_SCHEMA_VERSION}
            stream = self._stream_metadata(session_id)
            anchor_hash = str(stream.get("anchorHash", GENESIS_HASH))
            anchor_sequence = int(stream.get("anchorSequence", 0) or 0)

            raw = _read_text_stable(path)
            documents = [json.loads(line) for line in raw.split("\n") if line.strip()]
            versions = sorted({int(item.get("schemaVersion", 0) or 0) for item in documents})
            if not versions or versions == [EVENT_SCHEMA_VERSION]:
                return {"migrated": 0, "fromVersions": versions, "toVersion": EVENT_SCHEMA_VERSION}
            # Asked before authenticity, because it is the more specific answer:
            # a stream from a newer build is not damaged, it is simply not ours
            # to rewrite.
            if max(versions) > EVENT_SCHEMA_VERSION:
                raise StoreError(
                    f"session {session_id} contains events at schema version {max(versions)}, which is "
                    "newer than this build; a downgrade is not a migration and is refused"
                )
            _verify_before_migrating(documents, anchor_hash, anchor_sequence, session_id)

            original_tip = str(documents[-1].get("eventHash", ""))
            upgraded: list[TaskEvent] = []
            previous = anchor_hash
            for document in documents:
                current = _upgrade_event_document(document)
                current["previousHash"] = previous
                current["schemaVersion"] = EVENT_SCHEMA_VERSION
                from .events import _material, _seal  # local import: internal to the chain format

                material = _material(
                    schema_version=EVENT_SCHEMA_VERSION,
                    event_id=str(current["eventId"]),
                    session_id=str(current["sessionId"]),
                    task_id=str(current.get("taskId", "")),
                    sequence=int(current["sequence"]),
                    event_type=str(current["eventType"]),
                    timestamp=str(current["timestamp"]),
                    producer=str(current["producer"]),
                    payload=dict(current.get("payload") or {}),
                    classification=str(current["classification"]),
                    audit_reference=str(current.get("auditReference", "")),
                    redactions=list(current.get("redactions") or []),
                    internal_fields=list(current.get("internalFields") or []),
                    previous_hash=previous,
                )
                current["eventHash"] = _seal(material, EVENT_SCHEMA_VERSION)
                event = TaskEvent.from_json(current)
                upgraded.append(event)
                previous = event.event_hash

            record = {
                "fromVersions": versions,
                "toVersion": EVENT_SCHEMA_VERSION,
                "events": len(upgraded),
                "originalTipHash": original_tip,
                "newTipHash": upgraded[-1].event_hash if upgraded else anchor_hash,
            }
            self._rewrite_locked(
                session_id, tuple(upgraded), anchor_hash, anchor_sequence,
                dropped=int(stream.get("droppedEvents", 0) or 0),
                migrations=[*list(stream.get("migrations") or []), record],
            )
            return {"migrated": len(upgraded), **record}

    def export(self, session_id: str, *, audience: str = "audit") -> dict[str, Any]:
        """A sanitized history, rendered for one audience.

        This is the only supported way to get a session out of the store. It
        goes through :meth:`companion.events.TaskEvent.view`, so an export can
        never contain more than the audience it names is entitled to — including
        an export somebody takes for support and then emails.
        """
        read = self.read_stream(session_id)
        session = self.load_session(session_id)
        # The session document goes through the same projection as everything
        # else. It was previously embedded raw, so a session whose *title* was
        # the user's own words left with every export regardless of audience.
        # A session's own classification is the strictest of its tasks': the
        # container is at least as sensitive as what it holds.
        tasks = list(self.tasks(session_id))
        session_class = "internal"
        for task in tasks:
            from .privacy import rank

            if rank(task.classification) > rank(session_class):
                session_class = task.classification
        return {
            "schemaVersion": STORE_SCHEMA_VERSION,
            "audience": audience,
            "sessionId": session_id,
            "session": session.view(audience, classification=session_class) if session is not None else None,
            "tasks": [task.view(audience) for task in tasks],
            "anchorHash": read.anchor_hash,
            "anchorSequence": read.anchor_sequence,
            "incompleteTail": read.incomplete_tail,
            "warnings": list(read.warnings),
            "events": [event.view(audience) for event in read.events],
        }

    # -- internals ---------------------------------------------------------

    def _rewrite_locked(
        self,
        session_id: str,
        events: Sequence[TaskEvent],
        anchor_hash: str,
        anchor_sequence: int,
        *,
        dropped: int | None = None,
        migrations: list[Any] | None = None,
    ) -> None:
        """Replace a whole chain atomically. Only ever called under the lock."""
        path = self._events_path(session_id)
        encoded = "".join(
            json.dumps(item.to_json(), sort_keys=True, separators=(",", ":")) + "\n" for item in events
        )
        handle = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="\n", dir=str(path.parent),
            prefix=path.name + ".", suffix=".tmp", delete=False,
        )
        temporary = Path(handle.name)
        try:
            with handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except OSError as exc:
            try:
                temporary.unlink()
            except OSError:
                pass
            raise StoreError(f"{path} could not be rewritten: {exc}") from exc
        _fsync_directory(path.parent)

        existing = self._stream_metadata(session_id)
        document = {
            "schemaVersion": STORE_SCHEMA_VERSION,
            "anchorHash": anchor_hash,
            "anchorSequence": anchor_sequence,
            "droppedEvents": int(existing.get("droppedEvents", 0) or 0) if dropped is None else dropped,
            "migrations": list(existing.get("migrations") or []) if migrations is None else migrations,
        }
        _atomic_write_json(self._stream_path(session_id), document)


def _verify_from_anchor(events: Sequence[TaskEvent], anchor_hash: str, anchor_sequence: int) -> None:
    """Verify a chain that may begin after a retention anchor rather than at 1."""
    if anchor_sequence == 0 and anchor_hash == GENESIS_HASH:
        verify_chain(events)
        return
    previous = anchor_hash
    expected = anchor_sequence + 1
    seen: set[str] = set()
    for event in events:
        if event.event_id in seen:
            raise IntegrityError(f"event {event.event_id!r} appears more than once")
        seen.add(event.event_id)
        if event.sequence != expected:
            raise IntegrityError(
                f"expected sequence {expected} and found {event.sequence}; the stream has a gap or a reorder"
            )
        if event.previous_hash != previous:
            raise IntegrityError(
                f"event {event.sequence} does not follow its predecessor; the chain is broken"
            )
        previous = event.event_hash
        expected += 1




def _verify_before_migrating(
    documents: Sequence[Mapping[str, Any]],
    anchor_hash: str,
    anchor_sequence: int,
    session_id: str,
) -> None:
    """Refuse to migrate a chain that does not already verify.

    A security review found that :meth:`CompanionStore.migrate` re-sealed every
    record without checking the chain first — so a tampered stream, which
    :meth:`CompanionStore.read_stream` correctly refuses, came out of a
    migration verifying perfectly with the attacker's edit now correctly
    hashed. The migration record's ``originalTipHash`` was read from the
    tampered file's own last line, so even the audit trail was the attacker's.

    Verification here is done on the *stored* hashes, at whatever version each
    record declares, without constructing :class:`TaskEvent` objects — which is
    the point, since a version this build cannot represent is exactly what
    migration exists for.
    """
    from .events import _material, _seal

    previous = anchor_hash
    expected = anchor_sequence + 1
    for index, document in enumerate(documents):
        if not isinstance(document, Mapping):
            raise IntegrityError(f"{session_id} line {index + 1} is not an object")
        sequence = document.get("sequence")
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence != expected:
            raise IntegrityError(
                f"{session_id} cannot be migrated: expected sequence {expected} at line {index + 1} "
                f"and found {sequence!r}. A chain that does not verify is not migrated; "
                "migrating it would re-seal whatever it now says."
            )
        if str(document.get("previousHash", "")) != previous:
            raise IntegrityError(
                f"{session_id} cannot be migrated: event {sequence} does not follow its predecessor. "
                "A chain that does not verify is not migrated; migrating it would launder the break."
            )
        stored_hash = str(document.get("eventHash", ""))
        version = int(document.get("schemaVersion", 0) or 0)
        if version not in HASHED_FIELDS_BY_VERSION:
            raise IntegrityError(
                f"{session_id} cannot be migrated: event {sequence} declares schema version "
                f"{version}, whose hashing rule this build does not implement, so its "
                "authenticity cannot be established. Migrating it would re-seal an unverified record."
            )
        material = _material(
            schema_version=version,
            event_id=str(document.get("eventId", "")),
            session_id=str(document.get("sessionId", "")),
            task_id=str(document.get("taskId", "")),
            sequence=sequence,
            event_type=str(document.get("eventType", "")),
            timestamp=str(document.get("timestamp", "")),
            producer=str(document.get("producer", "")),
            payload=dict(document.get("payload") or {}),
            classification=str(document.get("classification", "")),
            audit_reference=str(document.get("auditReference", "")),
            redactions=list(document.get("redactions") or []),
            internal_fields=list(document.get("internalFields") or []),
            previous_hash=previous,
        )
        # Each version hashed a different field set. `_seal` restricts the
        # material to the rule of the version the record declares, which is what
        # makes an old chain authenticable at all — and what stops an attacker
        # downgrade-marking records to reach a version with no rule and
        # therefore no check.
        if _seal(material, version) != stored_hash:
            raise IntegrityError(
                f"{session_id} cannot be migrated: event {sequence} does not match its own hash. "
                "A chain that does not verify is not migrated."
            )
        previous = stored_hash
        expected += 1


def _upgrade_event_document(document: Mapping[str, Any]) -> dict[str, Any]:
    """Bring one stored event document up to the current field set.

    Version 0 is the shape written before the redaction record and the audit
    reference existed. Upgrading adds them empty, which is the truthful value:
    a version 0 event genuinely has no record of what was redacted, and
    inventing one would be worse than admitting it.
    """
    current = dict(document)
    version = int(current.get("schemaVersion", 0) or 0)
    if version < 1:
        # Version 0 genuinely has no record of what was redacted, and inventing
        # one would be worse than admitting it.
        current.setdefault("redactions", [])
        current.setdefault("auditReference", "")
    if version < 2:
        # Version 1 classified whole events, so nothing in it was a declared
        # runtime fact. Empty is the truthful — and fail-closed — value.
        current.setdefault("internalFields", [])
    current["schemaVersion"] = EVENT_SCHEMA_VERSION
    return current
