# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Stage 13 — adversarial evidence tests for the dsq-1 gate.

Each test builds a valid synthetic evidence tree, commits exactly one fraud,
and asserts the importer names it. The final class mutation-tests the
critical checks: it disables one check at a time and proves the fraud then
slips through — demonstrating each check is load-bearing, not decorative."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from . import fixtures
from .fixtures import FakeContext, edit_record, full_tree, write_run

import import_results  # noqa: E402  (path set up by fixtures)
import journal_analysis  # noqa: E402


def run_checks(evidence_root: Path) -> list[str]:
    problems: list[str] = []
    by_cell = import_results.load_records(evidence_root, problems)
    import_results.verify_integrity(by_cell, FakeContext(), problems,
                                    verify_files=True)
    return problems


class EvidenceTreeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_healthy_tree_is_clean(self):
        full_tree(self.root)
        self.assertEqual(run_checks(self.root), [])

    # 1 & 2 — one boot copied into two run directories / duplicate IDs
    def test_copied_boot_rejected(self):
        write_run(self.root, "A", 1, "b" * 32)
        write_run(self.root, "A", 2, "b" * 32)
        problems = run_checks(self.root)
        self.assertTrue(any("cannot fill two run directories" in p
                            for p in problems), problems)

    # 3 & 4 — noncontiguous sequences (a gap is a deleted run)
    def test_sequence_gap_rejected(self):
        write_run(self.root, "A", 1, "c" * 32)
        write_run(self.root, "A", 3, "d" * 32)
        problems = run_checks(self.root)
        self.assertTrue(any("not contiguous" in p for p in problems), problems)

    # 5 — record carrying another boot's journal
    def test_foreign_boot_id_rejected(self):
        run_dir = write_run(self.root, "A", 1, "e" * 32)
        edit_record(run_dir, lambda r: r["analysis"].update(
            {"bootId": "f" * 32}))
        problems = run_checks(self.root)
        self.assertTrue(any("another boot's journal" in p for p in problems),
                        problems)

    # 6 — record from another disk digest
    def test_foreign_disk_digest_rejected(self):
        run_dir = write_run(self.root, "A", 1, "0" * 32)
        edit_record(run_dir, lambda r: r["artifact"].update(
            {"sha256": "9" * 64}))
        problems = run_checks(self.root)
        self.assertTrue(any("not the qualified disk" in p for p in problems),
                        problems)

    # 7 — serial-only record in a journal-required cell
    def test_serial_only_record_rejected(self):
        run_dir = write_run(self.root, "A", 1, "1" * 32)
        edit_record(run_dir, lambda r: r.update({"analysis": None}))
        problems = run_checks(self.root)
        self.assertTrue(any("serial-only" in p for p in problems), problems)

    # 8 — collection failure must never read as an empty failed-unit list
    def test_collection_failure_never_counts(self):
        run_dir = write_run(self.root, "A", 1, "2" * 32)
        edit_record(run_dir, lambda r: (
            r.update({"status": "COLLECTION_FAILED"}),
            r["collection"].update({"status": "collection-failed"})))
        by_cell = import_results.load_records(self.root, [])
        table = import_results.unit_occurrences(by_cell)
        counts = table["gdm.service"]["A"]
        self.assertEqual(counts["collectionFailed"], 1)
        self.assertEqual(counts["succeeded"], 0)

    def test_truncated_journal_with_empty_failures_rejected(self):
        run_dir = write_run(self.root, "A", 1, "3" * 32)
        edit_record(run_dir, lambda r: r["analysis"].update(
            {"entryCount": 40}))
        problems = run_checks(self.root)
        self.assertTrue(any("too small" in p for p in problems), problems)

    # 11 — a failed unit cannot be omitted: the manifest pins the record's
    # files, so omission requires editing the record, which the digest of
    # every evidence file (and the boot-id uniqueness) is designed to expose.
    def test_edited_evidence_file_rejected(self):
        run_dir = write_run(self.root, "A", 1, "4" * 32)
        (run_dir / "serial.log").write_bytes(b"doctored\n")
        problems = run_checks(self.root)
        self.assertTrue(any("does not match its recorded digest" in p
                            for p in problems), problems)

    # 18 — a no-network run cannot fill an ordinary-network cell
    def test_relabelled_network_cell_rejected(self):
        run_dir = write_run(self.root, "A", 1, "5" * 32)
        edit_record(run_dir, lambda r: r["cellConfiguration"].update(
            {"network": False}))
        problems = run_checks(self.root)
        self.assertTrue(any("cell configuration differs" in p
                            for p in problems), problems)

    # 19 — reduced-resource evidence cannot fill the normal-resource cell
    def test_relabelled_resources_rejected(self):
        run_dir = write_run(self.root, "A", 1, "6" * 32)
        edit_record(run_dir, lambda r: r["cellConfiguration"].update(
            {"smp": 2, "memory": 4096}))
        problems = run_checks(self.root)
        self.assertTrue(any("cell configuration differs" in p
                            for p in problems), problems)

    # 21 — evidence against another target/authority
    def test_foreign_authority_rejected(self):
        run_dir = write_run(self.root, "A", 1, "7" * 32)
        edit_record(run_dir, lambda r: r["authority"].update(
            {"sourceCommit": "someone-elses-commit"}))
        problems = run_checks(self.root)
        self.assertTrue(any("authority mismatch" in p for p in problems),
                        problems)


