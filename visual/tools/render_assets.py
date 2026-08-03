#!/usr/bin/python3
"""Render original wallpaper, icon, and deterministic screenshot SVG assets."""

from __future__ import annotations

import argparse
from hashlib import sha256
from html import escape
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build" / "visual"


def write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


def wallpaper_svg(title: str, colors: list[str], composition: str, width: int, height: int) -> str:
    background, surface, accent, secondary = colors
    cx, cy = int(width * 0.78), int(height * 0.52)
    span = int(min(width, height) * 0.33)
    patterns = {
        "nested-arcs": f'<path d="M{cx-span} {int(height*.12)}c0 {int(height*.45)} {int(width*.09)} {int(height*.68)} {span} {int(height*.82)}M{cx+span} {int(height*.12)}c0 {int(height*.45)} {int(-width*.09)} {int(height*.68)} {-span} {int(height*.82)}"/>',
        "rising-horizon": f'<path d="M{int(width*.42)} {int(height*.9)}Q{int(width*.67)} {int(height*.28)} {int(width*.94)} {int(height*.14)}M{int(width*.50)} {int(height*.94)}Q{int(width*.72)} {int(height*.38)} {int(width*.98)} {int(height*.24)}"/>',
        "soft-bands": f'<path d="M{int(width*.35)} {int(height*.84)}C{int(width*.52)} {int(height*.52)} {int(width*.65)} {int(height*.62)} {int(width*.98)} {int(height*.3)}M{int(width*.48)} {int(height*.94)}C{int(width*.64)} {int(height*.66)} {int(width*.78)} {int(height*.74)} {int(width*1.05)} {int(height*.5)}"/>',
        "paired-horizon": f'<path d="M{int(width*.32)} {int(height*.72)}Q{int(width*.64)} {int(height*.42)} {int(width*.98)} {int(height*.54)}M{int(width*.38)} {int(height*.82)}Q{int(width*.68)} {int(height*.53)} {int(width*1.02)} {int(height*.64)}"/>',
        "focus-channel": f'<path d="M{int(width*.62)} {int(height*.05)}Q{int(width*.65)} {int(height*.5)} {int(width*.76)} {int(height*.95)}M{int(width*.94)} {int(height*.05)}Q{int(width*.91)} {int(height*.5)} {int(width*.80)} {int(height*.95)}"/>',
        "single-mark": f'<path d="M{cx-int(span*.55)} {cy-int(span*.7)}c0 {span} {int(span*.2)} {int(span*1.35)} {int(span*.55)} {int(span*1.65)}M{cx+int(span*.55)} {cy-int(span*.7)}c0 {span} {int(-span*.2)} {int(span*1.35)} {int(-span*.55)} {int(span*1.65)}"/>',
    }
    pattern = patterns[composition]
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <title>{escape(title)}</title>
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop stop-color="{background}"/><stop offset="1" stop-color="{surface}"/></linearGradient>
    <linearGradient id="arc" x1="0" y1="0" x2="1" y2="1"><stop stop-color="{accent}"/><stop offset="1" stop-color="{secondary}"/></linearGradient>
  </defs>
  <rect width="{width}" height="{height}" fill="url(#bg)"/>
  <ellipse cx="{int(width*.84)}" cy="{int(height*.44)}" rx="{int(width*.28)}" ry="{int(height*.42)}" fill="{accent}" opacity=".035"/>
  <g fill="none" stroke="url(#arc)" stroke-width="{max(10, int(min(width,height)*.012))}" stroke-linecap="round" opacity=".46">{pattern}</g>
  <circle cx="{int(width*.92)}" cy="{int(height*.12)}" r="{max(3, int(min(width,height)*.004))}" fill="{secondary}" opacity=".5"/>
</svg>
'''


SYMBOL_PATHS = {
    "bunny-command": "M3 4h10v7H8l-3 3v-3H3zM5 7h6M5 9h4",
    "bunny-assistant": "M4 3h8v8H8l-3 3v-3H4zM6 6h4M6 8h3",
    "bunny-approval": "M8 2l5 2v4c0 3-2 5-5 6-3-1-5-3-5-6V4zM6 8l1.3 1.3L10.5 6",
    "bunny-diagnostics": "M3 12l3-4 2 2 3-6 2 8M3 13h10",
    "bunny-privacy": "M4 7V5a4 4 0 018 0v2M3 7h10v7H3z",
    "bunny-layout": "M2 3h5v4H2zM9 3h5v8H9zM2 9h5v4H2z",
}


def symbolic_svg(name: str) -> str:
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">
  <title>{escape(name.replace('-', ' ').title())}</title>
  <path d="{SYMBOL_PATHS[name]}" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
'''


