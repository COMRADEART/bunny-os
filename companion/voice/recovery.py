# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What to believe about speech that was in flight when the process died.

§20's hardest sentence is the last one: **do not infer that an utterance
completed merely because no child process remains.** After a crash there is no
child process either way — the kernel reaped it along with everything else — so
"no process" is evidence of nothing. A recovery that treated it as completion
would mark an utterance the user never heard as spoken, and §8's replay guard
would then refuse to ever speak it.

So completion is *recorded*, not inferred. :class:`VoiceJournal` writes a line
when an utterance starts and a line when it settles. On restart, a start with no
settle is **uncertain**, and uncertain is resolved as ``interrupted`` — which is
true (something stopped it) and, importantly, is in
:data:`companion.voice.captions.SpeechDisposition.HEARD`, so it is not
automatically replayed. The user may ask for it again; the machine will not
decide they want it.

The other half is cleanup. A crashed worker leaves a private workspace holding a
WAV of whatever the task said. :func:`sweep_workspaces` removes them, and it
**validates ownership before removing anything**: the name prefix is a
convention, not a proof, and a function that deleted every directory matching a
pattern in a shared temporary directory would be a way to delete somebody else's
files by naming them well.

Nothing here restarts a task, resubmits a request or contacts a provider to ask
what it did. The record is the authority, and where the record is silent the
answer is the conservative one.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import threading
import time
from typing import Any, Iterable, Mapping, Sequence

from .captions import SpeechDisposition
from .execution import PrivateWorkspace
from .request import VoiceRequest

__all__ = [
    "RecoveryReport",
    "VoiceJournal",
    "sweep_workspaces",
]

#: How old an abandoned workspace must be before it is swept. A worker that is
#: running right now owns a directory with this prefix, and a sweep that ignored
#: age would delete the audio of the utterance being played.
STALE_AFTER_SECONDS = 300.0

#: The most journal entries kept. One line per utterance; a thousand covers any
#: plausible session and bounds a file that would otherwise grow forever in a
#: service that runs for weeks.
MAX_JOURNAL_ENTRIES = 1024


@dataclass(frozen=True)
class RecoveryReport:
    """What one restart found and what it decided about each thing."""

    started: int = 0
    settled: int = 0
    uncertain: tuple[str, ...] = ()
    marked_interrupted: tuple[str, ...] = ()
    replayed: tuple[str, ...] = ()
    workspaces_removed: int = 0
    workspaces_skipped: tuple[str, ...] = ()
    files_removed: int = 0
    detail: str = ""

    @property
    def clean(self) -> bool:
        return not self.uncertain and not self.workspaces_skipped

    def to_json(self) -> dict[str, Any]:
        return {
            "started": self.started,
            "settled": self.settled,
            "uncertain": list(self.uncertain),
            "markedInterrupted": list(self.marked_interrupted),
            # Always empty, and present so a reader can see that it is. §20
            # forbids automatic replay and this is the field that would have to
            # become non-empty for that to change.
            "replayed": list(self.replayed),
            "workspacesRemoved": self.workspaces_removed,
            "workspacesSkipped": list(self.workspaces_skipped),
            "filesRemoved": self.files_removed,
            "automaticReplay": False,
            "captionsPreserved": True,
            "taskResultPreserved": True,
            "detail": self.detail,
        }


