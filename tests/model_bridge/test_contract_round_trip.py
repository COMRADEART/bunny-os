# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The two sides of the boundary, checked against each other.

Model Studio writes a manifest without importing the runtime, and the runtime
reads it without importing Model Studio. That independence is the point — see
:mod:`model_studio.export` — and its cost is that the manifest's *shape* exists
in two places. This file is what stops them drifting: it exports with the real
exporter and parses with the real parser, so a field renamed on one side fails
here rather than on somebody's machine.

The published schema is the third party to the agreement, and it is checked too.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from companion.models import ARTIFACT_SCHEMA_VERSION
from companion.models.artifact import read_manifest
from companion.models.validation import PASS, RuntimeExpectations, validate_artifact
from model_studio.export import ARTIFACT_SCHEMA_VERSION as EXPORT_SCHEMA_VERSION
from model_studio.export import export_artifact

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "schemas" / "bunny-model-artifact.schema.json"

_PROVENANCE = {
    "schemaVersion": 1,
    "studio": "bunny-model-studio",
    "job_id": "20260814T034732Z-e3ce8283",
    "status": "completed",
    "base_model": "HuggingFaceTB/SmolLM2-135M-Instruct",
    "base_revision": "12fd25f77366fa6b3b4b768ec3050bf629380bac",
    "dataset_sha256": "f466ea25228a88822059e4acfaa9475c1bdf168fe02711e382450953e0cc531e",
    "dataset_conversations": 35,
    "config_sha256": "3d520660ca553bacac1e64f4088fc86acac51dee012f0db64d384e74fbef1df8",
    "config_canonical_sha256": "1318a0e91b888c7ebb3c66d135e0c8844546ccee7e032003350add0cd5b4b02f",
    "bunny_commit": "dbe5f371372d9e8d44c4a2afd0e51a824d259f67",
    "method": "lora",
    "precision": "bf16",
    "steps": 12,
    "final_loss": 3.4654674530029297,
    "completed_at": "2026-08-14T04:02:03Z",
}


