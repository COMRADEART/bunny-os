"""Bounded state and decision adapters for Bunny Desktop Visual V2."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any


MAX_STATE_BYTES = 1024 * 1024
REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
DECISION_ADAPTER = Path("/usr/bin/bunny-approval-decision")
APPROVED_POSES = {
    "idle-neutral", "welcome-wave", "typing", "pointing-at-interface", "thinking",
    "explaining", "requesting-approval", "task-running", "task-completed", "warning",
    "error", "offline", "privacy-mode", "celebrating",
}


def mock_mode() -> bool:
    return os.environ.get("BUNNY_VISUAL_MOCK_MODE") == "1"


def _source_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _mock_path() -> Path:
    source = _source_root() / "shell/bunny-desktop-v2/mock-state.json"
    return source if source.is_file() else Path("/usr/share/bunny-visual-v2/mock-state.json")


def _state_path() -> Path:
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", "/run/user/invalid"))
    return runtime / "bunny-shell/core-summary-v2.json"


def _read_json(path: Path, *, allow_mock: bool = False) -> dict[str, Any] | None:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_STATE_BYTES:
        return None
    stat = path.stat()
    if os.name == "posix" and not allow_mock and (stat.st_uid != os.getuid() or stat.st_mode & 0o077):
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else None


def normalize(value: dict[str, Any] | None, *, is_mock: bool = False) -> dict[str, Any]:
    source = value or {}
    arrays = ("privacyUses", "approvals", "notifications", "recentActions", "systemContext", "suggestions")
    state = {name: source.get(name, []) if isinstance(source.get(name), list) else [] for name in arrays}
    state.update({
        "assistantState": str(source.get("assistantState", "Ready")),
        "providerState": str(source.get("providerState", "Unavailable")),
        "privacyState": str(source.get("privacyState", "Local Only")),
        "networkState": str(source.get("networkState", "Unavailable")),
        "updates": str(source.get("updates", "Unavailable")),
        "bunnyEnabled": source.get("bunnyEnabled", True) is not False,
        "resultConfirmed": source.get("resultConfirmed") is True,
        "milestoneConfirmed": source.get("milestoneConfirmed") is True,
        "mockMode": is_mock,
        "decisionAvailable": False if is_mock else source.get("decisionAvailable") is True,
    })
    return state


def load_state() -> dict[str, Any]:
    try:
        path = _mock_path() if mock_mode() else _state_path()
        return normalize(_read_json(path, allow_mock=mock_mode()), is_mock=mock_mode())
    except (OSError, ValueError, json.JSONDecodeError):
        return normalize(None, is_mock=mock_mode())


def decision_available() -> bool:
    return not mock_mode() and DECISION_ADAPTER.is_file() and os.access(DECISION_ADAPTER, os.X_OK)


def submit_decision(request_id: str, decision: str) -> None:
    if not decision_available():
        raise RuntimeError("Bunny approval decision adapter is unavailable")
    if not REQUEST_ID.fullmatch(request_id) or decision not in {"approve", "deny"}:
        raise ValueError("invalid approval decision")
    subprocess.run(
        [str(DECISION_ADAPTER), "--request-id", request_id, "--decision", decision],
        check=True,
        stdin=subprocess.DEVNULL,
        timeout=10,
    )


def save_welcome_preferences(preferences: dict[str, Any]) -> Path:
    allowed = {
        "language": str(preferences.get("language", "system"))[:32],
        "keyboard": str(preferences.get("keyboard", "system"))[:32],
        "appearance": str(preferences.get("appearance", "system"))[:16],
        "visualMode": str(preferences.get("visualMode", "regular"))[:16],
        "bunnyEnabled": bool(preferences.get("bunnyEnabled", False)),
        "localOnly": bool(preferences.get("localOnly", True)),
        "provider": str(preferences.get("provider", "none"))[:32],
        "highContrast": bool(preferences.get("highContrast", False)),
        "largeText": bool(preferences.get("largeText", False)),
        "reducedMotion": bool(preferences.get("reducedMotion", False)),
        "telemetry": False,
    }
    if allowed["visualMode"] not in {"regular", "character"}:
        raise ValueError("invalid visual mode")
    if allowed["provider"] not in {"none", "local", "cloud-optional"}:
        raise ValueError("invalid provider preference")
    config_root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    destination = config_root / "bunny/visual-v2-welcome.json"
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".visual-v2-welcome-", dir=destination.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(allowed, stream, indent=2, sort_keys=True)
            stream.write("\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return destination


def character_asset(pose: str) -> Path:
    if pose not in APPROVED_POSES:
        raise ValueError("unapproved Bunny guide pose")
    source = _source_root() / f"visual-v2/assets/character/bunny-guide/v1/{pose}.png"
    installed = Path(f"/usr/share/bunny-visual-v2/character/bunny-guide/v1/{pose}.png")
    path = source if source.is_file() else installed
    if not path.is_file():
        raise FileNotFoundError(f"Bunny guide asset unavailable: {pose}")
    return path


def diagnostic_facts(state: dict[str, Any]) -> list[dict[str, str]]:
    facts = [
        {"fact": "Assistant state", "severity": "information", "impact": "Features may be limited" if state["assistantState"] in {"Offline", "Failed"} else "No observed impact", "action": "Review Assistant state", "evidence": state["assistantState"]},
        {"fact": "Provider state", "severity": "information", "impact": "Provider features may be unavailable" if state["providerState"] == "Unavailable" else "No observed impact", "action": "Review provider settings", "evidence": state["providerState"]},
    ]
    try:
        usage = shutil.disk_usage("/")
        free = round(usage.free / usage.total * 100)
        facts.append({"fact": "System storage", "severity": "warning" if free < 10 else "information", "impact": "Low space can prevent updates" if free < 10 else "No observed impact", "action": "Review storage" if free < 10 else "None", "evidence": f"Observed free space: {free}%"})
    except OSError:
        facts.append({"fact": "System storage", "severity": "information", "impact": "Impact unavailable", "action": "Inspect storage", "evidence": "Storage observation unavailable"})
    return facts
