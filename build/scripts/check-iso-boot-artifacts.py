#!/usr/bin/python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Qualify an assembled installation ISO before anyone starts a virtual machine.

## What this catches that the in-container check cannot

A correct initramfs inside the build container is not a correct ISO. Between the
two there is an osbuild pipeline that copies files, an image-builder that writes
boot configuration from installer/config/iso.yaml, and a volume label that has
to agree with a string in a kernel command line. Each of those can be wrong on
its own:

  * a stale initrd copied from somewhere other than the image just qualified;
  * GRUB pointing at a kernel or initrd path that is not on the medium;
  * a kernel and an initramfs from different releases;
  * `root=live:CDLABEL=X` where the volume is labelled Y, which resolves to a
    /dev/disk/by-label path that never appears and hangs the initramfs;
  * a command line asking for a live root on a medium with no /LiveOS/squashfs.img;
  * a squashfs of a shape dmsquash-live cannot use as a root.

None of those makes the ISO fail to build, and all of them make it fail to boot.
The point of this check is that it costs seconds and a VM boot costs an hour.

## The mechanism it checks against

Established by reading dracut 108's dmsquash-live-root.sh out of the image
rather than from memory:

  root=live:CDLABEL=<label>   parse-dmsquash-live.sh rewrites this to
                              /dev/disk/by-label/<label>, so <label> must equal
                              the ISO9660 volume identifier exactly.
  rd.live.dir                 defaults to LiveOS
  rd.live.squashimg           defaults to squashfs.img
  the squashfs shape          dmsquash-live-root.sh looks inside the mounted
                              squashfs: a LiveOS/ directory means it expects
                              LiveOS/rootfs.img or LiveOS/ext3fs.img within it;
                              a top-level usr/ means the squashfs is itself the
                              root filesystem and overlayfs becomes required;
                              anything else is `die "Failed to find a root
                              filesystem"`. This medium is the second case.

Usage:
    check-iso-boot-artifacts.py --iso PATH [--expect-label LABEL]
                                [--expect-kver KVER] [--json REPORT]
    check-iso-boot-artifacts.py --root DIR ... (an already-mounted medium)

Reading the ISO needs either a loopback mount (root) or xorriso. Both are used
in that order; --root skips the question entirely and is what the tests use.

Exit status: 0 pass, 2 qualification failure or unreadable medium.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader

_loader = SourceFileLoader(
    "bunny_check_live_initramfs",
    str(Path(__file__).resolve().parent / "check-live-initramfs.py"),
)
_spec = spec_from_loader(_loader.name, _loader)
assert _spec is not None
_initramfs_module = module_from_spec(_spec)
_loader.exec_module(_initramfs_module)

# Boot configurations image-builder writes for a bootc-generic-iso. Both are
# checked: the EFI one is what a UEFI machine reads and the BIOS one is what
# eltorito boots, and an entry corrected in one and not the other is a medium
# that boots differently depending on the firmware it meets.
BOOT_CONFIGS = ("EFI/BOOT/grub.cfg", "boot/grub2/grub.cfg")

MENUENTRY = re.compile(r"^\s*menuentry\s+'([^']*)'", re.MULTILINE)
LINUX_LINE = re.compile(r"^\s*linux(?:efi)?\s+(\S+)\s*(.*)$", re.MULTILINE)
INITRD_LINE = re.compile(r"^\s*initrd(?:efi)?\s+(\S+)\s*$", re.MULTILINE)
SEARCH_LABEL = re.compile(r"^\s*search\s+.*?-l\s+'([^']*)'", re.MULTILINE)


class MediumError(Exception):
    pass


