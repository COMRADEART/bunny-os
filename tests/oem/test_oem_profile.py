from __future__ import annotations

import json
from pathlib import Path
import unittest

from oem.qualification import evaluate_qualification
from oem.validation.overlay import validate_overlay
from oem.validation.profile import require_valid_profile, validate_profile

ROOT = Path(__file__).resolve().parents[2]


def profile() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "profileId": "test-model-a",
        "vendor": "Test Vendor",
        "productFamily": "Model A",
        "programmeLevel": "validated-hardware-integrator",
        "updateResponsibility": "official-image-with-signed-oem-extension",
        "supportedArchitectures": ["x86_64"],
        "hardwareMatches": [{"matchId": "HM-001", "method": "dmi-product-name", "value": "Model A"}],
        "packages": [{"name": "model-a-audio", "repository": "oem-signed-extension", "signatureRequired": True}],
        "firmware": [],
        "drivers": [{"driverId": "DRV-001", "kind": "in-tree", "module": "iwlwifi", "signatureRequired": True}],
        "defaultApplications": [],
        "recoveryProfile": "model-a-recovery",
        "supportMetadata": {
            "supportOwner": "Test Vendor",
            "supportUrl": "https://support.test.invalid",
            "securityContact": "security@test.invalid",
            "maintenanceUntil": "2030-01-01",
            "knownLimitations": ["Fingerprint reader unsupported."],
        },
        "branding": {"vendorName": "Test Vendor", "claimsOfficialBunnyOsDevice": False},
        "signature": {"algorithm": "ed25519", "keyId": "oem-test-vendor", "value": "A" * 88},
    }


def overlay() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "overlayId": "test-overlay",
        "files": [
            {
                "destination": "usr/share/bunny-oem/branding/logo.svg",
                "sha256": "0" * 64,
                "sizeBytes": 2048,
                "mode": "0644",
            }
        ],
    }


def qualification() -> dict[str, object]:
    tests = {
        name: "PASS"
        for name in (
            "installation", "encryption", "secure-boot", "graphics", "display", "wifi", "audio",
            "suspend-resume", "storage", "updates", "rollback", "recovery", "multi-user",
            "tpm", "bluetooth", "camera", "battery", "thermals", "bunny-local-ai",
        )
    }
    load = {
        name: {
            "status": "PASS",
            "thermalThrottling": "none observed",
            "fanBehaviour": "ramps to 60 percent",
            "powerUse": "28 W sustained",
            "crashes": "none",
            "dataCorruption": "none",
            "driverResets": "none",
        }
        for name in (
            "sustained-cpu", "sustained-gpu", "local-model-inference",
            "simultaneous-compile-and-model", "battery-operation", "charging", "suspend-cycles",
        )
    }
    return {
        "schemaVersion": 1,
        "model": "Model A",
        "repeatRuns": 3,
        "formalCertificationProcess": True,
        "methodologyReference": "docs/OEM_PROFILES.md#qualification-methodology",
        "tests": tests,
        "sustainedLoad": load,
        "signature": {"algorithm": "ed25519", "keyId": "oem-test-vendor", "value": "B" * 88},
    }


