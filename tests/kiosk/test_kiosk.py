from __future__ import annotations

import unittest

from enterprise.kiosk import (
    PROTECTED_SETTINGS,
    RESTRICTABLE_SETTINGS,
    KioskError,
    parse_kiosk_profile,
    parse_shared_device_policy,
)


def profile(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schemaVersion": 1,
        "profileId": "ksk-library-catalogue",
        "mode": "single-application",
        "fixedApplication": "org.example.Catalogue",
        "networkAllowlist": ["catalogue.example.invalid", "*.cdn.example.invalid"],
        "localStorageQuotaMb": 512,
        "automaticRecovery": True,
        "administratorExitEnabled": True,
        "sessionIdleResetSeconds": 300,
        "restrictions": {"terminalAvailable": False, "applicationInstallation": False},
    }
    value.update(overrides)
    return value


def shared(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schemaVersion": 1,
        "sessionType": "ephemeral",
        "cleanupOnLogout": True,
        "storageQuotaMb": 2048,
        "shareLocalModelWeights": True,
        "shareBunnyMemory": False,
        "organisationApplications": ["org.example.LabTool"],
    }
    value.update(overrides)
    return value


class KioskProfileTests(unittest.TestCase):
    def test_valid_profile_parses(self) -> None:
        self.assertEqual(parse_kiosk_profile(profile()).mode, "single-application")

    def test_kiosk_cannot_disable_update_signature_verification(self) -> None:
        with self.assertRaises(KioskError) as error:
            parse_kiosk_profile(profile(restrictions={"updateSignatureVerification": False}))
        self.assertIn("cannot alter security protections", str(error.exception))

    def test_kiosk_cannot_weaken_any_protected_setting(self) -> None:
        for setting in sorted(PROTECTED_SETTINGS):
            with self.subTest(setting=setting):
                with self.assertRaises(KioskError):
                    parse_kiosk_profile(profile(restrictions={setting: False}))

    def test_kiosk_may_restrict_user_facing_settings(self) -> None:
        for setting in sorted(RESTRICTABLE_SETTINGS):
            with self.subTest(setting=setting):
                parse_kiosk_profile(profile(restrictions={setting: False}))

    def test_unknown_restriction_is_refused(self) -> None:
        with self.assertRaises(KioskError):
            parse_kiosk_profile(profile(restrictions={"disableEverything": True}))

    def test_administrator_exit_cannot_be_disabled(self) -> None:
        with self.assertRaises(KioskError) as error:
            parse_kiosk_profile(profile(administratorExitEnabled=False))
        self.assertIn("physical console", str(error.exception))

    def test_single_application_mode_requires_an_application(self) -> None:
        with self.assertRaises(KioskError):
            parse_kiosk_profile(profile(fixedApplication=None))

    def test_fixed_application_must_be_reverse_dns(self) -> None:
        with self.assertRaises(KioskError):
            parse_kiosk_profile(profile(fixedApplication="catalogue"))

    def test_restricted_desktop_mode_rejects_a_fixed_application(self) -> None:
        with self.assertRaises(KioskError):
            parse_kiosk_profile(profile(mode="restricted-desktop"))

    def test_restricted_desktop_mode_without_application_is_accepted(self) -> None:
        parse_kiosk_profile(profile(mode="restricted-desktop", fixedApplication=None))

    def test_malformed_network_allowlist_entry_is_refused(self) -> None:
        with self.assertRaises(KioskError):
            parse_kiosk_profile(profile(networkAllowlist=["http://example.invalid/path"]))

    def test_storage_quota_has_a_floor(self) -> None:
        with self.assertRaises(KioskError):
            parse_kiosk_profile(profile(localStorageQuotaMb=8))

    def test_idle_reset_bounds_are_enforced(self) -> None:
        with self.assertRaises(KioskError):
            parse_kiosk_profile(profile(sessionIdleResetSeconds=5))
        with self.assertRaises(KioskError):
            parse_kiosk_profile(profile(sessionIdleResetSeconds=99999))


class SharedDeviceTests(unittest.TestCase):
    def test_valid_shared_policy_parses(self) -> None:
        self.assertEqual(parse_shared_device_policy(shared()).sessionType, "ephemeral")

    def test_bunny_memory_is_never_shared_between_users(self) -> None:
        with self.assertRaises(KioskError) as error:
            parse_shared_device_policy(shared(shareBunnyMemory=True))
        self.assertIn("never shared between users", str(error.exception))

    def test_local_model_weights_may_be_shared(self) -> None:
        self.assertTrue(parse_shared_device_policy(shared(shareLocalModelWeights=True)).shareLocalModelWeights)

    def test_ephemeral_session_must_clean_up(self) -> None:
        with self.assertRaises(KioskError) as error:
            parse_shared_device_policy(shared(cleanupOnLogout=False))
        self.assertIn("clean up local user data", str(error.exception))

    def test_persistent_named_session_may_retain_data(self) -> None:
        parsed = parse_shared_device_policy(shared(sessionType="persistent-named", cleanupOnLogout=False))
        self.assertFalse(parsed.cleanupOnLogout)

    def test_storage_quota_floor_applies(self) -> None:
        with self.assertRaises(KioskError):
            parse_shared_device_policy(shared(storageQuotaMb=1))

    def test_unknown_session_type_is_refused(self) -> None:
        with self.assertRaises(KioskError):
            parse_shared_device_policy(shared(sessionType="anonymous-shared-memory"))

    def test_unknown_field_is_refused(self) -> None:
        with self.assertRaises(KioskError):
            parse_shared_device_policy(shared(shareBrowserHistory=True))


if __name__ == "__main__":
    unittest.main()
