"""XDG paths and secure atomic JSON persistence for Bunny Shell."""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Iterator


def _xdg(name: str, fallback: str) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else Path.home() / fallback


def config_dir() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config") / "bunny-shell"


def state_dir() -> Path:
    return _xdg("XDG_STATE_HOME", ".local/state") / "bunny-shell"


def cache_dir() -> Path:
    return _xdg("XDG_CACHE_HOME", ".cache") / "bunny-shell"


def runtime_dir() -> Path:
    value = os.environ.get("XDG_RUNTIME_DIR")
    if value:
        return Path(value) / "bunny-shell"
    return state_dir() / "runtime"


def ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass


def assert_private_file(path: Path) -> None:
    """Reject symlinked or cross-user state on POSIX before consuming it."""
    if not path.exists():
        return
    if path.is_symlink():
        raise PermissionError(f"refusing symlinked state file: {path}")
    stat = path.stat()
    if os.name == "posix":
        if stat.st_uid != os.getuid():
            raise PermissionError(f"state file is owned by another user: {path}")
        if stat.st_mode & 0o077:
            raise PermissionError(f"state file permissions are too broad: {path}")


def atomic_write_json(path: Path, value: Any) -> None:
    ensure_private_dir(path.parent)
    payload = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            temp_path.chmod(0o600)
        except OSError:
            pass
        temp_path.replace(path)
    finally:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass


@contextmanager
def file_lock(path: Path, timeout: float = 2.0) -> Iterator[None]:
    """Small cross-platform lock for short state transactions."""
    ensure_private_dir(path.parent)
    deadline = time.monotonic() + timeout
    while True:
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
            break
        except FileExistsError:
            try:
                if time.time() - path.stat().st_mtime > 30:
                    path.unlink()
                    continue
            except FileNotFoundError:
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError(f"state is busy: {path}")
            time.sleep(0.025)
    try:
        yield
    finally:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


class JsonStore:
    def __init__(self, path: Path, default: dict[str, Any]) -> None:
        self.path = path
        self.default = default
        self.lock_path = path.with_suffix(path.suffix + ".lock")

    def read(self) -> dict[str, Any]:
        if not self.path.exists():
            return json.loads(json.dumps(self.default))
        assert_private_file(self.path)
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid state file {self.path}: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"state file must contain an object: {self.path}")
        return value

    def write(self, value: dict[str, Any]) -> None:
        atomic_write_json(self.path, value)

    @contextmanager
    def transaction(self) -> Iterator[dict[str, Any]]:
        with file_lock(self.lock_path):
            value = self.read()
            yield value
            self.write(value)
