"""The initramfs qualification, and the faults it has to catch.

Every failure case here corresponds to something that either did happen or would
not have been noticed. The medium reached a GRUB menu in every recorded run and
never reached userspace, and the reason was inside an artifact that existed, was
the right size, and was named in the boot configuration — so the tests that
matter are the ones that build a plausible-looking initramfs and demand that the
checker refuse it.

The fixtures are real cpio archives assembled here, gzip-compressed with the
standard library, so these run anywhere: no dracut, no lsinitrd, no Fedora.
"""

from __future__ import annotations

import gzip
import io
import json
import subprocess
import sys
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "build/scripts/check-live-initramfs.py"
PRESERVE = ROOT / "build/scripts/preserve-initramfs-tail.py"


def _load(path: Path, name: str):
    loader = SourceFileLoader(name, str(path))
    spec = spec_from_loader(name, loader)
    assert spec is not None
    module = module_from_spec(spec)
    loader.exec_module(module)
    return module


checker = _load(SCRIPT, "bunny_check_live_initramfs")
preserver = _load(PRESERVE, "bunny_preserve_initramfs_tail")


# --------------------------------------------------------------------------
# Building initramfs images to order
# --------------------------------------------------------------------------

KERNEL = "7.1.5-200.fc44.x86_64"

# What a correct image contains, expressed once. Individual tests remove things
# from this to make each fault.
def complete_contents(kernel: str = KERNEL) -> dict[str, bytes]:
    modules = [
        "systemd", "base", "kernel-modules", "dmsquash-live", "livenet",
        "ostree", "overlayfs", "dm", "img-lib", "rootfs-block", "initqueue",
    ]
    contents: dict[str, bytes] = {
        checker.DRACUT_MODULE_MANIFEST: ("\n".join(modules) + "\n").encode(),
        checker.DRACUT_BUILD_PARAMETERS: b" --force --no-hostonly --reproducible\n",
    }
    for module, paths in checker.MODULE_EVIDENCE.items():
        for path in paths:
            contents[path] = f"# {module}\n".encode()
    for obj in checker.REQUIRED_KERNEL_OBJECTS:
        contents[f"usr/lib/modules/{kernel}/{obj}.xz"] = b"\x00"
    contents[f"usr/lib/modules/{kernel}/modules.dep"] = b""
    # The sibling directory that is not a kernel release, and once made a
    # correct artifact report two kernels.
    contents[f"usr/lib/modules/keys/redhatsecureboot.cer"] = b"\x00"
    return contents


def cpio(entries: dict[str, bytes], mode: int = 0o100644) -> bytes:
    """A newc cpio archive holding `entries`."""
    out = io.BytesIO()
    for index, (name, data) in enumerate(entries.items(), start=1):
        raw = name.encode() + b"\x00"
        header = (
            b"070701"
            + b"%08X" % index          # ino
            + b"%08X" % mode
            + b"%08X" % 0 + b"%08X" % 0   # uid, gid
            + b"%08X" % 1                 # nlink
            + b"%08X" % 0                 # mtime
            + b"%08X" % len(data)
            + b"%08X" % 0 + b"%08X" % 0   # devmajor, devminor
            + b"%08X" % 0 + b"%08X" % 0   # rdevmajor, rdevminor
            + b"%08X" % len(raw)
            + b"%08X" % 0                 # check
        )
        out.write(header + raw)
        out.write(b"\x00" * (-(len(header) + len(raw)) % 4))
        out.write(data)
        out.write(b"\x00" * (-len(data) % 4))
    trailer = b"TRAILER!!!\x00"
    header = (b"070701" + b"%08X" % 0 + b"%08X" % 0 + b"%08X" % 0 + b"%08X" % 0
              + b"%08X" % 1 + b"%08X" % 0 + b"%08X" % 0 + b"%08X" % 0
              + b"%08X" % 0 + b"%08X" % 0 + b"%08X" % 0
              + b"%08X" % len(trailer) + b"%08X" % 0)
    out.write(header + trailer)
    out.write(b"\x00" * (-(len(header) + len(trailer)) % 4))
    return out.getvalue()


