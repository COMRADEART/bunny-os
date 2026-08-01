# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The twenty TPM-evidence frauds, each refused by structure.

Every test here names a way TPM boot evidence could lie — a no-TPM log
imported as TPM evidence, CRB relabelled TIS, reused state called fresh, a
timeout called a reset, a VM called hardware — and proves the refusal fires.
The refusals live in three layers: record↔context binding
(``verify_record_binding``), record↔invocation consistency
(``verify_internal_consistency``), and aggregation rules inside
``import_tpm_results`` (repetition counts, paired control, cell shape,
physical-TPM immovability), which are exercised end-to-end against synthetic
evidence trees through the real CLI.

The companion mutation battery in ``test_mutation.py`` proves these checks
are load-bearing rather than tautological.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "qualification/tpm/scripts"
sys.path.insert(0, str(SCRIPTS))

from tpm_context import (  # noqa: E402
    TpmContext,
    verify_internal_consistency,
    verify_record_binding,
)

COMMIT = "b9c317d35b85aa082904ecd40c4a54c81aded99a"

CONTEXT = TpmContext(
    schemaVersion=1,
    scenarioVersion="tpmq-1",
    sourceCommit=COMMIT,
    sourceArchiveDigest="1" * 64,
    installationArtifactDigest="2" * 64,
    installationArtifactName="bunny.qcow2",
    qemuDigest="3" * 64,
    qemuVersion="QEMU 10.2.2",
    ovmfCodeDigest="4" * 64,
    ovmfCodePath="/nonexistent/OVMF_CODE.qcow2",
    ovmfVarsTemplateDigest="5" * 64,
    ovmfVarsTemplatePath="/nonexistent/OVMF_VARS.qcow2",
    swtpmDigest="6" * 64,
    swtpmVersion="0.10.1",
    libtpmsVersion="0.10.2",
    machineType="pc-q35-10.2",
    cpuMode="host",
)


def record(**overrides: object) -> dict[str, object]:
    """A record that binds and coheres cleanly, so each test tampers with
    exactly one thing."""
    document: dict[str, object] = {
        "schemaVersion": 1,
        "evidenceId": "TPMQ-20260801-crb-fresh-cold-001",
        "sourceCommit": COMMIT,
        "sourceArchiveDigest": "1" * 64,
        "installationArtifactDigest": "2" * 64,
        "qemuDigest": "3" * 64,
        "ovmfCodeDigest": "4" * 64,
        "ovmfVarsTemplateDigest": "5" * 64,
        "swtpmDigest": "6" * 64,
        "scenarioVersion": "tpmq-1",
        "environment": "qemu-kvm",
        "acceleration": "kvm",
        "machineType": "pc-q35-10.2",
        "cpuModel": "host",
        "diagnostic": False,
        "diskAttached": True,
        "ovmfVarsState": "fresh",
        "ovmfVarsSourceDigest": "5" * 64,
        "tpmInterface": "crb",
        "tpmState": "fresh",
        "secureBootState": "disabled",
        "smmState": "off",
        "bootType": "cold",
        "expectation": "target",
        "guestResetCount": 1,
        "resetClassification": "BOOTLOADER_REBOOT_COMMAND",
        "classificationBasis": ["QMP SHUTDOWN: guest-reset"],
        "stagesReached": ["grub-menu", "multi-user", "graphical", "health-check"],
        "lastStage": "health-check",
        "result": "PASS",
        "startedAt": "2026-08-01T20:00:00.000Z",
        "completedAt": "2026-08-01T20:01:00.000Z",
        "operator": "allamsettiraviteja2009",
        "limitations": [],
        "evidenceFiles": [],
    }
    document.update(overrides)
    return document


ARGV_CRB = ["qemu-system-x86_64", "-machine", "pc-q35-10.2,accel=kvm",
            "-device", "tpm-crb,tpmdev=tpm0"]
