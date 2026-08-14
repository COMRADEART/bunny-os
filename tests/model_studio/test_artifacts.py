# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The run directory: written once, digested, and refusing to overwrite silently."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from model_studio.artifacts import RunArtifacts, directory_digest, file_digest
from model_studio.config import config_from_mapping
from model_studio.errors import ModelStudioError
from model_studio.provenance import ProvenanceRecord

MINIMAL = {
    "model": {"base": "org/name"},
    "training": {"method": "lora"},
    "dataset": {"path": "./data.jsonl"},
    "output": {"directory": "./out"},
}


class Directory(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name) / "run"

    def test_it_creates_and_writes(self) -> None:
        artifacts = RunArtifacts.create(self.root)
        artifacts.write_config(config_from_mapping(MINIMAL))
        artifacts.write_provenance(ProvenanceRecord(job_id="j1", status="completed"))
        artifacts.append_log({"kind": "step", "step": 1})
        artifacts.append_log({"kind": "step", "step": 2})
        manifest = artifacts.write_manifest()

        document = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertIn("config.snapshot.json", document["files"])
        self.assertIn("provenance.json", document["files"])
        self.assertIn("training-log.jsonl", document["files"])
        self.assertNotIn("MANIFEST.json", document["files"],
                         "a manifest cannot contain its own digest")
        self.assertEqual(len(artifacts.log_path.read_text(encoding="utf-8").splitlines()), 2)

    def test_it_refuses_to_overwrite_a_run(self) -> None:
        artifacts = RunArtifacts.create(self.root)
        artifacts.write_provenance(ProvenanceRecord(job_id="j1"))
        with self.assertRaises(ModelStudioError) as caught:
            RunArtifacts.create(self.root)
        self.assertIn("already holds a run", str(caught.exception))
        self.assertIn("Nothing was written", str(caught.exception))

    def test_overwrite_is_allowed_when_asked_for(self) -> None:
        RunArtifacts.create(self.root).write_provenance(ProvenanceRecord(job_id="j1"))
        second = RunArtifacts.create(self.root, overwrite=True)
        second.write_provenance(ProvenanceRecord(job_id="j2"))
        document = json.loads((self.root / "provenance.json").read_text(encoding="utf-8"))
        self.assertEqual(document["job_id"], "j2")

    def test_an_empty_directory_is_not_a_run(self) -> None:
        self.root.mkdir(parents=True)
        RunArtifacts.create(self.root)  # must not raise

    def test_verify_catches_an_edited_file(self) -> None:
        artifacts = RunArtifacts.create(self.root)
        artifacts.write_provenance(ProvenanceRecord(job_id="j1"))
        artifacts.write_manifest()
        self.assertEqual(artifacts.verify(), [])

        (self.root / "provenance.json").write_text("{}", encoding="utf-8")
        problems = artifacts.verify()
        self.assertEqual(len(problems), 1)
        self.assertIn("provenance.json", problems[0])

    def test_verify_catches_a_missing_file(self) -> None:
        artifacts = RunArtifacts.create(self.root)
        artifacts.write_provenance(ProvenanceRecord(job_id="j1"))
        artifacts.write_manifest()
        (self.root / "provenance.json").unlink()
        self.assertIn("missing", artifacts.verify()[0])


class Digests(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)

    def test_a_directory_digest_covers_names_and_contents(self) -> None:
        first = self.root / "a"
        first.mkdir()
        (first / "weights.bin").write_bytes(b"abc")
        before = directory_digest(first)

        (first / "weights.bin").write_bytes(b"abd")
        self.assertNotEqual(directory_digest(first), before, "contents must matter")

        (first / "weights.bin").write_bytes(b"abc")
        self.assertEqual(directory_digest(first), before)

        (first / "weights.bin").rename(first / "renamed.bin")
        self.assertNotEqual(directory_digest(first), before, "names must matter")

    def test_a_file_digest_is_sha256(self) -> None:
        path = self.root / "x"
        path.write_bytes(b"")
        self.assertEqual(
            file_digest(path),
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
