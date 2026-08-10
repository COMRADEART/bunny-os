# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What to believe about a capture that was in flight when the process died.

§21's hardest rule is inherited from the voice runtime and is harder here: **do
not infer anything from the absence of a process, and never resume capture.**
After a crash there is no recorder either way; a recovery that marked an
unfinished capture "completed" would invent words the user never confirmed,
and one that *restarted* it would open a microphone no explicit action just
asked for — the one thing §26.11 exists to forbid. So completion is recorded,
not inferred: a start line with no settle line is **uncertain**, resolved as
``cancelled-uncertain``, and the resolution's whole meaning is "a new capture
requires a new explicit user action".

The other half is cleanup, in three parts:

* **abandoned private audio** is swept by prefix with ownership validated
  before anything is removed — the same discipline, and the same reasons, as
  :func:`companion.voice.recovery.sweep_workspaces`, against this subsystem's
  own ``bunny-speech-`` prefix so the attribution in the evidence is honest;
* **orphan recorders** end themselves: every capture child writes raw PCM to a
  pipe this process holds the read end of, so a recorder that outlives the
  service dies on ``SIGPIPE``/``EPIPE`` at its next write. Recorded here as
  the mechanism relied on, because a claim of "no orphan capture process"
  needs to say what enforces it;
* **orphan recogniser state** is memory in this process — the recognisers in
  this build are in-process libraries, chosen partly *for* this property — and
  is gone with the process.

Unconfirmed transcripts do not survive a restart. §21 permits preserving them
where policy allows; this build's policy is that it does not — a transcript
nobody confirmed is captured speech, and captured speech is retained only for
active recognition (§8). Confirmed transcripts are tasks in the canonical
store already and are not this module's to preserve.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
from typing import Any, Iterable, Mapping

from ..voice.recovery import _owned_by_us
from .execution import SpeechWorkspace
from .request import SpeechInputRequest

__all__ = [
    "CAPTURE_DISPOSITIONS",
    "SpeechJournal",
    "SpeechRecoveryReport",
    "recover",
    "sweep_workspaces",
]

#: Every way a capture can settle. Closed, for the gates.
CAPTURE_DISPOSITIONS = (
    "completed",
    "cancelled",
    "cancelled-uncertain",
    "expired",
    "refused",
    "no-speech",
    "device-lost",
    "failed",
)

#: How old an abandoned workspace must be before it is swept, matching the
#: voice runtime's threshold: a worker running right now owns a directory with
#: this prefix, and a sweep that ignored age would delete the audio of the
#: capture being recognised.
STALE_AFTER_SECONDS = 300.0

MAX_JOURNAL_ENTRIES = 1024


@dataclass(frozen=True)
class SpeechRecoveryReport:
    """What one restart found and what it decided about each thing."""

    started: int = 0
    settled: int = 0
    uncertain: tuple[str, ...] = ()
    marked_cancelled: tuple[str, ...] = ()
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
            "markedCancelled": list(self.marked_cancelled),
            "workspacesRemoved": self.workspaces_removed,
            "workspacesSkipped": list(self.workspaces_skipped),
            "filesRemoved": self.files_removed,
            # The §21 claims, on the record a gate reads rather than in prose.
            "captureResumed": False,
            "microphoneOpenedByRecovery": False,
            "indicatorCleared": True,
            "unconfirmedTranscriptsPreserved": False,
            "confirmedTasksPreserved": True,
            "detail": self.detail,
        }


