# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The developer surface, including the exit codes CI will branch on.

1 and 2 are distinct on purpose: "your configuration is wrong" and "this machine
cannot do it" lead to different actions, and a single non-zero code would leave
a CI job unable to tell a broken branch from a runner with no GPU.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from model_studio.cli import EXIT_INPUT, EXIT_MACHINE, EXIT_OK, main
from tests.model_studio.support import simple_conversations, write_dataset, write_model_config

MINIMAL_YAML = """
model:
  base: {base}
training:
  method: lora
  batch_size: 1
dataset:
  path: {dataset}
output:
  directory: {output}
"""


def _run(*argv: str) -> tuple[int, str]:
    stream = io.StringIO()
    with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(io.StringIO()):
        code = main(list(argv))
    return code, stream.getvalue()


class Commands(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        write_model_config(self.root / "base")
        dataset = write_dataset(self.root / "data.jsonl", simple_conversations(8))
        self.config = self.root / "run.yaml"
        self.config.write_text(
            MINIMAL_YAML.format(
                base=(self.root / "base").as_posix(),
                dataset=dataset.as_posix(),
                output=(self.root / "out").as_posix(),
            ),
            encoding="utf-8",
        )

    def test_hardware_always_answers(self) -> None:
        code, output = _run("hardware")
        self.assertEqual(code, EXIT_OK)
        self.assertIn("Hardware", output)
        self.assertIn("Recommended mode", output)

    def test_hardware_as_json(self) -> None:
        code, output = _run("--json", "hardware")
        self.assertEqual(code, EXIT_OK)
        document = json.loads(output)
        for key in ("hardware", "precision", "backend", "recommendedMethod"):
            self.assertIn(key, document)
        self.assertIn("accelerator", document["hardware"])

    def test_backends_lists_what_this_build_has(self) -> None:
        code, output = _run("--json", "backends")
        self.assertEqual(code, EXIT_OK)
        identifiers = [item["backendId"] for item in json.loads(output)["backends"]]
        self.assertIn("transformers-lora", identifiers)

    def test_validate_accepts_a_good_configuration(self) -> None:
        code, output = _run("validate", str(self.config))
        self.assertEqual(code, EXIT_OK)
        self.assertIn("VALID", output)

    def test_validate_rejects_a_bad_one_with_exit_one(self) -> None:
        bad = self.root / "bad.yaml"
        bad.write_text("model:\n  base: x\n", encoding="utf-8")
        code, _ = _run("validate", str(bad))
        self.assertEqual(code, EXIT_INPUT)

    def test_validate_rejects_a_bad_dataset_with_exit_one(self) -> None:
        (self.root / "data.jsonl").write_text("not json\n", encoding="utf-8")
        code, _ = _run("validate", str(self.config))
        self.assertEqual(code, EXIT_INPUT)

    def test_preflight_reports_and_exits_two_when_the_machine_cannot(self) -> None:
        code, output = _run("preflight", str(self.config))
        self.assertIn("STATUS:", output)
        self.assertIn("Training plan", output)
        self.assertIn(code, (EXIT_OK, EXIT_MACHINE))
        if code == EXIT_MACHINE:
            self.assertTrue("BLOCKED" in output or "UNKNOWN" in output)

    def test_preflight_json_carries_the_whole_report(self) -> None:
        code, output = _run("--json", "preflight", str(self.config))
        document = json.loads(output)
        for key in ("status", "backend", "hardware", "model", "precision", "blocking"):
            self.assertIn(key, document)
        self.assertIn(code, (EXIT_OK, EXIT_MACHINE))

    def test_view_produces_the_screen(self) -> None:
        code, output = _run("--json", "view", str(self.config))
        document = json.loads(output)
        self.assertEqual(document["title"], "Bunny Model Studio")
        self.assertIn("start", document)
        self.assertIn("methods", document)
        self.assertIn(code, (EXIT_OK, EXIT_MACHINE))

    def test_jobs_is_empty_before_anything_runs(self) -> None:
        code, output = _run("--json", "--jobs-root", str(self.root / "jobs"), "jobs")
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(json.loads(output)["jobs"], [])

    def test_inspecting_an_unknown_job_exits_one(self) -> None:
        code, _ = _run("--jobs-root", str(self.root / "jobs"), "inspect", "nothing")
        self.assertEqual(code, EXIT_INPUT)

    def test_verify_on_a_directory_with_no_manifest_exits_two(self) -> None:
        empty = self.root / "empty"
        empty.mkdir()
        code, output = _run("verify", str(empty))
        self.assertEqual(code, EXIT_MACHINE)
        self.assertIn("MANIFEST", output)

    def test_verify_accepts_a_written_run(self) -> None:
        from model_studio.artifacts import RunArtifacts
        from model_studio.provenance import ProvenanceRecord

        directory = self.root / "run"
        artifacts = RunArtifacts.create(directory)
        artifacts.write_provenance(ProvenanceRecord(job_id="j1"))
        artifacts.write_manifest()
        code, output = _run("verify", str(directory))
        self.assertEqual(code, EXIT_OK)
        self.assertIn("matches MANIFEST.json", output)

    def test_a_missing_configuration_file_exits_one(self) -> None:
        code, _ = _run("validate", str(self.root / "nowhere.yaml"))
        self.assertEqual(code, EXIT_INPUT)

    def test_train_refuses_a_configuration_it_cannot_read(self) -> None:
        code, _ = _run("train", str(self.root / "nowhere.yaml"))
        self.assertEqual(code, EXIT_INPUT)


class DownloadApproval(unittest.TestCase):
    def test_the_flag_exists_and_defaults_to_off(self) -> None:
        from model_studio.cli import parser

        arguments = parser().parse_args(["train", "x.yaml"])
        self.assertFalse(arguments.allow_model_download)
        approved = parser().parse_args(["train", "x.yaml", "--allow-model-download"])
        self.assertTrue(approved.allow_model_download)

    def test_there_is_no_upload_command(self) -> None:
        """A command that does not exist is the strongest form of "we do not do that"."""
        from model_studio.cli import parser

        choices = parser()._subparsers._group_actions[0].choices  # noqa: SLF001
        for name in ("push", "publish", "upload", "share"):
            self.assertNotIn(name, choices)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