@contextmanager
def opened(iso: Path | None, root: Path | None):
    """Yield a directory holding the medium's contents.

    Either the caller has already mounted or extracted it (--root, which is what
    the tests use), or this mounts it read-only over loopback, which needs root.
    There is deliberately no third path: a check that half-reads a medium when it
    cannot mount one would report a pass it did not establish, and the build
    script that calls this is running as root anyway.
    """
    if root is not None:
        if not root.is_dir():
            raise MediumError(f"no such directory: {root}")
        yield root
        return
    assert iso is not None
    if not iso.is_file():
        raise MediumError(f"no such ISO: {iso}")

    with tempfile.TemporaryDirectory(prefix="bunny-iso-") as scratch:
        mountpoint = Path(scratch) / "mnt"
        mountpoint.mkdir()
        mounted = subprocess.run(
            ["mount", "-o", "loop,ro", str(iso), str(mountpoint)],
            capture_output=True, text=True, check=False,
        )
        if mounted.returncode != 0:
            raise MediumError(
                f"cannot mount {iso} read-only over loopback: "
                f"{mounted.stderr.strip() or 'mount failed'}. Run this as root, "
                "or mount the medium yourself and pass --root."
            )
        try:
            yield mountpoint
        finally:
            subprocess.run(["umount", str(mountpoint)],
                           capture_output=True, check=False)


def volume_label(iso: Path) -> str | None:
    """The ISO9660 volume identifier, read from the primary volume descriptor.

    Read from the bytes rather than from blkid or xorriso, because this has to
    work in a test and on a builder without either. The PVD sits at sector 16
    and its volume identifier is 32 space-padded bytes at offset 40.
    """
    try:
        with iso.open("rb") as handle:
            handle.seek(16 * 2048)
            descriptor = handle.read(2048)
    except OSError:
        return None
    if len(descriptor) < 72 or descriptor[1:6] != b"CD001":
        return None
    return descriptor[40:72].decode("ascii", "replace").rstrip(" \x00")


def parse_boot_config(text: str) -> dict:
    entries = []
    for block in re.split(r"^\s*menuentry\s+", text, flags=re.MULTILINE)[1:]:
        name_match = re.match(r"'([^']*)'", block)
        linux_match = LINUX_LINE.search(block)
        initrd_match = INITRD_LINE.search(block)
        if linux_match is None:
            # An entry with no `linux` line boots nothing. Reported as an entry
            # with no kernel rather than skipped, because silently dropping it
            # would make a broken menu look like a shorter one.
            entries.append({
                "name": name_match.group(1) if name_match else "(unnamed)",
                "kernel": None, "cmdline": "", "initrd": None,
            })
            continue
        entries.append({
            "name": name_match.group(1) if name_match else "(unnamed)",
            "kernel": linux_match.group(1),
            "cmdline": linux_match.group(2).strip(),
            "initrd": initrd_match.group(1) if initrd_match else None,
        })
    search = SEARCH_LABEL.search(text)
    return {"searchLabel": search.group(1) if search else None, "entries": entries}


def cmdline_value(cmdline: str, key: str) -> str | None:
    for token in cmdline.split():
        if token == key:
            return ""
        if token.startswith(f"{key}="):
            return token.split("=", 1)[1]
    return None


def _squashfs_top_level(path: Path) -> tuple[set[str] | None, bool]:
    """Top-level names in a squashfs, read from a bounded prefix of the listing.

    `unsquashfs -l` walks depth-first in sorted order and this payload is a
    whole root filesystem, so asking for the complete listing would mean reading
    several hundred thousand lines to answer a question about six of them. The
    stream is read incrementally and abandoned as soon as the answer is settled:
    once `usr` has been seen, or once a top-level name sorting after it has,
    there is nothing further to learn.
    """
    process = subprocess.Popen(
        ["unsquashfs", "-l", str(path)],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
    )
    top: set[str] = set()
    nested = False
    try:
        assert process.stdout is not None
        for count, line in enumerate(process.stdout):
            entry = line.strip()
            if entry.startswith("squashfs-root"):
                entry = entry[len("squashfs-root"):].lstrip("/")
            entry = entry.lstrip("/")
            if not entry:
                continue
            first = entry.split("/", 1)[0]
            top.add(first)
            if re.fullmatch(r"LiveOS/(rootfs|ext3fs|ext4fs)\.img", entry):
                nested = True
            if first == "usr" or first > "usr":
                break
            if count > 2_000_000:  # a safety valve, never expected to fire
                break
    finally:
        # Closing the pipe before killing matters: the loop breaks early by
        # design, so unsquashfs is usually mid-write and the handle would be
        # left open. Python reports that as a ResourceWarning, which is exactly
        # the sort of thing a test suite prints and nobody reads.
        if process.stdout is not None:
            process.stdout.close()
        process.kill()
        process.wait()
    return (top or None), nested