class ReadinessTests(unittest.TestCase):
    """Stage 7/15 — graphical.target is never proof of a usable greeter."""

    def make_record(self, **kwargs):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = write_run(Path(tmp), "A", 1, "8" * 32, **kwargs)
            import json
            return json.loads((run_dir / "record.json").read_text())

    # 15 — target reached but greeter never appeared
    def test_target_without_greeter_not_ready(self):
        record = self.make_record(gdm_ok=False)
        record["analysis"]["graphicalTargetReachedMono"] = 7.5
        ok, reasons = import_results.gdm_readiness(record)
        self.assertFalse(ok)
        self.assertTrue(any("greeter" in r or "gdm" in r for r in reasons))

    # 16 — screenshots alone can never satisfy readiness
    def test_screenshot_only_not_ready(self):
        record = self.make_record(gdm_ok=False)
        record["screenshots"] = ["graphical-reached.ppm"]
        ok, _ = import_results.gdm_readiness(record)
        self.assertFalse(ok)

    # 17 — collection ended before the observation window: the journal
    # shows shutdown initiated 22 s after greeter readiness
    def test_incomplete_observation_window_not_ready(self):
        record = self.make_record()
        record["observationWindowCompleted"] = False
        record["analysis"]["shutdownInitiatedMono"] = 30.0
        ok, reasons = import_results.gdm_readiness(record)
        self.assertFalse(ok)
        self.assertTrue(any("stable for only" in r for r in reasons))

    # the serial-paced flag alone cannot fail a boot whose journal proves a
    # full stability window (the serial graphical marker is intermittent)
    def test_journal_window_overrides_serial_flag(self):
        record = self.make_record()
        record["observationWindowCompleted"] = False
        record["liveOutcome"] = "timeout"
        ok, reasons = import_results.gdm_readiness(record)
        self.assertTrue(ok, reasons)

    # with no journal shutdown timestamp, the serial flag is the fallback
    def test_missing_shutdown_timestamp_falls_back_to_serial(self):
        record = self.make_record()
        record["observationWindowCompleted"] = False
        record["analysis"]["shutdownInitiatedMono"] = None
        ok, reasons = import_results.gdm_readiness(record)
        self.assertFalse(ok)
        self.assertTrue(any("observation window" in r for r in reasons))

    def test_unexpected_reset_not_ready(self):
        record = self.make_record()
        record["guestResetCount"] = record["expectedResets"] + 1
        ok, _ = import_results.gdm_readiness(record)
        self.assertFalse(ok)

    def test_healthy_record_ready(self):
        record = self.make_record()
        ok, reasons = import_results.gdm_readiness(record)
        self.assertTrue(ok, reasons)


