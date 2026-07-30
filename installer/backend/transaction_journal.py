# SPDX-License-Identifier: GPL-3.0-or-later
"""Redacted installer transaction journal with irreversible-boundary truth."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping

from operations.redaction import redact


STATES = ("not_started", "planned", "validated", "started", "completed", "failed")
TRANSITIONS = {
    "not_started": {"planned"},
    "planned": {"validated", "failed"},
    "validated": {"started", "failed"},
    "started": {"completed", "failed"},
    "completed": set(),
    "failed": set(),
}


@dataclass
class JournalOperation:
    operation_id: str
    description: str
    destructive: bool
    resume_safe: bool
    state: str = "not_started"
    history: list[dict[str, str]] = field(default_factory=list)

    def transition(self, target: str, *, detail: str = "", timestamp: datetime | None = None) -> None:
        if target not in STATES or target not in TRANSITIONS[self.state]:
            raise ValueError(f"invalid installer journal transition: {self.state} -> {target}")
        if self.destructive and self.state == "started" and target == "failed":
            self.resume_safe = False
        now = (timestamp or datetime.now(timezone.utc)).astimezone(timezone.utc)
        self.history.append({"from": self.state, "to": target, "at": now.isoformat().replace("+00:00", "Z"), "detail": detail[:256]})
        self.state = target

    @property
    def can_resume(self) -> bool:
        return self.resume_safe and self.state in {"not_started", "planned", "validated", "failed"} and not (self.destructive and self.state == "failed")


class InstallationTransactionJournal:
    def __init__(self, installation_id: str, operations: list[JournalOperation]) -> None:
        if not installation_id or len(installation_id) > 128:
            raise ValueError("installation ID is invalid")
        if not operations or len({item.operation_id for item in operations}) != len(operations):
            raise ValueError("journal operations must be non-empty and unique")
        self.installation_id = installation_id
        self.operations = operations

    def operation(self, operation_id: str) -> JournalOperation:
        match = next((item for item in self.operations if item.operation_id == operation_id), None)
        if match is None:
            raise KeyError(operation_id)
        return match

    def export(self) -> dict[str, Any]:
        value: Mapping[str, Any] = {
            "schemaVersion": 1,
            "installationId": self.installation_id,
            "rollbackAfterDestructiveWrite": False,
            "operations": [
                {
                    "operationId": item.operation_id,
                    "description": item.description,
                    "destructive": item.destructive,
                    "resumeSafe": item.can_resume,
                    "state": item.state,
                    "history": item.history,
                }
                for item in self.operations
            ],
        }
        clean = redact(value)
        if not isinstance(clean, dict):
            raise AssertionError("redaction changed journal shape")
        return clean

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(json.dumps(self.export(), sort_keys=True, indent=2) + "\n", encoding="utf-8")
        try:
            temporary.chmod(0o600)
        except OSError:
            pass
        temporary.replace(path)
