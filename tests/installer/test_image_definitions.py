from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class ImageDefinitionTests(unittest.TestCase):
    def test_live_profile_embeds_offline_payload(self) -> None:
        value = json.loads((ROOT / "build/profiles/live.json").read_text(encoding="utf-8"))
        self.assertEqual(value["imageTypes"], ["bootc-generic-iso"])
        self.assertTrue(value["offlinePayload"])

    def test_beta_formats_are_not_padded_with_untested_ova(self) -> None:
        value = json.loads((ROOT / "build/profiles/beta.json").read_text(encoding="utf-8"))
        self.assertEqual(value["imageTypes"], ["qcow2", "raw"])
        self.assertNotIn("ova", value["imageTypes"])

    def test_boot_menu_has_required_entries(self) -> None:
        value = (ROOT / "installer/config/iso.yaml").read_text(encoding="utf-8")
        for label in ("Try or Install Bunny OS", "Safe Graphics", "Recovery Tools", "Verify Installation Media"):
            self.assertIn(label, value)
        self.assertIn("serial console", value)

    def test_interactive_defaults_do_not_clear_disk_or_embed_secrets(self) -> None:
        value = (ROOT / "installer/config/interactive-defaults.ks").read_text(encoding="utf-8")
        self.assertNotIn("clearpart", "\n".join(line for line in value.splitlines() if not line.startswith("#")))
        self.assertNotIn("autopart", "\n".join(line for line in value.splitlines() if not line.startswith("#")))
        self.assertNotIn("password=", value)

    def test_live_builder_uses_separate_installer_and_payload_refs(self) -> None:
        value = (ROOT / "build/scripts/build-live-image.sh").read_text(encoding="utf-8")
        self.assertIn("--bootc-ref", value)
        self.assertIn("--bootc-installer-payload-ref", value)
        self.assertIn("bootc-generic-iso", value)

