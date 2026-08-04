# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Private, bounded JSON-lines contract between runtime and restartable UIs."""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import socketserver
import stat
import struct
import threading
from typing import Any, Mapping
from uuid import uuid4

from . import PROTOCOL_SCHEMA_VERSION
from .approval import (
    ApprovalError,
    ApprovalExpired,
    ApprovalReplay,
    ApprovalResolution,
    ApprovalScopeMismatch,
    SupersededPlan,
)
from .model import PrivacyClass, safe_identifier
from .runtime import CompanionRuntime

MAX_REQUEST_BYTES = 64 * 1024
MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class ProtocolError(ValueError):
    code = "invalid_request"


def default_runtime_directory() -> Path:
    configured = os.environ.get("XDG_RUNTIME_DIR")
    if configured:
        return Path(configured) / "bunny-companion"
    configured_state = os.environ.get("XDG_STATE_HOME")
    base = Path(configured_state).expanduser() if configured_state else Path.home() / ".local/state"
    return base / "bunny-companion/runtime"


def default_socket_path() -> Path:
    return default_runtime_directory() / "runtime.sock"


class CompanionProtocol:
    def __init__(self, runtime: CompanionRuntime, *, transport_token: str | None = None) -> None:
        self.runtime = runtime
        self.transport_token = transport_token

    @staticmethod
    def _params(document: Mapping[str, Any]) -> Mapping[str, Any]:
        value = document.get("params", {})
        if not isinstance(value, Mapping):
            raise ProtocolError("params must be an object")
        return value

    def dispatch(self, document: Mapping[str, Any]) -> dict[str, Any]:
        if document.get("schemaVersion") != PROTOCOL_SCHEMA_VERSION:
            raise ProtocolError("unsupported protocol schemaVersion")
        if self.transport_token is not None and document.get("transportToken") != self.transport_token:
            raise PermissionError("companion loopback transport token is invalid")
        request_id = str(document.get("requestId", ""))
        safe_identifier(request_id, "protocol request id")
        command = str(document.get("command", ""))
        params = self._params(document)
        if command == "health":
            result: Any = self.runtime.health()
        elif command == "submit":
            privacy = PrivacyClass(str(params.get("privacyClassification", "internal")))
            result = self.runtime.submit(
                str(params.get("userRequest", "")),
                session_id=str(params["sessionId"]) if params.get("sessionId") else None,
                privacy_classification=privacy,
            ).to_json()
        elif command == "snapshot":
            result = self.runtime.snapshot(
                str(params.get("taskId", "")),
                after_sequence=int(params.get("afterSequence", 0)),
            ).to_json()
        elif command == "tasks":
            result = {
                "tasks": list(self.runtime.tasks(
                    session_id=str(params["sessionId"]) if params.get("sessionId") else None
                ))
            }
        elif command == "resolve_approval":
            task_id = str(params.get("taskId", ""))
            resolution = ApprovalResolution(
                request_id=str(params.get("requestId", "")),
                decision=str(params.get("decision", "")),
                plan_id=str(params.get("planId", "")),
                transition_id=str(params.get("transitionId", "")),
                destination=str(params.get("destination", "")),
                provider_destination=str(params["providerDestination"])
                if params.get("providerDestination") else None,
                actor="user",
            )
            result = self.runtime.resolve_approval(task_id, resolution).to_json()
        elif command == "cancel":
            result = self.runtime.cancel(str(params.get("taskId", ""))).to_json()
        else:
            raise ProtocolError(f"unknown companion command: {command!r}")
        return {
            "schemaVersion": PROTOCOL_SCHEMA_VERSION,
            "requestId": request_id,
            "ok": True,
            "result": result,
        }

    @staticmethod
    def error_response(request_id: str, exc: BaseException) -> dict[str, Any]:
        if isinstance(exc, ApprovalExpired):
            code = "approval_expired"
        elif isinstance(exc, ApprovalReplay):
            code = "approval_replay"
        elif isinstance(exc, ApprovalScopeMismatch):
            code = "approval_scope_mismatch"
        elif isinstance(exc, SupersededPlan):
            code = "superseded_plan"
        elif isinstance(exc, ApprovalError):
            code = "approval_error"
        elif isinstance(exc, KeyError):
            code = "not_found"
        elif isinstance(exc, PermissionError):
            code = "permission_denied"
        elif isinstance(exc, (ProtocolError, TypeError, ValueError)):
            code = "invalid_request"
        else:
            code = "runtime_error"
        message = str(exc).strip("'\"")[:512] or type(exc).__name__
        return {
            "schemaVersion": PROTOCOL_SCHEMA_VERSION,
            "requestId": request_id if request_id else "request-invalid",
            "ok": False,
            "error": {"code": code, "message": message},
        }


