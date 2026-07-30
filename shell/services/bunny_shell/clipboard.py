# SPDX-License-Identifier: GPL-3.0-or-later
"""Opt-in private clipboard history; never a clipboard monitor by itself."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from pathlib import Path
from typing import Any

from .paths import JsonStore, state_dir
from .settings import SettingsStore


_SENSITIVE = re.compile(r"(?:password|passwd|api[_ -]?key|secret|token|BEGIN [A-Z ]+PRIVATE KEY)", re.IGNORECASE)
MAX_ENTRIES = 50


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ClipboardHistory:
    def __init__(self, path: Path | None = None, settings: SettingsStore | None = None) -> None:
        self.store = JsonStore(path or state_dir() / "clipboard.json", {"schemaVersion": 1, "entries": []})
        self.settings = settings or SettingsStore()

    def _prune(self, value: dict[str, Any]) -> None:
        now = _now()
        retained = []
        for entry in value.get("entries", []):
            try:
                expiry = datetime.fromisoformat(entry["expiresAt"].replace("Z", "+00:00"))
            except (KeyError, TypeError, ValueError):
                continue
            if expiry > now:
                retained.append(entry)
        value["entries"] = retained[-MAX_ENTRIES:]

    def add(self, text: str, application_id: str, *, password_field: bool = False) -> bool:
        settings = self.settings.get_all()
        if not settings["clipboardHistory"] or password_field or application_id in settings["clipboardExcludedApplications"]:
            return False
        if not isinstance(text, str) or not text or len(text.encode("utf-8")) > 64 * 1024:
            return False
        sensitive = bool(_SENSITIVE.search(text))
        expiry = _now() + timedelta(seconds=60 if sensitive else 3600)
        with self.store.transaction() as value:
            self._prune(value)
            value.setdefault("entries", []).append({
                "text": text,
                "applicationId": application_id[:256],
                "sensitive": sensitive,
                "expiresAt": expiry.isoformat().replace("+00:00", "Z"),
            })
            value["entries"] = value["entries"][-MAX_ENTRIES:]
        return True

    def entries(self) -> list[dict[str, Any]]:
        with self.store.transaction() as value:
            self._prune(value)
            return list(value["entries"])

    def clear(self) -> None:
        self.store.write({"schemaVersion": 1, "entries": []})
