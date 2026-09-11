# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Host tests for the installer peercred + session-token channel.

These tests prove what this Linux host can prove: socket mode, kernel
``SO_PEERCRED``, token-file permissions, and nonce/token refusals over a real
AF_UNIX socket. They are not guest E2E, not a second-user login session, and
not UEFI/LUKS/Secure Boot.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import stat
import struct
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

unix_only = unittest.skipUnless(
    hasattr(socket, "AF_UNIX") and hasattr(socket, "SO_PEERCRED"),
    "AF_UNIX/SO_PEERCRED are Linux checks; a skip is not a PASS",
)


@unix_only
class SocketModeTests(unittest.TestCase):
    def setUp(self) -> None:
        from installer.backend.server import ProtocolServer
        from installer.backend.service import InstallerService

        self.directory = tempfile.TemporaryDirectory(prefix="bunny-trust-sock-")
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "backend.sock"
        self.service = InstallerService(live_uid=os.getuid(), probe=lambda: [])
        self.server = ProtocolServer(self.service, path=self.path, live_uid=os.getuid())
        self.server.open()
        self.addCleanup(self.server.close)

    def test_the_endpoint_is_a_socket(self) -> None:
        self.assertTrue(stat.S_ISSOCK(self.path.lstat().st_mode))

    def test_the_socket_is_mode_0600(self) -> None:
        mode = stat.S_IMODE(self.path.lstat().st_mode)
        self.assertEqual(mode, 0o600, f"the socket is mode {oct(mode)}")


@unix_only
class PeerCredentialTests(unittest.TestCase):
    """``SO_PEERCRED`` is consulted, and it is the kernel that answers."""

    def test_the_credential_comes_from_the_kernel_and_names_this_process(self) -> None:
        from installer.backend.server import ProtocolServer

        left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        uid = ProtocolServer.peer_uid(left)
        raw = left.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        pid, kernel_uid, gid = struct.unpack("3i", raw)
        self.assertEqual(uid, os.getuid())
        self.assertEqual(uid, kernel_uid)
        self.assertEqual(gid, os.getgid())
        self.assertEqual(pid, os.getpid())

    def test_a_peer_whose_uid_is_not_the_live_user_is_refused(self) -> None:
        from installer.backend.server import ProtocolServer
        from installer.backend.service import InstallerService

        class Foreign:
            def __init__(self) -> None:
                self.sent = b""

            def getsockopt(self, _level: int, _option: int, _length: int) -> bytes:
                foreign = os.getuid() + 1
                return struct.pack("3i", 4242, foreign, foreign)

            def sendall(self, data: bytes) -> None:
                self.sent += data

        events: list[tuple[str, dict]] = []
        service = InstallerService(live_uid=os.getuid(), probe=lambda: [])
        server = ProtocolServer(service, live_uid=os.getuid(),
                                on_event=lambda name, detail: events.append((name, dict(detail))))
        peer = Foreign()
        server.handle(peer)  # type: ignore[arg-type]
        self.assertIn(b"this socket serves one session only", peer.sent)
        self.assertEqual(events[0][0], "refused")
        self.assertEqual(events[0][1]["reason"], "peer-uid")

    def test_a_peer_whose_credential_cannot_be_read_is_refused(self) -> None:
        from installer.backend.server import ProtocolServer
        from installer.backend.service import InstallerService

        class Unreadable:
            def __init__(self) -> None:
                self.sent = b""

            def getsockopt(self, _level: int, _option: int, _length: int) -> bytes:
                raise OSError("the credential is not available")

            def sendall(self, data: bytes) -> None:
                self.sent += data

        events: list[tuple[str, dict]] = []
        service = InstallerService(live_uid=os.getuid(), probe=lambda: [])
        server = ProtocolServer(service, live_uid=os.getuid(),
                                on_event=lambda name, detail: events.append((name, dict(detail))))
        peer = Unreadable()
        server.handle(peer)  # type: ignore[arg-type]
        self.assertIn(b"this socket serves one session only", peer.sent)
        self.assertEqual(events[0][1]["reason"], "peer-cred")

    def test_invalid_kernel_credentials_are_refused(self) -> None:
        from installer.backend.server import PeerCredentialError, ProtocolServer

        class ZeroPid:
            def getsockopt(self, _level: int, _option: int, _length: int) -> bytes:
                return struct.pack("3i", 0, os.getuid(), os.getgid())

        with self.assertRaises(PeerCredentialError):
            ProtocolServer.peer_uid(ZeroPid())  # type: ignore[arg-type]

    def test_missing_so_peercred_is_refused_not_admitted(self) -> None:
        from installer.backend.server import PeerCredentialError, ProtocolServer

        left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        bare = types.ModuleType("socket")
        bare.SOL_SOCKET = socket.SOL_SOCKET
        with patch("installer.backend.server.socket", bare):
            with self.assertRaises(PeerCredentialError) as raised:
                ProtocolServer.peer_uid(left)
        self.assertIn("unavailable", str(raised.exception))


