# SPDX-License-Identifier: GPL-3.0-or-later
"""Versioned, user-owned Bunny workspace metadata."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import os
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from . import WORKSPACE_SCHEMA_VERSION
from .paths import JsonStore, state_dir


_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_SECRET_KEY = re.compile(r"(?:api.?key|credential|password|secret|token)", re.IGNORECASE)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_name(name: str) -> str:
    value = name.strip()
    if not value or len(value) > 80 or any(ord(char) < 32 for char in value):
        raise ValueError("workspace name must contain 1-80 printable characters")
    return value


def _assert_no_secrets(value: Any, key: str = "") -> None:
    if key and _SECRET_KEY.search(key):
        raise ValueError("workspace metadata may not contain credentials or secrets")
    if isinstance(value, dict):
        for child_key, child_value in value.items():
            _assert_no_secrets(child_value, str(child_key))
    elif isinstance(value, list):
        for child in value:
            _assert_no_secrets(child)


def _project_path(path: str) -> str:
    candidate = Path(path).expanduser()
    if not candidate.exists() or not candidate.is_dir():
        raise ValueError("project path must be an existing directory")
    resolved = candidate.resolve()
    if os.name == "posix":
        home = Path.home().resolve()
        homes = Path("/home")
        try:
            resolved.relative_to(homes)
        except ValueError:
            pass
        else:
            try:
                resolved.relative_to(home)
            except ValueError as exc:
                raise PermissionError("project path belongs to another user's home") from exc
    return str(resolved)


class WorkspaceStore:
    def __init__(self, path: Path | None = None) -> None:
        self.store = JsonStore(
            path or state_dir() / "workspaces.json",
            {"schemaVersion": WORKSPACE_SCHEMA_VERSION, "revision": 0, "items": []},
        )

    def _validate_state(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        if state.get("schemaVersion") != WORKSPACE_SCHEMA_VERSION:
            raise ValueError("unsupported workspace schema version")
        items = state.get("items")
        if not isinstance(items, list):
            raise ValueError("workspace items must be a list")
        identifiers: set[str] = set()
        for item in items:
            if not isinstance(item, dict) or not _ID.fullmatch(str(item.get("id", ""))):
                raise ValueError("workspace has an invalid id")
            if item["id"] in identifiers:
                raise ValueError("workspace ids must be unique")
            identifiers.add(item["id"])
            _assert_no_secrets(item)
        return items

    def list(self, include_archived: bool = False) -> list[dict[str, Any]]:
        items = self._validate_state(self.store.read())
        return deepcopy([item for item in items if include_archived or not item.get("archivedAt")])

    def get(self, workspace_id: str) -> dict[str, Any]:
        for item in self.list(include_archived=True):
            if item["id"] == workspace_id:
                return item
        raise KeyError(f"workspace not found: {workspace_id}")

    def _change(self, workspace_id: str, operation: Any) -> dict[str, Any]:
        if not _ID.fullmatch(workspace_id):
            raise ValueError("invalid workspace id")
        changed: dict[str, Any] | None = None
        with self.store.transaction() as state:
            items = self._validate_state(state)
            for item in items:
                if item["id"] == workspace_id:
                    operation(item)
                    item["updatedAt"] = _now()
                    _assert_no_secrets(item)
                    changed = deepcopy(item)
                    state["revision"] = int(state.get("revision", 0)) + 1
                    break
            else:
                raise KeyError(f"workspace not found: {workspace_id}")
        assert changed is not None
        return changed

    def create(self, name: str, project_path: str | None = None) -> dict[str, Any]:
        timestamp = _now()
        item: dict[str, Any] = {
            "id": f"ws-{uuid4().hex[:16]}",
            "name": _safe_name(name),
            "taskIds": [],
            "applicationWindows": [],
            "terminalSessions": [],
            "recentFiles": [],
            "permissions": [],
            "sandboxSessions": [],
            "checkpoints": [],
            "createdAt": timestamp,
            "updatedAt": timestamp,
        }
        if project_path:
            item["projectPath"] = _project_path(project_path)
        with self.store.transaction() as state:
            items = self._validate_state(state)
            items.append(item)
            state["revision"] = int(state.get("revision", 0)) + 1
        return deepcopy(item)

    def rename(self, workspace_id: str, name: str) -> dict[str, Any]:
        return self._change(workspace_id, lambda item: item.update(name=_safe_name(name)))

    def duplicate(self, workspace_id: str, name: str | None = None) -> dict[str, Any]:
        original = self.get(workspace_id)
        timestamp = _now()
        duplicate = deepcopy(original)
        duplicate.update(
            id=f"ws-{uuid4().hex[:16]}",
            name=_safe_name(name or f"{original['name']} copy"),
            createdAt=timestamp,
            updatedAt=timestamp,
        )
        duplicate.pop("archivedAt", None)
        with self.store.transaction() as state:
            items = self._validate_state(state)
            items.append(duplicate)
            state["revision"] = int(state.get("revision", 0)) + 1
        return duplicate

    def archive(self, workspace_id: str) -> dict[str, Any]:
        return self._change(workspace_id, lambda item: item.update(archivedAt=_now()))

    def restore(self, workspace_id: str) -> dict[str, Any]:
        def restore_item(item: dict[str, Any]) -> None:
            item.pop("archivedAt", None)
        return self._change(workspace_id, restore_item)

    def attach_project(self, workspace_id: str, project_path: str) -> dict[str, Any]:
        value = _project_path(project_path)
        return self._change(workspace_id, lambda item: item.update(projectPath=value))

    def detach_project(self, workspace_id: str) -> dict[str, Any]:
        def detach(item: dict[str, Any]) -> None:
            item.pop("projectPath", None)
        return self._change(workspace_id, detach)

    def attach_thread(self, workspace_id: str, thread_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", thread_id):
            raise ValueError("invalid Bunny thread id")
        return self._change(workspace_id, lambda item: item.update(bunnyThreadId=thread_id))
