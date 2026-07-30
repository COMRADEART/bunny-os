"""Seventeen dimensions, read out of the archive by one collector.

A dimension one builder collected and the other did not is `NOT_COLLECTED`, and
an incomplete comparison cannot support a reproducibility claim. The answer to
"the local builder never collected xattrs" is to collect them — not to drop the
dimension, and certainly not to mark the two equal.

Both sides go through this collector, so a difference in the report is a
difference in the images rather than a difference in how they were measured.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts/reproducibility"))

from collect_comparison_dimensions import collect, read_image  # noqa: E402

from release.comparison import COMPARISON_DIMENSIONS  # noqa: E402


def layer(entries: dict[str, dict]) -> bytes:
    """A gzipped tar layer. Each entry is {content, mode, uid, gid, xattrs, type}."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for name, spec in entries.items():
            kind = spec.get("type", "file")
            info = tarfile.TarInfo(name)
            info.mode = spec.get("mode", 0o644)
            info.uid = spec.get("uid", 0)
            info.gid = spec.get("gid", 0)
            if spec.get("xattrs"):
                info.pax_headers = {
                    f"SCHILY.xattr.{key}": value for key, value in spec["xattrs"].items()
                }
            if kind == "dir":
                info.type = tarfile.DIRTYPE
                archive.addfile(info)
            elif kind == "symlink":
                info.type = tarfile.SYMTYPE
                info.linkname = spec["link"]
                archive.addfile(info)
            else:
                payload = spec.get("content", b"")
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))
    return gzip.compress(buffer.getvalue(), mtime=0)


def oci_archive(path: Path, layers: list[bytes], config: dict | None = None) -> Path:
    """A minimal but real OCI archive: index, manifest, config, layer blobs."""
    config = config or {"architecture": "amd64", "os": "linux"}
    blobs: dict[str, bytes] = {}

    def add(payload: bytes) -> str:
        digest = "sha256:" + hashlib.sha256(payload).hexdigest()
        blobs[digest] = payload
        return digest

    config_digest = add(json.dumps(config, sort_keys=True).encode())
    layer_digests = [add(payload) for payload in layers]
    manifest = {
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "config": {"mediaType": "application/vnd.oci.image.config.v1+json",
                   "digest": config_digest, "size": len(blobs[config_digest])},
        "layers": [
            {"mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
             "digest": digest, "size": len(blobs[digest])}
            for digest in layer_digests
        ],
    }
    manifest_digest = add(json.dumps(manifest, sort_keys=True).encode())
    index = {
        "schemaVersion": 2,
        "manifests": [{"mediaType": manifest["mediaType"], "digest": manifest_digest,
                       "size": len(blobs[manifest_digest])}],
    }

    with tarfile.open(path, "w") as archive:
        def write(name: str, payload: bytes) -> None:
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))

        write("oci-layout", json.dumps({"imageLayoutVersion": "1.0.0"}).encode())
        write("index.json", json.dumps(index).encode())
        for digest, payload in blobs.items():
            write("blobs/" + digest.replace(":", "/"), payload)
    return path


BASE_LAYER = {
    "usr/": {"type": "dir", "mode": 0o755},
    "usr/bin/": {"type": "dir", "mode": 0o755},
    "usr/bin/hello": {"content": b"#!/bin/sh\necho hello\n", "mode": 0o755},
    "usr/bin/setuid-tool": {"content": b"binary", "mode": 0o4755,
                            "xattrs": {"security.capability": "cap_net_raw"}},
    "usr/lib/systemd/system/bunny.service": {"content": b"[Unit]\n", "mode": 0o644,
                                             "xattrs": {"security.selinux": "system_u:object_r:systemd_unit_file_t:s0"}},
    "usr/share/applications/bunny.desktop": {"content": b"[Desktop Entry]\n", "mode": 0o644},
    "usr/share/glib-2.0/schemas/gschemas.compiled": {"content": b"compiled", "mode": 0o644},
    "usr/lib/modules/7.1.5-200.fc44.x86_64/vmlinuz": {"content": b"kernel", "mode": 0o644},
    "usr/lib/bootc/install.toml": {"content": b"[install]\n", "mode": 0o644},
    "etc/machine-id": {"content": b"volatile\n", "mode": 0o444},
    "var/log/dnf.log": {"content": b"volatile\n", "mode": 0o644},
    "usr/lib/os-release": {"content": b"ID=fedora\n", "mode": 0o644},
}

