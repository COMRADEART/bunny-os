# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The privileged half: a local socket that serves the installer protocol.

`InstallerService` has always had peer-UID authentication, a session token and a
nonce window, and nothing has ever called it over a socket —
``/usr/libexec/bunny-installer-backend`` printed "not available" and exited 78.
This is the server that was missing.

## Why there are two processes at all

§2 requires the setup surface to have no authority over storage. That is a claim
about privilege as much as about code structure: a surface that could partition a
disk has the authority whatever its source says. So the surface runs as the live
desktop user with no capability to write to a block device, and everything that
can is here, behind a socket, running as root.

The division is then enforced by the kernel rather than by intent. The strongest
statement this phase can make about §2 is that the process drawing the buttons
**cannot** erase a disk, and this file is why that is true.

## What the socket refuses

``SO_PEERCRED`` gives the connecting process's real UID, checked against the
single live-session UID the service was constructed with. A second user on the
machine — or a capsule, or anything else that found the path — is refused before
its request is parsed. On top of that every request carries the session token
issued at startup and a nonce that is remembered, so a captured request cannot be
replayed.

The socket lives in ``/run`` at 0600 owned by the live user, which means the
filesystem refuses most of this before the code has to.

## The one thing it will not do

Serve more than one installation. ``installer.install.start`` is accepted once;
after that the service has an adapter that has run and a state machine past its
write boundary, and a second start would be a second erase of a disk the first
one already reformatted. The refusal is in `InstallationState.start`, which only
accepts a transition from ``planned``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import struct
import sys
import threading
import traceback
from typing import Any, Callable, Mapping

from installer.backend.service import AuthenticationError, BackendUnavailable, InstallerService

__all__ = ["SOCKET_PATH", "ProtocolServer", "serve"]

SOCKET_PATH = Path("/run/bunny-installer/backend.sock")

#: A request larger than this is not a request. The protocol's biggest legitimate
#: payload is a storage plan, which is a few kilobytes.
_MAX_REQUEST = 256 * 1024


