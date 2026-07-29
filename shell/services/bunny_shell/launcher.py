"""Safe desktop-entry parsing and deterministic launcher intent routing."""

from __future__ import annotations

from configparser import ConfigParser
from dataclasses import asdict, dataclass
import os
from pathlib import Path
import re
import shlex
from typing import Any

from .paths import JsonStore, state_dir


_SAFE_EXECUTABLE = re.compile(r"^[A-Za-z0-9._+-]+$")
_FIELD_CODE = re.compile(r"^%(?:f|F|u|U|i|c|k)$")
_SHELL_META = re.compile(r"[;&|`<>\n\r]|\$\(")
_ALLOWED_ABSOLUTE_PREFIXES = ("/usr/bin/", "/usr/libexec/", "/app/bin/", "/opt/bunny/")


@dataclass(frozen=True)
class DesktopApplication:
    desktop_id: str
    name: str
    comment: str
    icon: str
    categories: tuple[str, ...]
    argv: tuple[str, ...]
    terminal: bool
    path: str


@dataclass(frozen=True)
class ShellIntent:
    type: str
    confidence: float
    payload: dict[str, Any]
    requiresConfirmation: bool
    requiresBunnyPermission: bool
    requiresBrokerPermission: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class LauncherState:
    def __init__(self, path: Path | None = None) -> None:
        self.store = JsonStore(path or state_dir() / "launcher.json", {"schemaVersion": 1, "pinned": [], "recent": []})

    @staticmethod
    def _id(desktop_id: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9._+-]{1,256}\.desktop", desktop_id):
            raise ValueError("invalid desktop application id")
        return desktop_id

    def get(self) -> dict[str, list[str]]:
        value = self.store.read()
        if value.get("schemaVersion") != 1 or not isinstance(value.get("pinned"), list) or not isinstance(value.get("recent"), list):
            raise ValueError("invalid launcher state")
        return {"pinned": list(value["pinned"][:50]), "recent": list(value["recent"][:20])}

    def pin(self, desktop_id: str) -> dict[str, list[str]]:
        desktop_id = self._id(desktop_id)
        with self.store.transaction() as value:
            pinned = [item for item in value.get("pinned", []) if item != desktop_id]
            value["pinned"] = [*pinned, desktop_id][-50:]
        return self.get()

    def unpin(self, desktop_id: str) -> dict[str, list[str]]:
        desktop_id = self._id(desktop_id)
        with self.store.transaction() as value:
            value["pinned"] = [item for item in value.get("pinned", []) if item != desktop_id]
        return self.get()

    def record_launch(self, desktop_id: str) -> dict[str, list[str]]:
        desktop_id = self._id(desktop_id)
        with self.store.transaction() as value:
            recent = [item for item in value.get("recent", []) if item != desktop_id]
            value["recent"] = [desktop_id, *recent][:20]
        return self.get()


def _parse_exec(value: str) -> tuple[str, ...]:
    if not value or len(value) > 2048 or _SHELL_META.search(value):
        raise ValueError("desktop entry Exec is empty or contains shell syntax")
    try:
        tokens = shlex.split(value, posix=True)
    except ValueError as exc:
        raise ValueError("desktop entry Exec is malformed") from exc
    if not tokens:
        raise ValueError("desktop entry Exec is empty")
    executable = tokens[0]
    if executable in {"sh", "bash", "dash", "zsh", "env", "sudo", "pkexec"}:
        raise ValueError("desktop entry may not invoke a shell or privilege wrapper")
    if "/" in executable:
        if not executable.startswith(_ALLOWED_ABSOLUTE_PREFIXES) or ".." in Path(executable).parts:
            raise ValueError("desktop entry executable path is outside approved prefixes")
    elif not _SAFE_EXECUTABLE.fullmatch(executable):
        raise ValueError("desktop entry executable name is invalid")
    cleaned: list[str] = []
    for token in tokens:
        if token.startswith("%"):
            if _FIELD_CODE.fullmatch(token):
                continue
            if token == "%%":
                cleaned.append("%")
                continue
            raise ValueError("desktop entry uses an unsupported field code")
        if _SHELL_META.search(token):
            raise ValueError("desktop entry argument contains shell syntax")
        cleaned.append(token)
    return tuple(cleaned)


