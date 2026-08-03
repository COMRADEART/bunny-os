#!/usr/bin/env python3
"""Render deterministic Visual V2 SVG review scenarios."""

from __future__ import annotations

import argparse
from html import escape
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = ROOT / "visual-v2/screenshots/scenarios.json"
OUTPUT = ROOT / "visual-v2/screenshots/rendered"


def palette(theme: str) -> dict[str, str]:
    colors = json.loads((ROOT / "visual-v2/tokens/colors.json").read_text(encoding="utf-8"))
    return colors["themes"][theme] | colors["accents"] | colors["semantic"]


def top_bar(colors: dict[str, str], layout: str) -> str:
    focus = layout == "focus"
    left = "FocusMode" if focus else "◌  Bunny OS"
    right = "Exit Focus" if focus else "◉  ◌  ◖  100%"
    return f'''<rect width="1920" height="48" fill="{colors['deep']}" fill-opacity=".96"/><text x="26" y="31" class="body">{left}</text><rect x="833" y="9" width="254" height="30" rx="12" fill="{colors['elevated']}"/><text x="873" y="30" class="label">Mon, May 12 · 10:30 AM</text><text x="1716" y="31" class="body">{right}</text>'''


def dock(colors: dict[str, str], layout: str) -> str:
    if layout == "focus":
        return ""
    width = 570 if layout == "compact" else 690
    height = 62 if layout == "compact" else 78
    x = (1920 - width) // 2
    y = 1080 - height - 28
    icon = 38 if layout == "compact" else 48
    gap = 18 if layout == "compact" else 24
    items = []
    for index in range(8):
        item_x = x + 28 + index * (icon + gap)
        fill = colors["violet"] if index == 0 else colors["elevated"]
        items.append(f'<rect x="{item_x}" y="{y + (height-icon)//2}" width="{icon}" height="{icon}" rx="12" fill="{fill}"/><circle cx="{item_x + icon/2}" cy="{y + height - 7}" r="2.5" fill="{colors["sky"]}"/>')
    return f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="24" fill="{colors["surface"]}" fill-opacity=".94" stroke="{colors["border"]}"/>{"".join(items)}'


def palette_surface(colors: dict[str, str]) -> str:
    rows = []
    entries = [("Open Files", "Open"), ("Search Everything", "Open"), ("System Settings", "Open"), ("Switch to Character Mode", "Change setting"), ("Open Approval Center", "Requires approval")]
    for index, (label, action) in enumerate(entries):
        y = 388 + index * 64
        rows.append(f'<rect x="596" y="{y}" width="728" height="52" rx="12" fill="{colors["elevated"]}"/><text x="620" y="{y+32}" class="body">{escape(label)}</text><text x="1190" y="{y+32}" class="caption">{escape(action)}</text>')
    return f'''<rect x="570" y="270" width="780" height="510" rx="24" fill="{colors['deep']}" fill-opacity=".96" stroke="{colors['violet']}" stroke-opacity=".6"/><text x="606" y="320" class="title">Bunny Command Palette</text><rect x="596" y="338" width="728" height="54" rx="12" fill="{colors['surface']}" stroke="{colors['focus']}"/><text x="620" y="372" class="muted">Open, switch, or change…</text>{''.join(rows)}'''


