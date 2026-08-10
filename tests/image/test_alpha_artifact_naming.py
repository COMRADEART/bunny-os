# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression coverage for Alpha artifact renaming and provenance."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
ALPHA_BUILDER = ROOT / "build/scripts/build-alpha-image.sh"
MANIFEST_WRITER = ROOT / "build/scripts/write-media-manifest.py"
COMMIT = "a" * 40


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class AlphaArtifactNamingTests(unittest.TestCase):
    def run_writer(self, root: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(MANIFEST_WRITER),
                "--root",
                str(root),
                "--source-commit",
                COMMIT,
                "--image-version",
                "0.1.0-alpha.test",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

    def write_provenance(
        self, root: Path, artifacts: list[dict[str, object]], disk_images: list[str]
    ) -> None:
        (root / "provenance.json").write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "sourceCommit": COMMIT,
                    "artifacts": artifacts,
                    "diskImages": disk_images,
                }
            ),
            encoding="utf-8",
        )

    def test_alpha_records_are_written_after_public_artifact_names(self) -> None:
        source = ALPHA_BUILDER.read_text(encoding="utf-8")
        rename = source.index('mv -- "${artifact}" "${target}"')
        provenance = source.index("write-build-provenance.py", rename)
        manifest = source.index("write-media-manifest.py", provenance)
        self.assertLess(rename, provenance)
        self.assertLess(provenance, manifest)

    def test_stale_generic_provenance_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            disk = root / "disk/bunny-os-0.1.0-alpha-test.qcow2"
            disk.parent.mkdir()
            disk.write_bytes(b"final-disk")
            self.write_provenance(
                root,
                [
                    {
                        "path": "disk/bootc-fedora-44-qcow2-x86_64.qcow2",
                        "size": disk.stat().st_size,
                        "sha256": sha256(b"final-disk"),
                    }
                ],
                ["disk/bootc-fedora-44-qcow2-x86_64.qcow2"],
            )

            result = self.run_writer(root)

            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("disagrees with the final media tree", result.stdout)
            self.assertFalse((root / "BUNNY-MANIFEST.json").exists())

    def test_final_names_sizes_and_digests_are_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            disk_path = "disk/bunny-os-0.1.0-alpha-test.qcow2"
            oci_path = "bunny-os.oci.tar"
            disk = root / disk_path
            disk.parent.mkdir()
            disk.write_bytes(b"final-disk")
            oci = root / oci_path
            oci.write_bytes(b"oci-archive")
            artifacts = [
                {
                    "path": oci_path,
                    "size": oci.stat().st_size,
                    "sha256": sha256(b"oci-archive"),
                },
                {
                    "path": disk_path,
                    "size": disk.stat().st_size,
                    "sha256": sha256(b"final-disk"),
                },
            ]
            self.write_provenance(root, artifacts, [disk_path])

            result = self.run_writer(root)

            self.assertEqual(result.returncode, 0, result.stdout)
            manifest = json.loads(
                (root / "BUNNY-MANIFEST.json").read_text(encoding="utf-8")
            )
            indexed = {item["path"]: item for item in manifest["files"]}
            self.assertTrue(indexed[disk_path]["critical"])
            self.assertEqual(indexed[disk_path]["sha256"], sha256(b"final-disk"))


if __name__ == "__main__":
    unittest.main()
