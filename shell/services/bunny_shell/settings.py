"""Versioned Bunny Shell settings with explicit policy and scope metadata."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
from typing import Any, Callable

from . import SETTINGS_SCHEMA_VERSION
from .paths import JsonStore, config_dir


def _boolean(value: Any) -> bool:
    if not isinstance(value, bool):
        raise ValueError("value must be boolean")
    return value


def _choice(*choices: str) -> Callable[[Any], str]:
    def check(value: Any) -> str:
        if value not in choices:
            raise ValueError(f"value must be one of: {', '.join(choices)}")
        return str(value)
    return check


def _bounded_int(minimum: int, maximum: int) -> Callable[[Any], int]:
    def check(value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise ValueError(f"value must be an integer from {minimum} to {maximum}")
        return value
    return check


def _alias(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,96}", value):
        raise ValueError("value must be a credential alias or identifier, never a secret")
    return value


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list) or len(value) > 100 or any(not isinstance(item, str) or len(item) > 512 for item in value):
        raise ValueError("value must be a bounded string list")
    return value


DEFINITIONS: dict[str, dict[str, Any]] = {
    "launchBunnyAtLogin": {"default": False, "scope": "user", "owner": "bunny-desktop", "validate": _boolean},
    "defaultProviderAlias": {"default": "local", "scope": "user", "owner": "bunny-core", "validate": _alias},
    "defaultModel": {"default": "automatic", "scope": "user", "owner": "bunny-core", "validate": _alias},
    "localOnlyMode": {"default": False, "scope": "user", "owner": "bunny-core", "validate": _boolean},
    "offlineMode": {"default": False, "scope": "user", "owner": "bunny-shell", "validate": _boolean},
    "cloudFailoverPolicy": {"default": "ask", "scope": "user", "owner": "bunny-core", "validate": _choice("never", "ask")},
    "memoryEnabled": {"default": True, "scope": "user", "owner": "bunny-core", "validate": _boolean},
    "approvedSearchLocations": {"default": [], "scope": "user", "owner": "bunny-search", "validate": _strings},
    "pluginNetworkDefault": {"default": "deny", "scope": "user", "owner": "bunny-core", "validate": _choice("deny", "ask")},
    "unattendedJobs": {"default": False, "scope": "user", "owner": "bunny-core", "validate": _boolean},
    "notifications": {"default": True, "scope": "user", "owner": "bunny-shell", "validate": _boolean},
    "doNotDisturb": {"default": False, "scope": "user", "owner": "bunny-shell", "validate": _boolean},
    "checkpointRetentionDays": {"default": 30, "scope": "user", "owner": "bunny-core", "validate": _bounded_int(1, 365)},
    "modelStoragePath": {"default": "default", "scope": "user", "owner": "bunny-core", "validate": _alias},
    "diagnosticsPolicy": {"default": "local-only", "scope": "user", "owner": "bunny-os", "validate": _choice("local-only")},
    "telemetryEnabled": {"default": False, "scope": "user", "owner": "bunny-os", "validate": _boolean},
    "clipboardHistory": {"default": False, "scope": "user", "owner": "bunny-shell", "validate": _boolean},
    "clipboardExcludedApplications": {"default": [], "scope": "user", "owner": "bunny-shell", "validate": _strings},
    "reducedMotion": {"default": False, "scope": "user", "owner": "bunny-shell", "validate": _boolean},
    "reducedTransparency": {"default": False, "scope": "user", "owner": "bunny-shell", "validate": _boolean},
    "theme": {"default": "system", "scope": "user", "owner": "bunny-shell", "validate": _choice("system", "bunny-light", "bunny-dark", "high-contrast")},
    "textScalePercent": {"default": 100, "scope": "user", "owner": "gnome", "validate": _bounded_int(75, 200)},
}

SECTIONS = (
    "Network", "Bluetooth", "Displays", "Sound", "Power", "Keyboard", "Mouse and Touchpad",
    "Appearance", "Applications", "Notifications", "Privacy", "Users", "Date and Time", "Storage",
    "Updates", "Recovery", "Bunny", "Local Models", "Plugins", "Permissions", "Accessibility", "System Information",
)


def defaults() -> dict[str, Any]:
    return {key: deepcopy(value["default"]) for key, value in DEFINITIONS.items()}


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.store = JsonStore(path or config_dir() / "settings.json", {"schemaVersion": SETTINGS_SCHEMA_VERSION, "revision": 0, "values": defaults()})

    def _validate(self, state: dict[str, Any]) -> dict[str, Any]:
        if state.get("schemaVersion") != SETTINGS_SCHEMA_VERSION or not isinstance(state.get("values"), dict):
            raise ValueError("unsupported settings schema version")
        unknown = set(state["values"]) - set(DEFINITIONS)
        if unknown:
            raise ValueError(f"unknown setting: {sorted(unknown)[0]}")
        merged = defaults()
        merged.update(state["values"])
        for key, value in merged.items():
            DEFINITIONS[key]["validate"](value)
        return merged

    def get_all(self) -> dict[str, Any]:
        return self._validate(self.store.read())

    def describe(self) -> dict[str, Any]:
        return {
            key: {"type": type(meta["default"]).__name__, "default": deepcopy(meta["default"]), "scope": meta["scope"], "policyOwner": meta["owner"], "reset": "default"}
            for key, meta in DEFINITIONS.items()
        }

    def set(self, key: str, value: Any) -> dict[str, Any]:
        if key not in DEFINITIONS:
            raise KeyError(f"unknown setting: {key}")
        checked = DEFINITIONS[key]["validate"](value)
        with self.store.transaction() as state:
            values = self._validate(state)
            values[key] = checked
            if key == "localOnlyMode" and checked:
                values["cloudFailoverPolicy"] = "never"
                values["defaultProviderAlias"] = "local"
            if key == "offlineMode" and checked:
                values["cloudFailoverPolicy"] = "never"
            state["values"] = values
            state["revision"] = int(state.get("revision", 0)) + 1
        return self.get_all()

    def reset(self, key: str | None = None) -> dict[str, Any]:
        if key is not None and key not in DEFINITIONS:
            raise KeyError(f"unknown setting: {key}")
        if self.store.path.exists():
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup = self.store.path.with_name(f"settings.backup.{timestamp}.json")
            shutil.copyfile(self.store.path, backup)
            try:
                backup.chmod(0o600)
            except OSError:
                pass
        with self.store.transaction() as state:
            current = self._validate(state)
            if key:
                current[key] = deepcopy(DEFINITIONS[key]["default"])
            else:
                current = defaults()
            state.update(schemaVersion=SETTINGS_SCHEMA_VERSION, revision=int(state.get("revision", 0)) + 1, values=current)
        return self.get_all()


def parse_value(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text