ARGV_TIS = ["qemu-system-x86_64", "-machine", "pc-q35-10.2,accel=kvm",
            "-device", "tpm-tis,tpmdev=tpm0"]
ARGV_NONE = ["qemu-system-x86_64", "-machine", "pc-q35-10.2,accel=kvm"]
ARGV_TCG = ["qemu-system-x86_64", "-machine", "pc-q35-10.2,accel=tcg",
            "-device", "tpm-crb,tpmdev=tpm0"]


class Binding(unittest.TestCase):
    def test_a_faithful_record_binds_and_coheres(self) -> None:
        # The baseline: every refusal below must come from the one field the
        # test tampers with, not from a fixture that never bound at all.
        self.assertEqual(verify_record_binding(record(), CONTEXT), [])
        self.assertEqual(verify_internal_consistency(record(), ARGV_CRB), [])

    def test_10_a_different_disk_digest_is_stale(self) -> None:
        reasons = verify_record_binding(
            record(installationArtifactDigest="e" * 64), CONTEXT)
        self.assertTrue(any("does not transfer" in r for r in reasons), reasons)

    def test_11_changed_ovmf_code_with_unchanged_authority_is_stale(self) -> None:
        # The record was produced under a different firmware image than the
        # context pins; whichever direction the change went, it does not bind.
        reasons = verify_record_binding(record(ovmfCodeDigest="a" * 64), CONTEXT)
        self.assertTrue(any("ovmfCodeDigest" in r for r in reasons), reasons)

    def test_12_changed_swtpm_with_unchanged_authority_is_stale(self) -> None:
        reasons = verify_record_binding(record(swtpmDigest="b" * 64), CONTEXT)
        self.assertTrue(any("swtpmDigest" in r for r in reasons), reasons)

    def test_19_vm_evidence_cannot_claim_physical(self) -> None:
        reasons = verify_record_binding(record(environment="physical"), CONTEXT)
        self.assertTrue(any("physical" in r for r in reasons), reasons)

    def test_5_tcg_labelled_kvm_needs_diagnostic_declaration(self) -> None:
        # Undeclared acceleration drift is refused at binding time too: a
        # record claiming tcg without diagnostic:true does not bind.
        reasons = verify_record_binding(
            record(environment="qemu-tcg", acceleration="tcg"), CONTEXT)
        self.assertTrue(any("diagnostic" in r for r in reasons), reasons)

    def test_scenario_drift_is_a_new_context(self) -> None:
        reasons = verify_record_binding(record(scenarioVersion="tpmq-0"), CONTEXT)
        self.assertTrue(any("scenarioVersion" in r for r in reasons), reasons)