SBOM = {"packages": [{"name": "podman", "versionInfo": "5.8.4"},
                     {"name": "bootc", "versionInfo": "1.16.4"}]}


class CollectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        base = Path(self.directory.name)
        self.archive = oci_archive(base / "image.oci.tar", [layer(BASE_LAYER)])
        self.sbom = base / "sbom.spdx.json"
        self.sbom.write_text(json.dumps(SBOM), encoding="utf-8")
        self.normalisation = base / "normalisation.json"
        # Both digests describe the shipped archive. Normalisation runs in place,
        # so the file on disk *is* the normalised one; a fixture whose
        # normalisedDigest named some other file would be describing a state the
        # build cannot produce.
        archive_digest = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        self.normalisation.write_text(json.dumps({
            "rawDigest": archive_digest,
            "normalisedDigest": archive_digest,
        }), encoding="utf-8")

    def tearDown(self) -> None:
        self.directory.cleanup()

    def collected(self) -> dict:
        return collect(self.archive, sbom=self.sbom, normalisation=self.normalisation)

    def test_every_one_of_the_seventeen_dimensions_is_collected(self) -> None:
        dimensions = self.collected()["dimensions"]
        for name, _, _ in COMPARISON_DIMENSIONS:
            with self.subTest(dimension=name):
                self.assertIn(name, dimensions)
                self.assertIsNotNone(dimensions[name], f"{name} was not collected")

    def test_the_dimension_names_match_the_comparison_definition_exactly(self) -> None:
        self.assertEqual(
            set(self.collected()["dimensions"]),
            {name for name, _, _ in COMPARISON_DIMENSIONS},
        )

    def test_the_filesystem_tree_lists_paths(self) -> None:
        tree = self.collected()["dimensions"]["filesystemTree"]
        self.assertIn("usr/bin/hello", tree)
        self.assertIn("usr/lib/systemd/system/bunny.service", tree)

    def test_file_digests_are_content_hashes(self) -> None:
        digests = self.collected()["dimensions"]["fileDigests"]
        self.assertEqual(
            digests["usr/bin/hello"],
            hashlib.sha256(b"#!/bin/sh\necho hello\n").hexdigest(),
        )

    def test_setuid_bits_are_captured_in_permissions(self) -> None:
        # A setuid bit appearing or vanishing between builders is exactly the
        # kind of difference this dimension exists for.
        permissions = self.collected()["dimensions"]["permissions"]
        self.assertEqual(permissions["usr/bin/setuid-tool"], "4755")
        self.assertEqual(permissions["usr/bin/hello"], "0755")

    def test_ownership_is_captured(self) -> None:
        self.assertEqual(self.collected()["dimensions"]["ownership"]["usr/bin/hello"], "0:0")

    def test_extended_attributes_including_capabilities_are_captured(self) -> None:
        xattrs = self.collected()["dimensions"]["extendedAttributes"]
        self.assertEqual(xattrs["usr/bin/setuid-tool"]["security.capability"], "cap_net_raw")

    def test_selinux_labels_are_captured_separately(self) -> None:
        labels = self.collected()["dimensions"]["selinuxLabels"]
        self.assertEqual(
            labels["usr/lib/systemd/system/bunny.service"],
            "system_u:object_r:systemd_unit_file_t:s0",
        )

    def test_an_archive_with_no_selinux_labels_reports_not_collected(self) -> None:
        # Two empty sets compare equal. Reporting {} would make the dimension
        # silently MATCH on both builders having measured nothing, which claims
        # a comparison that did not happen. A bootc image carries no contexts in
        # its layers, so the honest value is None.
        stripped = {
            name: {k: v for k, v in spec.items() if k != "xattrs"}
            for name, spec in BASE_LAYER.items()
        }
        with tempfile.TemporaryDirectory() as directory:
            archive = oci_archive(Path(directory) / "image.oci.tar", [layer(stripped)])
            payload = collect(archive, sbom=None, normalisation=None)
            self.assertIsNone(payload["dimensions"]["selinuxLabels"])
            self.assertIn("selinuxLabels", payload["notCollected"])
            self.assertIn("bootc install", payload["notCollected"]["selinuxLabels"])

    def test_two_archives_with_no_labels_do_not_match_on_that_dimension(self) -> None:
        from release.comparison import compare_dimension

        result = compare_dimension("selinuxLabels", {"first": None, "second": None})
        self.assertEqual(result.state, "NOT_COLLECTED")

    def test_systemd_units_desktop_entries_and_schemas_are_captured(self) -> None:
        dimensions = self.collected()["dimensions"]
        self.assertIn("usr/lib/systemd/system/bunny.service", dimensions["systemdUnits"])
        self.assertIn("usr/share/applications/bunny.desktop", dimensions["desktopEntries"])
        self.assertIn("usr/share/glib-2.0/schemas/gschemas.compiled", dimensions["schemas"])

    def test_the_kernel_version_and_digest_are_captured(self) -> None:
        kernel = self.collected()["dimensions"]["kernel"]
        self.assertIn("7.1.5-200.fc44.x86_64", kernel["versions"])
        self.assertEqual(
            kernel["vmlinuz"]["usr/lib/modules/7.1.5-200.fc44.x86_64/vmlinuz"],
            hashlib.sha256(b"kernel").hexdigest(),
        )

    def test_an_absent_initramfs_states_why_rather_than_being_empty(self) -> None:
        initramfs = self.collected()["dimensions"]["initramfs"]
        self.assertIn("notPresent", initramfs)
        self.assertIn("bootc", initramfs["notPresent"])

    def test_boot_configuration_is_captured(self) -> None:
        self.assertIn(
            "usr/lib/bootc/install.toml", self.collected()["dimensions"]["bootConfiguration"]
        )

    def test_oci_layer_digests_are_captured_in_order(self) -> None:
        layers = self.collected()["dimensions"]["ociLayers"]
        self.assertEqual(len(layers), 1)
        self.assertTrue(layers[0].startswith("sha256:"))

    def test_the_package_inventory_and_sbom_come_from_the_sbom(self) -> None:
        dimensions = self.collected()["dimensions"]
        self.assertEqual(dimensions["packageInventory"], ["bootc@1.16.4", "podman@5.8.4"])
        self.assertEqual(len(dimensions["sbom"]), 2)

    def test_the_raw_archive_digest_is_the_file_on_disk(self) -> None:
        payload = self.collected()
        self.assertEqual(
            payload["dimensions"]["rawArchive"],
            hashlib.sha256(self.archive.read_bytes()).hexdigest(),
        )

    def test_a_normalisation_record_for_another_file_is_refused(self) -> None:
        self.normalisation.write_text(
            json.dumps({"rawDigest": "0" * 64, "normalisedDigest": "n" * 64}), encoding="utf-8"
        )
        with self.assertRaises(SystemExit) as caught:
            self.collected()
        self.assertIn("not from the same build", str(caught.exception))

    def test_volatile_paths_are_excluded_and_listed(self) -> None:
        payload = self.collected()
        self.assertNotIn("etc/machine-id", payload["dimensions"]["filesystemTree"])
        self.assertNotIn("var/log/dnf.log", payload["dimensions"]["filesystemTree"])
        self.assertIn("etc/machine-id", payload["volatilePathsExcluded"])
        self.assertIn("var/log/dnf.log", payload["volatilePathsExcluded"])
        self.assertIn("visible rather than silent", payload["volatileNote"])


