from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import unittest

from installer.backend.audit import redact
from installer.backend.service import AuthenticationError, BackendUnavailable, InstallerService
from installer.storage.models import parse_lsblk
from installer.storage.safety import confirmation_phrase


FIXTURE = json.loads((Path(__file__).parent / "fixtures/storage-fixtures.json").read_text(encoding="utf-8"))["fixtures"]["empty_gpt"]


def message(operation: str, nonce: str, params: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "requestId": "request-12345678",
        "installationId": "install-12345678",
        "operation": operation,
        "nonce": nonce,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "params": params or {},
    }


def plan(disk) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "installationId": "install-12345678",
        "mode": "erase_disk",
        "targetDisk": {"id": disk.id, "devicePath": disk.devicePath, "expectedSizeBytes": disk.sizeBytes},
        "partitions": [
            {"action": "create", "role": "efi", "sizeBytes": 1024**3},
            {"action": "create", "role": "boot", "sizeBytes": 2 * 1024**3},
            {"action": "create", "role": "system", "sizeBytes": 50 * 1024**3},
        ],
        "encryption": {"enabled": False, "type": "none", "recoveryKeyRequired": False},
        "boot": {"firmware": "uefi", "bootloader": "fedora-shim-grub", "preserveExistingEntries": True},
        "user": {"username": "alice", "displayName": "Alice", "administrator": True, "passwordSecretRef": "installer-secret:abcdefghijklmnop", "autologin": False, "groups": []},
        "locale": {"language": "en_US.UTF-8", "keyboard": "us", "timezone": "America/New_York"},
        "network": {"required": False, "migrateLiveConnection": False},
        "recovery": {"installDeployment": True, "recoveryKeyAcknowledged": False},
        "applicationProfile": "offline-essential",
    }


class BackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.disk = parse_lsblk(FIXTURE)[0]
        self.service = InstallerService(live_uid=1000, probe=lambda: [self.disk])
        self.token = self.service.issue_session_token(peer_uid=1000)

    def call(self, operation: str, nonce: str, params: dict[str, object] | None = None):
        return self.service.handle(message(operation, nonce, params), peer_uid=1000, session_token=self.token)

    def test_cross_session_is_rejected(self) -> None:
        with self.assertRaises(AuthenticationError):
            self.service.handle(message("installer.initialize", "nonce-cross-user1"), peer_uid=1001, session_token=self.token)

    def test_wrong_token_is_rejected(self) -> None:
        with self.assertRaises(AuthenticationError):
            self.service.handle(message("installer.initialize", "nonce-wrong-token1"), peer_uid=1000, session_token="wrong")

    def test_replay_is_rejected(self) -> None:
        payload = message("installer.initialize", "nonce-replay-test1")
        self.service.handle(payload, peer_uid=1000, session_token=self.token)
        with self.assertRaises(AuthenticationError):
            self.service.handle(payload, peer_uid=1000, session_token=self.token)

    def test_probe_validate_preview_perform_no_writes(self) -> None:
        self.call("installer.probe", "nonce-probe-value1")
        validated = self.call("installer.plan.validate", "nonce-plan-value01", {"plan": plan(self.disk)})
        self.assertTrue(validated["result"]["valid"])
        preview = self.call("installer.plan.preview", "nonce-preview-val1", {"plan": plan(self.disk)})
        self.assertFalse(preview["result"]["writesPerformed"])
        self.assertFalse(preview["result"]["rollbackAfterWrite"])

    def test_install_fails_closed_without_production_adapter(self) -> None:
        self.call("installer.probe", "nonce-probe-value2")
        self.call("installer.plan.validate", "nonce-plan-value02", {"plan": plan(self.disk)})
        with self.assertRaises(BackendUnavailable):
            self.call("installer.install.start", "nonce-start-value1", {"acknowledgement": confirmation_phrase(self.disk), "secondConfirmation": True})

    def test_install_rechecks_disk_confirmation_before_adapter(self) -> None:
        self.call("installer.probe", "nonce-probe-value4")
        self.call("installer.plan.validate", "nonce-plan-value04", {"plan": plan(self.disk)})
        with self.assertRaises(ValueError):
            self.call("installer.install.start", "nonce-start-value2", {"acknowledgement": "ERASE WRONG", "secondConfirmation": True})

    def test_changed_disk_identity_is_rejected(self) -> None:
        self.call("installer.probe", "nonce-probe-value3")
        changed = plan(self.disk)
        changed["targetDisk"] = {"id": self.disk.id, "devicePath": self.disk.devicePath, "expectedSizeBytes": self.disk.sizeBytes + 1}
        result = self.call("installer.plan.validate", "nonce-plan-value03", {"plan": changed})
        self.assertFalse(result["result"]["valid"])

    def test_logs_are_redacted(self) -> None:
        value = redact({"password": "bad", "nested": {"recoveryKey": "worse", "message": "ok"}})
        self.assertNotIn("bad", json.dumps(value))
        self.assertEqual(value["nested"]["message"], "ok")
