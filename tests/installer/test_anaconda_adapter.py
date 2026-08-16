# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The adapter behind the fail-closed gate, and the stage vocabulary mapping.

The DBus executor cannot be tested here — it needs an installer ISO — so what is
tested is everything around it: that the gate still closes for every reason it
can, that the rendered kickstart reaches the executor unchanged, that the
passphrase file is destroyed whatever happens, and that the Companion is never
put in a state the engine is not in.
"""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from installer.backend.anaconda import (                       # noqa: E402
    AnacondaAdapter, AnacondaDBusExecutor, ExecutorUnavailable,
    InstallationFailed, RecordingExecutor, read_medium_kickstart,
)
from installer.backend.progress import (                       # noqa: E402
    STAGE_TO_PROGRESS, companion_phase_for, progress_rows,
)
from installer.backend.service import BackendUnavailable, InstallerService  # noqa: E402
from installer.backend.state import STAGES, WRITE_BOUNDARY     # noqa: E402
from installer.companion_flow import PROGRESS_STAGES           # noqa: E402
from installer.setup_state import Choices                      # noqa: E402
from installer.storage.models import DiskInfo                  # noqa: E402
from installer.storage.planning import automatic_plan          # noqa: E402

HASH = "$y$j9T$abcdefghijklmnop$0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHI"
MEDIUM = [
    "text",
    "clearpart --all --initlabel",
    "ostreecontainer --url=/run/install/repo/container --transport=oci",
    "%post",
    "bootupctl backend install /",
    "%end",
]
DISK = DiskInfo(
    id="disk-2f6a9c1e4b7d8a05", devicePath="/dev/vda", sizeBytes=80 * 1024**3,
    logicalSectorSize=512, physicalSectorSize=512, removable=False, readOnly=False,
    model="QEMU HARDDISK",
)


def _adapter(tmp: Path, *, executor=None, passphrase="a-passphrase", encryption=True):
    medium = tmp / "osbuild.ks"
    medium.write_text("\n".join(MEDIUM) + "\n", encoding="utf-8")
    return AnacondaAdapter(
        executor=executor or RecordingExecutor(),
        choices=Choices(display_name="Alex", username="alex",
                        encryption_enabled=encryption).as_record(),
        password_hash=HASH,
        passphrase=passphrase if encryption else None,
        medium_paths=(medium,),
        runtime_directory=tmp / "run",
    )


class TheGateStillCloses(unittest.TestCase):
    def test_the_service_still_refuses_without_an_adapter(self) -> None:
        """The property this phase must not have removed."""
        service = InstallerService(live_uid=1000, probe=lambda: [DISK])
        self.assertIsNone(service._adapter)

    def test_a_missing_medium_kickstart_refuses_before_anything(self) -> None:
        with self.assertRaises(ExecutorUnavailable) as caught:
            read_medium_kickstart((Path("/nonexistent/one.ks"), Path("/nonexistent/two.ks")))
        self.assertIn("looked in", str(caught.exception))

    def test_an_unavailable_executor_stops_before_a_write(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            executor = RecordingExecutor(available=False)
            adapter = _adapter(tmp, executor=executor)
            with self.assertRaises(ExecutorUnavailable):
                adapter.start(plan=automatic_plan(DISK, mode="erase_disk", encryption=True),
                              confirmations={})
            self.assertEqual(executor.kickstarts, [], "a refused install still wrote a kickstart")
            self.assertEqual(executor.stages, [])

    def test_a_plan_that_cannot_render_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            adapter = _adapter(tmp, passphrase=None, encryption=True)
            with self.assertRaises(ExecutorUnavailable) as caught:
                adapter.start(plan=automatic_plan(DISK, mode="erase_disk", encryption=True),
                              confirmations={})
            self.assertIn("could not be rendered", str(caught.exception))


class WhatReachesTheExecutor(unittest.TestCase):
    def test_the_executor_receives_the_rendered_kickstart(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            executor = RecordingExecutor()
            adapter = _adapter(tmp, executor=executor)
            adapter.start(plan=automatic_plan(DISK, mode="erase_disk", encryption=True),
                          confirmations={})
            self.assertEqual(len(executor.kickstarts), 1)
            document = executor.kickstarts[0]
            self.assertIn("--drives=vda", document)
            self.assertIn("ostreecontainer", document)
            self.assertIn("a-passphrase", document)

    def test_the_passphrase_file_does_not_survive_the_install(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            adapter = _adapter(tmp)
            adapter.start(plan=automatic_plan(DISK, mode="erase_disk", encryption=True),
                          confirmations={})
            leftovers = list((tmp / "run").glob("*.ks"))
            self.assertEqual(leftovers, [], f"a kickstart with a passphrase survived: {leftovers}")

    def test_the_passphrase_file_does_not_survive_a_failure(self) -> None:
        """The finally-clause that matters more than the happy path."""
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            adapter = _adapter(tmp, executor=RecordingExecutor(fail_at="Partitioning"))
            with self.assertRaises(RuntimeError):
                adapter.start(plan=automatic_plan(DISK, mode="erase_disk", encryption=True),
                              confirmations={})
            leftovers = list((tmp / "run").glob("*.ks"))
            self.assertEqual(leftovers, [], f"a kickstart with a passphrase survived: {leftovers}")

    def test_diagnostics_carry_no_secret(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            adapter = _adapter(tmp)
            adapter.start(plan=automatic_plan(DISK, mode="erase_disk", encryption=True),
                          confirmations={})
            written = adapter.diagnostics(tmp / "diag.txt")
            body = written.read_text(encoding="utf-8")
            self.assertNotIn("a-passphrase", body)
            self.assertNotIn(HASH, body)
            self.assertIn("[redacted]", body)


class TheHandoffReachesTheExecutor(unittest.TestCase):
    def test_the_executor_receives_the_choices_as_the_handoff(self) -> None:
        """§45: what the adapter holds is what the placement step gets."""
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            executor = RecordingExecutor()
            adapter = _adapter(tmp, executor=executor)
            adapter.start(plan=automatic_plan(DISK, mode="erase_disk", encryption=True),
                          confirmations={})
            self.assertEqual(executor.handoffs, [adapter.choices])


class _PlacementFake(AnacondaDBusExecutor):
    """The placement logic over an in-memory target; no bus, no systemd."""

    def __init__(self) -> None:
        self.files: dict[str, str] = {}
        self.stages: list[tuple[str, str]] = []

    def _read_target_file(self, relative: str) -> str | None:
        return self.files.get(relative)

    def _write_target_file(self, relative: str, content: str, *,
                           directory_mode: str = "0755",
                           file_mode: str = "0644") -> None:
        self.files[relative] = content
        self.modes = getattr(self, "modes", {})
        self.modes[relative] = file_mode

    def stage(self, stage: str, detail: str) -> None:
        self.stages.append((stage, detail))


class ThePlacementStep(unittest.TestCase):
    """§45's crossing, decided file by file."""

    def test_every_choice_lands_as_its_file(self) -> None:
        executor = _PlacementFake()
        document = Choices(display_name="Alex", username="alex",
                           device_name="warren").as_record()
        executor._place_handoff({
            "locale": {"language": "en-GB", "keyboardLayout": "gb"},
            "account": {"username": "alex", "deviceName": "warren"},
            "setupDocument": document,
        }, on_stage=executor.stage)
        self.assertEqual(executor.files["/etc/locale.conf"], "LANG=en_GB.UTF-8\n")
        self.assertEqual(executor.files["/etc/vconsole.conf"], "KEYMAP=gb\n")
        self.assertEqual(executor.files["/etc/hostname"], "warren\n")
        import json as json_module

        parsed = json_module.loads(executor.files["/var/lib/bunny-setup/choices.json"])
        self.assertEqual(parsed["account"]["deviceName"], "warren")

    def test_the_created_user_gets_the_bunny_session(self) -> None:
        """GDM has no DefaultSession key; the AccountsService record is the
        mechanism it reads, and login-8b measured plain GNOME starting when
        only custom.conf claimed a default."""
        executor = _PlacementFake()
        executor._place_handoff({
            "account": {"username": "alex", "deviceName": "warren"},
        }, on_stage=executor.stage)
        record = executor.files["/var/lib/AccountsService/users/alex"]
        self.assertIn("Session=bunny\n", record)
        self.assertIn("XSession=bunny\n", record)
        self.assertIn("SystemAccount=false\n", record)
        # Written 0600: the daemon owns the file; nothing else needs to read it.
        self.assertEqual(executor.modes["/var/lib/AccountsService/users/alex"],
                         "0600")

    def test_an_invalid_username_refuses_the_session_record(self) -> None:
        executor = _PlacementFake()
        with self.assertRaises(InstallationFailed):
            executor._place_handoff({
                "account": {"username": "alex; rm -rf /"},
            }, on_stage=executor.stage)

    def test_no_username_writes_no_session_record(self) -> None:
        executor = _PlacementFake()
        executor._place_handoff({"locale": {"language": "en-GB"}},
                                on_stage=executor.stage)
        self.assertFalse([path for path in executor.files
                          if "AccountsService" in path])

    def test_a_vconsole_anaconda_already_wrote_is_kept(self) -> None:
        executor = _PlacementFake()
        executor.files["/etc/vconsole.conf"] = 'KEYMAP="gb"\nFONT="eurlatgr"\n'
        executor._place_handoff({
            "locale": {"language": "en-GB", "keyboardLayout": "gb"},
            "account": {},
        }, on_stage=executor.stage)
        self.assertIn("FONT", executor.files["/etc/vconsole.conf"],
                      "the placement clobbered a file the engine wrote correctly")

    def test_no_device_name_writes_no_hostname(self) -> None:
        executor = _PlacementFake()
        executor._place_handoff({
            "locale": {"language": "en-GB", "keyboardLayout": "gb"},
            "account": {"deviceName": ""},
        }, on_stage=executor.stage)
        self.assertNotIn("/etc/hostname", executor.files)

    def test_an_invalid_device_name_refuses_the_install(self) -> None:
        from installer.backend.anaconda import InstallationFailed

        executor = _PlacementFake()
        with self.assertRaises(InstallationFailed):
            executor._place_handoff({
                "locale": {},
                "account": {"deviceName": "Not A Hostname"},
            }, on_stage=executor.stage)

    def test_an_empty_handoff_places_nothing(self) -> None:
        executor = _PlacementFake()
        executor._place_handoff(None, on_stage=executor.stage)
        self.assertEqual(executor.files, {})
        self.assertEqual(executor.stages, [])

    def test_a_write_that_does_not_read_back_refuses(self) -> None:
        from installer.backend.anaconda import InstallationFailed

        class Truncating(AnacondaDBusExecutor):
            def __init__(self) -> None:
                pass

            def _target_shell(self, script, *, stdin=None):
                import subprocess as sp
                return sp.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

            def _read_target_file(self, relative):
                return ""  # the write "succeeded" and the disk holds nothing

        with self.assertRaises(InstallationFailed) as caught:
            Truncating()._write_target_file("/etc/locale.conf", "LANG=en_GB.UTF-8\n")
        self.assertIn("did not read back", str(caught.exception))


