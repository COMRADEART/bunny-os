# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Where a Bunny model came from, in a form a machine can check.

A fine-tuned adapter is a few megabytes of floating-point numbers. Nothing in it
says which model it modifies, which conversations produced it, or which version
of which library did the producing — and six months later, when it behaves
oddly, those are the only three questions worth asking. So every run writes this
record beside its weights, and the rule is that a Bunny model is traceable to:

    base model + dataset + training recipe + software versions

Digests rather than paths wherever the content is what matters. ``/home/me/
data.jsonl`` names a file that has since been edited; ``dataset_sha256`` names
the bytes that were trained on and can be checked against the file that is there
now. The same for the configuration, which is recorded twice — the digest of the
document, and the digest of the *resolved* run — because reformatting a YAML file
changes the first and must not change the second.

``bunny_commit`` carries a ``-dirty`` suffix when the working tree had
uncommitted changes. That is not tidiness: a run from a modified checkout cannot
be reproduced from the commit it names, and a record that omits the distinction
asserts something false about the most important field it has.

What is deliberately *not* here: the machine's hostname, the user's name, the
dataset's contents, and any sample of them. The record travels with the adapter,
the adapter may be shared, and none of those four are needed to reproduce a run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
import importlib
import os
from pathlib import Path
import platform
import subprocess
from typing import Any

from . import STUDIO_NAME, STUDIO_SCHEMA_VERSION

__all__ = ["ProvenanceRecord", "bunny_commit", "library_versions", "utc_now"]

#: The libraries whose version changes a training result. Recorded whether or
#: not the active backend used them, because "transformers was not installed"
#: is itself a fact about the environment that produced the adapter.
_TRACKED_LIBRARIES = ("torch", "transformers", "peft", "safetensors", "tokenizers", "bitsandbytes",
                      "accelerate", "numpy")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def library_versions() -> dict[str, str]:
    """Version of every tracked library, or ``"absent"``. Never a guess."""
    versions: dict[str, str] = {}
    for name in _TRACKED_LIBRARIES:
        try:
            module = importlib.import_module(name)
        except Exception:  # noqa: BLE001 - a broken install is "absent" for this purpose
            versions[name] = "absent"
            continue
        versions[name] = str(getattr(module, "__version__", "unknown"))
    return versions


@lru_cache(maxsize=8)
def _commit_of(root: str) -> str:
    """The expensive half of :func:`bunny_commit`, computed once per process.

    ``git status --porcelain`` costs 8.6 seconds on this repository — it stats
    every one of several thousand tracked files, and the qualification evidence
    trees are most of them. Provenance asked for it once per record, which made
    a test suite that writes twenty records take three minutes and a single
    training run pay for it twice.

    Caching is not only a speed fix. Two provenance records written by one
    process describe one checkout, so recomputing invites them to disagree —
    and a pair of records from the same run naming different commits is a worse
    outcome than either number being slightly stale.
    """
    environment = {**os.environ, "LC_ALL": "C", "GIT_OPTIONAL_LOCKS": "0"}
    try:
        head = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=15, check=False, env=environment,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    if head.returncode != 0:
        return "unknown"
    commit = head.stdout.strip()
    if not commit:
        return "unknown"
    try:
        status = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            capture_output=True, text=True, timeout=30, check=False, env=environment,
        )
    except (OSError, subprocess.SubprocessError):
        return f"{commit}-unverified"
    if status.returncode != 0:
        return f"{commit}-unverified"
    return f"{commit}-dirty" if status.stdout.strip() else commit


def bunny_commit(repository: Path | str | None = None) -> str:
    """The commit this code is, with ``-dirty`` when the tree does not match it.

    ``-dirty`` is not tidiness: a run from a modified checkout cannot be
    reproduced from the commit it names, and a record that omits the
    distinction asserts something false about its most important field.
    ``-unverified`` means the commit was read but the tree state could not be,
    and ``unknown`` means neither could — both of which happen, and neither of
    which is allowed to look like a clean commit.
    """
    root = Path(repository) if repository else Path(__file__).resolve().parent.parent
    return _commit_of(str(root))


