"""Fixed broker operations.  No operation accepts an executable or argv."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import gzip
import io
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tarfile
import tempfile
import threading
import time
from typing import Any

from .auth import PeerIdentity


class BackendError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


_ENV = {
    "PATH": "/usr/sbin:/usr/bin",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "HOME": "/var/lib/bunny-system-broker",
}
_OUTPUT_LIMIT = 1024 * 1024
_STATUS_PATH = Path("/var/lib/bunny-os/update/status.json")
_UPDATE_PREFERENCE_PATH = Path("/var/lib/bunny-os/update/automatic-check-enabled.json")
_RECOVERY_PATH = Path("/var/lib/bunny-os/recovery/scheduled.json")
_RELEASE_PATH = Path("/usr/lib/bunny-os/release.json")
_SUPPORT_ROOT = Path("/var/lib/bunny-os/support")
_SECRET_PATTERN = re.compile(
    r"(?i)(authorization|api[_-]?key|token|password|secret)(\s*[:=]\s*)([^\s,;]+)"
)


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


def _run(argv: list[str], timeout: int, cancel: threading.Event) -> CommandResult:
    if not argv or not all(isinstance(value, str) and "\x00" not in value for value in argv):
        raise BackendError("internal_error", "invalid fixed backend command")
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=errors,
            env=_ENV,
            start_new_session=True,
            close_fds=True,
        )
        deadline = time.monotonic() + timeout
        while process.poll() is None:
            if cancel.is_set():
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=3)
                raise BackendError("cancelled", "request was cancelled")
            if time.monotonic() >= deadline:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=3)
                raise BackendError("timeout", "operation exceeded its fixed timeout")
            time.sleep(0.05)
        output.seek(0)
        errors.seek(0)
        stdout = output.read(_OUTPUT_LIMIT + 1)
        stderr = errors.read(_OUTPUT_LIMIT + 1)
    if len(stdout) > _OUTPUT_LIMIT or len(stderr) > _OUTPUT_LIMIT:
        raise BackendError("output_too_large", "operation output exceeded the broker limit")
    return CommandResult(process.returncode, stdout.decode("utf-8", "replace"), stderr.decode("utf-8", "replace"))


def _json_file(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else fallback
    except (OSError, json.JSONDecodeError):
        return fallback


def _write_fixed_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + f".tmp.{os.getpid()}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", closefd=False) as handle:
            json.dump(value, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)
    os.replace(temporary, path)


def _system_status() -> dict[str, Any]:
    release = _json_file(_RELEASE_PATH, {})
    os_release: dict[str, str] = {}
    try:
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                os_release[key] = value.strip().strip('"')
    except OSError:
        pass
    return {
        "state": "degraded" if not release else "ready",
        "os": {"id": os_release.get("ID", "unknown"), "versionId": os_release.get("VERSION_ID", "unknown")},
        "bunnyOs": release,
        "offlineCapable": True,
    }


def _service_status(service: str, cancel: threading.Event) -> dict[str, Any]:
    result = _run(["/usr/bin/systemctl", "show", service, "--property=LoadState,ActiveState,SubState", "--value"], 5, cancel)
    values = result.stdout.splitlines()
    return {
        "service": service,
        "loadState": values[0] if len(values) > 0 else "unknown",
        "activeState": values[1] if len(values) > 1 else "unknown",
        "subState": values[2] if len(values) > 2 else "unknown",
    }


def _network_status() -> dict[str, Any]:
    interfaces: list[dict[str, Any]] = []
    root = Path("/sys/class/net")
    if root.is_dir():
        for entry in sorted(root.iterdir(), key=lambda item: item.name):
            try:
                state = (entry / "operstate").read_text(encoding="ascii").strip()
                kind = "loopback" if entry.name == "lo" else "network"
                interfaces.append({"name": entry.name, "state": state, "kind": kind})
            except OSError:
                continue
    return {"interfaces": interfaces, "remoteAccessEnabled": False}


def _bootc_status(cancel: threading.Event) -> dict[str, Any]:
    if not Path("/usr/bin/bootc").exists():
        return {"available": False, "deployments": []}
    result = _run(["/usr/bin/bootc", "status", "--json"], 10, cancel)
    if result.returncode != 0:
        raise BackendError("backend_failed", "bootc status failed")
    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise BackendError("backend_failed", "bootc returned malformed status") from exc
    return {"available": True, "status": parsed}


def _start_update(action: str, cancel: threading.Event) -> dict[str, Any]:
    if action not in {"check", "stage", "install"}:
        raise BackendError("internal_error", "invalid update backend action")
    unit = f"bunny-update-agent@{action}.service"
    try:
        result = _run(["/usr/bin/systemctl", "start", "--wait", unit], 5100 if action == "stage" else 120, cancel)
    except BackendError as exc:
        if exc.code in {"cancelled", "timeout"}:
            try:
                _run(["/usr/bin/systemctl", "stop", unit], 30, threading.Event())
            except BackendError:
                pass
        raise
    if result.returncode != 0:
        raise BackendError("backend_failed", f"{action} did not complete successfully")
    return _json_file(_STATUS_PATH, {"state": "unknown", "action": action})


def _power(method: str, cancel: threading.Event) -> dict[str, Any]:
    verb = {"power.shutdown": "poweroff", "power.reboot": "reboot", "power.suspend": "suspend"}[method]
    result = _run(["/usr/bin/systemctl", verb], 20, cancel)
    if result.returncode != 0:
        raise BackendError("backend_failed", f"system {verb} request failed")
    return {"accepted": True, "operation": verb}


def _redact(text: str) -> str:
    return _SECRET_PATTERN.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", text)


def _support_bundle(minutes: int, peer: PeerIdentity, request_id: str, cancel: threading.Event) -> dict[str, Any]:
    _SUPPORT_ROOT.parent.mkdir(parents=True, exist_ok=True, mode=0o711)
    os.chmod(_SUPPORT_ROOT.parent, 0o711)
    _SUPPORT_ROOT.mkdir(parents=True, exist_ok=True, mode=0o711)
    os.chmod(_SUPPORT_ROOT, 0o711)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_id = re.sub(r"[^A-Za-z0-9._-]", "_", request_id)[:64]
    destination = _SUPPORT_ROOT / f"bunny-os-support-{stamp}-{safe_id}.tar.gz"
    journal = _run(
        [
            "/usr/bin/journalctl",
            "--no-pager",
            f"--since=-{minutes} minutes",
            "-u",
            "bunny-system-broker.service",
            "-u",
            "bunny-update-agent@*.service",
            "-u",
            "bunny-health-check.service",
            "--output=short-iso",
        ],
        60,
        cancel,
    )
    status = json.dumps(_system_status(), indent=2, sort_keys=True)
    manifest = {
        "schemaVersion": 1,
        "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "requestedByUid": peer.uid,
        "redacted": True,
        "excluded": ["credentials", "prompts", "memory bodies", "user files", "environment"],
    }
    with tarfile.open(destination, "w:gz") as archive:
        for name, content in {
            "manifest.json": json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            "system-status.json": status + "\n",
            "journal.txt": _redact(journal.stdout + journal.stderr),
        }.items():
            payload = content.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            info.mode = 0o600
            info.mtime = 0
            archive.addfile(info, io.BytesIO(payload))
    os.chmod(destination, 0o600)
    os.chown(destination, peer.uid, peer.gid)
    return {"path": str(destination), "redacted": True, "size": destination.stat().st_size}


def execute(method: str, params: dict[str, Any], peer: PeerIdentity, request_id: str, cancel: threading.Event) -> Any:
    if method == "system.status.read":
        return _system_status()
    if method.startswith("power."):
        return _power(method, cancel)
    if method == "service.status.read":
        return _service_status(params["service"], cancel)
    if method == "network.status.read":
        return _network_status()
    if method == "update.status.read":
        return _json_file(_STATUS_PATH, {"state": "idle", "updatesEnabled": False})
    if method == "update.check":
        return _start_update("check", cancel)
    if method == "update.stage":
        return _start_update("stage", cancel)
    if method == "update.install":
        return _start_update("install", cancel)
    if method == "update.preference.set":
        enabled = params["enabled"]
        if enabled:
            _write_fixed_json(_UPDATE_PREFERENCE_PATH, {
                "schemaVersion": 1,
                "enabled": True,
                "changedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "changedByUid": peer.uid,
            })
            argv = ["/usr/bin/systemctl", "enable", "--now", "bunny-update-agent.timer"]
        else:
            argv = ["/usr/bin/systemctl", "disable", "--now", "bunny-update-agent.timer"]
        result = _run(argv, 30, cancel)
        if result.returncode != 0:
            if enabled:
                try:
                    _UPDATE_PREFERENCE_PATH.unlink()
                except FileNotFoundError:
                    pass
            raise BackendError("backend_failed", "update check preference could not be applied")
        if not enabled:
            try:
                _UPDATE_PREFERENCE_PATH.unlink()
            except FileNotFoundError:
                pass
        return {"enabled": enabled}
    if method == "rollback.list":
        return _bootc_status(cancel)
    if method == "rollback.select":
        if not Path("/usr/bin/bootc").exists():
            raise BackendError("backend_unavailable", "bootc is not installed")
        result = _run(["/usr/bin/bootc", "rollback"], 30, cancel)
        if result.returncode != 0:
            raise BackendError("backend_failed", "bootc rollback selection failed")
        return {"selected": "previous", "rebootRequired": True}
    if method == "recovery.status.read":
        return {"available": Path("/usr/lib/systemd/system/bunny-recovery.target").exists(), "scheduled": _json_file(_RECOVERY_PATH, {})}
    if method == "recovery.schedule":
        value = {
            "schemaVersion": 1,
            "mode": params["mode"],
            "scheduledAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "scheduledByUid": peer.uid,
        }
        _write_fixed_json(_RECOVERY_PATH, value)
        result = _run(["/usr/bin/systemctl", "start", "bunny-recovery-prepare.service"], 15, cancel)
        if result.returncode != 0:
            raise BackendError("backend_failed", "recovery preparation failed")
        return {"scheduled": True, "mode": params["mode"], "rebootRequired": True}
    if method == "logs.export":
        return _support_bundle(params["sinceMinutes"], peer, request_id, cancel)
    if method == "hardware.inventory.read":
        result = _run(["/usr/bin/bunny-os-info", "--json"], 20, cancel)
        if result.returncode != 0:
            raise BackendError("backend_failed", "hardware inventory failed")
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise BackendError("backend_failed", "hardware inventory returned malformed output") from exc
    raise BackendError("unknown_method", "method has no backend")
