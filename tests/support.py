from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import secrets
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services/bunny-system-broker/src"))
sys.path.insert(0, str(ROOT / "services/bunny-update-agent"))
sys.path.insert(0, str(ROOT / "tools/bunny-os"))
sys.path.insert(0, str(ROOT / "shell/services"))


def request(method: str = "system.status.read", params: dict | None = None) -> dict:
    return {
        "contractVersion": "1.0.0",
        "id": "test-request-1",
        "method": method,
        "params": params or {},
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "nonce": secrets.token_urlsafe(24),
    }