def quick_panel(colors: dict[str, str], compact: bool) -> str:
    width = 370 if compact else 420
    x = 1920 - width - 24
    cards = []
    values = [("Wi-Fi", "Home Network"), ("Bluetooth", "On"), ("Focus", "Default"), ("Privacy", "Local Only"), ("Dark Mode", "On"), ("Character Mode", "Off")]
    columns = 1 if compact else 2
    card_width = width - 48 if columns == 1 else (width - 60) // 2
    for index, (label, value) in enumerate(values):
        column, row = index % columns, index // columns
        card_x = x + 24 + column * (card_width + 12)
        card_y = 158 + row * 92
        cards.append(f'<rect x="{card_x}" y="{card_y}" width="{card_width}" height="78" rx="14" fill="{colors["elevated"]}"/><text x="{card_x+18}" y="{card_y+31}" class="body">{label}</text><text x="{card_x+18}" y="{card_y+55}" class="caption">{value}</text>')
    bottom = 158 + ((len(values) + columns - 1) // columns) * 92
    return f'''<rect x="{x}" y="72" width="{width}" height="900" rx="24" fill="{colors['deep']}" fill-opacity=".96" stroke="{colors['border']}"/><text x="{x+28}" y="122" class="title">Bunny OS</text>{''.join(cards)}<rect x="{x+24}" y="{bottom+4}" width="{width-48}" height="112" rx="16" fill="{colors['elevated']}"/><text x="{x+44}" y="{bottom+42}" class="heading">Output</text><text x="{x+44}" y="{bottom+74}" class="muted">Speakers · 72%</text><rect x="{x+24}" y="{bottom+130}" width="{width-48}" height="82" rx="16" fill="{colors['elevated']}"/><text x="{x+44}" y="{bottom+164}" class="body">Updates</text><text x="{x+44}" y="{bottom+190}" class="caption">System is up to date</text>'''


def assistant_panel(colors: dict[str, str], scenario: dict) -> str:
    width, x = 420, 1476
    state = scenario.get("state", "Ready")
    pose = scenario.get("pose")
    header = f'<rect x="{x}" y="72" width="{width}" height="940" rx="24" fill="{colors["deep"]}" fill-opacity=".96" stroke="{colors["border"]}"/><text x="{x+28}" y="122" class="title">Assistant</text><text x="{x+28}" y="151" class="caption">{escape(state)} · Local Only</text>'
    if scenario["mode"] == "regular" or not pose:
        titles = ["Recent activity", "System context", "Suggested actions", "Privacy summary"]
        bodies = ["Reviewed update plan", "Connectivity · Online", "Open Diagnostics", "Local Only · no active devices"]
        cards = []
        for index, (title, body) in enumerate(zip(titles, bodies)):
            y = 180 + index * 154
            cards.append(f'<rect x="{x+24}" y="{y}" width="{width-48}" height="132" rx="16" fill="{colors["elevated"]}"/><text x="{x+44}" y="{y+38}" class="heading">{title}</text><text x="{x+44}" y="{y+76}" class="body">{body}</text><text x="{x+44}" y="{y+104}" class="caption">Observed state · no action executed</text>')
        visual = "".join(cards)
    else:
        message_one = "An action needs your approval." if state == "Waiting for approval" else "I can help with tasks and explain"
        message_two = "Review the exact controls below." if state == "Waiting for approval" else "observed system state."
        image = f'../../assets/character/bunny-guide/v1/{pose}.png'
        visual = f'<rect x="{x+24}" y="180" width="{width-48}" height="150" rx="16" fill="{colors["elevated"]}"/><text x="{x+44}" y="220" class="heading">Bunny guidance</text><text x="{x+44}" y="255" class="body">{escape(message_one)}</text><text x="{x+44}" y="282" class="body">{escape(message_two)}</text><text x="{x+44}" y="310" class="caption">The real controls remain separate.</text><image href="{image}" x="{x+70}" y="342" width="280" height="570" preserveAspectRatio="xMidYMid meet"/>'
    return header + visual + f'<rect x="{x+24}" y="934" width="{width-48}" height="54" rx="14" fill="{colors["surface"]}" stroke="{colors["border"]}"/><text x="{x+44}" y="968" class="muted">Ask Bunny…</text>'


def approval_panel(colors: dict[str, str], scenario: dict) -> str:
    x, width = (1376, 520) if scenario["mode"] == "character" else (1430, 466)
    fields = [("Application", "Bunny Updates"), ("Operation", "Install update preview"), ("Resources", "Preview package set"), ("Privilege", "Privileged"), ("Network", "Downloads packages"), ("Data", "Changes preview packages"), ("Reversible", "Separate rollback"), ("Expires", "10 minutes")]
    if scenario["mode"] == "character":
        rows = ''.join(f'<text x="{x+44}" y="{314+i*37}" class="body">{label}: {value}</text>' for i, (label, value) in enumerate(fields))
        image = '../../assets/character/bunny-guide/v1/requesting-approval.png'
        return f'''<rect x="{x}" y="72" width="{width}" height="920" rx="24" fill="{colors['deep']}" fill-opacity=".97" stroke="{colors['border']}"/><text x="{x+28}" y="122" class="title">Approval Center</text><rect x="{x+24}" y="150" width="{width-48}" height="112" rx="16" fill="{colors['elevated']}"/><text x="{x+44}" y="188" class="heading">Approval requires your decision</text><text x="{x+44}" y="220" class="caption">The guide explains; native controls decide.</text><rect x="{x+24}" y="278" width="{width-48}" height="324" rx="16" fill="{colors['elevated']}"/>{rows}<rect x="{x+24}" y="620" width="130" height="50" rx="12" fill="{colors['surface']}" stroke="{colors['focus']}"/><text x="{x+42}" y="651" class="body">Inspect details</text><rect x="{x+172}" y="620" width="94" height="50" rx="12" fill="{colors['surface']}"/><text x="{x+202}" y="651" class="body">Deny</text><rect x="{x+284}" y="620" width="110" height="50" rx="12" fill="{colors['violet']}"/><text x="{x+308}" y="651" class="body">Approve</text><image href="{image}" x="{x+145}" y="678" width="230" height="290" preserveAspectRatio="xMidYMid meet"/>'''
    rows = ''.join(f'<text x="{x+48}" y="{244+i*48}" class="body">{label}: {value}</text>' for i, (label, value) in enumerate(fields))
    return f'''<rect x="{x}" y="72" width="{width}" height="920" rx="24" fill="{colors['deep']}" fill-opacity=".97" stroke="{colors['border']}"/><text x="{x+28}" y="122" class="title">Approval Center</text><text x="{x+28}" y="164" class="warning">PRIVILEGED · APPROVAL REQUIRED</text><rect x="{x+24}" y="190" width="{width-48}" height="480" rx="16" fill="{colors['elevated']}"/>{rows}<rect x="{x+24}" y="700" width="130" height="50" rx="12" fill="{colors['surface']}" stroke="{colors['focus']}"/><text x="{x+42}" y="731" class="body">Inspect details</text><rect x="{x+172}" y="700" width="94" height="50" rx="12" fill="{colors['surface']}"/><text x="{x+202}" y="731" class="body">Deny</text><rect x="{x+284}" y="700" width="110" height="50" rx="12" fill="{colors['violet']}"/><text x="{x+308}" y="731" class="body">Approve</text>'''


def render(scenario: dict) -> str:
    colors = palette(scenario["theme"])
    surface = scenario["surface"]
    middle = ""
    if surface == "palette":
        middle = palette_surface(colors)
    elif surface == "quick":
        middle = quick_panel(colors, scenario["layout"] == "compact")
    elif surface in {"assistant", "welcome", "privacy"}:
        middle = assistant_panel(colors, scenario)
    elif surface == "approval":
        middle = approval_panel(colors, scenario)
    title = escape(scenario["id"])
    mock = "VISUAL MOCK DATA · review artifact only"
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080" viewBox="0 0 1920 1080">
  <title>{title} — Bunny Desktop Visual V2 mock review</title>
  <style>.title{{fill:{colors['text']};font:600 24px 'Adwaita Sans',sans-serif}}.heading{{fill:{colors['text']};font:600 18px 'Adwaita Sans',sans-serif}}.body{{fill:{colors['text']};font:15px 'Adwaita Sans',sans-serif}}.label{{fill:{colors['text']};font:500 13px 'Adwaita Sans',sans-serif}}.caption,.muted{{fill:{colors['muted']};font:13px 'Adwaita Sans',sans-serif}}.warning{{fill:{colors['warning']};font:600 14px 'Adwaita Sans',sans-serif}}</style>
  <rect width="1920" height="1080" fill="{colors['background']}"/>
  <path d="M-80 980 C 40 180, 470 20, 790 1030" fill="none" stroke="{colors['violet']}" stroke-opacity=".22" stroke-width="128" stroke-linecap="round"/>
  <path d="M2000 980 C 1880 180, 1450 20, 1130 1030" fill="none" stroke="{colors['sky']}" stroke-opacity=".18" stroke-width="128" stroke-linecap="round"/>
{top_bar(colors, scenario['layout'])}
{middle}
{dock(colors, scenario['layout'])}
  <rect x="24" y="1020" width="360" height="36" rx="10" fill="{colors['warning']}"/><text x="42" y="1044" fill="{colors['background']}" font-family="Adwaita Sans,sans-serif" font-size="13" font-weight="700">{mock}</text>
</svg>
'''


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    data = json.loads(SCENARIOS.read_text(encoding="utf-8"))
    OUTPUT.mkdir(parents=True, exist_ok=True)
    mismatches = []
    for scenario in data["scenarios"]:
        target = OUTPUT / f"{scenario['id']}.svg"
        value = render(scenario)
        if args.check:
            if not target.is_file() or target.read_text(encoding="utf-8") != value:
                mismatches.append(target.name)
        else:
            target.write_text(value, encoding="utf-8", newline="\n")
    if mismatches:
        print("Screenshot mismatch: " + ", ".join(mismatches))
        return 1
    print(f"Verified {len(data['scenarios'])} deterministic Visual V2 screenshots" if args.check else f"Rendered {len(data['scenarios'])} deterministic Visual V2 screenshots")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
