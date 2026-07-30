from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from enterprise.enrolment import (
    ENROLMENT_MODES,
    REQUIRED_DISCLOSURE_FIELDS,
    EnrolmentError,
    assert_no_secret_in_arguments,
    evaluate_disclosure,
    next_state,
    parse_enrolment_token,
    parse_message,
    redact_for_log,
)

NOW = datetime(2026, 7, 29, 12, 0, 0, tzinfo=timezone.utc)


def stamp(offset_seconds: int = 0) -> str:
    return (NOW + timedelta(seconds=offset_seconds)).isoformat().replace("+00:00", "Z")


def token(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schemaVersion": 1,
        "tokenId": "ent-0123456789abcdef",
        "organisationId": "org-example-school",
        "issuedAt": stamp(-60),
        "expiresAt": stamp(3600),
        "singleUse": True,
        "mode": "organisation-owned",
    }
    value.update(overrides)
    return value


def message(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schemaVersion": 1,
        "messageType": "enrolment.begin",
        "messageId": "msg-0001",
        "organisationId": "org-example-school",
        "nonce": "abcdefghijklmnopqrstuvwx",
        "timestamp": stamp(),
        "params": {"deviceKeyId": "dev-0123456789abcdef"},
    }
    value.update(overrides)
    return value


def disclosure(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "organisationName": "Example School",
        "managementServer": "https://fleet.example.invalid",
        "policiesApplied": ["Require disk encryption", "Pin the stable update channel"],
        "informationVisibleToOrganisation": ["OS version", "Update state", "Encryption state"],
        "remoteActionsAvailable": ["Request update check", "Request lock"],
        "applicationControls": "The school may require or block applications.",
        "updateControls": "The school schedules updates and may set a deadline.",
        "unenrolmentRules": "You may unenrol this personally owned device at any time from Settings.",
        "personalDataBoundary": "Your personal files, accounts, and private Bunny memories stay invisible to the school.",
    }
    value.update(overrides)
    return value


class EnrolmentTokenTests(unittest.TestCase):
    def test_valid_token_parses(self) -> None:
        self.assertEqual(parse_enrolment_token(token(), now=NOW).organisationId, "org-example-school")

    def test_expired_token_is_rejected(self) -> None:
        value = token(issuedAt=stamp(-7200), expiresAt=stamp(-3600))
        with self.assertRaises(EnrolmentError) as error:
            parse_enrolment_token(value, now=NOW)
        self.assertIn("expired", str(error.exception))

    def test_replayed_token_is_rejected(self) -> None:
        with self.assertRaises(EnrolmentError) as error:
            parse_enrolment_token(token(), now=NOW, consumed_token_ids=["ent-0123456789abcdef"])
        self.assertIn("already been consumed", str(error.exception))

    def test_multi_use_token_is_rejected(self) -> None:
        with self.assertRaises(EnrolmentError):
            parse_enrolment_token(token(singleUse=False), now=NOW)

    def test_overlong_lifetime_is_rejected(self) -> None:
        value = token(issuedAt=stamp(-60), expiresAt=stamp(60 * 60 * 48))
        with self.assertRaises(EnrolmentError):
            parse_enrolment_token(value, now=NOW)

    def test_token_carrying_a_secret_is_rejected(self) -> None:
        value = token()
        value["secret"] = "hunter2"
        with self.assertRaises(EnrolmentError):
            parse_enrolment_token(value, now=NOW)

    def test_unknown_mode_is_rejected(self) -> None:
        with self.assertRaises(EnrolmentError):
            parse_enrolment_token(token(mode="silently-managed"), now=NOW)

    def test_expiry_before_issue_is_rejected(self) -> None:
        with self.assertRaises(EnrolmentError):
            parse_enrolment_token(token(issuedAt=stamp(0), expiresAt=stamp(-1)), now=NOW)


