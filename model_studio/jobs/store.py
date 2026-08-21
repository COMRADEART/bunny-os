# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Job records that survive a crash without lying about what happened.

A training run is the longest-lived thing in this subsystem and the one most
likely to be interrupted: laptops sleep, WSL virtual machines idle out, sessions
end, power goes. So the record on disk has to answer a question the record alone
cannot answer — *is this job still running, or did it stop?* — and the answer
"the file says training, so it is training" is wrong every time it matters.

Two facts are written with every state change, and together they settle it:

``ownerPid``
    the process that made the transition. Gone means gone.
``ownerBootId``
    the machine's boot identity. A record from a previous boot is from a
    previous boot; no process check is needed and none would be meaningful,
    because that pid now belongs to something else.

:meth:`JobStore.recover` applies both and moves any orphan out of its active
state into ``failed``. It is called on every load, so there is no path that
reads a stale ``training`` record and treats it as live — and, more to the
point, no path by which an interrupted run is later found in a state that
reads as success. ``completed`` is only ever written by the one transition that
writes it, from ``evaluating``, after evaluation returned.

Writes are atomic: a temporary file in the same directory, then
:func:`os.replace`. The retry loop around it is not decoration — on Windows,
``os.replace`` onto a path another process has open raises ``PermissionError``,
which this repository has already met once in the Companion's approval store,
and a job record that failed to save because a text editor had it open would
otherwise lose a state transition silently.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import secrets
import sys
import time
from typing import Any, Callable, Iterator, Mapping

from ..errors import ModelStudioError
from . import state as machine

__all__ = [
    "JobRecord",
    "JobStore",
    "StateChange",
    "boot_identity",
    "default_jobs_root",
    "process_alive",
]

_MAX_RECORD_BYTES = 8 * 1024 * 1024


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def default_jobs_root() -> Path:
    """Where job records live, following the Companion's own state convention."""
    override = os.environ.get("BUNNY_MODEL_STUDIO_HOME", "").strip()
    if override:
        return Path(override) / "jobs"
    configured = os.environ.get("XDG_STATE_HOME", "").strip()
    base = Path(configured) if configured else Path.home() / ".local" / "state"
    return base / "bunny-os" / "model-studio" / "jobs"


def boot_identity() -> str:
    """An identifier that changes when the machine restarts.

    Linux hands one out directly. Elsewhere the boot time is close enough for
    the question being asked — "is this record from the system that is running
    now?" — and where neither is available the identity is empty, which
    :func:`process_alive` alone then has to settle.
    """
    try:
        value = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
        if value:
            return value
    except OSError:
        pass
    try:
        import psutil  # type: ignore

        return f"boot-time-{int(psutil.boot_time())}"
    except Exception:  # noqa: BLE001 - psutil is optional everywhere
        pass
    if sys.platform == "win32":  # pragma: no cover - platform-specific
        try:
            import ctypes

            # Milliseconds since boot, quantised to the hour: stable within a
            # session, different after a restart, and needing no dependency.
            ticks = ctypes.windll.kernel32.GetTickCount64()
            started = time.time() - ticks / 1000
            return f"boot-time-{int(started // 3600)}"
        except Exception:  # noqa: BLE001
            return ""
    return ""


def process_alive(pid: int) -> bool:
    """Whether ``pid`` is a live process. Conservative: unsure means alive."""
    if pid <= 0:
        return False
    if sys.platform == "win32":  # pragma: no cover - platform-specific
        try:
            import ctypes

            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if not handle:
                return False
            exit_code = ctypes.c_ulong()
            ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            ctypes.windll.kernel32.CloseHandle(handle)
            return exit_code.value == 259  # STILL_ACTIVE
        except Exception:  # noqa: BLE001
            return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # It exists and belongs to somebody else.
        return True
    except OSError:
        return True
    return True


@dataclass(frozen=True)
class StateChange:
    """One transition, kept forever. The history is the audit trail."""

    at: str
    was: str
    became: str
    detail: str = ""
    pid: int = 0

    def to_json(self) -> dict[str, Any]:
        return {"at": self.at, "was": self.was, "became": self.became,
                "detail": self.detail, "pid": self.pid}


