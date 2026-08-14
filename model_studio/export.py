# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Turning a finished training run into something the Bunny runtime may read.

This is the *outbound* half of the trust boundary and it lives on the training
side, off-image, with the rest of Model Studio. Export is an explicit act: a
completed run does not become a runtime artifact by existing, and nothing here
installs, enables or activates anything. It writes a directory.

**This module does not import the runtime.** It writes a manifest against the
published contract, ``schemas/bunny-model-artifact.schema.json``, and
:mod:`companion.models.artifact` reads against the same one. That is a
deliberate duplication of a *shape*, not of logic: the alternative is the
training tool importing the runtime's parser, which couples what trains to what
runs and puts a runtime package on the import path of every training host.
``tests/model_bridge/test_contract_round_trip.py`` exports and then parses with
the runtime, so the two cannot drift apart quietly.

**Conversion is here, not there.** A PEFT adapter is safetensors; llama.cpp
applies GGUF. Something has to convert, and that something needs llama.cpp's
own converter and the ``gguf`` Python package — a development dependency that
has no business in a Bunny image. So the conversion runs on this side, before
the boundary, and the runtime only ever sees the result. The converter is named
by the caller: there is no search, no download, and no guess about which
llama.cpp somebody meant.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

from . import STUDIO_NAME
from .errors import ModelStudioError

__all__ = [
    "ARTIFACT_SCHEMA_VERSION",
    "MANIFEST_FILE_NAME",
    "ExportResult",
    "convert_lora_to_gguf",
    "export_artifact",
]

#: Kept in step with ``companion.models.ARTIFACT_SCHEMA_VERSION`` and the
#: published schema. The round-trip test fails if they disagree.
ARTIFACT_SCHEMA_VERSION = 1
MANIFEST_FILE_NAME = "bunny-model-manifest.json"

_READ_BLOCK = 1024 * 1024
_CONVERT_TIMEOUT_SECONDS = 900


@dataclass(frozen=True)
class ExportResult:
    """What export produced, and where."""

    model_id: str
    directory: str
    adapter_file: str
    adapter_format: str
    adapter_sha256: str
    adapter_bytes: int
    manifest_path: str

    def to_json(self) -> dict[str, Any]:
        return {
            "modelId": self.model_id,
            "directory": self.directory,
            "adapterFile": self.adapter_file,
            "adapterFormat": self.adapter_format,
            "adapterSha256": self.adapter_sha256,
            "adapterBytes": self.adapter_bytes,
            "manifestPath": self.manifest_path,
        }


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(_READ_BLOCK), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ModelStudioError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ModelStudioError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise ModelStudioError(f"{path} is not a JSON object")
    return document


def convert_lora_to_gguf(
    adapter_directory: Path | str,
    *,
    converter: Path | str,
    base_model: Path | str,
    output: Path | str,
    python: str = "",
) -> Path:
    """Run llama.cpp's ``convert_lora_to_gguf.py`` on a PEFT adapter.

    ``converter`` is a path the caller supplies. Nothing is searched for and
    nothing is fetched: a conversion tool found by guessing is a program nobody
    reviewed, and this one runs with the user's privileges over the user's
    adapter.
    """
    script = Path(converter)
    if not script.is_file():
        raise ModelStudioError(
            f"the converter {script} is not a file. Point --converter at llama.cpp's "
            "convert_lora_to_gguf.py; Model Studio does not download it."
        )
    source = Path(adapter_directory)
    if not (source / "adapter_config.json").is_file():
        raise ModelStudioError(f"{source} does not look like a PEFT adapter directory")
    base = Path(base_model)
    if not base.is_dir():
        raise ModelStudioError(
            f"the base model directory {base} does not exist; conversion reads the "
            "base model's configuration to size the adapter's tensors"
        )
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)

    argv = [
        python or sys.executable,
        str(script),
        str(source),
        "--base", str(base),
        "--outfile", str(destination),
        "--outtype", "f16",
    ]
    completed = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=_CONVERT_TIMEOUT_SECONDS,
        check=False,
        env={**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"},
    )
    if completed.returncode != 0 or not destination.is_file():
        tail = (completed.stderr or completed.stdout or "").strip().splitlines()[-8:]
        raise ModelStudioError(
            f"conversion failed ({completed.returncode}):\n  " + "\n  ".join(tail)
        )
    return destination


