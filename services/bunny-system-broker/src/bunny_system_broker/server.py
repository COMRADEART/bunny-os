# SPDX-License-Identifier: GPL-3.0-or-later
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
from .auth import (
    AuthenticationError,
    PeerIdentity,
    authorize_polkit,
    peer_identity,
    require_local_user,
    require_policy_identity,
)
from .backend import BackendError, execute
from . import policy_backend
from .limits import NonceCache, RateLimiter
from .protocol import (
    METHODS,
    POLICY_METHODS,
    MethodSpec,
    ProtocolError,
    error_response,
    success_response,
    validate_request,
)
from typing import Callable


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
    """One socket, one method table, one authentication rule.

    The user socket and the policy socket are two instances rather than one
    instance with a mode flag. Each therefore has its own ``RateLimiter`` and
    ``NonceCache``, so neither identity can exhaust the other's budget, and a
    mistake in one table cannot widen the other.
    """

    def __init__(
        self,
        listener: socket.socket,
        *,
        methods: dict[str, MethodSpec] | None = None,
        authenticate: Callable[[PeerIdentity], None] = require_local_user,
        execute_operation: Callable[..., Any] = execute,
        name: str = "broker",
    ) -> None:
        self.listener = listener
        self.methods = METHODS if methods is None else methods
        self.authenticate = authenticate
        self.execute_operation = execute_operation
        self.name = name
        self.rate = RateLimiter()
        self.nonces = NonceCache()
        self.cancellations = CancellationRegistry()
        self.executor = ThreadPoolExecutor(max_workers=16, thread_name_prefix=name)
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
            self.authenticate(peer)
            payload = self._read(connection)
            request_id = payload.get("id") if isinstance(payload, dict) and isinstance(payload.get("id"), str) else None
            request = validate_request(payload, methods=self.methods)
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
                result = self.execute_operation(method, request.params, peer, request.request_id, cancel)
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
                        "event": f"{self.name}.request",
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


USER_SOCKET_NAME = "broker.sock"
POLICY_SOCKET_NAME = "policy.sock"


def _bind(path: str, mode: int) -> socket.socket:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    try:
        target.unlink()
    except FileNotFoundError:
        pass
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(target))
    os.chmod(target, mode)
    listener.listen(32)
    return listener


def _inherited_listeners() -> dict[str, socket.socket]:
    """Adopt systemd-passed sockets, keyed by ``LISTEN_FDNAMES``.

    Accepts one or two descriptors. With two, the names disambiguate which is
    the user socket and which is the policy socket; guessing by descriptor
    order would silently swap their authentication rules if the unit files
    ever changed, so an unnamed pair is refused.
    """
    count = int(os.environ.get("LISTEN_FDS", "0"))
    listen_pid = int(os.environ.get("LISTEN_PID", "0"))
    if not count or listen_pid != os.getpid():
        return {}
    if count > 2:
        raise RuntimeError("at most two systemd sockets are supported")
    names = [name for name in os.environ.get("LISTEN_FDNAMES", "").split(":") if name]
    if count == 1 and not names:
        names = [USER_SOCKET_NAME]
    if len(names) != count:
        raise RuntimeError("LISTEN_FDNAMES must name every inherited socket")

    # Only the exact name "policy.sock" selects the policy socket. Every other
    # name is the user socket, including the unit name systemd assigns by
    # default when FileDescriptorName= is unset — "bunny-system-broker.socket".
    #
    # Rejecting unfamiliar names looked safer and was not: it broke the broker
    # under real socket activation, which unit tests using our own names could
    # not see. Defaulting to the user socket is the fail-closed direction,
    # because that socket applies require_local_user and would refuse the
    # policy agent's system identity outright.
    resolved: list[str] = [
        POLICY_SOCKET_NAME if name == POLICY_SOCKET_NAME else USER_SOCKET_NAME for name in names
    ]
    if len(set(resolved)) != len(resolved):
        raise RuntimeError(
            "two inherited sockets resolved to the same role; set FileDescriptorName= "
            "to broker.sock and policy.sock so they can be told apart"
        )
    listeners: dict[str, socket.socket] = {}
    for offset, name in enumerate(resolved):
        listeners[name] = socket.fromfd(3 + offset, socket.AF_UNIX, socket.SOCK_STREAM)
    for offset in range(count):
        os.close(3 + offset)
    return listeners


def _policy_service_uid(name: str) -> int:
    import pwd

    try:
        return pwd.getpwnam(name).pw_uid
    except KeyError as exc:
        raise RuntimeError(
            f"policy socket requested but the {name!r} service account does not exist"
        ) from exc


def main() -> int:
    parser = argparse.ArgumentParser(prog="bunny-system-broker")
    parser.add_argument("--socket", default="/run/bunny/broker.sock")
    parser.add_argument(
        "--policy-socket",
        default=None,
        help="enable the policy socket for the device policy agent (off unless requested)",
    )
    parser.add_argument("--policy-user", default="bunny-policy")
    parser.add_argument("--policy-unit", default="bunny-policy-agent.service")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    inherited = _inherited_listeners()
    servers: list[BrokerServer] = []

    user_listener = inherited.get(USER_SOCKET_NAME) or _bind(args.socket, 0o666)
    servers.append(BrokerServer(user_listener, name="broker"))

    policy_listener = inherited.get(POLICY_SOCKET_NAME)
    if policy_listener is None and args.policy_socket:
        # 0600 root-only: the policy socket is not for interactive users, and
        # filesystem permissions are the first of two independent barriers.
        policy_listener = _bind(args.policy_socket, 0o600)
    if policy_listener is not None:
        expected_uid = _policy_service_uid(args.policy_user)
        servers.append(
            BrokerServer(
                policy_listener,
                methods=POLICY_METHODS,
                authenticate=lambda peer: require_policy_identity(
                    peer, expected_uid=expected_uid, expected_unit=args.policy_unit
                ),
                execute_operation=policy_backend.execute,
                name="policy",
            )
        )

    def stop(_signum: int, _frame: Any) -> None:
        for item in servers:
            item.stopping.set()
            try:
                item.listener.close()
            except OSError:
                pass

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    threads = [threading.Thread(target=item.serve, name=item.name, daemon=True) for item in servers[1:]]
    for thread in threads:
        thread.start()
    try:
        servers[0].serve()
    finally:
        for item in servers:
            item.stop()
        for thread in threads:
            thread.join(timeout=5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