class WhiteoutTests(unittest.TestCase):
    """A layered image's filesystem is not the union of its layers."""

    def _tree(self, layers: list[dict]) -> list[str]:
        with tempfile.TemporaryDirectory() as directory:
            archive = oci_archive(
                Path(directory) / "image.oci.tar", [layer(entries) for entries in layers]
            )
            return collect(archive, sbom=None, normalisation=None)["dimensions"]["filesystemTree"]

    def test_a_whiteout_removes_the_file_from_the_tree(self) -> None:
        tree = self._tree([
            {"usr/bin/removed": {"content": b"x"}, "usr/bin/kept": {"content": b"y"}},
            {"usr/bin/.wh.removed": {"content": b""}},
        ])
        self.assertNotIn("usr/bin/removed", tree)
        self.assertIn("usr/bin/kept", tree)

    def test_an_opaque_whiteout_clears_the_directory(self) -> None:
        tree = self._tree([
            {"usr/share/doc/a": {"content": b"a"}, "usr/share/doc/b": {"content": b"b"},
             "usr/bin/kept": {"content": b"y"}},
            {"usr/share/doc/.wh..wh..opq": {"content": b""}},
        ])
        self.assertNotIn("usr/share/doc/a", tree)
        self.assertNotIn("usr/share/doc/b", tree)
        self.assertIn("usr/bin/kept", tree)

    def test_a_later_layer_replaces_an_earlier_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive = oci_archive(Path(directory) / "image.oci.tar", [
                layer({"usr/bin/tool": {"content": b"old"}}),
                layer({"usr/bin/tool": {"content": b"new"}}),
            ])
            digests = collect(archive, sbom=None, normalisation=None)["dimensions"]["fileDigests"]
            self.assertEqual(digests["usr/bin/tool"], hashlib.sha256(b"new").hexdigest())