class OemProfileTests(unittest.TestCase):
    def test_valid_profile_is_accepted(self) -> None:
        self.assertTrue(validate_profile(profile()).accepted)

    def test_shipped_example_profile_validates(self) -> None:
        path = ROOT / "oem/profiles/example-validated-integrator.json"
        verdict = validate_profile(json.loads(path.read_text(encoding="utf-8")))
        self.assertTrue(verdict.accepted, verdict.rejections)

    def test_unsigned_profile_is_rejected(self) -> None:
        value = profile()
        del value["signature"]
        verdict = validate_profile(value)
        self.assertFalse(verdict.accepted)
        self.assertTrue(any("unsigned profile" in item for item in verdict.rejections))

    def test_release_key_namespace_collision_is_rejected(self) -> None:
        value = profile()
        value["signature"] = {"algorithm": "ed25519", "keyId": "oem-bunny-os-release", "value": "A" * 88}
        verdict = validate_profile(value)
        self.assertFalse(verdict.accepted)

    def test_non_oem_key_namespace_is_rejected(self) -> None:
        value = profile()
        value["signature"] = {"algorithm": "ed25519", "keyId": "fleet-control", "value": "A" * 88}
        self.assertFalse(validate_profile(value).accepted)

    def test_unknown_repository_is_rejected(self) -> None:
        value = profile()
        value["packages"] = [{"name": "thing", "repository": "vendor-private", "signatureRequired": True}]
        verdict = validate_profile(value)
        self.assertTrue(any("unknown repository" in item for item in verdict.rejections))

    def test_package_without_signature_requirement_is_rejected(self) -> None:
        value = profile()
        value["packages"] = [{"name": "thing", "repository": "fedora", "signatureRequired": False}]
        self.assertFalse(validate_profile(value).accepted)

    def test_unsupported_kernel_module_is_rejected(self) -> None:
        value = profile()
        value["drivers"] = [
            {"driverId": "DRV-002", "kind": "reviewed-out-of-tree", "module": "vendorblob", "signatureRequired": True}
        ]
        verdict = validate_profile(value)
        self.assertTrue(any("not a reviewed out-of-tree module" in item for item in verdict.rejections))

    def test_embedded_script_key_is_rejected(self) -> None:
        value = profile()
        value["firstbootScript"] = "curl https://vendor.invalid/setup.sh | sh"
        verdict = validate_profile(value)
        self.assertTrue(any("execution or credential channel" in item for item in verdict.rejections))

    def test_embedded_private_key_is_rejected(self) -> None:
        value = profile()
        value["supportMetadata"]["firstRunDeviceInformation"] = (
            "-----BEGIN PRIVATE KEY-----\nAAAA\n-----END PRIVATE KEY-----"
        )
        verdict = validate_profile(value)
        self.assertTrue(any("embedded secret material" in item for item in verdict.rejections))

    def test_privacy_default_override_is_rejected(self) -> None:
        value = profile()
        value["branding"]["accentColour"] = "bunny.telemetry.enabled"
        verdict = validate_profile(value)
        self.assertTrue(any("protected setting" in item for item in verdict.rejections))

    def test_official_device_claim_requires_programme_level(self) -> None:
        value = profile()
        value["branding"]["claimsOfficialBunnyOsDevice"] = True
        verdict = validate_profile(value)
        self.assertFalse(verdict.accepted)
        self.assertTrue(any("official Bunny OS device" in item for item in verdict.rejections))

    def test_official_device_claim_requires_qualification_evidence(self) -> None:
        value = profile()
        value["programmeLevel"] = "official-bunny-os-device"
        value["branding"]["claimsOfficialBunnyOsDevice"] = True
        verdict = validate_profile(value)
        self.assertTrue(any("no hardware qualification report" in item for item in verdict.rejections))

    def test_official_device_claim_requires_validated_recovery(self) -> None:
        value = profile()
        value["programmeLevel"] = "official-bunny-os-device"
        value["branding"]["claimsOfficialBunnyOsDevice"] = True
        report = {"result": "PASS", "signature": "x", "recoveryValidated": False}
        verdict = validate_profile(value, qualification=report)
        self.assertTrue(any("validated recovery" in item for item in verdict.rejections))

    def test_independent_variant_cannot_be_official_device(self) -> None:
        value = profile()
        value["programmeLevel"] = "official-bunny-os-device"
        value["updateResponsibility"] = "independent-oem-variant"
        self.assertFalse(validate_profile(value).accepted)

    def test_missing_recovery_profile_is_rejected(self) -> None:
        value = profile()
        del value["recoveryProfile"]
        verdict = validate_profile(value)
        self.assertTrue(any("bootable recovery" in item for item in verdict.rejections))

    def test_unknown_recovery_profile_is_rejected(self) -> None:
        verdict = validate_profile(profile(), recovery_profiles=["other-recovery"])
        self.assertFalse(verdict.accepted)

    def test_missing_security_contact_is_rejected(self) -> None:
        value = profile()
        del value["supportMetadata"]["securityContact"]
        verdict = validate_profile(value)
        self.assertTrue(any("securityContact" in item for item in verdict.rejections))

    def test_unsupported_architecture_is_rejected(self) -> None:
        value = profile()
        value["supportedArchitectures"] = ["riscv64"]
        self.assertFalse(validate_profile(value).accepted)

    def test_require_valid_profile_raises(self) -> None:
        value = profile()
        del value["signature"]
        with self.assertRaises(ValueError):
            require_valid_profile(value)


