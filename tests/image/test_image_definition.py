from __future__ import annotations

import json
import unittest

from tests.support import ROOT


class ImageDefinitionTests(unittest.TestCase):
    def test_profiles_and_package_sets_exist(self) -> None:
        for name in ("developer", "minimal", "desktop", "recovery", "shell", "shell-test"):
            profile = json.loads((ROOT / f"build/profiles/{name}.json").read_text(encoding="utf-8"))
            for package_set in profile["packageSets"]:
                self.assertTrue((ROOT / f"build/packages/{package_set}.txt").is_file())

    def test_developer_updates_disabled(self) -> None:
        value = json.loads((ROOT / "build/manifests/update.disabled.json").read_text(encoding="utf-8"))
        self.assertFalse(value["enabled"])

    def test_no_private_key_in_build_tree(self) -> None:
        values = list((ROOT / "build/keys").glob("*.key")) + list((ROOT / "build/keys").glob("*private*"))
        self.assertEqual(values, [])

    def test_container_is_bootc_based(self) -> None:
        value = (ROOT / "build/Containerfile").read_text(encoding="utf-8")
        self.assertIn("fedora-bootc:44", value)
        self.assertIn('containers.bootc="1"', value)

    def test_image_inspection_handles_bootc_layout_without_legacy_auto_inspection(self) -> None:
        value = (ROOT / "build/scripts/inspect-image.sh").read_text(encoding="utf-8")
        self.assertIn("virt-filesystems", value)
        self.assertIn('filesystem labelled root', value)
        self.assertIn('/ostree/deploy/', value)
        self.assertNotIn(' -i ', value)

    def test_each_image_type_is_composed_with_a_separate_builder_invocation(self) -> None:
        value = (ROOT / "build/scripts/build-image.sh").read_text(encoding="utf-8")
        self.assertIn('for image_type in "${image_types[@]}"', value)
        self.assertIn('ext4 "${image_type}"', value)
        self.assertNotIn('ext4 "${image_types[@]}"', value)


if __name__ == "__main__":
    unittest.main()
