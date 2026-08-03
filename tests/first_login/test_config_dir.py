# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Stage 3 — behavioural tests for the directory guard.

Every path condition Stage 1 requires a defined behaviour for is driven here
against the real program. The conditions that need a second uid are marked and
skipped off-Linux and unprivileged, rather than being asserted by reading the
source: a skipped test that says why is honest, a source grep that pretends to
be a behavioural test is not.

The last class mutation-tests the refusals: it disables one guard clause at a
time and proves the unsafe state is then accepted, so each refusal is shown to
be load-bearing rather than decorative.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
GUARD_PATH = ROOT / "scripts/bunny-config-dir.py"

_spec = importlib.util.spec_from_file_location("bunny_config_dir", GUARD_PATH)
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)

POSIX = os.name == "posix" and hasattr(os, "getuid")
ROOTED = POSIX and os.geteuid() == 0

requires_posix = unittest.skipUnless(
    POSIX, "symlink and ownership semantics are POSIX-only")
requires_root = unittest.skipUnless(
    ROOTED, "needs a second uid to create a directory this user does not own")


def setUpModule():
    """The guard reads uids and manipulates symlinks; there is no meaningful
    Windows behaviour to assert. The qualification gate runs on the Linux
    builder, which is where these must pass — a green Windows run that
    silently skipped them would be worse than an honest skip."""
    if not POSIX:
        raise unittest.SkipTest(
            "bunny-config-dir is a Linux user-session program; its behaviour "
            "is asserted on the Linux builder, not on this host")


class GuardTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.bunny = self.home / ".config/bunny-os"
        self.systemd_user = self.home / ".config/systemd/user"

    def run_guard(self) -> int:
        previous = os.environ.get("HOME")
        os.environ["HOME"] = str(self.home)
        try:
            return guard.main()
        finally:
            if previous is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = previous

    def mode_of(self, path: Path) -> int:
        return stat.S_IMODE(path.lstat().st_mode)


class CreationTests(GuardTestCase):
    def test_absent_directories_are_created(self):
        self.assertEqual(self.run_guard(), 0)
        for path in (self.bunny, self.systemd_user):
            self.assertTrue(path.is_dir(), f"{path} was not created")
            self.assertEqual(self.mode_of(path), 0o700)

    def test_creation_works_when_config_is_absent_entirely(self):
        """A genuinely fresh home has no .config at all."""
        self.assertFalse((self.home / ".config").exists())
        self.assertEqual(self.run_guard(), 0)
        self.assertTrue(self.bunny.is_dir())

    def test_existing_config_directory_is_reused(self):
        (self.home / ".config").mkdir()
        (self.home / ".config/other-app").mkdir()
        self.assertEqual(self.run_guard(), 0)
        self.assertTrue(self.bunny.is_dir())
        self.assertTrue((self.home / ".config/other-app").is_dir(),
                        "an unrelated application's directory was disturbed")

    def test_repeated_runs_preserve_state(self):
        """9. First-run configuration overwritten on second login."""
        self.assertEqual(self.run_guard(), 0)
        marker = self.bunny / "first-boot-complete.json"
        marker.write_text('{"launchBunnyAtLogin": true}', encoding="utf-8")
        inode = self.bunny.lstat().st_ino

        self.assertEqual(self.run_guard(), 0)
        self.assertEqual(self.bunny.lstat().st_ino, inode,
                         "the directory was replaced rather than reused")
        self.assertEqual(marker.read_text(encoding="utf-8"),
                         '{"launchBunnyAtLogin": true}',
                         "first-run configuration was overwritten")

    @requires_posix
    def test_mode_is_corrected_without_touching_contents(self):
        """8. World-readable or world-writable directory accepted."""
        self.bunny.mkdir(parents=True)
        self.bunny.chmod(0o777)
        kept = self.bunny / "first-boot-complete.json"
        kept.write_text("{}", encoding="utf-8")
        kept_mode = self.mode_of(kept)

        self.assertEqual(self.run_guard(), 0)
        self.assertEqual(self.mode_of(self.bunny), 0o700,
                         "a world-writable Bunny directory was accepted")
        self.assertEqual(self.mode_of(kept), kept_mode,
                         "the guard changed a mode inside the directory; it "
                         "must not recurse")


