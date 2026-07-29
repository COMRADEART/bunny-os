from __future__ import annotations

from datetime import datetime, timedelta, timezone
import tempfile
from pathlib import Path
import unittest
from unittest import mock

from tests.support import ROOT
import bunny_update_agent as agent


def manifest() -> dict:
    now = datetime.now(timezone.utc)
    return {
        "schemaVersion": 1,
        "sequence": 2,
        "channel": "developer",
        "osVersion": "0.1.1",
        "imageVersion": "0.1.1-2",
        "imageReference": "quay.io/comradeart/bunny-os/developer",
        "imageDigest": "sha256:" + "a" * 64,
        "architecture": agent._architecture(),
        "publishedAt": now.isoformat(),
        "expiresAt": (now + timedelta(days=2)).isoformat(),
        "minimumBunnyVersion": "0.2.0",
        "maximumBunnyVersion": "0.2.999",
        "contractVersion": "1.0.0",
        "downloadSize": 1024,
        "installedSize": 2048,
        "releaseNotesReference": "https://updates.example/releases/0.1.1",
        "keyId": "developer-1",
        "signature": "AA==",
    }


CONFIG = {"enabled": True, "channel": "developer", "manifestUrl": "https://updates.example/manifest.json", "imageRepositories": ["quay.io/comradeart/bunny-os"]}


class UpdateManifestTests(unittest.TestCase):
    def test_valid_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(agent, "SEQUENCE_PATH", Path(temporary) / "sequence"), mock.patch.object(agent, "BUNNY_ARTIFACT_PATH", ROOT / "build/manifests/bunny-artifact.placeholder.json"), mock.patch.object(agent, "_verify_signature"):
            agent._validate_manifest(manifest(), CONFIG, True)

    def test_bad_signature(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(agent, "KEY_DIR", Path(temporary)), mock.patch.object(agent, "REVOCATIONS_PATH", Path(temporary) / "revoked"):
            with self.assertRaisesRegex(agent.UpdateError, "not trusted"):
                agent._verify_signature(manifest())

    def test_wrong_architecture(self) -> None:
        value = manifest()
        value["architecture"] = "aarch64" if agent._architecture() == "x86_64" else "x86_64"
        with self.assertRaisesRegex(agent.UpdateError, "architecture"):
            agent._validate_manifest(value, CONFIG, False)

    def test_rollback_attack(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            sequence = Path(temporary) / "sequence"
            sequence.write_text("3\n", encoding="ascii")
            with mock.patch.object(agent, "SEQUENCE_PATH", sequence), self.assertRaisesRegex(agent.UpdateError, "sequence"):
                agent._validate_manifest(manifest(), CONFIG, True)

    def test_insufficient_disk(self) -> None:
        fake = mock.Mock(free=1)
        with mock.patch("bunny_update_agent.shutil.disk_usage", return_value=fake), self.assertRaises(agent.UpdateError):
            agent._check_space(manifest())

    def test_interrupted_download_fails_closed(self) -> None:
        with mock.patch("bunny_update_agent.urlopen", side_effect=OSError("interrupted")), self.assertRaisesRegex(agent.UpdateError, "download"):
            agent._fetch("https://updates.example/manifest.json")


if __name__ == "__main__":
    unittest.main()
