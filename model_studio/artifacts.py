# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The output directory: one shape, written by one thing.

    <output.directory>/
      adapter/
        adapter_config.json
        adapter_model.safetensors
      config.snapshot.json      the resolved run, not the document
      preflight.json            what was checked, and on what
      training-metadata.json    the plan, and what the run measured
      training-log.jsonl        one line per step
      evaluation.json           reload, tensor delta, held-out loss
      provenance.json           base + dataset + recipe + versions
      MANIFEST.json             every file above, with its sha256

The manifest is what turns a directory into an artifact. Without it, "this is
the adapter I trained on Tuesday" is a claim about a folder somebody may have
edited; with it, every file's digest is recorded at the moment it was written
and the whole set can be checked in one pass. It is written last, and it covers
itself by omission — a manifest cannot contain its own digest, so it names
everything else and the caller checks it against what is there.

Overwriting is refused unless the configuration asked for it. A training run
that silently replaced a previous one's adapter and provenance would leave a
directory whose ``MANIFEST.json`` describes weights that no longer exist,
and the person who lost the earlier run would find out from the digest mismatch.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any, Iterable, Mapping

from . import STUDIO_NAME, STUDIO_SCHEMA_VERSION
from .errors import ModelStudioError

__all__ = ["ADAPTER_DIRECTORY", "RunArtifacts", "directory_digest", "file_digest"]

ADAPTER_DIRECTORY = "adapter"

CONFIG_SNAPSHOT = "config.snapshot.json"
PREFLIGHT = "preflight.json"
METADATA = "training-metadata.json"
LOG = "training-log.jsonl"
EVALUATION = "evaluation.json"
PROVENANCE = "provenance.json"
MANIFEST = "MANIFEST.json"

#: Files a run may leave behind besides the adapter. Named, so the manifest
#: writer does not have to guess whether a stray file belongs to the run.
_KNOWN = (CONFIG_SNAPSHOT, PREFLIGHT, METADATA, LOG, EVALUATION, PROVENANCE)


def file_digest(path: Path | str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def directory_digest(directory: Path | str) -> str:
    """A digest over a directory's files: names and contents, order-independent.

    Used for the adapter, so that ``adapter_sha256`` in provenance means "these
    weights" rather than "a file called adapter_model.safetensors".
    """
    root = Path(directory)
    combined = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        combined.update(path.relative_to(root).as_posix().encode("utf-8"))
        combined.update(b"\0")
        combined.update(bytes.fromhex(file_digest(path)))
    return combined.hexdigest()


@dataclass
class RunArtifacts:
    """The output directory of one run, and the only thing that writes into it."""

    directory: Path

    @classmethod
    def create(cls, directory: Path | str, *, overwrite: bool = False) -> "RunArtifacts":
        target = Path(directory)
        if target.exists():
            occupied = [name for name in _KNOWN if (target / name).exists()]
            adapter = target / ADAPTER_DIRECTORY
            if adapter.exists():
                occupied.append(ADAPTER_DIRECTORY)
            if occupied and not overwrite:
                raise ModelStudioError(
                    f"{target} already holds a run ({', '.join(sorted(occupied))}). "
                    "Set output.overwrite: true to replace it, or choose another directory. "
                    "Nothing was written."
                )
        target.mkdir(parents=True, exist_ok=True)
        return cls(directory=target)

    # -- paths -------------------------------------------------------------- #

    @property
    def adapter_directory(self) -> Path:
        return self.directory / ADAPTER_DIRECTORY

    @property
    def log_path(self) -> Path:
        return self.directory / LOG

    # -- writing ------------------------------------------------------------ #

    def _write_json(self, name: str, document: Any) -> Path:
        target = self.directory / name
        payload = json.dumps(document, indent=2, sort_keys=True) + "\n"
        temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        temporary.write_text(payload, encoding="utf-8")
        for attempt in range(5):
            try:
                os.replace(temporary, target)
                break
            except PermissionError:  # pragma: no cover - Windows sharing
                if attempt == 4:
                    temporary.unlink(missing_ok=True)
                    raise
                time.sleep(0.05 * (attempt + 1))
        return target

    def write_config(self, config: Any) -> Path:
        return self._write_json(CONFIG_SNAPSHOT, {
            "resolved": config.to_json(),
            "sourcePath": getattr(config, "source_path", ""),
            "loader": getattr(config, "loader", ""),
            "fileSha256": getattr(config, "file_sha256", ""),
            "canonicalSha256": getattr(config, "canonical_sha256", ""),
        })

    def write_preflight(self, report: Any) -> Path:
        return self._write_json(PREFLIGHT, report.to_json())

    def write_metadata(self, *, plan: Any, result: Any, job_id: str) -> Path:
        return self._write_json(METADATA, {
            "jobId": job_id,
            "plan": plan.to_json() if plan is not None else None,
            "result": result.to_json() if result is not None else None,
        })

    def write_evaluation(self, evaluation: Any) -> Path:
        return self._write_json(EVALUATION, evaluation.to_json())

    def write_provenance(self, provenance: Any) -> Path:
        return self._write_json(PROVENANCE, provenance.to_json())

    def append_log(self, event: Mapping[str, Any]) -> None:
        """One JSON object per line, flushed. A log that buffers loses the crash.

        The reason to flush every line is the case the log is most needed for:
        a run that was killed. A buffered writer's last block is exactly the part
        that says what it was doing when it stopped.
        """
        with open(self.log_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def write_manifest(self, *, extra: Iterable[str] = ()) -> Path:
        """Digest every file in the run, last. Does not cover itself."""
        entries: dict[str, dict[str, Any]] = {}
        for path in sorted(p for p in self.directory.rglob("*") if p.is_file()):
            relative = path.relative_to(self.directory).as_posix()
            if relative == MANIFEST or relative.startswith("."):
                continue
            entries[relative] = {
                "sha256": file_digest(path),
                "bytes": path.stat().st_size,
            }
        return self._write_json(MANIFEST, {
            "studio": STUDIO_NAME,
            "schemaVersion": STUDIO_SCHEMA_VERSION,
            "files": entries,
            "adapterSha256": (
                directory_digest(self.adapter_directory)
                if self.adapter_directory.is_dir() else ""
            ),
            "extra": sorted(extra),
        })

    # -- reading ------------------------------------------------------------ #

    def verify(self) -> list[str]:
        """Every file whose bytes no longer match the manifest. Empty is good."""
        manifest_path = self.directory / MANIFEST
        try:
            document = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return [f"{MANIFEST}: {exc}"]
        problems: list[str] = []
        for name, entry in sorted((document.get("files") or {}).items()):
            path = self.directory / name
            if not path.is_file():
                problems.append(f"{name}: missing")
                continue
            actual = file_digest(path)
            if actual != entry.get("sha256"):
                problems.append(f"{name}: sha256 {actual[:12]} != recorded {str(entry.get('sha256'))[:12]}")
        return problems