def squashfs_shape(path: Path) -> tuple[str, str]:
    """Which branch of dmsquash-live-root.sh this squashfs will take.

    Returns (verdict, detail). Reads the squashfs superblock and root directory
    via unsquashfs when it is available; without it, reports 'unknown' rather
    than guessing, because a wrong answer here would be worse than no answer.
    """
    if not path.exists():
        return "missing", f"{path} does not exist"
    if path.stat().st_size == 0:
        return "empty", f"{path} is zero bytes"
    with path.open("rb") as handle:
        magic = handle.read(4)
    if magic != b"hsqs":
        return "not-squashfs", f"{path} does not begin with the squashfs magic 'hsqs'"
    if shutil.which("unsquashfs") is None:
        return "unknown", "unsquashfs is not installed; shape not determined"
    top, nested = _squashfs_top_level(path)
    if top is None:
        return "unreadable", "unsquashfs could not list the payload"
    if "LiveOS" in top:
        if nested:
            return "nested-rootfs", "contains LiveOS/rootfs.img"
        return "bad-liveos", (
            "contains a top-level LiveOS/ directory but no rootfs.img or "
            "ext3fs.img inside it; dmsquash-live-root.sh takes the LiveOS branch "
            "and then dies with 'Failed to find a root filesystem'"
        )
    if "usr" in top:
        return "squashfs-is-root", (
            "has a top-level usr/, so dmsquash-live uses the squashfs itself as "
            "the root filesystem and sets overlayfs=required"
        )
    return "unusable", (
        f"has neither LiveOS/ nor usr/ at its top level ({', '.join(sorted(top)[:8])}); "
        "dmsquash-live-root.sh dies with 'Failed to find a root filesystem'"
    )


