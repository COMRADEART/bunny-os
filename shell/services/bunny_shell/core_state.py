# SPDX-License-Identifier: GPL-3.0-or-later
"""Strict read-only projection of server-authoritative Bunny task state."""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
from typing import Any

from .paths import runtime_dir


MAX_SNAPSHOT_BYTES = 1024 * 1024
ALLOWED_TASK_STATES = {"queued", "running", "paused", "blocked", "completed", "failed", "cancelled"}


def _safe_text(value: Any, field: str, maximum: int = 256) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum or any(ord(char) < 32 and char not in "\t" for char in value):
        raise ValueError(f"invalid {field}")
    return value


def validate_snapshot(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Bunny snapshot must be an object")
    expected = {"schemaVersion", "sequence", "tasks", "plans", "approvals", "notifications", "provider", "privacy", "sandbox"}
    if set(value) != expected or value.get("schemaVersion") != 1 or not isinstance(value.get("sequence"), int) or value["sequence"] < 0:
        raise ValueError("Bunny snapshot envelope is invalid")
    for key in ("tasks", "plans", "approvals", "notifications"):
        if not isinstance(value[key], list) or len(value[key]) > 500:
            raise ValueError(f"Bunny snapshot {key} is invalid")
    for task in value["tasks"]:
        if not isinstance(task, dict) or task.get("state") not in ALLOWED_TASK_STATES:
            raise ValueError("Bunny task state is invalid")
        _safe_text(task.get("id"), "task id", 128)
        _safe_text(task.get("title"), "task title")
    for approval in value["approvals"]:
        if not isinstance(approval, dict):
            raise ValueError("approval must be an object")
        for field in ("id", "action", "capability", "scope", "risk", "expiresAt"):
            _safe_text(approval.get(field), f"approval {field}", 512)
        if "alwaysAllowEverything" in approval:
            raise ValueError("unbounded approval is forbidden")
    if not isinstance(value["privacy"], dict) or not isinstance(value["sandbox"], dict):
        raise ValueError("Bunny privacy and sandbox summaries must be objects")
    return value


def read_snapshot(path: Path | None = None) -> dict[str, Any] | None:
    target = path or runtime_dir() / "core-summary.json"
    if not target.exists():
        return None
    if target.is_symlink() or target.stat().st_size > MAX_SNAPSHOT_BYTES:
        raise PermissionError("unsafe Bunny snapshot file")
    stat = target.stat()
    if os.name == "posix" and (stat.st_uid != os.getuid() or stat.st_mode & 0o077):
        raise PermissionError("Bunny snapshot must be private to the session user")
    return validate_snapshot(json.loads(target.read_text(encoding="utf-8")))


def notifications_for_lock_screen(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a privacy-preserving projection for the locked session."""
    validated = validate_snapshot(snapshot)
    projected: list[dict[str, Any]] = []
    for notification in validated["notifications"]:
        if not isinstance(notification, dict):
            continue
        source = str(notification.get("source", "Application"))[:80]
        if notification.get("sensitive", True):
            projected.append({"source": source, "title": "Sensitive notification", "body": "", "actions": []})
        else:
            projected.append({
                "source": source,
                "title": str(notification.get("title", "Notification"))[:160],
                "body": "",
                "actions": [],
            })
    return projected


def shell_status() -> dict[str, Any]:
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", "/run/user/invalid"))
    core_ready = runtime / "bunny" / "core.ready"
    broker_socket = Path("/run/bunny/broker.sock")
    snapshot = None
    try:
        snapshot = read_snapshot()
    except (OSError, ValueError, PermissionError, json.JSONDecodeError):
        pass
    return {
        "bunny": "available" if core_ready.is_file() and snapshot is not None else "unavailable",
        "broker": "available" if broker_socket.exists() and stat_is_socket(broker_socket) else "unavailable",
        "search": "available",
        "desktopUsable": True,
        "privilegedActionsEnabled": broker_socket.exists() and stat_is_socket(broker_socket),
        "taskCount": len(snapshot["tasks"]) if snapshot else 0,
        "pendingApprovalCount": len(snapshot["approvals"]) if snapshot else 0,
        "update": "unknown",
        "sandbox": snapshot.get("sandbox", {}).get("state", "unknown") if snapshot else "unknown",
        "localModel": "unknown" if snapshot else "unavailable",
        "securitySummary": "unknown",
    }


def stat_is_socket(path: Path) -> bool:
    try:
        return path.stat().st_mode & 0o170000 == 0o140000
    except OSError:
        return False
