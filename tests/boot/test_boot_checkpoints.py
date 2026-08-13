"""The boot-chain classifier, against serial logs shaped like the real ones.

The point of the ladder is that it distinguishes failures. So the tests here are
mostly logs that stop at different rungs, each asserting that the classifier
names the right one — because a classifier that reported FAIL for everything
would pass a test suite that only checked the happy path, and would be exactly
as useful as the "timeout" it was written to replace.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "build/scripts/classify-boot-checkpoints.py"
STATS = ROOT / "build/scripts/screen-stats.py"


def _load(path: Path, name: str):
    loader = SourceFileLoader(name, str(path))
    spec = spec_from_loader(name, loader)
    assert spec is not None
    module = module_from_spec(spec)
    loader.exec_module(module)
    return module


classifier = _load(SCRIPT, "bunny_classify_boot_checkpoints")
stats_tool = _load(STATS, "bunny_screen_stats")


# Fragments in the order a real boot emits them. Each stage is what the console
# shows between one checkpoint and the next.
FIRMWARE = ["BdsDxe: loading Boot0001", "Booting from DVD/CD..."]
GRUB = ["GNU GRUB  version 2.12", "   Try or Install Bunny OS"]
KERNEL = [
    "[    0.000000] Linux version 7.1.5-200.fc44.x86_64 (mockbuild@fedora)",
    "[    0.000000] Command line: root=live:CDLABEL=Bunny-OS-Beta rd.live.image console=ttyS0,115200n8",
]
INITRAMFS = [
    "[    2.101] systemd[1]: systemd 258 running in initrd.",
    "[    2.310] systemd[1]: Starting dracut-cmdline.service...",
    "[    2.980] systemd[1]: Starting dracut-initqueue.service...",
]
LIVE_ROOT = [
    "dracut: root was live:CDLABEL=Bunny-OS-Beta, is now live:/dev/disk/by-label/Bunny-OS-Beta",
    "[    6.220] systemd[1]: Mounted /run/initramfs/live.",
    "[    7.410] systemd[1]: Mounting /sysroot...",
    "[    8.002] systemd[1]: Reached target initrd-root-fs.target - Initrd Root File System.",
]
SWITCH = [
    "[    9.115] systemd[1]: Starting initrd-switch-root.service - Switch Root...",
    "[    9.330] systemd[1]: Switching root.",
]
REAL_ROOT = [
    "[    9.900] systemd[1]: systemd 258 running in system mode.",
    "[   10.400] systemd[1]: Started D-Bus System Message Bus.",
    "[   11.100] systemd[1]: Reached target basic.target - Basic System.",
    "[   14.200] systemd[1]: Reached target multi-user.target - Multi-User System.",
]
GRAPHICAL = [
    "[   15.300] systemd[1]: Starting GNOME Display Manager...",
    "[   16.100] systemd[1]: Started GNOME Display Manager.",
    "[   17.000] systemd[1]: Reached target graphical.target - Graphical Interface.",
]
SESSION = [
    "[   18.400] systemd[1]: Created slice user-1000.slice - User Slice of UID 1000.",
    "[   18.900] systemd[1]: Started User Manager for UID 1000.",
    "[   19.100] systemd[1]: Started Session 1 of User bunny-live.",
]

STAGES = [FIRMWARE, GRUB, KERNEL, INITRAMFS, LIVE_ROOT, SWITCH, REAL_ROOT,
          GRAPHICAL, SESSION]


def log_through(count: int, extra: list[str] | None = None) -> str:
    lines: list[str] = []
    for stage in STAGES[:count]:
        lines.extend(stage)
    if extra:
        lines.extend(extra)
    return "\n".join(lines) + "\n"


class ClassifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = Path(tempfile.mkdtemp())
        self.screens = self.scratch / "screens"
        self.screens.mkdir()
        # A frame that is not blank, so image-backed checkpoints are decided by
        # the serial log unless a test says otherwise.
        for name in ("01-grub-menu", "03-session"):
            (self.screens / f"{name}.png").write_bytes(b"\x89PNG\r\n\x1a\n")
            (self.screens / f"{name}.stats.json").write_text(json.dumps(
                {"path": f"{name}.ppm", "distinctColours": 4096,
                 "standardDeviation": 61.4, "blank": False}))

    def classify(self, text: str, outcome: str = "graphical") -> dict:
        serial = self.scratch / "serial.log"
        serial.write_text(text, encoding="utf-8")
        return classifier.classify(serial, self.screens, outcome)

    def status(self, report: dict) -> dict[str, str]:
        return {r["checkpoint"]: r["status"] for r in report["checkpoints"]}

    def test_a_complete_boot_passes_every_checkpoint(self) -> None:
        report = self.classify(log_through(9))
        self.assertEqual(report["status"], "PASS", self.status(report))
        self.assertEqual(report["reached"], "BOOT-9")

    def test_the_failure_this_medium_actually_had(self) -> None:
        # Reached GRUB, kernel, initramfs; then no root and switch-root fails.
        text = log_through(4, [
            "[   99.100] dracut-initqueue[612]: Warning: dracut-initqueue: timeout, still waiting for following initqueue hooks:",
            "[   99.200] dracut: Warning: /dev/disk/by-label/Bunny-OS-Beta does not exist",
            "[  100.010] systemd[1]: Failed to start initrd-switch-root.service - Switch Root.",
            "[  100.400] systemd[1]: Starting emergency.service - Emergency Shell...",
            "[  100.900] You are in emergency mode.",
        ])
        report = self.classify(text, outcome="boot-failure")
        status = self.status(report)
        self.assertEqual(status["BOOT-3"], "PASS")
        self.assertEqual(status["BOOT-4"], "FAIL")
        # Everything after the first failure is not-reached, not nine failures.
        for name in ("BOOT-5", "BOOT-6", "BOOT-7", "BOOT-8", "BOOT-9"):
            self.assertEqual(status[name], "NOT-REACHED", name)
        self.assertEqual(report["reached"], "BOOT-3")
        refuted = next(r for r in report["checkpoints"] if r["checkpoint"] == "BOOT-4")
        # The earliest refutation wins, and here that is the initqueue timeout
        # rather than the by-label warning that follows it. Either names the
        # same fault; asserting on whichever came first would be asserting on
        # the order dracut happens to print two lines in.
        self.assertRegex(refuted["refutedBy"]["text"],
                         r"timeout|does not exist|emergency")

    def test_a_negative_beats_a_positive_in_the_same_stage(self) -> None:
        # The initramfs both starts and then gives up. That is not a pass.
        text = log_through(4, ["[  60.0] Entering emergency mode. Exit the shell to continue."])
        self.assertEqual(self.status(self.classify(text))["BOOT-4"], "FAIL")

    def test_real_userspace_is_not_claimed_from_initramfs_output(self) -> None:
        # This log reaches the initramfs and stops, but the initramfs' own
        # systemd printed 'Reached target basic.target'. Without the ordering
        # rule BOOT-7 would match it and report userspace on a machine sitting
        # in an initramfs.
        text = log_through(5, [
            "[    8.5] systemd[1]: Reached target basic.target - Basic System.",
            "[    8.9] systemd[1]: Started D-Bus System Message Bus.",
        ])
        status = self.status(self.classify(text))
        self.assertEqual(status["BOOT-5"], "PASS")
        self.assertEqual(status["BOOT-6"], "FAIL")
        self.assertEqual(status["BOOT-7"], "NOT-REACHED")

    def test_switch_root_reached_but_failed_is_a_failure(self) -> None:
        text = log_through(6, [
            "[    9.6] systemd[1]: initrd-switch-root.service: Failed with result 'exit-code'.",
            "[    9.7] systemd[1]: Failed to start initrd-switch-root.service - Switch Root.",
        ])
        status = self.status(self.classify(text))
        self.assertEqual(status["BOOT-5"], "PASS")
        self.assertEqual(status["BOOT-6"], "FAIL")

    def test_a_boot_that_stops_at_the_graphical_target(self) -> None:
        status = self.status(self.classify(log_through(8)))
        self.assertEqual(status["BOOT-8"], "PASS")
        self.assertEqual(status["BOOT-9"], "FAIL")

    def test_a_blank_frame_fails_the_checkpoint_that_rests_on_it(self) -> None:
        # The realistic shape: a serial console that never sees GRUB, because
        # GRUB does not write to one, plus a black screen. With no evidence of
        # either kind there is nothing left to establish the checkpoint, and
        # passing it would be passing on nothing at all.
        (self.screens / "01-grub-menu.stats.json").write_text(json.dumps(
            {"path": "01-grub-menu.ppm", "distinctColours": 1,
             "standardDeviation": 0.0, "blank": True}))
        text = "\n".join(FIRMWARE + KERNEL + INITRAMFS) + "\n"
        report = self.classify(text)
        status = self.status(report)
        self.assertEqual(status["BOOT-1"], "PASS")
        self.assertEqual(status["BOOT-2"], "FAIL")
        self.assertEqual(status["BOOT-3"], "NOT-REACHED")
        entry = next(r for r in report["checkpoints"] if r["checkpoint"] == "BOOT-2")
        self.assertIn("blank", entry["refutedBy"]["text"])

    def test_grub_text_on_serial_still_establishes_the_menu(self) -> None:
        # Some firmware/GRUB combinations do echo to serial. When they do, that
        # is evidence and a blank capture does not overrule it.
        (self.screens / "01-grub-menu.stats.json").write_text(json.dumps(
            {"path": "01-grub-menu.ppm", "distinctColours": 1,
             "standardDeviation": 0.0, "blank": True}))
        self.assertEqual(self.status(self.classify(log_through(9)))["BOOT-2"], "PASS")

    def test_grub_is_established_by_the_frame_when_serial_says_nothing(self) -> None:
        # The case that matters on every real run. GRUB renders to the video
        # console and writes no byte to ttyS0, so a serial log from a perfectly
        # good boot contains no GRUB text at all. A BOOT-2 that needed one would
        # fail on every correct medium there has ever been.
        text = "\n".join(FIRMWARE + KERNEL + INITRAMFS + LIVE_ROOT + SWITCH
                         + REAL_ROOT + GRAPHICAL + SESSION) + "\n"
        self.assertNotIn("GNU GRUB", text)
        report = self.classify(text)
        status = self.status(report)
        self.assertEqual(status["BOOT-2"], "PASS")
        entry = next(r for r in report["checkpoints"] if r["checkpoint"] == "BOOT-2")
        self.assertIn("established by the frame", entry["matched"]["text"])
        self.assertEqual(report["status"], "PASS")

    def test_boot_nine_needs_both_the_session_and_the_frame(self) -> None:
        # A session that started is not a window that drew.
        (self.screens / "03-session.stats.json").write_text(json.dumps(
            {"path": "03-session.ppm", "distinctColours": 1,
             "standardDeviation": 0.0, "blank": True}))
        report = self.classify(log_through(9))
        status = self.status(report)
        self.assertEqual(status["BOOT-8"], "PASS")
        self.assertEqual(status["BOOT-9"], "FAIL")
        entry = next(r for r in report["checkpoints"] if r["checkpoint"] == "BOOT-9")
        self.assertIn("blank", entry["refutedBy"]["text"])
        # and the serial half is still reported, so the diagnosis is "the
        # session started and nothing drew" rather than "BOOT-9 failed"
        self.assertIsNotNone(entry["matched"])

    def test_boot_nine_with_no_frame_at_all_fails(self) -> None:
        (self.screens / "03-session.stats.json").unlink()
        (self.screens / "03-session.png").unlink()
        report = self.classify(log_through(9))
        self.assertEqual(self.status(report)["BOOT-9"], "FAIL")
        entry = next(r for r in report["checkpoints"] if r["checkpoint"] == "BOOT-9")
        self.assertIn("no frame was captured", entry["refutedBy"]["text"])

    def test_a_blank_frame_does_not_fail_the_checkpoint_it_only_accompanies(self) -> None:
        # The same capture is BOOT-1's evidence and BOOT-2's. A machine that
        # started and produced no video has not failed to start, and reporting
        # it as one would name the wrong stage — which is the whole point of
        # having stages.
        (self.screens / "01-grub-menu.stats.json").write_text(json.dumps(
            {"path": "01-grub-menu.ppm", "distinctColours": 1,
             "standardDeviation": 0.0, "blank": True}))
        status = self.status(self.classify(log_through(9)))
        self.assertEqual(status["BOOT-1"], "PASS")

    def test_image_backed_checkpoints_keep_needing_a_look(self) -> None:
        report = self.classify(log_through(9))
        looks = {r["checkpoint"] for r in report["checkpoints"] if r["needsLook"]}
        self.assertEqual(looks, {"BOOT-2", "BOOT-9"})

    def test_systemds_coloured_console_copy_is_matched_too(self) -> None:
        # The real serial log carries every message twice: plain through kmsg,
        # and coloured from systemd's own status output. A negative pattern that
        # only matched the plain copy would keep working right up until the day
        # a failure appeared in the coloured one alone.
        coloured = (
            "\x1b[[0;32m  OK  \x1b[0m] Reached target \x1b[0;1;39minitrd.target\x1b[0m"
            " - Initrd Default Target.\n"
            "         Starting \x1b[0;1;39minitrd-switch-root.service\x1b[0m - Switch Root...\n"
            "[\x1b[0;1;31mFAILED\x1b[0m] Failed to start \x1b[0;1;39minitrd-switch-root.service"
            "\x1b[0m - Switch Root.\n"
        )
        text = "\n".join(FIRMWARE + KERNEL + INITRAMFS + LIVE_ROOT) + "\n" + coloured
        report = self.classify(text, outcome="boot-failure")
        status = self.status(report)
        self.assertEqual(status["BOOT-5"], "PASS")
        self.assertEqual(status["BOOT-6"], "FAIL")
        entry = next(r for r in report["checkpoints"] if r["checkpoint"] == "BOOT-6")
        self.assertIn("Failed to start initrd-switch-root.service",
                      entry["refutedBy"]["text"])
        self.assertNotIn("\x1b", entry["refutedBy"]["text"])

    def test_evidence_is_quoted_around_the_match_not_from_the_start_of_the_line(self) -> None:
        # GRUB positions with escape sequences and emits no newline, so its
        # whole screen and the kernel's first output arrive as one line
        # thousands of characters long. Quoting its beginning reported the
        # kernel's start as "Press enter to boot the selected OS".
        collapsed = (
            "GNU GRUB  version 2.12    Try or Install Bunny OS    Safe Graphics"
            + "    " * 40
            + "Press enter to boot the selected OS, `e' to edit the commands."
            + "    " * 40
            + "[    0.000000] Linux version 7.1.5-200.fc44.x86_64 (mockbuild@fedora)"
        )
        text = collapsed + "\n" + "\n".join(INITRAMFS + LIVE_ROOT + SWITCH
                                            + REAL_ROOT + GRAPHICAL + SESSION) + "\n"
        report = self.classify(text)
        kernel = next(r for r in report["checkpoints"] if r["checkpoint"] == "BOOT-3")
        self.assertEqual(kernel["status"], "PASS")
        self.assertIn("Linux version 7.1.5-200.fc44.x86_64", kernel["matched"]["text"])
        self.assertNotIn("Press enter to boot", kernel["matched"]["text"])

    def test_an_empty_log_reaches_nothing(self) -> None:
        report = self.classify("")
        self.assertIsNone(report["reached"])
        self.assertEqual(report["status"], "FAIL")

    def test_a_kernel_panic_fails_at_the_kernel(self) -> None:
        text = log_through(3, ["[    4.0] Kernel panic - not syncing: VFS: Unable to mount root fs"])
        status = self.status(self.classify(text))
        self.assertEqual(status["BOOT-3"], "FAIL")
        self.assertEqual(status["BOOT-4"], "NOT-REACHED")


class CommandLineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = Path(tempfile.mkdtemp())
        screens = self.scratch / "screens"
        screens.mkdir()
        # These exercise the exit-status plumbing, so they need the frames the
        # ladder now requires — BOOT-9 does not pass on a serial log alone.
        for name in ("01-grub-menu", "03-session"):
            (screens / f"{name}.png").write_bytes(b"\x89PNG\r\n\x1a\n")
            (screens / f"{name}.stats.json").write_text(json.dumps(
                {"path": f"{name}.ppm", "distinctColours": 4096,
                 "standardDeviation": 61.4, "blank": False}))

    def test_exit_status_reflects_the_ladder(self) -> None:
        serial = self.scratch / "serial.log"
        serial.write_text(log_through(9), encoding="utf-8")
        finished = subprocess.run(
            [sys.executable, str(SCRIPT), "--serial", str(serial),
             "--screens", str(self.scratch / "screens"),
             "--harness-outcome", "graphical",
             "--json", str(self.scratch / "checkpoints.json")],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(finished.returncode, 0, finished.stdout + finished.stderr)
        report = json.loads((self.scratch / "checkpoints.json").read_text())
        self.assertEqual(report["status"], "PASS")

    def test_a_failed_boot_exits_two_and_names_the_rung(self) -> None:
        serial = self.scratch / "serial.log"
        serial.write_text(log_through(3), encoding="utf-8")
        finished = subprocess.run(
            [sys.executable, str(SCRIPT), "--serial", str(serial),
             "--screens", str(self.scratch / "screens"),
             "--harness-outcome", "timeout"],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(finished.returncode, 2)
        self.assertIn("BOOT-3", finished.stderr + finished.stdout)


class ScreenStatsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = Path(tempfile.mkdtemp())

    def ppm(self, name: str, width: int, height: int, pixels: bytes) -> Path:
        path = self.scratch / name
        path.write_bytes(f"P6\n{width} {height}\n255\n".encode() + pixels)
        return path

    def test_a_uniform_frame_is_blank(self) -> None:
        path = self.ppm("black.ppm", 64, 64, b"\x00\x00\x00" * (64 * 64))
        self.assertTrue(stats_tool.summarise(path)["blank"])

    def test_a_uniform_grey_frame_is_also_blank(self) -> None:
        path = self.ppm("grey.ppm", 64, 64, b"\x80\x80\x80" * (64 * 64))
        self.assertTrue(stats_tool.summarise(path)["blank"])

    def test_a_frame_with_content_is_not_blank(self) -> None:
        pixels = bytearray()
        for index in range(64 * 64):
            value = (index * 7) % 256
            pixels += bytes((value, (value * 3) % 256, (value * 5) % 256))
        path = self.ppm("busy.ppm", 64, 64, bytes(pixels))
        report = stats_tool.summarise(path)
        self.assertFalse(report["blank"])
        self.assertGreater(report["distinctColours"], 10)

    def test_a_comment_in_the_header_is_tolerated(self) -> None:
        path = self.scratch / "comment.ppm"
        path.write_bytes(b"P6\n# written by qemu\n8 8\n255\n" + b"\x10\x20\x30" * 64)
        self.assertEqual(stats_tool.summarise(path)["width"], 8)

    def test_a_file_that_is_not_a_ppm_is_rejected(self) -> None:
        path = self.scratch / "not.ppm"
        path.write_bytes(b"\x89PNG\r\n\x1a\n")
        with self.assertRaises(ValueError):
            stats_tool.summarise(path)


if __name__ == "__main__":
    unittest.main()
