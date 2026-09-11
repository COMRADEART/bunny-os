# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Layer 1 — files are the system of record.

Layout under the memory root::

    records/<scope-kind>/<scope-id>/<plugin>/<id>.json
    records/<scope-kind>/<scope-id>/<plugin>/<id>.md   # optional sidecar
    keys/<id>.dek                                     # sensitive-body DEK
    index/memory.sqlite                               # disposable, rebuilt

Owner-only modes, atomic replace, no symlink follow. Export is ``cp -r``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any, Iterator, Mapping

from companion.errors import MemoryError, StoreError
from companion.ids import valid_id
from companion.memory.record import MemoryRecord

__all__ = [
    "atomic_write_json",
    "atomic_write_text",
    "iter_record_files",
    "private_directory",
    "read_json",
    "record_path",
    "remove_record_files",
    "write_record",
]

_FILE_MODE = 0o600
_DIRECTORY_MODE = 0o700


def private_directory(path: Path) -> None:
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
            pass


def record_path(records_root: Path, record: MemoryRecord) -> Path:
    if not valid_id(record.id):
        raise MemoryError(f"memory id {record.id!r} is not a safe file name")
    for part in (record.scope_kind, record.scope_id, record.plugin):
        if not part or "/" in part or "\\" in part or part in (".", ".."):
            raise MemoryError(f"path component {part!r} is not allowed")
    return records_root / record.scope_kind / record.scope_id / record.plugin / f"{record.id}.json"


def atomic_write_text(path: Path, text: str) -> None:
    private_directory(path.parent)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="\n", dir=str(path.parent),
        prefix=path.name + ".", suffix=".tmp", delete=False,
    )
    temporary = Path(handle.name)
    try:
        with handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(temporary, _FILE_MODE)
        except OSError:
            pass
        os.replace(temporary, path)
    except OSError as exc:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise StoreError(f"{path} could not be written: {exc}") from exc
    _fsync_directory(path.parent)


def atomic_write_json(path: Path, document: Mapping[str, Any]) -> None:
    encoded = json.dumps(document, indent=2, sort_keys=True) + "\n"
    atomic_write_text(path, encoded)


def read_json(path: Path) -> dict[str, Any]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        with os.fdopen(descriptor, "r", encoding="utf-8", closefd=False) as handle:
            document = json.load(handle)
    finally:
        os.close(descriptor)
    if not isinstance(document, dict):
        raise MemoryError(f"{path} is not a JSON object")
    return document


def write_record(records_root: Path, record: MemoryRecord) -> Path:
    path = record_path(records_root, record)
    atomic_write_json(path, record.to_json())
    if record.sidecar_markdown is not None:
        atomic_write_text(path.with_suffix(".md"), record.sidecar_markdown)
    return path


def remove_record_files(path: Path) -> None:
    for candidate in (path, path.with_suffix(".md")):
        try:
            candidate.unlink()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise StoreError(f"{candidate} could not be removed: {exc}") from exc


def iter_record_files(records_root: Path) -> Iterator[Path]:
    if not records_root.is_dir():
        return
    for path in sorted(records_root.rglob("*.json")):
        if path.name.endswith(".tmp") or ".tmp" in path.suffixes:
            continue
        yield path


def _fsync_directory(directory: Path) -> None:
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
