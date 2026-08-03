#!/usr/bin/env python3
"""Static and deterministic performance checks for Visual V2."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import time


ROOT = Path(__file__).resolve().parents[2]


def audit() -> dict:
    started = time.perf_counter()
    sources = "\n".join(path.read_text(encoding="utf-8") for path in sorted((ROOT / "shell/bunny-desktop-v2").rglob("*.js")))
    loader = (ROOT / "shell/bunny-desktop-v2/services/characterAssetLoader.js").read_text(encoding="utf-8")
    checks = {
        "noTimerPolling": not re.search(r"setInterval|timeout_add|setTimeout", sources),
        "eventDrivenState": "monitor_directory" in (ROOT / "shell/bunny-desktop-v2/services/state.js").read_text(encoding="utf-8"),
        "boundedCharacterCache": "MAX_CACHE_ENTRIES = 3" in loader and "while (this._cache.size > MAX_CACHE_ENTRIES)" in loader,
        "lazyCharacterLoader": "this._loader = null" in sources and "this._loader ??= new CharacterAssetLoader" in sources,
        "noContinuousCharacterAnimation": "character-entrance" not in sources,
    }
    elapsed = round((time.perf_counter() - started) * 1000, 3)
    return {
        "schemaVersion": 1,
        "notice": "VISUAL PROTOTYPE ONLY — NOT RELEASE QUALIFIED — DO NOT MERGE INTO MAIN",
        "checks": checks,
        "staticAuditMilliseconds": elapsed,
        "passed": all(checks.values()),
        "targetsMilliseconds": {"commandPalette": 150, "quickSettings": 150, "assistantPanel": 250, "visualModeSwitch": 300},
        "liveShellMeasurementsAvailable": False,
        "idleCpuMeasured": False,
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
