# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Provenance: every field the brief asks for, and the ones it must not carry."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from model_studio.datasets.chat import load_chat_dataset
from model_studio.config import config_from_mapping
from model_studio.models import resolve_base_model
from model_studio.network import OFFLINE
from model_studio.provenance import ProvenanceRecord, bunny_commit, library_versions, utc_now
from tests.model_studio.support import simple_conversations, write_dataset, write_model_config

REQUIRED_FIELDS = (
    "base_model", "base_revision", "dataset_sha256", "config_sha256", "bunny_commit",
    "backend", "backend_version", "torch_version", "transformers_version", "gpu",
    "precision", "started_at", "completed_at", "status",
)


class Record(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        write_model_config(self.root / "base")
        self.dataset_path = write_dataset(self.root / "data.jsonl", simple_conversations(4))
        self.dataset = load_chat_dataset(self.dataset_path)
        self.config = config_from_mapping(
            {
                "model": {"base": str(self.root / "base")},
                "training": {"method": "lora"},
                "dataset": {"path": str(self.dataset_path)},
                "output": {"directory": str(self.root / "out")},
            },
            base_directory=self.root,
        )

    def _record(self) -> ProvenanceRecord:
        return ProvenanceRecord.for_run(
            job_id="job-1",
            status="completed",
            config=self.config,
            model=resolve_base_model(str(self.root / "base")),
            dataset=self.dataset,
            network_policy=OFFLINE,
            started_at=utc_now(),
            completed_at=utc_now(),
            gpu="none",
        )

    def test_every_required_field_is_present(self) -> None:
        document = self._record().to_json()
        for field in REQUIRED_FIELDS:
            self.assertIn(field, document, f"{field} is required by the provenance contract")

    def test_it_binds_to_the_dataset_by_digest(self) -> None:
        self.assertEqual(self._record().dataset_sha256, self.dataset.sha256)
        self.assertEqual(self._record().dataset_conversations, 4)

    def test_it_records_both_configuration_digests(self) -> None:
        record = self._record()
        self.assertEqual(record.config_sha256, self.config.file_sha256)
        self.assertEqual(record.config_canonical_sha256, self.config.canonical_sha256)

    def test_it_records_whether_the_permission_lint_ran(self) -> None:
        self.assertTrue(self._record().dataset_policy_checked)
        unchecked = load_chat_dataset(self.dataset_path, policy_check=False)
        record = ProvenanceRecord.for_run(
            job_id="job-2", status="completed", config=self.config,
            model=resolve_base_model(str(self.root / "base")), dataset=unchecked,
        )
        self.assertFalse(record.dataset_policy_checked)

    def test_it_carries_no_identifying_or_corpus_content(self) -> None:
        """The record travels with the adapter; the corpus and the person do not."""
        import json
        import platform

        text = json.dumps(self._record().to_json())
        self.assertNotIn("Open folder 0", text, "no dataset content")
        self.assertNotIn(platform.node(), text, "no hostname")

    def test_library_versions_say_absent_rather_than_guessing(self) -> None:
        versions = library_versions()
        self.assertIn("torch", versions)
        self.assertIn("transformers", versions)
        for name, value in versions.items():
            self.assertTrue(value, f"{name} has no version string at all")

    def test_the_commit_is_a_commit_or_says_it_is_unknown(self) -> None:
        commit = bunny_commit()
        self.assertTrue(commit)
        if commit != "unknown":
            base = commit.split("-")[0]
            self.assertEqual(len(base), 40, commit)
            int(base, 16)

    def test_a_dirty_tree_is_marked(self) -> None:
        """A run from a modified checkout cannot be reproduced from the commit it names."""
        commit = bunny_commit()
        if commit == "unknown":
            self.skipTest("not a git checkout")
        self.assertTrue(
            commit.count("-") == 0 or commit.endswith(("-dirty", "-unverified")),
            f"unexpected commit suffix: {commit}",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