class Consistency(unittest.TestCase):
    def test_1_no_tpm_log_imported_as_tpm_evidence(self) -> None:
        # The fraud: a clean no-TPM boot log filed under a CRB cell. The
        # recorded invocation has no TPM device, and the claim is refused.
        reasons = verify_internal_consistency(record(), ARGV_NONE)
        self.assertTrue(any("no tpm-crb device" in r for r in reasons), reasons)

    def test_1b_tpm_run_labelled_no_tpm(self) -> None:
        reasons = verify_internal_consistency(
            record(tpmInterface="none", tpmState="none"), ARGV_CRB)
        self.assertTrue(any("attached a TPM device" in r for r in reasons), reasons)

    def test_2_crb_evidence_labelled_tis(self) -> None:
        reasons = verify_internal_consistency(record(tpmInterface="tis"), ARGV_CRB)
        self.assertTrue(any("tpm-tis" in r for r in reasons), reasons)

    def test_3_reused_tpm_state_labelled_fresh(self) -> None:
        reasons = verify_internal_consistency(
            record(tpmStateSourceManifest=[{"path": "tpm2-00.permall"}]), ARGV_CRB)
        self.assertTrue(any("reused state labelled fresh" in r for r in reasons),
                        reasons)

    def test_4_reused_ovmf_vars_labelled_fresh(self) -> None:
        reasons = verify_internal_consistency(
            record(ovmfVarsSourceDigest="c" * 64), ARGV_CRB)
        self.assertTrue(any("labelled fresh" in r or "labelled fresh" in r
                            for r in reasons), reasons)

    def test_5_tcg_invocation_labelled_kvm(self) -> None:
        reasons = verify_internal_consistency(record(), ARGV_TCG)
        self.assertTrue(any("TCG evidence relabelled KVM" in r for r in reasons),
                        reasons)

    def test_6_production_secure_boot_cannot_be_claimed(self) -> None:
        reasons = verify_internal_consistency(
            record(secureBootState="production"), ARGV_CRB)
        self.assertTrue(any("production Secure Boot" in r for r in reasons), reasons)

    def test_7_reset_inferred_from_screenshot_alone(self) -> None:
        # The fraud: a screen back at the firmware logo, no QMP event, and a
        # record that says "reset". The classification basis must quote QMP.
        reasons = verify_internal_consistency(
            record(classificationBasis=["screenshot shows firmware logo"]), ARGV_CRB)
        self.assertTrue(any("screenshot" in r for r in reasons), reasons)

    def test_8_harness_timeout_labelled_reset(self) -> None:
        reasons = verify_internal_consistency(
            record(resetClassification="HARNESS_TIMEOUT"), ARGV_CRB)
        self.assertTrue(any("timeout is not a reset" in r for r in reasons), reasons)

    def test_9_qemu_termination_labelled_guest_reset(self) -> None:
        reasons = verify_internal_consistency(
            record(resetClassification="HOST_TERMINATED"), ARGV_CRB)
        self.assertTrue(any("host killed" in r for r in reasons), reasons)

    def test_14_grub_reached_is_not_boot_success(self) -> None:
        reasons = verify_internal_consistency(
            record(stagesReached=["firmware-bds", "grub-menu"],
                   lastStage="grub-menu", guestResetCount=0,
                   resetClassification=None, classificationBasis=None), ARGV_CRB)
        self.assertTrue(any("reaching GRUB is not booting" in r for r in reasons),
                        reasons)

    def test_a_missing_vars_source_digest_is_refused(self) -> None:
        # Omission is the cheapest bypass: with no source digest, the
        # fresh-versus-reused comparison has nothing to compare.
        tampered = record()
        del tampered["ovmfVarsSourceDigest"]
        reasons = verify_internal_consistency(tampered, ARGV_CRB)
        self.assertTrue(any("no source digest" in r for r in reasons), reasons)

    def test_a_reproduction_that_reproduced_nothing_is_refused(self) -> None:
        reasons = verify_internal_consistency(
            record(expectation="reset", guestResetCount=0,
                   resetClassification=None, classificationBasis=None), ARGV_CRB)
        self.assertTrue(any("reproduced nothing" in r for r in reasons), reasons)

    def test_a_stability_run_that_reset_is_refused(self) -> None:
        reasons = verify_internal_consistency(
            record(expectation="stable"), ARGV_CRB)
        self.assertTrue(any("was not stable" in r for r in reasons), reasons)

    def test_a_guest_reboot_with_no_reset_never_rebooted(self) -> None:
        # A session restart re-printing "Reached target Graphical Interface"
        # is indistinguishable in the transcript from a second boot. Only a
        # guest reset proves the machine actually rebooted.
        reasons = verify_internal_consistency(
            record(bootType="guest-reboot", secondBootTargetReached=True,
                   guestResetCount=0, resetClassification=None,
                   classificationBasis=None), ARGV_CRB)
        self.assertTrue(any("never did" in r for r in reasons), reasons)

    def test_a_reset_run_must_record_its_second_boot(self) -> None:
        reasons = verify_internal_consistency(
            record(bootType="qemu-reset"), ARGV_CRB)
        self.assertTrue(any("second boot" in r for r in reasons), reasons)

    def test_15_late_target_cannot_be_omitted_as_timeout(self) -> None:
        reasons = verify_internal_consistency(
            record(resetClassification="HARNESS_TIMEOUT", guestResetCount=0,
                   result="FAIL"), ARGV_CRB)
        self.assertTrue(any("judge the complete log" in r for r in reasons), reasons)