@dataclass(frozen=True)
class JobRecord:
    """One training job, as it exists on disk."""

    job_id: str
    state: str = machine.CREATED
    created_at: str = ""
    updated_at: str = ""
    config_path: str = ""
    config_sha256: str = ""
    config_canonical_sha256: str = ""
    run_name: str = ""
    output_directory: str = ""
    owner_pid: int = 0
    owner_boot_id: str = ""
    owner_host: str = ""
    detail: str = ""
    history: tuple[StateChange, ...] = ()
    preflight: dict[str, Any] = field(default_factory=dict)
    plan: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] = field(default_factory=dict)
    evaluation: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)

    @property
    def active(self) -> bool:
        return machine.is_active(self.state)

    @property
    def terminal(self) -> bool:
        return machine.is_terminal(self.state)

    def orphaned(self, *, boot_id: str) -> bool:
        """Active, but the process that was doing it is not there any more."""
        if not self.active:
            return False
        if self.owner_boot_id and boot_id and self.owner_boot_id != boot_id:
            return True
        if self.owner_host and self.owner_host != platform.node():
            # A record written on another machine, on a shared directory. Not
            # ours to declare dead, and not ours to treat as live either.
            return False
        return not process_alive(self.owner_pid)

    def to_json(self) -> dict[str, Any]:
        return {
            "jobId": self.job_id,
            "state": self.state,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "configPath": self.config_path,
            "configSha256": self.config_sha256,
            "configCanonicalSha256": self.config_canonical_sha256,
            "runName": self.run_name,
            "outputDirectory": self.output_directory,
            "owner": {
                "pid": self.owner_pid,
                "bootId": self.owner_boot_id,
                "host": self.owner_host,
            },
            "detail": self.detail,
            "history": [item.to_json() for item in self.history],
            "preflight": dict(self.preflight),
            "plan": dict(self.plan),
            "result": dict(self.result),
            "evaluation": dict(self.evaluation),
            "provenance": dict(self.provenance),
            "config": dict(self.config),
        }

    @classmethod
    def from_json(cls, document: Mapping[str, Any]) -> "JobRecord":
        owner = document.get("owner") or {}
        if not isinstance(owner, Mapping):
            owner = {}
        state = str(document.get("state", ""))
        if state not in machine.STATES:
            raise ModelStudioError(f"job record has unknown state {state!r}")
        history = tuple(
            StateChange(
                at=str(item.get("at", "")),
                was=str(item.get("was", "")),
                became=str(item.get("became", "")),
                detail=str(item.get("detail", "")),
                pid=int(item.get("pid", 0) or 0),
            )
            for item in document.get("history", [])
            if isinstance(item, Mapping)
        )
        return cls(
            job_id=str(document.get("jobId", "")),
            state=state,
            created_at=str(document.get("createdAt", "")),
            updated_at=str(document.get("updatedAt", "")),
            config_path=str(document.get("configPath", "")),
            config_sha256=str(document.get("configSha256", "")),
            config_canonical_sha256=str(document.get("configCanonicalSha256", "")),
            run_name=str(document.get("runName", "")),
            output_directory=str(document.get("outputDirectory", "")),
            owner_pid=int(owner.get("pid", 0) or 0),
            owner_boot_id=str(owner.get("bootId", "")),
            owner_host=str(owner.get("host", "")),
            detail=str(document.get("detail", "")),
            history=history,
            preflight=dict(document.get("preflight") or {}),
            plan=dict(document.get("plan") or {}),
            result=dict(document.get("result") or {}),
            evaluation=dict(document.get("evaluation") or {}),
            provenance=dict(document.get("provenance") or {}),
            config=dict(document.get("config") or {}),
        )