def initramfs(contents: dict[str, bytes], *, early: bool = True,
              appended: dict[str, bytes] | None = None) -> bytes:
    """An initramfs shaped like the real one: plain cpio, then a compressed cpio.

    `appended` adds a third segment, which is what fedora-bootc:44 does.
    """
    blob = b""
    if early:
        blob += cpio({"early_cpio": b"1\n"})
        blob += b"\x00" * ((-len(blob)) % 4 or 4)
    blob += gzip.compress(cpio(contents))
    if appended is not None:
        blob += gzip.compress(cpio(appended))
    return blob


def write(directory: Path, name: str, blob: bytes) -> Path:
    path = directory / name
    path.write_bytes(blob)
    return path


def run(*arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *arguments],
                          capture_output=True, text=True, check=False)


# --------------------------------------------------------------------------


class ReaderTests(unittest.TestCase):
    """The reader, which had to be corrected against a real artifact."""

    def setUp(self) -> None:
        self.scratch = Path(tempfile.mkdtemp())

    def test_reads_all_segments_not_only_the_first_compressed_one(self) -> None:
        # The shipped artifact is three segments — plain, zstd, gzip — and the
        # first version of this reader saw the middle one only. Had a required
        # module lived in the third, it would have been reported missing from an
        # image that contained it.
        path = write(self.scratch, "three.img",
                     initramfs(complete_contents(),
                               appended={"dev/random": b"", "dev/urandom": b""}))
        image = checker.Initramfs(path)
        self.assertEqual([segment.encoding for segment in image.segments],
                         ["cpio", "gzip", "gzip"])
        self.assertIn("dev/random", image.names)
        self.assertIn("usr/bin/dmsquash-live-root", image.names)

    def test_a_later_segment_shadows_an_earlier_one(self) -> None:
        contents = complete_contents()
        contents["usr/lib/dracut/marker"] = b"first"
        path = write(self.scratch, "shadow.img",
                     initramfs(contents, appended={"usr/lib/dracut/marker": b"second"}))
        self.assertEqual(checker.Initramfs(path).read("usr/lib/dracut/marker"), b"second")

    def test_keys_is_not_mistaken_for_a_kernel_release(self) -> None:
        path = write(self.scratch, "keys.img", initramfs(complete_contents()))
        self.assertEqual(checker.Initramfs(path).kernel_releases(), (KERNEL,))

    def test_an_image_without_an_early_cpio_still_reads(self) -> None:
        path = write(self.scratch, "plain.img",
                     initramfs(complete_contents(), early=False))
        self.assertIn("usr/bin/dmsquash-live-root", checker.Initramfs(path).names)

    def test_truncated_archive_is_an_error_not_a_short_file_list(self) -> None:
        blob = initramfs(complete_contents())
        path = write(self.scratch, "torn.img", blob[: len(blob) // 2])
        with self.assertRaises(checker.QualificationError):
            checker.Initramfs(path)


class QualificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = Path(tempfile.mkdtemp())

    def qualify(self, contents, **kwargs):
        path = write(self.scratch, "initramfs.img", initramfs(contents))
        return checker.qualify(path, checker.DEFAULT_REQUIRED_MODULES,
                               kwargs.get("expect_kver", KERNEL))

    def failed(self, report) -> set[str]:
        return {check["check"] for check in report["checks"]
                if check["status"] == "FAIL"}

    def test_a_complete_image_passes(self) -> None:
        report = self.qualify(complete_contents())
        self.assertEqual(report["status"], "PASS", report["checks"])
        self.assertEqual(report["failures"], 0)

    def test_missing_dmsquash_live_fails(self) -> None:
        # The actual fault. root=live:CDLABEL= is parsed by this module and by
        # nothing else, so its absence is the whole reason the medium never
        # reached userspace.
        contents = complete_contents()
        manifest = contents[checker.DRACUT_MODULE_MANIFEST].decode().split()
        manifest.remove("dmsquash-live")
        contents[checker.DRACUT_MODULE_MANIFEST] = ("\n".join(manifest) + "\n").encode()
        for path in checker.MODULE_EVIDENCE["dmsquash-live"]:
            del contents[path]
        report = self.qualify(contents)
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("module/dmsquash-live", self.failed(report))
        self.assertIn(
            "file/var/lib/dracut/hooks/cmdline/30-parse-dmsquash-live.sh",
            self.failed(report),
        )

    def test_missing_livenet_fails(self) -> None:
        contents = complete_contents()
        manifest = contents[checker.DRACUT_MODULE_MANIFEST].decode().split()
        manifest.remove("livenet")
        contents[checker.DRACUT_MODULE_MANIFEST] = ("\n".join(manifest) + "\n").encode()
        for path in checker.MODULE_EVIDENCE["livenet"]:
            del contents[path]
        self.assertIn("module/livenet", self.failed(self.qualify(contents)))

    def test_a_module_named_in_the_manifest_but_not_installed_still_fails(self) -> None:
        # The manifest is dracut's claim about what it did. If the name is there
        # and the hook that parses the kernel command line is not, the image
        # does not work and a name check alone would have passed it.
        contents = complete_contents()
        for path in checker.MODULE_EVIDENCE["dmsquash-live"]:
            del contents[path]
        report = self.qualify(contents)
        self.assertEqual(report["status"], "FAIL")
        self.assertNotIn("module/dmsquash-live", self.failed(report))
        self.assertIn("file/usr/bin/dmsquash-live-root", self.failed(report))

    def test_missing_squashfs_kernel_object_fails(self) -> None:
        # Every dracut module present and the medium still does not boot,
        # because nothing can mount the squashfs.
        contents = complete_contents()
        del contents[f"usr/lib/modules/{KERNEL}/kernel/fs/squashfs/squashfs.ko.xz"]
        self.assertIn("kernel-object/kernel/fs/squashfs/squashfs.ko",
                      self.failed(self.qualify(contents)))

    def test_wrong_kernel_mapping_fails(self) -> None:
        report = self.qualify(complete_contents(), expect_kver="9.9.9-9.fc44.x86_64")
        self.assertIn("kernel-release/expected", self.failed(report))

    def test_two_kernel_releases_fail_as_ambiguous(self) -> None:
        contents = complete_contents()
        contents["usr/lib/modules/6.0.0-1.fc44.x86_64/modules.dep"] = b""
        self.assertIn("kernel-release/single", self.failed(self.qualify(contents)))

    def test_an_image_with_no_dracut_manifest_is_refused(self) -> None:
        path = write(self.scratch, "nomanifest.img",
                     initramfs({"usr/bin/true": b""}))
        with self.assertRaises(checker.QualificationError):
            checker.qualify(path, checker.DEFAULT_REQUIRED_MODULES, None)


class CommandLineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = Path(tempfile.mkdtemp())

    def test_exit_status_and_report(self) -> None:
        good = write(self.scratch, "good.img", initramfs(complete_contents()))
        report = self.scratch / "report.json"
        finished = run("--initramfs", str(good), "--expect-kver", KERNEL,
                       "--json", str(report), "--quiet")
        self.assertEqual(finished.returncode, 0, finished.stderr)
        self.assertEqual(json.loads(report.read_text())["status"], "PASS")

    def test_a_missing_artifact_is_a_failure_not_a_crash(self) -> None:
        finished = run("--initramfs", str(self.scratch / "absent.img"), "--quiet")
        self.assertEqual(finished.returncode, 2)
        self.assertIn("no such initramfs", finished.stderr)

    def test_an_empty_artifact_is_a_failure(self) -> None:
        empty = write(self.scratch, "empty.img", b"")
        finished = run("--initramfs", str(empty), "--quiet")
        self.assertEqual(finished.returncode, 2)

    def test_a_failing_image_exits_nonzero_and_names_the_module(self) -> None:
        contents = complete_contents()
        manifest = contents[checker.DRACUT_MODULE_MANIFEST].decode().split()
        manifest.remove("dmsquash-live")
        contents[checker.DRACUT_MODULE_MANIFEST] = ("\n".join(manifest) + "\n").encode()
        bad = write(self.scratch, "bad.img", initramfs(contents))
        finished = run("--initramfs", str(bad), "--quiet")
        self.assertEqual(finished.returncode, 2)
        self.assertIn("dmsquash-live", finished.stderr)


class TailPreservationTests(unittest.TestCase):
    """Regeneration must not quietly drop what the base appended."""

    def setUp(self) -> None:
        self.scratch = Path(tempfile.mkdtemp())

    def test_appended_segment_is_carried_across_a_regeneration(self) -> None:
        original = write(self.scratch, "original.img",
                         initramfs(complete_contents(),
                                   appended={"dev/random": b"", "dev/urandom": b""}))
        regenerated = write(self.scratch, "new.img", initramfs(complete_contents()))
        self.assertNotIn("dev/random", checker.Initramfs(regenerated).names)

        finished = subprocess.run(
            [sys.executable, str(PRESERVE), "--original", str(original),
             "--regenerated", str(regenerated)],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(finished.returncode, 0, finished.stderr)
        after = checker.Initramfs(regenerated)
        self.assertIn("dev/random", after.names)
        self.assertIn("dev/urandom", after.names)
        # and the modules are still readable afterwards
        self.assertIn("usr/bin/dmsquash-live-root", after.names)

    def test_nothing_to_carry_is_not_a_failure(self) -> None:
        original = write(self.scratch, "original.img", initramfs(complete_contents()))
        regenerated = write(self.scratch, "new.img", initramfs(complete_contents()))
        before = regenerated.read_bytes()
        finished = subprocess.run(
            [sys.executable, str(PRESERVE), "--original", str(original),
             "--regenerated", str(regenerated)],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(finished.returncode, 0, finished.stderr)
        self.assertEqual(regenerated.read_bytes(), before)


class ConfigurationTests(unittest.TestCase):
    """The configuration and the build step have to agree with each other."""

    def setUp(self) -> None:
        self.conf = (ROOT / "installer/config/bunny-live-dracut.conf").read_text(
            encoding="utf-8")

    def test_the_configuration_requests_the_modules_image_builder_requires(self) -> None:
        requested = set()
        for line in self.conf.splitlines():
            stripped = line.strip()
            if stripped.startswith("add_dracutmodules+="):
                requested.update(stripped.split('"')[1].split())
        self.assertEqual(requested, {"dmsquash-live", "livenet", "ostree"})

    def test_host_only_is_off_because_dmsquash_live_refuses_a_host_only_build(self) -> None:
        self.assertIn('hostonly="no"', self.conf)

    def test_it_is_installed_where_dracut_reads_it_after_the_bootc_files(self) -> None:
        routes = (ROOT / "build/scripts/install_routes.py").read_text(encoding="utf-8")
        self.assertIn("/usr/lib/dracut/dracut.conf.d/95-bunny-live.conf", routes)
        self.assertIn("installer/config/bunny-live-dracut.conf", routes)

    def test_the_build_regenerates_the_initramfs_after_installing_the_config(self) -> None:
        # A dracut.conf.d file changes no bytes until dracut runs again. This is
        # the assertion that the necessary step is also the sufficient one.
        containerfile = (ROOT / "build/Containerfile").read_text(encoding="utf-8")
        self.assertIn("regenerate-live-initramfs.sh", containerfile)
        install_at = containerfile.index("install-root.py")
        regenerate_at = containerfile.index("regenerate-live-initramfs.sh")
        finalise_at = containerfile.index("finalise-image.sh")
        self.assertLess(install_at, regenerate_at,
                        "regeneration must follow the step that installs the config")
        self.assertLess(regenerate_at, finalise_at,
                        "regeneration must precede finalisation, whose canonicalised "
                        "package databases the step's rpm queries would disturb")

    def test_regeneration_does_not_swallow_failure(self) -> None:
        script = (ROOT / "build/scripts/regenerate-live-initramfs.sh").read_text(
            encoding="utf-8")
        self.assertIn("set -euo pipefail", script)
        self.assertIn("check-live-initramfs.py", script)
        # Only the code. The prose above it says the words "|| true" in order to
        # say the script does not use them, and an assertion that cannot tell
        # the two apart would forbid explaining itself.
        code = [line for line in script.splitlines()
                if line.strip() and not line.lstrip().startswith("#")]
        self.assertNotIn("|| true", "\n".join(code))

    def test_the_build_gate_refuses_an_unqualified_medium(self) -> None:
        build = (ROOT / "build/scripts/build-live-image.sh").read_text(encoding="utf-8")
        self.assertIn("check-iso-boot-artifacts.py", build)
        self.assertIn("live-initramfs.json", build)
        gate_at = build.index("check-iso-boot-artifacts.py")
        manifest_at = build.index("write-media-manifest.py")
        self.assertLess(gate_at, manifest_at,
                        "the medium must be qualified before a manifest declares it")


if __name__ == "__main__":
    unittest.main()