class _RequestHandler(socketserver.StreamRequestHandler):
    def _same_user(self) -> bool:
        if os.name != "posix" or not hasattr(socket, "SO_PEERCRED"):
            return True
        credentials = self.request.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        _pid, uid, _gid = struct.unpack("3i", credentials)
        return uid == os.getuid()

    def handle(self) -> None:
        request_id = "request-invalid"
        try:
            if not self._same_user():
                raise PermissionError("companion socket peer is not the session user")
            payload = self.rfile.readline(MAX_REQUEST_BYTES + 1)
            if len(payload) > MAX_REQUEST_BYTES:
                raise ProtocolError("companion request is oversized")
            if not payload or not payload.endswith(b"\n"):
                raise ProtocolError("companion request must be one newline-terminated JSON object")
            document = json.loads(payload.decode("utf-8"))
            if not isinstance(document, Mapping):
                raise ProtocolError("companion request must be an object")
            request_id = str(document.get("requestId", request_id))
            response = self.server.protocol.dispatch(document)  # type: ignore[attr-defined]
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            response = self.server.protocol.error_response(request_id, ProtocolError("request is not valid UTF-8 JSON"))  # type: ignore[attr-defined]
        except BaseException as exc:
            response = self.server.protocol.error_response(request_id, exc)  # type: ignore[attr-defined]
        encoded = json.dumps(response, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n"
        if len(encoded) > MAX_RESPONSE_BYTES:
            encoded = json.dumps(
                self.server.protocol.error_response(request_id, ProtocolError("response is too large; reconnect with afterSequence pagination")),  # type: ignore[attr-defined]
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8") + b"\n"
        self.wfile.write(encoded)


if hasattr(socket, "AF_UNIX"):
    class _UnixStreamServer(socketserver.TCPServer):
        """socketserver may omit UnixStreamServer even when AF_UNIX exists."""

        address_family = socket.AF_UNIX
        socket_type = socket.SOCK_STREAM


    class _ThreadingUnixServer(socketserver.ThreadingMixIn, _UnixStreamServer):
        daemon_threads = True
        block_on_close = True

        def __init__(self, path: str, protocol: CompanionProtocol) -> None:
            self.protocol = protocol
            super().__init__(path, _RequestHandler)
else:
    _ThreadingUnixServer = None  # type: ignore[misc,assignment]


class _ThreadingLoopbackServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    block_on_close = True
    allow_reuse_address = False

    def __init__(self, protocol: CompanionProtocol) -> None:
        self.protocol = protocol
        super().__init__(("127.0.0.1", 0), _RequestHandler)


class CompanionServer:
    def __init__(self, runtime: CompanionRuntime, socket_path: Path | None = None) -> None:
        self.runtime = runtime
        self.socket_path = Path(socket_path or default_socket_path())
        self._use_unix = hasattr(socket, "AF_UNIX")
        self._transport_token: str | None = None
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.socket_path.parent.chmod(0o700)
        except OSError:
            pass
        self._prepare_socket_path()
        if self._use_unix:
            assert _ThreadingUnixServer is not None
            self._server = _ThreadingUnixServer(str(self.socket_path), CompanionProtocol(runtime))
        else:
            self._transport_token = uuid4().hex
            self._server = _ThreadingLoopbackServer(
                CompanionProtocol(runtime, transport_token=self._transport_token)
            )
            endpoint = {
                "schemaVersion": PROTOCOL_SCHEMA_VERSION,
                "transport": "loopback-tcp",
                "host": "127.0.0.1",
                "port": int(self._server.server_address[1]),
                "token": self._transport_token,
            }
            temporary = self.socket_path.with_suffix(self.socket_path.suffix + ".new")
            temporary.write_text(json.dumps(endpoint, sort_keys=True) + "\n", encoding="utf-8")
            temporary.replace(self.socket_path)
        try:
            self.socket_path.chmod(0o600)
        except OSError:
            pass
        self._thread: threading.Thread | None = None

    def _prepare_socket_path(self) -> None:
        if not self.socket_path.exists():
            return
        if self.socket_path.is_symlink():
            raise PermissionError("refusing a symlinked companion socket")
        status = self.socket_path.stat()
        if not self._use_unix:
            try:
                endpoint = json.loads(self.socket_path.read_text(encoding="utf-8"))
                host = endpoint["host"]
                port = int(endpoint["port"])
            except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
                raise PermissionError("refusing to replace an invalid companion endpoint file")
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                probe.settimeout(0.2)
                probe.connect((host, port))
            except OSError:
                self.socket_path.unlink()
            else:
                raise RuntimeError("another Bunny companion runtime is already listening")
            finally:
                probe.close()
            return
        if os.name == "posix" and not stat.S_ISSOCK(status.st_mode):
            raise PermissionError("refusing to replace a non-socket companion runtime path")
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            probe.settimeout(0.2)
            probe.connect(str(self.socket_path))
        except OSError:
            self.socket_path.unlink()
        else:
            raise RuntimeError("another Bunny companion runtime is already listening")
        finally:
            probe.close()

    def serve_forever(self) -> None:
        self._server.serve_forever(poll_interval=0.2)

    def start_thread(self) -> threading.Thread:
        if self._thread is not None:
            raise RuntimeError("companion server thread is already started")
        self._thread = threading.Thread(target=self.serve_forever, name="bunny-companion-runtime", daemon=True)
        self._thread.start()
        return self._thread

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        try:
            self.socket_path.unlink()
        except FileNotFoundError:
            pass

    def __enter__(self) -> "CompanionServer":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


class CompanionClientError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class CompanionClient:
    def __init__(self, socket_path: Path | None = None, *, timeout: float = 30.0) -> None:
        self.socket_path = Path(socket_path or default_socket_path())
        self.timeout = timeout

    def call(self, command: str, params: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        request_id = f"request-{uuid4()}"
        transport_token: str | None = None
        if hasattr(socket, "AF_UNIX"):
            address: Any = str(self.socket_path)
            family = socket.AF_UNIX
        else:
            try:
                endpoint = json.loads(self.socket_path.read_text(encoding="utf-8"))
                if endpoint.get("transport") != "loopback-tcp" or endpoint.get("host") != "127.0.0.1":
                    raise ValueError("endpoint is not private loopback")
                address = ("127.0.0.1", int(endpoint["port"]))
                transport_token = str(endpoint["token"])
            except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise CompanionClientError("runtime_unavailable", "companion endpoint is unavailable") from exc
            family = socket.AF_INET
        request = {
            "schemaVersion": PROTOCOL_SCHEMA_VERSION,
            "requestId": request_id,
            "command": command,
            "params": dict(params or {}),
        }
        if transport_token is not None:
            request["transportToken"] = transport_token
        encoded = json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n"
        if len(encoded) > MAX_REQUEST_BYTES:
            raise ValueError("companion request is oversized")
        connection = socket.socket(family, socket.SOCK_STREAM)
        connection.settimeout(self.timeout)
        try:
            connection.connect(address)
            connection.sendall(encoded)
            chunks: list[bytes] = []
            size = 0
            while True:
                chunk = connection.recv(min(65536, MAX_RESPONSE_BYTES + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES:
                    raise CompanionClientError("oversized_response", "companion response exceeded its bound")
                if chunk.endswith(b"\n"):
                    break
        finally:
            connection.close()
        response = json.loads(b"".join(chunks).decode("utf-8"))
        if not isinstance(response, Mapping) or response.get("requestId") != request_id:
            raise CompanionClientError("invalid_response", "companion response does not match the request")
        if not response.get("ok"):
            error = response.get("error") if isinstance(response.get("error"), Mapping) else {}
            raise CompanionClientError(str(error.get("code", "runtime_error")), str(error.get("message", "runtime error")))
        result = response.get("result")
        if not isinstance(result, Mapping):
            raise CompanionClientError("invalid_response", "companion result must be an object")
        return result

    def health(self) -> Mapping[str, Any]:
        return self.call("health")

    def submit(self, user_request: str, *, session_id: str | None = None) -> Mapping[str, Any]:
        params: dict[str, Any] = {"userRequest": user_request}
        if session_id:
            params["sessionId"] = session_id
        return self.call("submit", params)

    def snapshot(self, task_id: str, *, after_sequence: int = 0) -> Mapping[str, Any]:
        return self.call("snapshot", {"taskId": task_id, "afterSequence": after_sequence})

    def resolve_approval(self, task_id: str, approval: Mapping[str, Any], decision: str) -> Mapping[str, Any]:
        return self.call("resolve_approval", {
            "taskId": task_id,
            "requestId": approval.get("requestId"),
            "decision": decision,
            "planId": approval.get("planId"),
            "transitionId": approval.get("transitionId"),
            "destination": approval.get("destination"),
            "providerDestination": approval.get("providerDestination"),
        })

    def cancel(self, task_id: str) -> Mapping[str, Any]:
        return self.call("cancel", {"taskId": task_id})