class EnrolmentMessageTests(unittest.TestCase):
    def test_valid_message_parses(self) -> None:
        self.assertEqual(parse_message(message(), now=NOW)["messageType"], "enrolment.begin")

    def test_stale_message_is_rejected(self) -> None:
        with self.assertRaises(EnrolmentError) as error:
            parse_message(message(timestamp=stamp(-3600)), now=NOW)
        self.assertIn("stale", str(error.exception))

    def test_nonce_replay_is_rejected(self) -> None:
        seen: set[str] = set()
        parse_message(message(), now=NOW, seen_nonces=seen)
        with self.assertRaises(EnrolmentError) as error:
            parse_message(message(), now=NOW, seen_nonces=seen)
        self.assertIn("replay", str(error.exception))

    def test_secret_in_params_is_rejected(self) -> None:
        value = message(params={"deviceKeyId": "dev-0123456789abcdef", "token": "abc123"})
        with self.assertRaises(EnrolmentError):
            parse_message(value, now=NOW)

    def test_nested_secret_in_params_is_rejected(self) -> None:
        value = message(params={"outer": {"inner": {"passphrase": "abc"}}})
        with self.assertRaises(EnrolmentError):
            parse_message(value, now=NOW)

    def test_unknown_message_type_is_rejected(self) -> None:
        with self.assertRaises(EnrolmentError):
            parse_message(message(messageType="enrolment.root-shell"), now=NOW)

    def test_extra_field_is_rejected(self) -> None:
        value = message()
        value["extra"] = 1
        with self.assertRaises(EnrolmentError):
            parse_message(value, now=NOW)

    def test_log_rendering_omits_params(self) -> None:
        rendered = redact_for_log(message())
        self.assertNotIn("params", rendered)
        self.assertTrue(rendered["paramsOmitted"])

    def test_secret_in_process_arguments_is_rejected(self) -> None:
        with self.assertRaises(EnrolmentError):
            assert_no_secret_in_arguments(["bunny-enrol", "--token=abc123"])

    def test_safe_arguments_are_accepted(self) -> None:
        assert_no_secret_in_arguments(["bunny-enrol", "--organisation=org-example-school"])


class DisclosureTests(unittest.TestCase):
    def test_complete_disclosure_passes(self) -> None:
        report = evaluate_disclosure(disclosure(), mode="personally-owned")
        self.assertTrue(report["complete"], report)
        self.assertTrue(report["confirmationRequired"])

    def test_every_required_field_is_checked(self) -> None:
        for field in REQUIRED_DISCLOSURE_FIELDS:
            with self.subTest(field=field):
                value = disclosure()
                del value[field]
                report = evaluate_disclosure(value, mode="organisation-owned")
                self.assertIn(field, report["missingFields"])

    def test_non_https_management_server_is_flagged(self) -> None:
        report = evaluate_disclosure(disclosure(managementServer="http://fleet.example.invalid"), mode="organisation-owned")
        self.assertFalse(report["complete"])

    def test_personally_owned_cannot_disclose_blanket_reset_permission(self) -> None:
        value = disclosure()
        value["fullDeviceResetPermitted"] = True
        report = evaluate_disclosure(value, mode="personally-owned")
        self.assertFalse(report["complete"])
        self.assertTrue(any("full-reset" in item for item in report["problems"]))

    def test_organisation_owned_modes_are_flagged_as_such(self) -> None:
        self.assertTrue(evaluate_disclosure(disclosure(), mode="kiosk-or-dedicated-purpose")["organisationOwned"])
        self.assertFalse(evaluate_disclosure(disclosure(), mode="personally-owned")["organisationOwned"])

    def test_all_five_enrolment_modes_are_supported(self) -> None:
        self.assertEqual(len(ENROLMENT_MODES), 5)
        for mode in ENROLMENT_MODES:
            with self.subTest(mode=mode):
                evaluate_disclosure(disclosure(), mode=mode)

    def test_unknown_mode_is_rejected(self) -> None:
        with self.assertRaises(EnrolmentError):
            evaluate_disclosure(disclosure(), mode="surprise")


class EnrolmentStateTests(unittest.TestCase):
    def test_happy_path_progresses(self) -> None:
        state = "unenrolled"
        for requested in (
            "token-validated", "organisation-trust-validated", "device-key-generated",
            "certificate-issued", "device-registered", "policy-bootstrapped", "enrolled",
        ):
            state = next_state(state, requested)
        self.assertEqual(state, "enrolled")

    def test_skipping_a_stage_is_rejected(self) -> None:
        with self.assertRaises(EnrolmentError):
            next_state("unenrolled", "enrolled")

    def test_interrupted_enrolment_can_abort_to_unenrolled(self) -> None:
        self.assertEqual(next_state("certificate-issued", "unenrolled"), "unenrolled")

    def test_resume_from_same_state_is_permitted(self) -> None:
        self.assertEqual(next_state("device-registered", "device-registered"), "device-registered")

    def test_unenrolment_requires_unenrolling_first(self) -> None:
        self.assertEqual(next_state("enrolled", "unenrolling"), "unenrolling")
        with self.assertRaises(EnrolmentError):
            next_state("enrolled", "unenrolled")


if __name__ == "__main__":
    unittest.main()
