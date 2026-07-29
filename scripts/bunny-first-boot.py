#!/usr/bin/python3
"""Small offline post-account preference flow for the developer image."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess


def yes_no(prompt: str, default: bool = False) -> bool:
    suffix = " [Y/n] " if default else " [y/N] "
    try:
        answer = input(prompt + suffix).strip().lower()
    except EOFError:
        return default
    if not answer:
        return default
    return answer in {"y", "yes"}


def main() -> int:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    destination = config_home / "bunny-os" / "first-boot-complete.json"
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    print("Bunny OS first-boot preferences")
    print("GNOME Initial Setup manages language, keyboard, time, network, hostname, and the Linux account.")
    print("No cloud account, model download, telemetry, or payment is required.")
    launch_bunny = yes_no("Launch Bunny Desktop when you sign in?")
    try:
        update_available = json.loads(Path("/etc/bunny-os/update.json").read_text(encoding="utf-8")).get("enabled") is True
    except (OSError, json.JSONDecodeError):
        update_available = False
    check_updates = yes_no("Check the signed Bunny OS update channel periodically?") if update_available else False
    if not update_available:
        print("A signed OS update channel is not configured in this image; periodic checks remain off.")
    update_preference_applied = not check_updates
    if check_updates:
        result = subprocess.run(["/usr/bin/bunny-os", "--json", "update", "preference", "enable"], stdin=subprocess.DEVNULL, check=False)
        update_preference_applied = result.returncode == 0
    preferences = {
        "schemaVersion": 1,
        "privacy": {
            "telemetry": False,
            "remoteDiagnostics": False,
            "cloudFallback": False,
            "screenCapture": False,
        },
        "checkForOsUpdates": check_updates,
        "updatePreferenceApplied": update_preference_applied,
        "launchBunnyAtLogin": launch_bunny,
        "localModelSetup": "deferred",
        "recoveryGuidanceAcknowledged": yes_no("Have you stored your disk-encryption recovery key safely?"),
        "completedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    destination.write_text(json.dumps(preferences, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(destination, 0o600)
    if launch_bunny:
        subprocess.run(["/usr/bin/systemctl", "--user", "enable", "bunny-desktop.service"], stdin=subprocess.DEVNULL, check=False)
    print(f"Saved local preferences to {destination}")
    print("Enable autostart later with: systemctl --user enable bunny-desktop.service")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
