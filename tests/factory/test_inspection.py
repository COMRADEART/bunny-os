from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from oem.inspection import (
    INSPECTABLE_CHECKS,
    REQUIRES_LIVE_ATTESTATION,
    merge_attestation,
    probe_root,
)
from oem.validation.finalize import CHECK_IDS, FAIL, PASS, UNKNOWN, describe_checks, evaluate_finalisation


def write(root: Path, relative: str, content: str = "x", mode: int | None = None) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if mode is not None:
        path.chmod(mode)
    return path


def clean_tree(root: Path) -> Path:
    """A root filesystem that has been correctly sealed."""
    write(root, "etc/passwd", "root:x:0:0:root:/root:/bin/bash\nnobody:x:65534:65534::/:/sbin/nologin\n")
    write(root, "etc/group", "wheel:x:10:\nsudo:x:27:\nadm:x:4:\n")
    write(root, "etc/gdm/custom.conf", "[daemon]\n")
    write(root, "etc/machine-id", "")
    write(root, "etc/sudoers", "root ALL=(ALL) ALL\n")
    return root


class CleanTreeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = clean_tree(Path(self._temp.name))
        self.addCleanup(self._temp.cleanup)

    def test_probe_returns_a_record_for_every_check(self) -> None:
        record = probe_root(self.root)
        self.assertEqual(set(record["checks"]), set(CHECK_IDS))

    def test_clean_tree_passes_every_inspectable_check(self) -> None:
        record = probe_root(self.root)
        for check_id in sorted(INSPECTABLE_CHECKS):
            with self.subTest(check=check_id):
                self.assertEqual(record["checks"][check_id], PASS, record["findings"])

    def test_offline_probe_alone_never_seals(self) -> None:
        # Five checks need a running system, so an offline probe must refuse.
        verdict = evaluate_finalisation(probe_root(self.root))
        self.assertFalse(verdict.sealed)
        self.assertEqual(set(verdict.unknown), set(REQUIRES_LIVE_ATTESTATION))

    def test_seventeen_checks_are_offline_inspectable(self) -> None:
        self.assertEqual(len(INSPECTABLE_CHECKS), 17)
        self.assertEqual(len(REQUIRES_LIVE_ATTESTATION), 5)
        self.assertEqual(len(INSPECTABLE_CHECKS) + len(REQUIRES_LIVE_ATTESTATION), len(CHECK_IDS))

    def test_catalogue_marks_which_checks_the_probe_can_settle(self) -> None:
        catalogue = {item["checkId"]: item for item in describe_checks()}
        self.assertTrue(catalogue["shell-history-cleared"]["offlineInspectable"])
        self.assertFalse(catalogue["recovery-verified"]["offlineInspectable"])
        self.assertIn("booting", catalogue["recovery-verified"]["requiresLiveAttestation"])

    def test_missing_root_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            probe_root(self.root / "does-not-exist")


class ResidueDetectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = clean_tree(Path(self._temp.name))
        self.addCleanup(self._temp.cleanup)

    def status(self, check_id: str) -> str:
        return probe_root(self.root)["checks"][check_id]

    def test_leftover_factory_account_is_detected(self) -> None:
        write(
            self.root,
            "etc/passwd",
            "root:x:0:0:root:/root:/bin/bash\noemtest:x:1000:1000::/home/oemtest:/bin/bash\n",
        )
        self.assertEqual(self.status("factory-accounts-removed"), FAIL)

    def test_nologin_system_account_is_not_flagged(self) -> None:
        write(
            self.root,
            "etc/passwd",
            "root:x:0:0:root:/root:/bin/bash\nbunny-policy:x:471:471::/:/sbin/nologin\n",
        )
        self.assertEqual(self.status("factory-accounts-removed"), PASS)

    def test_privileged_group_membership_is_detected(self) -> None:
        write(self.root, "etc/group", "wheel:x:10:oemtest\n")
        self.assertEqual(self.status("factory-groups-removed"), FAIL)

    def test_autologin_is_detected(self) -> None:
        write(self.root, "etc/gdm/custom.conf", "[daemon]\nAutomaticLoginEnable=true\n")
        self.assertEqual(self.status("factory-autologin-disabled"), FAIL)

    def test_getty_autologin_dropin_is_detected(self) -> None:
        write(self.root, "etc/systemd/system/getty@tty1.service.d/autologin.conf", "ExecStart=--autologin root\n")
        self.assertEqual(self.status("factory-autologin-disabled"), FAIL)

    def test_wifi_profile_is_detected(self) -> None:
        write(self.root, "etc/NetworkManager/system-connections/FactoryNet.nmconnection", "psk=hunter2\n")
        self.assertEqual(self.status("factory-wifi-profiles-removed"), FAIL)

    def test_authorized_keys_is_detected(self) -> None:
        write(self.root, "root/.ssh/authorized_keys", "ssh-ed25519 AAAA factory@line\n")
        self.assertEqual(self.status("factory-ssh-keys-removed"), FAIL)

    def test_embedded_credential_is_detected(self) -> None:
        write(self.root, "etc/bunny-os/provider.conf", "api_key=sk-livekey-abcdef123456\n")
        self.assertEqual(self.status("test-credentials-removed"), FAIL)

    def test_embedded_private_key_is_detected(self) -> None:
        write(self.root, "var/lib/bunny-os/test.pem", "-----BEGIN PRIVATE KEY-----\nAAAA\n")
        self.assertEqual(self.status("test-credentials-removed"), FAIL)

    def test_passwordless_sudo_is_detected(self) -> None:
        write(self.root, "etc/sudoers.d/factory", "oemtest ALL=(ALL) NOPASSWD:ALL\n")
        self.assertEqual(self.status("factory-sudo-rules-removed"), FAIL)

    def test_permissive_polkit_rule_is_detected(self) -> None:
        write(self.root, "etc/polkit-1/rules.d/99-factory.rules", "polkit.addRule(function(){return polkit.Result.YES;});")
        self.assertEqual(self.status("factory-sudo-rules-removed"), FAIL)

    def test_installer_log_is_detected(self) -> None:
        write(self.root, "var/log/anaconda/journal.log", "installed onto /dev/sda serial ABC123\n")
        self.assertEqual(self.status("identifier-logs-removed"), FAIL)

    def test_shell_history_is_detected(self) -> None:
        write(self.root, "root/.bash_history", "curl https://factory.invalid/provision.sh\n")
        self.assertEqual(self.status("shell-history-cleared"), FAIL)

    def test_user_shell_history_is_detected(self) -> None:
        write(self.root, "home/oemtest/.zsh_history", "export TOKEN=abc\n")
        self.assertEqual(self.status("shell-history-cleared"), FAIL)

    def test_kickstart_answer_file_is_detected(self) -> None:
        write(self.root, "root/anaconda-ks.cfg", "rootpw --plaintext factory\n")
        self.assertEqual(self.status("installer-session-removed"), FAIL)

    def test_fixed_machine_id_is_detected(self) -> None:
        write(self.root, "etc/machine-id", "0123456789abcdef0123456789abcdef\n")
        self.assertEqual(self.status("machine-id-regenerated"), FAIL)

    def test_uninitialized_machine_id_passes(self) -> None:
        write(self.root, "etc/machine-id", "uninitialized\n")
        self.assertEqual(self.status("machine-id-regenerated"), PASS)

    def test_cloned_host_key_is_detected(self) -> None:
        write(self.root, "etc/ssh/ssh_host_ed25519_key", "PRIVATE\n")
        self.assertEqual(self.status("host-keys-regenerated"), FAIL)

    def test_factory_device_identity_is_detected(self) -> None:
        write(self.root, "var/lib/bunny-os/identity/device.json", "{}")
        self.assertEqual(self.status("device-identity-absent-or-fresh"), FAIL)

    def test_enrolment_residue_is_detected(self) -> None:
        write(self.root, "etc/bunny-os/enrolment.json", "{}")
        self.assertEqual(self.status("enrolment-state-absent"), FAIL)

    def test_sync_residue_is_detected(self) -> None:
        write(self.root, "var/lib/bunny-os/sync/device.key", "k")
        self.assertEqual(self.status("sync-state-absent"), FAIL)

    def test_completed_first_run_marker_is_detected(self) -> None:
        write(self.root, "home/oemtest/.local/state/bunny-os/first-run.json", '{"completed": true}')
        self.assertEqual(self.status("first-user-setup-incomplete"), FAIL)

    def test_retained_diagnostic_serial_is_detected(self) -> None:
        write(self.root, "var/lib/bunny-os/support/bundle.txt", "serial: SN12345678\n")
        self.assertEqual(self.status("diagnostic-serials-not-retained"), FAIL)

    def test_missing_passwd_is_unknown_not_pass(self) -> None:
        (self.root / "etc/passwd").unlink()
        self.assertEqual(self.status("factory-accounts-removed"), UNKNOWN)

    def test_a_single_residue_blocks_handoff(self) -> None:
        write(self.root, "root/.bash_history", "secret\n")
        verdict = evaluate_finalisation(probe_root(self.root))
        self.assertFalse(verdict.sealed)
        self.assertIn("shell-history-cleared", verdict.failures)


class AttestationMergeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = clean_tree(Path(self._temp.name))
        self.addCleanup(self._temp.cleanup)
        self.record = probe_root(self.root)

    def attestation(self, **overrides: object) -> dict[str, object]:
        value: dict[str, object] = {
            "schemaVersion": 1,
            "signature": {"algorithm": "ed25519", "keyId": "oem-test", "value": "A" * 88},
            "checks": {name: PASS for name in REQUIRES_LIVE_ATTESTATION},
        }
        value.update(overrides)
        return value

    def test_merged_attestation_completes_the_record(self) -> None:
        merged = merge_attestation(self.record, self.attestation())
        verdict = evaluate_finalisation(merged)
        self.assertTrue(verdict.sealed, verdict.as_dict())

    def test_unsigned_attestation_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            merge_attestation(self.record, self.attestation(signature=None))

    def test_attestation_cannot_override_an_inspected_result(self) -> None:
        # The whole point: a dishonest factory must not be able to paper over
        # what the probe actually observed.
        payload = self.attestation()
        payload["checks"]["shell-history-cleared"] = PASS
        with self.assertRaises(ValueError) as error:
            merge_attestation(self.record, payload)
        self.assertIn("may not override checks settled by inspection", str(error.exception))

    def test_attestation_naming_an_unknown_check_is_refused(self) -> None:
        payload = self.attestation()
        payload["checks"]["invented-check"] = PASS
        with self.assertRaises(ValueError):
            merge_attestation(self.record, payload)

    def test_failing_attestation_still_blocks(self) -> None:
        payload = self.attestation()
        payload["checks"]["recovery-verified"] = FAIL
        verdict = evaluate_finalisation(merge_attestation(self.record, payload))
        self.assertFalse(verdict.sealed)
        self.assertIn("recovery-verified", verdict.failures)

    def test_partial_attestation_leaves_the_rest_unknown(self) -> None:
        payload = self.attestation(checks={"tpm-state-recorded": PASS})
        verdict = evaluate_finalisation(merge_attestation(self.record, payload))
        self.assertFalse(verdict.sealed)
        self.assertIn("recovery-verified", verdict.unknown)


if __name__ == "__main__":
    unittest.main()
