#!/usr/bin/env python3
"""Render deterministic, character-free boot and authentication concepts."""

from __future__ import annotations

import argparse
from html import escape
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "visual-v2/assets"
MANIFEST = ASSETS / "system-concepts.json"
NOTICE = ("VISUAL PROTOTYPE ONLY", "NOT RELEASE QUALIFIED", "DO NOT MERGE INTO MAIN")


def _tokens() -> dict[str, str]:
    colors = json.loads((ROOT / "visual-v2/tokens/colors.json").read_text(encoding="utf-8"))
    return colors["themes"]["dark"] | colors["accents"] | colors["semantic"]


def _symbol(x: int, y: int, scale: float, colors: dict[str, str]) -> str:
    return f'''<g transform="translate({x} {y}) scale({scale})" fill="none" stroke="{colors['text']}" stroke-width="7" stroke-linecap="round">
    <ellipse cx="-18" cy="-28" rx="12" ry="28" transform="rotate(-16 -18 -28)"/>
    <ellipse cx="18" cy="-28" rx="12" ry="28" transform="rotate(16 18 -28)"/>
    <circle cx="0" cy="12" r="32"/><circle cx="-11" cy="8" r="2.5" fill="{colors['text']}"/><circle cx="11" cy="8" r="2.5" fill="{colors['text']}"/>
  </g>'''


def _notice(colors: dict[str, str]) -> str:
    return "".join(
        f'<text x="28" y="{1004 + index * 20}" class="notice">{escape(line)}</text>'
        for index, line in enumerate(NOTICE)
    )


def _frame(title: str, content: str, colors: dict[str, str]) -> str:
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080" viewBox="0 0 1920 1080">
  <title>{escape(title)} — Bunny Desktop Visual V2 concept</title>
  <metadata>{escape(" | ".join(NOTICE))}</metadata>
  <defs>
    <radialGradient id="depth" cx="50%" cy="42%" r="75%"><stop stop-color="{colors['deep']}"/><stop offset="1" stop-color="{colors['background']}"/></radialGradient>
    <filter id="shadow" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="20"/></filter>
  </defs>
  <style>.display{{fill:{colors['text']};font:600 56px 'Adwaita Sans',sans-serif}}.title{{fill:{colors['text']};font:600 28px 'Adwaita Sans',sans-serif}}.body{{fill:{colors['text']};font:16px 'Adwaita Sans',sans-serif}}.label{{fill:{colors['text']};font:500 14px 'Adwaita Sans',sans-serif}}.muted{{fill:{colors['muted']};font:14px 'Adwaita Sans',sans-serif}}.notice{{fill:{colors['warning']};font:700 11px 'Adwaita Mono',monospace}}</style>
  <rect width="1920" height="1080" fill="url(#depth)"/>
  <path d="M-90 960 C 70 190, 480 20, 790 1080" fill="none" stroke="{colors['violet']}" stroke-opacity=".13" stroke-width="120" stroke-linecap="round"/>
  <path d="M2010 960 C 1850 190, 1440 20, 1130 1080" fill="none" stroke="{colors['sky']}" stroke-opacity=".11" stroke-width="120" stroke-linecap="round"/>
  {content}
  {_notice(colors)}
