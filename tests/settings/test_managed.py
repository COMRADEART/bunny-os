from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from bunny_shell import policy
from bunny_shell.managed import (
    MANAGEABLE_SETTINGS,
    NEVER_MANAGEABLE_SETTINGS,
    ManagedOverlay,
    ManagedSetting,
    load_overlay,
)
from bunny_shell.settings import SettingLockedError, SettingsStore


def overlay_document(**settings: object) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "organisationId": "org-example-school",
        "updatedAt": "2026-07-29T12:00:00Z",
        "settings": {
            key: {"value": value, "policyId": "POL-0001", "version": 1}
            for key, value in settings.items()
        },
        "osPolicy": {},
    }


def write_overlay(directory: Path, document: dict[str, object]) -> Path:
    path = directory / "managed-settings.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def store_with(directory: Path, overlay: ManagedOverlay) -> SettingsStore:
    return SettingsStore(directory / "settings.json", managed=overlay)


class OverlayLoadingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.directory = Path(self._temp.name)
        self.addCleanup(self._temp.cleanup)

    def test_absent_overlay_is_empty_and_not_an_error(self) -> None:
        result = load_overlay(self.directory / "missing.json")
        self.assertFalse(result.present)
        self.assertEqual(result.settings, {})
        self.assertEqual(result.rejected, [])

    def test_valid_overlay_locks_the_named_setting(self) -> None:
        path = write_overlay(self.directory, overlay_document(localOnlyMode=True))
        result = load_overlay(path)
        self.assertTrue(result.is_locked("localOnlyMode"))
        self.assertEqual(result.settings["localOnlyMode"].value, True)
        self.assertEqual(result.organisationId, "org-example-school")

    def test_unmanageable_setting_is_refused_by_name(self) -> None:
        path = write_overlay(self.directory, overlay_document(telemetryEnabled=True))
        result = load_overlay(path)
        self.assertFalse(result.is_locked("telemetryEnabled"))
        self.assertTrue(any("can never be managed" in item for item in result.rejected))

    def test_every_never_manageable_setting_is_refused(self) -> None:
        for key in sorted(NEVER_MANAGEABLE_SETTINGS):
            with self.subTest(key=key):
                path = write_overlay(self.directory, overlay_document(**{key: True}))
                result = load_overlay(path)
                self.assertFalse(result.is_locked(key))

    def test_allowlist_and_denylist_do_not_intersect(self) -> None:
        self.assertEqual(MANAGEABLE_SETTINGS & NEVER_MANAGEABLE_SETTINGS, frozenset())

    def test_setting_outside_the_allowlist_is_refused(self) -> None:
        path = write_overlay(self.directory, overlay_document(notifications=False))
        result = load_overlay(path)
        self.assertFalse(result.is_locked("notifications"))
        self.assertTrue(any("not an organisation-manageable setting" in item for item in result.rejected))

    def test_invalid_organisation_value_is_discarded_not_applied(self) -> None:
        path = write_overlay(self.directory, overlay_document(cloudFailoverPolicy="always"))
        result = load_overlay(path)
        self.assertFalse(result.is_locked("cloudFailoverPolicy"))
        self.assertTrue(any("organisation value rejected" in item for item in result.rejected))

    def test_entry_without_a_policy_id_is_refused(self) -> None:
        document = overlay_document(localOnlyMode=True)
        del document["settings"]["localOnlyMode"]["policyId"]
        path = write_overlay(self.directory, document)
        self.assertFalse(load_overlay(path).is_locked("localOnlyMode"))

    def test_entry_without_a_valid_version_is_refused(self) -> None:
        document = overlay_document(localOnlyMode=True)
        document["settings"]["localOnlyMode"]["version"] = 0
        path = write_overlay(self.directory, document)
        self.assertFalse(load_overlay(path).is_locked("localOnlyMode"))

    def test_malformed_json_leaves_the_user_in_control(self) -> None:
        path = self.directory / "managed-settings.json"
        path.write_text("{not json", encoding="utf-8")
        result = load_overlay(path)
        self.assertEqual(result.settings, {})
        self.assertTrue(any("not valid JSON" in item for item in result.rejected))

    def test_unsupported_schema_version_is_refused(self) -> None:
        document = overlay_document(localOnlyMode=True)
        document["schemaVersion"] = 2
        path = write_overlay(self.directory, document)
        self.assertEqual(load_overlay(path).settings, {})

    def test_oversized_overlay_is_refused(self) -> None:
        document = overlay_document(approvedSearchLocations=["x" * 500 for _ in range(100)])
        document["padding"] = "y" * 300_000
        path = write_overlay(self.directory, document)
        result = load_overlay(path)
        self.assertTrue(any("size limit" in item for item in result.rejected))


class LockedSettingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.directory = Path(self._temp.name)
        self.addCleanup(self._temp.cleanup)
        self.overlay = ManagedOverlay(
            organisationId="org-example-school",
            settings={"localOnlyMode": ManagedSetting(True, "POL-0001", 1)},
        )

    def test_locked_value_overrides_the_user_value(self) -> None:
        store = store_with(self.directory, ManagedOverlay())
        store.set("localOnlyMode", False)
        managed_store = store_with(self.directory, self.overlay)
        self.assertTrue(managed_store.get_all()["localOnlyMode"])

    def test_locked_setting_refuses_a_user_write(self) -> None:
        store = store_with(self.directory, self.overlay)
        with self.assertRaises(SettingLockedError) as error:
            store.set("localOnlyMode", False)
        self.assertEqual(error.exception.key, "localOnlyMode")
        self.assertEqual(error.exception.policyId, "POL-0001")
        self.assertIn("org-example-school", str(error.exception))

    def test_unlocked_setting_still_writes(self) -> None:
        store = store_with(self.directory, self.overlay)
        self.assertTrue(store.set("notifications", False)["notifications"] is False)

    def test_reset_returns_to_the_organisation_value_not_the_default(self) -> None:
        store = store_with(self.directory, self.overlay)
        # The Bunny OS default for localOnlyMode is False; the organisation
        # requires True. Reset must not be an escape hatch.
        self.assertTrue(store.reset("localOnlyMode")["localOnlyMode"])

    def test_reset_all_preserves_organisation_locks(self) -> None:
        store = store_with(self.directory, self.overlay)
        self.assertTrue(store.reset()["localOnlyMode"])

    def test_locked_local_only_drags_the_coupled_settings(self) -> None:
        store = store_with(self.directory, self.overlay)
        values = store.get_all()
        self.assertEqual(values["cloudFailoverPolicy"], "never")
        self.assertEqual(values["defaultProviderAlias"], "local")

    def test_describe_names_the_owning_organisation(self) -> None:
        described = store_with(self.directory, self.overlay).describe()
        self.assertTrue(described["localOnlyMode"]["managed"])
        self.assertEqual(described["localOnlyMode"]["lockedBy"], "org-example-school")
        self.assertEqual(described["localOnlyMode"]["lockedByPolicy"], "POL-0001")
        self.assertEqual(described["localOnlyMode"]["effectiveSource"], "organisation")
        self.assertEqual(described["localOnlyMode"]["scope"], "organisation")
        self.assertEqual(described["localOnlyMode"]["reset"], "organisation")

    def test_describe_marks_unmanaged_settings_as_user_owned(self) -> None:
        described = store_with(self.directory, self.overlay).describe()
        self.assertFalse(described["notifications"]["managed"])
        self.assertEqual(described["notifications"]["effectiveSource"], "user")
        self.assertIsNone(described["notifications"]["lockedBy"])

    def test_describe_reports_manageability(self) -> None:
        described = store_with(self.directory, ManagedOverlay()).describe()
        self.assertFalse(described["telemetryEnabled"]["manageable"])
        self.assertTrue(described["localOnlyMode"]["manageable"])

    def test_managed_status_surfaces_rejections(self) -> None:
        overlay = ManagedOverlay(rejected=["telemetryEnabled: this setting can never be managed"])
        status = store_with(self.directory, overlay).managed_status()
        self.assertEqual(len(status["rejected"]), 1)

    def test_unmanaged_store_behaves_exactly_as_before(self) -> None:
        store = store_with(self.directory, ManagedOverlay())
        self.assertFalse(store.get_all()["localOnlyMode"])
        store.set("localOnlyMode", True)
        self.assertTrue(store.get_all()["localOnlyMode"])
        self.assertFalse(store.reset("localOnlyMode")["localOnlyMode"])


class NetworkKindTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.directory = Path(self._temp.name)
        self.addCleanup(self._temp.cleanup)

    def store(self, **values: object) -> SettingsStore:
        store = SettingsStore(self.directory / "settings.json", managed=ManagedOverlay())
        for key, value in values.items():
            store.set(key, value)
        return store

    def test_sync_and_enrolment_are_known_kinds(self) -> None:
        self.assertIn("sync", policy.NETWORK_KINDS)
        self.assertIn("enrolment", policy.NETWORK_KINDS)

    def test_sync_is_denied_by_local_only_mode(self) -> None:
        decision = policy.evaluate("sync", settings=self.store(localOnlyMode=True))
        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["reason"], "local_only_mode")

    def test_enrolment_survives_local_only_mode_like_os_update(self) -> None:
        store = self.store(localOnlyMode=True)
        self.assertTrue(policy.evaluate("enrolment", settings=store)["allowed"])
        self.assertTrue(policy.evaluate("os_update", settings=store)["allowed"])

    def test_offline_mode_stops_both(self) -> None:
        store = self.store(offlineMode=True)
        for kind in ("sync", "enrolment"):
            with self.subTest(kind=kind):
                decision = policy.evaluate(kind, settings=store)
                self.assertFalse(decision["allowed"])
                self.assertEqual(decision["reason"], "offline_mode")

    def test_both_are_allowed_by_default(self) -> None:
        store = self.store()
        for kind in ("sync", "enrolment"):
            with self.subTest(kind=kind):
                self.assertTrue(policy.evaluate(kind, settings=store)["allowed"])

    def test_unknown_kind_is_still_denied(self) -> None:
        decision = policy.evaluate("exfiltrate", settings=self.store())
        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["reason"], "unknown_action")

    def test_local_only_denied_set_is_a_subset_of_known_kinds(self) -> None:
        self.assertTrue(policy.LOCAL_ONLY_DENIED_KINDS <= policy.NETWORK_KINDS)


if __name__ == "__main__":
    unittest.main()