@dataclass(frozen=True)
class ProvenanceRecord:
    """One run, described well enough to be argued with."""

    job_id: str = ""
    status: str = ""
    base_model: str = ""
    base_revision: str = ""
    base_model_path: str = ""
    dataset_sha256: str = ""
    dataset_conversations: int = 0
    dataset_policy_checked: bool = False
    config_sha256: str = ""
    config_canonical_sha256: str = ""
    bunny_commit: str = ""
    backend: str = ""
    backend_version: str = ""
    method: str = ""
    precision: str = ""
    device: str = ""
    gpu: str = ""
    started_at: str = ""
    completed_at: str = ""
    steps: int = 0
    final_loss: float | None = None
    trainable_parameters: int = 0
    total_parameters: int = 0
    adapter_sha256: str = ""
    network_policy: dict[str, Any] = field(default_factory=dict)
    libraries: dict[str, str] = field(default_factory=dict)
    platform_name: str = ""
    python_version: str = ""
    studio: str = STUDIO_NAME
    schema_version: int = STUDIO_SCHEMA_VERSION

    def to_json(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "studio": self.studio,
            "job_id": self.job_id,
            "status": self.status,
            "base_model": self.base_model,
            "base_revision": self.base_revision,
            "base_model_path": self.base_model_path,
            "dataset_sha256": self.dataset_sha256,
            "dataset_conversations": self.dataset_conversations,
            "dataset_policy_checked": self.dataset_policy_checked,
            "config_sha256": self.config_sha256,
            "config_canonical_sha256": self.config_canonical_sha256,
            "bunny_commit": self.bunny_commit,
            "backend": self.backend,
            "backend_version": self.backend_version,
            "method": self.method,
            "precision": self.precision,
            "device": self.device,
            "gpu": self.gpu,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "steps": self.steps,
            "final_loss": self.final_loss,
            "trainable_parameters": self.trainable_parameters,
            "total_parameters": self.total_parameters,
            "adapter_sha256": self.adapter_sha256,
            "network_policy": dict(self.network_policy),
            "torch_version": self.libraries.get("torch", "absent"),
            "transformers_version": self.libraries.get("transformers", "absent"),
            "peft_version": self.libraries.get("peft", "absent"),
            "libraries": dict(self.libraries),
            "platform": self.platform_name,
            "python_version": self.python_version,
        }

    @classmethod
    def for_run(
        cls,
        *,
        job_id: str,
        status: str,
        config: Any,
        model: Any,
        plan: Any = None,
        result: Any = None,
        dataset: Any = None,
        network_policy: Any = None,
        started_at: str = "",
        completed_at: str = "",
        adapter_sha256: str = "",
        gpu: str = "",
    ) -> "ProvenanceRecord":
        """Assemble a record from the objects a run already has.

        Every field comes from something that was measured or resolved. Nothing
        here reaches for a default: a run with no result carries zeros and an
        empty completion time, and that is the honest description of a run that
        did not finish.
        """
        return cls(
            job_id=job_id,
            status=status,
            base_model=getattr(model, "reference", ""),
            base_revision=getattr(model, "resolved_revision", "")
            or getattr(model, "requested_revision", ""),
            base_model_path=getattr(model, "path", ""),
            dataset_sha256=getattr(dataset, "sha256", "") if dataset is not None else "",
            dataset_conversations=len(dataset) if dataset is not None else 0,
            dataset_policy_checked=(
                bool(getattr(getattr(dataset, "policy", None), "ran", False))
                if dataset is not None else False
            ),
            config_sha256=getattr(config, "file_sha256", ""),
            config_canonical_sha256=getattr(config, "canonical_sha256", ""),
            bunny_commit=bunny_commit(),
            backend=getattr(plan, "backend_id", "") if plan is not None else "",
            backend_version=library_versions().get("peft", "absent"),
            method=getattr(plan, "method", "") if plan is not None else getattr(
                config, "effective_method", ""
            ),
            precision=getattr(result, "precision", "") if result is not None else (
                getattr(getattr(plan, "precision", None), "dtype", "") if plan is not None else ""
            ),
            device=getattr(result, "device", "") if result is not None else "",
            gpu=gpu,
            started_at=started_at,
            completed_at=completed_at,
            steps=getattr(result, "steps", 0) if result is not None else 0,
            final_loss=getattr(result, "final_loss", None) if result is not None else None,
            trainable_parameters=getattr(result, "trainable_parameters", 0) if result is not None else 0,
            total_parameters=getattr(result, "total_parameters", 0) if result is not None else 0,
            adapter_sha256=adapter_sha256,
            network_policy=network_policy.to_json() if network_policy is not None else {},
            libraries=library_versions(),
            platform_name=platform.platform(),
            python_version=platform.python_version(),
        )