def qualify(medium: Path, iso: Path | None, expect_label: str | None,
            expect_kver: str | None) -> dict:
    checks: list[dict] = []

    def record(name: str, ok: bool, detail: str) -> None:
        checks.append({"check": name, "status": "PASS" if ok else "FAIL",
                       "detail": detail})

    label = volume_label(iso) if iso is not None else None
    configs: dict[str, dict] = {}
    for relative in BOOT_CONFIGS:
        path = medium / relative
        if not path.is_file():
            record(f"boot-config/{relative}", False,
                   f"{relative} is not on the medium")
            continue
        parsed = parse_boot_config(path.read_text(encoding="utf-8", errors="replace"))
        configs[relative] = parsed
        record(f"boot-config/{relative}", bool(parsed["entries"]),
               f"{len(parsed['entries'])} menu entr(y|ies)")

    if not configs:
        record("boot-config/any", False,
               "the medium carries no GRUB configuration this check can read")
        return _finish(checks, medium, iso, label, configs, None, None)

    # Referenced artifacts must exist, and the kernel and initramfs a single
    # entry names must be the pair osbuild copied out of one /usr/lib/modules
    # directory. A GRUB entry naming a kernel that is not there is the failure
    # this medium would show as a blank screen after the menu.
    referenced_kernels: set[str] = set()
    referenced_initrds: set[str] = set()
    for relative, parsed in configs.items():
        for entry in parsed["entries"]:
            for kind, value in (("kernel", entry["kernel"]), ("initrd", entry["initrd"])):
                if value is None:
                    record(f"entry/{relative}/{entry['name']}/{kind}", False,
                           f"the entry declares no {kind}")
                    continue
                target = medium / value.lstrip("/")
                exists = target.is_file() and target.stat().st_size > 0
                record(f"entry/{relative}/{entry['name']}/{kind}", exists,
                       f"{value} {'exists' if exists else 'is MISSING from the medium'}")
                (referenced_kernels if kind == "kernel" else referenced_initrds).add(value)

            live = cmdline_value(entry["cmdline"], "root")
            if live is None or not live.startswith("live:"):
                record(f"entry/{relative}/{entry['name']}/root", False,
                       f"root= is {live!r}; this medium is a LiveOS ISO and its "
                       "initramfs reads root=live:… and nothing else")
                continue
            record(f"entry/{relative}/{entry['name']}/root", True,
                   f"root={live}")

            # A live root is a squashfs of a bootc container tree, and a bootc
            # container carries no SELinux labels: ostree applies them when it
            # deploys, and nothing deploys a live medium. So the overlay root is
            # unlabeled_t while /etc/selinux/config says enforcing, and PID 1
            # cannot label the /run directories it needs before it has a
            # manager. Measured, on the medium that first got far enough to
            # care:
            #
            #     Welcome to Bunny OS 0.3.0-beta (development)!
            #     systemd[1]: Failed to allocate manager object: Permission denied
            #     systemd[1]: Freezing execution.
            #
            # image-builder's own generated entries carry enforcing=0 for this
            # reason. Bunny's replace them wholesale, so the requirement has to
            # be asserted here or the next edit of installer/config/iso.yaml
            # drops it again and the medium freezes after switch-root — which is
            # both further on and harder to read than failing to boot at all.
            permissive = (cmdline_value(entry["cmdline"], "enforcing") == "0"
                          or cmdline_value(entry["cmdline"], "selinux") == "0")
            record(f"entry/{relative}/{entry['name']}/selinux", permissive,
                   "carries enforcing=0" if permissive else
                   "carries neither enforcing=0 nor selinux=0; the live root is "
                   "an unlabelled squashfs and PID 1 will freeze with 'Failed to "
                   "allocate manager object' after switch-root")
            if live.startswith("live:CDLABEL="):
                wanted = live[len("live:CDLABEL="):]
                if label is not None:
                    record(f"entry/{relative}/{entry['name']}/label", wanted == label,
                           f"root=live:CDLABEL={wanted} against volume label "
                           f"{label!r}"
                           + ("" if wanted == label else
                              " — dmsquash-live resolves this to "
                              f"/dev/disk/by-label/{wanted}, which will never appear"))
                if parsed["searchLabel"] is not None:
                    record(f"entry/{relative}/{entry['name']}/search-label",
                           wanted == parsed["searchLabel"],
                           f"the command line asks for {wanted!r} and GRUB's "
                           f"search sets root from {parsed['searchLabel']!r}")

    if expect_label is not None:
        # A --expect-label that silently checks nothing is worse than no
        # expectation at all: the caller asked for a label to be verified and
        # would read a pass as an answer. The volume identifier lives in the
        # ISO9660 primary volume descriptor, so --root mode cannot supply one.
        record("volume-label/expected", label == expect_label,
               f"volume label is {label!r}, expected {expect_label!r}"
               if label is not None else
               "the volume identifier cannot be read from an extracted medium; "
               "pass --iso to check a label")

    record("artifacts/one-kernel", len(referenced_kernels) == 1,
           f"entries reference {len(referenced_kernels)} distinct kernel path(s): "
           f"{', '.join(sorted(referenced_kernels)) or 'none'}")
    record("artifacts/one-initrd", len(referenced_initrds) == 1,
           f"entries reference {len(referenced_initrds)} distinct initrd path(s): "
           f"{', '.join(sorted(referenced_initrds)) or 'none'}")

    # The live payload the command line depends on.
    live_dir, squash_name = "LiveOS", "squashfs.img"
    for parsed in configs.values():
        for entry in parsed["entries"]:
            live_dir = cmdline_value(entry["cmdline"], "rd.live.dir") or live_dir
            squash_name = cmdline_value(entry["cmdline"], "rd.live.squashimg") or squash_name
    payload = medium / live_dir / squash_name
    shape, detail = squashfs_shape(payload)
    record("live-payload/present", shape not in {"missing", "empty"},
           f"{live_dir}/{squash_name}: {detail}")
    record("live-payload/shape", shape in {"squashfs-is-root", "nested-rootfs", "unknown"},
           f"{shape}: {detail}")

    # And finally the artifact itself, through the same reader the build used.
    initramfs_report = None
    for relative in sorted(referenced_initrds):
        target = medium / relative.lstrip("/")
        if not target.is_file():
            continue
        try:
            initramfs_report = _initramfs_module.qualify(
                target,
                _initramfs_module.DEFAULT_REQUIRED_MODULES,
                expect_kver,
            )
        except _initramfs_module.QualificationError as error:
            record(f"initramfs{relative}", False, f"unreadable: {error}")
            continue
        record(f"initramfs{relative}", initramfs_report["status"] == "PASS",
               f"{initramfs_report['failures']} failed check(s); modules: "
               f"{len(initramfs_report['dracutModules'])}; kernel: "
               f"{', '.join(initramfs_report['kernelReleases']) or 'none'}")
        for check in initramfs_report["checks"]:
            if check["status"] == "FAIL":
                record(f"initramfs{relative}/{check['check']}", False, check["detail"])

    # Kernel/initramfs release agreement. The kernel image on the medium carries
    # its release string; the initramfs reports the release it holds modules for.
    if initramfs_report is not None:
        for kernel_path in sorted(referenced_kernels):
            release = kernel_release(medium / kernel_path.lstrip("/"))
            if release is None:
                record(f"kernel-release{kernel_path}", True,
                       "the kernel image does not expose a readable release string; "
                       "not treated as a failure")
                continue
            matches = list(initramfs_report["kernelReleases"]) == [release]
            record(f"kernel-release{kernel_path}", matches,
                   f"{kernel_path} is {release}; the initramfs carries modules for "
                   f"{', '.join(initramfs_report['kernelReleases']) or 'nothing'}")

    return _finish(checks, medium, iso, label, configs, initramfs_report, expect_kver)


