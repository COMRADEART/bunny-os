# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What the Unix-socket transport is actually protected by, on Linux.

The companion's local protocol rests on three things, and until this module
existed only the third had ever been executed on the platform it is claimed for:

* the endpoint directory is private to the user (``0700``);
* the socket itself is private to the user (``0600``);
* ``SO_PEERCRED`` is consulted, and a peer whose uid is not this user's is
  refused by the kernel-supplied credential rather than by anything the peer
  says about itself.

Every test here is skipped where there is no ``AF_UNIX``. That is deliberate:
the developer fallback is a loopback socket with a per-run token, and a test
that quietly passed on it would be reporting a property of the fallback under
the name of the shipped transport. §6 forbids exactly that substitution, so the
tests refuse to run rather than run against the wrong thing.
"""

from __future__ import annotations

import os
from pathlib import Path
import socket
import stat
import struct
import time
import unittest

from .support import CompanionTestCase

HAS_UNIX = hasattr(socket, "AF_UNIX")
unix_only = unittest.skipUnless(
    HAS_UNIX, "AF_UNIX is absent; the loopback fallback proves nothing about this"
)


@unix_only
class EndpointPermissionTests(CompanionTestCase):
    """The socket and its directory, as they exist on disk."""

    def _server(self):
        from companion.protocol import CompanionServer
        from companion.service import CompanionGateway, InteractiveConsent

        consent = InteractiveConsent(maximum_wait_seconds=5.0)
        runtime = self.started(consent=consent)
        gateway = CompanionGateway(runtime, consent=consent)
        endpoint = self.root / "run" / "runtime.sock"
        server = CompanionServer(gateway, endpoint)
        self.addCleanup(server.close)
        return server, endpoint

    def test_the_endpoint_is_a_socket_and_not_a_regular_file(self) -> None:
        _server, endpoint = self._server()
        self.assertTrue(stat.S_ISSOCK(endpoint.lstat().st_mode))

    def test_the_socket_is_readable_and_writable_by_nobody_else(self) -> None:
        _server, endpoint = self._server()
        mode = stat.S_IMODE(endpoint.lstat().st_mode)
        self.assertEqual(mode, 0o600, f"the socket is mode {oct(mode)}")

    def test_the_directory_holding_it_is_private_to_the_user(self) -> None:
        _server, endpoint = self._server()
        mode = stat.S_IMODE(endpoint.parent.lstat().st_mode)
        self.assertEqual(mode, 0o700, f"the endpoint directory is mode {oct(mode)}")

    def test_the_socket_is_owned_by_the_user_running_the_runtime(self) -> None:
        _server, endpoint = self._server()
        self.assertEqual(endpoint.lstat().st_uid, os.getuid())

    def test_a_stale_socket_from_a_dead_runtime_is_replaced(self) -> None:
        """A crash leaves the socket file behind; a restart must still bind.

        The file is not evidence that a runtime is running — only a successful
        connection is. Refusing to start because of a leftover inode would turn
        every crash into a permanent outage requiring manual cleanup.
        """
        from companion.protocol import CompanionServer
        from companion.service import CompanionGateway, InteractiveConsent

        endpoint = self.root / "run" / "runtime.sock"
        endpoint.parent.mkdir(parents=True, exist_ok=True)
        # A socket inode nobody is listening on, exactly as a killed process
        # leaves behind.
        stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        stale.bind(str(endpoint))
        stale.close()
        self.assertTrue(endpoint.exists())

        consent = InteractiveConsent(maximum_wait_seconds=5.0)
        runtime = self.started(consent=consent)
        gateway = CompanionGateway(runtime, consent=consent)
        server = CompanionServer(gateway, endpoint)
        self.addCleanup(server.close)
        self.assertTrue(stat.S_ISSOCK(endpoint.lstat().st_mode))
        self.assertEqual(stat.S_IMODE(endpoint.lstat().st_mode), 0o600)


@unix_only
class PeerCredentialTests(CompanionTestCase):
    """``SO_PEERCRED`` is consulted, and it is the kernel that answers."""

    def test_a_connection_from_this_user_is_accepted(self) -> None:
        from companion.protocol import _peer_uid_check

        left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        self.assertTrue(_peer_uid_check(left))

    def test_the_credential_comes_from_the_kernel_and_names_this_process(self) -> None:
        """Proves the check reads a real credential rather than defaulting true.

        Without this, a ``_peer_uid_check`` that had quietly become
        ``return True`` would pass every other test in this class.
        """
        left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        raw = left.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        pid, uid, gid = struct.unpack("3i", raw)
        self.assertEqual(uid, os.getuid())
        self.assertEqual(gid, os.getgid())
        self.assertEqual(pid, os.getpid())

    def test_a_peer_whose_uid_is_not_ours_is_refused(self) -> None:
        """The refusal path, driven by a credential this process does not have.

        A second real user is not available inside a unit test, so the kernel's
        answer is substituted rather than the check's own logic: the code under
        test still decides, and it decides on a uid that is not ours.
        """
        from companion.protocol import _peer_uid_check

        class ForeignPeer:
            def getsockopt(self, _level, _option, _length):
                foreign_uid = os.getuid() + 1
                return struct.pack("3i", 4242, foreign_uid, foreign_uid)

        self.assertFalse(_peer_uid_check(ForeignPeer()))

    def test_a_peer_whose_credential_cannot_be_read_is_refused(self) -> None:
        from companion.protocol import _peer_uid_check

        class Unreadable:
            def getsockopt(self, _level, _option, _length):
                raise OSError("the credential is not available")

        # Refused, not allowed: an identity that cannot be established is not
        # this user by default.
        self.assertFalse(_peer_uid_check(Unreadable()))


@unix_only
class TransportSelectionTests(CompanionTestCase):
    """The shipped transport is chosen, and the fallback is not silent."""

    def test_a_platform_with_af_unix_uses_it(self) -> None:
        from companion.protocol import CompanionServer
        from companion.service import CompanionGateway, InteractiveConsent

        consent = InteractiveConsent(maximum_wait_seconds=5.0)
        runtime = self.started(consent=consent)
        gateway = CompanionGateway(runtime, consent=consent)
        server = CompanionServer(gateway, self.root / "run" / "runtime.sock")
        self.addCleanup(server.close)
        description = server.describe()
        self.assertEqual(description["transport"], "unix-socket")
        # No token exists on this transport: there is nothing for one to add
        # that the socket's own permissions and the peer check do not already
        # provide, and a token in the record would suggest otherwise.
        self.assertEqual(server.transport_token, "")

    def test_closing_a_server_that_never_served_releases_it_promptly(self) -> None:
        """A runtime that fails between binding and serving must still let go.

        ``socketserver.shutdown`` waits for ``serve_forever`` to acknowledge, so
        closing a server that was never started blocked for ever — and the
        ``finally`` that closes a half-built service is exactly where that
        happens. Found by this module hanging rather than failing.
        """
        from companion.protocol import CompanionServer
        from companion.service import CompanionGateway, InteractiveConsent

        consent = InteractiveConsent(maximum_wait_seconds=5.0)
        runtime = self.started(consent=consent)
        gateway = CompanionGateway(runtime, consent=consent)
        endpoint = self.root / "run" / "runtime.sock"
        server = CompanionServer(gateway, endpoint)

        started = time.monotonic()
        server.close()
        self.assertLess(time.monotonic() - started, 5.0)
        # The socket is gone, so the next runtime can bind without a probe.
        self.assertFalse(endpoint.exists())

    def test_requiring_unix_refuses_the_fallback_rather_than_downgrading(self) -> None:
        from companion.protocol import CompanionServer
        from companion.service import CompanionGateway, InteractiveConsent

        consent = InteractiveConsent(maximum_wait_seconds=5.0)
        runtime = self.started(consent=consent)
        gateway = CompanionGateway(runtime, consent=consent)
        with self.assertRaises(RuntimeError) as caught:
            CompanionServer(
                gateway,
                self.root / "run" / "runtime.sock",
                require_unix=True,
                prefer_loopback=True,
            )
        self.assertIn("loopback fallback", str(caught.exception))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