class RoundTrip(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.base = Path(self.scratch.name)
        self.run = self.base / "run"
        (self.run / "adapter").mkdir(parents=True)
        (self.run / "provenance.json").write_text(json.dumps(_PROVENANCE), encoding="utf-8")
        (self.run / "adapter" / "adapter_model.safetensors").write_bytes(b"safetensors-bytes")
        (self.run / "adapter" / "adapter_config.json").write_text(
            json.dumps({"peft_type": "LORA", "r": 8}), encoding="utf-8"
        )
        self.gguf = self.base / "converted" / "bunny-demo-lora-f16.gguf"
        self.gguf.parent.mkdir(parents=True)
        self.gguf.write_bytes(b"GGUF\x00converted-lora")
        self.artifacts = self.base / "agent-models"

    def test_the_two_sides_agree_on_the_version(self) -> None:
        self.assertEqual(EXPORT_SCHEMA_VERSION, ARTIFACT_SCHEMA_VERSION)
        document = json.loads(SCHEMA.read_text(encoding="utf-8"))
        self.assertEqual(
            document["properties"]["schemaVersion"]["maximum"], ARTIFACT_SCHEMA_VERSION
        )

    def test_an_exported_artifact_parses_with_the_runtime_parser(self) -> None:
        result = export_artifact(
            self.run, into=self.artifacts, model_id="bunny-demo",
            adapter_format="gguf", adapter_source=self.gguf,
        )
        manifest = read_manifest(result.directory)
        self.assertEqual(manifest.model_id, "bunny-demo")
        self.assertEqual(manifest.adapter_format, "gguf")
        self.assertEqual(manifest.adapter_sha256, result.adapter_sha256)
        self.assertEqual(manifest.base_model.reference, _PROVENANCE["base_model"])
        self.assertEqual(manifest.base_model.revision, _PROVENANCE["base_revision"])
        self.assertEqual(manifest.training.dataset_sha256, _PROVENANCE["dataset_sha256"])
        self.assertEqual(manifest.training.bunny_commit, _PROVENANCE["bunny_commit"])
        self.assertEqual(manifest.permissions, ())

    def test_an_exported_artifact_validates(self) -> None:
        result = export_artifact(
            self.run, into=self.artifacts, model_id="bunny-demo",
            adapter_format="gguf", adapter_source=self.gguf,
        )
        report = validate_artifact(
            result.directory,
            expectations=RuntimeExpectations(
                base_model_reference=_PROVENANCE["base_model"],
                base_model_revision=_PROVENANCE["base_revision"],
                base_model_present=True,
                supported_formats=("gguf",),
                trusted_roots=(self.artifacts,),
                check_modes=False,
            ),
        )
        self.assertEqual(report.status, PASS, report.to_json())

    def test_every_field_the_exporter_writes_is_one_the_parser_knows(self) -> None:
        """A field added on one side and not the other fails here, loudly."""
        result = export_artifact(
            self.run, into=self.artifacts, model_id="bunny-demo",
            adapter_format="gguf", adapter_source=self.gguf,
        )
        written = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        declared = set(schema["properties"])
        self.assertEqual(set(written) - declared, set(),
                         "the exporter wrote a field the published schema does not declare")
        base_declared = set(schema["properties"]["baseModel"]["properties"])
        self.assertEqual(set(written["baseModel"]) - base_declared, set())
        training_declared = set(schema["properties"]["training"]["properties"])
        self.assertEqual(set(written.get("training", {})) - training_declared, set())

    def test_the_exporter_cannot_be_asked_to_grant_permissions(self) -> None:
        """There is no argument that fills the permissions array."""
        import inspect

        signature = inspect.signature(export_artifact)
        for name in signature.parameters:
            self.assertNotIn("permission", name.lower())
            self.assertNotIn("capabilit", name.lower())
        result = export_artifact(
            self.run, into=self.artifacts, model_id="bunny-demo",
            adapter_format="gguf", adapter_source=self.gguf,
        )
        written = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
        self.assertEqual(written["permissions"], [])
        self.assertIs(written["networkRequired"], False)

    def test_a_run_that_did_not_complete_is_not_exportable(self) -> None:
        (self.run / "provenance.json").write_text(
            json.dumps({**_PROVENANCE, "status": "failed"}), encoding="utf-8"
        )
        from model_studio.errors import ModelStudioError

        with self.assertRaises(ModelStudioError) as caught:
            export_artifact(self.run, into=self.artifacts, adapter_format="gguf",
                            adapter_source=self.gguf)
        self.assertIn("half-trained", str(caught.exception))

    def test_a_peft_export_is_well_formed_but_unusable_here(self) -> None:
        """Honest about what the image can and cannot apply."""
        result = export_artifact(
            self.run, into=self.artifacts, model_id="peft-demo",
            adapter_format="peft-safetensors",
        )
        manifest = read_manifest(result.directory)
        self.assertEqual(manifest.adapter_format, "peft-safetensors")
        report = validate_artifact(
            result.directory,
            expectations=RuntimeExpectations(
                base_model_reference=_PROVENANCE["base_model"],
                base_model_revision=_PROVENANCE["base_revision"],
                base_model_present=True, supported_formats=("gguf",),
                trusted_roots=(self.artifacts,), check_modes=False,
            ),
        )
        self.assertEqual(report.status, "UNKNOWN")
        self.assertEqual(report.code, "NO_BACKEND_FOR_FORMAT")

    def test_export_refuses_to_overwrite_silently(self) -> None:
        from model_studio.errors import ModelStudioError

        export_artifact(self.run, into=self.artifacts, model_id="bunny-demo",
                        adapter_format="gguf", adapter_source=self.gguf)
        with self.assertRaises(ModelStudioError):
            export_artifact(self.run, into=self.artifacts, model_id="bunny-demo",
                            adapter_format="gguf", adapter_source=self.gguf)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