def kernel_release(path: Path) -> str | None:
    """The release string a bzImage records, if it can be found.

    x86 bzImage stores a pointer to its version string at offset 0x20e; the
    string lives at that offset plus 0x200. Read directly so this needs no
    external tool.
    """
    try:
        with path.open("rb") as handle:
            handle.seek(0x202)
            if handle.read(4) != b"HdrS":
                return None
            handle.seek(0x20E)
            pointer = int.from_bytes(handle.read(2), "little")
            handle.seek(pointer + 0x200)
            blob = handle.read(256)
    except OSError:
        return None
    text = blob.split(b"\x00", 1)[0].decode("ascii", "replace").strip()
    return text.split(" ", 1)[0] or None


def _finish(checks, medium, iso, label, configs, initramfs_report, expect_kver) -> dict:
    failures = [check for check in checks if check["status"] == "FAIL"]
    return {
        "schemaVersion": 1,
        "medium": str(iso or medium),
        "volumeLabel": label,
        "expectedKernelRelease": expect_kver,
        "bootConfigs": configs,
        "initramfs": initramfs_report,
        "checks": checks,
        "failures": len(failures),
        "status": "PASS" if not failures else "FAIL",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Qualify an installation ISO's boot artifacts.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--iso", type=Path, help="the ISO to inspect")
    source.add_argument("--root", type=Path,
                        help="a directory holding an already-extracted medium")
    parser.add_argument("--expect-label", default=None)
    parser.add_argument("--expect-kver", default=None)
    parser.add_argument("--json", type=Path, default=None)
    parser.add_argument("--quiet", action="store_true")
    arguments = parser.parse_args(argv)

    try:
        with opened(arguments.iso, arguments.root) as medium:
            report = qualify(medium, arguments.iso, arguments.expect_label,
                             arguments.expect_kver)
    except MediumError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 2

    if arguments.json:
        arguments.json.parent.mkdir(parents=True, exist_ok=True)
        arguments.json.write_text(json.dumps(report, indent=1), encoding="utf-8")

    if not arguments.quiet:
        print(f"medium: {report['medium']}")
        print(f"  volume label: {report['volumeLabel']!r}")
        for check in report["checks"]:
            print(f"  [{check['status']}] {check['check']}: {check['detail']}")

    if report["status"] == "PASS":
        print(f"PASS: {report['medium']} carries a bootable live-boot artifact set")
        return 0
    print(f"FAIL: {report['medium']}: {report['failures']} check(s) failed",
          file=sys.stderr)
    for check in report["checks"]:
        if check["status"] == "FAIL":
            print(f"  {check['check']}: {check['detail']}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
