# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The ownership rule, checked in the namespace the companion actually runs in.

Every other test in this suite runs in the initial user namespace, where a
root-owned file reports uid 0 and the rule passes. `bunny-companion.service`
does not: it is a user unit with `ProtectSystem=strict`, so systemd gives it a
user namespace mapping one uid, and the kernel reports every root-owned file to
it as the overflow uid.

The effect on the shipped image was complete — speech input reported
`STT_MODEL_CORRUPT` and the microphone button was permanently disabled — and it
was invisible to the whole suite, because the suite is on the other side of the
namespace. So the namespace is simulated here rather than assumed away.
"""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from companion import ownership
from companion.desktop.entries import DesktopRefused, _entry_file_safe
from companion.speech.recognizers import _path_safe

#: The map systemd writes for an unprivileged user unit: one uid, and root is
#: not in it. Copied from a running Bunny OS guest.
SANDBOXED_MAP = "      1000       1000          1\n"
#: What the initial namespace reports.
INITIAL_MAP = "         0          0 4294967295\n"


#: The two callers guard their ownership check on POSIX, so they cannot be
#: exercised on Windows at all. The rule itself can be, and is.
POSIX_ONLY = unittest.skipUnless(
    os.name == "posix" and hasattr(os, "getuid"),
    "the ownership check only runs on POSIX")


def _with_uid_map(text: str):
    """Point the ownership module's uid_map read at a file we control."""
    handle = tempfile.NamedTemporaryFile("w", suffix=".uid_map", delete=False)
    handle.write(text)
    handle.close()
    return mock.patch.object(ownership, "_UID_MAP_PATH", Path(handle.name))


class _Namespace:
    """uid_map, overflow uid and getuid together, so the rule can be exercised
    on a host that has no getuid at all."""

    def __init__(self, text: str, *, uid: int = 1000, overflow: int = 65534) -> None:
        self._patches = [
            _with_uid_map(text),
            mock.patch.object(ownership, "_overflow_uid", return_value=overflow),
            mock.patch.object(ownership.os, "getuid", create=True, return_value=uid),
        ]

    def __enter__(self) -> None:
        for patch in self._patches:
            patch.start()

    def __exit__(self, *exception) -> None:
        for patch in reversed(self._patches):
            patch.stop()


class RootUnmappedTests(unittest.TestCase):
    def test_the_initial_namespace_maps_root(self) -> None:
        with _with_uid_map(INITIAL_MAP):
            self.assertFalse(ownership._root_is_unmapped())

    def test_a_single_uid_map_does_not_map_root(self) -> None:
        with _with_uid_map(SANDBOXED_MAP):
            self.assertTrue(ownership._root_is_unmapped())

    def test_a_map_that_covers_root_explicitly_is_mapped(self) -> None:
        with _with_uid_map("0 100000 65536\n"):
            self.assertFalse(ownership._root_is_unmapped())

    def test_an_unreadable_map_refuses_rather_than_trusts(self) -> None:
        with mock.patch.object(ownership, "_UID_MAP_PATH", Path("/nonexistent/uid_map")):
            self.assertFalse(ownership._root_is_unmapped())


class TrustedOwnerTests(unittest.TestCase):
    def test_the_overflow_uid_is_refused_outside_a_namespace(self) -> None:
        with _Namespace(INITIAL_MAP):
            self.assertNotIn(65534, ownership.trusted_owner_ids())

    def test_the_overflow_uid_is_accepted_when_root_is_unmapped(self) -> None:
        with _Namespace(SANDBOXED_MAP):
            self.assertIn(65534, ownership.trusted_owner_ids())

    def test_root_and_this_user_are_always_accepted(self) -> None:
        for text in (INITIAL_MAP, SANDBOXED_MAP):
            with self.subTest(map=text.strip()), _Namespace(text, uid=1000):
                trusted = ownership.trusted_owner_ids()
                self.assertIn(0, trusted)
                self.assertIn(1000, trusted)

    def test_an_arbitrary_third_party_is_never_accepted(self) -> None:
        for text in (INITIAL_MAP, SANDBOXED_MAP):
            with self.subTest(map=text.strip()), _Namespace(text, uid=1000):
                self.assertFalse(ownership.owner_is_trusted(4242))


@POSIX_ONLY
class CallerTests(unittest.TestCase):
    """The two callers, each given a file the kernel reports as overflow-owned.

    `lstat`/`stat` are faked rather than the file's ownership changed, because
    changing it needs root and the point is the *reported* uid, which is what a
    namespace changes.
    """

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "owned-by-the-overflow-uid"

    def _stat_result(self, mode: int, uid: int) -> os.stat_result:
        return os.stat_result((mode, 0, 0, 1, uid, 0, 0, 0, 0, 0))

    def test_the_model_loader_refuses_an_overflow_owner_outside_a_namespace(self) -> None:
        self.path.mkdir()
        fake = self._stat_result(0o040755, 65534)
        with _Namespace(INITIAL_MAP), mock.patch.object(Path, "lstat", return_value=fake):
            safe, reason = _path_safe(self.path, require_directory=True)
        self.assertFalse(safe)
        self.assertIn("65534", reason)

    def test_the_model_loader_accepts_an_overflow_owner_inside_the_sandbox(self) -> None:
        self.path.mkdir()
        fake = self._stat_result(0o040755, 65534)
        with _with_uid_map(SANDBOXED_MAP), \
                mock.patch.object(ownership, "_overflow_uid", return_value=65534), \
                mock.patch.object(Path, "lstat", return_value=fake):
            safe, reason = _path_safe(self.path, require_directory=True)
        self.assertTrue(safe, reason)

    def test_a_group_writable_model_is_still_refused_inside_the_sandbox(self) -> None:
        """The other half of the rule must not travel with the first."""
        self.path.mkdir()
        fake = self._stat_result(0o040775, 65534)
        with _with_uid_map(SANDBOXED_MAP), \
                mock.patch.object(ownership, "_overflow_uid", return_value=65534), \
                mock.patch.object(Path, "lstat", return_value=fake):
            safe, reason = _path_safe(self.path, require_directory=True)
        self.assertFalse(safe)
        self.assertIn("writable by group or other", reason)

    def test_a_desktop_entry_owned_by_the_overflow_uid_is_refused_outside(self) -> None:
        self.path.write_text("[Desktop Entry]\n", encoding="utf-8")
        fake = self._stat_result(0o100644, 65534)
        with _Namespace(INITIAL_MAP), mock.patch.object(Path, "stat", return_value=fake):
            with self.assertRaises(DesktopRefused):
                _entry_file_safe(self.path, "org.gnome.Nautilus.desktop")

    def test_a_desktop_entry_owned_by_the_overflow_uid_is_accepted_inside(self) -> None:
        self.path.write_text("[Desktop Entry]\n", encoding="utf-8")
        fake = self._stat_result(0o100644, 65534)
        with _with_uid_map(SANDBOXED_MAP), \
                mock.patch.object(ownership, "_overflow_uid", return_value=65534), \
                mock.patch.object(Path, "stat", return_value=fake):
            _entry_file_safe(self.path, "org.gnome.Nautilus.desktop")


if __name__ == "__main__":
    unittest.main()