class SchemaShape(unittest.TestCase):
    """Frauds the record schema itself refuses, asserted structurally so the
    tests run without jsonschema and fully when it is available."""

    def setUp(self) -> None:
        path = ROOT / "qualification/tpm/schemas/tpm-boot-record.schema.json"
        self.schema = json.loads(path.read_text(encoding="utf-8"))

    def test_19_environment_enum_has_no_physical(self) -> None:
        self.assertEqual(self.schema["properties"]["environment"]["enum"],
                         ["qemu-kvm", "qemu-tcg"])

    def test_6_secure_boot_free_text_is_recorded_not_trusted(self) -> None:
        # The schema keeps secureBootState a string; the consistency layer
        # constrains it. This test pins the layering so a schema edit cannot
        # silently open a production claim.
        self.assertIn("secureBootState", self.schema["required"])

    def test_13_repetition_lives_in_the_importer_not_the_record(self) -> None:
        # No record field says "this cell is satisfied" — satisfaction is
        # calculated from counted records by the importer alone.
        self.assertNotIn("cellSatisfied", self.schema["properties"])

    def test_tpm_none_cannot_carry_tpm_state(self) -> None:
        conditional = self.schema["allOf"][0]
        self.assertEqual(conditional["then"]["properties"]["tpmState"]["const"],
                         "none")


def run_importer(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "import_tpm_results.py"),
         "--root", str(root), "--dry-run", "--skip-file-hashes"],
        capture_output=True, text=True)


def synthetic_tree(records: list[dict]) -> Path:
    """A temp repo root whose context matches the fixtures above."""
    root = Path(tempfile.mkdtemp(prefix="tpmq-test-"))
    tpm = root / "qualification/tpm"
    (tpm / "evidence").mkdir(parents=True)
    context = {
        "schemaVersion": 1, "scenarioVersion": "tpmq-1",
        "sourceCommit": COMMIT,
        "sourceArchiveDigest": "1" * 64,
        "installationArtifactDigest": "2" * 64,
        "installationArtifactName": "bunny.qcow2",
        "qemuDigest": "3" * 64, "qemuVersion": "QEMU 10.2.2",
        "ovmfCodeDigest": "4" * 64, "ovmfCodePath": "/nonexistent/code",
        "ovmfVarsTemplateDigest": "5" * 64,
        "ovmfVarsTemplatePath": "/nonexistent/vars",
        "swtpmDigest": "6" * 64, "swtpmVersion": "0.10.1",
        "libtpmsVersion": "0.10.2", "machineType": "pc-q35-10.2",
        "cpuMode": "host",
    }
    (tpm / "evidence-context.json").write_text(json.dumps(context), encoding="utf-8")
    for document in records:
        run_dir = tpm / "evidence" / str(document["evidenceId"])
        run_dir.mkdir()
        (run_dir / "record.json").write_text(json.dumps(document), encoding="utf-8")
        interface = document.get("tpmInterface")
        argv = {"crb": ARGV_CRB, "tis": ARGV_TIS}.get(str(interface), ARGV_NONE)
        if document.get("acceleration") == "tcg":
            argv = ARGV_TCG
        (run_dir / "qemu-command.json").write_text(
            json.dumps({"argv": argv}), encoding="utf-8")
    return root


def cell_name(document: dict) -> str:
    return str(document["evidenceId"]).split("-", 2)[2].rsplit("-", 1)[0]


def cell_records(cell: str, count: int, **overrides: object) -> list[dict]:
    documents = []
    for index in range(1, count + 1):
        documents.append(record(
            evidenceId=f"TPMQ-20260801-{cell}-{index:03d}", **overrides))
    return documents