def application_svg(name: str) -> str:
    symbol = {
        "bunny-control-center": "bunny-layout", "bunny-assistant": "bunny-assistant",
        "bunny-approval-center": "bunny-approval", "bunny-diagnostics": "bunny-diagnostics",
        "bunny-welcome": "bunny-command",
    }[name]
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">
  <title>{escape(name.replace('-', ' ').title())}</title>
  <defs><linearGradient id="g" x2="1" y2="1"><stop stop-color="#8B7CFF"/><stop offset="1" stop-color="#65C7F7"/></linearGradient></defs>
  <rect x="12" y="12" width="232" height="232" rx="54" fill="#151821"/>
  <circle cx="128" cy="128" r="76" fill="url(#g)" opacity=".94"/>
  <g transform="translate(48 48) scale(10)" color="#0C0E14"><path d="{SYMBOL_PATHS[symbol]}" fill="none" stroke="currentColor" stroke-width="1.35" stroke-linecap="round" stroke-linejoin="round"/></g>
</svg>
'''


def screenshot_svg(scenario: dict[str, object]) -> str:
    light = scenario["theme"] == "light"
    high = scenario["theme"] == "high"
    bg = "#F4F4F2" if light else "#000000" if high else "#0C0E14"
    surface = "#FFFFFF" if light else "#000000" if high else "#151821"
    elevated = "#E7E9EE" if light else "#151515" if high else "#1D2130"
    text = "#171923" if light else "#FFFFFF" if high else "#F4F4F2"
    muted = "#545B6B" if light else "#FFFFFF" if high else "#B9BFCC"
    accent = "#5948CC" if light else "#D7D0FF" if high else "#8B7CFF"
    focus = "#245E7A" if light else "#7FDBFF" if high else "#65C7F7"
    border = ' stroke="#FFFFFF" stroke-width="3"' if high else ''
    title = escape(str(scenario["title"]))
    mode = escape(str(scenario["mode"]))
    provider = escape(str(scenario.get("provider", "local")))
    surface_kind = scenario["surface"]
    main = ''
    if surface_kind in {"windows", "overview"}:
        main += f'<rect x="280" y="150" width="780" height="570" rx="22" fill="{surface}"{border}/><rect x="315" y="205" width="710" height="32" rx="8" fill="{elevated}"/><rect x="315" y="270" width="330" height="390" rx="16" fill="{elevated}"/><rect x="675" y="270" width="350" height="180" rx="16" fill="{elevated}"/>'
    if surface_kind == "overview":
        main += f'<rect x="32" y="78" width="360" height="720" rx="22" fill="{surface}"{border}/><text x="62" y="126" class="heading">Bunny overview</text><rect x="62" y="156" width="300" height="54" rx="9" fill="{elevated}"/><text x="82" y="190" class="muted">Search applications and windows</text>'
    if surface_kind == "palette":
        main += f'<rect x="410" y="160" width="780" height="590" rx="24" fill="{surface}"{border}/><text x="452" y="215" class="title">Bunny Command Palette</text><rect x="452" y="246" width="696" height="64" rx="10" fill="{elevated}" stroke="{focus}" stroke-width="2"/><text x="478" y="286" class="muted">Open, switch, or change…</text>' + ''.join(f'<rect x="452" y="{338+i*76}" width="696" height="62" rx="10" fill="{elevated}"/><text x="476" y="{376+i*76}" class="body">{label}</text><text x="1050" y="{376+i*76}" class="badge">{verb}</text>' for i, (label, verb) in enumerate([('Files','opens'),('Workspace 2','switches'),('Layout mode','changes'),('Approval Center','requires approval')]))
    if surface_kind in {"assistant", "approval", "critical", "quick", "notifications"}:
        width = 520 if surface_kind in {"approval", "critical"} else 430
        x = 1600 - width - 24
        heading = {"assistant": "Bunny Assistant", "approval": "Approval Center", "critical": "Critical approval", "quick": "Quick Settings", "notifications": "Notification Center"}[surface_kind]
        main += f'<rect x="{x}" y="72" width="{width}" height="780" rx="24" fill="{surface}"{border}/><text x="{x+32}" y="126" class="title">{heading}</text>'
        if surface_kind == "assistant":
            main += f'<text x="{x+32}" y="170" class="badge">Provider: {provider}</text>' + ''.join(f'<rect x="{x+28}" y="{200+i*112}" width="{width-56}" height="88" rx="16" fill="{elevated}"/><text x="{x+48}" y="{234+i*112}" class="muted">{label}</text><text x="{x+48}" y="{266+i*112}" class="body">{body}</text>' for i, (label, body) in enumerate([('CURRENT TASK','Organize project notes · running'),('PLAN','Apply approved changes · waiting'),('TOOL ACTIVITY','Move proposal · approval required'),('RESULT HISTORY','12 folders reviewed · complete')]))
        elif surface_kind in {"approval", "critical"}:
            severity = "CRITICAL" if surface_kind == "critical" else "SENSITIVE"
            main += f'<text x="{x+32}" y="174" fill="#EF6A72" font-size="18" font-weight="600">⚠ {severity} APPROVAL</text><rect x="{x+28}" y="202" width="{width-56}" height="430" rx="16" fill="{elevated}" stroke="#EF6A72" stroke-width="2"/>' + ''.join(f'<text x="{x+48}" y="{244+i*44}" class="body">{label}: {value}</text>' for i, (label, value) in enumerate([('Component','Bunny Assistant'),('Operation','Move 8 files'),('Resources','~/Documents/Research'),('Privilege','User files'),('Network','None'),('Data','Changes locations'),('Reversible','Yes'),('Expires','10 minutes')])) + f'<rect x="{x+158}" y="670" width="128" height="52" rx="9" fill="{elevated}" stroke="{focus}" stroke-width="2"/><text x="{x+178}" y="703" class="body">Inspect details</text><rect x="{x+304}" y="670" width="86" height="52" rx="9" fill="{elevated}"/><text x="{x+326}" y="703" class="body">Deny</text><rect x="{x+404}" y="670" width="88" height="52" rx="9" fill="{accent}"/><text x="{x+420}" y="703" fill="{bg}" font-size="15" font-weight="600">Approve</text>'
        else:
            main += ''.join(f'<rect x="{x+28}" y="{170+i*78}" width="{width-56}" height="60" rx="12" fill="{elevated}"/><text x="{x+50}" y="{207+i*78}" class="body">{label}</text>' for i, label in enumerate(['Privacy use visible','Wi-Fi and Bluetooth','Audio and microphone','FocusMode','Bunny activity state','Accessibility']))
    dock = '' if scenario["mode"] == "focus" else f'<rect x="550" y="804" width="500" height="68" rx="26" fill="{surface}"{border}/>' + ''.join(f'<rect x="{575+i*66}" y="816" width="44" height="44" rx="10" fill="{accent if i==2 else elevated}"/>' for i in range(7))
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900" viewBox="0 0 1600 900">
  <title>{title} — Bunny Visual V1 mock review</title>
  <style>.title{{fill:{text};font:600 25px 'Adwaita Sans',sans-serif}}.heading{{fill:{text};font:600 20px 'Adwaita Sans',sans-serif}}.body{{fill:{text};font:15px 'Adwaita Sans',sans-serif}}.muted{{fill:{muted};font:13px 'Adwaita Sans',sans-serif}}.badge{{fill:{focus};font:600 12px 'Adwaita Sans',sans-serif}}</style>
  <rect width="1600" height="900" fill="{bg}"/>
  <path d="M1190 90c0 310 80 520 275 710M1500 90c0 310-80 520-275 710" fill="none" stroke="{accent}" stroke-opacity=".12" stroke-width="18" stroke-linecap="round"/>
  <rect width="1600" height="42" fill="{surface}"{border}/><text x="22" y="28" class="body">◡ Bunny</text><text x="716" y="28" class="body">Workspace 1 · {mode}</text><text x="1420" y="28" class="body">Privacy · 10:24</text>
  {main}{dock}
  <rect x="20" y="852" width="420" height="32" rx="9" fill="#F0B65A"/><text x="34" y="874" fill="#0C0E14" font-family="Adwaita Sans,sans-serif" font-size="13" font-weight="600">VISUAL MOCK DATA · {title}</text>
</svg>
'''


