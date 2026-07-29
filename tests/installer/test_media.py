from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from installer.validation.media import MediaVerificationError, verify_manifest


class MediaTests(unittest.TestCase):
    def fixture(self, directory: str, *, digest: str | None = None, relative: str = "images/root.img"):
        root = Path(directory) / "media"
        target = root / "images/root.img"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"verified-image")
        manifest = Path(directory) / "manifest.json"
        manifest.write_text(json.dumps({"schemaVersion": 1, "files": [{"path": relative, "sha256": digest or hashlib.sha256(b"verified-image").hexdigest(), "critical": True}]}), encoding="utf-8")
        signature = Path(directory) / "manifest.sig"
        signature.write_bytes(b"signature")
        key = Path(directory) / "public.pem"
        key.write_text("public key fixture", encoding="utf-8")
        return root, manifest, signature, key

    @patch("installer.validation.media.subprocess.run")
    def test_valid_signature_and_hash_pass(self, run) -> None:
        run.return_value = subprocess.CompletedProcess([], 0, b"", b"")
        with tempfile.TemporaryDirectory() as directory:
            root, manifest, signature, key = self.fixture(directory)
            value = verify_manifest(root, manifest, signature_path=signature, public_key=key)
            self.assertTrue(value["verified"])
            self.assertEqual(value["filesChecked"], ["images/root.img"])

    @patch("installer.validation.media.subprocess.run")
    def test_signature_failure_is_critical(self, run) -> None:
        run.return_value = subprocess.CompletedProcess([], 1, b"", b"bad")
        with tempfile.TemporaryDirectory() as directory:
            root, manifest, signature, key = self.fixture(directory)
            with self.assertRaises(MediaVerificationError):
                verify_manifest(root, manifest, signature_path=signature, public_key=key)

    @patch("installer.validation.media.subprocess.run")
    def test_checksum_mismatch_fails(self, run) -> None:
        run.return_value = subprocess.CompletedProcess([], 0, b"", b"")
        with tempfile.TemporaryDirectory() as directory:
            root, manifest, signature, key = self.fixture(directory, digest="0" * 64)
            with self.assertRaises(MediaVerificationError):
                verify_manifest(root, manifest, signature_path=signature, public_key=key)

    @patch("installer.validation.media.subprocess.run")
    def test_path_traversal_fails(self, run) -> None:
        run.return_value = subprocess.CompletedProcess([], 0, b"", b"")
        with tempfile.TemporaryDirectory() as directory:
            root, manifest, signature, key = self.fixture(directory, relative="../outside")
            with self.assertRaises(MediaVerificationError):
                verify_manifest(root, manifest, signature_path=signature, public_key=key)

