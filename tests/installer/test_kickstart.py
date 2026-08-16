# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The document that erases a disk, and everything it refuses to be.

The kickstart is the only artefact in this phase that a disk is destroyed by, so
it is tested harder than anything else here: what it names, what it must not
contain, and — the part a reading of the code will not give you — that no command
in it is set twice.

That last one is a real defect this suite was written after. The first render
kept the installation medium's ``firewall --disabled`` *after* the module's own
``firewall --enabled``. Kickstart takes the last occurrence, so a document that
read as hardened would have installed a system with the firewall off, and both
lines were individually correct.
"""

from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from installer.backend.kickstart import (                    # noqa: E402
    KickstartError, crypt_password, payload_directives, redacted, render,
)
from installer.setup_state import Choices                    # noqa: E402
from installer.storage.models import DiskInfo                # noqa: E402
from installer.storage.planning import automatic_plan        # noqa: E402

#: A plausible bootc-generic-iso kickstart. The payload line is the one that
#: decides which operating system is written, and is taken verbatim.
MEDIUM = [
    "# osbuild-generated",
    "text",
    "lang en_US.UTF-8",
    "keyboard us",
    "zerombr",
    "clearpart --all --initlabel --disklabel=gpt",
    "autopart --nohome --noswap --type=plain",
    "ostreecontainer --url=/run/install/repo/container --transport=oci "
    "--no-signature-verification",
    "firewall --disabled",
    "selinux --permissive",
    "%post --erroronfail",
    "bootupctl backend install --write-uuid --update-firmware /",
    "%end",
    "reboot --eject",
]

#: A hash-shaped string. `render` only requires that it start with '$', so the
#: document tests do not need a working libcrypt.
HASH = "$y$j9T$abcdefghijklmnop$0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHI"

DISK = DiskInfo(
    id="disk-2f6a9c1e4b7d8a05", devicePath="/dev/vda", sizeBytes=80 * 1024**3,
    logicalSectorSize=512, physicalSectorSize=512, removable=False, readOnly=False,
    model="QEMU HARDDISK",
)
OTHER = DiskInfo(
    id="disk-other", devicePath="/dev/sdb", sizeBytes=500 * 1024**3,
    logicalSectorSize=512, physicalSectorSize=512, removable=False, readOnly=False,
    model="Other Disk",
)


def _choices(**overrides) -> dict:
    value = Choices(display_name="Alex", username="alex", device_name="alex-laptop",
                    encryption_enabled=True, **overrides)
    return value.as_record()


def _render(*, encryption=True, base=None, **kwargs):
    plan = automatic_plan(DISK, mode="erase_disk", encryption=encryption)
    arguments = {
        "plan": plan,
        "choices": _choices(),
        "base": base if base is not None else MEDIUM,
        "password_hash": HASH,
    }
    if encryption:
        arguments["passphrase"] = "a-disk-passphrase"
    arguments.update(kwargs)
    return render(**arguments)


class WhatItNames(unittest.TestCase):
    def test_only_the_planned_disk_is_named(self) -> None:
        """§12: the destructive directives name the disk the plan targets.

        Asserted as an absence as well as a presence — a document that named the
        right disk *and* another one would pass a presence-only check and erase
        two disks.
        """
        document = _render()
        self.assertIn("ignoredisk --only-use=vda", document)
        self.assertIn("clearpart --all --drives=vda --initlabel", document)
        for line in document.splitlines():
            if line.startswith(("clearpart", "part ", "ignoredisk")):
                self.assertNotIn("sdb", line)
                self.assertNotIn("nvme", line)

    def test_the_payload_comes_from_the_medium_verbatim(self) -> None:
        document = _render()
        payload = payload_directives(MEDIUM)
        self.assertEqual(len(payload), 1)
        self.assertIn(payload[0], document)

    def test_the_keyboard_names_the_console_keymap_as_well(self) -> None:
        """Without --vckeymap Anaconda asks the live session's localed for the
        conversion, and a medium whose localed is unreachable from the module
        process writes no /etc/vconsole.conf at all — journey A's disk had the
        X layout configured and no console file. The directive carries both."""
        document = _render()
        self.assertIn("keyboard --xlayouts='gb' --vckeymap='gb'", document)

    def test_a_medium_with_no_payload_renders_nothing(self) -> None:
        """The refusal that stops an installer writing the wrong system."""
        with self.assertRaises(KickstartError) as caught:
            _render(base=["text", "lang en_US.UTF-8", "firewall --enabled"])
        self.assertIn("payload", str(caught.exception))

    def test_post_sections_from_the_medium_survive(self) -> None:
        """`bootupctl backend install` lives in %post; dropping it breaks boot."""
        document = _render()
        self.assertIn("%post --erroronfail", document)
        self.assertIn("bootupctl backend install", document)
        self.assertIn("%end", document)

    def test_the_medium_does_not_reboot_the_machine(self) -> None:
        """§27: the person presses Restart, not the kickstart."""
        document = _render()
        for line in document.splitlines():
            self.assertFalse(line.strip().startswith(("reboot", "poweroff", "halt", "shutdown")))


class NoCommandIsSetTwice(unittest.TestCase):
    """The defect this file was written after."""

    def test_the_medium_cannot_override_the_security_posture(self) -> None:
        document = _render()
        firewall = [line for line in document.splitlines()
                    if line.strip().startswith("firewall")]
        selinux = [line for line in document.splitlines()
                   if line.strip().startswith("selinux")]
        self.assertEqual(firewall, ["firewall --enabled"])
        self.assertEqual(selinux, ["selinux --enforcing"])

    def test_no_command_outside_a_section_appears_twice(self) -> None:
        document = _render()
        counts: dict[str, int] = {}
        in_section = False
        for line in document.splitlines():
            stripped = line.strip()
            if stripped.startswith("%end"):
                in_section = False
                continue
            if stripped.startswith("%"):
                in_section = True
                continue
            if in_section or not stripped or stripped.startswith("#"):
                continue
            command = stripped.split(None, 1)[0]
            counts[command] = counts.get(command, 0) + 1
        repeated = {name: count for name, count in counts.items()
                    if count > 1 and name not in {"part"}}
        self.assertEqual(repeated, {})

    def test_a_duplicate_is_refused_rather_than_rendered(self) -> None:
        """The negative control: the guard fires when a duplicate gets through.

        A medium carrying a command this module does not supersede and does
        supply would produce two of it. `timezone` is used because it is a
        command the module emits, so a base carrying one is exactly the
        situation the guard exists for — with the supersession list emptied, it
        must still refuse.
        """
        import installer.backend.kickstart as module

        original = module._SUPERSEDED
        module._SUPERSEDED = ()
        try:
            with self.assertRaises(KickstartError) as caught:
                _render()
            self.assertIn("more than once", str(caught.exception))
        finally:
            module._SUPERSEDED = original


class Secrets(unittest.TestCase):
    def test_an_unhashed_password_is_refused(self) -> None:
        with self.assertRaises(KickstartError):
            _render(password_hash="hunter2")

    def test_the_passphrase_and_plan_must_agree(self) -> None:
        with self.assertRaises(KickstartError):
            plan = automatic_plan(DISK, mode="erase_disk", encryption=True)
            render(plan=plan, choices=_choices(), base=MEDIUM, password_hash=HASH)
        with self.assertRaises(KickstartError):
            plan = automatic_plan(DISK, mode="erase_disk", encryption=False)
            render(plan=plan, choices=_choices(), base=MEDIUM, password_hash=HASH,
                   passphrase="x")

    def test_redaction_removes_both_secrets(self) -> None:
        document = _render(passphrase="THE-DISK-PASSPHRASE")
        self.assertIn("THE-DISK-PASSPHRASE", document)
        self.assertNotIn("THE-DISK-PASSPHRASE", redacted(document))
        self.assertNotIn(HASH, redacted(document))
        self.assertIn("[redacted]", redacted(document))

    def test_encryption_is_luks2(self) -> None:
        document = _render()
        root = [line for line in document.splitlines() if line.startswith("part /")][-1]
        self.assertIn("--encrypted", root)
        self.assertIn("--luks-version=luks2", root)


class Injection(unittest.TestCase):
    """Kickstart is word-split, so a quote in a value is a new directive."""

    def test_a_quote_in_the_display_name_is_refused(self) -> None:
        for hostile in ("A'; reboot", "A'\nreboot", "A\rreboot"):
            with self.subTest(hostile):
                choices = _choices()
                choices["account"]["displayName"] = hostile
                with self.assertRaises(KickstartError):
                    _render(choices=choices)

    def test_an_invalid_username_is_refused(self) -> None:
        for hostile in ("root; reboot", "Alex", "", "a" * 40):
            with self.subTest(hostile):
                choices = _choices()
                choices["account"]["username"] = hostile
                with self.assertRaises(KickstartError):
                    _render(choices=choices)

    def test_an_invalid_device_name_is_refused(self) -> None:
        choices = _choices()
        choices["account"]["deviceName"] = "host name with spaces"
        with self.assertRaises(KickstartError):
            _render(choices=choices)

    def test_a_target_that_is_not_a_plain_device_is_refused(self) -> None:
        plan = automatic_plan(DISK, mode="erase_disk", encryption=False)
        for path in ("/dev/mapper/luks-x", "vda", "/dev/../etc/passwd", ""):
            with self.subTest(path):
                broken = dict(plan)
                broken["targetDisk"] = {**plan["targetDisk"], "devicePath": path}
                with self.assertRaises(KickstartError):
                    render(plan=broken, choices=_choices(), base=MEDIUM,
                           password_hash=HASH)


class Hashing(unittest.TestCase):
    def test_a_password_hashes_and_verifies(self) -> None:
        try:
            hashed = crypt_password("a-real-password")
        except KickstartError as error:
            self.skipTest(f"no crypt(3) on this platform: {error}")
        self.assertTrue(hashed.startswith("$"))
        self.assertNotIn("a-real-password", hashed)
        # crypt(3) verifies by re-hashing with the stored value as the setting.
        self.assertEqual(crypt_password("a-real-password", salt=hashed), hashed)
        self.assertNotEqual(crypt_password("a-different-password", salt=hashed), hashed)

    def test_an_empty_password_is_refused(self) -> None:
        with self.assertRaises(KickstartError):
            crypt_password("")

    def test_two_hashes_of_one_password_differ(self) -> None:
        """Salted, so a shadow file does not reveal that two users match."""
        try:
            first = crypt_password("same-password")
            second = crypt_password("same-password")
        except KickstartError as error:
            self.skipTest(f"no crypt(3) on this platform: {error}")
        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