class JobStore:
    """Job records in a directory, one JSON file each."""

    def __init__(self, root: Path | str | None = None, *,
                 clock: Callable[[], str] = _now,
                 boot_id: str | None = None) -> None:
        self.root = Path(root) if root is not None else default_jobs_root()
        self._clock = clock
        self._boot_id = boot_id if boot_id is not None else boot_identity()

    # -- paths -------------------------------------------------------------- #

    def path_for(self, job_id: str) -> Path:
        if not job_id or "/" in job_id or "\\" in job_id or job_id.startswith("."):
            raise ModelStudioError(f"{job_id!r} is not a usable job identifier")
        return self.root / f"{job_id}.json"

    # -- writing ------------------------------------------------------------ #

    def _write(self, record: JobRecord) -> JobRecord:
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.path_for(record.job_id)
        payload = json.dumps(record.to_json(), indent=2, sort_keys=True) + "\n"
        temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        temporary.write_text(payload, encoding="utf-8")
        for attempt in range(5):
            try:
                os.replace(temporary, target)
                break
            except PermissionError:  # pragma: no cover - Windows sharing
                if attempt == 4:
                    temporary.unlink(missing_ok=True)
                    raise
                time.sleep(0.05 * (attempt + 1))
        return record

    def create(self, *, config: Any = None, job_id: str = "", detail: str = "") -> JobRecord:
        """A new job in ``created``. The identifier is time-ordered and random.

        Time-ordered so a directory listing is chronological without parsing
        every file; random-suffixed so two runs started in the same second do
        not collide and silently overwrite one another's record.
        """
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        identifier = job_id or f"{stamp}-{secrets.token_hex(4)}"
        now = self._clock()
        record = JobRecord(
            job_id=identifier,
            state=machine.CREATED,
            created_at=now,
            updated_at=now,
            owner_pid=os.getpid(),
            owner_boot_id=self._boot_id,
            owner_host=platform.node(),
            detail=detail,
            history=(StateChange(at=now, was="", became=machine.CREATED, detail=detail, pid=os.getpid()),),
        )
        if config is not None:
            record = replace(
                record,
                config_path=getattr(config, "source_path", ""),
                config_sha256=getattr(config, "file_sha256", ""),
                config_canonical_sha256=getattr(config, "canonical_sha256", ""),
                run_name=getattr(config, "run_name", ""),
                output_directory=str(getattr(config, "output_directory", "")),
                config=config.to_json() if hasattr(config, "to_json") else {},
            )
        if self.path_for(identifier).exists():
            raise ModelStudioError(f"job {identifier} already exists")
        return self._write(record)

    def transition(self, record: JobRecord, target: str, *, detail: str = "",
                   **updates: Any) -> JobRecord:
        """Move a job. Refuses any edge the machine does not have.

        Every field a caller wants to attach to the new state is passed here and
        written in the same atomic write as the state itself. Writing the result
        and then the state would leave a window in which a crash produces a
        record that says ``training`` and holds a finished result — the exact
        ambiguity this store exists to remove.
        """
        machine.check_transition(record.state, target)
        now = self._clock()
        change = StateChange(at=now, was=record.state, became=target, detail=detail, pid=os.getpid())
        moved = replace(
            record,
            state=target,
            updated_at=now,
            detail=detail,
            owner_pid=os.getpid(),
            owner_boot_id=self._boot_id,
            owner_host=platform.node(),
            history=(*record.history, change),
            **updates,
        )
        return self._write(moved)

    # -- reading ------------------------------------------------------------ #

    def load(self, job_id: str, *, recover: bool = True) -> JobRecord:
        path = self.path_for(job_id)
        try:
            data = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise ModelStudioError(f"no job {job_id}") from exc
        except OSError as exc:
            raise ModelStudioError(f"cannot read job {job_id}: {exc}") from exc
        if len(data) > _MAX_RECORD_BYTES:
            raise ModelStudioError(f"job record {job_id} is implausibly large")
        try:
            document = json.loads(data)
        except json.JSONDecodeError as exc:
            raise ModelStudioError(f"job record {job_id} is not valid JSON: {exc}") from exc
        record = JobRecord.from_json(document)
        return self.recover(record) if recover else record

    def list(self, *, recover: bool = True) -> list[JobRecord]:
        if not self.root.is_dir():
            return []
        records: list[JobRecord] = []
        for path in sorted(self.root.glob("*.json")):
            try:
                records.append(self.load(path.stem, recover=recover))
            except ModelStudioError:
                # An unreadable record is reported by `load` when named
                # directly. A listing skips it rather than refusing to list
                # anything, and the file is still there to be looked at.
                continue
        return records

    def __iter__(self) -> Iterator[JobRecord]:
        return iter(self.list())

    # -- crash recovery ----------------------------------------------------- #

    def recover(self, record: JobRecord) -> JobRecord:
        """Move an orphaned active job to ``failed``, and persist that.

        This is the function that makes the guarantee real. It runs on every
        load, so no reader ever sees an interrupted run in a state that suggests
        it is still going — and, because ``failed`` is where it lands rather
        than anywhere on the success path, an interrupted run can never be
        mistaken for a finished one.
        """
        if not record.orphaned(boot_id=self._boot_id):
            return record
        reason = (
            f"the process that was running this job (pid {record.owner_pid} on "
            f"{record.owner_host or 'this host'}) is no longer present"
        )
        if record.owner_boot_id and self._boot_id and record.owner_boot_id != self._boot_id:
            reason = (
                f"this record was written before a restart (boot {record.owner_boot_id[:8]}, "
                f"now {self._boot_id[:8]}); the run did not finish"
            )
        return self.transition(
            record,
            machine.FAILED,
            detail=f"interrupted in {record.state}: {reason}",
        )

    def recover_all(self) -> list[JobRecord]:
        """Recover every orphan. Returns the ones that were changed."""
        changed: list[JobRecord] = []
        for record in self.list(recover=False):
            recovered = self.recover(record)
            if recovered.state != record.state:
                changed.append(recovered)
        return changed
