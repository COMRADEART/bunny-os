#!/usr/bin/env python3
"""Render deterministic, static Bunny ribbon wallpaper SVGs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WALLPAPERS = ROOT / "visual-v2" / "assets" / "wallpapers"
MANIFEST = WALLPAPERS / "wallpapers.json"


def svg(width: int, height: int, theme: str) -> str:
    if theme == "dark":
        background, deep, violet, sky = "#090C17", "#0D1222", "#8C7CFF", "#63C5FF"
        halo = "0.24"
    else:
        background, deep, violet, sky = "#EDF2FF", "#E4EAF8", "#7667E8", "#3187B8"
        halo = "0.20"
    left = f"M {-0.04 * width:.1f} {0.90 * height:.1f} C {0.04 * width:.1f} {0.20 * height:.1f}, {0.28 * width:.1f} {0.04 * height:.1f}, {0.42 * width:.1f} {0.98 * height:.1f}"
    right = f"M {1.04 * width:.1f} {0.90 * height:.1f} C {0.96 * width:.1f} {0.20 * height:.1f}, {0.72 * width:.1f} {0.04 * height:.1f}, {0.58 * width:.1f} {0.98 * height:.1f}"
    stroke = max(84, round(width * 0.078))
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <title>Bunny ribbon wallpaper — {theme} — {width}×{height}</title>
  <defs>
    <radialGradient id="depth" cx="50%" cy="42%" r="76%"><stop offset="0" stop-color="{deep}"/><stop offset="1" stop-color="{background}"/></radialGradient>
    <linearGradient id="violet" x1="0" y1="0" x2="1" y2="1"><stop stop-color="{violet}" stop-opacity=".72"/><stop offset="1" stop-color="{violet}" stop-opacity=".10"/></linearGradient>
    <linearGradient id="sky" x1="1" y1="0" x2="0" y2="1"><stop stop-color="{sky}" stop-opacity=".68"/><stop offset="1" stop-color="{sky}" stop-opacity=".10"/></linearGradient>
    <filter id="soft" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="{max(18, width * 0.012):.1f}"/></filter>
  </defs>
  <rect width="{width}" height="{height}" fill="url(#depth)"/>
  <path d="{left}" fill="none" stroke="{violet}" stroke-opacity="{halo}" stroke-width="{stroke * 1.22:.1f}" stroke-linecap="round" filter="url(#soft)"/>
  <path d="{right}" fill="none" stroke="{sky}" stroke-opacity="{halo}" stroke-width="{stroke * 1.22:.1f}" stroke-linecap="round" filter="url(#soft)"/>
  <path d="{left}" fill="none" stroke="url(#violet)" stroke-width="{stroke}" stroke-linecap="round"/>
  <path d="{right}" fill="none" stroke="url(#sky)" stroke-width="{stroke}" stroke-linecap="round"/>
</svg>
'''


def render(check: bool) -> int:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    mismatches = []
    for theme in data["themes"]:
        for name, dimensions in data["sizes"].items():
            target = WALLPAPERS / f"bunny-ribbon-{theme}-{name}.svg"
            value = svg(*dimensions, theme)
            if check:
                if not target.is_file() or target.read_text(encoding="utf-8") != value:
                    mismatches.append(target.name)
            else:
                target.write_text(value, encoding="utf-8", newline="\n")
    if mismatches:
        print("Wallpaper mismatch: " + ", ".join(mismatches))
        return 1
    if not check:
        print(f"Rendered {len(data['themes']) * len(data['sizes'])} Bunny ribbon wallpapers")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    return render(parser.parse_args().check)


if __name__ == "__main__":
    raise SystemExit(main())
