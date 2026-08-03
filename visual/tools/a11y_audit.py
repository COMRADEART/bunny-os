#!/usr/bin/python3
"""Run the deterministic source-level accessibility baseline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from layout_model import SUPPORTED_VIEWPORTS, surface_bounds


ROOT = Path(__file__).resolve().parents[2]


def audit() -> dict[str, object]:
    shell_sources = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "shell/bunny-shell-extension/components").glob("*.js"))
    gtk_source = (ROOT / "apps/common/bunny_visual/application.py").read_text(encoding="utf-8")
    css = (ROOT / "shell/bunny-shell-extension/stylesheet.css").read_text(encoding="utf-8")
    checks = {
        "keyboard_escape": "KEY_Escape" in shell_sources,
        "keyboard_navigation": all(key in shell_sources for key in ("KEY_Down", "KEY_Up", "KEY_Return")),
        "accessible_names": "accessible_name" in shell_sources and "AccessibleProperty.LABEL" in gtk_source,
        "visible_focus": ":focus" in css and "2px" in css,
        "reduced_motion": "bunny-v1-reduced-motion" in css and "reducedMotion" in shell_sources,
        "critical_neutral_focus": "inspect.grab_focus()" in gtk_source,
        "focus_exit": "Exit FocusMode" in shell_sources,
        "supported_viewports": all(
            all(width > 0 and height > 0 and width <= viewport.width and height <= viewport.height
                for width, height in surface_bounds(viewport, mode).values())
            for viewport in SUPPORTED_VIEWPORTS for mode in ("normal", "compact", "focus")
        ),
    }
    return {
        "schemaVersion": 1,
        "scope": "source-level baseline; runtime AT-SPI/Orca validation remains required",
        "checks": checks,
        "passed": all(checks.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit()
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8", newline="\n")
    else:
        print(encoded, end="")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