class CanonicalisationTests(unittest.TestCase):
    """Stage 13 items 12–14 and the collector-defect that started this pass."""

    # 12 — a per-boot D-Bus connection ID never creates a second unit
    def test_transient_dbus_units_share_identity(self):
        one, _ = journal_analysis.canonical_unit(
            "dbus-:1.2-org.gnome.Shell.Screencast@0.service")
        two, _ = journal_analysis.canonical_unit(
            "dbus-:1.3-org.gnome.Shell.Screencast@0.service")
        self.assertEqual(one, two)
        self.assertEqual(one, "dbus-:*-org.gnome.Shell.Screencast@0.service")

    def test_ordinary_units_untouched(self):
        name, conn = journal_analysis.canonical_unit("gdm.service")
        self.assertEqual(name, "gdm.service")
        self.assertIsNone(conn)

    # 13 & 14 — transient recovered failures stay visible both ways
    def test_recovered_failure_counted_as_recovered(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = write_run(root, "A", 1, "9" * 32)

            def mutate(record):
                unit = record["analysis"]["systemUnits"][0]
                unit["disposition"] = "failed-transiently-and-recovered"
                unit["failures"] = 1
                unit["started"] = 2
            edit_record(run_dir, mutate)
            by_cell = import_results.load_records(root, [])
            table = import_results.unit_occurrences(by_cell)
            counts = table["gdm.service"]["A"]
            self.assertEqual(counts["failedAndRecovered"], 1)
            self.assertEqual(counts["succeeded"], 0)


class ContextualDispositionTests(unittest.TestCase):
    """Stage 13 items 9 and 20 — no unit is ever excused by name alone."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    # 9 — a user-unit failure with a real user session present cannot be
    # accepted as EXPECTED_WITHOUT_USER_SESSION
    def test_expected_without_session_needs_no_real_session(self):
        write_run(self.root, "A", 1, "a1" + "0" * 30,
                  screencast_failed=True,
                  sessions={"1000": ["pam:realuser"]})
        by_cell = import_results.load_records(self.root, [])
        problems: list[str] = []
        accepted = import_results.verify_contextual_acceptance(
            "dbus-:*-org.gnome.Shell.Screencast@0.service",
            {"disposition": "EXPECTED_WITHOUT_USER_SESSION",
             "confidence": "CONFIRMED"},
            by_cell, problems)
        self.assertFalse(accepted)
        self.assertTrue(problems)

    def test_expected_without_session_accepted_in_context(self):
        write_run(self.root, "A", 1, "a2" + "0" * 30,
                  screencast_failed=True)
        by_cell = import_results.load_records(self.root, [])
        accepted = import_results.verify_contextual_acceptance(
            "dbus-:*-org.gnome.Shell.Screencast@0.service",
            {"disposition": "EXPECTED_WITHOUT_USER_SESSION",
             "confidence": "CONFIRMED"},
            by_cell, [])
        self.assertTrue(accepted)

    # a boot-phase failure can never be excused as a teardown race
    def test_teardown_race_cannot_cover_boot_failure(self):
        write_run(self.root, "A", 1, "a4" + "0" * 30, gdm_ok=False)
        problems: list[str] = []
        accepted = import_results.verify_contextual_acceptance(
            "gdm.service",
            {"disposition": "SHUTDOWN_TEARDOWN_EXIT_RACE",
             "confidence": "CONFIRMED"},
            import_results.load_records(self.root, []), problems)
        self.assertFalse(accepted)
        self.assertTrue(any("before shutdown" in p for p in problems))

    def test_teardown_race_accepted_when_all_failures_in_teardown(self):
        run_dir = write_run(self.root, "A", 1, "a5" + "0" * 30)

        def mutate(record):
            unit = record["analysis"]["systemUnits"][0]
            unit["disposition"] = "failed-during-shutdown"
            unit["failures"] = 1
            unit["failuresDuringBoot"] = 0
            unit["failuresDuringShutdown"] = 1
            unit["events"] = [{"kind": "failed", "monotonic": 84.7,
                               "detail": "exit-code"}]
        edit_record(run_dir, mutate)
        accepted = import_results.verify_contextual_acceptance(
            "gdm.service",
            {"disposition": "SHUTDOWN_TEARDOWN_EXIT_RACE",
             "confidence": "CONFIRMED"},
            import_results.load_records(self.root, []), [])
        self.assertTrue(accepted)

    # a unit that dumped core can never close as a mere exit race
    def test_exit_race_cannot_cover_a_crash(self):
        run_dir = write_run(self.root, "A", 1, "a7" + "0" * 30)

        def mutate(record):
            unit = record["analysis"]["systemUnits"][0]
            unit["unit"] = "avahi-daemon.service"
            unit["disposition"] = "failed-during-shutdown"
            unit["failures"] = 1
            unit["failuresDuringBoot"] = 0
            unit["failuresDuringShutdown"] = 1
            unit["mainExit"] = {"code": "dumped", "status": "6/ABRT"}
            unit["events"] = [{"kind": "failed", "monotonic": 85.0,
                               "detail": "core-dump"}]
        edit_record(run_dir, mutate)
        problems: list[str] = []
        accepted = import_results.verify_contextual_acceptance(
            "avahi-daemon.service",
            {"disposition": "SHUTDOWN_TEARDOWN_EXIT_RACE",
             "confidence": "CONFIRMED"},
            import_results.load_records(self.root, []), problems)
        self.assertFalse(accepted)
        self.assertTrue(any("cannot cover a crash" in p for p in problems))

    # a teardown-crash disposition is rejected if the coredump preceded
    # shutdown initiation
    def test_teardown_crash_requires_teardown_coredump(self):
        run_dir = write_run(self.root, "A", 1, "a8" + "0" * 30)

        def mutate(record):
            unit = record["analysis"]["systemUnits"][0]
            unit["unit"] = "avahi-daemon.service"
            unit["disposition"] = "failed-during-shutdown"
            unit["failures"] = 1
            unit["failuresDuringBoot"] = 0
            unit["failuresDuringShutdown"] = 1
            unit["mainExit"] = {"code": "dumped", "status": "6/ABRT"}
            unit["events"] = [{"kind": "failed", "monotonic": 85.0,
                               "detail": "core-dump"}]
            record["analysis"]["coredumps"] = [
                {"monotonic": 12.0, "process": "avahi-daemon",
                 "uid": "70", "signal": "SIGABRT", "message": "x"}]
        edit_record(run_dir, mutate)
        problems: list[str] = []
        accepted = import_results.verify_contextual_acceptance(
            "avahi-daemon.service",
            {"disposition": "SHUTDOWN_TEARDOWN_CRASH",
             "confidence": "CONFIRMED",
             "crashProcesses": ["avahi-daemon"]},
            import_results.load_records(self.root, []), problems)
        self.assertFalse(accepted)
        self.assertTrue(any("before shutdown was requested" in p
                            for p in problems))

    # an NSS-window race is bound to the authselect window, not the name
    def test_nss_window_race_rejected_outside_window(self):
        run_dir = write_run(self.root, "A", 1, "a6" + "0" * 30)

        def mutate(record):
            unit = record["analysis"]["systemUnits"][0]
            unit["unit"] = "chronyd.service"
            unit["disposition"] = "currently-failed"
            unit["failures"] = 1
            unit["failuresDuringBoot"] = 1
            unit["events"] = [{"kind": "failed", "monotonic": 30.0,
                               "detail": "exit-code"}]
            record["analysis"]["failedSystemUnits"] = ["chronyd.service"]
        edit_record(run_dir, mutate)
        problems: list[str] = []
        accepted = import_results.verify_contextual_acceptance(
            "chronyd.service",
            {"disposition": "FIRST_BOOT_NSS_WINDOW_RACE",
             "confidence": "CONFIRMED"},
            import_results.load_records(self.root, []), problems)
        self.assertFalse(accepted)
        self.assertTrue(any("outside the authselect apply window" in p
                            for p in problems))

    # 20 — a blanket ignore-by-name disposition never closes a unit
    def test_defect_dispositions_always_block(self):
        write_run(self.root, "A", 1, "a3" + "0" * 30)
        accepted = import_results.verify_contextual_acceptance(
            "dbus-:*-org.gnome.Shell.Screencast@0.service",
            {"disposition": "IGNORE_ALWAYS", "confidence": "CONFIRMED"},
            import_results.load_records(self.root, []), [])
        self.assertFalse(accepted)


class MutationTests(unittest.TestCase):
    """Prove the critical fraud checks are load-bearing: with a check
    disabled (the pre-fix logic), the corresponding fraud passes clean."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_duplicate_boot_check_is_load_bearing(self):
        write_run(self.root, "A", 1, "b" * 32)
        write_run(self.root, "A", 2, "b" * 32)
        self.assertTrue(run_checks(self.root))
        original = import_results.RUN_DIR_RE
        # pre-fix logic: no boot-id ledger — simulate by loading each run
        # in isolation, which is exactly what the old collector did
        problems_isolated: list[str] = []
        for run in sorted(self.root.iterdir()):
            single = Path(self.tmp.name) / "single"
            single.mkdir(exist_ok=True)
            isolated = single / run.name
            # The property under test is that each run is loaded alone, not
            # symbolic-link handling.  Copying keeps that mutation test live
            # on Windows hosts where creating an NTFS symlink requires an
            # unrelated developer-mode privilege.
            shutil.copytree(run, isolated)
            import_results.load_records(single, problems_isolated)
            shutil.rmtree(isolated)
        self.assertEqual(import_results.RUN_DIR_RE, original)
        self.assertFalse([p for p in problems_isolated
                          if "cannot fill two" in p])

    def test_authority_check_is_load_bearing(self):
        run_dir = write_run(self.root, "A", 1, "c" * 32)
        edit_record(run_dir, lambda r: r["authority"].update(
            {"sourceCommit": "stale"}))
        with_check = run_checks(self.root)
        self.assertTrue(any("authority mismatch" in p for p in with_check))
        # pre-fix logic: no binding verification
        original = import_results.verify_record_binding
        import_results.verify_record_binding = lambda record, context: []
        try:
            without_check = run_checks(self.root)
        finally:
            import_results.verify_record_binding = original
        self.assertFalse([p for p in without_check
                          if "authority mismatch" in p])

    def test_digest_check_is_load_bearing(self):
        run_dir = write_run(self.root, "A", 1, "d" * 32)
        (run_dir / "serial.log").write_bytes(b"doctored\n")
        with_check = run_checks(self.root)
        self.assertTrue(any("recorded digest" in p for p in with_check))
        problems: list[str] = []
        by_cell = import_results.load_records(self.root, problems)
        import_results.verify_integrity(by_cell, FakeContext(), problems,
                                        verify_files=False)
        self.assertFalse([p for p in problems if "recorded digest" in p])


if __name__ == "__main__":
    unittest.main()
