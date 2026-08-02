# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Stage 3 — adversarial tests for the dsq-2 evidence gate.

The remaining rejections are ones no static check can make: they are about
what a *record* is allowed to claim. Each test builds a valid synthetic record
and commits exactly one fraud, then asserts the gate names it. A test that
starts from an invalid record proves nothing about the check it targets.

The final class mutation-tests the gate: it disables one check at a time and
proves the fraud then passes, so each check is shown to be load-bearing.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "qualification/first-login/scripts"))
sys.path.insert(0, str(ROOT / "qualification/display-stack/scripts"))

import import_first_login as gate  # noqa: E402
from run_boot import CELLS  # noqa: E402

ARTIFACT = "a" * 64
SOURCE_COMMIT = "b" * 40
CONTEXT = {
    "scenarioVersion": "dsq-2",
    "sourceCommit": SOURCE_COMMIT,
    "installationArtifactDigest": ARTIFACT,
}
UID = "4242"


def unit(name: str, *, disposition="activated-and-succeeded",
         exit_status=None) -> dict:
    return {
        "unit": name, "scope": "user", "uid": UID, "uidHadSession": True,
        "rawNames": [name], "disposition": disposition,
        "failures": 0 if disposition == "activated-and-succeeded" else 1,
        "failuresDuringBoot": 0, "failuresDuringShutdown": 0,
        "started": 1, "result": None,
        "mainExit": {"code": "exited", "status": exit_status}
                    if exit_status else None,
        "restartCounterMax": 0, "skipped": [],
        "activeEnterMono": 21.0, "inactiveEnterMono": None, "events": [],
    }


def analysis(boot_id: str, *, label="login-1", user_units=None,
             chronyd=None, logged_in=(UID,)) -> dict:
    units = user_units if user_units is not None else [
        unit("bunny-config-dir.service"), unit("bunny-first-boot.service")]
    per_uid = {
        uid: {u["unit"]: {"disposition": u["disposition"],
                          "result": u["result"],
                          "mainExitStatus": (u.get("mainExit") or {}).get(
                              "status"),
                          "failuresDuringBoot": u["failuresDuringBoot"],
                          "restartCounterMax": u["restartCounterMax"],
                          "activeEnterMono": u["activeEnterMono"],
                          "namespaceFailure":
                              (u.get("mainExit") or {}).get("status")
                              == "226/NAMESPACE"}
              for u in units}
        for uid in logged_in}
    return {
        "bootId": boot_id, "label": label, "entryCount": 5000,
        "graphicalTargetReachedMono": 18.0, "seat0CreatedMono": 12.0,
        "shutdownInitiatedMono": 95.0,
        "gdm": {"gdmReachedActive": True, "gdmBootPhaseFailures": 0},
        "coredumps": [],
        "userUnits": units, "systemUnits": [],
        "firstLogin": {
            "loggedInUids": list(logged_in),
            "sessionCount": len(logged_in),
            "units": per_uid,
            "anyNamespaceFailure": any(
                e["namespaceFailure"] for u in per_uid.values()
                for e in u.values()),
        },
        "chronydOrdering": chronyd if chronyd is not None else {
            "chronydStartRequestedMono": 8.4,
            "authselectApplyStartMono": 7.2,
            "authselectApplyEndMono": 7.9,
            "orderedAfterAuthselect": True,
            "startedInsideApplyWindow": False,
            "mainExitStatus": None,
            "userResolutionFailure": False,
            "observed": True,
        },
    }


def home_ok(problems=None) -> dict:
    return {
        "home": "/var/home/dsq-test", "expectedUid": 4242,
        "expectedGid": 4242, "homeExists": True,
        "directories": {
            ".config/bunny-os": {"present": True, "type": "directory",
                                 "mode": 0o700, "uid": 4242, "gid": 4242,
                                 "inode": 111,
                                 "selinuxContext":
                                     "unconfined_u:object_r:config_home_t:s0"},
            ".config/systemd/user": {"present": True, "type": "directory",
                                     "mode": 0o700, "uid": 4242, "gid": 4242,
                                     "inode": 112,
                                     "selinuxContext":
                                         "unconfined_u:object_r:config_home_t:s0"},
        },
        "completionMarker": {"present": True, "mode": 0o600, "uid": 4242},
        "problems": problems or [],
    }


