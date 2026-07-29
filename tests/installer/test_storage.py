from __future__ import annotations

import json
from pathlib import Path
import unittest

from installer.storage.models import parse_lsblk
from installer.storage.planning import PlannedPartition, automatic_plan, validate_manual
from installer.storage.safety import assess_target, assert_confirmed, confirmation_phrase


FIXTURES = json.loads((Path(__file__).parent / "fixtures/storage-fixtures.json").read_text(encoding="utf-8"))["fixtures"]


class StorageTests(unittest.TestCase):
    def disk(self, name: str):
        return parse_lsblk(FIXTURES[name], installation_source="/run/initramfs/live")[0]

    def test_serials_and_uuids_are_redacted(self) -> None:
        disk = self.disk("windows_uefi")
        self.assertTrue(disk.serialRedacted.startswith("sha256:"))
        self.assertNotIn("PRIVATE-SERIAL", json.dumps(disk.to_dict()))
        self.assertNotIn("SECRET-UUID", json.dumps(disk.to_dict()))

    def test_detects_existing_windows(self) -> None:
        self.assertEqual(self.disk("windows_uefi").existingOperatingSystems[0].family, "windows")

    def test_excludes_installation_media(self) -> None:
        disk = self.disk("removable_install_media")
        findings = assess_target(disk, mode="erase_disk")
        self.assertTrue(any(item.code == "installation-media" and item.blocks for item in findings))

    def test_rejects_small_and_read_only_disks(self) -> None:
        for name in ("small_disk", "read_only"):
            self.assertTrue(any(item.blocks for item in assess_target(self.disk(name), mode="erase_disk")))

    def test_erase_plan_has_uefi_boot_and_system(self) -> None:
        plan = automatic_plan(self.disk("empty_gpt"), mode="erase_disk", encryption=False)
        self.assertEqual([part["role"] for part in plan["partitions"]], ["efi", "boot", "system"])
        self.assertFalse(plan["operationsAreReversibleAfterWrite"])

    def test_encrypted_plan_uses_luks2(self) -> None:
        plan = automatic_plan(self.disk("empty_gpt"), mode="erase_disk", encryption=True)
        self.assertEqual(plan["partitions"][-1]["filesystem"], "crypto_luks")
        self.assertTrue(plan["encryption"]["recoveryKeyRequired"])

    def test_alongside_reuses_esp_without_format(self) -> None:
        plan = automatic_plan(self.disk("windows_uefi"), mode="install_alongside", encryption=False, free_start_bytes=180 * 1024**3, free_size_bytes=70 * 1024**3)
        esp = plan["partitions"][0]
        self.assertEqual(esp["action"], "reuse")
        self.assertTrue(esp["preserve"])

    def test_destructive_confirmation_binds_disk(self) -> None:
        disk = self.disk("empty_gpt")
        assert_confirmed(disk, acknowledgement=confirmation_phrase(disk), second_confirmation=True)
        with self.assertRaises(ValueError):
            assert_confirmed(disk, acknowledgement="ERASE /dev/vdz", second_confirmation=True)

    def test_manual_validation_detects_missing_and_duplicate_mounts(self) -> None:
        items = [
            PlannedPartition("create", "efi", 0, 1024**3, "vfat", "/boot/efi"),
            PlannedPartition("create", "home", 2 * 1024**3, 10 * 1024**3, "ext4", "/home"),
            PlannedPartition("create", "var", 13 * 1024**3, 10 * 1024**3, "ext4", "/home"),
        ]
        errors = validate_manual(items)
        self.assertTrue(any("missing root" in item for item in errors))
        self.assertTrue(any("duplicate" in item for item in errors))

    def test_fixture_catalog_covers_required_cases(self) -> None:
        expected = {"empty_gpt", "empty_mbr", "windows_uefi", "linux", "dual_boot", "encrypted_linux", "bitlocker_like", "multiple_disks", "small_disk", "read_only", "removable_install_media", "corrupted_partition_table"}
        self.assertEqual(set(FIXTURES), expected)

