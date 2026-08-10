# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Getting a file in, and getting a result out, without either becoming a hole.

Two directions, and they are not symmetric.

**In** is a bind mount, planned by :mod:`capsules.isolation` and executed by the
backend. Nothing is copied. A capsule sees the user's file at
``/run/bunny/files/<digest>/<name>``, read-only unless the grant said ``write``.
The function here, :func:`describe_import`, exists only to say what the user is
being asked to hand over, in the same words the prompt used.

**Out** is a copy, and it is a copy for one reason: §15 requires the original to
survive. A capsule that could write its result over its input would make "the
original file wasn't modified" a claim rather than a property. So an export reads
from the capsule's ``exports`` directory — the only place a capsule can put
something it wants the user to have — and writes a *new* file at an approved
destination.

Four rules on the way out, each of which is a way the export becomes the hole:

**The destination is somewhere the user keeps files.** Inside one of their own
XDG directories, resolved. Not ``/etc``, not another capsule, not a dot directory
that holds credentials. A capsule cannot name the destination at all; it names a
file in its own ``exports`` and Bunny decides where that goes.

**The original is never the destination.** Compared by resolved path, so a
destination that is a symlink to the input is caught. Overwriting the input
requires an explicit ``overwrite=True`` from a caller that has a ``write`` grant
for it, and even then the original is copied aside first.

**A name collision produces a new name, never a silent replacement.** ``cat.png``
lands next to an existing ``cat.png`` as ``cat (1).png``. Silently replacing
somebody's file with the output of an automated task is the single most damaging
thing this code could do, and the numbering is the whole defence.

**The bytes are verified after the copy.** A digest of the source and of the
destination, compared. A truncated copy that reported success would tell somebody
their work was saved when it was not.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import shutil
from typing import Any, Mapping

from trust.persistence import private_directory
from trust.resources import Resource, contains, real_path

from .errors import CapsuleExportRefused, CapsuleSchemaError
from .isolation import CREDENTIAL_DIRECTORIES, GRANT_TARGET_ROOT
from .layout import CapsuleLayout, is_capsule_private

__all__ = [
    "MAX_EXPORT_ATTEMPTS",
    "ExportResult",
    "ImportDescription",
    "describe_import",
    "digest_file",
    "export_artifact",
    "user_destinations",
]

#: How many numbered names an export will try before giving up. A directory with
#: a thousand ``cat (n).png`` is not a collision, it is a defect somewhere.
MAX_EXPORT_ATTEMPTS = 1000

_XDG_DESTINATIONS = {
    "Documents": "XDG_DOCUMENTS_DIR",
    "Downloads": "XDG_DOWNLOAD_DIR",
    "Pictures": "XDG_PICTURES_DIR",
    "Music": "XDG_MUSIC_DIR",
    "Videos": "XDG_VIDEOS_DIR",
    "Desktop": "XDG_DESKTOP_DIR",
}


def user_destinations(home: Path | None = None) -> Mapping[str, Path]:
    """The directories an export may land in, resolved.

    The home directory itself is not one. "Anywhere in your home" is not a bound,
    and it contains every credential directory in
    :data:`~capsules.isolation.CREDENTIAL_DIRECTORIES`.
    """
    base = Path(home) if home is not None else Path(os.path.expanduser("~"))
    found: dict[str, Path] = {}
    for name, variable in sorted(_XDG_DESTINATIONS.items()):
        configured = os.environ.get(variable)
        path = Path(configured) if configured else base / name
        found[name] = path
    return found


def digest_file(path: Path) -> str:
    """SHA-256 of a file's contents, read in blocks."""
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


@dataclass(frozen=True)
class ImportDescription:
    """What a capsule will be able to see, said the way the prompt said it."""

    resource: Resource
    sandbox_path: str
    writable: bool

    def as_record(self) -> Mapping[str, Any]:
        return {
            "resource": dict(self.resource.as_record()),
            "sandboxPath": self.sandbox_path,
            "writable": self.writable,
        }


def describe_import(resource: Resource, *, writable: bool) -> ImportDescription:
    """Where a granted path will appear inside the capsule.

    Mirrors :func:`capsules.isolation._grant_target` deliberately rather than
    calling it: this runs before a grant exists, when there is nothing to key on
    but the resource, and the two are asserted equal by a test so they cannot
    drift.
    """
    if resource.kind != "path":
        raise CapsuleSchemaError("only a path can be imported into a capsule")
    name = Path(resource.identifier.rstrip("/") or "/").name or "item"
    return ImportDescription(
        resource=resource,
        sandbox_path=f"{GRANT_TARGET_ROOT}/{resource.digest}/{name}",
        writable=writable,
    )


