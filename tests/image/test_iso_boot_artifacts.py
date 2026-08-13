"""The ISO gate, and the unbootable media it has to refuse.

Every fixture below is a medium that builds cleanly, mounts cleanly and does not
boot. That combination is the whole problem: image-builder returned 0 on the ISO
that never reached userspace, and so did every check that ran on it.

The media are directory trees rather than real ISO images, which is what --root
is for. Volume-label checks need a real ISO9660 primary volume descriptor, so
those tests build a 34 KB one by hand instead.
"""

from __future__ import annotations

import base64
import gzip
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "build/scripts/check-iso-boot-artifacts.py"

sys.path.insert(0, str(ROOT / "tests/image"))
from test_live_initramfs import (  # noqa: E402
    KERNEL, complete_contents, initramfs,
)


def _load(path: Path, name: str):
    loader = SourceFileLoader(name, str(path))
    spec = spec_from_loader(name, loader)
    assert spec is not None
    module = module_from_spec(spec)
    loader.exec_module(module)
    return module


gate = _load(SCRIPT, "bunny_check_iso_boot_artifacts")

LABEL = "Bunny-OS-Beta"

# Real squashfs images, 4 KB each, gzipped and base64'd so they travel in the
# file and need no mksquashfs to produce.
#
# They are here because the first version of these tests used
# `b"hsqs" + b"\x00" * 1024` — four bytes of magic and nothing behind them —
# which passed on a host with no unsquashfs and failed on one with it. That is
# the wrong way round: the test was green precisely where the checker could not
# run, and the reference measurement on Linux is what caught it. A fixture that
# only works when the tool is missing is not a fixture.
#
# SQUASHFS_IS_ROOT has a top-level usr/ and no LiveOS/ — the shape this medium
# actually has, where dmsquash-live uses the squashfs itself as the root.
# BAD_LIVEOS has a top-level LiveOS/ with no rootfs.img inside it, which is the
# shape dmsquash-live-root.sh dies on.
SQUASHFS_IS_ROOT = base64.b64decode("""
H4sIAAAAAAACA8soLixmY4ABJgZGIMnIIMhwAEiyANkLoDJ+jBDaDUr/h4JiqPw+KC0BlbeA
0p4utkmleXmVXMqK+kmZefrFGVyeDBW3kpMiDp1gYPXhWdEg3CEpee/QU8mJVzSZDKVn9F44
37VsOrevPfekukw2S7Y0k8o0laiugzw5dptspCdZruLZx/OGh4eHIfoYW6UbyKiEBgY1i7Mn
J8SviZ4ya/KsiDlcoikJrEnsG3SMnT0DNWPmsHYIN8wQ1Jg8ZeZxDlG2i1wBD69MesKmwJo0
TUyckUG/muuFQEMC1P3CDOAgYGCDul8MaENwggMrb4AVo5e1w0vWACkGDQPGhwpQeZYGEOnA
yDAKRsEoGAWjYBSMglEwCkbBKBgFo2AUDGIAAJGIZ40AEAAA
""")
BAD_LIVEOS = base64.b64decode("""
H4sIAAAAAAACA8soLixmZoABJgZGIMnIIMhwAEiyANkOUBkORigDSv+HgkKo8AIofQtKf4LS
efklCokKRflAKjM3MT2VS5eh4lZyUsShEwysPjwrHAQ6JCXvHXoqOfHKSSZD41k2xkK6pxWO
Hjh04ADQTGumv2og5QkNDGoWZ08FTJk1Y9JsLtGEBJYkVoOzpx5Mjpz2Sp6HIZif5aJAQwLU
RkGoG09A+XxAE4ITHFj5AqQYWCUYEh9BxVkaQOQvhlEwCkbBKBgFo2AUjIJRMApGwSgYBaNg
+AMA3MctowAQAAA=
""")


def squashfs(payload: bytes) -> bytes:
    return gzip.decompress(payload)

GRUB_TEMPLATE = """
set timeout=60
search --no-floppy --set=root -l '{search_label}'

menuentry 'Try or Install Bunny OS' --class fedora {{
\tlinux {kernel} {cmdline}
\tinitrd {initrd}
}}
"""


def bzimage(release: str = KERNEL) -> bytes:
    """A minimal x86 bzImage carrying a readable version string.

    The header magic sits at 0x202 and a two-byte pointer at 0x20e names the
    version string's offset, biased by 0x200. Enough of one to be parsed; not a
    kernel.
    """
    blob = bytearray(b"\x00" * 0x1000)
    blob[0x202:0x206] = b"HdrS"
    version_at = 0x600
    struct.pack_into("<H", blob, 0x20E, version_at - 0x200)
    encoded = f"{release} (mockbuild@fedora) #1 SMP".encode()
    blob[version_at:version_at + len(encoded)] = encoded
    return bytes(blob)


