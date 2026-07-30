# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What an archive-only build may and may not be used to claim.

`BUNNY_ARCHIVE_ONLY=1` stops the build after the normalised OCI archive. It
exists so a hosted Ubuntu runner can be a real second builder: the reproducibility
comparison compares the archive, its members, the SBOM and the package inventory,
and none of those comes from `image-builder`, which is Fedora-only.

The mode is a genuine capability reduction, and the danger is that the artifact it
produces looks like a normal one. It has the same name, the same digest
discipline, the same provenance shape. What it does not have is a disk image —
and therefore nothing was installed, nothing booted, no recovery media was
written and no hardware was exercised. An archive-only artifact presented as a
release candidate would carry a qualification claim that no step of its build
could have justified.

So the mode is recorded in the artifact's own provenance as `archiveOnly: true`
and refused here, rather than inferred later from which files are missing.
Inference is what allows a truncated full build to pass as a candidate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

__all__ = [
    "ARCHIVE_ONLY_CANNOT_QUALIFY",
    "BuildCapability",
    "BuildModeError",
    "evaluate_build_mode",
    "require_candidate_capable",
]

#: Everything an archive-only build says nothing about. Each of these is a
#: qualification prerequisite that needs a disk image to even attempt.
ARCHIVE_ONLY_CANNOT_QUALIFY = (
    "installation",
    "recovery-media",
    "hardware",
    "encryption",
    "update",
    "rollback",
    "secure-boot",
    "stable-artifact",
)

DISK_SUFFIXES = (".qcow2", ".raw", ".iso", ".vmdk")


class BuildModeError(ValueError):
    """An artifact was used for something its build mode cannot support."""


@dataclass(frozen=True)
class BuildCapability:
    archiveOnly: bool
    diskImages: tuple[str, ...]
    hasOciArchive: bool
    declared: bool
    reasons: tuple[str, ...]

    @property
    def candidateCapable(self) -> bool:
        """Whether this build could, in principle, be a release candidate."""
        return not self.archiveOnly and bool(self.diskImages) and not self.reasons

    def as_dict(self) -> dict[str, Any]:
        return {
            "archiveOnly": self.archiveOnly,
            "diskImages": list(self.diskImages),
            "hasOciArchive": self.hasOciArchive,
            "buildModeDeclared": self.declared,
            "candidateCapable": self.candidateCapable,
            "cannotQualify": list(ARCHIVE_ONLY_CANNOT_QUALIFY) if self.archiveOnly else [],
            "reasons": list(self.reasons),
        }


def evaluate_build_mode(provenance: Mapping[str, Any]) -> BuildCapability:
    """Read the build mode out of a build provenance record.

    Reads `archiveOnly` where it is declared. Where it is not — an older record
    written before the field existed — the mode is *unknown*, not *full*, and the
    record is refused for candidate use. Treating an undeclared record as a full
    build is the assumption this module exists to avoid.
    """
    if not isinstance(provenance, Mapping):
        raise BuildModeError("build provenance must be an object")

    reasons: list[str] = []
    declared = "archiveOnly" in provenance
    archive_only = bool(provenance.get("archiveOnly", False))

    artifacts = provenance.get("artifacts", [])
    if not isinstance(artifacts, list):
        raise BuildModeError("build provenance artifacts must be a list")

    paths = [
        str(item.get("path", "")) for item in artifacts if isinstance(item, Mapping)
    ]
    observed_disks = tuple(
        sorted(path for path in paths if path.endswith(DISK_SUFFIXES))
    )
    has_archive = any(path.endswith("bunny-os.oci.tar") for path in paths)

    recorded_disks = provenance.get("diskImages")
    if isinstance(recorded_disks, list):
        recorded = tuple(sorted(str(item) for item in recorded_disks))
        if recorded != observed_disks:
            reasons.append(
                f"provenance records diskImages {list(recorded)} but its artifact list holds "
                f"{list(observed_disks)}; the record disagrees with itself"
            )

    if not declared:
        reasons.append(
            "build provenance does not declare archiveOnly; the build mode is unknown and an "
            "artifact of unknown mode cannot be a release candidate"
        )

    if archive_only and observed_disks:
        reasons.append(
            f"provenance claims archiveOnly but carries disk images {list(observed_disks)}"
        )
    if declared and not archive_only and not observed_disks:
        reasons.append(
            "provenance claims a full build but carries no disk image"
        )

    return BuildCapability(
        archiveOnly=archive_only,
        diskImages=observed_disks,
        hasOciArchive=has_archive,
        declared=declared,
        reasons=tuple(reasons),
    )


def require_candidate_capable(
    provenance: Mapping[str, Any], *, gate: str = "qualification-candidate"
) -> BuildCapability:
    """Raise unless this build could be a release candidate.

    Called by the candidate and stable gates. The message names what the build
    did not do, because "rejected" without that is indistinguishable from a bug.
    """
    capability = evaluate_build_mode(provenance)
    if capability.candidateCapable:
        return capability

    if capability.archiveOnly:
        raise BuildModeError(
            f"{gate}: this is an archive-only build (BUNNY_ARCHIVE_ONLY=1). It produced an OCI "
            "archive and no disk image, so nothing was installed, nothing booted, no recovery "
            "media was written and no hardware was exercised. It cannot qualify: "
            + ", ".join(ARCHIVE_ONLY_CANNOT_QUALIFY)
            + ". An archive-only build is evidence for reproducibility comparison only."
        )
    raise BuildModeError(f"{gate}: " + "; ".join(capability.reasons))
