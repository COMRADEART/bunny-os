from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging
import os
import socket
import threading
import unittest
from unittest import mock

from tests.support import request
from bunny_system_broker.auth import AuthenticationError, PeerIdentity, require_local_user
from bunny_system_broker import backend
from bunny_system_broker.limits import NonceCache, RateLimiter
from bunny_system_broker.protocol import ProtocolError, validate_request
from bunny_system_broker.server import BrokerServer


class ProtocolTests(unittest.TestCase):
    def test_authenticated_well_formed_request(self) -> None:
        value = validate_request(request())
        self.assertEqual(value.method, "system.status.read")

    def test_invalid_method(self) -> None:
        with self.assertRaisesRegex(ProtocolError, "not allowed"):
            validate_request(request("root.shell"))

    def test_malformed_arguments(self) -> None:
        with self.assertRaises(ProtocolError):
            validate_request(request("logs.export", {"sinceMinutes": "all"}))

    def test_command_injection_attempt_is_not_a_service(self) -> None:
        with self.assertRaises(ProtocolError):
            validate_request(request("service.status.read", {"service": "gdm.service;id"}))

    def test_stale_request(self) -> None:
        value = request()
        value["timestamp"] = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
        with self.assertRaisesRegex(ProtocolError, "30 second"):
            validate_request(value)

    def test_unknown_field_rejected(self) -> None:
        value = request()
        value["command"] = "id"
        with self.assertRaises(ProtocolError):
            validate_request(value)

    def test_update_preference_requires_boolean(self) -> None:
        self.assertTrue(validate_request(request("update.preference.set", {"enabled": True})).params["enabled"])
        with self.assertRaises(ProtocolError):
            validate_request(request("update.preference.set", {"enabled": "yes"}))

    def test_system_identity_is_unauthenticated_for_user_api(self) -> None:
        with self.assertRaises(AuthenticationError):
            require_local_user(PeerIdentity(55, 999, 999, 1))

    @unittest.skipUnless(os.name == "posix", "process-group timeout semantics require Linux/POSIX")
    def test_backend_timeout(self) -> None:
        with self.assertRaisesRegex(backend.BackendError, "timeout"):
            backend._run(["/usr/bin/python3", "-c", "import time; time.sleep(5)"], 1, threading.Event())


class LimitTests(unittest.TestCase):
    def test_nonce_replay(self) -> None:
        cache = NonceCache()
        self.assertTrue(cache.accept(1000, "a" * 24))
        self.assertFalse(cache.accept(1000, "a" * 24))

    def test_rate_limiting(self) -> None:
        limiter = RateLimiter(read_per_minute=2, mutate_per_minute=1)
        self.assertTrue(limiter.allow(1000, False, now=1))
        self.assertTrue(limiter.allow(1000, False, now=2))
        self.assertFalse(limiter.allow(1000, False, now=3))
        self.assertTrue(limiter.allow(1000, True, now=3))
        self.assertFalse(limiter.allow(1000, True, now=4))


class ServerTests(unittest.TestCase):
    def server(self) -> BrokerServer:
        return BrokerServer(socket.socket(socket.AF_INET, socket.SOCK_STREAM))

    def test_audit_record_contains_metadata_not_params(self) -> None:
        server = self.server()
        client, broker = socket.socketpair()
        payload = request()
        client.sendall(json.dumps(payload).encode() + b"\n")
        peer = PeerIdentity(1234, 1000, 1000, 5)
        with mock.patch("bunny_system_broker.server.peer_identity", return_value=peer), mock.patch("bunny_system_broker.server.execute", return_value={"ok": True}), self.assertLogs("bunny-system-broker", logging.INFO) as logs:
            server.handle(broker)
        response = json.loads(client.recv(65536))
        self.assertTrue(response["ok"])
        self.assertIn('"method":"system.status.read"', logs.output[0])
        self.assertNotIn("params", logs.output[0])
        client.close()
        server.listener.close()
        server.executor.shutdown(wait=True)

    def test_unauthorized_mutation(self) -> None:
        server = self.server()
        client, broker = socket.socketpair()
        client.sendall(json.dumps(request("power.reboot")).encode() + b"\n")
        peer = PeerIdentity(1234, 1000, 1000, 5)
        with mock.patch("bunny_system_broker.server.peer_identity", return_value=peer), mock.patch("bunny_system_broker.server.authorize_polkit", return_value=False):
            server.handle(broker)
        response = json.loads(client.recv(65536))
        self.assertEqual(response["error"]["code"], "unauthorized")
        client.close()
        server.listener.close()
        server.executor.shutdown(wait=True)


if __name__ == "__main__":
    unittest.main()
