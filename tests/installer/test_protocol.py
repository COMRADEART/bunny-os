from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from installer.protocol import ProtocolError, parse_request


def request(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schemaVersion": 1,
        "requestId": "request-12345678",
        "installationId": "install-12345678",
        "operation": "installer.initialize",
        "nonce": "abcdefghijklmnop",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "params": {},
    }
    value.update(changes)
    return value


class ProtocolTests(unittest.TestCase):
    def test_parses_allowlisted_operation(self) -> None:
        self.assertEqual(parse_request(request()).operation, "installer.initialize")

    def test_rejects_generic_command(self) -> None:
        with self.assertRaises(ProtocolError):
            parse_request(request(operation="installer.command.execute"))

    def test_rejects_secret_fields_at_any_depth(self) -> None:
        with self.assertRaises(ProtocolError):
            parse_request(request(params={"plan": {"password": "do-not-store"}}))

    def test_rejects_extra_fields(self) -> None:
        with self.assertRaises(ProtocolError):
            parse_request(request(command="rm -rf /"))

    def test_rejects_stale_request(self) -> None:
        stale = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        with self.assertRaises(ProtocolError):
            parse_request(request(timestamp=stale))

