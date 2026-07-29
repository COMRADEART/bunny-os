from __future__ import annotations

import unittest

from bunny_shell.core_state import notifications_for_lock_screen


class NotificationTests(unittest.TestCase):
    def test_sensitive_content_is_hidden_on_lock_screen(self) -> None:
        value = {"schemaVersion": 1, "sequence": 1, "tasks": [], "plans": [], "approvals": [], "notifications": [{"source": "Bunny", "title": "Prompt text", "body": "secret", "sensitive": True}], "provider": None, "privacy": {}, "sandbox": {}}
        item = notifications_for_lock_screen(value)[0]
        self.assertEqual(item["title"], "Sensitive notification")
        self.assertEqual(item["body"], "")
        self.assertEqual(item["actions"], [])


if __name__ == "__main__":
    unittest.main()
