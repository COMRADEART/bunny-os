from __future__ import annotations

import unittest

from bunny_shell.core_state import validate_snapshot


def snapshot() -> dict:
    return {"schemaVersion": 1, "sequence": 1, "tasks": [], "plans": [], "approvals": [], "notifications": [], "provider": None, "privacy": {}, "sandbox": {}}


class ApprovalTests(unittest.TestCase):
    def test_scoped_approval_projection(self) -> None:
        value = snapshot()
        value["approvals"] = [{"id": "a1", "action": "Write file", "capability": "workspace.write", "scope": "/project/a", "risk": "medium", "expiresAt": "2026-07-29T00:00:00Z"}]
        self.assertEqual(validate_snapshot(value)["approvals"][0]["scope"], "/project/a")

    def test_unbounded_approval_is_forbidden(self) -> None:
        value = snapshot()
        value["approvals"] = [{"id": "a1", "action": "Root", "capability": "all", "scope": "*", "risk": "high", "expiresAt": "never", "alwaysAllowEverything": True}]
        with self.assertRaises(ValueError):
            validate_snapshot(value)


if __name__ == "__main__":
    unittest.main()
