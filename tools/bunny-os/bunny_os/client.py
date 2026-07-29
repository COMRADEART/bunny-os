"""One-request-per-connection client for the local broker socket."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import secrets
import socket
import uuid
from typing import Any

from . import CONTRACT_VERSION


_TIMEOUTS = {"update.stage": 5200.0, "update.install": 150.0, "logs.export": 150.0}


class BrokerClientError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def request(method: str, params: dict[str, Any] | None = None, socket_path: str = "/run/bunny/broker.sock", timeout: float | None = None) -> Any:
    request_id = str(uuid.uuid4())
    envelope = {
        "contractVersion": CONTRACT_VERSION,
        "id": request_id,
        "method": method,
        "params": params or {},
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "nonce": secrets.token_urlsafe(24),
    }
    payload = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.settimeout(_TIMEOUTS.get(method, 130.0) if timeout is None else timeout)
    try:
        connection.connect(socket_path)
        connection.sendall(payload)
        chunks = bytearray()
        while len(chunks) <= 1024 * 1024:
            part = connection.recv(8192)
            if not part:
                break
            chunks.extend(part)
            if b"\n" in part:
                break
    except (TimeoutError, KeyboardInterrupt) as exc:
        if method != "request.cancel":
            try:
                request("request.cancel", {"requestId": request_id}, socket_path, 5.0)
            except (BrokerClientError, KeyboardInterrupt):
                pass
        if isinstance(exc, KeyboardInterrupt):
            raise
        raise BrokerClientError("broker_timeout", "local Bunny OS broker operation timed out and cancellation was requested") from exc
    except OSError as exc:
        raise BrokerClientError("broker_unavailable", "local Bunny OS broker is unavailable") from exc
    finally:
        connection.close()
    if len(chunks) > 1024 * 1024:
        raise BrokerClientError("response_too_large", "broker response exceeded 1 MiB")
    line, separator, remainder = bytes(chunks).partition(b"\n")
    if not separator or remainder.strip():
        raise BrokerClientError("invalid_response", "broker returned an incomplete or multiple response")
    try:
        response = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, IndexError) as exc:
        raise BrokerClientError("invalid_response", "broker returned a malformed response") from exc
    if not isinstance(response, dict) or response.get("contractVersion") != CONTRACT_VERSION or response.get("id") != request_id:
        raise BrokerClientError("invalid_response", "broker response identity is invalid")
    if response.get("ok") is not True:
        error = response.get("error") if isinstance(response.get("error"), dict) else {}
        raise BrokerClientError(str(error.get("code", "broker_error")), str(error.get("message", "broker request failed")))
    return response.get("result")
