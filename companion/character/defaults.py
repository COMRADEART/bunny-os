# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Locations for the repository-owned reference character."""

from __future__ import annotations

from pathlib import Path


def _candidates(name: str) -> tuple[Path, Path]:
    source = Path(__file__).resolve().parents[2] / "assets" / "companion" / "characters" / name
    installed = Path(f"/usr/share/bunny-os/companion/characters/{name}")
    return installed, source


def default_character_paths() -> tuple[Path, ...]:
    """Every built-in package, **2D first**.

    Order is load-bearing: :meth:`companion.character.importer.PackageRegistry.selected`
    returns the first built-in when the user has chosen nothing, so this tuple
    decides the out-of-the-box character. The 2D package keeps that position
    deliberately.

    §24 says a package change must be user-initiated, and promoting the 3D
    character to the default would be this phase changing what every existing
    machine draws as a side effect of adding a renderer. The 3D package is
    shipped, validated by exactly the same validator, and selected with
    ``bunny-os companion character select bunny-default-3d``. §33's slice and
    the 3D diagnostics select it explicitly.
    """
    return _candidates("default-bunny") + _candidates("default-bunny-3d")


def default_character_path() -> Path:
    for path in _candidates("default-bunny"):
        if path.is_dir():
            return path
    return _candidates("default-bunny")[-1]


def default_3d_character_path() -> Path:
    """The built-in 3D package, wherever it is on this machine."""
    for path in _candidates("default-bunny-3d"):
        if path.is_dir():
            return path
    return _candidates("default-bunny-3d")[-1]