class ProtocolServer:
    """One socket, one live user, one installation."""

    def __init__(
        self,
        service: InstallerService,
        *,
        path: Path = SOCKET_PATH,
        live_uid: int | None = None,
        on_event: Callable[[str, Mapping[str, Any]], None] | None = None,
    ) -> None:
        self.service = service
        self.path = path
        self.live_uid = live_uid if live_uid is not None else service.live_uid
        self.on_event = on_event or (lambda name, detail: None)
        self._socket: socket.socket | None = None
        self._stop = threading.Event()

    # -- lifecycle -------------------------------------------------------

    def open(self) -> socket.socket:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        if self.path.exists():
            self.path.unlink()
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        # Bind with a restrictive umask rather than chmod afterwards: between
        # bind and chmod the socket is connectable, and the window is exactly
        # when a live session is starting and things are racing.
        previous = os.umask(0o177)
        try:
            server.bind(str(self.path))
        finally:
            os.umask(previous)
        try:
            os.chown(self.path, self.live_uid, -1)
        except (OSError, PermissionError):
            # Not fatal: SO_PEERCRED is the check that matters, and the file
            # mode already excludes everyone but the owner.
            pass
        server.listen(4)
        self._socket = server
        return server

    def close(self) -> None:
        self._stop.set()
        if self._socket is not None:
            try:
                self._socket.close()
            finally:
                self._socket = None
        try:
            self.path.unlink()
        except OSError:
            pass

    # -- one connection --------------------------------------------------

    @staticmethod
    def peer_uid(connection: socket.socket) -> int:
        raw = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED,
                                    struct.calcsize("3i"))
        _pid, uid, _gid = struct.unpack("3i", raw)
        return uid

    def handle(self, connection: socket.socket) -> None:
        uid = self.peer_uid(connection)
        if uid != self.live_uid:
            self.on_event("refused", {"reason": "peer-uid", "uid": uid})
            connection.sendall(self._error("this socket serves one session only") + b"\n")
            return

        buffered = b""
        received_fds: list[int] = []

        def discard_fds() -> None:
            for fd in received_fds:
                try:
                    os.close(fd)
                except OSError:
                    pass
            received_fds.clear()

        try:
            while not self._stop.is_set():
                # recv_fds rather than recv: the one thing the JSON protocol
                # refuses to carry — secret material — arrives as a sealed
                # memfd alongside the request that references it. A request
                # with no ancillary data behaves exactly as before.
                chunk, fds, _flags, _address = socket.recv_fds(connection, 65536, 4)
                received_fds.extend(fds)
                if len(received_fds) > 4:
                    connection.sendall(self._error("too many secret descriptors") + b"\n")
                    return
                if not chunk:
                    return
                buffered += chunk
                if len(buffered) > _MAX_REQUEST:
                    connection.sendall(self._error("request too large") + b"\n")
                    return
                while b"\n" in buffered:
                    line, buffered = buffered.split(b"\n", 1)
                    if not line.strip():
                        continue
                    connection.sendall(self._respond(line, uid, tuple(received_fds)) + b"\n")
                    # A descriptor accompanies exactly the request it arrived
                    # with; it does not linger for a later one.
                    discard_fds()
        finally:
            discard_fds()

    @staticmethod
    def _secret_values(fds: tuple[int, ...]) -> dict[str, str]:
        """The reference→material map delivered alongside a request."""
        values: dict[str, str] = {}
        for fd in fds:
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                raw = os.read(fd, 65536)
                parsed = json.loads(raw.decode("utf-8"))
            except (OSError, ValueError, UnicodeDecodeError):
                continue
            if isinstance(parsed, dict):
                for key, value in parsed.items():
                    if isinstance(key, str) and isinstance(value, str):
                        values[key] = value
        return values

    def _respond(self, line: bytes, uid: int, fds: tuple[int, ...] = ()) -> bytes:
        try:
            envelope = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return self._error("request is not JSON")
        if not isinstance(envelope, dict):
            return self._error("request must be an object")
        token = envelope.pop("sessionToken", "")
        try:
            result = self.service.handle(envelope, peer_uid=uid, session_token=str(token),
                                         secret_values=self._secret_values(fds))
        except AuthenticationError as error:
            self.on_event("refused", {"reason": str(error)})
            return self._error(str(error), kind="authentication")
        except BackendUnavailable as error:
            return self._error(str(error), kind="unavailable")
        except ValueError as error:
            return self._error(str(error), kind="invalid")
        except Exception as error:                       # pragma: no cover
            # The message is deliberately not the exception's: an unexpected
            # failure inside the installer should not become text on a screen
            # that a person is asked to act on.
            self.on_event("error", {"traceback": traceback.format_exc()})
            return self._error(f"the installer backend failed: {type(error).__name__}",
                               kind="internal")
        return json.dumps(result, sort_keys=True).encode("utf-8")

    @staticmethod
    def _error(message: str, *, kind: str = "invalid") -> bytes:
        return json.dumps({"schemaVersion": 1, "error": {"kind": kind, "message": message}},
                          sort_keys=True).encode("utf-8")

    def serve_forever(self) -> None:
        server = self._socket or self.open()
        self.on_event("listening", {"path": str(self.path), "liveUid": self.live_uid})
        while not self._stop.is_set():
            try:
                connection, _ = server.accept()
            except OSError:
                if self._stop.is_set():
                    return
                raise
            with connection:
                try:
                    self.handle(connection)
                except (ConnectionResetError, BrokenPipeError):
                    continue


def serve(*, live_uid: int, probe: Callable[[], list], adapter: object | None,
          path: Path = SOCKET_PATH, token_path: Path | None = None) -> int:
    """Run the backend until it is stopped.

    ``adapter`` is passed straight through to `InstallerService`, so the
    fail-closed gate is exactly as it was: without one, ``install.start`` raises
    `BackendUnavailable` and this server reports that as an error rather than
    installing anything.
    """
    service = InstallerService(live_uid=live_uid, probe=probe, production_adapter=adapter)
    server = ProtocolServer(service, path=path, live_uid=live_uid)

    def announce(name: str, detail: Mapping[str, Any]) -> None:
        sys.stderr.write(json.dumps({"event": name, **dict(detail)}, sort_keys=True) + "\n")
        sys.stderr.flush()

    server.on_event = announce

    token = service.issue_session_token(peer_uid=0)
    if token_path is not None:
        # 0400 and owned by the live user. Written before the socket is served,
        # so a session that finds the socket has already been able to find the
        # token — the reverse order gives a window in which the surface starts,
        # fails to authenticate, and shows a person an error that fixes itself.
        token_path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        descriptor = os.open(str(token_path),
                             os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o400)
        try:
            os.write(descriptor, token.encode("ascii"))
            os.fchown(descriptor, live_uid, -1)
        finally:
            os.close(descriptor)
    # The token goes to stdout once, for the unit to hand to the session. It is
    # not in the socket's greeting: a client that could read the token from the
    # socket it is authenticating to would make the token pointless.
    sys.stdout.write(json.dumps({
        "schemaVersion": 1,
        "socket": str(path),
        "sessionToken": token,
        "destructiveExecutionAvailable": adapter is not None,
    }, sort_keys=True) + "\n")
    sys.stdout.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.close()
    return 0