class StageMapping(unittest.TestCase):
    """§6 and §23: the Companion says what the engine is doing, not a guess."""

    def test_every_engine_stage_maps(self) -> None:
        for stage in STAGES:
            self.assertIn(stage, STAGE_TO_PROGRESS)

    def test_every_mapped_stage_is_one_the_companion_shows(self) -> None:
        shown = {key for key, _ in PROGRESS_STAGES}
        for target in STAGE_TO_PROGRESS.values():
            self.assertIn(target, shown)

    def test_progress_only_moves_forwards(self) -> None:
        """A stage that goes back to `waiting` is a progress bar that rewinds."""
        order = {"waiting": 0, "active": 1, "done": 2}
        previous = {key: 0 for key, _ in PROGRESS_STAGES}
        for stage in STAGES:
            for row in progress_rows(stage):
                self.assertGreaterEqual(
                    order[row["status"]], previous[row["key"]],
                    f"{row['key']} went backwards at engine stage {stage}")
                previous[row["key"]] = order[row["status"]]

    def test_security_is_not_done_until_the_bootloader_is(self) -> None:
        """Two engine stages map to one phrase; the first must not complete it."""
        after_encrypting = {row["key"]: row["status"]
                            for row in progress_rows("Creating filesystems")}
        self.assertNotEqual(after_encrypting["security"], "done")
        after_bootloader = {row["key"]: row["status"]
                            for row in progress_rows("Creating user")}
        self.assertEqual(after_bootloader["security"], "done")

    def test_no_progress_row_carries_a_percentage(self) -> None:
        for stage in STAGES:
            for row in progress_rows(stage):
                self.assertNotIn("percent", row)

    def test_the_companion_cannot_be_happy_about_a_failure(self) -> None:
        for stage in STAGES:
            self.assertEqual(companion_phase_for("failed", stage), "error")
            self.assertNotEqual(companion_phase_for("cancelled", stage), "success")

    def test_the_companion_is_only_working_past_the_write_boundary(self) -> None:
        before = STAGES[WRITE_BOUNDARY - 1]
        after = STAGES[WRITE_BOUNDARY]
        self.assertEqual(companion_phase_for("installing", before), "planning")
        self.assertEqual(companion_phase_for("installing", after), "working")