class Medium:
    """A medium built to order, as a directory tree."""

    def __init__(self, root: Path) -> None:
        self.root = root

    @classmethod
    def good(cls, root: Path, *, cmdline: str | None = None,
             search_label: str = LABEL, kernel: str = "/images/pxeboot/vmlinuz",
             initrd: str | None = "/images/pxeboot/initrd.img",
             initramfs_contents: dict | None = None,
             kernel_release: str = KERNEL,
             live_payload: bytes | None = None,
             omit_live_payload: bool = False) -> "Medium":
        # `None` means "the correct payload", and omission has its own flag, so
        # that "no payload at all" cannot be expressed by accident.
        if live_payload is None and not omit_live_payload:
            live_payload = squashfs(SQUASHFS_IS_ROOT)
        if omit_live_payload:
            live_payload = None
        medium = cls(root)
        cmdline = cmdline if cmdline is not None else (
            f"root=live:CDLABEL={LABEL} rd.live.image enforcing=0 console=tty0 quiet")
        (root / "images/pxeboot").mkdir(parents=True)
        (root / "images/pxeboot/vmlinuz").write_bytes(bzimage(kernel_release))
        (root / "images/pxeboot/initrd.img").write_bytes(
            initramfs(initramfs_contents if initramfs_contents is not None
                      else complete_contents(kernel_release)))
        if live_payload is not None:
            (root / "LiveOS").mkdir(parents=True)
            (root / "LiveOS/squashfs.img").write_bytes(live_payload)
        body = GRUB_TEMPLATE.format(search_label=search_label, kernel=kernel,
                                    cmdline=cmdline,
                                    initrd=initrd or "/images/pxeboot/initrd.img")
        if initrd is None:
            body = "\n".join(line for line in body.splitlines()
                             if not line.strip().startswith("initrd"))
        for relative in gate.BOOT_CONFIGS:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
        return medium

    def qualify(self, expect_kver: str | None = KERNEL) -> dict:
        return gate.qualify(self.root, None, None, expect_kver)


def failed(report) -> set[str]:
    return {check["check"] for check in report["checks"] if check["status"] == "FAIL"}


class MediumTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = Path(tempfile.mkdtemp())

    def build(self, **kwargs) -> Medium:
        root = self.scratch / f"medium{len(list(self.scratch.iterdir()))}"
        root.mkdir()
        return Medium.good(root, **kwargs)

    def test_a_correct_medium_passes(self) -> None:
        report = self.build().qualify()
        self.assertEqual(report["status"], "PASS",
                         [c for c in report["checks"] if c["status"] == "FAIL"])

    def test_inst_stage2_is_refused_because_nothing_on_this_medium_reads_it(self) -> None:
        # The first wrong hypothesis, and the configuration the failing ISO
        # actually carried. inst.stage2= is read by anaconda-dracut; this is a
        # LiveOS medium whose initramfs has no such module and never will.
        report = self.build(
            cmdline=f"inst.stage2=hd:LABEL={LABEL} inst.webui console=tty0").qualify()
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any(name.endswith("/root") for name in failed(report)))

    def test_a_live_entry_without_enforcing_zero_is_caught(self) -> None:
        # The second real failure of this medium, and the one that only shows
        # itself after switch-root: the live root is an unlabelled squashfs, so
        # PID 1 freezes with "Failed to allocate manager object" the moment it
        # tries to label /run. image-builder's own entries carry enforcing=0;
        # Bunny's replace them, so dropping it is a one-line edit away.
        report = self.build(
            cmdline=f"root=live:CDLABEL={LABEL} rd.live.image console=tty0 quiet"
        ).qualify()
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any(name.endswith("/selinux") for name in failed(report)),
                        failed(report))

    def test_selinux_zero_is_accepted_as_well(self) -> None:
        report = self.build(
            cmdline=f"root=live:CDLABEL={LABEL} rd.live.image selinux=0 console=tty0"
        ).qualify()
        self.assertFalse(any(name.endswith("/selinux") for name in failed(report)),
                         failed(report))

    def test_a_missing_initrd_is_caught(self) -> None:
        medium = self.build()
        (medium.root / "images/pxeboot/initrd.img").unlink()
        report = medium.qualify()
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any(name.endswith("/initrd") for name in failed(report)))

    def test_a_missing_kernel_is_caught(self) -> None:
        medium = self.build()
        (medium.root / "images/pxeboot/vmlinuz").unlink()
        self.assertTrue(any(name.endswith("/kernel") for name in failed(medium.qualify())))

    def test_a_stale_initrd_without_the_live_modules_is_caught(self) -> None:
        # The exact fault. Everything about this medium is right except the one
        # artifact, and nothing else in the build would notice.
        contents = complete_contents()
        manifest = contents[gate._initramfs_module.DRACUT_MODULE_MANIFEST].decode().split()
        manifest.remove("dmsquash-live")
        contents[gate._initramfs_module.DRACUT_MODULE_MANIFEST] = (
            ("\n".join(manifest) + "\n").encode())
        for path in gate._initramfs_module.MODULE_EVIDENCE["dmsquash-live"]:
            del contents[path]
        report = self.build(initramfs_contents=contents).qualify()
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(
            any("dmsquash-live" in name for name in failed(report)),
            failed(report),
        )

    def test_kernel_and_initramfs_from_different_releases_are_caught(self) -> None:
        medium = self.build()
        (medium.root / "images/pxeboot/vmlinuz").write_bytes(bzimage("6.0.0-1.fc44.x86_64"))
        report = medium.qualify()
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("kernel-release/images/pxeboot/vmlinuz", failed(report))

    def test_a_label_the_command_line_does_not_match_is_caught(self) -> None:
        # GRUB finds the medium by its own search label and boots; the initramfs
        # then waits forever for /dev/disk/by-label/<other>. On screen this is a
        # hang, not an error.
        report = self.build(search_label="Something-Else").qualify()
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any(name.endswith("/search-label") for name in failed(report)))

    def test_a_medium_with_no_live_payload_is_caught(self) -> None:
        report = self.build(omit_live_payload=True).qualify()
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("live-payload/present", failed(report))

    def test_a_payload_that_is_not_a_squashfs_is_caught(self) -> None:
        report = self.build(live_payload=b"NOTSQUASH" + b"\x00" * 64).qualify()
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("live-payload/shape", failed(report))

    def test_a_payload_with_squashfs_magic_and_nothing_behind_it_is_caught(self) -> None:
        # The fixture these tests used to ship. It passes on a host with no
        # unsquashfs and fails on one with it, so it is now a case rather than
        # a foundation.
        report = self.build(live_payload=b"hsqs" + b"\x00" * 1024).qualify()
        if shutil.which("unsquashfs") is None:
            self.skipTest("unsquashfs unavailable; the shape cannot be determined")
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("live-payload/shape", failed(report))

    @unittest.skipIf(shutil.which("unsquashfs") is None, "unsquashfs unavailable")
    def test_a_liveos_directory_with_no_root_image_inside_it_is_caught(self) -> None:
        # dmsquash-live-root.sh takes the LiveOS branch on sight of the
        # directory and then dies with "Failed to find a root filesystem".
        report = self.build(live_payload=squashfs(BAD_LIVEOS)).qualify()
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("live-payload/shape", failed(report))
        detail = next(c["detail"] for c in report["checks"]
                      if c["check"] == "live-payload/shape")
        self.assertIn("rootfs.img", detail)

    def test_an_entry_with_no_initrd_line_is_caught(self) -> None:
        report = self.build(initrd=None).qualify()
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any(name.endswith("/initrd") for name in failed(report)))

    def test_two_configs_disagreeing_would_be_two_media_in_one(self) -> None:
        medium = self.build()
        efi = medium.root / gate.BOOT_CONFIGS[0]
        efi.write_text(efi.read_text().replace(f"CDLABEL={LABEL}", "CDLABEL=Wrong"),
                       encoding="utf-8")
        report = medium.qualify()
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("EFI/BOOT/grub.cfg" in name and name.endswith("/label")
                            or "EFI/BOOT/grub.cfg" in name and name.endswith("/search-label")
                            for name in failed(report)), failed(report))


class ExpectedLabelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = Path(tempfile.mkdtemp())

    def test_expecting_a_label_on_an_extracted_medium_fails_rather_than_passes(self) -> None:
        # --root cannot see the volume descriptor. Answering "fine" to a
        # question it did not ask is how a check reports a property it never
        # examined.
        root = self.scratch / "medium"
        root.mkdir()
        Medium.good(root)
        report = gate.qualify(root, None, LABEL, KERNEL)
        self.assertIn("volume-label/expected", failed(report))
        detail = next(c["detail"] for c in report["checks"]
                      if c["check"] == "volume-label/expected")
        self.assertIn("--iso", detail)


class VolumeLabelTests(unittest.TestCase):
    """Reading the ISO9660 primary volume descriptor without a mount."""

    def setUp(self) -> None:
        self.scratch = Path(tempfile.mkdtemp())

    def iso_with_label(self, label: str) -> Path:
        blob = bytearray(b"\x00" * (17 * 2048))
        pvd = 16 * 2048
        blob[pvd] = 1
        blob[pvd + 1:pvd + 6] = b"CD001"
        encoded = label.encode("ascii").ljust(32, b" ")
        blob[pvd + 40:pvd + 72] = encoded
        path = self.scratch / f"{label}.iso"
        path.write_bytes(bytes(blob))
        return path

    def test_the_label_is_read_from_the_volume_descriptor(self) -> None:
        self.assertEqual(gate.volume_label(self.iso_with_label(LABEL)), LABEL)

    def test_a_file_that_is_not_an_iso_yields_no_label(self) -> None:
        path = self.scratch / "not.iso"
        path.write_bytes(b"\x00" * 40960)
        self.assertIsNone(gate.volume_label(path))


class CommandLineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = Path(tempfile.mkdtemp())

    def test_root_mode_exits_zero_on_a_good_medium(self) -> None:
        root = self.scratch / "medium"
        root.mkdir()
        Medium.good(root)
        finished = subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(root),
             "--expect-kver", KERNEL, "--quiet"],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(finished.returncode, 0, finished.stdout + finished.stderr)

    def test_a_missing_medium_is_a_failure_not_a_crash(self) -> None:
        finished = subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(self.scratch / "absent"),
             "--quiet"],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(finished.returncode, 2)
        self.assertIn("no such directory", finished.stderr)


if __name__ == "__main__":
    unittest.main()