def write_run(root: Path, cell: str, sequence: int, boot_id: str, *,
              second_login: bool = False, **overrides) -> Path:
    run_dir = root / f"FLQ-20260802-cell{cell}-{sequence:03d}"
    (run_dir / "journal").mkdir(parents=True, exist_ok=True)
    payload = b"serial\n"
    (run_dir / "serial-login-1.log").write_bytes(payload)

    analyses = [analysis(boot_id)]
    if second_login:
        second = analysis(boot_id + "s", label="login-2")
        second["firstLogin"]["units"][UID]["bunny-first-boot.service"][
            "disposition"] = "skipped-by-condition"
        analyses.append(second)

    record = {
        "schemaVersion": 1, "scenarioVersion": "dsq-2",
        "runId": run_dir.name, "cell": cell, "sequence": sequence,
        "cellConfiguration": dict(CELLS[cell]),
        "secondLoginPlanned": second_login,
        "status": "COLLECTED",
        "authority": {"scenarioVersion": "dsq-2",
                      "sourceCommit": SOURCE_COMMIT},
        "artifact": {"name": "bunny-os.qcow2", "sha256": ARTIFACT},
        "loginFixture": {"testInjected": True, "partOfBunnyArtifact": False,
                         "home": "/var/home/dsq-test"},
        "collection": {"status": "ok",
                       "bootIds": [a["bootId"] for a in analyses]},
        "analyses": analyses,
        "homeAssertions": home_ok(),
        "idempotence": {"problems": [], "idempotent": True},
        "evidenceManifest": [{
            "path": "serial-login-1.log",
            "sha256": hashlib.sha256(payload).hexdigest(),
            "sizeBytes": len(payload)}],
    }
    record.update(overrides)
    (run_dir / "record.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return run_dir


def run_gate(root: Path) -> list[str]:
    problems: list[str] = []
    by_cell = gate.load_records(root, problems)
    gate.verify_integrity(by_cell, CONTEXT, problems, verify_files=True)
    return problems


class GateTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)


class IntegrityTests(GateTestCase):
    def test_a_healthy_run_is_clean(self):
        write_run(self.root, "A", 1, "boot-1")
        self.assertEqual(run_gate(self.root), [])

    def test_dsq1_evidence_cannot_be_imported(self):
        """19. Old dsq-1 evidence imported against the corrected archive."""
        write_run(self.root, "A", 1, "boot-1", scenarioVersion="dsq-1")
        problems = run_gate(self.root)
        self.assertTrue(any("dsq-1" in p and "dsq-2" in p for p in problems),
                        f"a dsq-1 record was accepted: {problems}")

    def test_a_record_about_another_disk_is_refused(self):
        """20. A changed root filesystem retains the old target."""
        write_run(self.root, "A", 1, "boot-1",
                  artifact={"name": "old.qcow2", "sha256": "c" * 64})
        problems = run_gate(self.root)
        self.assertTrue(any("artifact digest" in p for p in problems),
                        f"a record about another disk was accepted: {problems}")

    def test_a_record_bound_to_another_commit_is_refused(self):
        write_run(self.root, "A", 1, "boot-1",
                  authority={"scenarioVersion": "dsq-2",
                             "sourceCommit": "d" * 40})
        self.assertTrue(any("source commit" in p for p in run_gate(self.root)))

    def test_one_boot_cannot_fill_two_runs(self):
        write_run(self.root, "A", 1, "shared")
        write_run(self.root, "A", 2, "shared")
        self.assertTrue(any("already appears" in p
                            for p in run_gate(self.root)))

    def test_unit_success_without_home_assertions_is_refused(self):
        """12. Service success inferred without reading the evidence that
        establishes what the directory is."""
        write_run(self.root, "A", 1, "boot-1", homeAssertions=None)
        problems = run_gate(self.root)
        self.assertTrue(any("home assertions" in p for p in problems),
                        f"{problems}")

    def test_a_record_without_journal_analysis_is_refused(self):
        """13. A system journal query substituted for USER_UNIT evidence —
        a record with no analyses at all cannot answer what the user units
        did."""
        write_run(self.root, "A", 1, "boot-1", analyses=[])
        self.assertTrue(any("without journal analyses" in p
                            for p in run_gate(self.root)))

    def test_a_record_that_hides_the_fixture_is_refused(self):
        """11-adjacent: every record must state the account is test-injected."""
        write_run(self.root, "A", 1, "boot-1",
                  loginFixture={"testInjected": False,
                                "partOfBunnyArtifact": True})
        problems = run_gate(self.root)
        self.assertTrue(any("test-injected" in p for p in problems), problems)

    def test_a_tampered_file_is_refused(self):
        run_dir = write_run(self.root, "A", 1, "boot-1")
        (run_dir / "serial-login-1.log").write_bytes(b"rewritten\n")
        self.assertTrue(any("does not match its recorded digest" in p
                            for p in run_gate(self.root)))

    def test_a_gap_in_the_sequence_is_refused(self):
        write_run(self.root, "A", 1, "boot-1")
        write_run(self.root, "A", 3, "boot-3")
        self.assertTrue(any("not contiguous" in p
                            for p in run_gate(self.root)))