</svg>
'''


def _boot(colors: dict[str, str], *, shutdown: bool = False) -> str:
    verb = "Shutting down safely" if shutdown else "Starting Bunny OS"
    progress = "" if shutdown else f'''<rect x="835" y="688" width="250" height="4" rx="2" fill="{colors['panel']}"/><rect x="835" y="688" width="156" height="4" rx="2" fill="{colors['sky']}"/>'''
    content = f'''{_symbol(960, 430, 1.6, colors)}
  <text x="960" y="570" text-anchor="middle" class="display">Bunny OS</text>
  <text x="960" y="630" text-anchor="middle" class="muted">{verb}</text>{progress}'''
    return _frame("Shutdown concept" if shutdown else "Boot splash concept", content, colors)


def _login(colors: dict[str, str]) -> str:
    content = f'''<text x="48" y="62" class="title">Bunny OS</text><text x="960" y="60" text-anchor="middle" class="label">Mon, May 12 · 10:30 AM</text>
  <rect x="674" y="154" width="572" height="720" rx="24" fill="{colors['deep']}" fill-opacity=".96" stroke="{colors['border']}"/>
  {_symbol(960, 292, 1.05, colors)}<text x="960" y="405" text-anchor="middle" class="title">Alex Morgan</text><text x="960" y="438" text-anchor="middle" class="muted">Enter your password to continue</text>
  <rect x="744" y="486" width="432" height="58" rx="12" fill="{colors['surface']}" stroke="{colors['focus']}"/><text x="768" y="522" class="muted">Password</text>
  <rect x="744" y="566" width="432" height="58" rx="12" fill="{colors['violet']}"/><text x="960" y="603" text-anchor="middle" class="label">Unlock</text>
  <rect x="744" y="652" width="432" height="112" rx="16" fill="{colors['elevated']}"/><text x="768" y="688" class="label">Session</text><text x="768" y="721" class="body">GNOME</text><text x="768" y="748" class="muted">Bunny Desktop Preview is available from the selector</text>
  <text x="1430" y="1034" class="label">Keyboard · Accessibility · Network · Power</text>'''
    return _frame("Login screen concept", content, colors)


def _lock(colors: dict[str, str]) -> str:
    content = f'''<text x="960" y="386" text-anchor="middle" class="display">10:30</text><text x="960" y="440" text-anchor="middle" class="title">Monday, May 12</text>
  <rect x="786" y="532" width="348" height="60" rx="16" fill="{colors['surface']}" fill-opacity=".94" stroke="{colors['border']}"/><text x="960" y="570" text-anchor="middle" class="body">Press a key to unlock</text>
  <text x="1442" y="1034" class="label">Accessibility · Network · Power</text>'''
    return _frame("Lock screen concept", content, colors)


def _selector(colors: dict[str, str]) -> str:
    content = f'''<rect x="616" y="160" width="688" height="720" rx="24" fill="{colors['deep']}" fill-opacity=".97" stroke="{colors['border']}"/>
  <text x="664" y="224" class="title">Choose a desktop session</text><text x="664" y="260" class="muted">The system default remains unchanged.</text>
  <rect x="654" y="314" width="612" height="132" rx="16" fill="{colors['elevated']}" stroke="{colors['focus']}"/><circle cx="698" cy="358" r="11" fill="{colors['sky']}"/><text x="730" y="365" class="title">GNOME</text><text x="730" y="402" class="muted">Existing desktop session</text>
  <rect x="654" y="468" width="612" height="166" rx="16" fill="{colors['elevated']}"/><circle cx="698" cy="514" r="11" fill="none" stroke="{colors['muted']}" stroke-width="2"/><text x="730" y="521" class="title">Bunny Desktop Preview</text><text x="730" y="558" class="muted">Selectable visual prototype · never selected automatically</text><text x="730" y="592" class="muted">Regular Mode is the initial visual mode</text>
  <rect x="912" y="752" width="146" height="52" rx="12" fill="{colors['surface']}"/><text x="985" y="785" text-anchor="middle" class="label">Cancel</text><rect x="1076" y="752" width="146" height="52" rx="12" fill="{colors['violet']}"/><text x="1149" y="785" text-anchor="middle" class="label">Select</text>'''
    return _frame("Session selector concept", content, colors)


def outputs() -> dict[Path, str]:
    colors = _tokens()
    return {
        ASSETS / "boot/boot-splash.svg": _boot(colors),
        ASSETS / "boot/shutdown.svg": _boot(colors, shutdown=True),
        ASSETS / "login/login-screen.svg": _login(colors),
        ASSETS / "login/lock-screen.svg": _lock(colors),
        ASSETS / "login/session-selector.svg": _selector(colors),
    }


def render(check: bool) -> int:
    mismatches: list[str] = []
    for target, value in outputs().items():
        if check:
            if not target.is_file() or target.read_text(encoding="utf-8") != value:
                mismatches.append(target.relative_to(ROOT).as_posix())
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(value, encoding="utf-8", newline="\n")
    if mismatches:
        print("System concept mismatch: " + ", ".join(mismatches))
        return 1
    print(("Verified" if check else "Rendered") + " 5 deterministic system concepts")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    return render(parser.parse_args().check)


if __name__ == "__main__":
    raise SystemExit(main())
