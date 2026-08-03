"""Read shared Visual V2 layout tokens for GTK companion applications."""

from __future__ import annotations

import json
from pathlib import Path


def _token_root() -> Path:
    source = Path(__file__).resolve().parents[3] / "visual-v2/tokens"
    return source if source.is_dir() else Path("/usr/share/bunny-visual-v2/tokens")


def _read(name: str) -> dict:
    return json.loads((_token_root() / name).read_text(encoding="utf-8"))


SPACING: dict[str, int] = _read("spacing.json")["scale"]
LAYOUT: dict[str, int | float] = _read("layout.json")["tokens"]