def parse_desktop_entry(path: Path) -> DesktopApplication:
    if path.is_symlink() or path.suffix != ".desktop" or path.stat().st_size > 256 * 1024:
        raise ValueError("desktop entry path is not a regular bounded .desktop file")
    parser = ConfigParser(interpolation=None, strict=True)
    parser.optionxform = str
    try:
        parser.read(path, encoding="utf-8")
    except Exception as exc:
        raise ValueError("desktop entry cannot be parsed") from exc
    if not parser.has_section("Desktop Entry"):
        raise ValueError("desktop entry group is missing")
    section = parser["Desktop Entry"]
    if section.get("Type") != "Application" or section.getboolean("Hidden", fallback=False) or section.getboolean("NoDisplay", fallback=False):
        raise ValueError("desktop entry is not launchable")
    name = section.get("Name", "").strip()
    if not name or len(name) > 160 or any(ord(char) < 32 for char in name):
        raise ValueError("desktop entry name is invalid")
    icon = section.get("Icon", "").strip()
    if icon and (".." in Path(icon).parts or _SHELL_META.search(icon)):
        raise ValueError("desktop entry icon is invalid")
    url_handlers = section.get("MimeType", "")
    if "x-scheme-handler/" in url_handlers and "%u" not in section.get("Exec", "") and "%U" not in section.get("Exec", ""):
        raise ValueError("URL handler does not declare a URL field code")
    argv = _parse_exec(section.get("Exec", ""))
    return DesktopApplication(
        desktop_id=path.name,
        name=name,
        comment=section.get("Comment", "").strip()[:256],
        icon=icon[:256],
        categories=tuple(item for item in section.get("Categories", "").split(";") if item)[:16],
        argv=argv,
        terminal=section.getboolean("Terminal", fallback=False),
        path=str(path),
    )


def desktop_directories() -> tuple[Path, ...]:
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    data_dirs = [Path(item) for item in os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(os.pathsep) if item]
    return tuple([data_home / "applications", *[item / "applications" for item in data_dirs]])


def installed_applications() -> list[DesktopApplication]:
    found: dict[str, DesktopApplication] = {}
    for directory in desktop_directories():
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.desktop")):
            if path.name in found:
                continue
            try:
                found[path.name] = parse_desktop_entry(path)
            except (OSError, ValueError):
                continue
    return sorted(found.values(), key=lambda item: item.name.casefold())


_SETTINGS = {
    "network": "network",
    "wifi": "wifi",
    "wi-fi": "wifi",
    "bluetooth": "bluetooth",
    "display": "display",
    "sound": "sound",
    "power": "power",
    "privacy": "privacy",
    "accessibility": "universal-access",
    "updates": "bunny-updates",
    "recovery": "bunny-recovery",
}


def route_intent(text: str) -> ShellIntent:
    raw = " ".join(text.strip().split())
    lowered = raw.casefold()
    if not raw:
        return ShellIntent("search", 1.0, {"query": ""}, False, False, False)
    if lowered.startswith(("ask bunny ", "bunny ")):
        prompt = raw.split(" ", 2)[-1] if lowered.startswith("ask bunny ") else raw.split(" ", 1)[-1]
        return ShellIntent("bunny_request", 0.99, {"prompt": prompt, "mode": "ask"}, False, True, False)
    if lowered in {"show active tasks", "open tasks", "show tasks"}:
        return ShellIntent("search", 0.99, {"domain": "tasks", "query": "active"}, False, True, False)
    if lowered in {"show plans", "open plans", "show active plan"}:
        return ShellIntent("search", 0.99, {"domain": "plans", "query": "active"}, False, True, False)
    if lowered in {"check for system updates", "check for updates"}:
        return ShellIntent("system_action", 1.0, {"brokerMethod": "update.check", "params": {}}, True, False, True)
    if lowered in {"restart", "restart computer", "reboot"}:
        return ShellIntent("system_action", 1.0, {"brokerMethod": "power.reboot", "params": {}}, True, False, True)
    if lowered.startswith("open ") and lowered.endswith(" settings"):
        subject = lowered[5:-9].strip()
        panel = _SETTINGS.get(subject)
        if panel:
            return ShellIntent("open_setting", 1.0, {"panel": panel}, False, False, panel.startswith("bunny-") is False and False)
    if lowered.startswith("open ") and (" project" in lowered or lowered.endswith(" workspace")):
        return ShellIntent("open_workspace", 0.85, {"query": raw[5:]}, False, False, False)
    if lowered.startswith("open folder "):
        return ShellIntent("open_folder", 0.98, {"query": raw[12:]}, False, False, False)
    if lowered.startswith("open file "):
        return ShellIntent("open_file", 0.98, {"query": raw[10:]}, False, False, False)
    return ShellIntent("search", 0.65, {"query": raw}, False, False, False)


def application_search(text: str, limit: int = 20) -> list[dict[str, Any]]:
    needle = text.strip().casefold()
    results: list[tuple[int, DesktopApplication]] = []
    for application in installed_applications():
        haystack = f"{application.name} {application.comment} {' '.join(application.categories)}".casefold()
        if needle and needle not in haystack:
            continue
        score = 0 if application.name.casefold().startswith(needle) else 1
        results.append((score, application))
    results.sort(key=lambda pair: (pair[0], pair[1].name.casefold()))
    return [asdict(application) | {"kind": "Application"} for _, application in results[:limit]]