class RefusalTests(GuardTestCase):
    """6, 7 — unsafe path types are refused, never followed or replaced."""

    @requires_posix
    def test_symlink_is_refused_and_left_alone(self):
        elsewhere = self.home / "elsewhere"
        elsewhere.mkdir()
        (self.home / ".config").mkdir()
        os.symlink(elsewhere, self.bunny)

        self.assertEqual(self.run_guard(), 1)
        self.assertTrue(self.bunny.is_symlink(),
                        "the guard replaced the symlink instead of refusing")
        self.assertEqual(list(elsewhere.iterdir()), [],
                         "the guard wrote through the symlink")

    @requires_posix
    def test_symlink_escaping_the_home_is_refused(self):
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: outside.rmdir())
        (self.home / ".config").mkdir()
        os.symlink(outside, self.bunny)

        self.assertEqual(self.run_guard(), 1)
        self.assertEqual(list(outside.iterdir()), [],
                         "the guard followed a link out of the home and "
                         "would have made that target writable to the "
                         "sandboxed service")

    @requires_posix
    def test_dangling_symlink_is_refused(self):
        (self.home / ".config").mkdir()
        os.symlink(self.home / "nowhere-at-all", self.bunny)

        self.assertEqual(self.run_guard(), 1)
        self.assertTrue(self.bunny.is_symlink())
        self.assertFalse((self.home / "nowhere-at-all").exists(),
                         "the guard created the link's missing target")

    def test_regular_file_is_refused_not_replaced(self):
        (self.home / ".config").mkdir()
        self.bunny.write_text("not a directory", encoding="utf-8")

        self.assertEqual(self.run_guard(), 1)
        self.assertTrue(self.bunny.is_file(),
                        "the guard deleted a regular file to make room")
        self.assertEqual(self.bunny.read_text(encoding="utf-8"),
                         "not a directory")

    @requires_root
    def test_directory_owned_by_another_user_is_refused(self):
        """7. Wrong-owner directory silently accepted.

        systemd-tmpfiles in --user mode exits 0 here and leaves the ownership
        alone, which is the whole reason this check exists.
        """
        self.bunny.mkdir(parents=True)
        os.chown(self.bunny, 12345, 12345)
        os.chown(self.home / ".config", os.getuid(), os.getgid())

        self.assertEqual(self.run_guard(), 1)
        self.assertEqual(self.bunny.lstat().st_uid, 12345,
                         "the guard took ownership of another account's "
                         "directory")

    @requires_posix
    def test_inaccessible_parent_is_refused_cleanly(self):
        config = self.home / ".config"
        config.mkdir()
        config.chmod(0o000)
        self.addCleanup(lambda: config.chmod(0o755))

        if ROOTED:
            self.skipTest("root bypasses directory permissions")
        self.assertEqual(self.run_guard(), 1)

    def test_one_bad_path_does_not_hide_the_other(self):
        """Both ReadWritePaths entries are checked even when the first
        refuses; a guard that stops at the first failure would report a home
        as repaired when only half of it was."""
        (self.home / ".config").mkdir()
        self.bunny.write_text("not a directory", encoding="utf-8")

        self.assertEqual(self.run_guard(), 1)
        self.assertTrue(self.systemd_user.is_dir(),
                        "the guard abandoned the second path after the first "
                        "refused")


class SeparateAccountTests(GuardTestCase):
    """10. User A receives ownership belonging to user B."""

    def test_two_homes_get_their_own_directories(self):
        first = self.home
        second = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(second,
                                                            ignore_errors=True))
        self.assertEqual(self.run_guard(), 0)

        self.home = second
        self.bunny = second / ".config/bunny-os"
        self.assertEqual(self.run_guard(), 0)

        self.assertTrue((first / ".config/bunny-os").is_dir())
        self.assertTrue((second / ".config/bunny-os").is_dir())
        self.assertNotEqual((first / ".config/bunny-os").lstat().st_ino,
                            (second / ".config/bunny-os").lstat().st_ino,
                            "both accounts resolved to one directory")


class MutationTests(GuardTestCase):
    """Each refusal is disabled in turn; the unsafe state must then be
    accepted. A check that cannot be shown to fail when removed was never
    testing anything."""

    def _patch(self, attribute: str, replacement):
        original = getattr(guard, attribute)
        setattr(guard, attribute, replacement)
        self.addCleanup(lambda: setattr(guard, attribute, original))

    @requires_posix
    def test_symlink_refusal_is_load_bearing(self):
        elsewhere = self.home / "elsewhere"
        elsewhere.mkdir()
        (self.home / ".config").mkdir()
        os.symlink(elsewhere, self.bunny)
        self.assertEqual(self.run_guard(), 1)

        # Remove only the symlink clause: report every link as a plain
        # directory and let the rest of the guard proceed.
        self._patch("verify_directory", _without_symlink_check(guard))
        self.assertEqual(
            self.run_guard(), 0,
            "with the symlink clause removed the guard still refused, so the "
            "clause is not what produced the refusal")

    def test_non_directory_refusal_is_load_bearing(self):
        (self.home / ".config").mkdir()
        self.bunny.write_text("not a directory", encoding="utf-8")
        self.assertEqual(self.run_guard(), 1)

        self._patch("verify_directory", _accepting_everything())
        self.assertEqual(
            self.run_guard(), 0,
            "the non-directory refusal is not what produced the failure")

    @requires_root
    def test_ownership_refusal_is_load_bearing(self):
        self.bunny.mkdir(parents=True)
        os.chown(self.bunny, 12345, 12345)
        self.assertEqual(self.run_guard(), 1)

        self._patch("verify_directory", _without_ownership_check(guard))
        self.assertEqual(
            self.run_guard(), 0,
            "the ownership refusal is not what produced the failure")

    def test_the_guard_reports_failure_at_all(self):
        """The harness itself: a guard whose main() always returned 0 would
        make every refusal test above vacuous."""
        (self.home / ".config").mkdir()
        self.bunny.write_text("not a directory", encoding="utf-8")
        self.assertEqual(self.run_guard(), 1)
        self.assertNotEqual(
            self.run_guard(), 0,
            "main() returns success for a refused path, so no refusal test "
            "in this module can fail")


def _accepting_everything():
    """The whole verification removed: whatever is at the path is accepted."""
    def verify(path, uid, gid):
        return "verified"
    return verify


def _without_symlink_check(module):
    def verify(path, uid, gid):
        if path.is_symlink():
            return "verified"
        return module.__dict__["_original_verify"](path, uid, gid)
    return verify


def _without_ownership_check(module):
    def verify(path, uid, gid):
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            return "verified"
        return module.__dict__["_original_verify"](path, uid, gid)
    return verify


guard._original_verify = guard.verify_directory


if __name__ == "__main__":
    unittest.main()