class TheDBusExecutorRefusesOffAnISO(unittest.TestCase):
    """It cannot be exercised here; it can be shown to fail closed."""

    def test_no_bus_address_means_no_installation(self) -> None:
        executor = AnacondaDBusExecutor(bus_address="unix:path=/nonexistent/bunny-test")
        with self.assertRaises(ExecutorUnavailable):
            executor.preflight()

    def test_a_missing_address_file_is_reported_as_not_an_installer(self) -> None:
        """It refuses, and says which prerequisite is missing.

        The exact sentence differs by platform and both are correct: without
        PyGObject it cannot reach any bus, and with PyGObject but no Anaconda it
        cannot find the address file. Asserting one of them made this fail on
        Windows for a reason that was not a defect, so what is asserted is that
        the refusal names something actionable.
        """
        executor = AnacondaDBusExecutor()
        executor.BUS_ADDRESS_FILE = Path("/nonexistent/anaconda/bus.address")
        with self.assertRaises(ExecutorUnavailable) as caught:
            executor.preflight()
        message = str(caught.exception)
        self.assertTrue(
            "not an installer environment" in message or "GIO is required" in message,
            f"the refusal does not say what is missing: {message}",
        )

    def test_the_required_methods_are_stated_rather_than_assumed(self) -> None:
        """These three were verified against anaconda-core 44.30-2.fc44.

        Not by booting: the package was downloaded and
        `pyanaconda/modules/boss/boss_interface.py` read. All three exist with
        the signatures the adapter relies on. `preflight` still introspects,
        because the anaconda on the medium is what decides and it need not be
        this version.
        """
        # StartModulesWithTask joined the list after run 15 of Journey A: a
        # bare DBus-activated Boss has no modules, and a module-less Boss
        # "completed" an installation of nothing. Verified present by
        # introspecting the Boss inside the built live image.
        self.assertEqual(
            AnacondaDBusExecutor.REQUIRED_BOSS_METHODS,
            ("StartModulesWithTask", "ReadKickstartFile",
             "CollectRequirements", "InstallWithTasks"))
        self.assertEqual(
            AnacondaDBusExecutor.REQUIRED_TASK_MEMBERS,
            ("Start", "Finish", "IsRunning", "Name"))

    def test_a_kickstart_report_message_is_flattened_for_a_person(self) -> None:
        """`ReadKickstartFile` returns a report, and it must not be discarded.

        An earlier version ignored the return value, so a kickstart Anaconda
        could not parse produced no error and the install proceeded to
        `InstallWithTasks` regardless. The structure is a KickstartReport whose
        `error-messages` list being empty is what "valid" means.
        """
        flatten = AnacondaDBusExecutor._message
        self.assertEqual(
            flatten({"message": "Unknown command: ostreecontainr", "line-number": 12}),
            "line 12: Unknown command: ostreecontainr")
        self.assertEqual(flatten({"message": "something", "line-number": 0}), "something")
        self.assertEqual(flatten({}), "")

        class Variant:
            def __init__(self, value): self._value = value
            def unpack(self): return self._value

        self.assertEqual(
            flatten({"message": Variant("wrapped"), "line-number": Variant(3)}),
            "line 3: wrapped")


if __name__ == "__main__":
    unittest.main()
