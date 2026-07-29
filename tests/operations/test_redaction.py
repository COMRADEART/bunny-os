from __future__ import annotations

import unittest
from pathlib import Path

from operations.redaction import assert_no_forbidden_keys, redact, redact_text


ROOT = Path(__file__).resolve().parents[2]


class RedactionTests(unittest.TestCase):
    def test_common_personal_identifiers_are_removed(self) -> None:
        text = "mail me@example.org ip 192.168.1.9 mac AA:BB:CC:DD:EE:FF /home/alice/file"
        clean = redact_text(text)
        for secret in ("me@example.org", "192.168.1.9", "AA:BB:CC:DD:EE:FF", "/home/alice"):
            self.assertNotIn(secret, clean)

    def test_secret_keys_are_redacted(self) -> None:
        self.assertEqual(redact({"token": "abc", "nested": {"password": "def"}}), {"token": "[redacted]", "nested": {"password": "[redacted]"}})

    def test_user_content_is_excluded(self) -> None:
        self.assertEqual(redact({"prompt": "private request"})["prompt"], "[excluded-user-content]")

    def test_recovery_key_shape_is_removed(self) -> None:
        value = "AAAA-BBBB-CCCC-DDDD-EEEE-FFFF"
        self.assertNotIn(value, redact_text(value))

    def test_labelled_phone_hostname_wifi_and_api_key_are_removed(self) -> None:
        text = 'phone=+1 (555) 867-5309 hostname=alice-laptop ssid="Private Home" api_key=example-secret-value'
        clean = redact_text(text)
        for secret in ("867-5309", "alice-laptop", "Private Home", "example-secret-value"):
            self.assertNotIn(secret, clean)

    def test_forbidden_key_check_is_recursive(self) -> None:
        with self.assertRaises(ValueError):
            assert_no_forbidden_keys({"safe": [{"api_key": "secret"}]})

    def test_public_listener_is_not_configured(self) -> None:
        source = (ROOT / "systemd/bunny-system-broker.socket").read_text(encoding="utf-8")
        self.assertIn("ListenStream=/run/", source)
        self.assertNotIn("0.0.0.0", source)

    def test_update_timer_is_disabled_in_preset(self) -> None:
        source = (ROOT / "config/systemd/60-bunny-os.preset").read_text(encoding="utf-8")
        self.assertIn("disable bunny-update-agent.timer", source)

    def test_redaction_is_deterministic(self) -> None:
        value = {"email": "a@example.org", "message": "a@example.org"}
        self.assertEqual(redact(value), redact(value))


if __name__ == "__main__":
    unittest.main()
