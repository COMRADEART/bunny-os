# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Phase 9 intake is append-only, and this is what enforces it.

The ledger (``qualification/phase9/intake/LEDGER.json``) admits evidence
through exactly one mechanism — ``qualification/phase9/tools/intake.py
register`` — which pins every ingested byte and seals every entry. The three
§19 properties are executed here on every run, against constructed trees, so
the failure branches exist before any real evidence does:

* an accepted record modified → FAIL,
* a rejected record modified → FAIL,
* a new intake added through the approved append mechanism → PASS.

Deliberately absent: an assertion that the ledger is empty. Registering real
evidence is the designed forward path; a test that fails when the mechanism
is used as intended would punish the property for getting exercised. The
report records "zero intakes" as the current state; this file enforces
structure, not emptiness.

The tool is imported by explicit file location, so the checkout under test
is the code under test — no installed tree can shadow it.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

_ROOT = Path(__file__).resolve().parents[2]
_TOOL = _ROOT / "qualification" / "phase9" / "tools" / "intake.py"
_LEDGER = _ROOT / "qualification" / "phase9" / "intake" / "LEDGER.json"

_ISO = "823d50caba35afe72452768affd5f6fa0ac8cfc13c164f0e1bc909fa887ab421"
_IMAGE = "sha256:c87a6616008ce34f97840f63814e08fdb33574b52202fbb4841b7f5aa7f8562d"
#: A well-formed digest that is not any subject-artifact digest — the
#: brief's "valid-looking document about e501218f…" case, constructed.
_FOREIGN = "e501218f" * 8


