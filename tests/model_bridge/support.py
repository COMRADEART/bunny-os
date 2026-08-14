# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Artifacts and backends built to order, so each test states its own world.

The artifact builder writes a *real* directory with a real adapter file and a
real digest, because most of what is being tested here is the relationship
between a manifest and bytes on disk — and a fixture that faked the digest
would be testing the fixture.

The fake backend is where the fake is. Applying an adapter needs a model server
and none of the ordinary tests should need one, so :class:`FakeBackend` answers
the three questions the registry asks and records what it was asked. It can be
told to be unavailable, to refuse, or — the case worth having — to accept a
request and then report a state that does not match, which is how a backend
that says 200 and does nothing is distinguished from one that worked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from companion.models import MANIFEST_FILE_NAME
from companion.models.inference import (
    ADAPTER_NOT_PRELOADED,
    APPLIED,
    APPLY_REFUSED,
    BACKEND_UNAVAILABLE,
    RELEASED,
    VERIFY_FAILED,
    AdapterApplication,
    BackendStatus,
)

__all__ = ["FakeBackend", "artifact", "manifest_document", "write_artifact"]

#: A base identity used by most tests. Matching the one the real evidence run
#: uses keeps the two describing the same thing.
BASE_REFERENCE = "HuggingFaceTB/SmolLM2-135M-Instruct"
BASE_REVISION = "12fd25f77366fa6b3b4b768ec3050bf629380bac"


def manifest_document(
    model_id: str = "bunny-demo",
    *,
    adapter_file: str = "adapter.gguf",
    adapter_sha256: str = "",
    adapter_bytes: int = 0,
    adapter_format: str = "gguf",
    adapter_type: str = "lora",
    schema_version: int = 1,
    base_reference: str = BASE_REFERENCE,
    base_revision: str = BASE_REVISION,
    intended_runtime: str = "companion",
    network_required: bool = False,
    permissions: Sequence[str] = (),
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schemaVersion": schema_version,
        "modelId": model_id,
        "adapterType": adapter_type,
        "adapterFormat": adapter_format,
        "adapterFile": adapter_file,
        "adapterSha256": adapter_sha256,
        "baseModel": {"reference": base_reference},
        "training": {
            "createdBy": "bunny-model-studio",
            "createdAt": "2026-08-14T04:02:03Z",
            "jobId": "20260814T034732Z-e3ce8283",
            "datasetSha256": "f466ea25228a88822059e4acfaa9475c1bdf168fe02711e382450953e0cc531e",
            "bunnyCommit": "dbe5f371372d9e8d44c4a2afd0e51a824d259f67",
            "method": "lora",
        },
        "intendedRuntime": intended_runtime,
        "networkRequired": network_required,
        "permissions": list(permissions),
    }
    if base_revision:
        document["baseModel"]["revision"] = base_revision
    if adapter_bytes:
        document["adapterBytes"] = adapter_bytes
    if extra:
        document.update(extra)
    return document


def write_artifact(
    root: Path,
    model_id: str = "bunny-demo",
    *,
    adapter_content: bytes = b"GGUF\x00fake-lora-tensors",
    adapter_file: str = "adapter.gguf",
    corrupt_digest: bool = False,
    omit_adapter: bool = False,
    **manifest_keywords: Any,
) -> Path:
    """Write a real artifact directory and return it."""
    directory = Path(root) / model_id
    directory.mkdir(parents=True, exist_ok=True)
    if not omit_adapter:
        (directory / adapter_file).write_bytes(adapter_content)
    digest = hashlib.sha256(adapter_content).hexdigest()
    if corrupt_digest:
        digest = "0" * 64
    document = manifest_document(
        model_id,
        adapter_file=adapter_file,
        adapter_sha256=digest,
        adapter_bytes=len(adapter_content),
        **manifest_keywords,
    )
    (directory / MANIFEST_FILE_NAME).write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    return directory


def artifact(root: Path, model_id: str = "bunny-demo", **keywords: Any) -> Path:
    return write_artifact(root, model_id, **keywords)


@dataclass
class FakeBackend:
    """A backend that answers without a model server, and records what it was asked."""

    backend_id: str = "fake"
    available: bool = True
    formats: tuple[str, ...] = ("gguf",)
    #: Accept the request but report a state that does not match it. This is
    #: the case that separates "the server said 200" from "the adapter is on".
    lies_about_state: bool = False
    refuses: bool = False
    knows_adapter: bool = True
    applied: list[str] = field(default_factory=list)
    released: list[str] = field(default_factory=list)

    def describe(self) -> BackendStatus:
        return BackendStatus(
            backend_id=self.backend_id,
            available=self.available,
            detail="a fake backend" if self.available else "not available in this test",
            supported_formats=self.formats if self.available else (),
            endpoint="test",
        )

    def apply(self, model_id: str, adapter_path: Path, *, scale: float = 1.0) -> AdapterApplication:
        if not self.available:
            return AdapterApplication(self.backend_id, model_id, False, False,
                                      BACKEND_UNAVAILABLE, "not available in this test")
        if not self.knows_adapter:
            return AdapterApplication(self.backend_id, model_id, False, False,
                                      ADAPTER_NOT_PRELOADED,
                                      "this backend was not started with that adapter")
        if self.refuses:
            return AdapterApplication(self.backend_id, model_id, False, False,
                                      APPLY_REFUSED, "the backend refused")
        self.applied.append(model_id)
        if self.lies_about_state:
            return AdapterApplication(self.backend_id, model_id, True, False, VERIFY_FAILED,
                                      "accepted the request and reports scale 0.0",
                                      scale=0.0, adapter_path=str(adapter_path))
        return AdapterApplication(self.backend_id, model_id, True, True, APPLIED,
                                  "applied and confirmed", scale=scale,
                                  adapter_path=str(adapter_path))

    def release(self, model_id: str) -> AdapterApplication:
        self.released.append(model_id)
        if not self.available:
            return AdapterApplication(self.backend_id, model_id, False, False,
                                      BACKEND_UNAVAILABLE, "not available in this test")
        return AdapterApplication(self.backend_id, model_id, False, True, RELEASED,
                                  "nothing is in effect")