class VerdictTests(GateTestCase):
    def test_namespace_failure_blocks(self):
        """The corrected defect's exact signature must never pass."""
        run_dir = write_run(self.root, "A", 1, "boot-1")
        record = json.loads((run_dir / "record.json").read_text())
        entry = record["analyses"][0]["firstLogin"]["units"][UID][
            "bunny-first-boot.service"]
        entry["namespaceFailure"] = True
        entry["mainExitStatus"] = "226/NAMESPACE"
        entry["disposition"] = "currently-failed"
        ok, reasons = gate.first_login_verdict(record)
        self.assertFalse(ok)
        self.assertTrue(any("226/NAMESPACE" in r for r in reasons), reasons)

    def test_chronyd_user_resolution_failure_blocks(self):
        """15. Chronyd succeeds only because the race did not occur."""
        run_dir = write_run(self.root, "A", 1, "boot-1")
        record = json.loads((run_dir / "record.json").read_text())
        record["analyses"][0]["chronydOrdering"].update(
            userResolutionFailure=True, mainExitStatus="217/USER")
        ok, reasons = gate.first_login_verdict(record)
        self.assertFalse(ok)
        self.assertTrue(any("217/USER" in r for r in reasons), reasons)

    def test_chronyd_inside_the_apply_window_blocks(self):
        """14. Chronyd starts before authselect completes."""
        run_dir = write_run(self.root, "A", 1, "boot-1")
        record = json.loads((run_dir / "record.json").read_text())
        record["analyses"][0]["chronydOrdering"].update(
            startedInsideApplyWindow=True, orderedAfterAuthselect=False)
        ok, reasons = gate.first_login_verdict(record)
        self.assertFalse(ok)
        self.assertTrue(any("apply window" in r for r in reasons), reasons)

    def test_a_boot_with_no_session_blocks(self):
        run_dir = write_run(self.root, "A", 1, "boot-1")
        record = json.loads((run_dir / "record.json").read_text())
        record["analyses"][0]["firstLogin"]["loggedInUids"] = []
        record["analyses"][0]["firstLogin"]["units"] = {}
        ok, reasons = gate.first_login_verdict(record)
        self.assertFalse(ok)
        self.assertTrue(any("no user session" in r for r in reasons), reasons)

    def test_home_problems_block(self):
        run_dir = write_run(self.root, "A", 1, "boot-1")
        record = json.loads((run_dir / "record.json").read_text())
        record["homeAssertions"] = home_ok(
            problems=["/var/home/dsq-test/.config/bunny-os: is a symbolic "
                      "link"])
        ok, reasons = gate.first_login_verdict(record)
        self.assertFalse(ok)
        self.assertTrue(any("symbolic link" in r for r in reasons), reasons)

    def test_second_login_that_repeats_the_flow_blocks(self):
        """9. First-run configuration overwritten on second login."""
        run_dir = write_run(self.root, "A", 1, "boot-1", second_login=True)
        record = json.loads((run_dir / "record.json").read_text())
        record["analyses"][1]["firstLogin"]["units"][UID][
            "bunny-first-boot.service"]["disposition"] = "currently-failed"
        ok, reasons = gate.second_login_verdict(record)
        self.assertFalse(ok)

    def test_second_login_that_replaced_the_directory_blocks(self):
        run_dir = write_run(self.root, "A", 1, "boot-1", second_login=True)
        record = json.loads((run_dir / "record.json").read_text())
        record["idempotence"] = {
            "problems": [".config/bunny-os: inode changed 111 -> 999; the "
                         "directory was replaced, not reused"],
            "idempotent": False}
        ok, reasons = gate.second_login_verdict(record)
        self.assertFalse(ok)
        self.assertTrue(any("inode changed" in r for r in reasons), reasons)

    def test_a_healthy_run_passes(self):
        run_dir = write_run(self.root, "A", 1, "boot-1", second_login=True)
        record = json.loads((run_dir / "record.json").read_text())
        ok, reasons = gate.first_login_verdict(record)
        self.assertTrue(ok, reasons)
        ok2, reasons2 = gate.second_login_verdict(record)
        self.assertTrue(ok2, reasons2)