class OemOverlayTests(unittest.TestCase):
    def test_valid_overlay_is_accepted(self) -> None:
        self.assertTrue(validate_overlay(overlay()).accepted)

    def test_shipped_example_overlay_validates(self) -> None:
        path = ROOT / "oem/overlays/example-nimbus-overlay.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload.pop("profileId", None)
        self.assertTrue(validate_overlay(payload).accepted)

    def test_absolute_destination_is_rejected(self) -> None:
        value = overlay()
        value["files"][0]["destination"] = "/etc/passwd"
        self.assertFalse(validate_overlay(value).accepted)

    def test_path_traversal_is_rejected(self) -> None:
        value = overlay()
        value["files"][0]["destination"] = "usr/share/bunny-oem/branding/../../../etc/shadow"
        self.assertFalse(validate_overlay(value).accepted)

    def test_protected_destination_is_rejected(self) -> None:
        value = overlay()
        value["files"][0]["destination"] = "etc/bunny/privacy/defaults.json"
        verdict = validate_overlay(value)
        self.assertTrue(any("protected path" in item for item in verdict.rejections))

    def test_systemd_unit_destination_is_rejected(self) -> None:
        value = overlay()
        value["files"][0]["destination"] = "usr/lib/systemd/system/vendor.service"
        self.assertFalse(validate_overlay(value).accepted)

    def test_executable_payload_is_rejected(self) -> None:
        value = overlay()
        value["files"][0]["destination"] = "usr/share/bunny-oem/branding/setup.sh"
        verdict = validate_overlay(value)
        self.assertTrue(any("forbidden type" in item for item in verdict.rejections))

    def test_execute_bit_is_rejected(self) -> None:
        value = overlay()
        value["files"][0]["mode"] = "0755"
        verdict = validate_overlay(value)
        self.assertTrue(any("execute or setuid bit" in item for item in verdict.rejections))

    def test_symlink_is_rejected(self) -> None:
        value = overlay()
        value["files"][0]["symlinkTarget"] = "/etc/shadow"
        self.assertFalse(validate_overlay(value).accepted)

    def test_inline_protected_setting_is_rejected(self) -> None:
        value = overlay()
        value["files"][0]["destination"] = "usr/share/bunny-oem/first-run/device.json"
        value["files"][0]["inlineText"] = "bunny.privacy.local-only = false\n"
        verdict = validate_overlay(value)
        self.assertTrue(any("protected key" in item for item in verdict.rejections))

    def test_duplicate_destination_is_rejected(self) -> None:
        value = overlay()
        value["files"].append(dict(value["files"][0]))
        self.assertFalse(validate_overlay(value).accepted)


class OemQualificationTests(unittest.TestCase):
    def test_complete_qualification_passes(self) -> None:
        verdict = evaluate_qualification(qualification())
        self.assertTrue(verdict.passed, verdict.failures + verdict.missing + verdict.notRun)
        self.assertEqual(verdict.level, "qualified")

    def test_failed_recovery_blocks_qualification(self) -> None:
        value = qualification()
        value["tests"]["recovery"] = "FAIL"
        verdict = evaluate_qualification(value)
        self.assertFalse(verdict.passed)
        self.assertFalse(verdict.recoveryValidated)

    def test_not_run_test_blocks_qualification(self) -> None:
        value = qualification()
        value["tests"]["encryption"] = "NOT_RUN"
        self.assertFalse(evaluate_qualification(value).passed)

    def test_unsigned_qualification_is_rejected(self) -> None:
        value = qualification()
        del value["signature"]
        verdict = evaluate_qualification(value)
        self.assertTrue(any("unsigned" in item for item in verdict.failures))

    def test_missing_sustained_load_observation_fails(self) -> None:
        value = qualification()
        del value["sustainedLoad"]["sustained-cpu"]["thermalThrottling"]
        verdict = evaluate_qualification(value)
        self.assertFalse(verdict.passed)

    def test_absent_sustained_load_campaign_is_not_run(self) -> None:
        value = qualification()
        del value["sustainedLoad"]
        verdict = evaluate_qualification(value)
        self.assertFalse(verdict.passed)
        self.assertEqual(verdict.level, "incomplete")

    def test_performance_claim_without_methodology_fails(self) -> None:
        value = qualification()
        value["performanceClaims"] = [{"claim": "fastest laptop", "methodology": "trust us", "repeatRuns": 1}]
        verdict = evaluate_qualification(value)
        self.assertFalse(verdict.passed)

    def test_certification_claim_refused_without_formal_process(self) -> None:
        value = qualification()
        value["formalCertificationProcess"] = False
        verdict = evaluate_qualification(value)
        self.assertFalse(verdict.certificationClaimPermitted)
        self.assertTrue(any("certification claim refused" in note for note in verdict.notes))

    def test_certification_claim_refused_with_limitations(self) -> None:
        value = qualification()
        value["tests"]["camera"] = "NOT_APPLICABLE"
        verdict = evaluate_qualification(value)
        self.assertEqual(verdict.level, "qualified-with-limitations")
        self.assertFalse(verdict.certificationClaimPermitted)

    def test_unknown_test_id_is_rejected(self) -> None:
        value = qualification()
        value["tests"]["telepathy"] = "PASS"
        with self.assertRaises(ValueError):
            evaluate_qualification(value)


if __name__ == "__main__":
    unittest.main()