@dataclass(frozen=True)
class ExportResult:
    """Where the artefact went, and what was true about the original."""

    source: str
    destination: str
    display: str
    digest: str
    bytes_written: int
    renamed: bool
    original_preserved: bool
    #: Where the input was copied to before being overwritten, when it was.
    original_copy: str | None = None

    def as_record(self) -> Mapping[str, Any]:
        return {
            "destination": self.destination,
            "display": self.display,
            "digest": self.digest,
            "bytesWritten": self.bytes_written,
            "renamed": self.renamed,
            "originalPreserved": self.original_preserved,
            "originalCopy": self.original_copy,
        }


def _unique(destination: Path) -> tuple[Path, bool]:
    if not destination.exists():
        return destination, False
    stem, suffix = destination.stem, destination.suffix
    for index in range(1, MAX_EXPORT_ATTEMPTS):
        candidate = destination.with_name(f"{stem} ({index}){suffix}")
        if not candidate.exists():
            return candidate, True
    raise CapsuleExportRefused(f"{destination.parent} already holds {MAX_EXPORT_ATTEMPTS} files with that name")


def export_artifact(
    layout: CapsuleLayout,
    artifact_name: str,
    *,
    destination_root: Path,
    original: Path | None = None,
    overwrite: bool = False,
    capsule_root: Path | None = None,
    home: Path | None = None,
) -> ExportResult:
    """Copy one artefact out of a capsule to a place the user keeps files.

    ``artifact_name`` names a file in the capsule's ``exports`` directory and is
    a *name*, not a path: a capsule does not get to say where in its own tree the
    artefact is, because the answer to "where" would be a traversal parameter.

    ``original`` is the input the task was run on, when there was one. It is
    passed so that this function — not the caller, not the model — is the thing
    that refuses to overwrite it.
    """
    if not isinstance(artifact_name, str) or not artifact_name:
        raise CapsuleSchemaError("an artefact needs a name")
    if "/" in artifact_name or "\\" in artifact_name or artifact_name in (".", ".."):
        raise CapsuleSchemaError(f"not an artefact name: {artifact_name!r}")

    exports = layout.directory("exports")
    source = real_path(exports / artifact_name)
    if not contains(real_path(exports), source):
        raise CapsuleExportRefused("that artefact is not in the capsule's exports directory")
    if not source.is_file():
        raise CapsuleExportRefused("there is no such artefact to export")

    target_directory = real_path(destination_root)
    approved = {name: real_path(path) for name, path in user_destinations(home).items()}
    if not any(contains(root, target_directory) for root in approved.values()):
        raise CapsuleExportRefused("that is not one of your own folders")
    if is_capsule_private(target_directory, root=capsule_root):
        raise CapsuleExportRefused("results are not exported into another app's private space")
    for part in target_directory.parts:
        if part in CREDENTIAL_DIRECTORIES:
            raise CapsuleExportRefused(f"{part} holds credentials and is not an export destination")

    if not target_directory.exists():
        private_directory(target_directory)
    destination = target_directory / source.name
    resolved_original = real_path(original) if original is not None else None

    renamed = False
    original_copy: Path | None = None
    if destination.exists() and not overwrite:
        destination, renamed = _unique(destination)
    elif destination.exists() and overwrite:
        # An explicit overwrite. If what is about to be replaced is the task's own
        # input, a copy is kept aside first, so "explicitly requested" still does
        # not mean "unrecoverable". This is the one place §15's guarantee is
        # deliberately relaxed, and it is relaxed by half rather than entirely.
        if resolved_original is not None and real_path(destination) == resolved_original:
            original_copy, _ = _unique(
                destination.with_name(f"{destination.stem} (original){destination.suffix}")
            )
            shutil.copy2(resolved_original, original_copy)

    shutil.copyfile(source, destination)
    shutil.copystat(source, destination, follow_symlinks=False)
    written = destination.stat().st_size
    source_digest = digest_file(source)
    if digest_file(destination) != source_digest:
        try:
            destination.unlink()
        except OSError:
            pass
        raise CapsuleExportRefused("the copy did not match the artefact and was removed")

    # Preserved means the input path still holds what it held. An overwrite of
    # the input makes this False even though a copy was kept aside, because the
    # sentence the user is shown must not say "your original wasn't modified"
    # about a file that was.
    original_preserved = resolved_original is None or real_path(destination) != resolved_original

    display = _display(destination, approved)
    return ExportResult(
        source=str(source),
        destination=str(destination),
        display=display,
        digest=source_digest,
        bytes_written=int(written),
        renamed=renamed,
        original_preserved=bool(original_preserved),
        original_copy=str(original_copy) if original_copy is not None else None,
    )


def _display(destination: Path, approved: Mapping[str, Path]) -> str:
    for name, root in sorted(approved.items(), key=lambda item: -len(str(item[1]))):
        if contains(root, destination):
            relative = destination.relative_to(root)
            return f"{name}/{relative}" if relative.parts else name
    return destination.name
