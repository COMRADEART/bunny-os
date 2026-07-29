"""First-run state and privacy defaults."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping


STEPS = (
    "welcome",
    "language_region",
    "keyboard",
    "privacy",
    "updates",
    "user_profile",
    "bunny_introduction",
    "provider_setup",
    "local_model_setup",
    "search_locations",
    "permissions_overview",
    "backup_recovery",
    "finish",
)
SECRET_KEYS = frozenset({"password", "apikey", "token", "credential", "recoverykey", "secret"})
HOSTNAME = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
USERNAME = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")


DEFAULTS: dict[str, object] = {
    "telemetry": False,
    "cloudAIConfigured": False,
    "remoteDiagnostics": False,
    "screenAccess": False,
    "microphoneAccess": False,
    "cameraAccess": False,
    "searchLocations": [],
    "pluginNetworkAccess": False,
    "bunnyAtLogin": False,
    "bunnyMode": "configure_later",
    "backup": "configure_later",
}


def _contains_secret(value: object) -> bool:
    if isinstance(value, Mapping):
        return any(str(key).casefold() in SECRET_KEYS or _contains_secret(child) for key, child in value.items())
    if isinstance(value, list):
        return any(_contains_secret(item) for item in value)
    return False


class FirstRunState:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.completion_path = path.with_name("first-run-complete")
        self.value: dict[str, Any] = {"schemaVersion": 1, "currentStep": STEPS[0], "completed": False, "preferences": dict(DEFAULTS), "providerAliases": []}

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self.value
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schemaVersion") != 1 or payload.get("currentStep") not in STEPS or _contains_secret(payload):
            raise ValueError("invalid or secret-bearing first-run state")
        self.value = payload
        return self.value

    def update(self, *, step: str, values: Mapping[str, object]) -> None:
        if step not in STEPS:
            raise ValueError("unknown first-run step")
        if _contains_secret(values):
            raise ValueError("credentials may not be written to first-run state")
        if step == "search_locations":
            roots = values.get("searchLocations", [])
            if not isinstance(roots, list):
                raise ValueError("searchLocations must be a list")
            home = Path.home().resolve()
            for root in roots:
                candidate = Path(str(root)).resolve()
                if candidate == home or candidate == home.parent or candidate == Path(candidate.anchor):
                    raise ValueError("whole-home/root indexing is not allowed")
        self.value.setdefault("preferences", {}).update(values)
        self.value["currentStep"] = step

    def advance(self) -> str:
        current = STEPS.index(self.value["currentStep"])
        if current < len(STEPS) - 1:
            self.value["currentStep"] = STEPS[current + 1]
        else:
            self.value["completed"] = True
        return self.value["currentStep"]

    def finish(self) -> None:
        self.value["currentStep"] = "finish"
        self.value["completed"] = True
        self.save()
        descriptor = os.open(self.completion_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            os.write(descriptor, b"schemaVersion=1\ncompleted=true\n")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def save(self) -> None:
        if _contains_secret(self.value):
            raise ValueError("refusing to persist secrets")
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, temporary_name = tempfile.mkstemp(prefix=".first-run-", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(self.value, stream, sort_keys=True, separators=(",", ":"))
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary_name, 0o600)
            os.replace(temporary_name, self.path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)


def validate_username(value: str) -> bool:
    return bool(USERNAME.fullmatch(value)) and value not in {"root", "bin", "daemon", "nobody", "bunny"}


def validate_hostname(value: str) -> bool:
    return len(value) <= 63 and bool(HOSTNAME.fullmatch(value)) and not any(char.isupper() for char in value)