def render_wallpapers() -> list[Path]:
    data = json.loads((ROOT / "visual/assets/wallpapers/wallpapers.json").read_text(encoding="utf-8"))
    outputs = []
    for family, definition in data["families"].items():
        for theme in ("light", "dark"):
            for size_name, (width, height) in data["sizes"].items():
                target = BUILD / "wallpapers" / f"{family}-{theme}-{size_name}.svg"
                write(target, wallpaper_svg(f"{definition['title']} · {theme} · {size_name}", definition[theme], definition["composition"], width, height))
                outputs.append(target)
    return outputs


def render_icons() -> list[Path]:
    data = json.loads((ROOT / "visual/assets/icons/icons.json").read_text(encoding="utf-8"))
    outputs = []
    for name in data["symbolic"]:
        target = BUILD / "icons" / "symbolic" / f"{name}-symbolic.svg"
        write(target, symbolic_svg(name)); outputs.append(target)
    for name in data["applications"]:
        target = BUILD / "icons" / "apps" / f"{name}.svg"
        write(target, application_svg(name)); outputs.append(target)
    return outputs


def render_screenshots() -> list[Path]:
    data = json.loads((ROOT / "visual/screenshots/scenarios.json").read_text(encoding="utf-8"))
    outputs = []
    for scenario in data["scenarios"]:
        target = BUILD / "screenshots" / f"{scenario['id']}.svg"
        write(target, screenshot_svg(scenario)); outputs.append(target)
    return outputs


def write_manifest(paths: list[Path], target: Path) -> None:
    records = [{"path": str(path.relative_to(ROOT)).replace('\\', '/'), "sha256": sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size} for path in sorted(paths)]
    write(target, json.dumps({"schemaVersion": 1, "artifacts": records}, indent=2, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=("wallpapers", "icons", "screenshots", "all"), default="all", nargs="?")
    args = parser.parse_args()
    outputs: list[Path] = []
    if args.kind in {"wallpapers", "all"}:
        outputs.extend(render_wallpapers())
    if args.kind in {"icons", "all"}:
        outputs.extend(render_icons())
    if args.kind in {"screenshots", "all"}:
        outputs.extend(render_screenshots())
    write_manifest(outputs, BUILD / f"{args.kind}-manifest.json")
    print(f"Rendered {len(outputs)} deterministic SVG artifacts under {BUILD.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