class VoiceJournal:
    """A line per utterance start and a line per settle, on disk.

    Deliberately not the companion's event store. Speech is presentation, and
    §15 is explicit that speech history is not stored separately unless the
    canonical task event already permits it — so this holds identity and
    disposition, never text, and it is truncated rather than archived. It exists
    for exactly one purpose: to let the next process tell "finished" from
    "stopped mid-sentence", which is a question nothing else can answer.

    Appended with an ``fsync`` on the settle line only. The start line is the
    cheap one and a lost start makes recovery *more* conservative, not less; a
    lost settle would make a completed utterance look uncertain, which is the
    direction that costs correctness.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._guard = threading.RLock()

    def _write(self, document: Mapping[str, Any], *, durable: bool) -> None:
        line = json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n"
        with self._guard:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                descriptor = os.open(
                    self.path, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600
                )
                try:
                    os.write(descriptor, line.encode("utf-8"))
                    if durable:
                        os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            except OSError:
                # A journal that cannot be written must not stop speech. The
                # consequence is a more conservative recovery next time, which
                # is the safe direction.
                return

    def record_start(self, request: VoiceRequest, *, monotonic: float = 0.0) -> None:
        self._write({
            "event": "start",
            "requestId": request.request_id,
            "sessionId": request.session_id,
            "taskId": request.task_id,
            "captionReference": request.caption_reference,
            "textDigest": request.text_digest,
            "priority": request.priority.wire,
            "atMonotonic": monotonic,
            "pid": os.getpid(),
        }, durable=False)

    def record_settle(
        self, request: VoiceRequest, disposition: str, *, monotonic: float = 0.0
    ) -> None:
        if disposition not in SpeechDisposition.ALL:
            raise ValueError(f"unknown speech disposition: {disposition!r}")
        self._write({
            "event": "settle",
            "requestId": request.request_id,
            "captionReference": request.caption_reference,
            "disposition": disposition,
            "atMonotonic": monotonic,
            "pid": os.getpid(),
        }, durable=True)

    def read(self) -> list[dict[str, Any]]:
        with self._guard:
            try:
                raw = self.path.read_text(encoding="utf-8")
            except OSError:
                return []
        entries: list[dict[str, Any]] = []
        for line in raw.splitlines()[-MAX_JOURNAL_ENTRIES:]:
            line = line.strip()
            if not line:
                continue
            try:
                document = json.loads(line)
            except json.JSONDecodeError:
                # A torn last line after a crash. Skipped rather than fatal: the
                # entries before it are still evidence.
                continue
            if isinstance(document, dict):
                entries.append(document)
        return entries

    def truncate(self) -> None:
        """Start clean. Called after a recovery has read and resolved the file."""
        with self._guard:
            try:
                self.path.unlink()
            except OSError:
                return

    def reconcile(self, *, own_pid: int | None = None) -> RecoveryReport:
        """Decide what happened to everything the journal mentions.

        ``own_pid`` excludes the current process's own in-flight utterance from
        the uncertain set, which matters when a *service* restarts its worker
        without the process dying: those are being handled right now and are not
        abandoned.
        """
        entries = self.read()
        started: dict[str, dict[str, Any]] = {}
        settled: set[str] = set()
        for item in entries:
            identifier = str(item.get("requestId", ""))
            if not identifier:
                continue
            if item.get("event") == "start":
                started[identifier] = item
            elif item.get("event") == "settle":
                settled.add(identifier)

        uncertain = [
            identifier for identifier, item in started.items()
            if identifier not in settled
            and (own_pid is None or int(item.get("pid", -1)) != own_pid)
        ]
        return RecoveryReport(
            started=len(started),
            settled=len(settled),
            uncertain=tuple(sorted(uncertain)),
            # Resolved, not merely listed. "Uncertain" is the finding;
            # "interrupted" is the decision, and it is the same set because
            # there is no evidence that would separate them.
            marked_interrupted=tuple(sorted(uncertain)),
            replayed=(),
            detail=(
                f"{len(uncertain)} utterance(s) were in flight and are recorded interrupted; "
                "none was replayed"
                if uncertain else "no utterance was in flight"
            ),
        )


def _owned_by_us(path: Path) -> tuple[bool, str]:
    """Whether this directory is ours to delete.

    Three checks, and each has a way of being false that matters:

    * it is a directory, not a symlink to one — a symlink named like a workspace
      is how a deletion becomes a deletion of something else;
    * its owner is this user — a prefix is a convention and ownership is a fact;
    * it is not group- or world-writable — a directory anyone can write is a
      directory anyone could have put anything in.
    """
    try:
        info = path.lstat()
    except OSError as exc:
        return False, f"could not be inspected: {exc.strerror or exc}"
    if stat.S_ISLNK(info.st_mode):
        return False, "is a symbolic link rather than a directory"
    if not stat.S_ISDIR(info.st_mode):
        return False, "is not a directory"
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        return False, f"is owned by uid {info.st_uid} rather than this user"
    if os.name == "posix" and info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        return False, "is writable by group or other"
    return True, ""


def sweep_workspaces(
    *,
    parent: Path | str | None = None,
    stale_after_seconds: float = STALE_AFTER_SECONDS,
    now: float | None = None,
    active: Iterable[Path | str] = (),
) -> tuple[int, tuple[str, ...], int]:
    """Remove private audio a crashed worker left behind.

    Returns ``(removed, skipped_with_reasons, files_removed)``. Skipped entries
    are returned rather than silently ignored: a workspace this refuses to touch
    is either not ours or is in use, and both are things somebody investigating
    disk usage needs told rather than left to guess.
    """
    root = Path(parent) if parent is not None else Path(tempfile.gettempdir())
    moment = time.time() if now is None else now
    protected = {str(Path(item).resolve()) for item in active}
    removed = 0
    files_removed = 0
    skipped: list[str] = []

    try:
        candidates = sorted(root.glob(f"{PrivateWorkspace.PREFIX}*"))
    except OSError as exc:
        return 0, (f"{root}: {exc.strerror or exc}",), 0

    for candidate in candidates:
        try:
            if str(candidate.resolve()) in protected:
                skipped.append(f"{candidate.name}: in use by a running worker")
                continue
        except OSError:
            pass
        owned, reason = _owned_by_us(candidate)
        if not owned:
            skipped.append(f"{candidate.name}: {reason}")
            continue
        try:
            age = moment - candidate.stat().st_mtime
        except OSError as exc:
            skipped.append(f"{candidate.name}: {exc.strerror or exc}")
            continue
        if age < stale_after_seconds:
            skipped.append(
                f"{candidate.name}: only {int(age)}s old, below the {int(stale_after_seconds)}s threshold"
            )
            continue
        try:
            files_removed += sum(1 for item in candidate.rglob("*") if item.is_file())
        except OSError:
            pass
        shutil.rmtree(candidate, ignore_errors=True)
        if candidate.exists():
            skipped.append(f"{candidate.name}: could not be removed")
            continue
        removed += 1

    return removed, tuple(skipped), files_removed


def recover(
    journal: VoiceJournal,
    *,
    parent: Path | str | None = None,
    own_pid: int | None = None,
    stale_after_seconds: float = STALE_AFTER_SECONDS,
    active_workspaces: Iterable[Path | str] = (),
    truncate: bool = True,
) -> RecoveryReport:
    """The whole of §20, in the order the guarantees depend on each other.

    The journal is read *before* the sweep, because a workspace named after an
    utterance the journal has not resolved yet would be removed while it was
    still evidence. It is truncated *after* both, so a crash during recovery
    re-runs a recovery rather than losing one.
    """
    report = journal.reconcile(own_pid=own_pid)
    removed, skipped, files = sweep_workspaces(
        parent=parent,
        stale_after_seconds=stale_after_seconds,
        active=active_workspaces,
    )
    if truncate:
        journal.truncate()
    return RecoveryReport(
        started=report.started,
        settled=report.settled,
        uncertain=report.uncertain,
        marked_interrupted=report.marked_interrupted,
        replayed=(),
        workspaces_removed=removed,
        workspaces_skipped=skipped,
        files_removed=files,
        detail=(
            f"{report.detail}; {removed} abandoned workspace(s) holding {files} file(s) removed"
        ),
    )