def full_passing_matrix() -> list[dict]:
    reused = {"ovmfVarsState": "reused", "ovmfVarsSourceDigest": "c" * 64,
              "tpmState": "reused",
              "tpmStateSourceManifest": [{"path": "tpm2-00.permall"}],
              "guestResetCount": 0, "resetClassification": None,
              "classificationBasis": None}
    documents = []
    documents += cell_records("no-tpm-cold", 5, tpmInterface="none",
                              tpmState="none", guestResetCount=0,
                              resetClassification=None, classificationBasis=None)
    documents += cell_records("crb-fresh-cold", 5)
    documents += cell_records("tis-fresh-cold", 5, tpmInterface="tis")
    documents += cell_records("crb-reused-cold", 5, **reused)
    documents += cell_records("tis-reused-cold", 5, tpmInterface="tis", **reused)
    documents += cell_records("crb-qemu-reset", 5, bootType="qemu-reset",
                              secondBootTargetReached=True, **reused)
    documents += cell_records("tis-qemu-reset", 5, tpmInterface="tis",
                              bootType="qemu-reset",
                              secondBootTargetReached=True, **reused)
    for document in documents:
        for key in [k for k, v in document.items() if v is None]:
            del document[key]
    return documents


class ImporterAggregation(unittest.TestCase):
    def test_a_full_passing_matrix_passes(self) -> None:
        proc = run_importer(synthetic_tree(full_passing_matrix()))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn('"softwareTpmBoot": "PASS"', proc.stdout.replace("\n", ""),
                      proc.stdout)

    def test_13_one_passing_boot_does_not_satisfy_five(self) -> None:
        documents = full_passing_matrix()
        thinned = [d for d in documents
                   if not (str(d["evidenceId"]).startswith("TPMQ-20260801-crb-fresh-cold")
                           and not str(d["evidenceId"]).endswith("001"))]
        proc = run_importer(synthetic_tree(thinned))
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)

    def test_17_tpm_pass_over_failing_control_is_blocked(self) -> None:
        documents = [d for d in full_passing_matrix()]
        for document in documents:
            if str(document["evidenceId"]).startswith("TPMQ-20260801-no-tpm-cold"):
                document["result"] = "FAIL"
        proc = run_importer(synthetic_tree(documents))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("control", proc.stderr)

    def test_18_disabling_tpm_cannot_fill_a_tpm_cell(self) -> None:
        # The fraud: "fix" the reset by removing the TPM device and file the
        # clean boots under the CRB cell. The cell shape refuses the records
        # and the cell goes unsatisfied.
        documents = full_passing_matrix()
        for document in documents:
            if str(document["evidenceId"]).startswith("TPMQ-20260801-crb-fresh-cold"):
                document["tpmInterface"] = "none"
                document["tpmState"] = "none"
                document["guestResetCount"] = 0
                document.pop("resetClassification", None)
                document.pop("classificationBasis", None)
        proc = run_importer(synthetic_tree(documents))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("shape", proc.stdout + proc.stderr)

    def test_20_physical_tpm_never_moves(self) -> None:
        proc = run_importer(synthetic_tree(full_passing_matrix()))
        self.assertIn('"physicalTpm": "NOT_RUN"', proc.stdout.replace("\n", ""))

    def test_16_a_listed_evidence_file_must_exist(self) -> None:
        # Without --skip-file-hashes, a record listing a serial log that is
        # not there (or was truncated after hashing) is refused: judging
        # success from a complete log and failure from a missing one is the
        # fraud, and integrity is the structural refusal.
        documents = full_passing_matrix()
        documents[6]["evidenceFiles"] = [
            {"path": "serial.log", "sha256": "d" * 64, "sizeBytes": 1}]
        root = synthetic_tree(documents)
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / "import_tpm_results.py"),
             "--root", str(root), "--dry-run"],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("missing", proc.stdout + proc.stderr)

    def test_a_run_copied_into_five_directories_is_one_boot(self) -> None:
        # Found by review, confirmed against the real importer: the gate
        # counted directories, not boots. One passing run copied into four
        # more directories satisfied a five-boot cell and produced
        # softwareTpmBoot PASS, with every file hash intact because the
        # files were copied too. Identity — record id equals directory name,
        # ids unique — is what makes a count a count.
        documents = full_passing_matrix()
        thinned = [d for d in documents
                   if cell_name(d) != "crb-fresh-cold"
                   or str(d["evidenceId"]).endswith("001")]
        original = next(d for d in thinned if cell_name(d) == "crb-fresh-cold")
        root = synthetic_tree(thinned)
        source = root / "qualification/tpm/evidence" / str(original["evidenceId"])
        for index in range(2, 6):
            clone = source.parent / f"TPMQ-20260801-crb-fresh-cold-{index:03d}"
            shutil.copytree(source, clone)
        proc = run_importer(root)
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("directory it sits in", proc.stdout + proc.stderr)

    def test_a_record_in_the_wrong_directory_is_refused(self) -> None:
        documents = full_passing_matrix()
        root = synthetic_tree(documents)
        evidence = root / "qualification/tpm/evidence"
        (evidence / "TPMQ-20260801-crb-fresh-cold-001").rename(
            evidence / "TPMQ-20260801-crb-fresh-cold-009")
        proc = run_importer(root)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("directory it sits in", proc.stdout + proc.stderr)

    def test_stable_expectation_records_cannot_fill_a_boot_cell(self) -> None:
        # Found by review, confirmed against the real importer: CELL_SHAPE did
        # not pin the expectation, so five records judged by the stability
        # rule — none of which had to boot — filled a boot cell. The runner
        # itself produces exactly such a record when invoked with
        # --expect stable under a boot cell's name.
        documents = full_passing_matrix()
        for document in documents:
            if cell_name(document) == "crb-fresh-cold":
                document["expectation"] = "stable"
                document["stagesReached"] = ["firmware-bds", "grub-menu"]
                document["lastStage"] = "grub-menu"
                document["guestResetCount"] = 0
                document.pop("resetClassification", None)
                document.pop("classificationBasis", None)
        proc = run_importer(synthetic_tree(documents))
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("shape", proc.stdout + proc.stderr)

    def test_a_record_without_an_expectation_cannot_fill_a_cell(self) -> None:
        # The schema does not require `expectation` — six early investigation
        # runs predate it and backfilling would state how a run was judged
        # from outside the run. The bypass is closed at the cell instead, so
        # this test pins that the omission still cannot fill a boot cell.
        documents = full_passing_matrix()
        for document in documents:
            if cell_name(document) == "crb-fresh-cold":
                del document["expectation"]
        proc = run_importer(synthetic_tree(documents))
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("shape", proc.stdout + proc.stderr)

    def test_deleting_the_failures_leaves_a_detectable_hole(self) -> None:
        # Run a cell ten times, delete the five that failed, present 5/5.
        # Sequence numbers exist so that fraud leaves a gap.
        documents = full_passing_matrix()
        extra = record(evidenceId="TPMQ-20260801-crb-fresh-cold-007")
        documents.append(extra)
        proc = run_importer(synthetic_tree(documents))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("sequence gaps", proc.stdout + proc.stderr)

    def test_a_malformed_evidence_id_does_not_crash_the_gate(self) -> None:
        # A traceback loses the diagnostic output the gate exists to produce.
        documents = full_passing_matrix()
        documents.append(record(evidenceId="NOT-AN-ID"))
        proc = run_importer(synthetic_tree(documents))
        self.assertEqual(proc.returncode, 2)
        self.assertNotIn("Traceback", proc.stderr)

    def test_unknown_classification_blocks(self) -> None:
        documents = full_passing_matrix()
        documents[6]["resetClassification"] = "UNKNOWN"
        proc = run_importer(synthetic_tree(documents))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("UNKNOWN", proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
