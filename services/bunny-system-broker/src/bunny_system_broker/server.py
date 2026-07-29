"""Socket-activated Bunny OS broker server."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import logging
import os
from pathlib import Path
import signal
import socket
import threading
import time
from typing import Any

from . import BROKER_VERSION, MAX_REQUEST_BYTES, MAX_RESPONSE_BYTES
from .auth import AuthenticationError, PeerIdentity, authorize_polkit, peer_identity, require_local_user
from .backend import BackendError, execute
from .limits import NonceCache, RateLimiter
from .protocol import ProtocolError, error_response, success_response, validate_request


LOG = logging.getLogger("bunny-system-broker")


class CancellationRegistry:
    def __init__(self) -> None:
        self._values: dict[tuple[int, str], threading.Event] = {}
        self._lock = threading.Lock()

    def register(self, uid: int, request_id: str) -> threading.Event:
        event = threading.Event()
        with self._lock:
            self._values[(uid, request_id)] = event
        return event

    def cancel(self, uid: int, request_id: str) -> bool:
        with self._lock:
            event = self._values.get((uid, request_id))
        if event is None:
            return False
        event.set()
        return True

    def remove(self, uid: int, request_id: str) -> None:
        with self._lock:
            self._values.pop((uid, request_id), None)


class BrokerServer:
    def __init__(self, listener: socket.socket) -> None:
        self.listener = listener
        self.rate = RateLimiter()
        self.nonces = NonceCache()
        self.cancellations = CancellationRegistry()
        self.executor = ThreadPoolExecutor(max_workers=16, thread_name_prefix="broker")
        self.stopping = threading.Event()

    def serve(self) -> None:
        self.listener.settimeout(1.0)
        while not self.stopping.is_set():
            try:
                connection, _ = self.listener.accept()
            except TimeoutError:
                continue
            except OSError:
                if self.stopping.is_set():
                    break
                raise
            self.executor.submit(self.handle, connection)

    def stop(self) -> None:
        self.stopping.set()
        try:
            self.listener.close()
        except OSError:
            pass
        self.executor.shutdown(wait=True, cancel_futures=True)

    @staticmethod
    def _read(connection: socket.socket) -> Any:
        connection.settimeout(5)
        chunks = bytearray()
        while len(chunks) <= MAX_REQUEST_BYTES:
            part = connection.recv(min(8192, MAX_REQUEST_BYTES + 1 - len(chunks)))
            if not part:
                break
            chunks.extend(part)
            if b"\n" in part:
                break
        if len(chunks) > MAX_REQUEST_BYTES:
            raise ProtocolError("request_too_large", "request exceeds 64 KiB")
        line, separator, remainder = bytes(chunks).partition(b"\n")
        if not separator or remainder.strip():
            raise ProtocolError("invalid_request", "exactly one newline-delimited request is required")
        try:
            return json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProtocolError("invalid_json", "request is not valid UTF-8 JSON") from exc

    @staticmethod
    def _send(connection: socket.socket, response: dict[str, Any]) -> None:
        encoded = json.dumps(response, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
        if len(encoded) > MAX_RESPONSE_BYTES:
            encoded = json.dumps(error_response(response.get("id"), "response_too_large", "response exceeds 1 MiB"), separators=(",", ":")).encode("utf-8") + b"\n"
        connection.sendall(encoded)

    def handle(self, connection: socket.socket) -> None:
        started = time.monotonic()
        peer: PeerIdentity | None = None
        request_id: str | None = None
        method = "unparsed"
        outcome = "error"
        cancel: threading.Event | None = None
        try:
            peer = peer_identity(connection)
            require_local_user(peer)
            payload = self._read(connection)
            request_id = payload.get("id") if isinstance(payload, dict) and isinstance(payload.get("id"), str) else None
            request = validate_request(payload)
            request_id = request.request_id
            method = request.method
            if not self.nonces.accept(peer.uid, request.nonce):
                raise ProtocolError("replayed_request", "nonce has already been used")
            if not self.rate.allow(peer.uid, request.spec.mutating):
                raise ProtocolError("rate_limited", "caller exceeded the operation rate limit")
            if method == "request.cancel":
                result = {"cancelled": self.cancellations.cancel(peer.uid, request.params["requestId"])}
            else:
                if request.spec.polkit_action and not authorize_polkit(peer, request.spec.polkit_action):
                    raise AuthenticationError("operation authorization was denied")
                cancel = self.cancellations.register(peer.uid, request.request_id)
                result = execute(method, request.params, peer, request.request_id, cancel)
            self._send(connection, success_response(request.request_id, result))
            outcome = "ok"
        except ProtocolError as exc:
            self._send(connection, error_response(request_id, exc.code, exc.message))
            outcome = exc.code
        except AuthenticationError:
            self._send(connection, error_response(request_id, "unauthorized", "caller is not authorized"))
            outcome = "unauthorized"
        except BackendError as exc:
            self._send(connection, error_response(request_id, exc.code, exc.message))
            outcome = exc.code
        except (OSError, TimeoutError):
            try:
                self._send(connection, error_response(request_id, "io_error", "local broker I/O failed"))
            except OSError:
                pass
            outcome = "io_error"
        except Exception:
            LOG.exception("unhandled broker failure")
            try:
                self._send(connection, error_response(request_id, "internal_error", "broker operation failed"))
            except OSError:
                pass
            outcome = "internal_error"
        finally:
            if peer is not None and request_id is not None and cancel is not None:
                self.cancellations.remove(peer.uid, request_id)
            try:
                connection.close()
            except OSError:
                pass
            LOG.info(
                json.dumps(
                    {
                        "event": "broker.request",
                        "version": BROKER_VERSION,
                        "uid": peer.uid if peer else None,
                        "pid": peer.pid if peer else None,
                        "requestId": request_id,
                        "method": method,
                        "outcome": outcome,
                        "latencyMs": round((time.monotonic() - started) * 1000),
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )


def _listener(path: str) -> socket.socket:
    inherited = int(os.environ.get("LISTEN_FDS", "0"))
    inherited_pid = int(os.environ.get("LISTEN_PID", "0"))
    if inherited == 1 and inherited_pid == os.getpid():
        listener = socket.fromfd(3, socket.AF_UNIX, socket.SOCK_STREAM)
        os.close(3)
        return listener
    if inherited:
        raise RuntimeError("exactly one systemd socket is required")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    try:
        target.unlink()
    except FileNotFoundError:
        pass
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(target))
    os.chmod(target, 0o666)
    listener.listen(32)
    return listener


def main() -> int:
    parser = argparse.ArgumentParser(prog="bunny-system-broker")
    parser.add_argument("--socket", default="/run/bunny/broker.sock")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    server = BrokerServer(_listener(args.socket))

    def stop(_signum: int, _frame: Any) -> None:
        server.stopping.set()
        try:
            server.listener.close()
        except OSError:
            pass

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        server.serve()
    finally:
        server.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

