# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Locations for the repository-owned reference character."""

from __future__ import annotations

from pathlib import Path


def default_character_paths() -> tuple[Path, ...]:
    source = Path(__file__).resolve().parents[2] / "assets" / "companion" / "characters" / "default-bunny"
    installed = Path("/usr/share/bunny-os/companion/characters/default-bunny")
    return installed, source


def default_character_path() -> Path:
    for path in default_character_paths():
        if path.is_dir():
            return path
    return default_character_paths()[-1]