class NoThresholdTests(GateTestCase):
    def test_one_failure_in_sixty_still_blocks(self):
        """Stage 12: no percentage threshold. One unexplained failure keeps
        the category blocked, which is the rule a rate-based gate breaks."""
        healthy = write_run(self.root, "A", 1, "boot-1")
        record = json.loads((healthy / "record.json").read_text())
        ok, _ = gate.first_login_verdict(record)
        self.assertTrue(ok)

        broken = write_run(self.root, "A", 2, "boot-2")
        record2 = json.loads((broken / "record.json").read_text())
        record2["analyses"][0]["chronydOrdering"]["userResolutionFailure"] = True
        ok2, reasons2 = gate.first_login_verdict(record2)
        self.assertFalse(ok2, "a single chronyd identity failure was tolerated")


class MutationTests(GateTestCase):
    """Each gate check disabled in turn; the fraud must then pass."""

    def test_the_scenario_check_is_load_bearing(self):
        write_run(self.root, "A", 1, "boot-1", scenarioVersion="dsq-1")
        self.assertNotEqual(run_gate(self.root), [])

        original = gate.SCENARIO_VERSION
        self.addCleanup(lambda: setattr(gate, "SCENARIO_VERSION", original))
        gate.SCENARIO_VERSION = "dsq-1"
        problems = run_gate(self.root)
        self.assertFalse(
            any("dsq-2" in p and "scenarioVersion" in p for p in problems),
            "the scenario check is not what rejected the dsq-1 record")

    def test_the_artifact_check_is_load_bearing(self):
        write_run(self.root, "A", 1, "boot-1",
                  artifact={"name": "old.qcow2", "sha256": "c" * 64})
        self.assertTrue(any("artifact digest" in p
                            for p in run_gate(self.root)))

        loose = dict(CONTEXT, installationArtifactDigest="c" * 64)
        problems: list[str] = []
        by_cell = gate.load_records(self.root, problems)
        gate.verify_integrity(by_cell, loose, problems, verify_files=True)
        self.assertFalse(any("artifact digest" in p for p in problems),
                         "the artifact check is not what rejected the record")

    def test_the_namespace_check_is_load_bearing(self):
        run_dir = write_run(self.root, "A", 1, "boot-1")
        record = json.loads((run_dir / "record.json").read_text())
        entry = record["analyses"][0]["firstLogin"]["units"][UID][
            "bunny-first-boot.service"]
        entry["namespaceFailure"] = True
        entry["mainExitStatus"] = "226/NAMESPACE"
        ok, reasons = gate.first_login_verdict(record)
        self.assertFalse(ok)

        entry["namespaceFailure"] = False
        ok2, reasons2 = gate.first_login_verdict(record)
        self.assertTrue(
            ok2,
            "clearing namespaceFailure did not make the record pass, so that "
            f"flag is not what blocked it: {reasons2}")


if __name__ == "__main__":
    unittest.main()
