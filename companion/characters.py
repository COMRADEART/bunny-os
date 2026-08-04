# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""One static character, and the reasons it is only one.

This build ships a single image: an original bunny drawn as SVG, shipped in the
repository under the same licence as everything else, and loaded from a fixed
path list. There is deliberately no importer, no archive reader, no manifest and
no way for a user to install a character from anywhere — that machinery belongs
to the character-renderer branch, where it can be reviewed as the thing it is: a
loader for third-party content, which is one of the two or three most dangerous
components a desktop can have.

What is enforced here, on the one asset that does ship:

* **fixed paths.** :func:`candidate_paths` returns a closed list. No environment
  variable, protocol parameter or user preference can add to it. A character
  path that came from the wire would be an arbitrary file read with a picture
  in front of it.
* **regular files only.** A symbolic link is refused rather than followed:
  the installed path is under ``/usr/share`` and the source path is inside the
  checkout, and neither should ever be a link to somewhere else.
* **no executable bit, and a declared type.** SVG and PNG only, size-bounded,
  and refused if the file is marked executable — the shipped asset never is, so
  a copy that is has been through something.
* **nothing is fetched.** There is no network code in this module and no
  package script is ever run. A character is a file that was already on the
  disk when the image was built.

And the accessibility rule that outranks all of it: :func:`describe_phase`
produces the state in words, derived from the phase and not from the picture. A
user who cannot see the image, or who has turned it off, or whose machine chose
``text-only``, is told exactly what a user looking at the bunny is told.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any

__all__ = [
    "CharacterAsset",
    "CharacterError",
    "MAX_ASSET_BYTES",
    "PERMITTED_SUFFIXES",
    "candidate_paths",
    "describe_phase",
    "load_static_character",
]


class CharacterError(ValueError):
    """The shipped asset is not what it should be, and was not loaded."""


#: What a character asset may be. Both are data formats a renderer draws; there
#: is no entry that can carry a script. SVG can carry one in principle, which is
#: why :func:`load_static_character` checks for it rather than trusting the
#: suffix — see the scan in :func:`_refuse_active_content`.
PERMITTED_SUFFIXES = frozenset({".svg", ".png"})

#: A static character is a small picture. The bound is here so that a
#: substituted file cannot make the client allocate arbitrarily.
MAX_ASSET_BYTES = 2 * 1024 * 1024

#: Markup an SVG may not contain. A static character is a drawing; a drawing
#: with a script in it is a program the shell would run at whatever privilege
#: the shell has. Checked on load rather than assumed from the suffix.
_ACTIVE_CONTENT = (
    b"<script",
    b"javascript:",
    b"<foreignobject",
    b"onload=",
    b"onclick=",
    b"onerror=",
    b"<!entity",
    b"<iframe",
)


def candidate_paths() -> tuple[Path, ...]:
    """Where the shipped character may be, in order. A closed list.

    Installed location first, source tree second. Nothing else, and in
    particular nothing from the environment: a ``BUNNY_CHARACTER_PATH`` would be
    a way to point the shell at any file on the machine and have it rendered.
    """
    return (
        Path("/usr/share/bunny-shell/companion/default-bunny.svg"),
        Path(__file__).resolve().parents[1] / "shell" / "assets" / "companion" / "default-bunny.svg",
    )


@dataclass(frozen=True)
class CharacterAsset:
    """The one picture, and what may be said about it without seeing it."""

    path: Path
    media_type: str
    byte_size: int
    #: Text that stands in for the image everywhere it cannot be drawn. Not a
    #: caption for the picture: a description of the *character*, so that the
    #: text-only presentation is a complete surface rather than a degraded one.
    alternative_text: str = "A white bunny with violet ears, drawn as a simple flat illustration."

    def to_json(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "mediaType": self.media_type,
            "byteSize": self.byte_size,
            "alternativeText": self.alternative_text,
            "renderer": "static-image",
            "animated": False,
            "remote": False,
        }


def _refuse_active_content(path: Path, data: bytes) -> None:
    lowered = data.lower()
    for marker in _ACTIVE_CONTENT:
        if marker in lowered:
            raise CharacterError(
                f"{path} contains {marker.decode('ascii')!r}; a static character is a drawing "
                "and this one carries active content"
            )


def load_static_character(paths: tuple[Path, ...] | None = None) -> CharacterAsset | None:
    """Find and validate the shipped character. ``None`` when there is none.

    ``None`` rather than an exception for absence, because a missing picture is
    a presentation this build already supports — ``text-only`` — and not a
    fault. A picture that is *present and wrong* does raise: that is a file
    somebody replaced, and rendering it anyway is the failure mode this function
    exists to prevent.
    """
    for candidate in paths or candidate_paths():
        try:
            if candidate.is_symlink():
                raise CharacterError(f"{candidate} is a symbolic link and was not followed")
            if not candidate.is_file():
                continue
            status = candidate.stat()
        except OSError:
            continue
        suffix = candidate.suffix.casefold()
        if suffix not in PERMITTED_SUFFIXES:
            raise CharacterError(
                f"{candidate} is a {suffix or 'typeless'} file; a character asset is "
                f"one of {sorted(PERMITTED_SUFFIXES)}"
            )
        if status.st_size <= 0 or status.st_size > MAX_ASSET_BYTES:
            raise CharacterError(
                f"{candidate} is {status.st_size} bytes against a limit of {MAX_ASSET_BYTES}"
            )
        if os.name == "posix" and status.st_mode & 0o111:
            raise CharacterError(f"{candidate} is marked executable; a picture is not a program")
        data = candidate.read_bytes()
        if suffix == ".svg":
            _refuse_active_content(candidate, data)
        return CharacterAsset(
            path=candidate,
            media_type="image/svg+xml" if suffix == ".svg" else "image/png",
            byte_size=status.st_size,
        )
    return None


#: What the character is doing, in words, for every phase in
#: :data:`companion.presentation.PRESENTATION_PHASES`.
#:
#: Written as descriptions of the *companion's state* rather than of the
#: drawing, so that they read correctly whether or not anything is drawn. This
#: is the accessibility contract: the text-only surface is not a fallback that
#: says less, it is the same surface without the picture.
_PHASE_DESCRIPTIONS = {
    "idle": "Bunny is waiting for something to do.",
    "starting": "Bunny has taken the request and is getting started.",
    "recovering": "Bunny is checking what was interrupted when the machine stopped.",
    "understanding": "Bunny is working out what was asked.",
    "planning": "Bunny is deciding what to do.",
    "waiting_for_approval": "Bunny has stopped and is waiting for you to answer a question.",
    "listening": "Bunny is listening. The microphone is on.",
    "speaking": "Bunny is reading the result aloud.",
    "working": "Bunny is doing the work.",
    "reviewing": "A reviewer is looking at what Bunny did.",
    "presenting_result": "Bunny has a result and is showing it.",
    "success": "Bunny has finished.",
    "cancelling": "Bunny is stopping.",
    "cancelled": "Bunny stopped because you asked it to.",
    "paused": "Bunny is paused.",
    "blocked": "Bunny cannot go further without something changing.",
    "error": "Something went wrong and Bunny stopped.",
    "disconnected": "This window cannot reach the companion runtime. Any task is still running.",
}


def describe_phase(phase: str) -> str:
    """The state in words. Independent of the image, and never empty."""
    return _PHASE_DESCRIPTIONS.get(phase, "Bunny is here.")