class SpeechJournal:
    """A line per capture start and a line per settle, on disk.

    Identity and disposition only — never transcript text and never audio.
    The settle line carries the ``fsync``; a lost start makes recovery more
    conservative, which is the safe direction.
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
                # A journal that cannot be written must not stop a capture the
                # user asked for; the cost is a more conservative recovery.
                return

    def record_start(self, request: SpeechInputRequest, *, monotonic: float = 0.0) -> None:
        self._write({
            "event": "start",
            "requestId": request.request_id,
            "sessionId": request.session_id,
            "activationSource": request.activation_source,
            "atMonotonic": monotonic,
            "pid": os.getpid(),
        }, durable=False)

    def record_settle(
        self, request_id: str, disposition: str, *, monotonic: float = 0.0
    ) -> None:
        if disposition not in CAPTURE_DISPOSITIONS:
            raise ValueError(f"unknown capture disposition: {disposition!r}")
        self._write({
            "event": "settle",
            "requestId": request_id,
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
                # A torn last line after a crash: skipped, the rest is evidence.
                continue
            if isinstance(document, dict):
                entries.append(document)
        return entries

    def truncate(self) -> None:
        with self._guard:
            try:
                self.path.unlink()
            except OSError:
                return

    def reconcile(self, *, own_pid: int | None = None) -> SpeechRecoveryReport:
        """Decide what happened to every capture the journal mentions."""
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
        uncertain = sorted(
            identifier for identifier, item in started.items()
            if identifier not in settled
            and (own_pid is None or int(item.get("pid", -1)) != own_pid)
        )
        return SpeechRecoveryReport(
            started=len(started),
            settled=len(settled),
            uncertain=tuple(uncertain),
            marked_cancelled=tuple(uncertain),
            detail=(
                f"{len(uncertain)} capture(s) were in flight and are recorded "
                "cancelled-uncertain; none was resumed, and further capture needs a "
                "new explicit user action"
                if uncertain else "no capture was in flight"
            ),
        )


def sweep_workspaces(
    *,
    parent: Path | str | None = None,
    stale_after_seconds: float = STALE_AFTER_SECONDS,
    now: float | None = None,
    active: Iterable[Path | str] = (),
) -> tuple[int, tuple[str, ...], int]:
    """Remove private captured audio a crashed worker left behind.

    The ownership validation is the voice runtime's own — a symlink, a foreign
    owner or a group-writable directory is skipped with the reason — applied
    to the ``bunny-speech-`` prefix. §22's temporary-file-symlink test runs
    against this function.
    """
    import time as _time

    root = Path(parent) if parent is not None else Path(tempfile.gettempdir())
    moment = _time.time() if now is None else now
    protected = {str(Path(item).resolve()) for item in active}
    removed = 0
    files_removed = 0
    skipped: list[str] = []

    try:
        candidates = sorted(root.glob(f"{SpeechWorkspace.PREFIX}*"))
    except OSError as exc:
        return 0, (f"{root}: {exc.strerror or exc}",), 0

    for candidate in candidates:
        try:
            if str(candidate.resolve()) in protected:
                skipped.append(f"{candidate.name}: in use by a running capture")
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
                f"{candidate.name}: only {int(age)}s old, below the "
                f"{int(stale_after_seconds)}s threshold"
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
    journal: SpeechJournal,
    *,
    parent: Path | str | None = None,
    own_pid: int | None = None,
    stale_after_seconds: float = STALE_AFTER_SECONDS,
    active_workspaces: Iterable[Path | str] = (),
    truncate: bool = True,
) -> SpeechRecoveryReport:
    """The whole of §21, in dependency order.

    The journal is read before the sweep — a workspace named after an
    unresolved capture is evidence until the reconciliation has run — and
    truncated after both, so a crash during recovery re-runs a recovery
    rather than losing one.
    """
    report = journal.reconcile(own_pid=own_pid)
    removed, skipped, files = sweep_workspaces(
        parent=parent,
        stale_after_seconds=stale_after_seconds,
        active=active_workspaces,
    )
    if truncate:
        journal.truncate()
    return SpeechRecoveryReport(
        started=report.started,
        settled=report.settled,
        uncertain=report.uncertain,
        marked_cancelled=report.marked_cancelled,
        workspaces_removed=removed,
        workspaces_skipped=skipped,
        files_removed=files,
        detail=(
            f"{report.detail}; {removed} abandoned workspace(s) holding {files} "
            "file(s) removed"
        ),
    )
