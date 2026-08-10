# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""One build identity, read from the image, shown everywhere it is asked for.

§39 wants a single identity visible in settings, in diagnostics, in the release
metadata, in the installer and in the image filename. "Single" is the hard part:
there were already three places a version could come from — the OCI label, the
artifact manifest and ``release.json`` — and a fourth computed in the companion
would have made four.

So this reads ``/usr/lib/bunny-os/release.json``, which the build writes, and
derives nothing that the build did not already state. The two fields this phase
adds to that file are the channel and the build id; everything else here is a
projection of what was already there.

**The build id is not a version.** ``0.1.0`` is what the product calls itself and
it will be ``0.1.0`` for every Alpha build. The build id is what distinguishes
two of them, and it is derived from the source commit and the source date so
that two builds of the same tree get the same id — which is the property a
reproducibility claim would later need, and the reason it is not a counter.

On a developer checkout there is no ``release.json``. Rather than invent one,
:func:`build_identity` returns an identity whose ``channel`` is
``development`` and whose ``installed`` flag is ``False``, and every surface
that shows it shows that flag. A screenshot of a settings page that says
"Alpha 0.1" on a machine running from a checkout is exactly the confusion this
avoids.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Mapping

__all__ = [
    "ALPHA_VERSION",
    "RELEASE_CHANNELS",
    "RELEASE_METADATA_PATH",
    "BuildIdentity",
    "build_identity",
]

#: What this phase's product calls itself. One string, in one place.
ALPHA_VERSION = "0.1.0"

#: §40: two channels, and deliberately no more. A stable/beta/canary matrix is
#: infrastructure for a release cadence that does not exist yet, and every
#: channel is a promise about what lands in it.
RELEASE_CHANNELS: tuple[str, ...] = ("development", "alpha")

RELEASE_METADATA_PATH = Path("/usr/lib/bunny-os/release.json")

_UNKNOWN = "unknown"


@dataclass(frozen=True)
class BuildIdentity:
    """What this system is, as one record.

    ``installed`` is the field that keeps the rest honest: ``False`` means these
    values came from a source checkout rather than from an image, and no surface
    may present them as a release.
    """

    product: str = "Bunny OS"
    version: str = ALPHA_VERSION
    channel: str = "development"
    build_id: str = _UNKNOWN
    source_commit: str = _UNKNOWN
    image_version: str = _UNKNOWN
    image_digest: str = ""
    profile: str = _UNKNOWN
    architecture: str = _UNKNOWN
    build_timestamp: str = "unspecified"
    base_image_reference: str = ""
    installed: bool = False

    @property
    def display_name(self) -> str:
        """What a person sees. ``Bunny OS Alpha 0.1`` when it is one."""
        if self.channel == "alpha":
            major_minor = ".".join(self.version.split(".")[:2])
            return f"{self.product} Alpha {major_minor}"
        return f"{self.product} {self.version} ({self.channel})"

    @property
    def image_filename(self) -> str:
        """The name §39 asks the image to carry, built from the same fields."""
        channel = self.channel if self.channel in RELEASE_CHANNELS else "development"
        parts = [
            "bunny-os", self.version, channel,
            self.build_id if self.build_id != _UNKNOWN else "nobuildid",
            self.architecture if self.architecture != _UNKNOWN else "noarch",
        ]
        return "-".join(parts)

    @property
    def alpha(self) -> bool:
        return self.channel == "alpha"

    def to_json(self) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "product": self.product,
            "version": self.version,
            "channel": self.channel,
            "buildId": self.build_id,
            "sourceCommit": self.source_commit,
            "imageVersion": self.image_version,
            "imageDigest": self.image_digest,
            "profile": self.profile,
            "architecture": self.architecture,
            "buildTimestamp": self.build_timestamp,
            "baseImageReference": self.base_image_reference,
            "installed": self.installed,
            "displayName": self.display_name,
            "imageFilename": self.image_filename,
        }

    def lines(self) -> tuple[str, ...]:
        """The identity as a person reads it, for a settings page or a header."""
        rows = [
            self.display_name,
            f"Build {self.build_id}",
            f"Commit {self.source_commit[:12] if self.source_commit != _UNKNOWN else _UNKNOWN}",
            f"Channel {self.channel}",
            f"Architecture {self.architecture}",
            f"Built {self.build_timestamp}",
        ]
        if self.image_digest:
            rows.append(f"Image {self.image_digest}")
        if not self.installed:
            rows.append(
                "This is a source checkout, not an installed image. "
                "These values describe the working tree."
            )
        return tuple(rows)


def _read_metadata(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return value if isinstance(value, Mapping) else {}


def _architecture() -> str:
    import platform

    machine = platform.machine().lower()
    return {"amd64": "x86_64", "x86_64": "x86_64", "arm64": "aarch64", "aarch64": "aarch64"}.get(
        machine, machine or _UNKNOWN,
    )


def _checkout_commit(root: Path) -> str:
    """The working tree's commit, when git is available and this is a checkout.

    Best effort by design. A development identity with an unknown commit is
    still a usable identity; running git and failing must not be an error.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return _UNKNOWN
    value = result.stdout.strip()
    return value if result.returncode == 0 and len(value) == 40 else _UNKNOWN


def derive_build_id(source_commit: str, source_date_epoch: Any) -> str:
    """``<12 hex of commit>.<epoch>`` — deterministic, and not a counter.

    Two builds of one tree at one ``SOURCE_DATE_EPOCH`` produce the same id.
    That is the point: an id that incremented would make every rebuild a
    different build even when nothing about it differed, and the later
    qualification phase needs the opposite property.
    """
    commit = source_commit if isinstance(source_commit, str) and source_commit != _UNKNOWN else ""
    try:
        epoch = int(source_date_epoch)
    except (TypeError, ValueError):
        epoch = 0
    if not commit:
        return _UNKNOWN
    return f"{commit[:12]}.{epoch}"


def build_identity(
    *,
    metadata_path: Path = RELEASE_METADATA_PATH,
    source_root: Path | None = None,
) -> BuildIdentity:
    """Read the identity from the installed image, or describe the checkout."""
    metadata = _read_metadata(metadata_path)
    architecture = _architecture()
    if not metadata:
        root = source_root or Path(__file__).resolve().parents[1]
        commit = _checkout_commit(root)
        return BuildIdentity(
            version=ALPHA_VERSION, channel="development",
            build_id=derive_build_id(commit, 0), source_commit=commit,
            architecture=architecture, installed=False,
        )

    def text(key: str, default: str = _UNKNOWN) -> str:
        value = metadata.get(key)
        return value if isinstance(value, str) and value else default

    channel = text("releaseChannel", "development")
    if channel not in RELEASE_CHANNELS:
        channel = "development"
    commit = text("sourceCommit")
    build_id = text("buildId", "")
    if not build_id:
        build_id = derive_build_id(commit, metadata.get("sourceDateEpoch", 0))
    return BuildIdentity(
        version=text("osVersion", ALPHA_VERSION),
        channel=channel,
        build_id=build_id,
        source_commit=commit,
        image_version=text("imageVersion"),
        image_digest=text("imageDigest", ""),
        profile=text("profile"),
        architecture=text("architecture", architecture),
        build_timestamp=text("buildTimestamp", "unspecified"),
        base_image_reference=text("baseImageReference", ""),
        installed=True,
    )
