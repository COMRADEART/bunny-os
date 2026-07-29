from __future__ import annotations

import unittest

from installer.applications.policy import application_record, developer_environment, remote_plan


class ApplicationTests(unittest.TestCase):
    def test_flatpak_permissions_are_enforceable(self) -> None:
        value = application_record(app_id="org.example.App", source="flatpak", permissions=["camera", "filesystem"])
        self.assertTrue(all(item["enforcement"] == "sandbox/portal" for item in value["permissions"]))

    def test_native_permissions_are_honest(self) -> None:
        value = application_record(app_id="native-tool", source="native", permissions=["network"])
        self.assertEqual(value["permissions"][0]["enforcement"], "Not enforced by this package format")

    def test_flathub_requires_explicit_choice(self) -> None:
        with self.assertRaises(ValueError):
            remote_plan(name="flathub", url="https://flathub.org/repo/flathub.flatpakrepo", explicit_user_choice=False, signatureConfigured=True)

    def test_insecure_remote_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            remote_plan(name="test", url="http://example.test/repo", explicit_user_choice=True, signatureConfigured=True)

    def test_privileged_developer_container_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            developer_environment(project="demo", privileged=True)

