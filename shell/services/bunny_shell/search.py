# SPDX-License-Identifier: GPL-3.0-or-later
"""Private metadata-only desktop search with explicit location grants."""

from __future__ import annotations

from datetime import datetime, timezone
import fnmatch
import os
from pathlib import Path
from typing import Any

from . import SEARCH_SCHEMA_VERSION
from .paths import JsonStore, config_dir, state_dir


DEFAULT_EXCLUSIONS = (
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "target",
    "__pycache__",
    "*.key",
    "*.pem",
    "*.p12",
    "*.kdbx",
)
MAX_INDEX_ENTRIES = 20_000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _approved_path(raw: str) -> Path:
    candidate = Path(raw).expanduser()
    if not candidate.exists() or not candidate.is_dir():
        raise ValueError("search location must be an existing directory")
    value = candidate.resolve()
    home = Path.home().resolve()
    if value == home or value == value.parent or value in home.parents:
        raise ValueError("the home directory, filesystem root, and their parents cannot be indexed")
    if os.name == "posix":
        stat = value.stat()
        if stat.st_uid not in {os.getuid(), 0}:
            raise PermissionError("search location belongs to another user")
    return value


class SearchIndex:
    def __init__(self, config_path: Path | None = None, index_path: Path | None = None) -> None:
        self.config = JsonStore(
            config_path or config_dir() / "search.json",
            {
                "schemaVersion": SEARCH_SCHEMA_VERSION,
                "locations": [],
                "exclusions": list(DEFAULT_EXCLUSIONS),
                "contentIndexing": False,
                "cloudSearch": False,
                "maxEntries": MAX_INDEX_ENTRIES,
            },
        )
        self.index = JsonStore(
            index_path or state_dir() / "search-index.json",
            {"schemaVersion": SEARCH_SCHEMA_VERSION, "builtAt": None, "truncated": False, "entries": []},
        )

    def _configuration(self) -> dict[str, Any]:
        value = self.config.read()
        if value.get("schemaVersion") != SEARCH_SCHEMA_VERSION:
            raise ValueError("unsupported search configuration version")
        if value.get("contentIndexing") is not False or value.get("cloudSearch") is not False:
            raise ValueError("Bunny Search Phase 2 only supports local metadata indexing")
        return value

    def locations(self) -> list[dict[str, Any]]:
        return list(self._configuration().get("locations", []))

    def add(self, raw_path: str) -> dict[str, Any]:
        path = _approved_path(raw_path)
        record = {"path": str(path), "enabled": True, "encryption": "unknown", "addedAt": _now()}
        with self.config.transaction() as value:
            locations = value.setdefault("locations", [])
            if any(Path(item["path"]) == path for item in locations):
                raise ValueError("search location is already approved")
            locations.append(record)
        return record

    def remove(self, raw_path: str) -> int:
        path = Path(raw_path).expanduser().resolve()
        removed = 0
        with self.config.transaction() as value:
            before = list(value.get("locations", []))
            value["locations"] = [item for item in before if Path(item["path"]) != path]
            removed = len(before) - len(value["locations"])
        with self.index.transaction() as value:
            entries = list(value.get("entries", []))
            value["entries"] = [item for item in entries if Path(item["root"]) != path]
        return removed

    @staticmethod
    def _excluded(relative: Path, patterns: list[str]) -> bool:
        return any(fnmatch.fnmatch(part, pattern) for part in relative.parts for pattern in patterns)

    def rebuild(self) -> dict[str, Any]:
        config = self._configuration()
        maximum = min(int(config.get("maxEntries", MAX_INDEX_ENTRIES)), MAX_INDEX_ENTRIES)
        patterns = [str(item) for item in config.get("exclusions", DEFAULT_EXCLUSIONS)]
        entries: list[dict[str, Any]] = []
        truncated = False
        for location in config.get("locations", []):
            if not location.get("enabled", False):
                continue
            root = _approved_path(location["path"])
            for current, directories, files in os.walk(root, followlinks=False):
                current_path = Path(current)
                directories[:] = sorted(
                    name for name in directories
                    if not (current_path / name).is_symlink()
                    and not self._excluded((current_path / name).relative_to(root), patterns)
                )
                for name, kind in [(name, "folder") for name in directories] + [(name, "file") for name in sorted(files)]:
                    path = current_path / name
                    relative = path.relative_to(root)
                    if path.is_symlink() or self._excluded(relative, patterns):
                        continue
                    try:
                        stat = path.stat()
                    except OSError:
                        continue
                    entries.append({
                        "name": name,
                        "path": str(path),
                        "relativePath": str(relative),
                        "root": str(root),
                        "kind": kind,
                        "modifiedNs": stat.st_mtime_ns,
                    })
                    if len(entries) >= maximum:
                        truncated = True
                        break
                if truncated:
                    break
            if truncated:
                break
        value = {"schemaVersion": SEARCH_SCHEMA_VERSION, "builtAt": _now(), "truncated": truncated, "entries": entries}
        self.index.write(value)
        return {"entries": len(entries), "truncated": truncated, "builtAt": value["builtAt"]}

    def query(self, text: str, limit: int = 30) -> list[dict[str, Any]]:
        needle = text.strip().casefold()
        if not needle:
            return []
        value = self.index.read()
        scored: list[tuple[int, dict[str, Any]]] = []
        for entry in value.get("entries", []):
            name = str(entry.get("name", "")).casefold()
            relative = str(entry.get("relativePath", "")).casefold()
            if needle not in name and needle not in relative:
                continue
            score = 0 if name.startswith(needle) else 1 if needle in name else 2
            scored.append((score, entry))
        scored.sort(key=lambda pair: (pair[0], pair[1]["name"].casefold(), pair[1]["path"]))
        return [dict(item) for _, item in scored[: max(1, min(limit, 100))]]

    def status(self) -> dict[str, Any]:
        config = self._configuration()
        index = self.index.read()
        return {
            "schemaVersion": SEARCH_SCHEMA_VERSION,
            "approvedLocationCount": sum(1 for item in config.get("locations", []) if item.get("enabled")),
            "entryCount": len(index.get("entries", [])),
            "builtAt": index.get("builtAt"),
            "truncated": bool(index.get("truncated", False)),
            "contentIndexing": False,
            "cloudSearch": False,
        }