class TwoArchivesTests(unittest.TestCase):
    """The comparison must see a real difference and must not invent one."""

    def _collect(self, directory: Path, name: str, entries: dict) -> dict:
        archive = oci_archive(directory / f"{name}.oci.tar", [layer(entries)])
        return collect(archive, sbom=None, normalisation=None)["dimensions"]

    def test_identical_content_produces_identical_semantic_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            first = self._collect(base, "first", BASE_LAYER)
            second = self._collect(base, "second", BASE_LAYER)
            for name, kind, _ in COMPARISON_DIMENSIONS:
                if kind != "semantic":
                    continue
                with self.subTest(dimension=name):
                    self.assertEqual(first[name], second[name])

    def test_a_changed_file_shows_up_in_file_digests(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            changed = {**BASE_LAYER, "usr/bin/hello": {"content": b"different", "mode": 0o755}}
            first = self._collect(base, "first", BASE_LAYER)
            second = self._collect(base, "second", changed)
            self.assertNotEqual(first["fileDigests"], second["fileDigests"])
            self.assertEqual(first["filesystemTree"], second["filesystemTree"])

    def test_a_changed_permission_shows_up_only_in_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            changed = {**BASE_LAYER, "usr/bin/hello": {"content": b"#!/bin/sh\necho hello\n", "mode": 0o777}}
            first = self._collect(base, "first", BASE_LAYER)
            second = self._collect(base, "second", changed)
            self.assertNotEqual(first["permissions"], second["permissions"])
            self.assertEqual(first["fileDigests"], second["fileDigests"])


class ReadImageTests(unittest.TestCase):
    def test_an_archive_without_an_index_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "not-oci.tar"
            with tarfile.open(path, "w") as archive:
                info = tarfile.TarInfo("hello.txt")
                info.size = 5
                archive.addfile(info, io.BytesIO(b"hello"))
            with self.assertRaises(SystemExit) as caught:
                read_image(path)
            self.assertIn("no index.json", str(caught.exception))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
