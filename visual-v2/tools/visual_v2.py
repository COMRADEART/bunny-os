#!/usr/bin/env python3
"""Developer entry point for Bunny Desktop Visual Phase V2.

VISUAL PROTOTYPE ONLY — NOT RELEASE QUALIFIED — DO NOT MERGE INTO MAIN.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build" / "visual-v2"
NOTICE = "VISUAL PROTOTYPE ONLY — NOT RELEASE QUALIFIED — DO NOT MERGE INTO MAIN"


def run(argv: list[str], *, env: dict[str, str] | None = None) -> None:
    subprocess.run(argv, cwd=ROOT, env=env, check=True)


def setup() -> int:
    BUILD.mkdir(parents=True, exist_ok=True)
    tools = {
        name: shutil.which(name)
        for name in ("gnome-shell", "gnome-session", "dbus-run-session", "glib-compile-schemas")
    }
    (BUILD / "setup.json").write_text(
        json.dumps({"schemaVersion": 1, "notice": NOTICE, "hostPlatform": sys.platform, "tools": tools}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(NOTICE)
    print(f"Prepared {BUILD}")
    return 0


def validate_json() -> None:
    for path in sorted((ROOT / "visual-v2").rglob("*.json")):
        json.loads(path.read_text(encoding="utf-8"))
    for path in sorted((ROOT / "shell" / "bunny-desktop-v2").rglob("*.json")):
        json.loads(path.read_text(encoding="utf-8"))
    json.loads((ROOT / "sessions" / "bunny-desktop-preview.json").read_text(encoding="utf-8"))


def build() -> int:
    setup()
    validate_json()
    run([sys.executable, str(ROOT / "visual-v2/tools/generate_css.py"), "--check"])
    run([sys.executable, str(ROOT / "visual-v2/tools/generate_gtk_css.py"), "--check"])
    run([sys.executable, str(ROOT / "visual-v2/tools/render_wallpapers.py"), "--check"])
    print("Design tokens, generated CSS, and static wallpaper assets are current")
    return 0


def unavailable(command: str) -> int:
    print(f"{command} is introduced by a later V2 implementation commit", file=sys.stderr)
    return 2


def clean() -> int:
    resolved = BUILD.resolve()
    expected = (ROOT / "build" / "visual-v2").resolve()
    if resolved != expected:
        raise RuntimeError("refusing to clean an unexpected path")
    if resolved.exists():
        shutil.rmtree(resolved)
    print(f"Removed {resolved}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("setup", "build", "preview", "preview-nested", "test", "a11y", "screenshots", "package", "clean"))
    command = parser.parse_args().command
    if command == "setup":
        return setup()
    if command == "build":
        return build()
    if command == "clean":
        return clean()
    return unavailable(command)


if __name__ == "__main__":
    raise SystemExit(main())