@unix_only
class SessionTokenFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory(prefix="bunny-trust-token-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def test_the_token_file_is_mode_0400(self) -> None:
        from installer.backend.server import write_session_token

        path = self.root / "session-token"
        write_session_token(path, "token-value-not-a-secret-fixture", os.getuid())
        self.assertEqual(stat.S_IMODE(path.lstat().st_mode), 0o400)
        self.assertEqual(path.read_text(encoding="utf-8"), "token-value-not-a-secret-fixture")

    def test_a_leftover_world_readable_file_is_replaced_at_0400(self) -> None:
        from installer.backend.server import write_session_token

        path = self.root / "session-token"
        path.write_text("stale", encoding="utf-8")
        path.chmod(0o644)
        write_session_token(path, "replacement-token-value", os.getuid())
        self.assertEqual(stat.S_IMODE(path.lstat().st_mode), 0o400)
        self.assertEqual(path.read_text(encoding="utf-8"), "replacement-token-value")

    def test_a_symlink_at_the_token_path_does_not_receive_the_token(self) -> None:
        from installer.backend.server import write_session_token

        target = self.root / "elsewhere"
        target.write_text("untouched", encoding="utf-8")
        link = self.root / "session-token"
        link.symlink_to(target)
        write_session_token(link, "live-session-token", os.getuid())
        self.assertFalse(link.is_symlink())
        self.assertEqual(stat.S_IMODE(link.lstat().st_mode), 0o400)
        self.assertEqual(link.read_text(encoding="utf-8"), "live-session-token")
        self.assertEqual(target.read_text(encoding="utf-8"), "untouched")

    def test_the_stdout_greeting_does_not_carry_the_session_token(self) -> None:
        from installer.backend.server import listening_greeting

        greeting = listening_greeting(
            path=Path("/run/bunny-installer/backend.sock"),
            token_path=Path("/run/bunny-installer/session-token"),
            destructive=False,
        )
        self.assertNotIn("sessionToken", greeting)
        self.assertNotIn("token-should-never-appear", json.dumps(greeting))
        self.assertEqual(greeting["sessionTokenPath"], "/run/bunny-installer/session-token")


@unix_only
class WireAuthenticationTests(unittest.TestCase):
    """Token, empty token, and nonce replay over a real socket."""

    def setUp(self) -> None:
        from installer.backend.server import ProtocolServer
        from installer.backend.service import InstallerService
        from installer.frontend.client import BackendClient

        self.directory = tempfile.TemporaryDirectory(prefix="bunny-trust-wire-")
        self.addCleanup(self.directory.cleanup)
        self.events: list[tuple[str, dict]] = []
        self.service = InstallerService(live_uid=os.getuid(), probe=lambda: [])
        self.token = self.service.issue_session_token(peer_uid=0)
        self.socket_path = Path(self.directory.name) / "backend.sock"
        self.server = ProtocolServer(
            self.service, path=self.socket_path, live_uid=os.getuid(),
            on_event=lambda name, detail: self.events.append((name, dict(detail))),
        )
        self.server.open()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.close)
        self.BackendClient = BackendClient

    def _client(self, token: str):
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.settimeout(10)
        connection.connect(str(self.socket_path))
        session = self.BackendClient(connection, token)
        self.addCleanup(session.close)
        return session

    def test_the_live_token_is_accepted(self) -> None:
        result = self._client(self.token).initialize()
        self.assertEqual(result["protocolVersion"], 1)
        self.assertFalse(result["destructiveExecutionAvailable"])

    def test_a_wrong_token_is_refused(self) -> None:
        from installer.frontend.client import InstallerRefused

        with self.assertRaises(InstallerRefused) as refused:
            self._client("not-the-session-token").initialize()
        self.assertEqual(refused.exception.kind, "authentication")

    def test_an_empty_token_is_refused(self) -> None:
        from installer.frontend.client import InstallerRefused

        with self.assertRaises(InstallerRefused) as refused:
            self._client("").initialize()
        self.assertEqual(refused.exception.kind, "authentication")

    def test_a_replayed_nonce_is_refused(self) -> None:
        session = self._client(self.token)
        replay = {
            "schemaVersion": 1,
            "requestId": "req-replay-host01",
            "installationId": session.installation_id,
            "operation": "installer.initialize",
            "nonce": "nonce-replayed-host0001",
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "params": {},
            "sessionToken": self.token,
        }
        raw = json.dumps(replay).encode("utf-8") + b"\n"
        session._connection.sendall(raw)
        first = session._connection.recv(65536)
        self.assertNotIn(b'"error"', first.split(b"\n", 1)[0])
        session._connection.sendall(raw)
        second = json.loads(session._connection.recv(65536).decode("utf-8").split("\n", 1)[0])
        self.assertEqual(second["error"]["kind"], "authentication")
        self.assertIn("replayed", second["error"]["message"])

    def test_refused_events_do_not_echo_the_session_token(self) -> None:
        from installer.frontend.client import InstallerRefused

        with self.assertRaises(InstallerRefused):
            self._client("not-the-session-token").initialize()
        dumped = json.dumps(self.events)
        self.assertNotIn(self.token, dumped)


class UnitFileTests(unittest.TestCase):
    def _directives(self, name: str) -> list[str]:
        values: list[str] = []
        text = (ROOT / "systemd/bunny-installer-backend.service").read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or "=" not in stripped:
                continue
            key, _, value = stripped.partition("=")
            if key.strip() == name:
                values.extend(value.split())
        return values

    def test_the_backend_unit_does_not_journal_stdout(self) -> None:
        self.assertEqual(self._directives("StandardOutput"), ["null"])
        self.assertEqual(self._directives("StandardError"), ["journal"])
        self.assertNotIn("journal", self._directives("StandardOutput"))

    def test_the_backend_unit_keeps_unix_only_and_restrictive_umask(self) -> None:
        text = (ROOT / "systemd/bunny-installer-backend.service").read_text(encoding="utf-8")
        self.assertIn("RestrictAddressFamilies=AF_UNIX", text)
        self.assertIn("UMask=0077", text)
        self.assertIn("User=root", text)


if __name__ == "__main__":
    unittest.main()
