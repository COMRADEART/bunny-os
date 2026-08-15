# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Where the setup surface can go, and where it cannot.

Needs GTK, so it is skipped on a machine without it. The properties tested are
the ones that decide whether a disk gets erased, so they are asserted against the
real application object rather than against the screen records: a record can be
right while the flow that reaches it is wrong.
"""

from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from installer.storage.models import DiskInfo                       # noqa: E402
from installer.storage.safety import assess_target, confirmation_phrase  # noqa: E402

DISK = DiskInfo(
    id="disk-2f6a9c1e4b7d8a05", devicePath="/dev/vda", sizeBytes=80 * 1024**3,
    logicalSectorSize=512, physicalSectorSize=512, removable=False, readOnly=False,
    model="QEMU HARDDISK",
)


def _gtk_or_skip():
    try:
        from installer.frontend.setup import _gtk
        return _gtk()
    except Exception as error:                       # pragma: no cover
        raise unittest.SkipTest(f"GTK is not available: {error}")


class FlowTransitions(unittest.TestCase):
    def setUp(self) -> None:
        self.Gtk = _gtk_or_skip()
        from installer.frontend.setup import SetupApplication

        self.submitted: list[dict] = []
        self.application = SetupApplication(self.Gtk, context={
            "disks": (DISK,),
            "findings": {DISK.id: assess_target(DISK, mode="erase_disk")},
            "selectedDisk": DISK,
            "selectedDiskIdentity": "QEMU HARDDISK — 80.0 GiB — /dev/vda",
            "submit": lambda confirmation, on_state: self.submitted.append(
                {"confirmation": confirmation}),
        })
        # No window, so render() must not try to swap a child.
        self.application.window = None

    def _goto(self, key: str) -> None:
        keys = [name for name, _ in self.application.flow]
        self.application.index = keys.index(key)

    def test_review_does_not_start_an_installation(self) -> None:
        """§12: the forward action on Review leads to the confirmation, not to a write."""
        self._goto("review")
        self.application.on_action("install")
        self.assertIsNotNone(self.application.terminal)
        self.assertEqual(self.application.terminal.key, "confirm_erase")
        self.assertEqual(self.submitted, [], "Review started an installation directly")

    def test_the_confirmation_screen_names_the_selected_disk(self) -> None:
        self._goto("review")
        self.application.on_action("install")
        screen = self.application.terminal
        danger = [item for item in screen.warnings if item.level == "danger"]
        self.assertTrue(danger)
        self.assertIn("/dev/vda", danger[0].text)
        self.assertIn(confirmation_phrase(DISK), screen.announcement)

    def test_back_leaves_the_confirmation_without_installing(self) -> None:
        self._goto("review")
        self.application.on_action("install")
        self.application.on_action("back")
        self.assertIsNone(self.application.terminal)
        self.assertEqual(self.submitted, [])

    def test_the_typed_phrase_is_what_is_submitted(self) -> None:
        """The surface sends what was typed; the backend decides if it matches."""
        self._goto("review")
        self.application.on_action("install")
        self.application.on_change("phrase", "NOT THE PHRASE")
        self.application.on_action("confirm")
        self.assertEqual(len(self.submitted), 1)
        self.assertEqual(self.submitted[0]["confirmation"], "NOT THE PHRASE")

    def test_entering_the_confirmation_forgets_a_previous_phrase(self) -> None:
        """Otherwise a phrase typed for one disk unlocks the button for another."""
        self.application.on_change("phrase", confirmation_phrase(DISK))
        self._goto("review")
        self.application.on_action("install")
        self.assertNotIn("phrase", self.application.secrets)

    def test_back_does_not_escape_a_running_installation(self) -> None:
        self._goto("review")
        self.application.on_action("install")
        self.application.on_action("confirm")
        installing = self.application.terminal
        self.assertEqual(installing.key, "install")
        self.application.on_action("back")
        self.assertIs(self.application.terminal, installing)

    def test_with_no_backend_the_surface_says_so_and_does_not_pretend(self) -> None:
        from installer.frontend.setup import SetupApplication

        application = SetupApplication(self.Gtk, context={
            "disks": (DISK,), "selectedDisk": DISK,
            "selectedDiskIdentity": "QEMU HARDDISK — 80.0 GiB — /dev/vda",
        })
        application.window = None
        keys = [name for name, _ in application.flow]
        application.index = keys.index("review")
        application.on_action("install")
        application.on_action("confirm")
        self.assertEqual(application.terminal.key, "failure")
        self.assertIn("cannot write to a disk", application.terminal.fields[0].help)

    def test_no_disk_means_the_confirmation_is_unreachable(self) -> None:
        from installer.frontend.setup import SetupApplication

        application = SetupApplication(self.Gtk, context={"disks": ()})
        application.window = None
        keys = [name for name, _ in application.flow]
        application.index = keys.index("review")
        application.on_action("install")
        self.assertIsNone(application.terminal)

    def test_choosing_a_disk_reaches_the_flow_not_only_the_widget(self) -> None:
        """Until the targetDisk branch existed, on_change dropped the key:
        context["selectedDisk"] stayed None from construction, every widget
        state was correct, and both "Install Bunny OS" and "confirm" silently
        returned on their disk-is-None guards. Found by the §42 driver
        selecting a disk the way a person does."""
        from installer.frontend.setup import SetupApplication
        from installer.storage.safety import disk_identity

        application = SetupApplication(self.Gtk, context={
            "disks": (DISK,),
            "findings": {DISK.id: assess_target(DISK, mode="erase_disk")},
            "selectedDisk": None,
            "selectedDiskIdentity": "no disk selected",
            "identityFor": disk_identity,
        })
        application.window = None
        application.on_change("targetDisk", DISK.id)
        self.assertIs(application.context["selectedDisk"], DISK)
        self.assertIn("/dev/vda", application.context["selectedDiskIdentity"])
        # The flow's screen builders capture their facts at build time, so the
        # selection must survive into a freshly built review screen.
        keys = [name for name, _ in application.flow]
        application.index = keys.index("review")
        application.on_action("install")
        self.assertIsNotNone(application.terminal)
        self.assertEqual(application.terminal.key, "confirm_erase")


class AccessibilityIsImmediate(unittest.TestCase):
    def setUp(self) -> None:
        self.Gtk = _gtk_or_skip()

    def test_a_text_size_change_is_recorded_and_resolvable(self) -> None:
        """§8: the setting takes effect, rather than being stored for later."""
        from installer.frontend.setup import SetupApplication
        from installer.theme_css import render_gtk_css, resolve

        application = SetupApplication(self.Gtk)
        before = render_gtk_css(resolve(**application.choices.theme_options()))
        application.choices.text_scale = 2.0
        after = render_gtk_css(resolve(**application.choices.theme_options()))
        self.assertNotEqual(before, after)

    def test_high_contrast_changes_the_resolved_theme(self) -> None:
        from installer.frontend.setup import SetupApplication
        from installer.theme_css import resolve

        application = SetupApplication(self.Gtk)
        plain = resolve(**application.choices.theme_options())
        application.choices.high_contrast = True
        contrasted = resolve(**application.choices.theme_options())
        self.assertNotEqual(plain["name"], contrasted["name"])
        self.assertTrue(contrasted["highContrast"])


if __name__ == "__main__":
    unittest.main()
