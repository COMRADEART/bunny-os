from __future__ import annotations

import unittest

from installer.users.validation import validate_user_plan


def user(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {"username": "alice", "displayName": "Alice", "administrator": True, "passwordSecretRef": "fd:3", "autologin": False, "groups": []}
    value.update(changes)
    return value


class UserPlanTests(unittest.TestCase):
    def test_conventional_admin_user_passes(self) -> None:
        self.assertEqual(validate_user_plan(user()), ())

    def test_root_and_root_equivalent_groups_fail(self) -> None:
        self.assertTrue(validate_user_plan(user(username="root")))
        self.assertTrue(validate_user_plan(user(groups=["docker"])))

    def test_plaintext_password_reference_fails(self) -> None:
        self.assertTrue(validate_user_plan(user(passwordSecretRef="hunter2")))

    def test_autologin_is_off_by_default(self) -> None:
        self.assertTrue(validate_user_plan(user(autologin=True)))

