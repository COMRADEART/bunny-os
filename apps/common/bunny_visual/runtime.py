"""Read-only, privacy-aware adapter for Bunny Visual V1 surfaces."""

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


def mock_mode() -> bool:
    return os.environ.get("BUNNY_VISUAL_MOCK_MODE") == "1"


def _mock_path() -> Path:
    source = Path(__file__).resolve().parents[3] / "shell/bunny-shell-extension/mock-state.json"
    return source if source.is_file() else Path("/usr/share/bunny-visual-v1/mock-state.json")


def _state_path() -> Path:
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", "/run/user/invalid"))
    return runtime / "bunny-shell" / "core-summary.json"


def _read_private_json(path: Path, *, allow_mock: bool = False) -> dict[str, Any] | None:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_STATE_BYTES:
        return None
    stat = path.stat()
    if os.name == "posix" and not allow_mock and (stat.st_uid != os.getuid() or stat.st_mode & 0o077):
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else None


def normalize(value: dict[str, Any] | None, *, is_mock: bool = False) -> dict[str, Any]:
    source = value or {}
    approvals = []
    for item in source.get("approvals", []) if isinstance(source.get("approvals"), list) else []:
        if not isinstance(item, dict):
            continue
        approvals.append({
            "id": str(item.get("id", "unavailable")),
            "component": str(item.get("component", item.get("capability", "Not reported"))),
            "operation": str(item.get("operation", item.get("action", "Not reported"))),
            "resources": item.get("resources", item.get("scope", "Not reported")),
            "privilege": str(item.get("privilege", item.get("capability", "Not reported"))),
            "networkImpact": str(item.get("networkImpact", "Not reported")),
            "dataImpact": str(item.get("dataImpact", "Not reported")),
            "reversibility": str(item.get("reversibility", "Not reported")),
            "reason": str(item.get("reason", "Not reported")),
            "expiration": str(item.get("expiration", item.get("expiresAt", "Not reported"))),
            "severity": str(item.get("severity", item.get("risk", "standard"))),
        })
    arrays = ("tasks", "conversation", "plan", "recentFiles", "toolActivity", "results", "notifications")
    normalized = {name: source.get(name, []) if isinstance(source.get(name), list) else [] for name in arrays}
    normalized.update({
        "bunny": str(source.get("bunny", "unavailable")),
        "provider": str(source.get("provider", "unavailable")),
        "privacy": source.get("privacy", {}) if isinstance(source.get("privacy"), dict) else {},
        "approvals": approvals,
        "mockMode": is_mock,
    })
    return normalized


def load_state() -> dict[str, Any]:
    try:
        if mock_mode():
            return normalize(_read_private_json(_mock_path(), allow_mock=True), is_mock=True)
        return normalize(_read_private_json(_state_path()))
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


def diagnostic_facts(state: dict[str, Any]) -> list[dict[str, str]]:
    facts = [
        {"fact": "Bunny service projection", "severity": "information", "impact": "Assistant features may be unavailable" if state["bunny"] != "available" else "No observed impact", "action": "Open service logs" if state["bunny"] != "available" else "None", "evidence": f"Observed state: {state['bunny']}"},
        {"fact": "Provider projection", "severity": "information", "impact": "Cloud or local assistance may be unavailable" if state["provider"] in {"unavailable", "offline"} else "No observed impact", "action": "Review Providers settings", "evidence": f"Observed state: {state['provider']}"},
    ]
    try:
        usage = shutil.disk_usage("/")
        free_percent = round(usage.free / usage.total * 100)
        facts.append({"fact": "System storage", "severity": "warning" if free_percent < 10 else "information", "impact": "Low space can prevent updates" if free_percent < 10 else "No observed impact", "action": "Review storage" if free_percent < 10 else "None", "evidence": f"Observed free space: {free_percent}%"})
    except OSError:
        facts.append({"fact": "System storage", "severity": "information", "impact": "Impact unknown", "action": "Inspect system storage", "evidence": "Storage observation unavailable"})
    return facts


def save_welcome_preferences(preferences: dict[str, Any]) -> Path:
    """Persist non-secret onboarding choices without enabling any service."""
    allowed = {
        "language": str(preferences.get("language", "system"))[:32],
        "appearance": str(preferences.get("appearance", "system"))[:16],
        "bunnyEnabled": bool(preferences.get("bunnyEnabled", False)),
        "localOnly": bool(preferences.get("localOnly", True)),
        "provider": str(preferences.get("provider", "none"))[:32],
        "highContrast": bool(preferences.get("highContrast", False)),
        "largeText": bool(preferences.get("largeText", False)),
        "reducedMotion": bool(preferences.get("reducedMotion", False)),
        "telemetry": False,
    }
    if allowed["provider"] not in {"none", "local", "cloud-optional"}:
        raise ValueError("invalid provider preference")
    config_root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    destination = config_root / "bunny" / "visual-v1-welcome.json"
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".visual-v1-welcome-", dir=destination.parent)
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
