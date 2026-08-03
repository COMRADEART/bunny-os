#!/usr/bin/env python3
"""Deterministic source/layout accessibility audit for Visual V2."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def audit() -> dict:
    app = (ROOT / "apps/common/bunny_visual_v2/application.py").read_text(encoding="utf-8")
    character = (ROOT / "shell/bunny-desktop-v2/components/characterIllustration.js").read_text(encoding="utf-8")
    css = (ROOT / "shell/bunny-desktop-v2/stylesheet.css").read_text(encoding="utf-8")
    layout = json.loads((ROOT / "visual-v2/tokens/layout.json").read_text(encoding="utf-8"))["tokens"]
    viewports = [(1366, 768, 1), (1920, 1080, 1), (2560, 1440, 1), (3840, 2160, 2)]
    fits = []
    for physical_width, physical_height, scale in viewports:
        width, height = physical_width // scale, physical_height // scale
        panel_width = min(layout["panelMaximumWidth"], max(layout["panelMinimumWidth"], width - 96))
        panel_height = max(layout["panelMinimumHeight"], height - layout["topOffset"] - 32)
        fits.append({
            "physical": [physical_width, physical_height],
            "scale": scale,
            "logical": [width, height],
            "panel": [panel_width, panel_height],
            "fits": panel_width < width and panel_height <= height,
        })
    checks = {
        "keyboardLabels": "AccessibleProperty.LABEL" in app and "can_focus: true" in (ROOT / "shell/bunny-desktop-v2/components/commandPalette.js").read_text(encoding="utf-8"),
        "decorativeCharacterHidden": "Atk.Role.REDUNDANT_OBJECT" in character,
        "semanticCharacterContainer": "descriptionForPose(pose)" in character,
        "highContrast": "bunny-v2-high-contrast" in css,
        "reducedMotion": "transition-duration: 0ms" in css,
        "criticalApprovalConfirmation": "irreversible consequences" in app and "approve.set_sensitive(False)" in app,
        "allViewportsFit": all(item["fits"] for item in fits),
    }
    return {
        "schemaVersion": 1,
        "notice": "VISUAL PROTOTYPE ONLY — NOT RELEASE QUALIFIED — DO NOT MERGE INTO MAIN",
        "checks": checks,
        "viewports": fits,
        "passed": all(checks.values()),
        "liveOrcaTested": False,
        "realGnomeSessionTested": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(args.output)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
