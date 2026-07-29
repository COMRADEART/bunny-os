from __future__ import annotations

from datetime import datetime, timezone
import unittest

from operations.dashboard import FIELDS, render_markdown
from operations.maintenance import evaluate_alerts


class MaintenanceTests(unittest.TestCase):
    def test_broken_mirror_alert_cannot_publish(self) -> None:
        alerts = evaluate_alerts([{"kind": "mirror", "id": "primary", "status": "broken"}])
        self.assertEqual(alerts[0]["action"], "alert-only")

    def test_expiring_key_alert(self) -> None:
        now = datetime(2026, 7, 29, tzinfo=timezone.utc)
        alerts = evaluate_alerts([{"kind": "signing-key", "id": "release", "status": "active", "expiresAt": "2026-08-01T00:00:00Z"}], now)
        self.assertEqual(alerts[0]["reason"], "expires-within-30-days")

    def test_unknown_automation_kind_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            evaluate_alerts([{"kind": "publish-release", "status": "ready"}])

    def test_dashboard_has_no_percentage_score(self) -> None:
        values = {field: "UNKNOWN" for field in FIELDS}
        rendered = render_markdown(values)
        self.assertNotIn("%", rendered)

    def test_dashboard_rejects_missing_field(self) -> None:
        with self.assertRaises(ValueError):
            render_markdown({})


if __name__ == "__main__":
    unittest.main()
