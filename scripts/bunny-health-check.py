#!/usr/bin/python3
"""Offline boot-success checks; cloud connectivity is never a requirement."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import socket
import tempfile
import uuid


STATUS = Path("/var/lib/bunny-os/health/status.json")


def writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix=".health-", dir=path)
        os.close(descriptor)
        os.unlink(name)
        return True
    except OSError:
        return False


def socket_ready(path: str) -> bool:
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(2)
    try:
        client.connect(path)
        request_id = str(uuid.uuid4())
        payload = {
            "contractVersion": "1.0.0",
            "id": request_id,
            "method": "system.status.read",
            "params": {},
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "nonce": secrets.token_urlsafe(24),
        }
        client.sendall(json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n")
        chunks = bytearray()
        while len(chunks) <= 1024 * 1024 and b"\n" not in chunks:
            part = client.recv(8192)
            if not part:
                break
            chunks.extend(part)
        line, separator, remainder = bytes(chunks).partition(b"\n")
        if not separator or remainder.strip() or len(chunks) > 1024 * 1024:
            return False
        response = json.loads(line)
        return response.get("contractVersion") == "1.0.0" and response.get("id") == request_id and response.get("ok") is True
    except (OSError, json.JSONDecodeError):
        return False
    finally:
        client.close()


def main() -> int:
    checks = {
        "rootDeployment": Path("/run/ostree-booted").exists(),
        "brokerSocket": socket_ready("/run/bunny/broker.sock"),
        "networkStack": Path("/sys/class/net/lo").is_dir(),
        "systemStateWritable": writable(Path("/var/lib/bunny-os/health")),
        "bunnyStateBoundaryWritable": writable(Path("/var/lib/bunny")),
        "userHomesPresent": Path("/home").is_dir(),
    }
    advisory = {
        "networkManagerStatePresent": Path("/run/NetworkManager").is_dir(),
        "graphicsDevicePresent": Path("/dev/dri").is_dir(),
        "bunnyArtifactVerified": False,
    }
    try:
        artifact = json.loads(Path("/usr/share/bunny-os/bunny-artifact.json").read_text(encoding="utf-8"))
        advisory["bunnyArtifactVerified"] = artifact.get("status") == "verified"
    except (OSError, json.JSONDecodeError):
        pass
    healthy = all(checks.values())
    value = {
        "schemaVersion": 1,
        "healthy": healthy,
        "checkedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "required": checks,
        "advisory": advisory,
        "cloudRequired": False,
    }
    STATUS.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    STATUS.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(STATUS, 0o600)
    print(json.dumps(value, sort_keys=True))
    return 0 if healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())
