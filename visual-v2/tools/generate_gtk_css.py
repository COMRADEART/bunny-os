#!/usr/bin/env python3
"""Generate GTK companion-app CSS from Bunny Visual V2 tokens."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOKENS = ROOT / "visual-v2/tokens"
TARGET = ROOT / "apps/common/bunny_visual_v2/style.css"


def read(name: str) -> dict:
    return json.loads((TOKENS / name).read_text(encoding="utf-8"))


def render() -> str:
    colors = read("colors.json")
    dark = colors["themes"]["dark"]
    spacing = read("spacing.json")["scale"]
    radii = read("radii.json")["tokens"]
    type_scale = read("typography.json")["scale"]
    semantic = colors["semantic"]
    return f"""/* Generated from visual-v2/tokens. Do not hand edit. */
/* VISUAL PROTOTYPE ONLY — NOT RELEASE QUALIFIED — DO NOT MERGE INTO MAIN */
.bunny-window {{ background: {dark['background']}; color: {dark['text']}; }}
.bunny-card {{ background: {dark['elevated']}; border: 1px solid {dark['border']}; border-radius: {radii['card']}px; padding: {spacing['lg']}px; }}
.bunny-character-region {{ background: {dark['deep']}; border-radius: {radii['card']}px; padding: {spacing['sm']}px; }}
.bunny-mock-banner {{ background: {semantic['warning']}; color: {dark['background']}; border-radius: {radii['small']}px; padding: {spacing['sm']}px {spacing['md']}px; font-weight: 700; }}
.bunny-state {{ color: {colors['accents']['sky']}; font-weight: 600; }}
.bunny-mono {{ font-family: 'Adwaita Mono'; font-size: {type_scale['monospace']['size']}px; }}
.caption {{ color: {dark['muted']}; font-size: {type_scale['caption']['size']}px; }}
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    value = render()
    if args.check:
        return 0 if TARGET.is_file() and TARGET.read_text(encoding="utf-8") == value else 1
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(value, encoding="utf-8", newline="\n")
    print(TARGET)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