def _load_tool():
    spec = importlib.util.spec_from_file_location("phase9_intake", _TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


intake = _load_tool()


def _control_review_record(**overrides) -> dict:
    """A complete security-review record for control trees only.

    Constructed fixture: it exercises the machinery in a scratch tree and
    never approaches the real ledger — nothing here is external evidence.
    """
    record = {
        "reviewer": "Constructed Control Reviewer",
        "organisation": "negative-control fixture",
        "scope": "constructed fixture exercising the intake machinery",
        "date": "2026-08-18",
        "artifactDigest": _IMAGE,
        "findings": [],
        "disposition": "MORE_EVIDENCE_REQUIRED",
    }
    record.update(overrides)
    return record


class _ScratchTree(unittest.TestCase):
    """A constructed repo root with an empty ledger, per test."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="phase9-intake-control-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.intake_root = self.tmp / "qualification" / "phase9" / "intake"
        for source in intake.SOURCES:
            (self.intake_root / source).mkdir(parents=True)
        real = json.loads(_LEDGER.read_text(encoding="utf-8"))
        self.ledger_path = self.intake_root / "LEDGER.json"
        intake.dump_ledger(self.ledger_path, {
            "schemaVersion": 1,
            "appendMechanism": "qualification/phase9/tools/intake.py",
            "sources": list(intake.SOURCES),
            "statusVocabulary": list(intake.STATUSES),
            "sealAlgorithm": real["sealAlgorithm"],
            "subjectArtifact": real["subjectArtifact"],
            "entries": [],
        })
        self.staging = self.tmp / "staging"
        self.staging.mkdir()

    def _stage(self, name: str, payload) -> Path:
        path = self.staging / name
        if isinstance(payload, bytes):
            path.write_bytes(payload)
        else:
            path.write_text(
                json.dumps(payload, indent=1, sort_keys=True) + "\n",
                encoding="utf-8", newline="\n",
            )
        return path

    def _register(self, source: str, record, attachments=(), revises=None):
        return intake.register(
            self.ledger_path, source, self._stage("record-src.json", record),
            [self._stage(name, blob) for name, blob in attachments],
            "2026-08-18", "control fixture", revises,
        )

    def _verify(self) -> dict:
        return intake.verify_intake(
            self.intake_root, intake.load_ledger(self.ledger_path)
        )


class CommittedIntakeTree(unittest.TestCase):
    """The real tree: seals, pins, orphans, and the frozen identity."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.ledger = json.loads(_LEDGER.read_text(encoding="utf-8"))

    def test_the_ledger_binds_to_the_frozen_artifact(self) -> None:
        artifact = self.ledger["subjectArtifact"]
        self.assertEqual(artifact["identifier"], "e906a48793d7")
        self.assertEqual(artifact["imageDigest"], _IMAGE)
        self.assertEqual(artifact["isoSha256"], _ISO)
        self.assertEqual(artifact["signingStatus"], "UNSIGNED")
        self.assertTrue(artifact["frozen"])

    def test_the_vocabularies_are_closed_and_match_the_tool(self) -> None:
        self.assertEqual(tuple(self.ledger["sources"]), intake.SOURCES)
        self.assertEqual(tuple(self.ledger["statusVocabulary"]), intake.STATUSES)
        self.assertEqual(
            intake.STATUSES,
            ("ACCEPTED", "REJECTED", "INCOMPLETE", "ARTIFACT_MISMATCH",
             "UNVERIFIABLE", "SUPERSEDED"),
        )

    def test_the_committed_tree_verifies_clean(self) -> None:
        issues = intake.verify_intake(_LEDGER.parent, self.ledger)
        self.assertEqual(issues, {})

    def test_every_stored_entry_would_be_reportable(self) -> None:
        """Whatever lands later: sealed, sourced, statused — enforced now."""
        for entry in self.ledger["entries"]:
            self.assertEqual(intake.seal_entry(entry), entry["seal"])
            self.assertIn(entry["source"], intake.SOURCES)
            self.assertIn(entry["status"], intake.STATUSES)
            self.assertNotEqual(entry["status"], "SUPERSEDED",
                                "SUPERSEDED is derived, never stored")


class AppendOnlyControls(_ScratchTree):
    """The §19 immutability properties, failure branches executed."""

    def test_a_new_intake_through_the_mechanism_passes(self) -> None:
        entry = self._register("security-review", _control_review_record())
        self.assertEqual(entry["status"], "ACCEPTED")
        self.assertEqual(self._verify(), {})
        second = self._register(
            "signing",
            {"category": "SIGNING DRILL", "artifactDigest": _IMAGE,
             "signatureIdentifier": "control", "signerIdentity": "control",
             "signerAuthority": "control", "signingTimestamp": "2026-08-18",
             "verificationResult": "control", "verificationRunBy": "control"},
        )
        self.assertEqual(second["status"], "REJECTED")
        self.assertEqual(self._verify(), {},
                         "an appended rejection is a valid ledger state")

    def test_a_modified_accepted_record_fails(self) -> None:
        entry = self._register("security-review", _control_review_record())
        self.assertEqual(entry["status"], "ACCEPTED")
        (path,) = [
            self.tmp / name for name in entry["files"]
            if name.endswith("record.json")
        ]
        path.write_bytes(path.read_bytes() + b" ")
        issues = self._verify()
        self.assertEqual(list(issues), ["fileChanged"])

    def test_a_modified_rejected_record_fails(self) -> None:
        entry = self._register(
            "signing",
            {"category": "SIGNING DRILL", "artifactDigest": _IMAGE,
             "signatureIdentifier": "control", "signerIdentity": "control",
             "signerAuthority": "control", "signingTimestamp": "2026-08-18",
             "verificationResult": "control", "verificationRunBy": "control"},
        )
        self.assertEqual(entry["status"], "REJECTED")
        self.assertTrue(entry["files"], "the rejected evidence is preserved")
        (path,) = [
            self.tmp / name for name in entry["files"]
            if name.endswith("record.json")
        ]
        path.write_bytes(path.read_bytes() + b" ")
        issues = self._verify()
        self.assertEqual(list(issues), ["fileChanged"],
                         "rejected evidence is as immutable as accepted")

    def test_a_hand_edited_entry_breaks_its_seal(self) -> None:
        self._register("security-review", _control_review_record())
        ledger = json.loads(self.ledger_path.read_text(encoding="utf-8"))
        ledger["entries"][0]["status"] = "REJECTED"
        self.ledger_path.write_text(
            json.dumps(ledger, indent=1, sort_keys=True) + "\n",
            encoding="utf-8", newline="\n",
        )
        issues = self._verify()
        self.assertIn("sealBroken", issues)

    def test_a_deleted_evidence_file_fails(self) -> None:
        entry = self._register("security-review", _control_review_record())
        (path,) = [
            self.tmp / name for name in entry["files"]
            if name.endswith("record.json")
        ]
        path.unlink()
        self.assertIn("fileMissing", self._verify())

    def test_an_unregistered_file_fails(self) -> None:
        self._register("security-review", _control_review_record())
        stray = self.intake_root / "security-review" / "stray.log"
        stray.write_bytes(b"nobody registered this\n")
        issues = self._verify()
        self.assertEqual(issues.get("unregistered"),
                         ["qualification/phase9/intake/security-review/stray.log"])

    def test_register_refuses_a_tampered_ledger(self) -> None:
        self._register("security-review", _control_review_record())
        ledger = json.loads(self.ledger_path.read_text(encoding="utf-8"))
        ledger["entries"][0]["statusReason"] = "reworded after the fact"
        self.ledger_path.write_text(
            json.dumps(ledger, indent=1, sort_keys=True) + "\n",
            encoding="utf-8", newline="\n",
        )
        with self.assertRaises(SystemExit):
            self._register("security-review", _control_review_record())

    def test_a_revision_preserves_the_original(self) -> None:
        first = self._register(
            "security-review", _control_review_record(disposition="")
        )
        self.assertEqual(first["status"], "INCOMPLETE")
        revision = self._register(
            "security-review", _control_review_record(),
            revises=first["intakeId"],
        )
        self.assertEqual(revision["intakeId"], "INTAKE-001-R1")
        ledger = intake.load_ledger(self.ledger_path)
        self.assertEqual([e["intakeId"] for e in ledger["entries"]],
                         ["INTAKE-001", "INTAKE-001-R1"],
                         "both submissions are preserved")
        stored = {e["intakeId"]: e["status"] for e in ledger["entries"]}
        self.assertEqual(stored["INTAKE-001"], "INCOMPLETE",
                         "the stored record never changes")
        effective = intake.effective_statuses(ledger)
        self.assertEqual(effective["INTAKE-001"], "SUPERSEDED")
        self.assertEqual(effective["INTAKE-001-R1"], "ACCEPTED")
        self.assertEqual(self._verify(), {})


class ValidationControls(_ScratchTree):
    """The §3–§11 verdicts, executed against constructed submissions."""

    def test_private_key_material_is_never_ingested(self) -> None:
        entry = self._register(
            "signing",
            {"category": "PRODUCTION ARTIFACT SIGNED", "artifactDigest": _IMAGE},
            attachments=[
                ("leaked.pem",
                 b"-----BEGIN OPENSSH PRIVATE KEY-----\ncontrol bytes\n"
                 b"-----END OPENSSH PRIVATE KEY-----\n"),
            ],
        )
        self.assertEqual(entry["status"], "REJECTED")
        self.assertEqual(entry["files"], {}, "nothing was ingested")
        marker = b"PRIVATE KEY"
        on_disk = [
            path for path in self.intake_root.rglob("*")
            if path.is_file() and marker in path.read_bytes()
        ]
        self.assertEqual(on_disk, [], "the key bytes never touched the tree")
        self.assertEqual(self._verify(), {})

    def test_a_foreign_digest_is_artifact_mismatch(self) -> None:
        entry = self._register(
            "security-review", _control_review_record(artifactDigest=_FOREIGN)
        )
        self.assertEqual(entry["status"], "ARTIFACT_MISMATCH")
        self.assertFalse(entry["gateEligible"])
        self.assertIn(_FOREIGN, entry["statusReason"])

    def test_a_signing_drill_is_rejected_for_the_production_gate(self) -> None:
        entry = self._register(
            "signing",
            {"category": "SIGNING DRILL", "artifactDigest": _IMAGE,
             "signatureIdentifier": "drill", "signerIdentity": "drill",
             "signerAuthority": "drill", "signingTimestamp": "2026-08-18",
             "verificationResult": "drill", "verificationRunBy": "drill"},
        )
        self.assertEqual(entry["status"], "REJECTED")
        self.assertIn("drill", entry["statusReason"])

    def test_an_approval_naming_only_a_commit_is_incomplete(self) -> None:
        entry = self._register(
            "second-approval",
            {"scope": "distribute the ISO to the controlled Alpha cohort",
             "commit": "e906a48793d74544b39c14cc3e35e0654f5311e2",
             "firstApprover": {"name": "Control A", "role": "owner",
                               "date": "2026-08-18", "decision": "APPROVE"},
             "secondApprover": {"name": "Control B", "role": "second",
                                "date": "2026-08-18", "decision": "APPROVE"}},
        )
        self.assertEqual(entry["status"], "INCOMPLETE")
        self.assertIn("recomputedDigest", entry["statusReason"])

    def test_one_person_approving_twice_is_rejected(self) -> None:
        entry = self._register(
            "second-approval",
            {"scope": "distribute the ISO",
             "firstApprover": {"name": "Control A", "role": "owner",
                               "date": "2026-08-18", "decision": "APPROVE",
                               "recomputedDigest": _ISO},
             "secondApprover": {"name": "Control A", "role": "still the owner",
                                "date": "2026-08-18", "decision": "APPROVE",
                                "recomputedDigest": _ISO}},
        )
        self.assertEqual(entry["status"], "REJECTED")

    def test_a_complete_two_person_approval_is_gate_eligible(self) -> None:
        entry = self._register(
            "second-approval",
            {"scope": "distribute the ISO to the controlled Alpha cohort",
             "firstApprover": {"name": "Control A", "role": "owner",
                               "date": "2026-08-18", "decision": "APPROVE",
                               "recomputedDigest": _ISO},
             "secondApprover": {"name": "Control B", "role": "second approver",
                                "date": "2026-08-18", "decision": "APPROVE",
                                "recomputedDigest": _ISO}},
        )
        self.assertEqual(entry["status"], "ACCEPTED")
        self.assertTrue(entry["gateEligible"])

    def test_an_unbound_alpha_report_is_preserved_not_eligible(self) -> None:
        entry = self._register(
            "alpha-feedback",
            {"testerId": "T-001", "journey": "A",
             "environment": {"kind": "vm", "detail": "control"},
             "date": "2026-08-18", "steps": [], "measured": [],
             "userReported": [{"aboutStep": "boot",
                               "impression": "the tester's words, kept"}],
             "findings": []},
        )
        self.assertEqual(entry["status"], "ACCEPTED",
                         "unbound user evidence is preserved, not discarded")
        self.assertEqual(entry["binding"], "USER_EVIDENCE_UNBOUND")
        self.assertFalse(entry["gateEligible"],
                         "unbound evidence moves no artifact-specific gate")

    def test_a_bound_alpha_report_is_gate_eligible(self) -> None:
        entry = self._register(
            "alpha-feedback",
            {"testerId": "T-001", "artifactDigest": _ISO, "journey": "A",
             "environment": {"kind": "vm", "detail": "control"},
             "date": "2026-08-18", "steps": [], "measured": [],
             "userReported": [], "findings": []},
        )
        self.assertEqual(entry["status"], "ACCEPTED")
        self.assertEqual(entry["binding"], "BOUND")
        self.assertTrue(entry["gateEligible"])

    def test_a_hardware_pass_without_evidence_is_incomplete(self) -> None:
        entry = self._register(
            "hardware",
            {"hwId": "HW-001", "operator": "control operator",
             "date": "2026-08-18", "artifactDigest": _ISO,
             "machine": {"manufacturer": "c", "model": "c", "cpu": "c",
                         "ram": "c", "gpu": "c", "storage": "c",
                         "firmwareMode": "UEFI", "secureBootState": "enabled"},
             "results": {"boot-installation-media": {"status": "PASS"}}},
        )
        self.assertEqual(entry["status"], "INCOMPLETE")
        self.assertIn("PASS requires an evidence reference",
                      entry["statusReason"])

    def test_a_graded_hardware_mix_is_a_valid_result(self) -> None:
        """boot PASS + microphone FAIL + native-3D NOT_SUPPORTED is useful,
        acceptable evidence — dimensions never collapse into machine PASS."""
        entry = self._register(
            "hardware",
            {"hwId": "HW-001", "operator": "control operator",
             "date": "2026-08-18", "artifactDigest": _ISO,
             "machine": {"manufacturer": "c", "model": "c", "cpu": "c",
                         "ram": "c", "gpu": "c", "storage": "c",
                         "firmwareMode": "UEFI", "secureBootState": "enabled"},
             "results": {
                 "boot-installation-media": {"status": "PASS",
                                             "evidence": "serial.log"},
                 "voice-microphone": {"status": "FAIL",
                                      "evidence": "journal.txt"},
                 "companion-3d-native": {"status": "NOT_SUPPORTED",
                                         "evidence": "machine.gpu"},
                 "companion-3d-fallback": {"status": "PASS",
                                           "evidence": "frames.log"},
             }},
        )
        self.assertEqual(entry["status"], "ACCEPTED")
        self.assertTrue(entry["gateEligible"])

    def test_an_unparseable_record_is_unverifiable_but_kept(self) -> None:
        entry = self._register("security-review", b"not json at all\n")
        self.assertEqual(entry["status"], "UNVERIFIABLE")
        self.assertTrue(entry["files"], "the bytes are preserved verbatim")
        self.assertEqual(self._verify(), {})

    def test_a_claimed_attachment_digest_is_recomputed(self) -> None:
        blob = b"the attached evidence\n"
        entry = self._register(
            "security-review",
            _control_review_record(attachmentDigests={"notes.txt": "0" * 64}),
            attachments=[("notes.txt", blob)],
        )
        self.assertEqual(entry["status"], "UNVERIFIABLE")
        self.assertIn("claimed digests do not match",
                      entry["validation"]["integrity"])

    def _register(self, source, record, attachments=(), revises=None):
        if isinstance(record, bytes):
            return intake.register(
                self.ledger_path, source, self._stage("record-src.json", record),
                [self._stage(n, b) for n, b in attachments],
                "2026-08-18", "control fixture", revises,
            )
        return super()._register(source, record, attachments, revises)


if __name__ == "__main__":
    unittest.main()