def export_artifact(
    run_directory: Path | str,
    *,
    into: Path | str,
    model_id: str = "",
    adapter_format: str = "peft-safetensors",
    adapter_source: Path | str = "",
    base_model_file: str = "",
    base_model_sha256: str = "",
    display_name: str = "",
    notes: str = "",
    overwrite: bool = False,
) -> ExportResult:
    """Write a Bunny model artifact from a completed Model Studio run.

    Reads the run's own ``provenance.json`` and ``training-metadata.json`` — the
    records written by the previous milestone — and carries their digests
    forward. The manifest is provenance plus identity; it grants nothing, and
    :func:`export_artifact` refuses to write one that says otherwise.
    """
    run = Path(run_directory)
    provenance = _read_json(run / "provenance.json")
    if provenance.get("status") != "completed":
        raise ModelStudioError(
            f"{run} records status {provenance.get('status')!r}; only a completed run "
            "is exportable. A half-trained adapter is not a model."
        )

    metadata = _read_json(run / "training-metadata.json") if (run / "training-metadata.json").is_file() else {}
    plan = metadata.get("plan") or {}
    base_section = plan.get("baseModel") or {}

    identifier = (model_id or provenance.get("job_id", "") or run.name).strip().lower()
    identifier = "".join(character if character.isalnum() or character in "._-" else "-"
                         for character in identifier).strip("-._")
    if not identifier:
        raise ModelStudioError("could not derive a model id; pass model_id explicitly")

    if adapter_format not in ("gguf", "peft-safetensors"):
        raise ModelStudioError(f"unknown adapter format {adapter_format!r}")

    destination = Path(into) / identifier
    if destination.exists() and any(destination.iterdir()) and not overwrite:
        raise ModelStudioError(
            f"{destination} already holds an artifact. Pass overwrite=True to replace it; "
            "nothing was written."
        )
    destination.mkdir(parents=True, exist_ok=True)

    if adapter_format == "gguf":
        source = Path(adapter_source)
        if not source.is_file():
            raise ModelStudioError(
                "a gguf export needs adapter_source pointing at the converted .gguf file"
            )
        adapter_name = source.name
        shutil.copy2(source, destination / adapter_name)
    else:
        source_directory = Path(adapter_source) if adapter_source else run / "adapter"
        weights = source_directory / "adapter_model.safetensors"
        if not weights.is_file():
            raise ModelStudioError(f"no adapter_model.safetensors in {source_directory}")
        adapter_name = weights.name
        shutil.copy2(weights, destination / adapter_name)
        # The PEFT configuration travels with the weights: it is what any PEFT
        # reader needs, and the runtime does not read it.
        configuration = source_directory / "adapter_config.json"
        if configuration.is_file():
            shutil.copy2(configuration, destination / configuration.name)

    adapter_path = destination / adapter_name
    adapter_digest = _digest(adapter_path)
    adapter_bytes = adapter_path.stat().st_size

    manifest: dict[str, Any] = {
        "schemaVersion": ARTIFACT_SCHEMA_VERSION,
        "modelId": identifier,
        "adapterType": "lora",
        "adapterFormat": adapter_format,
        "adapterFile": adapter_name,
        "adapterSha256": adapter_digest,
        "adapterBytes": adapter_bytes,
        "baseModel": {
            "reference": str(provenance.get("base_model", "") or base_section.get("reference", "")),
        },
        "training": {
            "createdBy": str(provenance.get("studio", STUDIO_NAME)),
            "createdAt": str(provenance.get("completed_at", "")),
            "jobId": str(provenance.get("job_id", "")),
            "configSha256": str(provenance.get("config_sha256", "")),
            "configCanonicalSha256": str(provenance.get("config_canonical_sha256", "")),
            "datasetSha256": str(provenance.get("dataset_sha256", "")),
            "datasetConversations": int(provenance.get("dataset_conversations", 0) or 0),
            "bunnyCommit": str(provenance.get("bunny_commit", "")),
            "method": str(provenance.get("method", "")),
            "precision": str(provenance.get("precision", "")),
            "steps": int(provenance.get("steps", 0) or 0),
            "finalLoss": provenance.get("final_loss"),
        },
        "intendedRuntime": "companion",
        "networkRequired": False,
        # Always empty, and there is no argument that sets it. An artifact
        # cannot carry a capability; the runtime refuses one that tries.
        "permissions": [],
    }

    revision = str(provenance.get("base_revision", "") or base_section.get("revision", ""))
    if revision:
        manifest["baseModel"]["revision"] = revision
    if base_model_file:
        manifest["baseModel"]["file"] = base_model_file
    if base_model_sha256:
        manifest["baseModel"]["sha256"] = base_model_sha256
    architecture = plan.get("lora", {}).get("targetModulesSource", "")
    if isinstance(architecture, str) and "decoder" in architecture:
        manifest["baseModel"]["architecture"] = architecture.split()[-2] if len(architecture.split()) > 1 else ""
    if not manifest["baseModel"].get("architecture"):
        manifest["baseModel"].pop("architecture", None)
    total = plan.get("estimatedTotalParameters")
    if isinstance(total, int) and total > 0:
        manifest["baseModel"]["parameterCount"] = total
    if display_name:
        manifest["displayName"] = display_name
    if notes:
        manifest["notes"] = notes
    manifest["training"] = {
        key: value for key, value in manifest["training"].items()
        if value not in ("", 0, None)
    }

    if not manifest["baseModel"]["reference"]:
        raise ModelStudioError(
            f"{run} records no base model; the manifest would name nothing to be "
            "compatible with"
        )

    manifest_path = destination / MANIFEST_FILE_NAME
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )

    return ExportResult(
        model_id=identifier,
        directory=str(destination),
        adapter_file=adapter_name,
        adapter_format=adapter_format,
        adapter_sha256=adapter_digest,
        adapter_bytes=adapter_bytes,
        manifest_path=str(manifest_path),
    )
